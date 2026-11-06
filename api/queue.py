"""
Celery task dispatch helpers called by API route handlers.
Keeps routing logic in one place — tasks are defined in workers/.
"""
from __future__ import annotations

import os
import socket
import threading
from urllib.parse import urlparse
import uuid

from workers.celery_app import celery_app, REDIS_URL


def _is_redis_reachable() -> bool:
    try:
        parsed = urlparse(REDIS_URL)
        host = parsed.hostname or "localhost"
        port = parsed.port or 6379
        sock = socket.socket()
        sock.settimeout(0.25)
        ok = sock.connect_ex((host, port)) == 0
        sock.close()
        return ok
    except Exception:
        return False


def _run_pipeline_in_thread(
    project_id: str,
    video_storage_key: str,
    user_prompt: str | None = None,
) -> None:
    """Fallback local execution when Redis/Celery broker is not running."""
    from workers.tasks import (
        stage_ingest,
        stage_audio,
        stage_transcribe,
        stage_select_clips,
        stage_reframe,
        stage_render_clip,
    )

    try:
        r1 = stage_ingest(project_id, video_storage_key, user_prompt=user_prompt)
        r2 = stage_audio(r1)
        r3 = stage_transcribe(r2)
        r4 = stage_select_clips(r3)
        r5 = stage_reframe(r4)
        clip_ids = r5.get("clip_ids", [])
        clips_data = r5.get("clips_data", [])
        reframes = r5.get("reframe_results", [{} for _ in clip_ids])
        for i, (cid, cdata) in enumerate(zip(clip_ids, clips_data)):
            stage_render_clip(
                project_id=project_id,
                clip_id=cid,
                clip_data=cdata,
                reframe_data=reframes[i] if i < len(reframes) else {},
                total_clips=len(clip_ids),
                clip_index=i + 1,
            )
    except Exception as exc:
        import logging
        logging.getLogger(__name__).exception("Background pipeline error for %s: %s", project_id, exc)


def dispatch_pipeline(
    project_id: uuid.UUID,
    video_storage_key: str,
    user_prompt: str | None = None,
) -> str:
    """
    Dispatch the full 6-stage pipeline for a project.
    Returns the Celery task ID of the first stage.
    """
    kwargs: dict = {
        "project_id": str(project_id),
        "video_storage_key": video_storage_key,
    }
    if user_prompt:
        kwargs["user_prompt"] = user_prompt
    try:
        result = celery_app.send_task(
            "workers.tasks.run_pipeline",
            kwargs=kwargs,
            queue="cpu",
            retry=False,
        )
        return result.id
    except Exception:
        task_id = f"local-{uuid.uuid4()}"
        t = threading.Thread(
            target=_run_pipeline_in_thread,
            args=(str(project_id), video_storage_key, user_prompt),
            daemon=True,
        )
        t.start()
        return task_id


def dispatch_render(
    project_id: uuid.UUID,
    clip_id: uuid.UUID,
    render_settings: dict,
) -> str:
    """
    Dispatch a (re-)render job for a specific clip.
    Returns the Celery task ID.
    """
    try:
        result = celery_app.send_task(
            "workers.tasks.render_clip",
            kwargs={
                "project_id": str(project_id),
                "clip_id": str(clip_id),
                "render_settings": render_settings,
            },
            queue=os.getenv("GPU_QUEUE", "gpu"),
            retry=False,
        )
        return result.id
    except Exception:
        from workers.tasks import render_clip
        task_id = f"local-render-{uuid.uuid4()}"
        threading.Thread(
            target=render_clip,
            args=(str(project_id), str(clip_id), render_settings),
            daemon=True,
        ).start()
        return task_id


def dispatch_resume(project_id: uuid.UUID) -> str:
    """
    Resume an interrupted or failed pipeline from the last completed stage.
    Returns the Celery task ID.
    """
    try:
        result = celery_app.send_task(
            "workers.tasks.resume_pipeline",
            kwargs={"project_id": str(project_id)},
            queue="cpu",
            retry=False,
        )
        return result.id
    except Exception:
        task_id = f"local-resume-{uuid.uuid4()}"
        threading.Thread(
            target=_run_pipeline_in_thread,
            args=(str(project_id), "", None),
            daemon=True,
        ).start()
        return task_id


def dispatch_reclip(project_id: uuid.UUID, user_prompt: str | None = None) -> str:
    """
    Re-clip an existing project using its transcript, with optional custom user prompt.
    Returns the Celery task ID.
    """
    try:
        result = celery_app.send_task(
            "workers.tasks.reclip_pipeline",
            kwargs={"project_id": str(project_id), "user_prompt": user_prompt},
            queue="cpu",
            retry=False,
        )
        return result.id
    except Exception:
        task_id = f"local-reclip-{uuid.uuid4()}"
        threading.Thread(
            target=_run_pipeline_in_thread,
            args=(str(project_id), f"{project_id}/video.mp4", user_prompt),
            daemon=True,
        ).start()
        return task_id

