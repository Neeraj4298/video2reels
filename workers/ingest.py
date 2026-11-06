"""
Stage 1: Ingestion & Validation
─────────────────────────────────
Accepts a local file path or a URL.
- URL  → yt-dlp downloads best video+audio merged to MP4
- File → validates in place
Runs ffprobe to extract metadata.
Validates: duration, audio stream, codec.
Returns a VideoMeta dataclass consumed by downstream stages.
"""
from __future__ import annotations

import json
import subprocess
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from loguru import logger
from workers.config import FFMPEG_PATH, MAX_VIDEO_HOURS, OUTPUT_DIR


# ── Public data model ─────────────────────────────────────────────────────────

@dataclass
class VideoMeta:
    path: Path
    duration: float          # seconds
    width: int
    height: int
    fps: float
    has_audio: bool
    codec: str
    size_bytes: int = 0
    source_url: Optional[str] = None


# ── Helpers ───────────────────────────────────────────────────────────────────

def _run(cmd: list[str], check: bool = True) -> subprocess.CompletedProcess:
    logger.debug("CMD: {}", " ".join(cmd))
    return subprocess.run(cmd, capture_output=True, text=True, check=check)


def _ffmpeg_bin() -> str:
    """Return the ffmpeg executable: env override or system."""
    custom = Path(FFMPEG_PATH)
    if custom.exists():
        return str(custom)
    sys_ffmpeg = shutil.which("ffmpeg")
    if sys_ffmpeg:
        return sys_ffmpeg
    raise RuntimeError(
        "ffmpeg not found. Set FFMPEG_PATH in .env or install system ffmpeg."
    )


def _ffprobe_bin() -> str:
    """Return ffprobe — sibling of ffmpeg or system."""
    ff = Path(_ffmpeg_bin())
    probe = ff.parent / "ffprobe"
    if probe.exists():
        return str(probe)
    sys_probe = shutil.which("ffprobe")
    if sys_probe:
        return sys_probe
    raise RuntimeError("ffprobe not found.")


def _ytdlp_cmd() -> list[str]:
    """Return command prefix to run yt-dlp reliably across host venvs and Docker."""
    import importlib.util
    import sys
    if importlib.util.find_spec("yt_dlp") is not None:
        return [sys.executable, "-m", "yt_dlp"]
    for cand in (
        Path(sys.executable).resolve().parent / "yt-dlp",
        Path(__file__).resolve().parent.parent / ".venv" / "bin" / "yt-dlp",
    ):
        if cand.exists():
            return [str(cand)]
    sys_ytdlp = shutil.which("yt-dlp")
    if sys_ytdlp:
        return [sys_ytdlp]
    logger.warning("yt-dlp not found; installing yt-dlp via pip …")
    subprocess.run(
        [sys.executable, "-m", "pip", "install", "--no-cache-dir", "--quiet", "yt-dlp"],
        check=False,
    )
    if importlib.util.find_spec("yt_dlp") is not None:
        return [sys.executable, "-m", "yt_dlp"]
    return [shutil.which("yt-dlp") or "yt-dlp"]


# ── Core functions ────────────────────────────────────────────────────────────

def download_url(url: str, out_dir: Path) -> Path:
    """Download best quality video+audio from URL using yt-dlp."""
    out_dir.mkdir(parents=True, exist_ok=True)
    template = str(out_dir / "%(title).60s.%(ext)s")
    ffmpeg_dir = str(Path(_ffmpeg_bin()).resolve().parent)
    cmd = [
        *_ytdlp_cmd(),
        "--ffmpeg-location", ffmpeg_dir,
        "--restrict-filenames",
        "--hls-prefer-native",
        "--concurrent-fragments", "8",
        "--format", (
            "bestvideo[ext=mp4][vcodec^=avc1][protocol^=http][height<=1080]+bestaudio[ext=m4a][protocol^=http]/"
            "bestvideo[ext=mp4][protocol^=http][height<=1080]+bestaudio[ext=m4a][protocol^=http]/"
            "best[ext=mp4]/best"
        ),
        "--merge-output-format", "mp4",
        "--output", template,
        "--no-playlist",
        "--quiet",
        "--progress",
        url,
    ]
    logger.info("Downloading URL: {}", url)
    result = _run(cmd, check=False)
    if result.returncode != 0:
        raise RuntimeError(f"yt-dlp failed:\n{result.stderr}")

    # find the downloaded file
    mp4_files = sorted(out_dir.glob("*.mp4"), key=lambda p: p.stat().st_mtime)
    if not mp4_files:
        raise RuntimeError("yt-dlp ran but no MP4 found in output dir.")
    return mp4_files[-1]


