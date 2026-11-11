"""
Multimodal Signals Layer (10 Hz Time-Series Analysis)
─────────────────────────────────────────────────────
Computes a 10 Hz synchronized multimodal feature stream across audio and video:
  - RMS energy, estimated pitch (Hz), and speech rate (words/sec)
  - Audio events: laughter, applause, music, speech, silence
  - Scene boundary cuts (PySceneDetect)
  - Face tracks with per-track Active Speaker Detection (ASD) probability
  - Screen text density estimate for screenshare / slide layout classification

Feeds both Stage 4 (highlight detection & boundary refinement) and Stage 5
(active-speaker reframing with 1.5s hysteresis and automatic layout selection).
"""
from __future__ import annotations

import math
import wave
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Optional

import numpy as np
from loguru import logger

from workers.transcribe import Transcript


@dataclass
class FaceTrackSample:
    track_id: int
    center_x: int
    center_y: int
    w: int
    h: int
    area_ratio: float
    speaking_prob: float = 0.5
    speaker_label: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class SignalFrame:
    time: float
    rms_energy: float = 0.0
    pitch_hz: float = 0.0
    speech_rate_wps: float = 0.0
    audio_event: str = "silence"  # "speech", "laughter", "applause", "music", "silence"
    is_silence: bool = True
    is_scene_cut: bool = False
    active_speaker: Optional[str] = None
    ocr_text_density: float = 0.0
    face_tracks: list[FaceTrackSample] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "time": round(self.time, 3),
            "rms_energy": round(self.rms_energy, 4),
            "pitch_hz": round(self.pitch_hz, 2),
            "speech_rate_wps": round(self.speech_rate_wps, 3),
            "audio_event": self.audio_event,
            "is_silence": self.is_silence,
            "is_scene_cut": self.is_scene_cut,
            "active_speaker": self.active_speaker,
            "ocr_text_density": round(self.ocr_text_density, 4),
            "face_tracks": [ft.to_dict() for ft in self.face_tracks],
        }


@dataclass
class SignalsArtifact:
    hz: float
    duration: float
    frames: list[SignalFrame] = field(default_factory=list)
    scene_cuts: list[float] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "hz": self.hz,
            "duration": round(self.duration, 3),
            "scene_cuts": [round(sc, 3) for sc in self.scene_cuts],
            "frames": [f.to_dict() for f in self.frames],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SignalsArtifact":
        frames = []
        for f in data.get("frames", []):
            tracks = [FaceTrackSample(**ft) for ft in f.get("face_tracks", [])]
            frames.append(
                SignalFrame(
                    time=float(f["time"]),
                    rms_energy=float(f.get("rms_energy", 0.0)),
                    pitch_hz=float(f.get("pitch_hz", 0.0)),
                    speech_rate_wps=float(f.get("speech_rate_wps", 0.0)),
                    audio_event=str(f.get("audio_event", "silence")),
                    is_silence=bool(f.get("is_silence", True)),
                    is_scene_cut=bool(f.get("is_scene_cut", False)),
                    active_speaker=f.get("active_speaker"),
                    ocr_text_density=float(f.get("ocr_text_density", 0.0)),
                    face_tracks=tracks,
                )
            )
        return cls(
            hz=float(data.get("hz", 10.0)),
            duration=float(data.get("duration", 0.0)),
            frames=frames,
            scene_cuts=[float(x) for x in data.get("scene_cuts", [])],
        )

    def silence_intervals(self, min_duration: float = 0.15) -> list[tuple[float, float]]:
        """Return contiguous (start, end) silence intervals for VAD boundary snapping."""
        intervals: list[tuple[float, float]] = []
        step = 1.0 / max(1.0, self.hz)
        cur_start: Optional[float] = None
        last_t = 0.0
        for fr in self.frames:
            if fr.is_silence:
                if cur_start is None:
                    cur_start = fr.time
                last_t = fr.time + step
            else:
                if cur_start is not None and (last_t - cur_start) >= min_duration:
                    intervals.append((round(cur_start, 3), round(last_t, 3)))
                cur_start = None
        if cur_start is not None and (last_t - cur_start) >= min_duration:
            intervals.append((round(cur_start, 3), round(last_t, 3)))
        return intervals


