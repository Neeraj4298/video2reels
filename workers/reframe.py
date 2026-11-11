"""
Stage 5: Smart Vertical Reframing (9:16)
────────────────────────────────────────
Converts a landscape clip to 9:16 portrait using active speaker face tracking,
scene cut detection (PySceneDetect), and smoothed motion paths (Kalman/EMA).

Algorithm:
  1. Detect scene cuts within the clip using PySceneDetect (prevents panning across cuts).
  2. Sample frames at ~2–4 fps across each scene.
  3. Detect faces using MediaPipe BlazeFace (with OpenCV Haar cascade fallback).
  4. Select primary speaker face (largest area + centered / continuity bias).
  5. Fallback to center-crop if no face is detected.
  6. Smooth crop trajectory with deadband, max pan speed limit (e.g. 15%/sec),
     and EMA smoothing within each scene.
  7. Generate crop keyframes and dynamic FFmpeg filter expressions.
  8. Support blur-background (portrait canvas with blurred background) layout option.
"""
from __future__ import annotations

import json
import math
import os
import subprocess
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Optional

try:
    import cv2
    import numpy as np
except ImportError:
    subprocess.run(
        [
            sys.executable, "-m", "pip", "install",
            "--no-cache-dir", "--quiet", "--force-reinstall",
            "opencv-python-headless>=4.10", "numpy>=1.26",
        ],
        check=False,
    )
    try:
        import cv2
        import numpy as np
    except ImportError:
        cv2 = None  # type: ignore[assignment]
        np = None   # type: ignore[assignment]

from loguru import logger

from workers.config import (
    MODELS_DIR,
    OUTPUT_HEIGHT,
    OUTPUT_WIDTH,
    REFRAME_DEADBAND,
    REFRAME_DEFAULT_LAYOUT,
    REFRAME_EMA_ALPHA,
    REFRAME_MAX_PAN_SPEED,
    REFRAME_SAMPLE_FPS,
)
from workers.ingest import _ffmpeg_bin
from workers.select_clips import Clip


# ── Data Models ───────────────────────────────────────────────────────────────

@dataclass
class CropKeyframe:
    frame: int
    time: float
    x: int      # left edge of crop window
    y: int      # top edge of crop window
    w: int      # crop window width
    h: int      # crop window height

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CropKeyframe:
        return cls(
            frame=int(data.get("frame", 0)),
            time=float(data.get("time", 0.0)),
            x=int(data.get("x", 0)),
            y=int(data.get("y", 0)),
            w=int(data.get("w", 608)),
            h=int(data.get("h", 1080)),
        )


@dataclass
class ReframeResult:
    clip: Clip
    video_path: Path
    keyframes: list[CropKeyframe]
    crop_w: int
    crop_h: int
    layout: str = "vertical"  # "vertical", "blur_bg", "split_screen"
    out_width: int = OUTPUT_WIDTH
    out_height: int = OUTPUT_HEIGHT
    face_in_frame_ratio: float = 1.0
    crop_filter_expr: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "start": self.clip.start,
            "end": self.clip.end,
            "crop_w": self.crop_w,
            "crop_h": self.crop_h,
            "layout": self.layout,
            "out_width": self.out_width,
            "out_height": self.out_height,
            "face_in_frame_ratio": round(self.face_in_frame_ratio, 3),
            "crop_filter_expr": self.crop_filter_expr,
            "keyframes": [kf.to_dict() for kf in self.keyframes],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any], clip: Optional[Clip] = None) -> ReframeResult:
        c = clip or Clip(
            start=data.get("start", 0.0),
            end=data.get("end", 0.0),
            hook="",
            title="",
            score=0,
            score_breakdown=None,
            reason="",
        )
        keyframes = [CropKeyframe.from_dict(k) for k in data.get("keyframes", [])]
        return cls(
            clip=c,
            video_path=Path(""),
            keyframes=keyframes,
            crop_w=int(data.get("crop_w", 608)),
            crop_h=int(data.get("crop_h", 1080)),
            layout=str(data.get("layout", "vertical")),
            out_width=int(data.get("out_width", OUTPUT_WIDTH)),
            out_height=int(data.get("out_height", OUTPUT_HEIGHT)),
            face_in_frame_ratio=float(data.get("face_in_frame_ratio", 1.0)),
            crop_filter_expr=str(data.get("crop_filter_expr", "")),
        )


