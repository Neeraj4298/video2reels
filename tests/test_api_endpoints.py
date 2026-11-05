"""
Integration & unit tests for FastAPI REST endpoints and SSE events.
Uses in-memory async SQLite database and mocked Celery / Redis / MinIO clients.
"""
from __future__ import annotations

import uuid
from typing import AsyncGenerator
from unittest.mock import MagicMock, patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from api.db import Base, get_db
from api.main import app
from api.models import (
    BrandKit,
    Clip,
    ClipStatus,
    Job,
    JobStatus,
    Layout,
    Project,
    ProjectStatus,
    Render,
    RenderSettings,
    SourceType,
    Video,
    Transcript,
)

# In-memory async SQLite engine for testing
TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"


@pytest_asyncio.fixture
async def test_db() -> AsyncGenerator[AsyncSession, None]:
    """Create a fresh in-memory database and session for each test."""
    engine = create_async_engine(TEST_DATABASE_URL, echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(
        bind=engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )

    async with session_factory() as session:
        yield session

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest_asyncio.fixture
async def client(test_db: AsyncSession) -> AsyncGenerator[AsyncClient, None]:
    """Async HTTP test client with database dependency override."""
    async def override_get_db() -> AsyncGenerator[AsyncSession, None]:
        yield test_db

    app.dependency_overrides[get_db] = override_get_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()


# ── Health Endpoint ───────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_health_check(client: AsyncClient):
    response = await client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert "version" in data


# ── Project Endpoints ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_create_project_with_url(client: AsyncClient):
    with patch("api.routers.projects.dispatch_pipeline") as mock_dispatch:
        mock_dispatch.return_value = "celery-task-123"
        response = await client.post(
            "/api/projects",
            json={"name": "YouTube Project", "source_url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ"},
        )
        assert response.status_code == 201
        data = response.json()
        assert data["name"] == "YouTube Project"
        assert data["source_type"] == "url"
        assert data["status"] == "processing"
        mock_dispatch.assert_called_once()


@pytest.mark.asyncio
async def test_create_project_upload_mode(client: AsyncClient):
    response = await client.post(
        "/api/projects",
        json={"name": "Direct Upload Project"},
    )
    assert response.status_code == 201
    data = response.json()
    assert data["name"] == "Direct Upload Project"
    assert data["source_type"] == "upload"
    assert data["status"] == "pending"


@pytest.mark.asyncio
async def test_list_and_get_projects(client: AsyncClient, test_db: AsyncSession):
    proj_id = uuid.uuid4()
    proj = Project(
        id=proj_id,
        name="Listed Project",
        source_type=SourceType.upload,
        status=ProjectStatus.processing,
    )
    test_db.add(proj)
    await test_db.commit()

    # Test list
    res_list = await client.get("/api/projects")
    assert res_list.status_code == 200
    items = res_list.json()
    assert any(p["id"] == str(proj_id) for p in items)

    # Test get detail
    res_detail = await client.get(f"/api/projects/{proj_id}")
    assert res_detail.status_code == 200
    detail = res_detail.json()
    assert detail["id"] == str(proj_id)
    assert detail["name"] == "Listed Project"
    assert "clips" in detail
    assert "jobs" in detail


@pytest.mark.asyncio
async def test_delete_project(client: AsyncClient, test_db: AsyncSession):
    proj_id = uuid.uuid4()
    proj = Project(
        id=proj_id,
        name="To Delete",
        source_type=SourceType.upload,
        status=ProjectStatus.done,
    )
    test_db.add(proj)
    await test_db.commit()

    with patch("api.routers.projects.delete_prefix") as mock_del:
        res = await client.delete(f"/api/projects/{proj_id}")
        assert res.status_code == 204
        assert mock_del.call_count >= 1

    # Verify not found after delete
    res_get = await client.get(f"/api/projects/{proj_id}")
    assert res_get.status_code == 404


@pytest.mark.asyncio
async def test_resume_project(client: AsyncClient, test_db: AsyncSession):
    proj_id = uuid.uuid4()
    proj = Project(
        id=proj_id,
        name="To Resume",
        source_type=SourceType.url,
        status=ProjectStatus.failed,
    )
    test_db.add(proj)
    await test_db.commit()

    with patch("api.routers.projects.dispatch_resume") as mock_resume:
        mock_resume.return_value = "celery-resume-456"
        res = await client.post(f"/api/projects/{proj_id}/resume")
        assert res.status_code == 202
        data = res.json()
        assert data["message"] == "Pipeline resumed"
        assert data["task_id"] == "celery-resume-456"
        mock_resume.assert_called_once_with(proj_id)


# ── Upload Endpoints ──────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_sign_upload(client: AsyncClient, test_db: AsyncSession):
    proj_id = uuid.uuid4()
    proj = Project(id=proj_id, name="Upload Test", source_type=SourceType.upload)
    test_db.add(proj)
    await test_db.commit()

    with patch("api.routers.uploads.presigned_put_url") as mock_sign:
        mock_sign.return_value = "http://minio/upload-signed-url"
        res = await client.post(
            "/api/uploads/sign",
            json={"project_id": str(proj_id), "filename": "video.mp4"},
        )
        assert res.status_code == 200
        data = res.json()
        assert data["upload_url"] == "http://minio/upload-signed-url"
        assert str(proj_id) in data["storage_key"]


@pytest.mark.asyncio
async def test_confirm_upload(client: AsyncClient, test_db: AsyncSession):
    proj_id = uuid.uuid4()
    proj = Project(id=proj_id, name="Confirm Test", source_type=SourceType.upload)
    test_db.add(proj)
    await test_db.commit()

    with patch("api.routers.uploads.object_exists", return_value=True), \
         patch("api.routers.uploads.dispatch_pipeline") as mock_dispatch:
        mock_dispatch.return_value = "task-confirm-789"
        res = await client.post(
            "/api/uploads/confirm",
            json={"project_id": str(proj_id), "storage_key": f"{proj_id}/test.mp4"},
        )
        assert res.status_code == 202
        assert res.json()["message"] == "Pipeline started"
        mock_dispatch.assert_called_once()


# ── Clip Endpoints ────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_list_and_patch_clips(client: AsyncClient, test_db: AsyncSession):
    proj_id = uuid.uuid4()
    proj = Project(id=proj_id, name="Clip Test", source_type=SourceType.upload)
    test_db.add(proj)

    clip_id = uuid.uuid4()
    clip = Clip(
        id=clip_id,
        project_id=proj_id,
        start=10.0,
        end=45.0,
        score=88,
        title="Original Hook",
        status=ClipStatus.pending,
    )
    test_db.add(clip)
    await test_db.commit()

    # List clips
    res_list = await client.get(f"/api/projects/{proj_id}/clips")
    assert res_list.status_code == 200
    clips = res_list.json()
    assert len(clips) == 1
    assert clips[0]["id"] == str(clip_id)

    # Patch clip trim & title
    res_patch = await client.patch(
        f"/api/clips/{clip_id}",
        json={"title": "Updated Hook", "start": 12.5, "end": 42.0},
    )
    assert res_patch.status_code == 200
    patched = res_patch.json()
    assert patched["title"] == "Updated Hook"
    assert patched["start"] == 12.5
    assert patched["end"] == 42.0


@pytest.mark.asyncio
async def test_render_and_download_clip(client: AsyncClient, test_db: AsyncSession):
    proj_id = uuid.uuid4()
    proj = Project(id=proj_id, name="Render Test", source_type=SourceType.upload)
    test_db.add(proj)

    clip_id = uuid.uuid4()
    clip = Clip(
        id=clip_id,
        project_id=proj_id,
        start=0.0,
        end=30.0,
        score=92,
        status=ClipStatus.pending,
    )
    test_db.add(clip)

    render_record = Render(
        clip_id=clip_id,
        storage_key=f"{proj_id}/renders/{clip_id}.mp4",
        resolution="1080x1920",
        size_bytes=1048576,
    )
    test_db.add(render_record)
    await test_db.commit()

    # Queue re-render
    with patch("api.routers.clips.dispatch_render") as mock_dispatch:
        mock_dispatch.return_value = "render-task-123"
        res_render = await client.post(
            f"/api/clips/{clip_id}/render",
            json={"layout": "vertical"},
        )
        assert res_render.status_code == 200
        assert res_render.json()["task_id"] == "render-task-123"

    # Download presigned URL
    with patch("api.routers.clips.presigned_get_url") as mock_url:
        mock_url.return_value = "http://minio/download-signed-url"
        res_down = await client.get(f"/api/clips/{clip_id}/download")
        assert res_down.status_code == 200
        assert res_down.json()["download_url"] == "http://minio/download-signed-url"


# ── Brand Kits Endpoints ──────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_brand_kits_crud(client: AsyncClient):
    # Create brand kit
    res_create = await client.post(
        "/api/brand-kits",
        json={
            "name": "Acme Brand",
            "colors": {"primary": "#FF5733", "accent": "#FFE800"},
            "fonts": {"primary": "Montserrat"},
        },
    )
    assert res_create.status_code == 201
    bk = res_create.json()
    bk_id = bk["id"]
    assert bk["name"] == "Acme Brand"

    # List brand kits
    res_list = await client.get("/api/brand-kits")
    assert res_list.status_code == 200
    assert any(b["id"] == bk_id for b in res_list.json())

    # Update brand kit
    res_patch = await client.patch(
        f"/api/brand-kits/{bk_id}",
        json={"name": "Acme Updated"},
    )
    assert res_patch.status_code == 200
    assert res_patch.json()["name"] == "Acme Updated"

    # Delete brand kit
    res_del = await client.delete(f"/api/brand-kits/{bk_id}")
    assert res_del.status_code == 204


# ── Transcript & Subtitle Endpoints (Phase 4) ─────────────────────────────────

@pytest.mark.asyncio
async def test_transcript_and_subtitles_endpoints(client: AsyncClient, test_db: AsyncSession):
    proj_id = uuid.uuid4()
    proj = Project(id=proj_id, name="Transcript Test", source_type=SourceType.upload)
    test_db.add(proj)

    video_id = uuid.uuid4()
    video = Video(id=video_id, project_id=proj_id, duration=60.0)
    test_db.add(video)

    sample_transcript_data = {
        "language": "en",
        "duration": 60.0,
        "segments": [
            {
                "start": 0.0,
                "end": 8.0,
                "text": "This is a great moment you need to see.",
                "words": [
                    {"w": "This", "s": 0.5, "e": 0.9, "p": 0.98},
                    {"w": "is", "s": 1.0, "e": 1.2, "p": 0.99},
                    {"w": "a", "s": 1.3, "e": 1.4, "p": 0.95},
                    {"w": "great", "s": 1.5, "e": 2.1, "p": 0.99},
                    {"w": "moment", "s": 2.2, "e": 2.8, "p": 0.97},
                    {"w": "you", "s": 3.0, "e": 3.3, "p": 0.99},
                    {"w": "need", "s": 3.4, "e": 3.8, "p": 0.98},
                    {"w": "to", "s": 3.9, "e": 4.1, "p": 0.99},
                    {"w": "see.", "s": 4.2, "e": 4.8, "p": 0.96},
                ],
            }
        ],
    }

    transcript = Transcript(video_id=video_id, data=sample_transcript_data, model="faster-whisper-base")
    test_db.add(transcript)

    clip_id = uuid.uuid4()
    clip = Clip(
        id=clip_id,
        project_id=proj_id,
        start=0.0,
        end=5.0,
        score=95,
        title="Great Moment",
        status=ClipStatus.done,
    )
    test_db.add(clip)
    await test_db.commit()

    # 1. Project Transcript
    res_tr = await client.get(f"/api/projects/{proj_id}/transcript")
    assert res_tr.status_code == 200
    assert "segments" in res_tr.json()

    # 2. Clip Transcript
    res_clip_tr = await client.get(f"/api/clips/{clip_id}/transcript")
    assert res_clip_tr.status_code == 200
    clip_tr_data = res_clip_tr.json()
    assert clip_tr_data["clip_id"] == str(clip_id)
    assert len(clip_tr_data["words"]) > 0
    assert "great moment" in clip_tr_data["text"].lower()

    # 3. Subtitles SRT
    res_srt = await client.get(f"/api/clips/{clip_id}/subtitles?format=srt")
    assert res_srt.status_code == 200
    assert "text/plain" in res_srt.headers["content-type"]
    assert "-->" in res_srt.text
    assert "attachment" in res_srt.headers["content-disposition"]

    # 4. Subtitles VTT
    res_vtt = await client.get(f"/api/clips/{clip_id}/subtitles?format=vtt")
    assert res_vtt.status_code == 200
    assert "text/vtt" in res_vtt.headers["content-type"]
    assert res_vtt.text.startswith("WEBVTT")


# ── Phase 5 Tests ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_export_project_zip(client: AsyncClient, test_db: AsyncSession):
    import io
    import zipfile

    proj_id = uuid.uuid4()
    proj = Project(id=proj_id, name="Zip Export Test", source_type=SourceType.upload)
    test_db.add(proj)

    video_id = uuid.uuid4()
    video = Video(id=video_id, project_id=proj_id, duration=45.0)
    test_db.add(video)

    sample_transcript_data = {
        "language": "en",
        "duration": 45.0,
        "segments": [
            {
                "start": 0.0,
                "end": 10.0,
                "text": "Export test segment text.",
                "words": [
                    {"w": "Export", "s": 0.0, "e": 1.0, "p": 1.0},
                    {"w": "test", "s": 1.0, "e": 2.0, "p": 1.0},
                ],
            }
        ],
    }
    transcript = Transcript(video_id=video_id, data=sample_transcript_data, model="faster-whisper-base")
    test_db.add(transcript)

    clip_id = uuid.uuid4()
    clip = Clip(
        id=clip_id,
        project_id=proj_id,
        start=0.0,
        end=10.0,
        score=92,
        title="Epic Reel",
        hook="Must Watch",
        description="Great reel about exporting",
        hashtags=["#reels", "#viral"],
        status=ClipStatus.done,
    )
    test_db.add(clip)

    render = Render(
        id=uuid.uuid4(),
        clip_id=clip_id,
        storage_key=f"{proj_id}/renders/{clip_id}.mp4",
        resolution="1080x1920",
    )
    test_db.add(render)
    await test_db.commit()

    with patch("api.routers.projects.object_exists", return_value=True), \
         patch("api.routers.projects.download_bytes", return_value=b"fake-mp4-video-bytes"):
        res = await client.get(f"/api/projects/{proj_id}/export/zip")
        assert res.status_code == 200
        assert res.headers["content-type"] == "application/zip"
        assert "attachment" in res.headers["content-disposition"]

        # Verify ZIP archive contents
        zf = zipfile.ZipFile(io.BytesIO(res.content))
        file_list = zf.namelist()
        assert "project_summary.json" in file_list
        assert any("metadata.json" in name for name in file_list)
        assert any("subtitles.srt" in name for name in file_list)
        assert any("video.mp4" in name for name in file_list)


@pytest.mark.asyncio
async def test_reclip_project(client: AsyncClient, test_db: AsyncSession):
    proj_id = uuid.uuid4()
    proj = Project(id=proj_id, name="Reclip Test", source_type=SourceType.upload)
    test_db.add(proj)
    await test_db.commit()

    with patch("api.routers.projects.dispatch_reclip") as mock_reclip:
        mock_reclip.return_value = "celery-reclip-789"
        res = await client.post(
            f"/api/projects/{proj_id}/reclip",
            json={"user_prompt": "focus on revenue metrics"},
        )
        assert res.status_code == 202
        data = res.json()
        assert data["message"] == "Re-clipping initiated"
        assert data["task_id"] == "celery-reclip-789"
        assert data["user_prompt"] == "focus on revenue metrics"
        mock_reclip.assert_called_once_with(proj_id, user_prompt="focus on revenue metrics")


@pytest.mark.asyncio
async def test_clip_metadata_regenerate(client: AsyncClient, test_db: AsyncSession):
    proj_id = uuid.uuid4()
    proj = Project(id=proj_id, name="Meta Test", source_type=SourceType.upload)
    test_db.add(proj)

    video_id = uuid.uuid4()
    video = Video(id=video_id, project_id=proj_id, duration=30.0)
    test_db.add(video)

    sample_transcript_data = {
        "language": "en",
        "duration": 30.0,
        "segments": [
            {
                "start": 0.0,
                "end": 10.0,
                "text": "How we scaled to one million users in three months.",
                "words": [
                    {"w": "How", "s": 0.0, "e": 0.5, "p": 1.0},
                    {"w": "we", "s": 0.5, "e": 0.8, "p": 1.0},
                    {"w": "scaled", "s": 0.8, "e": 1.5, "p": 1.0},
                ],
            }
        ],
    }
    transcript = Transcript(video_id=video_id, data=sample_transcript_data, model="faster-whisper-base")
    test_db.add(transcript)

    clip_id = uuid.uuid4()
    clip = Clip(
        id=clip_id,
        project_id=proj_id,
        start=0.0,
        end=10.0,
        score=90,
        title="Old Title",
        status=ClipStatus.done,
    )
    test_db.add(clip)
    await test_db.commit()

    res = await client.post(f"/api/clips/{clip_id}/metadata")
    assert res.status_code == 200
    data = res.json()
    assert "title" in data
    assert "description" in data
    assert "hashtags" in data
    assert len(data["hashtags"]) > 0


@pytest.mark.asyncio
async def test_publish_clip_social(client: AsyncClient, test_db: AsyncSession):
    proj_id = uuid.uuid4()
    proj = Project(id=proj_id, name="Publish Test", source_type=SourceType.upload)
    test_db.add(proj)

    clip_id = uuid.uuid4()
    clip = Clip(
        id=clip_id,
        project_id=proj_id,
        start=0.0,
        end=15.0,
        score=94,
        title="Viral Hit",
        status=ClipStatus.done,
    )
    test_db.add(clip)
    await test_db.commit()

    # 1. YouTube Shorts immediate publish
    res_yt = await client.post(
        f"/api/clips/{clip_id}/publish",
        json={"platform": "youtube", "title": "Viral Hit", "description": "Check this out!"},
    )
    assert res_yt.status_code == 200
    assert res_yt.json()["status"] == "published"
    assert "YouTube Shorts" in res_yt.json()["message"]

    # 2. TikTok scheduled publish
    res_tt = await client.post(
        f"/api/clips/{clip_id}/publish",
        json={
            "platform": "tiktok",
            "title": "Viral Hit",
            "scheduled_at": "2026-11-05T15:00:00Z",
        },
    )
    assert res_tt.status_code == 200
    assert res_tt.json()["status"] == "scheduled"
    assert "TikTok" in res_tt.json()["message"]

    # 3. Invalid platform rejected
    res_inv = await client.post(
        f"/api/clips/{clip_id}/publish",
        json={"platform": "unknown_app"},
    )
    assert res_inv.status_code == 400


@pytest.mark.asyncio
async def test_brand_kit_logo_upload(client: AsyncClient, test_db: AsyncSession):
    kit = BrandKit(name="Acme Brand")
    test_db.add(kit)
    await test_db.commit()

    with patch("api.routers.brand_kits.upload_bytes") as mock_upload:
        fake_png = b"\x89PNG\r\n\x1a\n\x00\x00fakeimagecontent"
        res = await client.post(
            f"/api/brand-kits/{kit.id}/logo",
            files={"file": ("logo.png", fake_png, "image/png")},
        )
        assert res.status_code == 200
        data = res.json()
        assert f"brand_kits/{kit.id}/logo.png" in data["logo_key"]
        mock_upload.assert_called_once()


@pytest.mark.asyncio
async def test_ui_presigned_upload_and_complete_endpoints(client: AsyncClient):
    # Create upload project
    create_res = await client.post("/api/projects", json={"name": "Browser Upload Project"})
    assert create_res.status_code == 201
    proj_id = create_res.json()["id"]

    with patch("api.routers.uploads.presigned_put_url", return_value="http://minio:9000/originals/presigned-put"):
        presign_res = await client.get(
            f"/api/uploads/presigned?project_id={proj_id}&filename=demo.mp4"
        )
        assert presign_res.status_code == 200
        pdata = presign_res.json()
        assert pdata["project_id"] == proj_id
        assert pdata["upload_url"] == "http://minio:9000/originals/presigned-put"
        storage_key = pdata["storage_key"]

    with patch("api.routers.uploads.object_exists", return_value=True), \
         patch("api.routers.uploads.dispatch_pipeline") as mock_dispatch:
        complete_res = await client.post(
            "/api/uploads/complete",
            json={"project_id": proj_id, "storage_key": storage_key},
        )
        assert complete_res.status_code == 202
        mock_dispatch.assert_called_once()


@pytest.mark.asyncio
async def test_create_project_forwards_user_prompt(client: AsyncClient):
    with patch("api.routers.projects.dispatch_pipeline") as mock_dispatch:
        mock_dispatch.return_value = "task-prompt-1"
        res = await client.post(
            "/api/projects",
            json={
                "name": "Prompted URL Project",
                "source_url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
                "user_prompt": "focus on AI agents and pricing",
            },
        )
        assert res.status_code == 201
        _, kwargs = mock_dispatch.call_args
        assert kwargs.get("user_prompt") == "focus on AI agents and pricing"


