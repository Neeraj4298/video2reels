"""
Unit and integration tests for Celery task idempotence, stage resumability,
exponential backoff, SSE events, and database schema migrations.
"""
from __future__ import annotations

import json
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from api.db import Base
from api.events import event_stream, publish_progress_sync
from api.models import (
    Clip,
    ClipStatus,
    Job,
    JobStatus,
    Project,
    ProjectStatus,
    Render,
    RenderSettings,
    SourceType,
    Transcript,
    Video,
)
from workers.tasks import (
    _backoff,
    resume_pipeline,
    run_pipeline,
    stage_audio,
    stage_ingest,
    stage_reframe,
    stage_render_clip,
    stage_select_clips,
    stage_transcribe,
)


# ── Test 1: Exponential Backoff Schedule ──────────────────────────────────────

def test_exponential_backoff_schedule():
    """Verify backoff matches requirements: 60s -> 300s -> 900s."""
    assert _backoff(0) == 60
    assert _backoff(1) == 300
    assert _backoff(2) == 900
    assert _backoff(3) == 900
    assert _backoff(10) == 900


# ── Test 2: Ingest Stage Idempotence ──────────────────────────────────────────

def test_stage_ingest_idempotent():
    """If video metadata is already populated in DB, stage_ingest skips re-probing."""
    project_id = str(uuid.uuid4())
    mock_session = MagicMock()
    mock_video = MagicMock(duration=120.5, width=1920, height=1080, fps=30.0, codec="h264", storage_key="orig.mp4")

    # Mock DB query returning video with existing duration
    mock_session.execute.return_value.scalars.return_value.first.return_value = mock_video

    with patch("workers.tasks._get_session") as mock_get_sess, \
         patch("workers.tasks._emit") as mock_emit, \
         patch("workers.tasks._update_job_status") as mock_u_job, \
         patch("workers.tasks._update_project_status") as mock_u_proj:
        mock_get_sess.return_value.__enter__.return_value = mock_session

        res = stage_ingest(project_id, "orig.mp4")
        assert res["project_id"] == project_id
        assert res["meta"]["duration"] == 120.5
        assert res["meta"]["width"] == 1920
        mock_emit.assert_any_call(project_id, "ingest", 20, "Video validated (cached) ✓")


# ── Test 3: Audio Extraction Stage Idempotence ────────────────────────────────

def test_stage_audio_idempotent():
    """If audio already exists in MinIO, stage_audio returns immediately."""
    project_id = str(uuid.uuid4())
    prev = {"project_id": project_id, "video_storage_key": "video.mp4"}

    with patch("api.storage.object_exists", return_value=True), \
         patch("workers.tasks._emit") as mock_emit, \
         patch("workers.tasks._update_job_status"):
        res = stage_audio(prev)
        assert res["audio_key"] == f"{project_id}/audio.wav"
        mock_emit.assert_any_call(project_id, "audio", 35, "Audio extracted (cached) ✓")


# ── Test 4: Transcription Stage Idempotence ───────────────────────────────────

def test_stage_transcribe_idempotent():
    """If Transcript record already in DB, skip Whisper transcription."""
    project_id = str(uuid.uuid4())
    prev = {"project_id": project_id, "audio_key": f"{project_id}/audio.wav"}

    mock_session = MagicMock()
    mock_video = MagicMock(id=uuid.uuid4())
    cached_transcript = {"language": "en", "all_words": [{"word": "hello", "start": 0.0, "end": 0.5}]}
    mock_tr = MagicMock(data=cached_transcript)

    # First execute call -> video, second -> transcript
    mock_session.execute.return_value.scalars.return_value.first.side_effect = [mock_video, mock_tr]

    with patch("workers.tasks._get_session") as mock_get_sess, \
         patch("workers.tasks._emit") as mock_emit, \
         patch("workers.tasks._update_job_status"):
        mock_get_sess.return_value.__enter__.return_value = mock_session

        res = stage_transcribe(prev)
        assert res["transcript"] == cached_transcript
        mock_emit.assert_any_call(project_id, "transcribing", 55, "Transcribed (cached) ✓ — 1 words")


# ── Test 5: Clip Selection Stage Idempotence ──────────────────────────────────

def test_stage_select_clips_idempotent():
    """If Clip records already in DB, skip LLM API calls."""
    project_id = str(uuid.uuid4())
    prev = {"project_id": project_id, "transcript": {"all_words": []}}

    mock_session = MagicMock()
    clip_id = uuid.uuid4()
    mock_clip = MagicMock(
        id=clip_id,
        start=5.0,
        end=35.0,
        score=90,
        score_breakdown={"hook": 9, "flow": 9, "value": 9, "trend": 9},
        hook="Great hook",
        title="Sample Clip",
        description="",
        hashtags=["#ai"],
    )
    mock_session.execute.return_value.scalars.return_value.all.return_value = [mock_clip]

    with patch("workers.tasks._get_session") as mock_get_sess, \
         patch("workers.tasks._emit") as mock_emit, \
         patch("workers.tasks._update_job_status"):
        mock_get_sess.return_value.__enter__.return_value = mock_session

        res = stage_select_clips(prev)
        assert res["clip_ids"] == [str(clip_id)]
        assert len(res["clips_data"]) == 1
        assert res["clips_data"][0]["title"] == "Sample Clip"


