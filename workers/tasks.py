"""
Celery task definitions — one per pipeline stage + orchestrator + resumability.

Each stage task:
  - Is idempotent (safe to retry or resume from any point)
  - Reads project/clip state from PostgreSQL and MinIO
  - Updates Job & Project state in PostgreSQL
  - Publishes progress events to Redis (consumed by SSE)
  - Writes results back to PostgreSQL and MinIO
  - Retries up to 3× with exponential backoff on failure

Backoff schedule: attempt 0→1: 60s, 1→2: 300s, 2→3: 900s
"""
from __future__ import annotations

import logging
import os
import sys
import tempfile
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Ensure project root (/app) is on sys.path so `import api.*` works in all worker processes
_ROOT_DIR = str(Path(__file__).resolve().parent.parent)
if _ROOT_DIR not in sys.path:
    sys.path.insert(0, _ROOT_DIR)

from celery import chain, group
from celery.utils.log import get_task_logger
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from workers.celery_app import celery_app, GPU_QUEUE

logger = get_task_logger(__name__)

# ── Synchronous DB helper ─────────────────────────────────────────────────────
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+psycopg2://video2reels:video2reels@localhost:5432/video2reels",
).replace("+asyncpg", "+psycopg2")

_engine = None
_Session = None


def _get_session() -> Session:
    """Lazy-initialise a synchronous SQLAlchemy session (PostgreSQL primary, SQLite fallback)."""
    global _engine, _Session
    if _Session is None:
        import socket
        db_url = DATABASE_URL
        reachable = False
        for candidate_url in (db_url, db_url.replace("@postgres:", "@localhost:")):
            try:
                host_port = candidate_url.split("@")[-1].split("/")[0]
                host = host_port.split(":")[0]
                port = int(host_port.split(":")[1]) if ":" in host_port else 5432
                sock = socket.socket()
                sock.settimeout(0.5)
                if sock.connect_ex((host, port)) == 0:
                    reachable = True
                    db_url = candidate_url
                    sock.close()
                    break
                sock.close()
            except Exception:
                pass

        if reachable:
            _engine = create_engine(db_url, pool_pre_ping=True, pool_size=5)
        else:
            from api.db import Base
            db_path = Path(_ROOT_DIR) / "work" / "video2reels_local.db"
            db_path.parent.mkdir(parents=True, exist_ok=True)
            _engine = create_engine(
                f"sqlite:///{db_path}",
                connect_args={"check_same_thread": False},
            )
            Base.metadata.create_all(_engine)
        _Session = sessionmaker(bind=_engine)
    return _Session()


def _backoff(attempt: int) -> int:
    """Exponential backoff: 60 → 300 → 900 seconds."""
    return [60, 300, 900][min(attempt, 2)]


# ── State and Progress Helpers ────────────────────────────────────────────────

def _emit(project_id: str, stage: str, progress: int, message: str = "", **extra):
    """Publish real-time SSE progress to Redis pub/sub."""
    from api.events import publish_progress_sync
    try:
        publish_progress_sync(project_id, stage, progress, message, **extra)
    except Exception as exc:
        logger.debug("Failed to publish SSE event: %s", exc)


def _update_job_status(
    project_id: str,
    stage: str,
    status_val: Any,
    progress: int,
    error: str | None = None,
    attempts: int = 0,
):
    """Persist job state directly in PostgreSQL."""
    from api.models import Job
    try:
        with _get_session() as db:
            job = db.execute(
                select(Job).where(Job.project_id == uuid.UUID(project_id))
            ).scalars().first()
            if not job:
                job = Job(project_id=uuid.UUID(project_id))
                db.add(job)
            job.stage = stage
            job.status = status_val
            job.progress = progress
            if attempts > 0:
                job.attempts = attempts
            if error is not None:
                job.error = error
            now = datetime.now(timezone.utc)
            if status_val.value == "running" and not job.started_at:
                job.started_at = now
            elif status_val.value in ("done", "failed"):
                job.finished_at = now
            db.commit()
    except Exception as exc:
        logger.warning("Could not update job status in DB: %s", exc)


def _update_project_status(project_id: str, status_val: Any):
    """Update project status in PostgreSQL."""
    from api.models import Project
    try:
        with _get_session() as db:
            proj = db.get(Project, uuid.UUID(project_id))
            if proj:
                proj.status = status_val
                db.commit()
    except Exception as exc:
        logger.warning("Could not update project status in DB: %s", exc)


# ── Pipeline Orchestrators ───────────────────────────────────────────────────

@celery_app.task(
    name="workers.tasks.run_pipeline",
    bind=True,
    max_retries=0,
    queue="cpu",
)
def run_pipeline(
    self,
    project_id: str,
    video_storage_key: str,
    user_prompt: str | None = None,
):
    """
    Kick off the full 6-stage pipeline as a Celery chain.
    """
    logger.info("[pipeline] Starting project %s", project_id)
    ingest_sig = (
        stage_ingest.s(project_id, video_storage_key, user_prompt=user_prompt)
        if user_prompt
        else stage_ingest.s(project_id, video_storage_key)
    )
    pipeline = chain(
        ingest_sig,
        stage_audio.s(),
        stage_transcribe.s(),
        stage_select_clips.s(),
        stage_reframe.s(),
        stage_render_all.s(),
    )
    pipeline.apply_async()


