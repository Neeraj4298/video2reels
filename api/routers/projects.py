"""
API router — projects
POST   /api/projects               Create project (URL or start upload)
GET    /api/projects               List all projects
GET    /api/projects/{id}          Get project detail (with clips + jobs)
DELETE /api/projects/{id}          Delete project + all storage objects
GET    /api/projects/{id}/events   SSE progress stream
"""
from __future__ import annotations

import io
import json
import re
import uuid
import zipfile
from datetime import datetime, timezone
import logging

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import Response, StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from api.db import get_db
from api.events import event_stream
from api.models import Clip, Job, JobStatus, Project, ProjectStatus, SourceType, Video, Transcript, Render
from api.queue import dispatch_pipeline, dispatch_resume, dispatch_reclip
from api.schemas import (
    ClipRead,
    JobRead,
    ProjectCreate,
    ProjectDetail,
    ProjectRead,
    ReclipRequest,
)
from api.storage import presigned_put_url, delete_prefix, download_bytes, object_exists
from api.config import get_settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/projects", tags=["projects"])
_settings = get_settings()


@router.post("", response_model=ProjectRead, status_code=status.HTTP_201_CREATED)
async def create_project(body: ProjectCreate, db: AsyncSession = Depends(get_db)):
    """
    Create a new project from a URL or prepare a direct upload.

    - **URL mode**: Provide `source_url`. The pipeline is dispatched immediately.
    - **Upload mode**: Omit `source_url`. Response will include an upload endpoint to follow up.
    """
    source_type = SourceType.url if body.source_url else SourceType.upload

    project = Project(
        name=body.name or f"Project {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M')}",
        source_type=source_type,
        source_url=body.source_url,
        status=ProjectStatus.pending,
    )
    db.add(project)
    await db.flush()  # get the UUID without committing

    # Create a placeholder video record
    video = Video(project_id=project.id)
    db.add(video)

    # Create a queued job for stage tracking
    job = Job(project_id=project.id, stage="ingest", status=JobStatus.queued)
    db.add(job)
    await db.flush()

    if body.source_url:
        # URL mode: dispatch pipeline immediately; ingest worker handles yt-dlp
        dispatch_pipeline(project.id, video_storage_key="")
        project.status = ProjectStatus.processing

    return project


@router.get("", response_model=list[ProjectRead])
async def list_projects(db: AsyncSession = Depends(get_db)):
    """List all projects, most recent first."""
    result = await db.execute(
        select(Project).order_by(Project.created_at.desc()).limit(100)
    )
    return result.scalars().all()


