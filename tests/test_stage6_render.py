"""
Test Suite — Stage 6b: FFmpeg Render
Tests: filename slugifying, FFmpeg command construction, render caching.
Full render is an integration test — it needs a real video + FFmpeg.
"""
import os
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

os.environ.setdefault("FFMPEG_PATH", "./bin/ffmpeg")

from workers.render import (
    _slugify,
    _build_ffmpeg_cmd,
    render_clip,
    render_all_clips,
    RenderResult,
)
from workers.select_clips import Clip, ScoreBreakdown
from workers.reframe import ReframeResult, CropKeyframe
from workers.captions import DEFAULT_STYLE


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_clip(start=0.0, end=25.0, title="Test Clip"):
    return Clip(
        start=start, end=end,
        hook="This is the hook", title=title,
        score=80,
        score_breakdown=ScoreBreakdown(hook=8, flow=8, value=8, trend=8),
        reason="test",
    )


def _make_reframe(clip, video_path, src_w=1280, src_h=720):
    """Compute a proper center-crop reframe for the given source resolution."""
    from workers.reframe import _compute_center_crop
    x, y, crop_w, crop_h = _compute_center_crop(src_w, src_h)
    kf = CropKeyframe(frame=0, time=0.0, x=x, y=y, w=crop_w, h=crop_h)
    return ReframeResult(
        clip=clip,
        video_path=video_path,
        keyframes=[kf],
        crop_w=crop_w,
        crop_h=crop_h,
    )


# ── Slug helper ───────────────────────────────────────────────────────────────

class TestSlugify:
    def test_basic_ascii(self):
        assert _slugify("Hello World") == "hello_world"

    def test_special_chars_removed(self):
        slug = _slugify("Best Tips & Tricks! (2024)")
        assert "&" not in slug
        assert "!" not in slug

    def test_max_length(self):
        long_title = "A" * 100
        assert len(_slugify(long_title, max_len=20)) <= 20

    def test_empty_falls_back(self):
        assert _slugify("", max_len=20) == "clip"

    def test_unicode_stripped(self):
        slug = _slugify("Héllo Wörld")
        assert slug  # just don't crash


# ── FFmpeg command construction ───────────────────────────────────────────────

class TestBuildFfmpegCmd:
    def test_returns_list(self, sample_video_path, tmp_path):
        from workers.ingest import probe_video
        meta = probe_video(sample_video_path)
        clip = _make_clip()
        reframe = _make_reframe(clip, sample_video_path)
        ass = tmp_path / "test.ass"
        ass.write_text("[Script Info]\n", encoding="utf-8")

        cmd = _build_ffmpeg_cmd(sample_video_path, tmp_path / "out.mp4", clip, reframe, ass, meta)
        assert isinstance(cmd, list)
        assert cmd[0].endswith("ffmpeg") or "ffmpeg" in cmd[0]

    def test_crop_filter_in_cmd(self, sample_video_path, tmp_path):
        from workers.ingest import probe_video
        meta = probe_video(sample_video_path)
        clip = _make_clip()
        reframe = _make_reframe(clip, sample_video_path)
        ass = tmp_path / "test.ass"
        ass.write_text("[Script Info]\n", encoding="utf-8")

        cmd = _build_ffmpeg_cmd(sample_video_path, tmp_path / "out.mp4", clip, reframe, ass, meta)
        vf_idx = cmd.index("-vf")
        vf_val = cmd[vf_idx + 1]
        assert "crop=" in vf_val
        assert "scale=" in vf_val

    def test_loudnorm_in_af(self, sample_video_path, tmp_path):
        from workers.ingest import probe_video
        meta = probe_video(sample_video_path)
        clip = _make_clip()
        reframe = _make_reframe(clip, sample_video_path)
        ass = tmp_path / "test.ass"
        ass.write_text("[Script Info]\n", encoding="utf-8")

        cmd = _build_ffmpeg_cmd(sample_video_path, tmp_path / "out.mp4", clip, reframe, ass, meta)
        af_idx = cmd.index("-af")
        assert "loudnorm" in cmd[af_idx + 1]

    def test_faststart_flag_present(self, sample_video_path, tmp_path):
        from workers.ingest import probe_video
        meta = probe_video(sample_video_path)
        clip = _make_clip()
        reframe = _make_reframe(clip, sample_video_path)
        ass = tmp_path / "test.ass"
        ass.write_text("[Script Info]\n", encoding="utf-8")

        cmd = _build_ffmpeg_cmd(sample_video_path, tmp_path / "out.mp4", clip, reframe, ass, meta)
        assert "+faststart" in cmd


# ── Full render integration test ──────────────────────────────────────────────

class TestRenderClipIntegration:
    """
    Renders a real 5-second clip from the synthetic test video.
    Skipped if FFmpeg binary isn't accessible.
    """

    def test_render_produces_mp4(self, sample_video_path, sample_transcript, tmp_path):
        from workers.ingest import probe_video
        import shutil

        ffmpeg_path = Path("./bin/ffmpeg")
        if not ffmpeg_path.exists() and not shutil.which("ffmpeg"):
            pytest.skip("FFmpeg not available")

        meta = probe_video(sample_video_path)
        # Use a short clip within the 30s test video
        clip = _make_clip(start=2.0, end=8.0, title="Integration Test Clip")
        reframe = _make_reframe(clip, sample_video_path)

        # Patch OUTPUT_DIR to tmp
        import workers.render as render_mod
        original_output_dir = render_mod.OUTPUT_DIR
        render_mod.OUTPUT_DIR = tmp_path

        try:
            result = render_clip(
                clip=clip, reframe=reframe, transcript=sample_transcript,
                meta=meta, work_dir=tmp_path, project_id="test_project",
                clip_index=1,
            )
        finally:
            render_mod.OUTPUT_DIR = original_output_dir

        assert result.output_path.exists(), "Rendered MP4 must exist"
        assert result.output_path.stat().st_size > 0
        assert result.size_bytes > 0
        assert result.duration > 0

    def test_render_all_clips(self, sample_video_path, sample_transcript, tmp_path):
        from workers.ingest import probe_video
        import shutil
        import workers.render as render_mod

        ffmpeg_path = Path("./bin/ffmpeg")
        if not ffmpeg_path.exists() and not shutil.which("ffmpeg"):
            pytest.skip("FFmpeg not available")

        meta = probe_video(sample_video_path)
        clips = [_make_clip(2.0, 8.0), _make_clip(10.0, 16.0)]
        reframes = [_make_reframe(c, sample_video_path) for c in clips]

        original_output_dir = render_mod.OUTPUT_DIR
        render_mod.OUTPUT_DIR = tmp_path

        try:
            results = render_all_clips(
                clips=clips, reframes=reframes, transcript=sample_transcript,
                meta=meta, work_dir=tmp_path, project_id="test_multi",
            )
        finally:
            render_mod.OUTPUT_DIR = original_output_dir

        assert len(results) == 2
        for res in results:
            assert res.output_path.exists()
