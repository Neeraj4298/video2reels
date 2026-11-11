"""
Comprehensive test suite for all OpusClip-class upgrades (suggestions.md & opusclip/*):
  - Workstream 1: Storage path traversal sanitization, SSRF URL validation, CFR detection,
    FFmpeg filter path escaping, and removal of fabricated WAV fallback.
  - Workstream 2: StageRun & per-stage Job persistence, Artifact-based transcript passing,
    Alembic migration 002, and Credit calculation rules.
  - Workstream 3: Stable word IDs (w_000001), SRT override parsing, 10 Hz Signals layer,
    word-ID clip selection, dependent-clause boundary refinement, ASD + 1.5s hysteresis,
    layout classifier, real 2-speaker split-screen crop, FFmpeg sendcmd crop script,
    and true geometric face_in_frame_ratio.
  - Workstream 4: Canonical EDL compiler, word-deletion cut stitching, 15ms audio crossfades,
    auto-emoji captions, excluded_word_indices & word_overrides persistence, and FCP7 XML export.
  - Workstream 5: Evaluation harness metrics (WER, onset error, DER, IoU, boundaries,
    reframing, acceptance rate) & Platform/Credits/Feedback/MCP API endpoints.
"""
from __future__ import annotations

import io
import json
import uuid
import xml.etree.ElementTree as ET
import zipfile
from typing import AsyncGenerator
from unittest.mock import patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from api.db import Base, get_db
from api.main import app
from api.models import Clip, ClipStatus, Project, ProjectStatus, SourceType, Transcript as TranscriptModel, Video
from api.storage import sanitize_storage_key
from workers.captions import CaptionStyle, generate_captions, generate_srt, inject_auto_emojis
from workers.edl import build_edl_audio_filter, compile_edl_from_clip
from workers.eval_harness import (
    compute_caption_onset_error_ms,
    compute_clip_acceptance_rate,
    compute_der,
    compute_highlight_overlap_iou,
    compute_wer,
    run_golden_eval_suite,
)
from workers.ingest import compute_video_credits, needs_cfr_normalization, validate_source_url
from workers.reframe import (
    CropKeyframe,
    build_split_screen_filter_complex,
    classify_layout,
    generate_sendcmd_crop_script,
    select_active_speaker_face,
)
from workers.render import escape_ffmpeg_filter_path
from workers.select_clips import (
    Clip as WorkerClip,
    ScoreBreakdown,
    select_clips,
    starts_with_dependent_clause,
)
from workers.signals import compute_signals
from workers.transcribe import Segment, Transcript, Word, transcript_from_srt
from workers.xml_export import build_nle_export_zip, generate_fcpxml_v4


class TestSecurityAndHardening:
    def test_sanitize_storage_key_blocks_traversal(self):
        with pytest.raises(ValueError):
            sanitize_storage_key("video2reels-renders", "../../etc/passwd")
        with pytest.raises(ValueError):
            sanitize_storage_key("../bucket", "clip.mp4")
        with pytest.raises(ValueError):
            sanitize_storage_key("bucket", "foo\x00bar.mp4")

        b, k = sanitize_storage_key("video2reels-renders", "proj123/renders/clip1.mp4")
        assert b == "video2reels-renders"
        assert k == "proj123/renders/clip1.mp4"

    def test_validate_source_url_ssrf_protection(self):
        assert validate_source_url("https://www.youtube.com/watch?v=dQw4w9WgXcQ").startswith("https://")
        for bad_url in [
            "file:///etc/passwd",
            "ftp://example.com/video.mp4",
            "http://localhost:8000/internal",
            "http://127.0.0.1/admin",
            "http://169.254.169.254/latest/meta-data/",
            "http://192.168.1.10/private.mp4",
            "http://10.0.0.5/video.mp4",
        ]:
            with pytest.raises(ValueError):
                validate_source_url(bad_url)

    def test_cfr_detection_and_credit_math(self):
        assert needs_cfr_normalization(29.97) is True
        assert needs_cfr_normalization(30.0, "30/1", "30/1") is False
        assert compute_video_credits(25.0) == 1
        assert compute_video_credits(270.0) == 4

    def test_escape_ffmpeg_filter_path(self):
        escaped = escape_ffmpeg_filter_path("/tmp/dir:with'special[chars]/sub.ass")
        assert "\\:" in escaped
        assert "\\'" in escaped
        assert "\\[" in escaped

    def test_transcribe_has_no_fabricated_wav_fallback(self):
        import workers.transcribe as tr_mod
        assert not hasattr(tr_mod, "_fallback_transcript_from_wav")



