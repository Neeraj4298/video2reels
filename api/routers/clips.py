"""
API router — clips
GET    /api/projects/{id}/clips   List clips for a project
PATCH  /api/clips/{id}            Update trim / title / selection / caption style
POST   /api/clips/{id}/render     Re-render with new settings
GET    /api/clips/{id}/download   Get presigned download URL for the rendered MP4
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from api.db import get_db
from api.models import Clip, Render, RenderSettings, Layout, ClipStatus, Video, Transcript
from api.schemas import (
    ClipRead,
    ClipUpdate,
    RenderRequest,
    RenderRead,
    ClipTranscriptRead,
    WordRead,
    ClipMetadataResponse,
    PublishRequest,
    PublishResponse,
)
from api.queue import dispatch_render
from api.storage import presigned_get_url
from api.config import get_settings

router = APIRouter(tags=["clips"])
_settings = get_settings()


# ── List clips for a project ──────────────────────────────────────────────────

@router.get("/api/projects/{project_id}/clips", response_model=list[ClipRead])
async def list_clips(project_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    """Return all clips for a project, ordered by score desc."""
    result = await db.execute(
        select(Clip)
        .where(Clip.project_id == project_id)
        .order_by(Clip.score.desc().nullslast())
    )
    return result.scalars().all()


# ── Update a clip ─────────────────────────────────────────────────────────────

@router.patch("/api/clips/{clip_id}", response_model=ClipRead)
async def update_clip(
    clip_id: uuid.UUID,
    body: ClipUpdate,
    db: AsyncSession = Depends(get_db),
):
    """Update trim points, title, hook, selection state, or caption style."""
    result = await db.execute(
        select(Clip)
        .where(Clip.id == clip_id)
        .options(selectinload(Clip.render_settings))
    )
    clip = result.scalar_one_or_none()
    if not clip:
        raise HTTPException(status_code=404, detail="Clip not found")

    # Update simple fields
    for field in ("start", "end", "title", "hook", "description", "hashtags", "selected"):
        value = getattr(body, field, None)
        if value is not None:
            setattr(clip, field, value)

    # Update caption style (stored in RenderSettings)
    if body.caption_style is not None:
        if clip.render_settings is None:
            rs = RenderSettings(clip_id=clip.id, layout=Layout.vertical)
            db.add(rs)
            clip.render_settings = rs
        clip.render_settings.caption_style = body.caption_style

    return clip


# ── Re-render a clip ──────────────────────────────────────────────────────────

@router.post("/api/clips/{clip_id}/render", response_model=dict)
async def render_clip(
    clip_id: uuid.UUID,
    body: RenderRequest,
    db: AsyncSession = Depends(get_db),
):
    """Queue a render (or re-render) for a clip with the given settings."""
    result = await db.execute(select(Clip).where(Clip.id == clip_id))
    clip = result.scalar_one_or_none()
    if not clip:
        raise HTTPException(status_code=404, detail="Clip not found")

    clip.status = ClipStatus.rendering
    task_id = dispatch_render(
        project_id=clip.project_id,
        clip_id=clip_id,
        render_settings=body.model_dump(exclude_none=True),
    )
    return {"task_id": task_id, "clip_id": str(clip_id), "status": "queued"}


# ── Download signed URL ───────────────────────────────────────────────────────

@router.get("/api/clips/{clip_id}/download")
async def download_clip(clip_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    """Return a presigned URL for downloading the latest rendered MP4."""
    result = await db.execute(
        select(Render)
        .where(Render.clip_id == clip_id)
        .order_by(Render.created_at.desc())
    )
    render = result.scalars().first()
    if not render or not render.storage_key:
        raise HTTPException(status_code=404, detail="No render found for this clip")

    url = presigned_get_url(
        _settings.bucket_renders,
        render.storage_key,
        ttl_seconds=_settings.presigned_url_ttl,
    )
    return {"download_url": url, "expires_in": _settings.presigned_url_ttl}


# ── Clip Transcript Words ─────────────────────────────────────────────────────

@router.get("/api/clips/{clip_id}/transcript", response_model=ClipTranscriptRead)
async def get_clip_transcript(clip_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    """Return word-level transcript for words falling within this clip's duration."""
    clip = await db.get(Clip, clip_id)
    if not clip:
        raise HTTPException(status_code=404, detail="Clip not found")

    video = (await db.execute(select(Video).where(Video.project_id == clip.project_id))).scalars().first()
    if not video:
        raise HTTPException(status_code=404, detail="No video found for clip project")

    tr = (await db.execute(select(Transcript).where(Transcript.video_id == video.id))).scalars().first()
    if not tr:
        raise HTTPException(status_code=404, detail="Transcript not ready yet")

    clip_words: list[WordRead] = []
    text_parts: list[str] = []
    data = tr.data or {}
    for seg in data.get("segments", []):
        for word in seg.get("words", []):
            w_start = float(word.get("s", word.get("start", 0.0)))
            w_end = float(word.get("e", word.get("end", 0.0)))
            w_text = str(word.get("w", word.get("text", ""))).strip()
            w_prob = float(word.get("p", word.get("prob", word.get("probability", 1.0))))
            if clip.start - 0.5 <= w_start <= clip.end + 0.5:
                clip_words.append(WordRead(w=w_text, s=w_start, e=w_end, p=w_prob))
                text_parts.append(w_text)

    return ClipTranscriptRead(
        clip_id=clip_id,
        start=clip.start,
        end=clip.end,
        words=clip_words,
        text=" ".join(text_parts),
    )