# ── Crop Window Geometry ──────────────────────────────────────────────────────

def _compute_center_crop(src_w: int, src_h: int) -> tuple[int, int, int, int]:
    """
    Compute a centered 9:16 crop window for a given source resolution.
    Ensures crop dimensions and offsets are even integers.
    """
    target_ratio = 9 / 16
    crop_h = src_h
    crop_w = int(crop_h * target_ratio)

    if crop_w % 2 != 0:
        crop_w -= 1

    if crop_w > src_w:
        crop_w = src_w
        if crop_w % 2 != 0:
            crop_w -= 1
        crop_h = int(crop_w / target_ratio)
        if crop_h % 2 != 0:
            crop_h -= 1

    x = (src_w - crop_w) // 2
    if x % 2 != 0:
        x -= 1
    y = (src_h - crop_h) // 2
    if y % 2 != 0:
        y -= 1
    return max(0, x), max(0, y), crop_w, crop_h


def _ema_smooth(values: list[float], alpha: float = REFRAME_EMA_ALPHA) -> list[float]:
    """Exponential moving average smoothing."""
    if not values:
        return values
    smoothed = [values[0]]
    for v in values[1:]:
        smoothed.append(alpha * v + (1.0 - alpha) * smoothed[-1])
    return smoothed


class KalmanFilter1D:
    """
    1D Kalman Filter for smoothing horizontal camera crop coordinates.
    Tracks state x (position) with process variance Q and measurement variance R.
    """

    def __init__(
        self,
        initial_value: float = 0.0,
        process_variance: float = 1e-2,
        measurement_variance: float = 0.08,
    ):
        self.x = float(initial_value)
        self.p = 1.0
        self.q = float(process_variance)
        self.r = float(measurement_variance)

    def reset(self, value: float) -> float:
        self.x = float(value)
        self.p = 1.0
        return self.x

    def update(self, measurement: float) -> float:
        # Prediction update
        p_pred = self.p + self.q
        # Measurement update (Kalman gain)
        k = p_pred / (p_pred + self.r)
        self.x = self.x + k * (float(measurement) - self.x)
        self.p = (1.0 - k) * p_pred
        return self.x


def _kalman_smooth(
    values: list[float],
    process_variance: float = 1e-2,
    measurement_variance: float = 0.08,
) -> list[float]:
    """Apply 1D Kalman filter across a sequence of position measurements."""
    if not values:
        return values
    kf = KalmanFilter1D(
        initial_value=values[0],
        process_variance=process_variance,
        measurement_variance=measurement_variance,
    )
    out = [values[0]]
    for v in values[1:]:
        out.append(kf.update(v))
    return out


# ── Scene Boundary Cut Detection (PySceneDetect) ───────────────────────────────

def detect_scenes(
    video_path: Path,
    start_sec: float = 0.0,
    end_sec: Optional[float] = None,
    threshold: float = 27.0,
) -> list[tuple[float, float]]:
    """
    Detect scene cuts using PySceneDetect.
    Returns list of (start_time, end_time) intervals within [start_sec, end_sec].
    """
    try:
        from scenedetect import ContentDetector, detect
        detect_kwargs: dict[str, Any] = {}
        if start_sec > 0:
            detect_kwargs["start_time"] = float(start_sec)
        if end_sec is not None:
            detect_kwargs["end_time"] = float(end_sec)
        scene_list = detect(
            str(video_path),
            ContentDetector(threshold=threshold),
            **detect_kwargs,
        )
        cuts = []
        for s in scene_list:
            s_start = s[0].seconds
            s_end = s[1].seconds
            # Overlap with [start_sec, end_sec]
            clip_end = end_sec if end_sec is not None else s_end
            if s_end > start_sec and s_start < clip_end:
                cuts.append((max(start_sec, s_start), min(clip_end, s_end)))

        if cuts:
            return cuts
    except Exception as exc:
        logger.debug("[reframe] Scene detection fallback: {}", exc)

    total_end = end_sec if end_sec is not None else (start_sec + 30.0)
    return [(start_sec, total_end)]


# ── Face Detection Engine ─────────────────────────────────────────────────────

