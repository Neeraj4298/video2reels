r"""
Stage 6a: Caption Generation (ASS format)
──────────────────────────────────────────
Generates Advanced SubStation Alpha (.ass) subtitle files with
word-level highlight animations.

Each word transitions from primary_color → highlight_color as it is spoken,
creating the "karaoke" word-highlight effect popular on short-form video.

ASS format supports per-character timing via {\k} tags.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from loguru import logger
from workers.transcribe import Transcript, Segment, Word
from workers.select_clips import Clip


# ── Style config ──────────────────────────────────────────────────────────────

@dataclass
class CaptionStyle:
    font_name: str = "Arial"
    font_size: int = 52
    bold: bool = True
    primary_color: str = "&H00FFFFFF"        # White (ABGR format for ASS)
    highlight_color: str = "&H0000D7FF"      # Gold/yellow
    outline_color: str = "&H00000000"        # Black outline
    back_color: str = "&H80000000"           # Semi-transparent shadow
    outline_width: float = 2.5
    shadow_depth: float = 1.0
    margin_v: int = 80                       # px from bottom
    alignment: int = 2                       # 2=center bottom, 8=center top

    # Output resolution (must match render target)
    play_res_x: int = 1080
    play_res_y: int = 1920


DEFAULT_STYLE = CaptionStyle()

STYLE_PRESETS: dict[str, CaptionStyle] = {
    "karaoke": CaptionStyle(
        font_name="Arial",
        font_size=52,
        bold=True,
        primary_color="&H00FFFFFF",    # White
        highlight_color="&H0000D7FF",  # Gold / Yellow (#FFD700)
        outline_color="&H00000000",
        outline_width=2.5,
    ),
    "bold_yellow": CaptionStyle(
        font_name="Arial",
        font_size=56,
        bold=True,
        primary_color="&H0000D7FF",    # Yellow base
        highlight_color="&H00FFFFFF",  # White highlight
        outline_color="&H00000000",
        outline_width=3.0,
    ),
    "cyberpunk_neon": CaptionStyle(
        font_name="Arial",
        font_size=54,
        bold=True,
        primary_color="&H00FFFF00",    # Cyan (#00FFFF in BGR is 00FFFF00)
        highlight_color="&H007F00FF",  # Magenta / Hot Pink (#FF007F)
        outline_color="&H00000000",
        outline_width=3.0,
    ),
    "minimal_clean": CaptionStyle(
        font_name="Arial",
        font_size=46,
        bold=False,
        primary_color="&H00F6F4F3",    # Clean off-white
        highlight_color="&H00FAB560",  # Light blue highlight
        outline_color="&H80000000",
        outline_width=1.5,
        shadow_depth=0.5,
    ),
    "fire_red": CaptionStyle(
        font_name="Arial",
        font_size=56,
        bold=True,
        primary_color="&H00FFFFFF",    # White
        highlight_color="&H004444EF",  # Vivid red (#EF4444 in BGR)
        outline_color="&H00000000",
        outline_width=3.0,
    ),
}


def get_caption_style(style_input: dict | str | None) -> CaptionStyle:
    """Resolve CaptionStyle from preset name, custom dict, or return DEFAULT_STYLE."""
    if not style_input:
        return DEFAULT_STYLE
    if isinstance(style_input, str):
        return STYLE_PRESETS.get(style_input, DEFAULT_STYLE)
    if isinstance(style_input, dict):
        # Check if preset name is specified in dict
        preset_name = style_input.get("preset")
        base = STYLE_PRESETS.get(preset_name, DEFAULT_STYLE) if preset_name else DEFAULT_STYLE
        return CaptionStyle(
            font_name=style_input.get("font_name", base.font_name),
            font_size=int(style_input.get("font_size", base.font_size)),
            bold=bool(style_input.get("bold", base.bold)),
            primary_color=_ass_color(style_input.get("primary_color", base.primary_color)),
            highlight_color=_ass_color(style_input.get("highlight_color", base.highlight_color)),
            outline_color=_ass_color(style_input.get("outline_color", base.outline_color)),
            back_color=_ass_color(style_input.get("back_color", base.back_color)),
            outline_width=float(style_input.get("outline_width", base.outline_width)),
            shadow_depth=float(style_input.get("shadow_depth", base.shadow_depth)),
            margin_v=int(style_input.get("margin_v", base.margin_v)),
            alignment=int(style_input.get("alignment", base.alignment)),
        )
    return DEFAULT_STYLE


# ── ASS helpers ───────────────────────────────────────────────────────────────

def _seconds_to_ass_time(seconds: float) -> str:
    """Convert float seconds to ASS time format: H:MM:SS.cs"""
    cs = int(round((seconds % 1) * 100))
    total_s = int(seconds)
    s = total_s % 60
    m = (total_s // 60) % 60
    h = total_s // 3600
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def _ass_color(hex_color: str) -> str:
    """Ensure color is in ASS &H00BBGGRR format. Accepts #RRGGBB or &H…"""
    if hex_color.startswith("&H"):
        return hex_color
    # Convert #RRGGBB → &H00BBGGRR
    h = hex_color.lstrip("#")
    r, g, b = h[0:2], h[2:4], h[4:6]
    return f"&H00{b}{g}{r}"


