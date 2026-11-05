"""
API router — uploads
POST /api/uploads/sign    Get a presigned PUT URL for direct-to-MinIO upload
POST /api/uploads/confirm Notify the API that an upload is complete and start pipeline
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.db import get_db
from api.models import Job, JobStatus, Project, ProjectStatus, Video
from api.queue import dispatch_pipeline
from api.schemas import PresignedUploadResponse
from api.storage import presigned_put_url, object_exists
from api.config import get_settings

router = APIRouter(prefix="/api/uploads", tags=["uploads"])
_settings = get_settings()


class SignRequest(BaseModel):
    project_id: uuid.UUID
    filename: str
    content_type: str = "video/mp4"


class SignResponse(BaseModel):
    upload_url: str
    storage_key: str


class ConfirmRequest(BaseModel):
    project_id: uuid.UUID
    storage_key: str


@router.post("/sign", response_model=SignResponse)
async def sign_upload(body: SignRequest, db: AsyncSession = Depends(get_db)):
    """
    Return a presigned PUT URL for the client to upload directly to MinIO/S3.
    No file data passes through the API server.
    """
    result = await db.execute(select(Project).where(Project.id == body.project_id))
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    storage_key = f"{body.project_id}/{uuid.uuid4()}_{body.filename}"
    upload_url = presigned_put_url(
        _settings.bucket_originals,
        storage_key,
        ttl_seconds=3600,
    )
    return SignResponse(upload_url=upload_url, storage_key=storage_key)


@router.get("/presigned", response_model=PresignedUploadResponse)
async def presigned_upload(
    project_id: uuid.UUID,
    filename: str,
    db: AsyncSession = Depends(get_db),
):
    """
    GET endpoint used by the Next.js Web UI to obtain a presigned PUT URL
    for direct browser-to-MinIO upload.
    """
    result = await db.execute(select(Project).where(Project.id == project_id))
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    storage_key = f"{project_id}/{uuid.uuid4()}_{filename}"
    upload_url = presigned_put_url(
        _settings.bucket_originals,
        storage_key,
        ttl_seconds=3600,
    )
    return PresignedUploadResponse(
        upload_url=upload_url,
        storage_key=storage_key,
        project_id=project_id,
    )


@router.post("/confirm", status_code=status.HTTP_202_ACCEPTED)
@router.post("/complete", status_code=status.HTTP_202_ACCEPTED)
async def confirm_upload(body: ConfirmRequest, db: AsyncSession = Depends(get_db)):
    """
    Called by the client after a successful direct upload.
    Verifies the object exists, attaches it to the project's video record,
    and dispatches the processing pipeline.
    """
    result = await db.execute(select(Project).where(Project.id == body.project_id))
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    if not object_exists(_settings.bucket_originals, body.storage_key):
        raise HTTPException(status_code=400, detail="Upload not found in storage — did the upload complete?")

    # Attach video storage key
    video_result = await db.execute(
        select(Video).where(Video.project_id == body.project_id)
    )
    video = video_result.scalars().first()
    if not video:
        video = Video(project_id=body.project_id)
        db.add(video)
    video.storage_key = body.storage_key

    # Update project status and dispatch pipeline
    project.status = ProjectStatus.processing
    job_result = await db.execute(
        select(Job).where(Job.project_id == body.project_id)
    )
    job = job_result.scalars().first()
    if job:
        job.status = JobStatus.queued

    await db.flush()
    dispatch_pipeline(body.project_id, body.storage_key)

    return {"message": "Pipeline started", "project_id": str(body.project_id)}