class FaceDetectorEngine:
    """
    Multi-backend face detector:
      1. MediaPipe Tasks FaceDetector (BlazeFace short-range)
      2. OpenCV Haar Cascade (haarcascade_frontalface_default.xml)
    """

    def __init__(self, models_dir: Path = MODELS_DIR):
        self.models_dir = Path(models_dir)
        self._mp_detector = None
        self._haar_classifier = None
        self._init_mediapipe()
        if not self._mp_detector:
            self._init_haar()

    def _init_mediapipe(self):
        tflite_path = self.models_dir / "blaze_face_short_range.tflite"
        if not tflite_path.exists():
            return
        try:
            import mediapipe as mp
            from mediapipe.tasks.python import vision
            from mediapipe.tasks.python.core.base_options import BaseOptions

            options = vision.FaceDetectorOptions(
                base_options=BaseOptions(model_asset_path=str(tflite_path)),
                min_detection_confidence=0.35,
            )
            self._mp_detector = vision.FaceDetector.create_from_options(options)
            logger.debug("[reframe] MediaPipe FaceDetector initialised")
        except Exception as exc:
            logger.warning("[reframe] Could not init MediaPipe FaceDetector: {}", exc)
            self._mp_detector = None

    def _init_haar(self):
        haar_path = self.models_dir / "haarcascade_frontalface_default.xml"
        if not haar_path.exists():
            return
        try:
            clf = cv2.CascadeClassifier(str(haar_path))
            if not clf.empty():
                self._haar_classifier = clf
                logger.debug("[reframe] OpenCV Haar Classifier initialised")
        except Exception as exc:
            logger.warning("[reframe] Could not init Haar classifier: {}", exc)
            self._haar_classifier = None

    def detect(self, bgr_frame: np.ndarray) -> list[dict[str, Any]]:
        """
        Detect faces in a BGR OpenCV frame.
        Returns list of dicts: {x, y, w, h, confidence, center_x, center_y}.
        """
        h, w = bgr_frame.shape[:2]
        faces = []

        # 1. Try MediaPipe
        if self._mp_detector:
            try:
                import mediapipe as mp
                rgb = cv2.cvtColor(bgr_frame, cv2.COLOR_BGR2RGB)
                mp_img = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
                results = self._mp_detector.detect(mp_img)
                if results and results.detections:
                    for d in results.detections:
                        bb = d.bounding_box
                        score = d.categories[0].score if d.categories else 0.5
                        bx = max(0, bb.origin_x)
                        by = max(0, bb.origin_y)
                        bw = min(w - bx, bb.width)
                        bh = min(h - by, bb.height)
                        faces.append({
                            "x": bx, "y": by, "w": bw, "h": bh,
                            "confidence": float(score),
                            "center_x": bx + bw / 2.0,
                            "center_y": by + bh / 2.0,
                        })
                    return faces
            except Exception as exc:
                logger.debug("[reframe] MediaPipe detect error: {}", exc)

        # 2. Fallback to Haar Cascade
        if self._haar_classifier:
            try:
                gray = cv2.cvtColor(bgr_frame, cv2.COLOR_BGR2GRAY)
                detected = self._haar_classifier.detectMultiScale(
                    gray, scaleFactor=1.15, minNeighbors=4, minSize=(30, 30)
                )
                for (hx, hy, hw, hh) in detected:
                    faces.append({
                        "x": int(hx), "y": int(hy), "w": int(hw), "h": int(hh),
                        "confidence": 0.7,
                        "center_x": hx + hw / 2.0,
                        "center_y": hy + hh / 2.0,
                    })
                return faces
            except Exception as exc:
                logger.debug("[reframe] Haar detect error: {}", exc)

        return faces

    def close(self):
        if self._mp_detector:
            try:
                self._mp_detector.close()
            except Exception:
                pass
            self._mp_detector = None


def select_primary_face(
    faces: list[dict[str, Any]],
    prev_center_x: Optional[float] = None,
    src_w: int = 1920,
) -> Optional[dict[str, Any]]:
    """
    Select the primary speaker face among detected candidates.
    Balances face area (prominence), speaking probability (ASD), and continuity.
    """
    if not faces:
        return None
    if len(faces) == 1:
        return faces[0]

    best_face = None
    best_score = -1.0

    for f in faces:
        area = f["w"] * f["h"]
        cx = f["center_x"]
        speaking_prob = float(f.get("speaking_prob", 0.5))

        # Continuity penalty (if we were already tracking a subject)
        dist_prev = abs(cx - prev_center_x) / src_w if prev_center_x is not None else 0.0
        # Centering bias (faces near horizontal center are more likely the main subject)
        dist_center = abs(cx - (src_w / 2.0)) / src_w

        score = area * (0.65 + 0.70 * speaking_prob) * (1.0 - 0.35 * dist_prev - 0.15 * dist_center)
        if score > best_score:
            best_score = score
            best_face = f

    return best_face