@celery_app.task(
    name="workers.tasks.resume_pipeline",
    bind=True,
    max_retries=0,
    queue="cpu",
)
def resume_pipeline(self, project_id: str):
    """
    Smart resume: inspects the DB and storage state for project_id,
    and resumes execution from the earliest uncompleted stage.
    """
    from api.models import Project, Video, Transcript, Clip, RenderSettings, Render, JobStatus, ProjectStatus
    from api.storage import object_exists
    from api.config import get_settings

    cfg = get_settings()
    logger.info("[pipeline] Resuming project %s", project_id)

    with _get_session() as db:
        proj = db.get(Project, uuid.UUID(project_id))
        if not proj:
            logger.error("Cannot resume: project %s not found", project_id)
            return

        video = db.execute(
            select(Video).where(Video.project_id == uuid.UUID(project_id))
        ).scalars().first()
        storage_key = (video.storage_key if video else None) or ""

        # Check 1: Ingest complete?
        if not video or not video.duration or video.duration <= 0:
            logger.info("[resume] Resuming from Stage 1: Ingest")
            return run_pipeline.delay(project_id, storage_key)

        video_meta = {
            "duration": video.duration,
            "width": video.width,
            "height": video.height,
            "fps": video.fps,
            "codec": video.codec,
        }
        prev = {"project_id": project_id, "video_storage_key": storage_key, "meta": video_meta}

        # Check 2: Audio extraction complete?
        audio_key = f"{project_id}/audio.wav"
        if not object_exists(cfg.bucket_audio, audio_key):
            logger.info("[resume] Resuming from Stage 2: Audio extraction")
            pipeline = chain(
                stage_audio.s(prev),
                stage_transcribe.s(),
                stage_select_clips.s(),
                stage_reframe.s(),
                stage_render_all.s(),
            )
            return pipeline.apply_async()

        prev["audio_key"] = audio_key

        # Check 3: Transcription complete?
        tr = db.execute(
            select(Transcript).where(Transcript.video_id == video.id)
        ).scalars().first()
        if not tr or not tr.data:
            logger.info("[resume] Resuming from Stage 3: Transcription")
            pipeline = chain(
                stage_transcribe.s(prev),
                stage_select_clips.s(),
                stage_reframe.s(),
                stage_render_all.s(),
            )
            return pipeline.apply_async()

        prev["transcript"] = tr.data

        # Check 4: Clip selection complete?
        clips = db.execute(
            select(Clip).where(Clip.project_id == uuid.UUID(project_id))
        ).scalars().all()
        if not clips:
            logger.info("[resume] Resuming from Stage 4: Clip selection")
            pipeline = chain(
                stage_select_clips.s(prev),
                stage_reframe.s(),
                stage_render_all.s(),
            )
            return pipeline.apply_async()

        clip_ids = [str(c.id) for c in clips]
        clips_data = [
            {
                "start": c.start, "end": c.end, "score": c.score,
                "score_breakdown": c.score_breakdown or {},
                "hook": c.hook or "", "title": c.title or "",
                "description": c.description or "", "hashtags": c.hashtags or [],
            }
            for c in clips
        ]
        prev["clip_ids"] = clip_ids
        prev["clips_data"] = clips_data

        # Check 5: Reframe complete?
        needs_reframe = False
        reframe_results = []
        for c in clips:
            rs = db.execute(
                select(RenderSettings).where(RenderSettings.clip_id == c.id)
            ).scalar_one_or_none()
            if not rs or not rs.crop_keyframes:
                needs_reframe = True
                break
            reframe_results.append(rs.crop_keyframes)

        if needs_reframe:
            logger.info("[resume] Resuming from Stage 5: Reframing")
            pipeline = chain(
                stage_reframe.s(prev),
                stage_render_all.s(),
            )
            return pipeline.apply_async()

        prev["reframe_results"] = reframe_results

        # Check 6: Render remaining unrendered clips
        logger.info("[resume] Resuming from Stage 6: Rendering pending clips")
        return stage_render_all.delay(prev)