def probe_video(path: Path) -> VideoMeta:
    """Run ffprobe and return VideoMeta."""
    ffprobe = _ffprobe_bin()
    cmd = [
        ffprobe, "-v", "quiet",
        "-print_format", "json",
        "-show_streams", "-show_format",
        str(path),
    ]
    result = _run(cmd)
    data = json.loads(result.stdout)

    video_stream = next(
        (s for s in data.get("streams", []) if s.get("codec_type") == "video"), None
    )
    audio_stream = next(
        (s for s in data.get("streams", []) if s.get("codec_type") == "audio"), None
    )

    if not video_stream:
        raise ValueError(f"No video stream found in {path}")

    fmt = data.get("format", {})
    duration = float(fmt.get("duration", 0))
    fps_raw = video_stream.get("r_frame_rate", "25/1")
    num, den = fps_raw.split("/")
    fps = float(num) / float(den) if float(den) > 0 else 25.0

    return VideoMeta(
        path=path,
        duration=duration,
        width=int(video_stream.get("width", 0)),
        height=int(video_stream.get("height", 0)),
        fps=round(fps, 3),
        has_audio=audio_stream is not None,
        codec=video_stream.get("codec_name", "unknown"),
        size_bytes=int(fmt.get("size", 0)),
    )


def validate_video(meta: VideoMeta) -> None:
    """Raise ValueError if the video fails basic checks."""
    max_sec = MAX_VIDEO_HOURS * 3600
    if meta.duration > max_sec:
        raise ValueError(
            f"Video too long: {meta.duration/3600:.1f}h > {MAX_VIDEO_HOURS}h limit"
        )
    if not meta.has_audio:
        raise ValueError("Video has no audio stream — transcription not possible.")
    if meta.duration < 10:
        raise ValueError("Video too short (<10 s). Nothing to clip.")
    if meta.width < 320:
        raise ValueError(f"Resolution too low: {meta.width}px wide.")


def ingest(source: str | Path, work_dir: Path) -> VideoMeta:
    """
    Main entry point for Stage 1.

    Args:
        source: local file path OR a URL string
        work_dir: scratch directory for this project

    Returns:
        VideoMeta ready for downstream stages
    """
    work_dir.mkdir(parents=True, exist_ok=True)
    raw_dir = work_dir / "raw"
    raw_dir.mkdir(exist_ok=True)

    source_str = str(source).strip()
    if source_str.startswith("http://") or source_str.startswith("https://"):
        logger.info("[Stage 1] Downloading from URL …")
        video_path = download_url(source_str, raw_dir)
    else:
        video_path = Path(source_str)
        if not video_path.exists() or not video_path.is_file():
            raise FileNotFoundError(f"Input file not found: {video_path}")
        logger.info("[Stage 1] Using local file: {}", video_path)

    logger.info("[Stage 1] Probing video metadata …")
    meta = probe_video(video_path)
    meta.source_url = source_str if source_str.startswith("http") else None

    logger.info(
        "[Stage 1] Validated: {}  |  {:.1f}s  |  {}x{}  |  {:.2f}fps  |  {:.1f}MB",
        meta.codec, meta.duration, meta.width, meta.height, meta.fps,
        meta.size_bytes / 1_048_576,
    )
    validate_video(meta)
    logger.success("[Stage 1] ✓ Ingestion complete")
    return meta


# Alias for backward-compatibility with worker tasks
ingest_video = ingest

