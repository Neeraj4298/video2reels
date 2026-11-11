"""
Stage 6b: FFmpeg Render & Export
──────────────────────────────────
Composes the final 1080×1920 H.264 MP4 for each clip:
  1. Trim the source video to clip start/end
  2. Apply crop + scale to 1080×1920
  3. Burn in ASS word-highlight captions
  4. Normalize audio loudness (EBU R128)
  5. Encode to H.264 + AAC

Output: output/<project_id>/clip_NN_<title_slug>.mp4
"""
from __future__ import annotations

import re
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

from loguru import logger
from workers.config import (
    OUTPUT_WIDTH, OUTPUT_HEIGHT,
    OUTPUT_GPU_CODEC, OUTPUT_GPU_PRESET,
    OUTPUT_CODEC, OUTPUT_PRESET,
    OUTPUT_AUDIO_CODEC, OUTPUT_AUDIO_BITRATE,
    OUTPUT_DIR,
)
from workers.ingest import _ffmpeg_bin, VideoMeta
from workers.select_clips import Clip
from workers.reframe import ReframeResult
from workers.captions import CaptionStyle, DEFAULT_STYLE, generate_captions
from workers.transcribe import Transcript


# ── Data model ────────────────────────────────────────────────────────────────

@dataclass
class RenderResult:
    clip: Clip
    output_path: Path
    duration: float
    size_bytes: int
    render_time: float

    @property
    def size_mb(self) -> float:
        return self.size_bytes / 1_048_576


# ── Helpers ───────────────────────────────────────────────────────────────────

def escape_ffmpeg_filter_path(path: Path | str) -> str:
    """
    Escape a filesystem path for safe embedding inside FFmpeg filter arguments
    such as ass='...' or sendcmd=f='...'.
    """
    raw = str(path)
    # In FFmpeg filtergraphs, backslashes, colons, single quotes, and brackets must be escaped
    escaped = (
        raw.replace("\\", "\\\\")
        .replace(":", "\\:")
        .replace("'", "\\'")
        .replace("[", "\\[")
        .replace("]", "\\]")
        .replace(";", "\\;")
        .replace(",", "\\,")
    )
    return escaped


def _slugify(text: str, max_len: int = 40) -> str:

    """Convert title to a safe filename slug."""
    slug = re.sub(r"[^\w\s-]", "", text.lower())
    slug = re.sub(r"[\s_-]+", "_", slug).strip("_")
    return slug[:max_len] or "clip"


_NVENC_AVAILABLE: Optional[bool] = None