def select_active_speaker_face(
    faces: list[dict[str, Any]],
    current_time: float,
    prev_face: Optional[dict[str, Any]] = None,
    last_switch_time: float = -10.0,
    hysteresis_sec: float = 1.5,
    diarized_speaker: Optional[str] = None,
    src_w: int = 1920,
) -> tuple[Optional[dict[str, Any]], float]:
    """
    Fuse diarization, ASD (speaking_prob), and face tracks to pick the active speaker,
    enforcing a 1.5s hysteresis hold so the virtual camera does not ping-pong between speakers.
    Returns (selected_face, updated_last_switch_time).
    """
    if not faces:
        return None, last_switch_time
    if len(faces) == 1:
        return faces[0], last_switch_time

    # Map diarized speaker ("S1" -> left/first speaker, "S2" -> right/second speaker) as a prior
    sorted_by_x = sorted(faces, key=lambda f: f["center_x"])
    for idx, f in enumerate(sorted_by_x):
        inferred_label = f"S{idx + 1}"
        base_prob = float(f.get("speaking_prob", 0.5))
        if diarized_speaker and diarized_speaker == inferred_label:
            f = dict(f)
            f["speaking_prob"] = min(1.0, base_prob + 0.35)
            sorted_by_x[idx] = f

    prev_cx = prev_face["center_x"] if prev_face else None
    candidate = select_primary_face(sorted_by_x, prev_center_x=prev_cx, src_w=src_w)

    if prev_face is not None and candidate is not None:
        dist_ratio = abs(candidate["center_x"] - prev_face["center_x"]) / max(1.0, float(src_w))
        # If switching to a different person (horizontal separation > 15% of frame width)
        if dist_ratio > 0.15:
            if (current_time - last_switch_time) < hysteresis_sec:
                # Hold onto the face closest to prev_face unless hysteresis window has elapsed
                nearest_prev = min(
                    sorted_by_x,
                    key=lambda f: abs(f["center_x"] - prev_face["center_x"]),
                )
                return nearest_prev, last_switch_time
            return candidate, current_time

    return candidate, last_switch_time


def classify_layout(
    faces: list[dict[str, Any]],
    src_w: int = 1920,
    src_h: int = 1080,
    ocr_text_density: float = 0.0,
) -> str:
    """
    Automatic layout classifier (suggestions.md §3 Reframing):
      - Slides or text-dense frames (ocr_text_density >= 0.35) -> 'screenshare'
      - Corner webcam face + busy content -> 'gameplay'
      - 2 prominent faces separated horizontally in same frame -> 'split_screen'
      - 1 usable face -> 'vertical' (Fill)
      - 0 usable faces -> 'blur_bg' (Fit with blurred background)
    """
    if ocr_text_density >= 0.35:
        return "screenshare"
    if not faces:
        return "blur_bg"
    frame_area = max(1, src_w * src_h)
    valid = [f for f in faces if (f["w"] * f["h"]) / frame_area >= 0.004]
    if not valid:
        return "blur_bg"
    if len(valid) == 1:
        f0 = valid[0]
        area_ratio = (f0["w"] * f0["h"]) / frame_area
        in_corner = (f0["center_x"] < 0.25 * src_w or f0["center_x"] > 0.75 * src_w) and (
            f0["center_y"] < 0.30 * src_h or f0["center_y"] > 0.70 * src_h
        )
        if in_corner and area_ratio < 0.04:
            return "gameplay"
        return "vertical"
    # Two or more faces: check horizontal separation
    sorted_f = sorted(valid, key=lambda f: f["w"] * f["h"], reverse=True)[:2]
    sep = abs(sorted_f[0]["center_x"] - sorted_f[1]["center_x"]) / max(1.0, float(src_w))
    if sep >= 0.22:
        return "split_screen"
    return "vertical"