@celery_app.task(
    name="workers.tasks.reclip_pipeline",
    bind=True,
    max_retries=0,
    queue="cpu",
)
def reclip_pipeline(self, project_id: str, user_prompt: str | None = None):
    """
    Re-clip a project using existing video and transcript, with optional custom user prompt.
    Clears existing clips and re-runs Stage 4 (select clips) -> Stage 5 (reframe) -> Stage 6 (render).
    """
    from api.models import Project, Video, Transcript, ProjectStatus
    from api.config import get_settings

    cfg = get_settings()
    logger.info("[reclip] Re-clipping project %s with prompt: %s", project_id, user_prompt)
    _update_project_status(project_id, ProjectStatus.processing)

    with _get_session() as db:
        proj = db.get(Project, uuid.UUID(project_id))
        if not proj:
            logger.error("[reclip] Project %s not found", project_id)
            return

        video = db.execute(
            select(Video).where(Video.project_id == uuid.UUID(project_id))
        ).scalars().first()
        if not video:
            logger.error("[reclip] Video not found for project %s", project_id)
            return

        tr = db.execute(
            select(Transcript).where(Transcript.video_id == video.id)
        ).scalars().first()
        if not tr or not tr.data:
            logger.error("[reclip] Transcript not found for project %s", project_id)
            return

        prev = {
            "project_id": project_id,
            "video_storage_key": f"{project_id}/video.mp4",
            "meta": {
                "duration": video.duration,
                "width": video.width,
                "height": video.height,
                "fps": video.fps,
                "codec": video.codec,
            },
            "audio_key": f"{project_id}/audio.wav",
            "transcript": tr.data,
            "force_reclip": True,
            "user_prompt": user_prompt,
        }

    pipeline = chain(
        stage_select_clips.s(prev),
        stage_reframe.s(),
        stage_render_all.s(),
    )
    return pipeline.apply_async()


# ── Stage 1: Ingest ────────────────────────────────────────────────────────────

@celery_app.task(
    name="workers.tasks.stage_ingest",
    bind=True,
    max_retries=3,
    queue="cpu",
    acks_late=True,
)
def stage_ingest(
    self,
    project_id: str,
    video_storage_key: str,
    user_prompt: str | None = None,
) -> dict:
    """Download/validate the video and update the project record."""
    from api.models import Project, Video, Job, ProjectStatus, JobStatus
    from api.storage import download_file, upload_file
    from api.config import get_settings
    from workers.ingest import ingest_video

    cfg = get_settings()
    _emit(project_id, "ingest", 5, "Validating video…")
    _update_job_status(project_id, "ingest", JobStatus.running, 5, attempts=self.request.retries + 1)
    _update_project_status(project_id, ProjectStatus.processing)

    # Check for existing video metadata (idempotence)
    with _get_session() as db:
        video = db.execute(
            select(Video).where(Video.project_id == uuid.UUID(project_id))
        ).scalars().first()
        if video and video.duration and video.duration > 0 and video.width:
            logger.info("[ingest] Video already validated for project %s", project_id)
            meta = {
                "duration": video.duration,
                "width": video.width,
                "height": video.height,
                "fps": video.fps,
                "codec": video.codec,
            }
            _emit(project_id, "ingest", 20, "Video validated (cached) ✓")
            _update_job_status(project_id, "ingest", JobStatus.running, 20)
            out = {"project_id": project_id, "video_storage_key": video.storage_key or video_storage_key, "meta": meta}
            if user_prompt:
                out["user_prompt"] = user_prompt
            return out

    with tempfile.TemporaryDirectory() as tmpdir:
        work_dir = Path(tmpdir)
        try:
            # Determine source: MinIO key vs URL vs project source_url
            source_input = video_storage_key
            if not source_input:
                with _get_session() as db:
                    proj = db.get(Project, uuid.UUID(project_id))
                    if proj and proj.source_url:
                        source_input = proj.source_url

            if source_input.startswith("http://") or source_input.startswith("https://"):
                # URL mode: ingest_video downloads with yt-dlp
                meta = ingest_video(source_input, work_dir)
                # Store the downloaded video to MinIO so downstream stages have it
                storage_key = f"{project_id}/video.mp4"
                meta_path = getattr(meta, "path", None) if not isinstance(meta, dict) else meta.get("path")
                downloaded_file = (
                    Path(meta_path)
                    if meta_path and Path(meta_path).exists()
                    else (work_dir / "input.mp4")
                )
                if downloaded_file.exists():
                    upload_file(cfg.bucket_originals, storage_key, downloaded_file)
                    video_storage_key = storage_key
            else:
                # MinIO object mode: download from bucket_originals
                local_video = work_dir / "input.mp4"
                download_file(cfg.bucket_originals, video_storage_key, local_video)
                meta = ingest_video(local_video, work_dir)

        except Exception as exc:
            logger.error("[ingest] failed: %s", exc)
            _emit(project_id, "ingest", 0, f"Ingest failed: {exc}")
            _update_job_status(project_id, "ingest", JobStatus.failed, 0, error=str(exc))
            _update_project_status(project_id, ProjectStatus.failed)
            raise self.retry(exc=exc, countdown=_backoff(self.request.retries))

    # Persist video metadata to DB
    meta_dict = {
        "duration": getattr(meta, "duration", None) if not isinstance(meta, dict) else meta.get("duration"),
        "width": getattr(meta, "width", None) if not isinstance(meta, dict) else meta.get("width"),
        "height": getattr(meta, "height", None) if not isinstance(meta, dict) else meta.get("height"),
        "fps": getattr(meta, "fps", None) if not isinstance(meta, dict) else meta.get("fps"),
        "codec": getattr(meta, "codec", None) if not isinstance(meta, dict) else meta.get("codec"),
    }

    with _get_session() as db:
        video = db.execute(
            select(Video).where(Video.project_id == uuid.UUID(project_id))
        ).scalars().first()
        if not video:
            video = Video(project_id=uuid.UUID(project_id))
            db.add(video)
        video.storage_key = video_storage_key
        video.duration = meta_dict.get("duration")
        video.width = meta_dict.get("width")
        video.height = meta_dict.get("height")
        video.fps = meta_dict.get("fps")
        video.codec = meta_dict.get("codec")
        db.commit()

    _emit(project_id, "ingest", 20, "Video validated ✓")
    _update_job_status(project_id, "ingest", JobStatus.running, 20)
    out = {"project_id": project_id, "video_storage_key": video_storage_key, "meta": meta_dict}
    if user_prompt:
        out["user_prompt"] = user_prompt
    return out