@router.get("/{project_id}", response_model=ProjectDetail)
async def get_project(project_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    """Get a project and its clips + jobs."""
    result = await db.execute(
        select(Project)
        .where(Project.id == project_id)
        .options(
            selectinload(Project.clips),
            selectinload(Project.jobs),
        )
    )
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


@router.delete("/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_project(project_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    """Delete a project and cascade-delete all clips, renders, and storage objects."""
    result = await db.execute(select(Project).where(Project.id == project_id))
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    # Cascade delete storage objects from all buckets
    prefix = f"{project_id}/"
    for b in (_settings.bucket_originals, _settings.bucket_audio, _settings.bucket_renders, _settings.bucket_clips):
        delete_prefix(b, prefix)

    await db.delete(project)


@router.post("/{project_id}/resume", status_code=status.HTTP_202_ACCEPTED)
async def resume_project(project_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    """
    Resume an interrupted, failed, or partially-processed project from the
    earliest incomplete pipeline stage.
    """
    result = await db.execute(select(Project).where(Project.id == project_id))
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    project.status = ProjectStatus.processing
    task_id = dispatch_resume(project_id)
    return {"message": "Pipeline resumed", "project_id": str(project_id), "task_id": task_id}



@router.get("/{project_id}/events")
async def project_events(project_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    """
    SSE progress stream for a project.
    Emits JSON events: {stage, progress, message, ...}
    """
    # Verify project exists
    result = await db.execute(select(Project).where(Project.id == project_id))
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Project not found")

    return StreamingResponse(
        event_stream(project_id),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",  # disable nginx buffering
        },
    )


@router.get("/{project_id}/transcript")
async def get_project_transcript(project_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    """Retrieve full transcript JSON for a project."""
    # Find video for this project
    video_res = await db.execute(select(Video).where(Video.project_id == project_id))
    video = video_res.scalars().first()
    if not video:
        raise HTTPException(status_code=404, detail="No video found for this project")

    tr_res = await db.execute(select(Transcript).where(Transcript.video_id == video.id))
    tr = tr_res.scalars().first()
    if not tr:
        raise HTTPException(status_code=404, detail="Transcript not ready yet")

    return tr.data


@router.get("/{project_id}/export/zip")
async def export_project_zip(
    project_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    """
    Export all clips for a project in a single ZIP bundle:
    - Rendered .mp4 videos (if rendered)
    - Subtitles in .srt and .vtt formats
    - Formatted metadata.json with title, hook, description, hashtags
    - project_summary.json
    """
    result = await db.execute(
        select(Project)
        .where(Project.id == project_id)
        .options(selectinload(Project.clips))
    )
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    # Get transcript if available for subtitles
    video_res = await db.execute(select(Video).where(Video.project_id == project_id))
    video = video_res.scalars().first()
    tr = None
    if video:
        tr_res = await db.execute(select(Transcript).where(Transcript.video_id == video.id))
        tr = tr_res.scalars().first()

    from workers.transcribe import Transcript as WorkerTranscript
    from workers.select_clips import Clip as WorkerClip, ScoreBreakdown
    from workers.captions import generate_srt, generate_vtt

    worker_transcript = WorkerTranscript.from_dict(tr.data) if (tr and tr.data) else None

    # Get latest renders for each clip
    clip_renders: dict[uuid.UUID, Render] = {}
    if project.clips:
        clip_ids = [c.id for c in project.clips]
        renders_res = await db.execute(
            select(Render)
            .where(Render.clip_id.in_(clip_ids))
            .order_by(Render.created_at.desc())
        )
        for r in renders_res.scalars().all():
            if r.clip_id not in clip_renders:
                clip_renders[r.clip_id] = r

    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        clips_summary = []
        for idx, clip in enumerate(project.clips, start=1):
            clean_title = re.sub(r"[^\w\-_\. ]", "", clip.title or f"clip_{idx}").strip().replace(" ", "_")
            clip_folder = f"clip_{idx:02d}_{clean_title}"

            clip_meta = {
                "id": str(clip.id),
                "index": idx,
                "title": clip.title,
                "hook": clip.hook,
                "description": clip.description,
                "hashtags": clip.hashtags or [],
                "start": clip.start,
                "end": clip.end,
                "duration": round(clip.end - clip.start, 2),
                "score": clip.score,
                "score_breakdown": clip.score_breakdown,
                "status": clip.status.value if hasattr(clip.status, "value") else str(clip.status),
            }
            clips_summary.append(clip_meta)

            # 1. metadata.json
            zf.writestr(
                f"{clip_folder}/metadata.json",
                json.dumps(clip_meta, indent=2, ensure_ascii=False),
            )

            # 2. Subtitles (.srt and .vtt)
            if worker_transcript:
                bd = clip.score_breakdown or {"hook": 8, "flow": 8, "value": 8, "trend": 8}
                worker_clip = WorkerClip(
                    start=clip.start,
                    end=clip.end,
                    hook=clip.hook or "",
                    title=clip.title or "clip",
                    score=clip.score or 0,
                    score_breakdown=ScoreBreakdown(
                        hook=bd.get("hook", 8),
                        flow=bd.get("flow", 8),
                        value=bd.get("value", 8),
                        trend=bd.get("trend", 8),
                    ),
                    reason="",
                )
                srt_content = generate_srt(worker_clip, worker_transcript, relative=True)
                vtt_content = generate_vtt(worker_clip, worker_transcript, relative=True)
                zf.writestr(f"{clip_folder}/subtitles.srt", srt_content)
                zf.writestr(f"{clip_folder}/subtitles.vtt", vtt_content)

            # 3. Video .mp4 (if rendered)
            render = clip_renders.get(clip.id)
            if render and render.storage_key:
                try:
                    if object_exists(_settings.bucket_renders, render.storage_key):
                        mp4_bytes = download_bytes(_settings.bucket_renders, render.storage_key)
                        zf.writestr(f"{clip_folder}/video.mp4", mp4_bytes)
                except Exception as exc:
                    logger.warning("Could not download rendered video %s: %s", render.storage_key, exc)

        # Root project summary
        summary = {
            "project_id": str(project.id),
            "name": project.name,
            "source_type": project.source_type.value if hasattr(project.source_type, "value") else str(project.source_type),
            "source_url": project.source_url,
            "created_at": project.created_at.isoformat() if project.created_at else None,
            "total_clips": len(project.clips),
            "clips": clips_summary,
        }
        zf.writestr("project_summary.json", json.dumps(summary, indent=2, ensure_ascii=False))

    zip_bytes = zip_buffer.getvalue()
    filename = f"project_{str(project.id)[:8]}_reels.zip"
    return Response(
        content=zip_bytes,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/{project_id}/reclip", status_code=status.HTTP_202_ACCEPTED)
async def reclip_project(
    project_id: uuid.UUID,
    body: ReclipRequest | None = None,
    db: AsyncSession = Depends(get_db),
):
    """
    Re-clip a project using its existing video and transcript, with an optional prompt.
    Clears old clips and runs Stage 4 -> Stage 5 -> Stage 6.
    """
    result = await db.execute(select(Project).where(Project.id == project_id))
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    user_prompt = body.user_prompt if body else None
    task_id = dispatch_reclip(project_id, user_prompt=user_prompt)
    project.status = ProjectStatus.processing
    return {
        "message": "Re-clipping initiated",
        "project_id": str(project_id),
        "task_id": task_id,
        "user_prompt": user_prompt,
    }
