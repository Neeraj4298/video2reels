"""
Celery task dispatch helpers called by API route handlers.
Keeps routing logic in one place — tasks are defined in workers/.
"""
from __future__ import annotations

import os
import uuid

from workers.celery_app import celery_app


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
    result = celery_app.send_task(
        "workers.tasks.run_pipeline",
        kwargs=kwargs,
        queue="cpu",
    )
    return result.id


def dispatch_render(
    project_id: uuid.UUID,
    clip_id: uuid.UUID,
    render_settings: dict,
) -> str:
    """
    Dispatch a (re-)render job for a specific clip.
    Returns the Celery task ID.
    """
    result = celery_app.send_task(
        "workers.tasks.render_clip",
        kwargs={
            "project_id": str(project_id),
            "clip_id": str(clip_id),
            "render_settings": render_settings,
        },
        queue=os.getenv("GPU_QUEUE", "cpu"),
    )
    return result.id


def dispatch_resume(project_id: uuid.UUID) -> str:
    """
    Resume an interrupted or failed pipeline from the last completed stage.
    Returns the Celery task ID.
    """
    result = celery_app.send_task(
        "workers.tasks.resume_pipeline",
        kwargs={"project_id": str(project_id)},
        queue="cpu",
    )
    return result.id


def dispatch_reclip(project_id: uuid.UUID, user_prompt: str | None = None) -> str:
    """
    Re-clip an existing project using its transcript, with optional custom user prompt.
    Returns the Celery task ID.
    """
    result = celery_app.send_task(
        "workers.tasks.reclip_pipeline",
        kwargs={"project_id": str(project_id), "user_prompt": user_prompt},
        queue="cpu",
    )
    return result.id

