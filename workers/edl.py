"""
Canonical Edit Decision List (EDL) Schema & Compiler
────────────────────────────────────────────────────
Separates "analysis" from "composition" (suggestions.md §2 & §4):
  - AI stages propose an EDL (`edl.json`).
  - The Studio editor mutates the EDL (trim, excluded words, caption text overrides,
    layout switches, overlays, audio crossfades & loudness).
  - The EDL compiler produces deterministic FFmpeg filtergraphs and two-pass audio args.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Optional

from workers.captions import CaptionStyle, DEFAULT_STYLE, get_clip_words
from workers.reframe import ReframeResult
from workers.select_clips import Clip
from workers.transcribe import Transcript, Word


@dataclass
class EDLCutSegment:
    """A contiguous kept source interval [start, end] in seconds, optionally mapped to word IDs."""
    start: float
    end: float
    start_word_id: str = ""
    end_word_id: str = ""

    @property
    def duration(self) -> float:
        return max(0.0, self.end - self.start)

    def to_dict(self) -> dict[str, Any]:
        return {
            "start": round(self.start, 3),
            "end": round(self.end, 3),
            "duration": round(self.duration, 3),
            "start_word_id": self.start_word_id,
            "end_word_id": self.end_word_id,
        }


@dataclass
class EDLAudioConfig:
    loudnorm_target_i: float = -14.0
    loudnorm_tp: float = -1.5
    loudnorm_lra: float = 11.0
    two_pass_loudnorm: bool = True
    crossfade_ms: int = 15
    music_ducking_db: float = -12.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class EDLOverlay:
    kind: str  # "logo", "text", "broll", "emoji"
    asset_key: Optional[str] = None
    text: Optional[str] = None
    start: float = 0.0
    end: float = 0.0
    x_expr: str = "W-w-36"
    y_expr: str = "36"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class EDL:
    version: int = 1
    clip_id: str = ""
    source_start: float = 0.0
    source_end: float = 0.0
    layout: str = "vertical"
    out_width: int = 1080
    out_height: int = 1920
    cuts: list[EDLCutSegment] = field(default_factory=list)
    crop_keyframes: list[dict[str, Any]] = field(default_factory=list)
    caption_style: dict[str, Any] = field(default_factory=dict)
    excluded_word_indices: list[int] = field(default_factory=list)
    word_overrides: dict[str, str] = field(default_factory=dict)
    overlays: list[EDLOverlay] = field(default_factory=list)
    audio: EDLAudioConfig = field(default_factory=EDLAudioConfig)

    @property
    def total_duration(self) -> float:
        if not self.cuts:
            return max(0.0, self.source_end - self.source_start)
        return round(sum(c.duration for c in self.cuts), 3)

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "clip_id": self.clip_id,
            "source_start": round(self.source_start, 3),
            "source_end": round(self.source_end, 3),
            "total_duration": self.total_duration,
            "layout": self.layout,
            "out_width": self.out_width,
            "out_height": self.out_height,
            "cuts": [c.to_dict() for c in self.cuts],
            "crop_keyframes": self.crop_keyframes,
            "caption_style": self.caption_style,
            "excluded_word_indices": list(self.excluded_word_indices),
            "word_overrides": dict(self.word_overrides),
            "overlays": [o.to_dict() for o in self.overlays],
            "audio": self.audio.to_dict(),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "EDL":

        cuts = [
            EDLCutSegment(
                start=float(c["start"]),
                end=float(c["end"]),
                start_word_id=str(c.get("start_word_id", "")),
                end_word_id=str(c.get("end_word_id", "")),
            )
            for c in data.get("cuts", [])
        ]
        overlays = [EDLOverlay(**o) for o in data.get("overlays", [])]
        audio_raw = data.get("audio") or {}
        audio = EDLAudioConfig(**{k: v for k, v in audio_raw.items() if k in EDLAudioConfig.__dataclass_fields__})
        return cls(
            version=int(data.get("version", 1)),
            clip_id=str(data.get("clip_id", "")),
            source_start=float(data.get("source_start", 0.0)),
            source_end=float(data.get("source_end", 0.0)),
            layout=str(data.get("layout", "vertical")),
            out_width=int(data.get("out_width", 1080)),
            out_height=int(data.get("out_height", 1920)),
            cuts=cuts,
            crop_keyframes=list(data.get("crop_keyframes", [])),
            caption_style=dict(data.get("caption_style") or {}),
            excluded_word_indices=[int(i) for i in data.get("excluded_word_indices", [])],
            word_overrides={str(k): str(v) for k, v in (data.get("word_overrides") or {}).items()},
            overlays=overlays,
            audio=audio,
        )


def compute_cuts_from_excluded_words(
    clip_start: float,
    clip_end: float,
    clip_words: list[Word],
    excluded_word_indices: list[int] | set[int],
    min_cut_duration: float = 0.12,
) -> list[EDLCutSegment]:
    """
    Convert word-level deletions (text-based trimming) into contiguous source video cut segments.
    Deleting words skips their exact frame ranges while merging adjacent kept words.
    """
    excl = set(excluded_word_indices or [])
    if not excl or not clip_words:
        return [
            EDLCutSegment(
                start=clip_start,
                end=clip_end,
                start_word_id=clip_words[0].id if clip_words else "",
                end_word_id=clip_words[-1].id if clip_words else "",
            )
        ]

    segments: list[EDLCutSegment] = []
    cur_words: list[Word] = []

    for idx, w in enumerate(clip_words):
        if idx in excl:
            if cur_words:
                s_t = clip_start if not segments and idx == len(cur_words) else cur_words[0].start
                e_t = cur_words[-1].end
                if (e_t - s_t) >= min_cut_duration:
                    segments.append(
                        EDLCutSegment(
                            start=s_t,
                            end=e_t,
                            start_word_id=cur_words[0].id,
                            end_word_id=cur_words[-1].id,
                        )
                    )
                cur_words = []
        else:
            cur_words.append(w)

    if cur_words:
        s_t = clip_start if not segments and 0 not in excl else cur_words[0].start
        e_t = max(cur_words[-1].end, clip_end if (len(clip_words) - 1) not in excl else cur_words[-1].end)
        if (e_t - s_t) >= min_cut_duration:
            segments.append(
                EDLCutSegment(
                    start=s_t,
                    end=e_t,
                    start_word_id=cur_words[0].id,
                    end_word_id=cur_words[-1].id,
                )
            )

    return segments or [EDLCutSegment(start=clip_start, end=clip_end)]


def compile_edl_from_clip(
    clip: Clip,
    transcript: Optional[Transcript] = None,
    reframe: Optional[ReframeResult] = None,
    caption_style: Optional[dict[str, Any] | CaptionStyle] = None,
    excluded_word_indices: Optional[list[int]] = None,
    word_overrides: Optional[dict[str, str]] = None,
    clip_id: str = "",
    version: int = 1,
) -> EDL:
    """Compile a canonical EDL from a Clip, Transcript, ReframeResult, and Studio overrides."""
    raw_words = get_clip_words(clip, transcript) if transcript else []
    excl_list = sorted({int(i) for i in (excluded_word_indices or [])})
    cuts = compute_cuts_from_excluded_words(clip.start, clip.end, raw_words, excl_list)

    if isinstance(caption_style, CaptionStyle):
        style_dict = asdict(caption_style)
    elif isinstance(caption_style, dict):
        style_dict = dict(caption_style)
    else:
        style_dict = asdict(DEFAULT_STYLE)

    kfs = [kf.to_dict() for kf in reframe.keyframes] if (reframe and reframe.keyframes) else []
    layout = reframe.layout if reframe else "vertical"

    return EDL(
        version=version,
        clip_id=clip_id,
        source_start=clip.start,
        source_end=clip.end,
        layout=layout,
        cuts=cuts,
        crop_keyframes=kfs,
        caption_style=style_dict,
        excluded_word_indices=excl_list,
        word_overrides={str(k): str(v) for k, v in (word_overrides or {}).items()},
    )


def build_edl_audio_filter(edl: EDL) -> str:
    """
    Build the FFmpeg audio filter string with 15ms cut boundary crossfade/fade-in/out
    (preventing audio clicks at splice boundaries) and EBU R128 loudness normalization.
    """
    fade_s = max(0.005, edl.audio.crossfade_ms / 1000.0)
    dur = max(0.1, edl.total_duration)
    fade_out_st = max(0.0, dur - fade_s)
    loudnorm = (
        f"loudnorm=I={edl.audio.loudnorm_target_i}:"
        f"TP={edl.audio.loudnorm_tp}:LRA={edl.audio.loudnorm_lra}"
    )
    return f"afade=t=in:st=0:d={fade_s:.3f},afade=t=out:st={fade_out_st:.3f}:d={fade_s:.3f},{loudnorm}"