# ── Stage 2: Audio Extraction ─────────────────────────────────────────────────

@celery_app.task(
    name="workers.tasks.stage_audio",
    bind=True,
    max_retries=3,
    queue="cpu",
    acks_late=True,
)
def stage_audio(self, prev: dict) -> dict:
    """Extract mono 16kHz WAV from the original video."""
    from api.config import get_settings
    from api.models import JobStatus
    from api.storage import download_file, upload_file, object_exists
    from workers.audio_extract import extract_audio

    project_id = prev["project_id"]
    video_storage_key = prev["video_storage_key"]
    cfg = get_settings()
    audio_key = f"{project_id}/audio.wav"

    _emit(project_id, "audio", 22, "Extracting audio…")
    _update_job_status(project_id, "audio", JobStatus.running, 22, attempts=self.request.retries + 1)

    # Idempotence check: check if audio already exists in MinIO
    if object_exists(cfg.bucket_audio, audio_key):
        logger.info("[audio] Audio already exists for %s", project_id)
        _emit(project_id, "audio", 35, "Audio extracted (cached) ✓")
        _update_job_status(project_id, "audio", JobStatus.running, 35)
        return {**prev, "audio_key": audio_key}

    with tempfile.TemporaryDirectory() as tmpdir:
        work_dir = Path(tmpdir)
        try:
            video_path = download_file(cfg.bucket_originals, video_storage_key, work_dir / "video.mp4")
            audio_path = extract_audio(video_path, work_dir)
            upload_file(cfg.bucket_audio, audio_key, audio_path)
        except Exception as exc:
            logger.error("[audio] failed: %s", exc)
            _emit(project_id, "audio", 0, f"Audio extraction failed: {exc}")
            _update_job_status(project_id, "audio", JobStatus.failed, 0, error=str(exc))
            raise self.retry(exc=exc, countdown=_backoff(self.request.retries))

    _emit(project_id, "audio", 35, "Audio extracted ✓")
    _update_job_status(project_id, "audio", JobStatus.running, 35)
    return {**prev, "audio_key": audio_key}


# ── Stage 3: Transcription ─────────────────────────────────────────────────────

@celery_app.task(
    name="workers.tasks.stage_transcribe",
    bind=True,
    max_retries=3,
    queue=GPU_QUEUE,
    acks_late=True,
)
def stage_transcribe(self, prev: dict) -> dict:
    """Run faster-whisper ASR to produce word-level transcript."""
    from api.config import get_settings
    from api.models import JobStatus, Transcript, Video
    from api.storage import download_file
    from workers.transcribe import transcribe

    project_id = prev["project_id"]
    cfg = get_settings()

    _emit(project_id, "transcribing", 37, "Transcribing with Whisper…")
    _update_job_status(project_id, "transcribe", JobStatus.running, 37, attempts=self.request.retries + 1)

    # Idempotence check: check if transcript already exists in DB
    with _get_session() as db:
        video = db.execute(
            select(Video).where(Video.project_id == uuid.UUID(project_id))
        ).scalars().first()
        if video:
            tr = db.execute(
                select(Transcript).where(Transcript.video_id == video.id)
            ).scalars().first()
            if tr and tr.data:
                logger.info("[transcribe] Transcript already exists for %s", project_id)
                word_count = len(tr.data.get("all_words", [])) if isinstance(tr.data, dict) else 0
                _emit(project_id, "transcribing", 55, f"Transcribed (cached) ✓ — {word_count} words")
                _update_job_status(project_id, "transcribe", JobStatus.running, 55)
                return {**prev, "transcript": tr.data}

    with tempfile.TemporaryDirectory() as tmpdir:
        work_dir = Path(tmpdir)
        try:
            audio_path = download_file(cfg.bucket_audio, prev["audio_key"], work_dir / "audio.wav")

            def _on_transcribe_progress(done_sec: float, total_sec: float):
                ratio = min(1.0, max(0.0, done_sec / max(1.0, total_sec)))
                pct = 37 + int(ratio * 17)
                msg = f"Transcribing audio ({int(done_sec)}s / {int(total_sec)}s)…"
                _emit(project_id, "transcribing", pct, msg)
                _update_job_status(project_id, "transcribe", JobStatus.running, pct)

            try:
                transcript = transcribe(audio_path, work_dir, progress_callback=_on_transcribe_progress)
            except TypeError:
                transcript = transcribe(audio_path, work_dir)
        except Exception as exc:
            logger.error("[transcribe] failed: %s", exc)
            _emit(project_id, "transcribing", 0, f"Transcription failed: {exc}")
            _update_job_status(project_id, "transcribe", JobStatus.failed, 0, error=str(exc))
            raise self.retry(exc=exc, countdown=_backoff(self.request.retries))

        transcript_data = transcript.to_dict()

    # Persist transcript to DB
    with _get_session() as db:
        video = db.execute(
            select(Video).where(Video.project_id == uuid.UUID(project_id))
        ).scalars().first()
        if video:
            tr = Transcript(video_id=video.id, data=transcript_data, model="faster-whisper-base")
            db.add(tr)
            video.language = transcript.language
            db.commit()

    _emit(project_id, "transcribing", 55, f"Transcribed ✓ — {len(transcript.all_words)} words")
    _update_job_status(project_id, "transcribe", JobStatus.running, 55)
    return {**prev, "transcript": transcript_data}


