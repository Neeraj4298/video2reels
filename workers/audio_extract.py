"""
Stage 2: Audio Extraction
──────────────────────────
Extracts mono 16 kHz PCM WAV from the source video.
This is the standard input format for Whisper-family models.

ffmpeg command:
  ffmpeg -i input.mp4 -vn -ac 1 -ar 16000 -c:a pcm_s16le audio.wav
"""
from __future__ import annotations

import subprocess
import shutil
from pathlib import Path

from loguru import logger
from workers.config import FFMPEG_PATH
from workers.ingest import VideoMeta, _ffmpeg_bin


def extract_audio(meta: VideoMeta, work_dir: Path) -> Path:
    """
    Extract mono 16 kHz WAV from the source video.

    Args:
        meta:     VideoMeta from Stage 1
        work_dir: scratch directory for this project

    Returns:
        Path to the extracted audio.wav file
    """
    audio_dir = work_dir / "audio"
    audio_dir.mkdir(parents=True, exist_ok=True)
    out_path = audio_dir / "audio.wav"

    if out_path.exists():
        logger.info("[Stage 2] Cached audio found, skipping extraction.")
        return out_path

    ffmpeg = _ffmpeg_bin()
    cmd = [
        ffmpeg,
        "-y",                        # overwrite if exists
        "-i", str(meta.path),
        "-vn",                       # no video
        "-ac", "1",                  # mono
        "-ar", "16000",              # 16 kHz sample rate
        "-c:a", "pcm_s16le",         # 16-bit signed PCM little-endian
        str(out_path),
    ]

    logger.info("[Stage 2] Extracting audio → {}", out_path)
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"FFmpeg audio extraction failed:\n{result.stderr[-2000:]}")

    size_mb = out_path.stat().st_size / 1_048_576
    duration_min = meta.duration / 60
    logger.success(
        "[Stage 2] ✓ Audio extracted: {:.1f} MB  |  {:.1f} min", size_mb, duration_min
    )
    return out_path