class TestCoreAccuracyUpgrades:
    def test_stable_word_ids_and_lookup(self, sample_transcript):
        sample_transcript.ensure_word_ids()
        words = sample_transcript.all_words
        assert words[0].id == "w_000001"
        assert words[-1].id == f"w_{len(words):06d}"
        assert sample_transcript.word_by_id("w_000001").text == "The"
        span = sample_transcript.words_in_id_range("w_000001", "w_000005")
        assert len(span) == 5

    def test_srt_override_parser(self):
        srt = (
            "1\n00:00:01,000 --> 00:00:03,000\nHello world from SRT\n\n"
            "2\n00:00:03,500 --> 00:00:06,000\nSecond subtitle line here\n"
        )
        t = transcript_from_srt(srt)
        assert len(t.segments) == 2
        assert len(t.all_words) == 8
        assert t.all_words[0].id == "w_000001"

    def test_signals_layer_10hz(self, sample_transcript):
        sig = compute_signals(transcript=sample_transcript, hz=10.0)
        assert sig.hz == 10.0
        assert len(sig.frames) >= 130
        silences = sig.silence_intervals(min_duration=0.1)
        assert isinstance(silences, list)

    def test_word_id_clip_selection_and_dependent_clause_refinement(self, tmp_path):
        assert starts_with_dependent_clause("Because we launched early") is True
        assert starts_with_dependent_clause("The biggest mistake founders make") is False

        long_words = [
            Word(text=f"word{i}.", start=float(i), end=float(i) + 0.8, probability=0.98)
            for i in range(40)
        ]
        long_seg = Segment(start=0.0, end=40.0, text=" ".join(w.text for w in long_words), words=long_words, speaker="S1")
        long_tr = Transcript(language="en", language_probability=0.99, duration=40.0, segments=[long_seg])

        llm_reply = json.dumps({
            "clips": [
                {
                    "start_word_id": "w_000002",
                    "end_word_id": "w_000028",
                    "hook": "The biggest mistake",
                    "title": "Word ID Clip",
                    "score": 88,
                    "score_breakdown": {"hook": 9, "flow": 8, "value": 9, "trend": 8},
                    "reason": "Exact word ID boundaries",
                }
            ]
        })
        with patch("workers.select_clips._call_llm", return_value=llm_reply):
            clips = select_clips(long_tr, tmp_path)
            assert len(clips) == 1
            assert clips[0].start_word_id == "w_000002"
            assert clips[0].end_word_id == "w_000028"
            assert clips[0].low_confidence is False

    def test_asd_hysteresis_and_layout_classifier(self):
        faces = [
            {"x": 200, "y": 200, "w": 180, "h": 180, "center_x": 290.0, "center_y": 290.0, "speaking_prob": 0.9},
            {"x": 1200, "y": 200, "w": 180, "h": 180, "center_x": 1290.0, "center_y": 290.0, "speaking_prob": 0.2},
        ]
        assert classify_layout(faces, 1920, 1080) == "split_screen"
        assert classify_layout([], 1920, 1080, ocr_text_density=0.5) == "screenshare"

        f1, _ = select_active_speaker_face(faces, current_time=0.0)
        assert f1["center_x"] == 290.0

        faces_flipped = [
            {"x": 200, "y": 200, "w": 180, "h": 180, "center_x": 290.0, "center_y": 290.0, "speaking_prob": 0.1},
            {"x": 1200, "y": 200, "w": 180, "h": 180, "center_x": 1290.0, "center_y": 290.0, "speaking_prob": 0.95},
        ]
        f_hold, _ = select_active_speaker_face(
            faces_flipped, current_time=0.5, prev_face=f1, last_switch_time=0.0, hysteresis_sec=1.5
        )
        assert f_hold["center_x"] == 290.0

        f_switch, sw_new = select_active_speaker_face(
            faces_flipped, current_time=2.0, prev_face=f1, last_switch_time=0.0, hysteresis_sec=1.5
        )
        assert f_switch["center_x"] == 1290.0
        assert sw_new == 2.0

    def test_split_screen_distinct_crops_and_sendcmd(self, tmp_path):
        fc = build_split_screen_filter_complex(1080, 1920, top_speaker_x_ratio=0.20, bottom_speaker_x_ratio=0.80)
        assert "0.20" in fc and "0.80" in fc
        kfs = [CropKeyframe(frame=i * 10, time=float(i), x=400 + i * 5, y=0, w=606, h=1080) for i in range(30)]
        cmd_file, filt = generate_sendcmd_crop_script(kfs, tmp_path / "crop.cmd", 606, 1080, 1920)
        assert cmd_file.exists()
        assert "crop@reframe" in filt
        assert len(cmd_file.read_text().strip().splitlines()) == 30