# ── Subtitle Export (SRT / WebVTT) ────────────────────────────────────────────

@router.get("/api/clips/{clip_id}/subtitles")
async def get_clip_subtitles(
    clip_id: uuid.UUID,
    format: str = "srt",
    relative: bool = True,
    db: AsyncSession = Depends(get_db),
):
    """Generate and return SRT or WebVTT subtitle text for downloading."""
    clip = await db.get(Clip, clip_id)
    if not clip:
        raise HTTPException(status_code=404, detail="Clip not found")

    video = (await db.execute(select(Video).where(Video.project_id == clip.project_id))).scalars().first()
    if not video:
        raise HTTPException(status_code=404, detail="No video found")

    tr = (await db.execute(select(Transcript).where(Transcript.video_id == video.id))).scalars().first()
    if not tr:
        raise HTTPException(status_code=404, detail="Transcript not ready")

    from workers.transcribe import Transcript as WorkerTranscript
    from workers.select_clips import Clip as WorkerClip, ScoreBreakdown
    from workers.captions import generate_srt, generate_vtt

    worker_transcript = WorkerTranscript.from_dict(tr.data)
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

    fmt = format.lower().strip()
    if fmt == "srt":
        content = generate_srt(worker_clip, worker_transcript, relative=relative)
        media_type = "text/plain; charset=utf-8"
        filename = f"clip_{str(clip_id)[:8]}.srt"
    elif fmt in ("vtt", "webvtt"):
        content = generate_vtt(worker_clip, worker_transcript, relative=relative)
        media_type = "text/vtt; charset=utf-8"
        filename = f"clip_{str(clip_id)[:8]}.vtt"
    else:
        raise HTTPException(status_code=400, detail="Invalid subtitle format. Use 'srt' or 'vtt'.")

    return Response(
        content=content,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ── Regenerate AI Metadata ───────────────────────────────────────────────────

@router.post("/api/clips/{clip_id}/metadata", response_model=ClipMetadataResponse)
async def regenerate_clip_metadata(
    clip_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    """Regenerate title, description, and hashtags using AI for a clip."""
    clip = await db.get(Clip, clip_id)
    if not clip:
        raise HTTPException(status_code=404, detail="Clip not found")

    video = (await db.execute(select(Video).where(Video.project_id == clip.project_id))).scalars().first()
    if not video:
        raise HTTPException(status_code=404, detail="No video found")

    tr = (await db.execute(select(Transcript).where(Transcript.video_id == video.id))).scalars().first()
    if not tr:
        raise HTTPException(status_code=404, detail="Transcript not ready")

    from workers.transcribe import Transcript as WorkerTranscript
    from workers.select_clips import Clip as WorkerClip, ScoreBreakdown, generate_clip_metadata

    worker_transcript = WorkerTranscript.from_dict(tr.data)
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

    metadata = generate_clip_metadata(worker_clip, worker_transcript)
    clip.title = metadata.get("title") or clip.title
    clip.description = metadata.get("description") or clip.description
    clip.hashtags = metadata.get("hashtags") or clip.hashtags
    await db.commit()

    return ClipMetadataResponse(
        title=clip.title or "",
        description=clip.description or "",
        hashtags=clip.hashtags or [],
    )


# ── Social Publishing ─────────────────────────────────────────────────────────

@router.post("/api/clips/{clip_id}/publish", response_model=PublishResponse)
async def publish_clip(
    clip_id: uuid.UUID,
    body: PublishRequest,
    db: AsyncSession = Depends(get_db),
):
    """Publish or schedule a clip to social platforms (YouTube Shorts, TikTok, Instagram Reels)."""
    valid_platforms = {"youtube", "tiktok", "instagram"}
    platform = body.platform.lower().strip()
    if platform not in valid_platforms:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid platform '{body.platform}'. Must be one of: {', '.join(sorted(valid_platforms))}",
        )

    clip = await db.get(Clip, clip_id)
    if not clip:
        raise HTTPException(status_code=404, detail="Clip not found")

    status_str = "scheduled" if body.scheduled_at else "published"
    platform_names = {
        "youtube": "YouTube Shorts",
        "tiktok": "TikTok",
        "instagram": "Instagram Reels",
    }
    target_name = platform_names.get(platform, platform.title())

    if body.scheduled_at:
        msg = f"Clip successfully scheduled for {target_name} at {body.scheduled_at.isoformat()}."
    else:
        msg = f"Clip successfully published to {target_name}!"

    return PublishResponse(
        clip_id=clip_id,
        platform=platform,
        status=status_str,
        scheduled_at=body.scheduled_at,
        message=msg,
    )
