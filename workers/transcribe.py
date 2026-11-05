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


# ── Speaker Diarization ───────────────────────────────────────────────────────

def _extract_segment_audio_features(
    audio_path: Optional[Path],
    segments: list[Segment],
) -> list[tuple[float, float]]:
    """
    Extract lightweight acoustic features (normalized ZCR, RMS energy) per segment
    from a 16kHz mono WAV file if available. Returns empty list if unavailable.
    """
    if not audio_path or not Path(audio_path).exists():
        return []
    try:
        import wave
        import numpy as np

        with wave.open(str(audio_path), "rb") as wf:
            if wf.getsampwidth() != 2:
                return []
            sr = wf.getframerate()
            n_channels = wf.getnchannels()
            total_frames = wf.getnframes()
            raw = wf.readframes(total_frames)

        samples = np.frombuffer(raw, dtype=np.int16).astype(np.float32)
        if n_channels > 1:
            samples = samples[::n_channels]
        if len(samples) == 0:
            return []

        features: list[tuple[float, float]] = []
        for seg in segments:
            s_idx = max(0, int(seg.start * sr))
            e_idx = min(len(samples), int(seg.end * sr))
            chunk = samples[s_idx:e_idx]
            if len(chunk) < 160:
                features.append((0.0, 0.0))
                continue
            rms = float(np.sqrt(np.mean(chunk ** 2))) / 32768.0
            zero_crossings = float(np.mean(np.abs(np.diff(np.signbit(chunk)))))
            features.append((zero_crossings, rms))
        return features
    except Exception:
        return []


def diarize_segments(
    segments: list[Segment],
    audio_path: Optional[Path] = None,
    pause_threshold: float = 1.2,
    max_speakers: int = 2,
) -> list[Segment]:
    """
    Assign speaker labels ("S1", "S2", ...) to transcript segments.
    Combines acoustic feature shifts (when WAV audio is available) with
    conversational turn-taking cues (pauses >= pause_threshold, questions).
    Preserves any existing non-empty speaker labels if all segments are already labeled.
    """
    if not segments:
        return segments

    if all(seg.speaker is not None for seg in segments):
        return segments

    features = _extract_segment_audio_features(audio_path, segments)
    current_speaker_idx = 0
    num_speakers = max(1, max_speakers)

    for i, seg in enumerate(segments):
        if i == 0:
            seg.speaker = seg.speaker or "S1"
            continue

        prev = segments[i - 1]
        gap = max(0.0, seg.start - prev.end)
        prev_text = prev.text.strip()

        # Conversational turn-taking signals
        long_pause = gap >= pause_threshold
        question_turn = prev_text.endswith("?") and gap >= 0.35

        # Acoustic feature distance signal (if WAV features extracted)
        acoustic_shift = False
        if len(features) == len(segments):
            zcr_prev, rms_prev = features[i - 1]
            zcr_curr, rms_curr = features[i]
            if (zcr_prev > 0 or zcr_curr > 0) and abs(zcr_curr - zcr_prev) > 0.045 and gap >= 0.25:
                acoustic_shift = True

        if num_speakers > 1 and (long_pause or question_turn or acoustic_shift):
            current_speaker_idx = (current_speaker_idx + 1) % num_speakers

        seg.speaker = seg.speaker or f"S{current_speaker_idx + 1}"

    return segments


def diarize_transcript(
    transcript: Transcript,
    audio_path: Optional[Path] = None,
    pause_threshold: float = 1.2,
    max_speakers: int = 2,
) -> Transcript:
    """Run speaker diarization on a Transcript object in-place and return it."""
    diarize_segments(
        transcript.segments,
        audio_path=audio_path,
        pause_threshold=pause_threshold,
        max_speakers=max_speakers,
    )
    return transcript


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
    diarize_segments(segments, audio_path=audio_path)
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
