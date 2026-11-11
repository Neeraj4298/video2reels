"""
SQLAlchemy ORM models — exactly matches the DB schema in BUILD_ARCHITECTURE.md §5
All PKs are UUIDs, all timestamps are timezone-aware.
"""
from __future__ import annotations

import enum
import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    BigInteger, Boolean, Enum, Float, ForeignKey,
    Integer, String, Text, func, JSON, TypeDecorator,
)
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMP, UUID, ARRAY
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Mapped, mapped_column, relationship

from api.db import Base


class StringArray(TypeDecorator):
    """Platform-independent string array: ARRAY(Text) on PostgreSQL, JSON on SQLite."""
    impl = ARRAY(Text)
    cache_ok = True

    def load_dialect_impl(self, dialect):
        if dialect.name == "postgresql":
            return dialect.type_descriptor(ARRAY(Text))
        else:
            return dialect.type_descriptor(JSON())

    def process_bind_param(self, value, dialect):
        return value

    def process_result_value(self, value, dialect):
        return value


# Enable SQLite in-memory compilation for PostgreSQL ARRAY during testing
@compiles(ARRAY, "sqlite")
def _compile_array_sqlite(type_, compiler, **kw):
    return "JSON"



# ── Helpers ───────────────────────────────────────────────────────────────────

def _uuid() -> uuid.UUID:
    return uuid.uuid4()


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ── Enums ─────────────────────────────────────────────────────────────────────

class SourceType(str, enum.Enum):
    upload = "upload"
    url = "url"


class ProjectStatus(str, enum.Enum):
    pending = "pending"
    processing = "processing"
    done = "done"
    failed = "failed"


class ClipStatus(str, enum.Enum):
    pending = "pending"
    rendering = "rendering"
    done = "done"
    failed = "failed"


class JobStatus(str, enum.Enum):
    queued = "queued"
    running = "running"
    done = "done"
    failed = "failed"


class Layout(str, enum.Enum):
    vertical = "vertical"
    split_screen = "split_screen"
    blur_bg = "blur_bg"


# ── Models ────────────────────────────────────────────────────────────────────

class Project(Base):
    __tablename__ = "projects"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    name: Mapped[str | None] = mapped_column(Text)
    source_type: Mapped[SourceType] = mapped_column(Enum(SourceType), nullable=False)
    source_url: Mapped[str | None] = mapped_column(Text)
    status: Mapped[ProjectStatus] = mapped_column(
        Enum(ProjectStatus), nullable=False, default=ProjectStatus.pending, index=True
    )
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), default=_now)

    # Relationships
    videos: Mapped[list[Video]] = relationship(back_populates="project", cascade="all, delete-orphan")
    clips: Mapped[list[Clip]] = relationship(back_populates="project", cascade="all, delete-orphan")
    jobs: Mapped[list[Job]] = relationship(back_populates="project", cascade="all, delete-orphan")


class Video(Base):
    __tablename__ = "videos"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    storage_key: Mapped[str | None] = mapped_column(Text)
    duration: Mapped[float | None] = mapped_column(Float)
    width: Mapped[int | None] = mapped_column(Integer)
    height: Mapped[int | None] = mapped_column(Integer)
    fps: Mapped[float | None] = mapped_column(Float)
    codec: Mapped[str | None] = mapped_column(String(32))
    language: Mapped[str | None] = mapped_column(String(16))

    # Relationships
    project: Mapped[Project] = relationship(back_populates="videos")
    transcripts: Mapped[list[Transcript]] = relationship(back_populates="video", cascade="all, delete-orphan")


class Transcript(Base):
    __tablename__ = "transcripts"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    video_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("videos.id", ondelete="CASCADE"), index=True)
    data: Mapped[dict] = mapped_column(JSONB, nullable=False)   # full transcript JSON with word timestamps
    model: Mapped[str | None] = mapped_column(String(64))       # e.g. "faster-whisper-base"
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), default=_now)

    # Relationships
    video: Mapped[Video] = relationship(back_populates="transcripts")


class Clip(Base):
    __tablename__ = "clips"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    start: Mapped[float] = mapped_column(Float, nullable=False)
    end: Mapped[float] = mapped_column(Float, nullable=False)
    score: Mapped[int | None] = mapped_column(Integer)
    score_breakdown: Mapped[dict | None] = mapped_column(JSONB)
    hook: Mapped[str | None] = mapped_column(Text)
    title: Mapped[str | None] = mapped_column(Text)
    description: Mapped[str | None] = mapped_column(Text)
    hashtags: Mapped[list[str] | None] = mapped_column(StringArray)
    status: Mapped[ClipStatus] = mapped_column(
        Enum(ClipStatus), nullable=False, default=ClipStatus.pending, index=True
    )
    selected: Mapped[bool] = mapped_column(Boolean, default=True)

    # Relationships
    project: Mapped[Project] = relationship(back_populates="clips")
    render_settings: Mapped[RenderSettings | None] = relationship(
        back_populates="clip", cascade="all, delete-orphan", uselist=False
    )
    renders: Mapped[list[Render]] = relationship(back_populates="clip", cascade="all, delete-orphan")