def _has_nvenc_gpu() -> bool:
    """
    Detect whether an NVIDIA GPU device is present and FFmpeg supports h264_nvenc.
    Primary encoding uses GPU (h264_nvenc); falls back to CPU (libx264) when False.
    """
    global _NVENC_AVAILABLE
    if _NVENC_AVAILABLE is not None:
        return _NVENC_AVAILABLE

    if not Path("/dev/nvidia0").exists():
        _NVENC_AVAILABLE = False
        return False

    try:
        ffmpeg = _ffmpeg_bin()
        res = subprocess.run(
            [ffmpeg, "-hide_banner", "-encoders"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        _NVENC_AVAILABLE = OUTPUT_GPU_CODEC in res.stdout
    except Exception:
        _NVENC_AVAILABLE = False
    return _NVENC_AVAILABLE


def _build_ffmpeg_cmd(
    source: Path,
    out_path: Path,
    clip: Clip,
    reframe: ReframeResult,
    ass_path: Path,
    meta: VideoMeta,
    watermark_path: Optional[Path] = None,
    use_gpu: Optional[bool] = None,
) -> list[str]:
    """
    Build the FFmpeg command for rendering a single clip.
    Supports both:
      1. Vertical face-tracked smart crop with dynamic expressions
      2. Blurred background layout with letterboxed foreground
    """
    from workers.reframe import build_blur_bg_filter_complex, build_split_screen_filter_complex

    ffmpeg = _ffmpeg_bin()
    clip_dur = max(0.1, float(clip.end - clip.start))
    fade_out_st = max(0.0, clip_dur - 0.015)
    af = f"afade=t=in:st=0:d=0.015,afade=t=out:st={fade_out_st:.3f}:d=0.015,loudnorm=I=-14:TP=-2:LRA=11"
    layout = getattr(reframe, "layout", "vertical")


    # If watermark is provided, pass it as second input
    has_watermark = watermark_path is not None and watermark_path.exists()

    # Primary: GPU NVENC (h264_nvenc); Fallback: CPU (libx264)
    enable_gpu = _has_nvenc_gpu() if use_gpu is None else use_gpu
    if enable_gpu:
        vcodec_args = ["-c:v", OUTPUT_GPU_CODEC, "-preset", OUTPUT_GPU_PRESET, "-cq", "23"]
    else:
        vcodec_args = ["-c:v", OUTPUT_CODEC, "-preset", OUTPUT_PRESET, "-crf", "23"]

    if layout in ("blur_bg", "split_screen"):
        if layout == "blur_bg":
            filter_complex = build_blur_bg_filter_complex(
                out_w=OUTPUT_WIDTH,
                out_h=OUTPUT_HEIGHT,
                ass_path=ass_path,
            )
        else:
            filter_complex = build_split_screen_filter_complex(
                out_w=OUTPUT_WIDTH,
                out_h=OUTPUT_HEIGHT,
                ass_path=ass_path,
            )

        if has_watermark:
            # Chain watermark overlay onto [out]
            filter_complex = filter_complex.replace("[out]", "[pre_wm]") + f";[pre_wm][1:v]overlay=W-w-36:36[out]"

        cmd = [
            ffmpeg, "-y",
            "-ss", str(clip.start),
            "-to", str(clip.end),
            "-i", str(source),
        ]
        if has_watermark:
            cmd.extend(["-i", str(watermark_path)])

        cmd.extend([
            "-filter_complex", filter_complex,
            "-map", "[out]",
            "-map", "0:a?",
            "-af", af,
            *vcodec_args,
            "-c:a", OUTPUT_AUDIO_CODEC,
            "-b:a", OUTPUT_AUDIO_BITRATE,
            "-movflags", "+faststart",
            "-avoid_negative_ts", "make_zero",
            str(out_path),
        ])
        return cmd

    # Vertical smart-crop mode
    raw_expr = getattr(reframe, "crop_filter_expr", "")
    if raw_expr and raw_expr.count("if(") > 24 and getattr(reframe, "keyframes", None):
        from workers.reframe import generate_crop_filter_expression
        crop_filter = generate_crop_filter_expression(
            reframe.keyframes, reframe.crop_w, reframe.crop_h, meta.width
        )
    elif raw_expr:
        crop_filter = raw_expr
    elif reframe.keyframes:
        kf = reframe.keyframes[0]
        crop_filter = f"crop={kf.w}:{kf.h}:{kf.x}:{kf.y}"
    else:
        crop_filter = f"crop={reframe.crop_w}:{reframe.crop_h}:(in_w-out_w)/2:0"

    scale_filter = f"scale={OUTPUT_WIDTH}:{OUTPUT_HEIGHT}:flags=lanczos"
    ass_filter   = f"ass='{escape_ffmpeg_filter_path(ass_path)}'"


    if has_watermark:
        filter_complex = (
            f"[0:v]{crop_filter},{scale_filter}[cropped];"
            f"[cropped][1:v]overlay=W-w-36:36[with_wm];"
            f"[with_wm]{ass_filter}[out]"
        )
        return [
            ffmpeg, "-y",
            "-ss", str(clip.start),
            "-to", str(clip.end),
            "-i", str(source),
            "-i", str(watermark_path),
            "-filter_complex", filter_complex,
            "-map", "[out]",
            "-map", "0:a?",
            "-af", af,
            *vcodec_args,
            "-c:a", OUTPUT_AUDIO_CODEC,
            "-b:a", OUTPUT_AUDIO_BITRATE,
            "-movflags", "+faststart",
            "-avoid_negative_ts", "make_zero",
            str(out_path),
        ]

    vf = f"{crop_filter},{scale_filter},{ass_filter}"

    return [
        ffmpeg, "-y",
        "-ss", str(clip.start),
        "-to", str(clip.end),
        "-i", str(source),
        "-vf", vf,
        "-af", af,
        *vcodec_args,
        "-c:a", OUTPUT_AUDIO_CODEC,
        "-b:a", OUTPUT_AUDIO_BITRATE,
        "-movflags", "+faststart",
        "-avoid_negative_ts", "make_zero",
        str(out_path),
    ]



# ── Core function ─────────────────────────────────────────────────────────────

def render_clip(
    clip: Clip,
    reframe: ReframeResult,
    transcript: Transcript,
    meta: VideoMeta,
    work_dir: Path,
    project_id: str,
    clip_index: int,
    style: CaptionStyle = DEFAULT_STYLE,
    watermark_path: Optional[Path] = None,
    excluded_word_indices: Optional[list[int | str] | set[int | str]] = None,
    word_overrides: Optional[dict[str | int, str]] = None,
) -> RenderResult:
    """
    Render a single clip to 1080×1920 MP4.
    """
    out_dir = OUTPUT_DIR / project_id
    out_dir.mkdir(parents=True, exist_ok=True)

    slug = _slugify(clip.title or clip.hook)
    out_filename = f"clip_{clip_index:02d}_{slug}.mp4"
    out_path = out_dir / out_filename

    has_edits = bool(excluded_word_indices) or bool(word_overrides)
    if out_path.exists() and not has_edits:
        logger.info("[Stage 6b] Clip {} already rendered: {}", clip_index, out_path.name)
        size = out_path.stat().st_size
        return RenderResult(
            clip=clip, output_path=out_path,
            duration=clip.end - clip.start,
            size_bytes=size, render_time=0.0,
        )

    # ── Generate captions ─────────────────────────────────────────────────────
    ass_path = generate_captions(
        clip,
        transcript,
        work_dir,
        style,
        excluded_word_indices=excluded_word_indices,
        word_overrides=word_overrides,
    )


    # ── Build & run FFmpeg ────────────────────────────────────────────────────
    cmd = _build_ffmpeg_cmd(
        source=meta.path,
        out_path=out_path,
        clip=clip,
        reframe=reframe,
        ass_path=ass_path,
        meta=meta,
        watermark_path=watermark_path,
    )

    logger.info(
        "[Stage 6b] Rendering clip {}: {:.1f}s–{:.1f}s → {}",
        clip_index, clip.start, clip.end, out_filename,
    )
    logger.debug("FFmpeg CMD: {}", " ".join(cmd))

    t0 = time.time()
    result = subprocess.run(cmd, capture_output=True, text=True)

    # If primary GPU NVENC failed at runtime, fall back automatically to CPU libx264
    if result.returncode != 0 and OUTPUT_GPU_CODEC in cmd:
        logger.warning(
            "[Stage 6b] GPU encoder '{}' failed; falling back to CPU encoder '{}'",
            OUTPUT_GPU_CODEC, OUTPUT_CODEC,
        )
        cmd = _build_ffmpeg_cmd(
            source=meta.path,
            out_path=out_path,
            clip=clip,
            reframe=reframe,
            ass_path=ass_path,
            meta=meta,
            watermark_path=watermark_path,
            use_gpu=False,
        )
        result = subprocess.run(cmd, capture_output=True, text=True)

    render_time = time.time() - t0

    if result.returncode != 0:
        raise RuntimeError(
            f"FFmpeg render failed for clip {clip_index}:\n{result.stderr[-3000:]}"
        )

    size = out_path.stat().st_size
    logger.success(
        "[Stage 6b] ✓ Clip {}: {:.1f}s → {:.1f} MB (rendered in {:.1f}s)",
        clip_index, clip.end - clip.start, size / 1_048_576, render_time,
    )
    return RenderResult(
        clip=clip, output_path=out_path,
        duration=clip.end - clip.start,
        size_bytes=size, render_time=render_time,
    )


def render_all_clips(
    clips: list[Clip],
    reframes: list[ReframeResult],
    transcript: Transcript,
    meta: VideoMeta,
    work_dir: Path,
    project_id: str,
    style: CaptionStyle = DEFAULT_STYLE,
) -> list[RenderResult]:
    """Render all clips sequentially (Phase 0). Phase 1 will parallelize."""
    results = []
    for i, (clip, reframe) in enumerate(zip(clips, reframes), 1):
        try:
            res = render_clip(
                clip=clip, reframe=reframe, transcript=transcript,
                meta=meta, work_dir=work_dir, project_id=project_id,
                clip_index=i, style=style,
            )
            results.append(res)
        except Exception as e:
            logger.error("[Stage 6b] Clip {} failed: {}", i, e)

    logger.success(
        "[Stage 6b] ✓ Rendered {}/{} clips  |  Total: {:.1f} MB",
        len(results), len(clips),
        sum(r.size_mb for r in results),
    )
    return results
