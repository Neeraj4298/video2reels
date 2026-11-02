"""
Test Suite — Stage 2: Audio Extraction
Tests: ffmpeg extraction, caching, error cases
"""
import os
import pytest
from pathlib import Path

# Ensure static ffmpeg is found
os.environ.setdefault("FFMPEG_PATH", "./bin/ffmpeg")

from workers.audio_extract import extract_audio


class TestAudioExtraction:
    def test_extracts_wav_file(self, sample_video_path, work_dir, tmp_path):
        from workers.ingest import probe_video
        meta = probe_video(sample_video_path)
        audio = extract_audio(meta, tmp_path)
        assert audio.exists(), "audio.wav should be created"
        assert audio.suffix == ".wav"
        assert audio.stat().st_size > 0, "WAV file should not be empty"

    def test_output_path_is_audio_dir(self, sample_video_path, tmp_path):
        from workers.ingest import probe_video
        meta = probe_video(sample_video_path)
        audio = extract_audio(meta, tmp_path)
        assert audio.parent.name == "audio"
        assert audio.name == "audio.wav"

    def test_cached_audio_reused(self, sample_video_path, tmp_path):
        """Second call should return cached file without re-running ffmpeg."""
        from workers.ingest import probe_video
        meta = probe_video(sample_video_path)
        audio1 = extract_audio(meta, tmp_path)
        mtime1 = audio1.stat().st_mtime

        audio2 = extract_audio(meta, tmp_path)
        mtime2 = audio2.stat().st_mtime

        assert audio1 == audio2
        assert mtime1 == mtime2, "Cached file must not be recreated"

    def test_wav_is_readable_by_python(self, sample_video_path, tmp_path):
        """Verify the WAV is a valid PCM file by checking the header."""
        from workers.ingest import probe_video
        meta = probe_video(sample_video_path)
        audio = extract_audio(meta, tmp_path)
        header = audio.read_bytes()[:4]
        assert header == b"RIFF", "WAV must start with RIFF header"