def _build_ass_header(style: CaptionStyle) -> str:
    """Generate the ASS file header with Script Info and Styles sections."""
    return f"""[Script Info]
ScriptType: v4.00+
PlayResX: {style.play_res_x}
PlayResY: {style.play_res_y}
ScaledBorderAndShadow: yes
WrapStyle: 0

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,{style.font_name},{style.font_size},{style.primary_color},&H000000FF,{style.outline_color},{style.back_color},{int(style.bold)},-1,0,0,100,100,0,0,1,{style.outline_width},{style.shadow_depth},{style.alignment},10,10,{style.margin_v},1
Style: Highlight,{style.font_name},{style.font_size},{style.highlight_color},&H000000FF,{style.outline_color},{style.back_color},{int(style.bold)},-1,0,0,100,100,0,0,1,{style.outline_width},{style.shadow_depth},{style.alignment},10,10,{style.margin_v},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""


def _words_to_karaoke_line(words: list[Word], clip_start: float) -> str:
    r"""
    Convert a list of words to an ASS karaoke-style dialogue line.
    Uses {\k<duration>} tags where duration is in centiseconds.

    Each word is wrapped so it highlights (changes color) at its timestamp.
    """
    parts = []
    for i, word in enumerate(words):
        # Duration this word is highlighted (centiseconds)
        if i + 1 < len(words):
            next_start = words[i + 1].start
        else:
            next_start = word.end

        duration_cs = max(1, int(round((next_start - word.start) * 100)))
        text = word.text.replace("{", "").replace("}", "").strip()

        # {\kf<cs>} = karaoke fill — word highlights progressively
        parts.append(f"{{\\kf{duration_cs}}}{text}")

    return " ".join(parts)


# ── Main ──────────────────────────────────────────────────────────────────────

def generate_captions(
    clip: Clip,
    transcript: Transcript,
    work_dir: Path,
    style: Optional[CaptionStyle] = None,
    max_words_per_line: int = 6,
) -> Path:
    """
    Generate an ASS caption file for a single clip.

    Args:
        clip:               Clip definition (start/end times)
        transcript:         Full transcript (we extract words within clip window)
        work_dir:           Project scratch dir
        style:              Caption visual style (uses DEFAULT_STYLE if None)
        max_words_per_line: Word wrap threshold for readability

    Returns:
        Path to the generated .ass file
    """
    style = style or DEFAULT_STYLE
    captions_dir = work_dir / "captions"
    captions_dir.mkdir(parents=True, exist_ok=True)

    clip_id = f"clip_{int(clip.start * 10):06d}_{int(clip.end * 10):06d}"
    out_path = captions_dir / f"{clip_id}.ass"

    if out_path.exists():
        logger.debug("[Stage 6a] Cached captions: {}", out_path.name)
        return out_path

    # ── Gather words in clip window ───────────────────────────────────────────
    clip_words: list[Word] = []
    for seg in transcript.segments:
        for word in seg.words:
            if clip.start - 0.5 <= word.start <= clip.end + 0.5:
                clip_words.append(word)

    if not clip_words:
        logger.warning(
            "[Stage 6a] No words found for clip {:.1f}s–{:.1f}s", clip.start, clip.end
        )
        # Write empty ASS
        out_path.write_text(_build_ass_header(style))
        return out_path

    # ── Group words into lines ────────────────────────────────────────────────
    lines: list[list[Word]] = []
    current_line: list[Word] = []
    for word in clip_words:
        current_line.append(word)
        if len(current_line) >= max_words_per_line:
            lines.append(current_line)
            current_line = []
    if current_line:
        lines.append(current_line)

    # ── Build ASS dialogue events ─────────────────────────────────────────────
    events: list[str] = []
    for line_words in lines:
        if not line_words:
            continue
        # Timestamps relative to clip start
        line_start = line_words[0].start - clip.start
        line_end = line_words[-1].end - clip.start

        # Add small buffer
        line_start = max(0, line_start - 0.05)
        line_end = line_end + 0.1

        ass_start = _seconds_to_ass_time(line_start)
        ass_end = _seconds_to_ass_time(line_end)
        karaoke_text = _words_to_karaoke_line(line_words, clip.start)

        events.append(
            f"Dialogue: 0,{ass_start},{ass_end},Default,,0,0,0,,{karaoke_text}"
        )

    # ── Write ASS file ────────────────────────────────────────────────────────
    content = _build_ass_header(style) + "\n".join(events)
    out_path.write_text(content, encoding="utf-8")

    logger.debug(
        "[Stage 6a] Captions: {} lines, {} words → {}",
        len(lines), len(clip_words), out_path.name,
    )
    return out_path


# ── SRT & WebVTT Export ───────────────────────────────────────────────────────

def _seconds_to_srt_time(seconds: float) -> str:
    """Format seconds to SRT time format: HH:MM:SS,mmm"""
    total_ms = max(0, int(round(seconds * 1000)))
    ms = total_ms % 1000
    total_s = total_ms // 1000
    s = total_s % 60
    m = (total_s // 60) % 60
    h = total_s // 3600
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def _seconds_to_vtt_time(seconds: float) -> str:
    """Format seconds to WebVTT time format: HH:MM:SS.mmm"""
    total_ms = max(0, int(round(seconds * 1000)))
    ms = total_ms % 1000
    total_s = total_ms // 1000
    s = total_s % 60
    m = (total_s // 60) % 60
    h = total_s // 3600
    return f"{h:02d}:{m:02d}:{s:02d}.{ms:03d}"


def get_clip_words(clip: Clip, transcript: Transcript) -> list[Word]:
    """Gather all words that occur within the clip's time boundary."""
    words: list[Word] = []
    for seg in transcript.segments:
        for word in seg.words:
            if clip.start - 0.5 <= word.start <= clip.end + 0.5:
                words.append(word)
    return words


