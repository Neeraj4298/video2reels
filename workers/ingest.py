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

import ipaddress
import json
import socket
import subprocess
import shutil
import urllib.parse
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
    is_vfr: bool = False
    proxy_path: Optional[Path] = None
    credit_cost: int = 1



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


# ── URL Validation (SSRF Protection) & Credit Calculation ─────────────────────

_BLOCKED_HOSTNAMES = {
    "localhost",
    "localhost.localdomain",
    "metadata.google.internal",
    "metadata",
    "169.254.169.254",
    "0.0.0.0",
}


def validate_source_url(url: str, resolve_dns: bool = False) -> str:
    """
    Validate an external video URL before passing to yt-dlp to prevent SSRF:
      - Allowlist only http:// and https:// schemes.
      - Block localhost, loopback, link-local (169.254.x.x), RFC1918 private IPs,
        and cloud metadata endpoints.
    """
    if not url or not isinstance(url, str):
        raise ValueError("Source URL cannot be empty")
    clean = url.strip()
    parsed = urllib.parse.urlparse(clean)
    if parsed.scheme.lower() not in ("http", "https"):
        raise ValueError(f"Unsupported URL scheme {parsed.scheme!r}; only http and https are allowed")

    hostname = (parsed.hostname or "").strip().lower()
    if not hostname:
        raise ValueError("URL must include a valid hostname")
    if hostname in _BLOCKED_HOSTNAMES or hostname.endswith(".local") or hostname.endswith(".internal"):
        raise ValueError(f"Blocked internal/metadata hostname: {hostname}")

    # Check literal IP address if hostname is an IP
    try:
        ip_obj = ipaddress.ip_address(hostname)
        if (
            ip_obj.is_private
            or ip_obj.is_loopback
            or ip_obj.is_link_local
            or ip_obj.is_multicast
            or ip_obj.is_reserved
            or ip_obj.is_unspecified
        ):
            raise ValueError(f"Blocked private or reserved IP address: {hostname}")
    except ValueError as exc:
        if "Blocked" in str(exc):
            raise

    if resolve_dns:
        try:
            infos = socket.getaddrinfo(hostname, None)
            for info in infos:
                addr_str = info[4][0]
                ip_obj = ipaddress.ip_address(addr_str)
                if (
                    ip_obj.is_private
                    or ip_obj.is_loopback
                    or ip_obj.is_link_local
                    or ip_obj.is_reserved
                ):
                    raise ValueError(f"Hostname {hostname} resolves to private/reserved IP {addr_str}")
        except socket.gaierror:
            pass

    return clean


def compute_video_credits(duration_seconds: float) -> int:
    """
    OpusClip credit calculation rule (opusclip/research/plan-restrictions-and-credit-system.md):
      - 1 credit = 1 minute of video processed.
      - Videos < 1 minute (60s) are rounded UP to 1 credit.
      - Videos >= 1 minute with partial seconds are rounded DOWN (e.g. 4m 30s = 4 credits).
    """
    if duration_seconds <= 0:
        return 0
    if duration_seconds < 60.0:
        return 1
    return max(1, int(duration_seconds // 60.0))


def needs_cfr_normalization(fps: float, avg_frame_rate: Optional[str] = None, r_frame_rate: Optional[str] = None) -> bool:
    """
    Detect non-integer framerates (e.g. 29.97, 59.94, 23.976 fps) or VFR mismatch
    that cause audio-visual drift during reframing and caption burn-in.
    """
    if abs(fps - round(fps)) > 0.01:
        return True
    if avg_frame_rate and r_frame_rate and avg_frame_rate != r_frame_rate:
        try:
            a_num, a_den = [float(x) for x in avg_frame_rate.split("/")]
            r_num, r_den = [float(x) for x in r_frame_rate.split("/")]
            if a_den > 0 and r_den > 0:
                if abs((a_num / a_den) - (r_num / r_den)) > 0.05:
                    return True
        except Exception:
            pass
    return False


def normalize_to_cfr(source_path: Path, out_dir: Path, target_fps: int = 30) -> Path:
    """Normalize a VFR or non-integer FPS video (e.g. 29.97fps) to constant frame rate (CFR)."""
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{source_path.stem}_cfr{target_fps}.mp4"
    if out_path.exists() and out_path.stat().st_size > 0:
        return out_path
    ffmpeg = _ffmpeg_bin()
    cmd = [
        ffmpeg, "-y",
        "-i", str(source_path),
        "-vf", f"fps=fps={target_fps}",
        "-vsync", "cfr",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
        "-c:a", "copy",
        str(out_path),
    ]
    res = _run(cmd, check=False)
    if res.returncode != 0 or not out_path.exists():
        logger.warning("[Stage 1] CFR normalization failed; keeping original stream")
        return source_path
    return out_path


def generate_proxy_video(source_path: Path, out_dir: Path, height: int = 720, target_fps: int = 30) -> Path:
    """
    Generate a lightweight 720p CFR proxy video for fast vision analysis and browser preview
    while preserving the original high-res video for final export rendering.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    proxy_path = out_dir / f"{source_path.stem}_proxy_{height}p.mp4"
    if proxy_path.exists() and proxy_path.stat().st_size > 0:
        return proxy_path
    ffmpeg = _ffmpeg_bin()
    cmd = [
        ffmpeg, "-y",
        "-i", str(source_path),
        "-vf", f"scale=-2:{height},fps=fps={target_fps}",
        "-c:v", "libx264", "-preset", "ultrafast", "-crf", "26",
        "-c:a", "aac", "-b:a", "96k",
        "-movflags", "+faststart",
        str(proxy_path),
    ]
    res = _run(cmd, check=False)
    if res.returncode != 0 or not proxy_path.exists():
        return source_path
    return proxy_path


# ── Core functions ────────────────────────────────────────────────────────────

def download_url(url: str, out_dir: Path) -> Path:
    """Download best quality video+audio from URL using yt-dlp."""
    validate_source_url(url)
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
    avg_fps_raw = video_stream.get("avg_frame_rate", fps_raw)
    num, den = fps_raw.split("/")
    fps = float(num) / float(den) if float(den) > 0 else 25.0
    is_vfr = needs_cfr_normalization(fps, avg_frame_rate=avg_fps_raw, r_frame_rate=fps_raw)

    return VideoMeta(
        path=path,
        duration=duration,
        width=int(video_stream.get("width", 0)),
        height=int(video_stream.get("height", 0)),
        fps=round(fps, 3),
        has_audio=audio_stream is not None,
        codec=video_stream.get("codec_name", "unknown"),
        size_bytes=int(fmt.get("size", 0)),
        is_vfr=is_vfr,
        credit_cost=compute_video_credits(duration),
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
    if "://" in source_str and not (source_str.startswith("http://") or source_str.startswith("https://")):
        validate_source_url(source_str)
    if source_str.startswith("http://") or source_str.startswith("https://"):
        validate_source_url(source_str)
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

