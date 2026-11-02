"""
Stage 3: Transcription (ASR)
──────────────────────────────
Uses faster-whisper to produce a word-level timestamped transcript.
- Model: configurable (base/small/medium/large-v3)
- Device: cpu (default) or cuda
- VAD filtering: removes silence before transcription (faster, fewer hallucinations)

Output: transcript.json saved to work_dir/transcripts/
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from loguru import logger
from workers.config import WHISPER_MODEL, WHISPER_DEVICE, WHISPER_COMPUTE


# ── Data models ───────────────────────────────────────────────────────────────

@dataclass
class Word:
    text: str
    start: float
    end: float
    probability: float


@dataclass
class Segment:
    start: float
    end: float
    text: str
    words: list[Word] = field(default_factory=list)
    speaker: Optional[str] = None


@dataclass
class Transcript:
    language: str
    language_probability: float
    duration: float
    segments: list[Segment] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "language": self.language,
            "language_probability": self.language_probability,
            "duration": self.duration,
            "segments": [
                {
                    "start": s.start,
                    "end": s.end,
                    "text": s.text,
                    "speaker": s.speaker,
                    "words": [
                        {
                            "w": w.text,
                            "s": round(w.start, 3),
                            "e": round(w.end, 3),
                            "p": round(w.probability, 3),
                        }
                        for w in s.words
                    ],
                }
                for s in self.segments
            ],
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Transcript":
        segments = []
        for s in data.get("segments", []):
            words = [
                Word(text=w["w"], start=w["s"], end=w["e"], probability=w["p"])
                for w in s.get("words", [])
            ]
            segments.append(
                Segment(
                    start=s["start"],
                    end=s["end"],
                    text=s["text"],
                    words=words,
                    speaker=s.get("speaker"),
                )
            )
        return cls(
            language=data["language"],
            language_probability=data.get("language_probability", 1.0),
            duration=data["duration"],
            segments=segments,
        )

    @property
    def full_text(self) -> str:
        return " ".join(s.text.strip() for s in self.segments)

    @property
    def all_words(self) -> list[Word]:
        return [w for s in self.segments for w in s.words]


# ── Core function ─────────────────────────────────────────────────────────────

def transcribe(audio_path: Path, work_dir: Path) -> Transcript:
    """
    Transcribe audio using faster-whisper with word-level timestamps.

    Args:
        audio_path: path to the 16kHz mono WAV (output of Stage 2)
        work_dir:   project scratch dir — transcript.json cached here

    Returns:
        Transcript dataclass
    """
    transcript_dir = work_dir / "transcripts"
    transcript_dir.mkdir(parents=True, exist_ok=True)
    cache_path = transcript_dir / "transcript.json"

    # ── Cache hit ─────────────────────────────────────────────────────────────
    if cache_path.exists():
        logger.info("[Stage 3] Loading cached transcript from {}", cache_path)
        data = json.loads(cache_path.read_text())
        t = Transcript.from_dict(data)
        logger.success(
            "[Stage 3] ✓ Transcript loaded: {} segments, language={}",
            len(t.segments), t.language,
        )
        return t

    # ── Run faster-whisper ────────────────────────────────────────────────────
    try:
        from faster_whisper import WhisperModel
    except ImportError:
        raise ImportError(
            "faster-whisper is not installed. "
            "Run: uv pip install faster-whisper"
        )

    logger.info(
        "[Stage 3] Loading Whisper model '{}' on {} (compute={})",
        WHISPER_MODEL, WHISPER_DEVICE, WHISPER_COMPUTE,
    )
    model = WhisperModel(
        WHISPER_MODEL,
        device=WHISPER_DEVICE,
        compute_type=WHISPER_COMPUTE,
    )

    logger.info("[Stage 3] Transcribing {} …", audio_path.name)
    t0 = time.time()

    raw_segments, info = model.transcribe(
        str(audio_path),
        word_timestamps=True,
        vad_filter=True,
        vad_parameters={
            "min_silence_duration_ms": 500,
            "speech_pad_ms": 200,
        },
        beam_size=5,
    )

    segments: list[Segment] = []
    for seg in raw_segments:
        words = []
        for w in (seg.words or []):
            words.append(Word(
                text=w.word,
                start=w.start,
                end=w.end,
                probability=w.probability,
            ))
        segments.append(Segment(
            start=seg.start,
            end=seg.end,
            text=seg.text,
            words=words,
        ))

    elapsed = time.time() - t0
    transcript = Transcript(
        language=info.language,
        language_probability=round(info.language_probability, 3),
        duration=info.duration,
        segments=segments,
    )

    # ── Save to cache ─────────────────────────────────────────────────────────
    cache_path.write_text(json.dumps(transcript.to_dict(), indent=2, ensure_ascii=False))

    word_count = len(transcript.all_words)
    logger.success(
        "[Stage 3] ✓ Transcription done in {:.1f}s | lang={} | {} segments | {} words",
        elapsed, transcript.language, len(transcript.segments), word_count,
    )
    return transcript