# ── Stage 4: Clip Selection ────────────────────────────────────────────────────

@celery_app.task(
    name="workers.tasks.stage_select_clips",
    bind=True,
    max_retries=3,
    queue="cpu",
    acks_late=True,
)
def stage_select_clips(self, prev: dict) -> dict:
    """Use LLM to select and score the best clips."""
    from api.models import Clip as ClipModel, ClipStatus, JobStatus, Layout, RenderSettings
    from workers.select_clips import select_clips
    from workers.transcribe import Transcript

    project_id = prev["project_id"]
    _emit(project_id, "selecting_clips", 57, "LLM analyzing transcript…")
    _update_job_status(project_id, "select_clips", JobStatus.running, 57, attempts=self.request.retries + 1)

    force_reclip = prev.get("force_reclip", False)
    user_prompt = prev.get("user_prompt")

    # Idempotence check: check if clips already selected for this project
    with _get_session() as db:
        if force_reclip:
            logger.info("[select_clips] Force reclip requested for project %s; clearing old clips", project_id)
            old_clips = db.execute(
                select(ClipModel).where(ClipModel.project_id == uuid.UUID(project_id))
            ).scalars().all()
            for oc in old_clips:
                db.delete(oc)
            db.commit()
            existing_clips = []
        else:
            existing_clips = db.execute(
                select(ClipModel).where(ClipModel.project_id == uuid.UUID(project_id))
            ).scalars().all()

        if existing_clips:
            logger.info("[select_clips] Clips already exist for project %s", project_id)
            clip_ids = [str(c.id) for c in existing_clips]
            clips_data = [
                {
                    "start": c.start, "end": c.end, "score": c.score,
                    "score_breakdown": c.score_breakdown or {},
                    "hook": c.hook or "", "title": c.title or "",
                    "description": c.description or "", "hashtags": c.hashtags or [],
                }
                for c in existing_clips
            ]
            _emit(project_id, "selecting_clips", 65, f"Selected {len(clips_data)} clips (cached) ✓", clips_total=len(clips_data))
            _update_job_status(project_id, "select_clips", JobStatus.running, 65)
            return {**prev, "clip_ids": clip_ids, "clips_data": clips_data}

    with tempfile.TemporaryDirectory() as tmpdir:
        work_dir = Path(tmpdir)
        try:
            transcript = Transcript.from_dict(prev["transcript"])
            clips = select_clips(transcript, work_dir, user_prompt=user_prompt)
        except Exception as exc:
            logger.error("[select_clips] failed: %s", exc)
            _emit(project_id, "selecting_clips", 0, f"Clip selection failed: {exc}")
            _update_job_status(project_id, "select_clips", JobStatus.failed, 0, error=str(exc))
            raise self.retry(exc=exc, countdown=_backoff(self.request.retries))

    # Persist clips to DB
    clip_ids = []
    with _get_session() as db:
        for clip in clips:
            db_clip = ClipModel(
                project_id=uuid.UUID(project_id),
                start=clip.start,
                end=clip.end,
                score=clip.score,
                score_breakdown={
                    "hook": clip.score_breakdown.hook,
                    "flow": clip.score_breakdown.flow,
                    "value": clip.score_breakdown.value,
                    "trend": clip.score_breakdown.trend,
                },
                hook=clip.hook,
                title=clip.title,
                description=clip.description,
                hashtags=clip.hashtags,
                status=ClipStatus.pending,
            )
            db.add(db_clip)
            db.flush()
            rs = RenderSettings(clip_id=db_clip.id, layout=Layout.vertical)
            db.add(rs)
            clip_ids.append(str(db_clip.id))
        db.commit()

    _emit(project_id, "selecting_clips", 65, f"Selected {len(clips)} clips ✓", clips_total=len(clips))
    _update_job_status(project_id, "select_clips", JobStatus.running, 65)
    return {**prev, "clip_ids": clip_ids, "clips_data": [c.to_dict() for c in clips]}