def compute_face_in_frame_ratio(
    face_centers_per_frame: list[Optional[float]],
    keyframes: list[CropKeyframe],
    crop_w: int,
) -> float:
    """
    Measure true geometric face-in-frame rate: the fraction of detected-face samples
    where the active speaker's face center lies inside the smoothed crop window [kf.x, kf.x + crop_w].
    """
    if not face_centers_per_frame or not keyframes:
        return 1.0
    detected_samples = 0
    in_frame_samples = 0
    for idx, face_cx in enumerate(face_centers_per_frame):
        if face_cx is None:
            continue
        detected_samples += 1
        kf = keyframes[min(idx, len(keyframes) - 1)]
        if kf.x <= face_cx <= (kf.x + crop_w):
            in_frame_samples += 1
    if detected_samples == 0:
        return 1.0
    return round(in_frame_samples / float(detected_samples), 4)



# ── Motion Smoothing & Pan Limiting ───────────────────────────────────────────

def smooth_crop_trajectory(
    raw_positions: list[dict[str, Any]],
    scenes: list[tuple[float, float]],
    src_w: int,
    crop_w: int,
    max_pan_speed: float = REFRAME_MAX_PAN_SPEED,
    deadband_ratio: float = REFRAME_DEADBAND,
    alpha: float = REFRAME_EMA_ALPHA,
) -> list[CropKeyframe]:
    """
    Enforces deadband, pan speed limiting, and EMA smoothing.
    At scene cuts, the camera snaps instantly without panning across cuts.
    """
    if not raw_positions:
        return []

    max_x = src_w - crop_w
    deadband_px = deadband_ratio * src_w
    smoothed_keyframes: list[CropKeyframe] = []

    # Map timestamps to scene index
    def get_scene_index(t: float) -> int:
        for idx, (s_start, s_end) in enumerate(scenes):
            if s_start <= t <= s_end:
                return idx
        return 0

    current_scene = None
    prev_x = None
    prev_time = None
    kalman = KalmanFilter1D()

    for item in raw_positions:
        t = item["time"]
        frame = item["frame"]
        raw_x = item["target_x"]
        scene_idx = get_scene_index(t)

        if current_scene != scene_idx or prev_x is None:
            # Cut or first frame: snap to target immediately and reset Kalman state
            smoothed_x = kalman.reset(raw_x)
            current_scene = scene_idx
        else:
            dt = max(t - prev_time, 1e-4)
            # 1. Deadband check
            if abs(raw_x - prev_x) < deadband_px:
                target_x = prev_x
            else:
                target_x = raw_x

            # 2. Max pan speed limiting
            max_delta = max_pan_speed * src_w * dt
            delta = target_x - prev_x
            if abs(delta) > max_delta:
                target_x = prev_x + math.copysign(max_delta, delta)

            # 3. Kalman + EMA smoothing
            kalman_x = kalman.update(target_x)
            smoothed_x = alpha * kalman_x + (1.0 - alpha) * prev_x

        # Clamp and make even
        final_x = int(round(smoothed_x))
        final_x = max(0, min(max_x, final_x))
        if final_x % 2 != 0:
            final_x -= 1

        prev_x = float(final_x)
        prev_time = t

        smoothed_keyframes.append(
            CropKeyframe(
                frame=frame,
                time=t,
                x=final_x,
                y=0,
                w=crop_w,
                h=item.get("crop_h", 1080),
            )
        )

    return smoothed_keyframes


# ── FFmpeg Filter Expression Generators ───────────────────────────────────────