def generate_srt(
    clip: Clip,
    transcript: Transcript,
    relative: bool = True,
    max_words_per_line: int = 7,
) -> str:
    """Generate SRT subtitle text for a clip."""
    words = get_clip_words(clip, transcript)
    if not words:
        return ""

    lines: list[list[Word]] = []
    curr: list[Word] = []
    for w in words:
        curr.append(w)
        if len(curr) >= max_words_per_line:
            lines.append(curr)
            curr = []
    if curr:
        lines.append(curr)

    srt_entries: list[str] = []
    offset = clip.start if relative else 0.0

    for idx, line_words in enumerate(lines, 1):
        start_sec = max(0.0, line_words[0].start - offset)
        end_sec = max(start_sec + 0.1, line_words[-1].end - offset)
        text = " ".join(w.text.strip() for w in line_words)
        srt_entries.append(
            f"{idx}\n{_seconds_to_srt_time(start_sec)} --> {_seconds_to_srt_time(end_sec)}\n{text}\n"
        )

    return "\n".join(srt_entries)


def generate_vtt(
    clip: Clip,
    transcript: Transcript,
    relative: bool = True,
    max_words_per_line: int = 7,
) -> str:
    """Generate WebVTT subtitle text for a clip."""
    words = get_clip_words(clip, transcript)
    header = "WEBVTT\n\n"
    if not words:
        return header

    lines: list[list[Word]] = []
    curr: list[Word] = []
    for w in words:
        curr.append(w)
        if len(curr) >= max_words_per_line:
            lines.append(curr)
            curr = []
    if curr:
        lines.append(curr)

    vtt_entries: list[str] = []
    offset = clip.start if relative else 0.0

    for idx, line_words in enumerate(lines, 1):
        start_sec = max(0.0, line_words[0].start - offset)
        end_sec = max(start_sec + 0.1, line_words[-1].end - offset)
        text = " ".join(w.text.strip() for w in line_words)
        vtt_entries.append(
            f"{idx}\n{_seconds_to_vtt_time(start_sec)} --> {_seconds_to_vtt_time(end_sec)}\n{text}\n"
        )

    return header + "\n".join(vtt_entries)


def export_subtitles(
    clip: Clip,
    transcript: Transcript,
    fmt: str,
    out_path: Path,
    relative: bool = True,
) -> Path:
    """Export SRT or VTT subtitle file to out_path."""
    fmt_lower = fmt.lower().lstrip(".")
    if fmt_lower == "srt":
        content = generate_srt(clip, transcript, relative=relative)
    elif fmt_lower in ("vtt", "webvtt"):
        content = generate_vtt(clip, transcript, relative=relative)
    else:
        raise ValueError(f"Unsupported subtitle format: {fmt}. Use 'srt' or 'vtt'.")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(content, encoding="utf-8")
    return out_path