# ── Stage 5: Reframing ────────────────────────────────────────────────────────

@celery_app.task(
    name="workers.tasks.stage_reframe",
    bind=True,
    max_retries=3,
    queue=GPU_QUEUE,
    acks_late=True,
)
def stage_reframe(self, prev: dict) -> dict:
    """Compute 9:16 crop keyframes for each clip."""
    from api.config import get_settings
    from api.models import JobStatus, RenderSettings
    from api.storage import download_file
    from workers.reframe import reframe_all_clips
    from workers.select_clips import Clip

    project_id = prev["project_id"]
    cfg = get_settings()

    _emit(project_id, "reframing", 67, "Computing crop paths…")
    _update_job_status(project_id, "reframe", JobStatus.running, 67, attempts=self.request.retries + 1)

    # Idempotence check: check if crop_keyframes already stored for all clips
    with _get_session() as db:
        all_keyframes = []
        all_present = True
        for clip_id in prev["clip_ids"]:
            rs = db.execute(
                select(RenderSettings).where(RenderSettings.clip_id == uuid.UUID(clip_id))
            ).scalar_one_or_none()
            if not rs or not rs.crop_keyframes:
                all_present = False
                break
            all_keyframes.append(rs.crop_keyframes)

        if all_present and len(all_keyframes) == len(prev["clip_ids"]):
            logger.info("[reframe] Keyframes already exist for project %s", project_id)
            _emit(project_id, "reframing", 75, "Crop paths computed (cached) ✓")
            _update_job_status(project_id, "reframe", JobStatus.running, 75)
            return {**prev, "reframe_results": all_keyframes}

    with tempfile.TemporaryDirectory() as tmpdir:
        work_dir = Path(tmpdir)
        try:
            video_storage_key = prev.get("video_storage_key") or f"{project_id}/video.mp4"
            cache_vid = Path(tempfile.gettempdir()) / "video2reels_cache" / f"{project_id}_video.mp4"
            cache_vid.parent.mkdir(parents=True, exist_ok=True)
            if cache_vid.exists() and cache_vid.stat().st_size > 1_000_000:
                video_path = cache_vid
            else:
                video_path = download_file(cfg.bucket_originals, video_storage_key, cache_vid)
            meta = prev.get("meta", {})
            src_w = int(meta.get("width") or 1920)
            src_h = int(meta.get("height") or 1080)
            fps = float(meta.get("fps") or 30.0)
            clips = [Clip.from_dict(c) for c in prev["clips_data"]]
            reframe_results = reframe_all_clips(
                clips=clips,
                source_video=video_path,
                work_dir=work_dir,
                src_w=src_w,
                src_h=src_h,
                fps=fps,
            )

        except Exception as exc:
            logger.error("[reframe] failed: %s", exc)
            _emit(project_id, "reframing", 0, f"Reframing failed: {exc}")
            _update_job_status(project_id, "reframe", JobStatus.failed, 0, error=str(exc))
            raise self.retry(exc=exc, countdown=_backoff(self.request.retries))

    # Persist crop keyframes to DB
    with _get_session() as db:
        for clip_id, result in zip(prev["clip_ids"], reframe_results):
            rs = db.execute(
                select(RenderSettings).where(RenderSettings.clip_id == uuid.UUID(clip_id))
            ).scalar_one_or_none()
            if rs:
                rs.crop_keyframes = result.to_dict() if hasattr(result, "to_dict") else vars(result)
        db.commit()

    _emit(project_id, "reframing", 75, "Crop paths computed ✓")
    _update_job_status(project_id, "reframe", JobStatus.running, 75)
    return {**prev, "reframe_results": [
        r.to_dict() if hasattr(r, "to_dict") else vars(r) for r in reframe_results
    ]}


# ── Stage 6: Render All Clips ─────────────────────────────────────────────────

@celery_app.task(
    name="workers.tasks.stage_render_all",
    bind=True,
    max_retries=0,
    queue=GPU_QUEUE,
    acks_late=True,
)
def stage_render_all(self, prev: dict):
    """Dispatch individual render tasks for each clip (parallelized)."""
    from api.models import JobStatus

    project_id = prev["project_id"]
    clip_ids = prev["clip_ids"]
    clips_data = prev["clips_data"]
    reframe_results = prev.get("reframe_results", [{} for _ in clip_ids])

    _emit(project_id, "rendering", 77, f"Rendering {len(clip_ids)} clips…", clips_total=len(clip_ids))
    _update_job_status(project_id, "render", JobStatus.running, 77)

    render_group = group(
        stage_render_clip.s(
            project_id=project_id,
            clip_id=clip_id,
            clip_data=clip_data,
            reframe_data=reframe_results[i] if i < len(reframe_results) else {},
            total_clips=len(clip_ids),
            clip_index=i + 1,
        )
        for i, (clip_id, clip_data) in enumerate(zip(clip_ids, clips_data))
    )
    render_group.apply_async()