def generate_crop_filter_expression(
    keyframes: list[CropKeyframe],
    crop_w: int,
    crop_h: int,
    src_w: int,
    max_segments: int = 22,
) -> str:
    """
    Generate an FFmpeg crop filter string.
    - If static: 'crop=w:h:x:y'
    - If dynamic: generates a simplified piecewise-linear expression bounded
      to <= max_segments nested `if(lt(t,...))` terms so FFmpeg's expression
      parser never hits its recursion depth limit.
    """
    if not keyframes:
        return f"crop={crop_w}:{crop_h}:{(src_w - crop_w)//2}:0"

    x_values = [kf.x for kf in keyframes]
    # If all keyframes are within 2 pixels, treat as static
    if max(x_values) - min(x_values) <= 2:
        return f"crop={crop_w}:{crop_h}:{x_values[0]}:0"

    # 1. Remove redundant intermediate stationary points
    reduced: list[CropKeyframe] = [keyframes[0]]
    for i in range(1, len(keyframes) - 1):
        prev_kf = reduced[-1]
        curr_kf = keyframes[i]
        next_kf = keyframes[i + 1]
        if abs(curr_kf.x - prev_kf.x) <= 2 and abs(next_kf.x - curr_kf.x) <= 2:
            continue
        reduced.append(curr_kf)
    reduced.append(keyframes[-1])

    # 2. Cap total segments to max_segments to stay well below FFmpeg eval recursion limit
    if len(reduced) > max_segments:
        indices = [
            int(round(idx * (len(reduced) - 1) / (max_segments - 1)))
            for idx in range(max_segments)
        ]
        # Deduplicate while preserving order
        seen: set[int] = set()
        reduced = [reduced[idx] for idx in indices if not (idx in seen or seen.add(idx))]

    max_x = max(0, src_w - crop_w)
    expr = str(reduced[-1].x)

    for i in range(len(reduced) - 2, -1, -1):
        kf0 = reduced[i]
        kf1 = reduced[i + 1]
        dt = max(kf1.time - kf0.time, 1e-3)
        dx = kf1.x - kf0.x

        if abs(dx) < 1:
            segment = f"{kf0.x}"
        else:
            segment = f"({kf0.x}+({dx})*(t-{kf0.time:.2f})/{dt:.2f})"

        expr = f"if(lt(t,{kf1.time:.2f}),{segment},{expr})"

    # Bound within [0, max_x]
    full_expr = f"clip({expr},0,{max_x})"
    return f"crop={crop_w}:{crop_h}:x='{full_expr}':y=0"