class TestEDLAndCaptionsAndXMLExport:
    def test_edl_compilation_and_word_deletions(self, sample_transcript, tmp_path):
        clip = WorkerClip(
            start=0.0,
            end=13.0,
            hook="The biggest mistake",
            title="Founder Mistake",
            score=90,
            score_breakdown=ScoreBreakdown(hook=9, flow=9, value=9, trend=9),
            reason="Great clip",
        )
        edl = compile_edl_from_clip(
            clip=clip,
            transcript=sample_transcript,
            excluded_word_indices=[2, 3],
            word_overrides={"0": "THE"},
            clip_id="clip-1",
        )
        assert edl.total_duration > 0
        assert len(edl.cuts) >= 2
        af = build_edl_audio_filter(edl)
        assert "afade=t=in:st=0:d=0.015" in af
        assert "loudnorm" in af

        srt = generate_srt(
            clip,
            sample_transcript,
            excluded_word_indices=[2],
            word_overrides={0: "THE"},
        )
        assert "THE" in srt
        assert "mistake" not in srt

        style = CaptionStyle(auto_emoji=True, pop_animation=True)
        ass_path = generate_captions(
            clip,
            sample_transcript,
            tmp_path,
            style=style,
            excluded_word_indices=[2],
        )
        ass_text = ass_path.read_text(encoding="utf-8")
        assert "\\fscx112" in ass_text
        assert inject_auto_emojis("made ten thousand dollars").endswith("💵")

    def test_fcpxml_and_nle_zip_export(self, sample_transcript):
        clip = WorkerClip(
            start=0.0,
            end=10.0,
            hook="Hook",
            title="Premiere Clip",
            score=85,
            score_breakdown=ScoreBreakdown(hook=8, flow=8, value=8, trend=8),
            reason="r",
        )
        xml_str = generate_fcpxml_v4(clip, fps=30.0)
        assert "<xmeml version=\"4\">" in xml_str
        parsed = ET.fromstring(xml_str.split("<!DOCTYPE xmeml>\n", 1)[-1])
        assert parsed.tag == "xmeml"

        zip_bytes = build_nle_export_zip(clip, transcript=sample_transcript, fps=30.0)
        with zipfile.ZipFile(io.BytesIO(zip_bytes), "r") as zf:
            names = set(zf.namelist())
            assert {"timeline.xml", "captions.srt", "edl.json"}.issubset(names)


class TestEvaluationHarness:
    def test_eval_metrics_and_golden_suite(self):
        assert compute_wer("the quick brown fox", "the quick brown fox") == 0.0
        assert compute_wer("the quick brown fox", "the slow brown fox") == 0.25
        report = run_golden_eval_suite()
        assert report.all_passed is True
        assert report.wer < 0.05
        assert report.caption_onset_error_ms < 100.0
        assert report.der < 0.12
        assert report.highlight_overlap >= 0.70
        assert report.mid_sentence_boundary_rate < 0.02
        assert report.face_in_frame_rate >= 0.95
        assert report.clip_acceptance_rate >= 0.60


TEST_DB_URL = "sqlite+aiosqlite:///:memory:"


