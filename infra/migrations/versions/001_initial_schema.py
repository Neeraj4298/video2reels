"""001_initial_schema

Revision ID: 001_initial_schema
Revises: None
Create Date: 2026-11-02 12:45:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '001_initial_schema'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── Enums ─────────────────────────────────────────────────────────────────
    sourcetype_enum = postgresql.ENUM('upload', 'url', name='sourcetype', create_type=False)
    projectstatus_enum = postgresql.ENUM('pending', 'processing', 'done', 'failed', name='projectstatus', create_type=False)
    clipstatus_enum = postgresql.ENUM('pending', 'rendering', 'done', 'failed', name='clipstatus', create_type=False)
    jobstatus_enum = postgresql.ENUM('queued', 'running', 'done', 'failed', name='jobstatus', create_type=False)
    layout_enum = postgresql.ENUM('vertical', 'split_screen', 'blur_bg', name='layout', create_type=False)

    # In Postgres, create ENUM types first if they do not exist
    op.execute("DO $$ BEGIN CREATE TYPE sourcetype AS ENUM ('upload', 'url'); EXCEPTION WHEN duplicate_object THEN null; END $$;")
    op.execute("DO $$ BEGIN CREATE TYPE projectstatus AS ENUM ('pending', 'processing', 'done', 'failed'); EXCEPTION WHEN duplicate_object THEN null; END $$;")
    op.execute("DO $$ BEGIN CREATE TYPE clipstatus AS ENUM ('pending', 'rendering', 'done', 'failed'); EXCEPTION WHEN duplicate_object THEN null; END $$;")
    op.execute("DO $$ BEGIN CREATE TYPE jobstatus AS ENUM ('queued', 'running', 'done', 'failed'); EXCEPTION WHEN duplicate_object THEN null; END $$;")
    op.execute("DO $$ BEGIN CREATE TYPE layout AS ENUM ('vertical', 'split_screen', 'blur_bg'); EXCEPTION WHEN duplicate_object THEN null; END $$;")

    # ── Table: projects ───────────────────────────────────────────────────────
    op.create_table(
        'projects',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('name', sa.Text(), nullable=True),
        sa.Column('source_type', sourcetype_enum, nullable=False),
        sa.Column('source_url', sa.Text(), nullable=True),
        sa.Column('status', projectstatus_enum, nullable=False, server_default='pending'),
        sa.Column('created_at', postgresql.TIMESTAMP(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index(op.f('ix_projects_status'), 'projects', ['status'], unique=False)

    # ── Table: videos ─────────────────────────────────────────────────────────
    op.create_table(
        'videos',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('project_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('projects.id', ondelete='CASCADE'), nullable=False),
        sa.Column('storage_key', sa.Text(), nullable=True),
        sa.Column('duration', sa.Float(), nullable=True),
        sa.Column('width', sa.Integer(), nullable=True),
        sa.Column('height', sa.Integer(), nullable=True),
        sa.Column('fps', sa.Float(), nullable=True),
        sa.Column('codec', sa.String(length=32), nullable=True),
        sa.Column('language', sa.String(length=16), nullable=True),
    )
    op.create_index(op.f('ix_videos_project_id'), 'videos', ['project_id'], unique=False)

    # ── Table: transcripts ────────────────────────────────────────────────────
    op.create_table(
        'transcripts',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('video_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('videos.id', ondelete='CASCADE'), nullable=False),
        sa.Column('data', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('model', sa.String(length=64), nullable=True),
        sa.Column('created_at', postgresql.TIMESTAMP(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index(op.f('ix_transcripts_video_id'), 'transcripts', ['video_id'], unique=False)

    # ── Table: clips ──────────────────────────────────────────────────────────
    op.create_table(
        'clips',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('project_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('projects.id', ondelete='CASCADE'), nullable=False),
        sa.Column('start', sa.Float(), nullable=False),
        sa.Column('end', sa.Float(), nullable=False),
        sa.Column('score', sa.Integer(), nullable=True),
        sa.Column('score_breakdown', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('hook', sa.Text(), nullable=True),
        sa.Column('title', sa.Text(), nullable=True),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('hashtags', postgresql.ARRAY(sa.Text()), nullable=True),
        sa.Column('status', clipstatus_enum, nullable=False, server_default='pending'),
        sa.Column('selected', sa.Boolean(), nullable=False, server_default=sa.text('true')),
    )
    op.create_index(op.f('ix_clips_project_id'), 'clips', ['project_id'], unique=False)
    op.create_index(op.f('ix_clips_status'), 'clips', ['status'], unique=False)

    # ── Table: brand_kits ─────────────────────────────────────────────────────
    op.create_table(
        'brand_kits',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('name', sa.Text(), nullable=False),
        sa.Column('logo_key', sa.Text(), nullable=True),
        sa.Column('fonts', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('colors', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('default_caption_style', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )

    # ── Table: render_settings ────────────────────────────────────────────────
    op.create_table(
        'render_settings',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('clip_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('clips.id', ondelete='CASCADE'), nullable=False),
        sa.Column('layout', layout_enum, nullable=False, server_default='vertical'),
        sa.Column('caption_style', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('crop_keyframes', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('brand_kit_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('brand_kits.id', ondelete='SET NULL'), nullable=True),
    )
    op.create_index(op.f('ix_render_settings_clip_id'), 'render_settings', ['clip_id'], unique=True)

    # ── Table: renders ────────────────────────────────────────────────────────
    op.create_table(
        'renders',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('clip_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('clips.id', ondelete='CASCADE'), nullable=False),
        sa.Column('storage_key', sa.Text(), nullable=True),
        sa.Column('resolution', sa.String(length=16), nullable=True),
        sa.Column('size_bytes', sa.BigInteger(), nullable=True),
        sa.Column('created_at', postgresql.TIMESTAMP(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index(op.f('ix_renders_clip_id'), 'renders', ['clip_id'], unique=False)

    # ── Table: jobs ───────────────────────────────────────────────────────────
    op.create_table(
        'jobs',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('project_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('projects.id', ondelete='CASCADE'), nullable=False),
        sa.Column('stage', sa.String(length=32), nullable=True),
        sa.Column('status', jobstatus_enum, nullable=False, server_default='queued'),
        sa.Column('progress', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('error', sa.Text(), nullable=True),
        sa.Column('attempts', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('started_at', postgresql.TIMESTAMP(timezone=True), nullable=True),
        sa.Column('finished_at', postgresql.TIMESTAMP(timezone=True), nullable=True),
    )
    op.create_index(op.f('ix_jobs_project_id'), 'jobs', ['project_id'], unique=False)
    op.create_index(op.f('ix_jobs_status'), 'jobs', ['status'], unique=False)


def downgrade() -> None:
    op.drop_table('jobs')
    op.drop_table('renders')
    op.drop_table('render_settings')
    op.drop_table('brand_kits')
    op.drop_table('clips')
    op.drop_table('transcripts')
    op.drop_table('videos')
    op.drop_table('projects')

    op.execute('DROP TYPE IF EXISTS layout;')
    op.execute('DROP TYPE IF EXISTS jobstatus;')
    op.execute('DROP TYPE IF EXISTS clipstatus;')
    op.execute('DROP TYPE IF EXISTS projectstatus;')
    op.execute('DROP TYPE IF EXISTS sourcetype;')