def generate_sendcmd_crop_script(
    keyframes: list[CropKeyframe],
    out_path: Path,
    crop_w: int,
    crop_h: int,
    src_w: int,
) -> tuple[Path, str]:
    """
    Generate an FFmpeg `sendcmd` command script updating crop@reframe x/y at runtime.
    Removes the 22-segment nested `if(lt(t,...))` expression parser limit in FFmpeg.
    Returns (cmd_file_path, filtergraph_string).
    """
    out_path.parent.mkdir(parents=True, exist_ok=True)
    max_x = max(0, src_w - crop_w)
    lines: list[str] = []
    if not keyframes:
        cx = max(0, (src_w - crop_w) // 2)
        lines.append(f"0.000 [enter] crop@reframe x {cx}, crop@reframe y 0;")
    else:
        for kf in keyframes:
            clamped_x = max(0, min(max_x, int(kf.x)))
            clamped_y = max(0, int(kf.y))
            lines.append(
                f"{max(0.0, kf.time):.3f} [enter] crop@reframe x {clamped_x}, crop@reframe y {clamped_y};"
            )
    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    init_x = max(0, min(max_x, int(keyframes[0].x))) if keyframes else max(0, (src_w - crop_w) // 2)
    init_y = max(0, int(keyframes[0].y)) if keyframes else 0
    escaped_cmd = str(out_path).replace("\\", "\\\\").replace(":", "\\:").replace("'", "\\'")
    filter_str = f"sendcmd=f='{escaped_cmd}',crop@reframe={crop_w}:{crop_h}:{init_x}:{init_y}"
    return out_path, filter_str


def _escape_ass_path(ass_path: Path | str) -> str:
    raw = str(ass_path)
    return (
        raw.replace("\\", "\\\\")
        .replace(":", "\\:")
        .replace("'", "\\'")
    )


def build_blur_bg_filter_complex(
    out_w: int = OUTPUT_WIDTH,
    out_h: int = OUTPUT_HEIGHT,
    ass_path: Optional[Path | str] = None,
) -> str:
    """
    Build the FFmpeg -filter_complex graph for the blur-background layout.
    Canvas: 1080×1920 (9:16).
    Background: blurred and slightly darkened full bleed.
    Foreground: centered, letterboxed original video with sharp details.
    """
    ass_filter = f",ass='{_escape_ass_path(ass_path)}'" if ass_path else ""
    return (
        f"[0:v]split=2[bg_in][fg_in];"
        f"[bg_in]scale={out_w}:{out_h}:force_original_aspect_ratio=increase,"
        f"crop={out_w}:{out_h},boxblur=25:5,eq=brightness=-0.12[bg];"
        f"[fg_in]scale={out_w}:-2[fg];"
        f"[bg][fg]overlay=(W-w)/2:(H-h)/2[merged]"
        + (f";[merged]{ass_filter.lstrip(',')}[out]" if ass_path else ";[merged]copy[out]")
    )


def build_split_screen_filter_complex(
    out_w: int = OUTPUT_WIDTH,
    out_h: int = OUTPUT_HEIGHT,
    ass_path: Optional[Path | str] = None,
    top_speaker_x_ratio: float = 0.25,
    bottom_speaker_x_ratio: float = 0.75,
) -> str:
    """
    Build the FFmpeg -filter_complex graph for 50/50 vertical two-speaker split-screen layout.
    Canvas: 1080×1920 (9:16).
    Top pane: 1080×960 focused on Speaker A (left/top_speaker_x_ratio).
    Bottom pane: 1080×960 focused on Speaker B (right/bottom_speaker_x_ratio).
    Optionally burned with word-highlight captions.
    """
    half_h = out_h // 2
    top_r = max(0.0, min(1.0, float(top_speaker_x_ratio)))
    bot_r = max(0.0, min(1.0, float(bottom_speaker_x_ratio)))
    ass_filter = f",ass='{_escape_ass_path(ass_path)}'" if ass_path else ""
    return (
        f"[0:v]split=2[top_in][bot_in];"
        f"[top_in]scale={out_w}:{half_h}:force_original_aspect_ratio=increase,"
        f"crop={out_w}:{half_h}:x='clip((in_w-{out_w})*{top_r:.2f},0,in_w-{out_w})':y='(in_h-{half_h})/2'[top];"
        f"[bot_in]scale={out_w}:{half_h}:force_original_aspect_ratio=increase,"
        f"crop={out_w}:{half_h}:x='clip((in_w-{out_w})*{bot_r:.2f},0,in_w-{out_w})':y='(in_h-{half_h})/2'[bot];"
        f"[top][bot]vstack=inputs=2[stacked]"
        + (f";[stacked]{ass_filter.lstrip(',')}[out]" if ass_path else ";[stacked]copy[out]")
    )



# ── Core Pipeline Function ────────────────────────────────────────────────────

def compute_reframe(
    clip: Clip,
    source_video: Path,
    work_dir: Path,
    src_w: int,
    src_h: int,
    fps: float,
    layout: str = REFRAME_DEFAULT_LAYOUT,
    detector: Optional[FaceDetectorEngine] = None,
) -> ReframeResult:
    """
    Stage 5 Main Pipeline:
      1. Scene boundary detection (PySceneDetect)
      2. Frame sampling & face detection
      3. Motion path smoothing with scene cut snapping
      4. Dynamic crop filter expression generation
    """
    center_x, center_y, crop_w, crop_h = _compute_center_crop(src_w, src_h)

    # If layout is blur_bg or split_screen, special filter graph handles framing
    if layout in ("blur_bg", "split_screen"):
        keyframes = [CropKeyframe(frame=0, time=0.0, x=0, y=0, w=src_w, h=src_h)]
        return ReframeResult(
            clip=clip,
            video_path=source_video,
            keyframes=keyframes,
            crop_w=src_w,
            crop_h=src_h,
            layout=layout,
            out_width=OUTPUT_WIDTH,
            out_height=OUTPUT_HEIGHT,
            face_in_frame_ratio=1.0,
            crop_filter_expr="",
        )

    # Detect scene boundaries
    scenes = detect_scenes(source_video, start_sec=clip.start, end_sec=clip.end)
    logger.debug("[Stage 5] Clip {:.1f}s–{:.1f}s: {} scenes detected", clip.start, clip.end, len(scenes))

    # Initialize face detector
    engine = detector or FaceDetectorEngine()
    duration = max(clip.end - clip.start, 0.5)
    sample_interval = 1.0 / REFRAME_SAMPLE_FPS
    sample_times = np.arange(0.0, duration, sample_interval).tolist()

    raw_positions = []
    faces_detected_count = 0
    if cv2 is None:
        logger.warning("[Stage 5] OpenCV unavailable; using center-crop fallback")
        kf = CropKeyframe(frame=0, time=0.0, x=center_x, y=0, w=crop_w, h=crop_h)
        expr = f"crop={crop_w}:{crop_h}:{center_x}:0"
        return ReframeResult(
            clip=clip,
            video_path=source_video,
            keyframes=[kf],
            crop_w=crop_w,
            crop_h=crop_h,
            layout="vertical",
            face_in_frame_ratio=1.0,
            crop_filter_expr=expr,
        )

    cap = cv2.VideoCapture(str(source_video))
    prev_face: Optional[dict[str, Any]] = None
    prev_face_cx: Optional[float] = None
    last_switch_time = -10.0
    face_centers_per_frame: list[Optional[float]] = []

    try:
        for t_rel in sample_times:
            abs_time = clip.start + t_rel
            frame_num = int(round(t_rel * fps))
            cap.set(cv2.CAP_PROP_POS_MSEC, abs_time * 1000.0)
            ret, frame = cap.read()

            if not ret or frame is None:
                target_x = center_x
                face_centers_per_frame.append(None)
            else:
                faces = engine.detect(frame)
                primary, last_switch_time = select_active_speaker_face(
                    faces=faces,
                    current_time=t_rel,
                    prev_face=prev_face,
                    last_switch_time=last_switch_time,
                    hysteresis_sec=1.5,
                    src_w=src_w,
                )
                if primary:
                    faces_detected_count += 1
                    prev_face = primary
                    prev_face_cx = primary["center_x"]
                    face_centers_per_frame.append(primary["center_x"])
                    # Center the crop window around primary face
                    ideal_x = int(round(primary["center_x"] - (crop_w / 2.0)))
                    target_x = max(0, min(src_w - crop_w, ideal_x))
                else:
                    face_centers_per_frame.append(None)
                    # Fallback to last known position or center
                    target_x = int(round(prev_face_cx - (crop_w / 2.0))) if prev_face_cx else center_x

            raw_positions.append({
                "time": t_rel,
                "frame": frame_num,
                "target_x": target_x,
                "crop_h": crop_h,
            })
    finally:
        cap.release()
        if not detector:
            engine.close()

    # Smooth the trajectory
    smoothed_keyframes = smooth_crop_trajectory(
        raw_positions=raw_positions,
        scenes=[(s - clip.start, e - clip.start) for (s, e) in scenes],
        src_w=src_w,
        crop_w=crop_w,
    )

    face_ratio = compute_face_in_frame_ratio(
        face_centers_per_frame=face_centers_per_frame,
        keyframes=smoothed_keyframes,
        crop_w=crop_w,
    )


    crop_expr = generate_crop_filter_expression(smoothed_keyframes, crop_w, crop_h, src_w)
    logger.info(
        "[Stage 5] Clip {:.1f}s–{:.1f}s: face-in-frame {:.1f}%, {} keyframes generated",
        clip.start, clip.end, face_ratio * 100, len(smoothed_keyframes),
    )

    return ReframeResult(
        clip=clip,
        video_path=source_video,
        keyframes=smoothed_keyframes,
        crop_w=crop_w,
        crop_h=crop_h,
        layout=layout,
        out_width=OUTPUT_WIDTH,
        out_height=OUTPUT_HEIGHT,
        face_in_frame_ratio=face_ratio,
        crop_filter_expr=crop_expr,
    )


def reframe_all_clips(
    clips: list[Clip],
    source_video: Path,
    work_dir: Path,
    src_w: int = 1920,
    src_h: int = 1080,
    fps: float = 30.0,
    layout: str = REFRAME_DEFAULT_LAYOUT,
) -> list[ReframeResult]:
    """
    Compute smart reframe trajectories for all clips in a project.
    Writes keyframes JSON file and returns ReframeResult list.
    """
    detector = FaceDetectorEngine()
    results = []

    try:
        for clip in clips:
            result = compute_reframe(
                clip=clip,
                source_video=source_video,
                work_dir=work_dir,
                src_w=src_w,
                src_h=src_h,
                fps=fps,
                layout=layout,
                detector=detector,
            )
            results.append(result)
    finally:
        detector.close()

    # Save keyframes JSON
    keyframes_path = work_dir / "clips" / "reframe_keyframes.json"
    keyframes_path.parent.mkdir(parents=True, exist_ok=True)
    keyframes_data = [r.to_dict() for r in results]
    keyframes_path.write_text(json.dumps(keyframes_data, indent=2))

    logger.success("[Stage 5] ✓ Smart reframing computed for {} clips", len(results))
    return results
