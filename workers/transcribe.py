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
import subprocess
import sys
import time
import wave
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from loguru import logger
from workers.config import (
    WHISPER_MODEL,
    WHISPER_DEVICE,
    WHISPER_COMPUTE,
    WHISPER_FALLBACK_DEVICE,
    WHISPER_FALLBACK_COMPUTE,
)


# ── Data models ───────────────────────────────────────────────────────────────

@dataclass
class Word:
    text: str
    start: float
    end: float
    probability: float
    id: str = ""
    speaker: Optional[str] = None


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

    def __post_init__(self) -> None:
        self.ensure_word_ids()

    def ensure_word_ids(self) -> None:
        """Assign deterministic stable IDs (w_000001, w_000002, ...) to all words."""
        counter = 1
        for seg in self.segments:
            for w in seg.words:
                if not w.id:
                    w.id = f"w_{counter:06d}"
                if not w.speaker and seg.speaker:
                    w.speaker = seg.speaker
                counter += 1

    def word_by_id(self, word_id: str) -> Optional[Word]:
        """Look up a Word by its stable ID (e.g., 'w_000001' or '1')."""
        norm = word_id.strip()
        if norm.isdigit():
            norm = f"w_{int(norm):06d}"
        for w in self.all_words:
            if w.id == norm:
                return w
        return None

    def words_in_id_range(self, start_word_id: str, end_word_id: str) -> list[Word]:
        """Return all words inclusive between start_word_id and end_word_id."""
        self.ensure_word_ids()
        w_start = self.word_by_id(start_word_id)
        w_end = self.word_by_id(end_word_id)
        if not w_start or not w_end:
            return []
        all_w = self.all_words
        try:
            i_start = all_w.index(w_start)
            i_end = all_w.index(w_end)
        except ValueError:
            return []
        if i_start > i_end:
            i_start, i_end = i_end, i_start
        return all_w[i_start : i_end + 1]

    def to_dict(self) -> dict:
        self.ensure_word_ids()
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
                            "id": w.id,
                            "w": w.text,
                            "s": float(round(float(w.start), 3)),
                            "e": float(round(float(w.end), 3)),
                            "p": float(round(float(w.probability), 3)),
                            **({"speaker": w.speaker} if w.speaker else {}),
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
            seg_speaker = s.get("speaker")
            words = [
                Word(
                    text=str(w["w"]),
                    start=float(w["s"]),
                    end=float(w["e"]),
                    probability=float(w.get("p", 1.0)),
                    id=str(w.get("id", "")),
                    speaker=w.get("speaker") or seg_speaker,
                )
                for w in s.get("words", [])
            ]
            segments.append(
                Segment(
                    start=float(s["start"]),
                    end=float(s["end"]),
                    text=str(s["text"]),
                    words=words,
                    speaker=seg_speaker,
                )
            )
        t = cls(
            language=str(data["language"]),
            language_probability=float(data.get("language_probability", 1.0)),
            duration=float(data["duration"]),
            segments=segments,
        )
        t.ensure_word_ids()
        return t



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


def _parse_srt_timestamp(ts: str) -> float:
    """Parse HH:MM:SS,mmm or HH:MM:SS.mmm into seconds."""
    ts = ts.strip().replace(",", ".")
    parts = ts.split(":")
    if len(parts) != 3:
        raise ValueError(f"Invalid SRT timestamp: {ts!r}")
    return int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2])


def transcript_from_srt(srt_text: str, language: str = "en") -> Transcript:
    """
    Build a word-indexed Transcript from a user-uploaded .srt subtitle file override.
    Interpolates word timings proportionally across each subtitle cue and assigns stable IDs.
    """
    import re
    blocks = re.split(r"\n\s*\n", srt_text.strip())
    segments: list[Segment] = []
    max_end = 0.0

    for block in blocks:
        lines = [ln.strip() for ln in block.splitlines() if ln.strip()]
        if len(lines) < 2:
            continue
        time_line_idx = 0
        if "-->" not in lines[0] and len(lines) >= 3 and "-->" in lines[1]:
            time_line_idx = 1
        if "-->" not in lines[time_line_idx]:
            continue
        start_s, end_s = lines[time_line_idx].split("-->", 1)
        seg_start = _parse_srt_timestamp(start_s)
        seg_end = max(seg_start + 0.05, _parse_srt_timestamp(end_s))
        text = " ".join(lines[time_line_idx + 1 :]).strip()
        if not text:
            continue
        tokens = text.split()
        dur = max(0.05, seg_end - seg_start)
        step = dur / max(1, len(tokens))
        words = [
            Word(
                text=tok,
                start=round(seg_start + i * step, 3),
                end=round(seg_start + (i + 1) * step, 3),
                probability=1.0,
            )
            for i, tok in enumerate(tokens)
        ]
        segments.append(Segment(start=seg_start, end=seg_end, text=text, words=words, speaker="S1"))
        max_end = max(max_end, seg_end)

    t = Transcript(language=language, language_probability=1.0, duration=round(max_end, 3), segments=segments)
    t.ensure_word_ids()
    return t


# ── Core function ─────────────────────────────────────────────────────────────