@celery_app.task(
    name="workers.tasks.stage_render_clip",
    bind=True,
    max_retries=3,
    queue=GPU_QUEUE,
    acks_late=True,
)
def stage_render_clip(
    self,
    project_id: str,
    clip_id: str,
    clip_data: dict,
    reframe_data: dict,
    total_clips: int = 1,
    clip_index: int = 1,
):
    """Render a single clip: burn captions + export 1080x1920 MP4."""
    from api.config import get_settings
    from api.models import (
        Clip as ClipModel,
        ClipStatus,
        JobStatus,
        ProjectStatus,
        Render as RenderModel,
        RenderSettings as RenderSettingsModel,
        Transcript as TranscriptModel,
        Video as VideoModel,
        BrandKit as BrandKitModel,
    )
    from api.storage import download_file, upload_file, object_exists
    from workers.captions import get_caption_style
    from workers.ingest import VideoMeta
    from workers.reframe import CropKeyframe, ReframeResult
    from workers.render import render_clip as ffmpeg_render_clip
    from workers.select_clips import Clip
    from workers.transcribe import Transcript

    cfg = get_settings()
    storage_key = f"{project_id}/renders/{clip_id}.mp4"

    # Idempotence & metadata query from DB
    with _get_session() as db:
        c = db.get(ClipModel, uuid.UUID(clip_id))
        existing_render = db.execute(
            select(RenderModel).where(RenderModel.clip_id == uuid.UUID(clip_id))
        ).scalars().first()
        if existing_render and object_exists(cfg.bucket_renders, storage_key):
            logger.info("[render] Render already exists for clip %s", clip_id)
            if c and c.status != ClipStatus.done:
                c.status = ClipStatus.done
                db.commit()
            _check_and_mark_pipeline_complete(project_id, total_clips)
            return

        # Fetch video, transcript, and render_settings
        video_rec = db.execute(
            select(VideoModel).where(VideoModel.project_id == uuid.UUID(project_id))
        ).scalars().first()
        transcript_rec = db.execute(
            select(TranscriptModel).where(TranscriptModel.video_id == video_rec.id)
        ).scalars().first() if video_rec else None

        rs_rec = db.execute(
            select(RenderSettingsModel).where(RenderSettingsModel.clip_id == uuid.UUID(clip_id))
        ).scalars().first()

        brand_kit_rec = None
        if rs_rec and rs_rec.brand_kit_id:
            brand_kit_rec = db.get(BrandKitModel, rs_rec.brand_kit_id)

        transcript_data = transcript_rec.data if transcript_rec else None
        video_duration = (video_rec.duration if video_rec else None) or (clip_data.get("end", 15.0) - clip_data.get("start", 0.0))
        video_w = (video_rec.width if video_rec else None) or 1920
        video_h = (video_rec.height if video_rec else None) or 1080
        video_fps = (video_rec.fps if video_rec else None) or 30.0
        video_codec = (video_rec.codec if video_rec else None) or "h264"
        video_storage_key = (
            (video_rec.storage_key if video_rec and video_rec.storage_key else None)
            or f"{project_id}/video.mp4"
        )
        saved_crop = rs_rec.crop_keyframes if rs_rec else None
        saved_style = (
            (rs_rec.caption_style if rs_rec else None)
            or reframe_data.get("caption_style")
            or (brand_kit_rec.default_caption_style if brand_kit_rec else None)
        )
        saved_layout = (rs_rec.layout.value if rs_rec and rs_rec.layout else None) or reframe_data.get("layout", "vertical")
        brand_logo_key = brand_kit_rec.logo_key if brand_kit_rec else None

    with tempfile.TemporaryDirectory() as tmpdir:
        work_dir = Path(tmpdir)
        try:
            clip = Clip.from_dict(clip_data)
            cache_vid = Path(tempfile.gettempdir()) / "video2reels_cache" / f"{project_id}_video.mp4"
            cache_vid.parent.mkdir(parents=True, exist_ok=True)
            if cache_vid.exists() and cache_vid.stat().st_size > 1_000_000:
                video_path = cache_vid
            else:
                video_path = download_file(
                    cfg.bucket_originals, video_storage_key, cache_vid
                )

            watermark_path = None
            if brand_logo_key and object_exists(cfg.bucket_originals, brand_logo_key):
                watermark_path = download_file(
                    cfg.bucket_originals, brand_logo_key, work_dir / "brand_logo.png"
                )

            transcript = (
                Transcript.from_dict(transcript_data)
                if transcript_data
                else Transcript(
                    language="en",
                    language_probability=1.0,
                    duration=video_duration,
                    segments=[],
                )
            )
            style = get_caption_style(saved_style)

            crop_info = saved_crop or reframe_data or {}
            keyframes = [
                CropKeyframe(**kf) if isinstance(kf, dict) else kf
                for kf in crop_info.get("keyframes", [])
            ]
            reframe = ReframeResult(
                clip=clip,
                video_path=video_path,
                keyframes=keyframes,
                crop_w=crop_info.get("crop_w", 608),
                crop_h=crop_info.get("crop_h", 1080),
                crop_filter_expr=crop_info.get("crop_filter_expr", ""),
                layout=saved_layout,
            )

            meta = VideoMeta(
                path=video_path,
                duration=video_duration,
                width=video_w,
                height=video_h,
                fps=video_fps,
                codec=video_codec,
                has_audio=True,
                size_bytes=video_path.stat().st_size if video_path.exists() else 0,
            )

            # Render the clip via FFmpeg
            render_res = ffmpeg_render_clip(
                clip=clip,
                reframe=reframe,
                transcript=transcript,
                meta=meta,
                work_dir=work_dir,
                project_id=project_id,
                clip_index=clip_index,
                style=style,
                watermark_path=watermark_path,
            )
            output_path = render_res.output_path

            # Upload to storage
            upload_file(cfg.bucket_renders, storage_key, output_path)
            size_bytes = output_path.stat().st_size

        except Exception as exc:
            logger.error("[render] clip %s failed: %s", clip_id, exc)
            with _get_session() as db:
                c = db.get(ClipModel, uuid.UUID(clip_id))
                if c:
                    c.status = ClipStatus.failed
                    db.commit()
            raise self.retry(exc=exc, countdown=_backoff(self.request.retries))

    # Persist render to DB
    with _get_session() as db:
        c = db.get(ClipModel, uuid.UUID(clip_id))
        if c:
            c.status = ClipStatus.done
        render = RenderModel(
            clip_id=uuid.UUID(clip_id),
            storage_key=storage_key,
            resolution="1080x1920",
            size_bytes=size_bytes,
        )
        db.add(render)
        db.commit()

    _check_and_mark_pipeline_complete(project_id, total_clips)


