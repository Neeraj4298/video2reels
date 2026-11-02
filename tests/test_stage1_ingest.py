"""
Test Suite — Stage 1: Ingestion & Validation
Tests: ffprobe metadata reading, validation rules, error cases
"""
import pytest
import subprocess
import shutil
from pathlib import Path

from workers.ingest import probe_video, validate_video, VideoMeta, ingest


class TestProbeVideo:
    def test_probe_returns_correct_metadata(self, sample_video_path):
        meta = probe_video(sample_video_path)
        assert meta.duration > 0, "Duration must be > 0"
        assert meta.width == 1280
        assert meta.height == 720
        assert meta.fps > 0
        assert meta.has_audio is True
        assert meta.size_bytes > 0

    def test_probe_detects_audio_stream(self, sample_video_path):
        meta = probe_video(sample_video_path)
        assert meta.has_audio, "Test video must have an audio stream"

    def test_probe_nonexistent_file_raises(self):
        with pytest.raises(Exception):
            probe_video(Path("/nonexistent/video.mp4"))


class TestValidateVideo:
    def test_valid_video_passes(self, sample_video_path):
        meta = probe_video(sample_video_path)
        validate_video(meta)  # Should not raise

    def test_too_short_raises(self):
        meta = VideoMeta(
            path=Path("fake.mp4"), duration=5.0, width=1280,
            height=720, fps=25.0, has_audio=True, codec="h264", size_bytes=1000
        )
        with pytest.raises(ValueError, match="too short"):
            validate_video(meta)

    def test_no_audio_raises(self):
        meta = VideoMeta(
            path=Path("fake.mp4"), duration=120.0, width=1280,
            height=720, fps=25.0, has_audio=False, codec="h264", size_bytes=1000
        )
        with pytest.raises(ValueError, match="no audio"):
            validate_video(meta)

    def test_too_long_raises(self):
        meta = VideoMeta(
            path=Path("fake.mp4"), duration=4 * 3600,  # 4 hours
            width=1280, height=720, fps=25.0, has_audio=True,
            codec="h264", size_bytes=1000
        )
        with pytest.raises(ValueError, match="too long"):
            validate_video(meta)

    def test_low_resolution_raises(self):
        meta = VideoMeta(
            path=Path("fake.mp4"), duration=120.0, width=200,
            height=150, fps=25.0, has_audio=True, codec="h264", size_bytes=1000
        )
        with pytest.raises(ValueError, match="Resolution"):
            validate_video(meta)


class TestIngestIntegration:
    def test_ingest_local_file(self, sample_video_path, work_dir, tmp_path):
        meta = ingest(str(sample_video_path), tmp_path)
        assert meta.duration > 0
        assert meta.width > 0
        assert meta.has_audio

    def test_ingest_missing_file_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            ingest("/does/not/exist.mp4", tmp_path)