def transcribe(
    audio_path: Path,
    work_dir: Path,
    progress_callback: Optional[Any] = None,
    srt_override: Optional[str] = None,
    custom_vocabulary: Optional[list[str]] = None,
) -> Transcript:
    """
    Transcribe audio using faster-whisper with word-level timestamps.
    Fails loudly if the ASR model is unavailable instead of fabricating a transcript.
    """
    transcript_dir = work_dir / "transcripts"
    transcript_dir.mkdir(parents=True, exist_ok=True)
    cache_path = transcript_dir / "transcript.json"

    if srt_override and srt_override.strip():
        logger.info("[Stage 3] Building transcript from user .srt override")
        transcript = transcript_from_srt(srt_override)
        diarize_segments(transcript.segments, audio_path=audio_path)
        transcript.ensure_word_ids()
        cache_path.write_text(json.dumps(transcript.to_dict(), indent=2, ensure_ascii=False))
        return transcript

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

    # ── Run faster-whisper (auto-install in container if missing, fail loudly if unavailable) ──
    WhisperModel = None
    try:
        from faster_whisper import WhisperModel as _WM
        WhisperModel = _WM
    except ImportError:
        logger.warning("[Stage 3] faster-whisper not found in environment; auto-installing via uv/pip …")
        import shutil
        uv_bin = shutil.which("uv") or str(Path.home() / ".local" / "bin" / "uv")
        if Path(uv_bin).exists():
            subprocess.run(
                [uv_bin, "pip", "install", "--python", sys.executable, "--quiet", "faster-whisper==1.1.1", "numpy"],
                check=False,
            )
        else:
            subprocess.run(
                [sys.executable, "-m", "pip", "install", "--no-cache-dir", "--quiet", "faster-whisper==1.1.1", "numpy"],
                check=False,
            )
        try:
            from faster_whisper import WhisperModel as _WM
            WhisperModel = _WM
        except ImportError as e:
            raise RuntimeError(
                f"ASR backend 'faster-whisper' is not installed ({e}). "
                "Refusing to fabricate a synthetic transcript — install faster-whisper or provide an .srt override."
            ) from e


    initial_prompt = None
    if custom_vocabulary:
        clean_vocab = [v.strip() for v in custom_vocabulary if v and v.strip()]
        if clean_vocab:
            initial_prompt = "Vocabulary: " + ", ".join(clean_vocab)


    logger.info(
        "[Stage 3] Loading Whisper model '{}' on primary device={} (compute={})",
        WHISPER_MODEL, WHISPER_DEVICE, WHISPER_COMPUTE,
    )
    t0 = time.time()
    try:
        model = WhisperModel(
            WHISPER_MODEL,
            device=WHISPER_DEVICE,
            compute_type=WHISPER_COMPUTE,
        )
        raw_segments_gen, info = model.transcribe(
            str(audio_path),
            word_timestamps=True,
            vad_filter=True,
            vad_parameters={
                "threshold": 0.3,
                "min_silence_duration_ms": 500,
                "speech_pad_ms": 250,
            },
            beam_size=5,
            condition_on_previous_text=False,
            repetition_penalty=1.15,
        )
        # Peek first segment to verify CUDA execution works before streaming
        raw_iter = iter(raw_segments_gen)
        first_seg = next(raw_iter, None)
    except Exception as gpu_err:
        if WHISPER_DEVICE.lower() == "cpu":
            raise
        logger.warning(
            "[Stage 3] GPU device '{}' unavailable ({}); falling back to {} (compute={})",
            WHISPER_DEVICE, gpu_err, WHISPER_FALLBACK_DEVICE, WHISPER_FALLBACK_COMPUTE,
        )
        model = WhisperModel(
            WHISPER_MODEL,
            device=WHISPER_FALLBACK_DEVICE,
            compute_type=WHISPER_FALLBACK_COMPUTE,
        )
        raw_segments_gen, info = model.transcribe(
            str(audio_path),
            word_timestamps=True,
            vad_filter=True,
            vad_parameters={
                "threshold": 0.3,
                "min_silence_duration_ms": 500,
                "speech_pad_ms": 250,
            },
            beam_size=5,
            condition_on_previous_text=False,
            repetition_penalty=1.15,
        )
        raw_iter = iter(raw_segments_gen)
        first_seg = next(raw_iter, None)

    logger.info("[Stage 3] Transcribing {} …", audio_path.name)

    def _iter_all():
        if first_seg is not None:
            yield first_seg
        for s in raw_iter:
            yield s

    segments: list[Segment] = []
    last_emit = 0.0
    total_dur = max(1.0, float(getattr(info, "duration", 0.0) or 1.0))

    for seg in _iter_all():
        words = []
        for w in (seg.words or []):
            words.append(Word(
                text=str(w.word),
                start=float(w.start),
                end=float(w.end),
                probability=float(w.probability),
            ))
        segments.append(Segment(
            start=float(seg.start),
            end=float(seg.end),
            text=str(seg.text),
            words=words,
        ))

        now_t = time.time()
        if progress_callback and (now_t - last_emit >= 2.5):
            last_emit = now_t
            try:
                progress_callback(seg.end, total_dur)
            except Exception:
                pass

    # If Silero VAD filtered out >65% of speech (common on videos with loud background music),
    # retry once with vad_filter=False so spoken content over music is preserved.
    covered_dur = sum(max(0.0, s.end - s.start) for s in segments)
    if total_dur >= 30.0 and covered_dur < 0.35 * total_dur:
        logger.warning(
            "[Stage 3] VAD covered only {:.1f}s/{:.1f}s (background music likely); re-running with vad_filter=False",
            covered_dur, total_dur,
        )
        no_vad_gen, info = model.transcribe(
            str(audio_path),
            word_timestamps=True,
            vad_filter=False,
            beam_size=5,
            condition_on_previous_text=False,
            repetition_penalty=1.15,
        )
        segments = []
        for seg in no_vad_gen:
            words = [
                Word(text=w.word, start=w.start, end=w.end, probability=w.probability)
                for w in (seg.words or [])
            ]
            segments.append(Segment(start=seg.start, end=seg.end, text=seg.text, words=words))
            now_t = time.time()
            if progress_callback and (now_t - last_emit >= 2.5):
                last_emit = now_t
                try:
                    progress_callback(seg.end, total_dur)
                except Exception:
                    pass

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