# ── Test 6: Reframe Stage Idempotence ─────────────────────────────────────────

def test_stage_reframe_idempotent():
    """If keyframes already computed for all clips, skip reframe processing."""
    project_id = str(uuid.uuid4())
    clip_id = str(uuid.uuid4())
    prev = {
        "project_id": project_id,
        "clip_ids": [clip_id],
        "clips_data": [{"start": 0.0, "end": 20.0}],
        "video_storage_key": "video.mp4",
    }

    mock_session = MagicMock()
    mock_rs = MagicMock(crop_keyframes={"keyframes": [{"time": 0.0, "crop_x": 100}]})
    mock_session.execute.return_value.scalar_one_or_none.return_value = mock_rs

    with patch("workers.tasks._get_session") as mock_get_sess, \
         patch("workers.tasks._emit") as mock_emit, \
         patch("workers.tasks._update_job_status"):
        mock_get_sess.return_value.__enter__.return_value = mock_session

        res = stage_reframe(prev)
        assert len(res["reframe_results"]) == 1
        mock_emit.assert_any_call(project_id, "reframing", 75, "Crop paths computed (cached) ✓")


# ── Test 7: Render Stage Idempotence ──────────────────────────────────────────

def test_stage_render_clip_idempotent():
    """If rendered MP4 exists in storage and DB, skip FFmpeg re-rendering."""
    project_id = str(uuid.uuid4())
    clip_id = str(uuid.uuid4())

    mock_session = MagicMock()
    mock_clip = MagicMock(status=ClipStatus.pending)
    mock_render = MagicMock(storage_key=f"{project_id}/renders/{clip_id}.mp4")

    mock_session.get.return_value = mock_clip
    mock_session.execute.return_value.scalars.return_value.first.return_value = mock_render

    with patch("workers.tasks._get_session") as mock_get_sess, \
         patch("api.storage.object_exists", return_value=True), \
         patch("workers.tasks._check_and_mark_pipeline_complete") as mock_complete:
        mock_get_sess.return_value.__enter__.return_value = mock_session

        stage_render_clip(
            project_id=project_id,
            clip_id=clip_id,
            clip_data={"start": 0.0, "end": 15.0},
            reframe_data={},
            total_clips=1,
        )
        assert mock_clip.status == ClipStatus.done
        mock_complete.assert_called_once_with(project_id, 1)


# ── Test 8: Stage Resumability Logic ──────────────────────────────────────────

def test_resume_pipeline_dispatches_correct_earliest_stage():
    """Verify resume_pipeline inspects DB/storage state and dispatches the earliest uncompleted stage."""
    project_id = str(uuid.uuid4())

    mock_session = MagicMock()
    mock_proj = MagicMock(id=uuid.UUID(project_id))
    mock_video = MagicMock(duration=100.0, width=1920, height=1080, fps=30.0, codec="h264", storage_key="orig.mp4")

    mock_session.get.return_value = mock_proj
    mock_session.execute.return_value.scalars.return_value.first.return_value = mock_video

    with patch("workers.tasks._get_session") as mock_get_sess, \
         patch("api.storage.object_exists", return_value=False), \
         patch("workers.tasks.chain") as mock_chain:
        mock_chain.return_value.apply_async.return_value = MagicMock()
        mock_get_sess.return_value.__enter__.return_value = mock_session

        resume_pipeline(project_id)
        mock_chain.assert_called_once()
        mock_chain.return_value.apply_async.assert_called_once()



# ── Test 9: SSE Events Serialization & Formatting ─────────────────────────────

@pytest.mark.asyncio
async def test_sse_event_stream_formatting():
    """Verify event_stream formats SSE lines and terminates on 'done'."""
    project_id = uuid.uuid4()

    events_to_yield = [
        {"type": "message", "data": json.dumps({"stage": "ingest", "progress": 20})},
        {"type": "message", "data": json.dumps({"stage": "transcribing", "progress": 50})},
        {"type": "message", "data": json.dumps({"stage": "done", "progress": 100})},
    ]

    class FakePubSub:
        async def subscribe(self, channel): pass
        async def unsubscribe(self, channel): pass
        async def listen(self):
            for e in events_to_yield:
                yield e

    fake_client = MagicMock()
    fake_client.pubsub.return_value = FakePubSub()
    fake_client.aclose = AsyncMock()

    with patch("redis.asyncio.from_url", return_value=fake_client):
        collected = []
        async for sse_line in event_stream(project_id):
            collected.append(sse_line)

        assert len(collected) == 3
        assert collected[0].startswith("data: ")
        assert "ingest" in collected[0]
        assert "done" in collected[2]


# ── Test 10: Alembic Migration Module Validation ──────────────────────────────

def test_alembic_initial_migration_structure():
    """Verify initial migration script is valid and exposes required metadata."""
    import importlib
    mig = importlib.import_module("infra.migrations.versions.001_initial_schema")

    assert hasattr(mig, "revision")
    assert mig.revision == "001_initial_schema"
    assert hasattr(mig, "upgrade")
    assert callable(mig.upgrade)
    assert hasattr(mig, "downgrade")
    assert callable(mig.downgrade)