def _check_and_mark_pipeline_complete(project_id: str, total_clips: int):
    """Check how many clips have finished rendering and update overall progress."""
    from api.models import Clip as ClipModel, ClipStatus, JobStatus, ProjectStatus
    try:
        with _get_session() as db:
            clips = db.execute(
                select(ClipModel).where(ClipModel.project_id == uuid.UUID(project_id))
            ).scalars().all()
            done_count = sum(1 for c in clips if c.status == ClipStatus.done)
            failed_count = sum(1 for c in clips if c.status == ClipStatus.failed)
            total = len(clips) or total_clips or 1

            progress = 77 + int((done_count / total) * 23)
            _update_job_status(project_id, "render", JobStatus.running, min(progress, 99))
            _emit(
                project_id,
                "rendering",
                min(progress, 99),
                f"Rendered {done_count}/{total} clips",
                clips_done=done_count,
                clips_total=total,
            )

            if done_count + failed_count >= total:
                # All clips evaluated
                final_status = ProjectStatus.done if done_count > 0 else ProjectStatus.failed
                job_status = JobStatus.done if done_count > 0 else JobStatus.failed
                _update_project_status(project_id, final_status)
                _update_job_status(project_id, "done", job_status, 100)
                _emit(
                    project_id,
                    "done",
                    100,
                    f"Pipeline complete! {done_count} clips ready.",
                    clips_done=done_count,
                    clips_total=total,
                )
    except Exception as exc:
        logger.warning("Error checking completion for project %s: %s", project_id, exc)


# ── One-off re-render (triggered from PATCH /clips/{id}/render) ───────────────

@celery_app.task(
    name="workers.tasks.render_clip",
    bind=True,
    max_retries=3,
    queue=GPU_QUEUE,
    acks_late=True,
)
def render_clip(self, project_id: str, clip_id: str, render_settings: dict):
    """Re-render a specific clip with updated settings."""
    from api.models import Clip as ClipModel
    with _get_session() as db:
        clip = db.get(ClipModel, uuid.UUID(clip_id))
        if not clip:
            logger.error("render_clip: clip %s not found", clip_id)
            return
        clip_data = {
            "start": clip.start,
            "end": clip.end,
            "hook": clip.hook or "",
            "title": clip.title or "",
            "score": clip.score or 0,
            "score_breakdown": clip.score_breakdown or {},
            "reason": "",
            "description": clip.description or "",
            "hashtags": clip.hashtags or [],
        }

    stage_render_clip.apply_async(
        kwargs={
            "project_id": project_id,
            "clip_id": clip_id,
            "clip_data": clip_data,
            "reframe_data": render_settings,
            "total_clips": 1,
        },
        queue=GPU_QUEUE,
    )
