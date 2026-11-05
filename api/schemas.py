"""
Pydantic schemas for API request/response payloads.
Mirrors the ORM models but with serialization-friendly types.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, HttpUrl


# ── Shared ────────────────────────────────────────────────────────────────────

class OrmBase(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# ── Projects ──────────────────────────────────────────────────────────────────

class ProjectCreate(BaseModel):
    name: str | None = None
    source_url: str | None = None  # URL paste
    user_prompt: str | None = None  # Optional prompt for clip extraction ("find moments about X")
    # If no source_url, caller must follow up with an upload


class ReclipRequest(BaseModel):
    user_prompt: str | None = None


class ProjectRead(OrmBase):
    id: uuid.UUID
    name: str | None
    source_type: str
    source_url: str | None
    status: str
    created_at: datetime


class ProjectDetail(ProjectRead):
    clips: list[ClipRead] = []
    jobs: list[JobRead] = []


# ── Clips ─────────────────────────────────────────────────────────────────────

class ClipRead(OrmBase):
    id: uuid.UUID
    project_id: uuid.UUID
    start: float
    end: float
    score: int | None
    score_breakdown: dict | None
    hook: str | None
    title: str | None
    description: str | None
    hashtags: list[str] | None
    status: str
    selected: bool


class ClipUpdate(BaseModel):
    start: float | None = None
    end: float | None = None
    title: str | None = None
    hook: str | None = None
    description: str | None = None
    hashtags: list[str] | None = None
    selected: bool | None = None
    caption_style: dict | None = None


class WordRead(BaseModel):
    w: str
    s: float
    e: float
    p: float = 1.0


class ClipTranscriptRead(BaseModel):
    clip_id: uuid.UUID
    start: float
    end: float
    words: list[WordRead]
    text: str


class ClipMetadataResponse(BaseModel):
    title: str
    description: str
    hashtags: list[str]


class PublishRequest(BaseModel):
    platform: str  # "youtube", "tiktok", "instagram"
    title: str | None = None
    description: str | None = None
    scheduled_at: datetime | None = None


class PublishResponse(BaseModel):
    clip_id: uuid.UUID
    platform: str
    status: str  # "published", "scheduled"
    scheduled_at: datetime | None = None
    message: str


# ── Render Settings ───────────────────────────────────────────────────────────

class RenderSettingsRead(OrmBase):
    id: uuid.UUID
    clip_id: uuid.UUID
    layout: str
    caption_style: dict | None
    crop_keyframes: dict | None
    brand_kit_id: uuid.UUID | None


class RenderRequest(BaseModel):
    layout: str = "vertical"
    caption_style: dict | None = None
    brand_kit_id: uuid.UUID | None = None


# ── Renders ───────────────────────────────────────────────────────────────────

class RenderRead(OrmBase):
    id: uuid.UUID
    clip_id: uuid.UUID
    storage_key: str | None
    resolution: str | None
    size_bytes: int | None
    created_at: datetime


# ── Jobs ──────────────────────────────────────────────────────────────────────

class JobRead(OrmBase):
    id: uuid.UUID
    project_id: uuid.UUID
    stage: str | None
    status: str
    progress: int
    error: str | None
    attempts: int
    started_at: datetime | None
    finished_at: datetime | None


# ── Brand Kits ────────────────────────────────────────────────────────────────

class BrandKitCreate(BaseModel):
    name: str
    fonts: dict | None = None
    colors: dict | None = None
    default_caption_style: dict | None = None


class BrandKitRead(OrmBase):
    id: uuid.UUID
    name: str
    logo_key: str | None
    fonts: dict | None
    colors: dict | None
    default_caption_style: dict | None


# ── Upload ────────────────────────────────────────────────────────────────────

class PresignedUploadResponse(BaseModel):
    upload_url: str
    storage_key: str
    project_id: uuid.UUID


# ── SSE Events ────────────────────────────────────────────────────────────────

class ProgressEvent(BaseModel):
    stage: str
    progress: int          # 0-100
    message: str = ""
    clips_done: int | None = None
    clips_total: int | None = None
    clip_count: int | None = None


# ── Health ────────────────────────────────────────────────────────────────────

class HealthResponse(BaseModel):
    status: str = "ok"
    version: str


# Forward references
ProjectDetail.model_rebuild()