class RenderSettings(Base):
    __tablename__ = "render_settings"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    clip_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("clips.id", ondelete="CASCADE"), unique=True, index=True
    )
    layout: Mapped[Layout] = mapped_column(Enum(Layout), nullable=False, default=Layout.vertical)
    caption_style: Mapped[dict | None] = mapped_column(JSONB)    # {font, size, color, highlight_color, position}
    crop_keyframes: Mapped[dict | None] = mapped_column(JSONB)   # face-tracking crop path
    excluded_word_indices: Mapped[list | None] = mapped_column(JSONB)  # persisted word deletions
    word_overrides: Mapped[dict | None] = mapped_column(JSONB)         # persisted word text edits
    edl: Mapped[dict | None] = mapped_column(JSONB)                    # canonical EDL snapshot
    brand_kit_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("brand_kits.id", ondelete="SET NULL"))


    # Relationships
    clip: Mapped[Clip] = relationship(back_populates="render_settings")
    brand_kit: Mapped[BrandKit | None] = relationship()


class Render(Base):
    __tablename__ = "renders"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    clip_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("clips.id", ondelete="CASCADE"), index=True)
    storage_key: Mapped[str | None] = mapped_column(Text)
    resolution: Mapped[str | None] = mapped_column(String(16))   # e.g. "1080x1920"
    size_bytes: Mapped[int | None] = mapped_column(BigInteger)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), default=_now)

    # Relationships
    clip: Mapped[Clip] = relationship(back_populates="renders")


class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    stage: Mapped[str | None] = mapped_column(String(32))
    status: Mapped[JobStatus] = mapped_column(
        Enum(JobStatus), nullable=False, default=JobStatus.queued, index=True
    )
    progress: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(Text)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    started_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))

    # Relationships
    project: Mapped[Project] = relationship(back_populates="jobs")


class BrandKit(Base):
    __tablename__ = "brand_kits"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    logo_key: Mapped[str | None] = mapped_column(Text)
    fonts: Mapped[dict | None] = mapped_column(JSONB)    # {primary, secondary}
    colors: Mapped[dict | None] = mapped_column(JSONB)   # {primary, secondary, accent}
    default_caption_style: Mapped[dict | None] = mapped_column(JSONB)




# ── Platform, Stage Runs, Artifacts, EDL Versions & Credits (v2.1) ────────────

class Organization(Base):
    __tablename__ = "organizations"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    plan_tier: Mapped[str] = mapped_column(String(32), nullable=False, default="FREE")
    credits_remaining: Mapped[int] = mapped_column(Integer, nullable=False, default=60)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), default=_now)


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    org_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    role: Mapped[str] = mapped_column(String(32), nullable=False, default="OWNER")
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), default=_now)


class StageRun(Base):
    """One row per (project_id, stage, attempt) recording timing, status, model version, and artifacts."""
    __tablename__ = "stage_runs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    stage: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    status: Mapped[JobStatus] = mapped_column(Enum(JobStatus), nullable=False, default=JobStatus.queued)
    attempt: Mapped[int] = mapped_column(Integer, default=1)
    progress: Mapped[int] = mapped_column(Integer, default=0)
    model_version: Mapped[str | None] = mapped_column(String(64))
    prompt_version: Mapped[str | None] = mapped_column(String(64))
    output_artifact_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    error: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), default=_now)
    finished_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))


class Artifact(Base):
    """Versioned stage output artifact stored in object storage or JSONB."""
    __tablename__ = "artifacts"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    clip_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("clips.id", ondelete="CASCADE"), index=True)
    artifact_type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    storage_key: Mapped[str | None] = mapped_column(Text)
    data: Mapped[dict | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), default=_now)


class ClipVersion(Base):
    """Immutable EDL snapshot for undo/redo and clip variant history."""
    __tablename__ = "clip_versions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    clip_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("clips.id", ondelete="CASCADE"), index=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    edl: Mapped[dict] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), default=_now)


class CreditLedger(Base):
    """Append-only credit ledger (grants, spends, refunds, expiries)."""
    __tablename__ = "credit_ledger"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    org_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("organizations.id", ondelete="SET NULL"), index=True)
    project_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("projects.id", ondelete="SET NULL"), index=True)
    delta: Mapped[int] = mapped_column(Integer, nullable=False)
    reason: Mapped[str] = mapped_column(String(128), nullable=False)
    balance_after: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), default=_now)


class FeedbackEvent(Base):
    """User interaction telemetry (kept, trimmed, exported, published, rejected) for score calibration."""
    __tablename__ = "feedback_events"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    clip_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("clips.id", ondelete="CASCADE"), index=True)
    action: Mapped[str] = mapped_column(String(32), nullable=False)
    payload: Mapped[dict | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), default=_now)


class ApiKey(Base):
    __tablename__ = "api_keys"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    org_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    key_prefix: Mapped[str] = mapped_column(String(16), nullable=False)
    key_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), default=_now)