@pytest_asyncio.fixture
async def async_db() -> AsyncGenerator[AsyncSession, None]:
    engine = create_async_engine(TEST_DB_URL, echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as sess:
        yield sess
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest_asyncio.fixture
async def api_client(async_db: AsyncSession) -> AsyncGenerator[AsyncClient, None]:
    async def override_get_db() -> AsyncGenerator[AsyncSession, None]:
        yield async_db

    app.dependency_overrides[get_db] = override_get_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_edl_xml_credits_feedback_eval_and_mcp_endpoints(
    api_client: AsyncClient,
    async_db: AsyncSession,
    sample_transcript,
):
    proj = Project(name="Opus Upgrade Project", source_type=SourceType.upload, status=ProjectStatus.done)
    async_db.add(proj)
    await async_db.flush()

    vid = Video(project_id=proj.id, duration=120.0, width=1920, height=1080, fps=30.0)
    async_db.add(vid)
    await async_db.flush()

    tr = TranscriptModel(video_id=vid.id, data=sample_transcript.to_dict(), model="faster-whisper")
    async_db.add(tr)

    clip = Clip(
        project_id=proj.id,
        start=0.0,
        end=12.9,
        score=90,
        score_breakdown={"hook": 9, "flow": 9, "value": 9, "trend": 9},
        hook="The biggest mistake",
        title="Founder Mistake",
        status=ClipStatus.done,
    )
    async_db.add(clip)
    await async_db.commit()

    # 1. PATCH /api/clips/{id}/edl persists excluded_word_indices and word_overrides
    edl_res = await api_client.patch(
        f"/api/clips/{clip.id}/edl",
        json={"excluded_word_indices": [2, 3], "word_overrides": {"0": "THE"}},
    )
    assert edl_res.status_code == 200
    assert edl_res.json()["excluded_word_indices"] == [2, 3]
    assert edl_res.json()["version"] == 1

    # 2. GET /api/clips/{id}/transcript returns persisted excluded_word_indices and stable word IDs
    tr_res = await api_client.get(f"/api/clips/{clip.id}/transcript")
    assert tr_res.status_code == 200
    assert tr_res.json()["excluded_word_indices"] == [2, 3]
    assert tr_res.json()["words"][0]["id"] == "w_000001"

    # 3. GET /api/clips/{id}/export-xml returns ZIP with timeline.xml
    xml_res = await api_client.get(f"/api/clips/{clip.id}/export-xml")
    assert xml_res.status_code == 200
    assert xml_res.headers["content-type"] == "application/zip"

    # 4. Credits estimate & charge (X platform adds +3 credit surcharge)
    est_res = await api_client.post("/api/credits/estimate", json={"duration_seconds": 180.0, "platform": "x"})
    assert est_res.status_code == 200
    assert est_res.json()["estimated_credits"] == 6  # 3 min + 3 X surcharge

    charge_res = await api_client.post("/api/credits/charge", json={"project_id": str(proj.id), "credits": 6})
    assert charge_res.status_code == 200
    assert charge_res.json()["credits_remaining"] == 294

    # 5. Feedback & weight calibration
    fb_res = await api_client.post(f"/api/clips/{clip.id}/feedback", json={"action": "exported"})
    assert fb_res.status_code == 200
    assert "calibrated_weights" in fb_res.json()

    # 6. Evaluation harness report
    eval_res = await api_client.get("/api/eval/report")
    assert eval_res.status_code == 200
    assert eval_res.json()["all_passed"] is True

    # 7. MCP tools & invocation
    mcp_tools = await api_client.get("/api/mcp/tools")
    assert mcp_tools.status_code == 200
    assert len(mcp_tools.json()["tools"]) >= 5

    mcp_call = await api_client.post(
        "/api/mcp/call",
        json={"tool": "opusclip_list_clips", "arguments": {"project_id": str(proj.id)}},
    )
    assert mcp_call.status_code == 200
    assert len(mcp_call.json()["result"]) == 1

    # 8. Alembic 002 migration structure check
    import importlib
    mig2 = importlib.import_module("infra.migrations.versions.002_opusclip_platform_schema")
    assert mig2.revision == "002_opusclip_platform_schema"
    assert callable(mig2.upgrade)