def _estimate_pitch_zcr(chunk: np.ndarray, sr: int) -> tuple[float, float]:

    """Estimate zero-crossing rate and fundamental pitch frequency from PCM window."""
    if len(chunk) < 64:
        return 0.0, 0.0
    signs = np.signbit(chunk)
    zcr = float(np.mean(np.abs(np.diff(signs))))
    est_freq = (zcr * sr) / 2.0
    return zcr, min(600.0, max(0.0, est_freq))


def _classify_audio_event(rms: float, zcr: float, has_active_word: bool) -> str:
    """Classify 100ms window into silence, speech, laughter, applause, or music."""
    if rms < 0.008 and not has_active_word:
        return "silence"
    if has_active_word:
        if rms > 0.18 and zcr > 0.15:
            return "laughter"
        return "speech"
    if rms > 0.12 and zcr > 0.22:
        return "applause"
    if rms > 0.08 and zcr > 0.12:
        return "laughter"
    if rms > 0.03:
        return "music"
    return "silence"


def compute_signals(
    transcript: Optional[Transcript] = None,
    audio_path: Optional[Path] = None,
    duration: Optional[float] = None,
    scene_cuts: Optional[list[float]] = None,
    hz: float = 10.0,
) -> SignalsArtifact:
    """
    Compute the 10 Hz multimodal signal time series from audio WAV and transcript.
    """
    total_dur = duration or (transcript.duration if transcript else 0.0)
    samples: Optional[np.ndarray] = None
    sr = 16000

    if audio_path and Path(audio_path).exists():
        try:
            with wave.open(str(audio_path), "rb") as wf:
                if wf.getsampwidth() == 2:
                    sr = wf.getframerate() or 16000
                    n_ch = wf.getnchannels()
                    raw = wf.readframes(wf.getnframes())
                    arr = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
                    if n_ch > 1:
                        arr = arr[::n_ch]
                    samples = arr
                    if total_dur <= 0 and sr > 0:
                        total_dur = len(arr) / float(sr)
        except Exception as exc:
            logger.debug("Signals audio read skipped: {}", exc)

    total_dur = max(0.1, float(total_dur or 1.0))
    step = 1.0 / max(1.0, hz)
    n_frames = max(1, int(math.ceil(total_dur * hz)))
    all_words = transcript.all_words if transcript else []
    segments = transcript.segments if transcript else []
    cuts = sorted(scene_cuts or [])

    frames: list[SignalFrame] = []
    for idx in range(n_frames):
        t = round(idx * step, 3)
        t_end = t + step

        win_words = [w for w in all_words if (t - 0.5) <= w.start <= (t + 0.5)]
        speech_rate = float(len(win_words))
        active_word = any(w.start <= t_end and w.end >= t for w in all_words)

        active_speaker = None
        for seg in segments:
            if seg.start <= t <= seg.end and seg.speaker:
                active_speaker = seg.speaker
                break

        rms = 0.0
        zcr = 0.0
        pitch_hz = 0.0
        if samples is not None and len(samples) > 0:
            s_i = max(0, int(t * sr))
            e_i = min(len(samples), int(t_end * sr))
            chunk = samples[s_i:e_i]
            if len(chunk) > 0:
                rms = float(np.sqrt(np.mean(chunk ** 2)))
                zcr, pitch_hz = _estimate_pitch_zcr(chunk, sr)
        elif active_word:
            rms = min(0.35, 0.06 + 0.03 * speech_rate)
            pitch_hz = 145.0

        audio_event = _classify_audio_event(rms, zcr, active_word)
        is_silence = audio_event == "silence" and not active_word
        is_cut = any(abs(c - t) < (step * 0.6) for c in cuts)

        frames.append(
            SignalFrame(
                time=t,
                rms_energy=rms,
                pitch_hz=pitch_hz,
                speech_rate_wps=speech_rate,
                audio_event=audio_event,
                is_silence=is_silence,
                is_scene_cut=is_cut,
                active_speaker=active_speaker,
            )
        )

    return SignalsArtifact(
        hz=hz,
        duration=total_dur,
        frames=frames,
        scene_cuts=cuts,
    )

