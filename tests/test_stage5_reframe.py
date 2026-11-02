"""
Test Suite — Stage 5: Smart Vertical Reframing (Phase 2: v1.0.0-beta)
Tests:
  - 9:16 crop geometry & even-integer boundaries
  - EMA smoothing
  - Face detection engine (MediaPipe / Haar cascade fallback)
  - Primary face selection with continuity & centering bias
  - Scene boundary cut detection (PySceneDetect)
  - Crop trajectory smoothing (deadband, max pan speed, scene cut snapping)
  - Dynamic FFmpeg crop expression generation
  - Blurred background layout filter graph generation
  - ReframeResult data serialization (to_dict / from_dict)
  - End-to-end reframe execution on sample video
"""
from __future__ import annotations

import json
from pathlib import Path

import cv2
import numpy as np
import pytest

from workers.reframe import (
    CropKeyframe,
    FaceDetectorEngine,
    ReframeResult,
    _compute_center_crop,
    _ema_smooth,
    build_blur_bg_filter_complex,
    build_split_screen_filter_complex,
    compute_reframe,
    detect_scenes,
    generate_crop_filter_expression,
    reframe_all_clips,
    select_primary_face,
    smooth_crop_trajectory,
)
from workers.select_clips import Clip, ScoreBreakdown


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_clip(start=0.0, end=30.0) -> Clip:
    return Clip(
        start=start,
        end=end,
        hook="Smart reframing hook",
        title="Smart Reframe Clip",
        score=85,
        score_breakdown=ScoreBreakdown(hook=8, flow=8, value=9, trend=9),
        reason="test clip",
    )


# ── 1. Crop Geometry ──────────────────────────────────────────────────────────

class TestCenterCrop:
    def test_1080p_landscape(self):
        x, y, w, h = _compute_center_crop(1920, 1080)
        assert w == 606  # even integer close to 607.5
        assert h == 1080
        assert x == 656  # even integer for codec compatibility
        assert y == 0
        assert w % 2 == 0
        assert x % 2 == 0


    def test_720p_landscape(self):
        x, y, w, h = _compute_center_crop(1280, 720)
        assert w % 2 == 0
        assert x % 2 == 0
        ratio = w / h
        assert abs(ratio - 9 / 16) < 0.02

    def test_portrait_already(self):
        x, y, w, h = _compute_center_crop(1080, 1920)
        assert w <= 1080
        assert x >= 0

    def test_even_dimensions_for_codecs(self):
        for src_w in [1920, 1280, 1366, 640]:
            x, y, w, h = _compute_center_crop(src_w, 720)
            assert w % 2 == 0
            assert x % 2 == 0


# ── 2. EMA Smoothing ──────────────────────────────────────────────────────────

class TestEmaSmooth:
    def test_single_value(self):
        assert _ema_smooth([50.0]) == [50.0]

    def test_constant_sequence(self):
        vals = [100.0] * 5
        res = _ema_smooth(vals)
        for v in res:
            assert abs(v - 100.0) < 1e-4

    def test_step_response_is_smooth(self):
        vals = [0.0, 100.0, 100.0, 100.0]
        res = _ema_smooth(vals, alpha=0.5)
        assert res[0] == 0.0
        assert 0.0 < res[1] < 100.0
        assert res[2] > res[1]


# ── 3. Face Detection & Primary Speaker Selection ─────────────────────────────

class TestFaceDetection:
    def test_detector_initialization(self):
        detector = FaceDetectorEngine()
        assert detector._mp_detector is not None or detector._haar_classifier is not None
        detector.close()

    def test_black_frame_yields_no_faces(self):
        detector = FaceDetectorEngine()
        black_frame = np.zeros((720, 1280, 3), dtype=np.uint8)
        faces = detector.detect(black_frame)
        assert len(faces) == 0
        detector.close()

    def test_select_primary_face_single(self):
        face = {"x": 100, "y": 100, "w": 200, "h": 200, "center_x": 200, "center_y": 200}
        selected = select_primary_face([face])
        assert selected == face

    def test_select_primary_face_chooses_largest_and_centered(self):
        small_face = {"x": 10, "y": 10, "w": 50, "h": 50, "center_x": 35, "center_y": 35}
        large_face = {"x": 800, "y": 300, "w": 300, "h": 300, "center_x": 950, "center_y": 450}
        selected = select_primary_face([small_face, large_face], src_w=1920)
        assert selected == large_face

    def test_select_primary_face_continuity_bias(self):
        """Face closer to previously tracked speaker is favored over distant face of similar size."""
        face_left = {"x": 200, "y": 200, "w": 200, "h": 200, "center_x": 300, "center_y": 300}
        face_right = {"x": 1400, "y": 200, "w": 210, "h": 210, "center_x": 1500, "center_y": 300}
        # Tracking speaker on left
        selected = select_primary_face([face_left, face_right], prev_center_x=310, src_w=1920)
        assert selected == face_left


# ── 4. Scene Boundary Detection ───────────────────────────────────────────────

class TestSceneDetection:
    def test_detect_scenes_returns_valid_intervals(self, sample_video_path):
        scenes = detect_scenes(sample_video_path, start_sec=0.0, end_sec=5.0)
        assert len(scenes) >= 1
        s_start, s_end = scenes[0]
        assert s_start >= 0.0
        assert s_end <= 5.0

    def test_scene_cut_window_clamped_to_clip_bounds(self, sample_video_path):
        scenes = detect_scenes(sample_video_path, start_sec=2.0, end_sec=4.0)
        for s_start, s_end in scenes:
            assert s_start >= 2.0
            assert s_end <= 4.0


# ── 5. Motion Smoothing, Deadband & Pan Speed Limiting ─────────────────────────

class TestCropTrajectory:
    def test_deadband_suppresses_minor_jitter(self):
        """Movements smaller than 4% of frame width should not move the camera."""
        src_w = 1920
        crop_w = 606
        initial_x = 656  # center
        # Tiny movement of 20px (< 4% of 1920 = 76.8px)
        raw = [
            {"frame": 0, "time": 0.0, "target_x": initial_x, "crop_h": 1080},
            {"frame": 15, "time": 0.5, "target_x": initial_x + 20, "crop_h": 1080},
        ]
        smoothed = smooth_crop_trajectory(raw, [(0.0, 1.0)], src_w, crop_w)
        assert len(smoothed) == 2
        # Camera stays anchored at initial position
        assert smoothed[1].x == smoothed[0].x

    def test_max_pan_speed_limits_sudden_jumps(self):
        """A sudden jump of 800px should be capped by max pan speed (15%/sec)."""
        src_w = 1920
        crop_w = 606
        dt = 0.5
        max_allowed_delta = 0.15 * src_w * dt  # 144px
        raw = [
            {"frame": 0, "time": 0.0, "target_x": 100, "crop_h": 1080},
            {"frame": 15, "time": dt, "target_x": 900, "crop_h": 1080},
        ]
        smoothed = smooth_crop_trajectory(raw, [(0.0, 1.0)], src_w, crop_w, max_pan_speed=0.15)
        delta = abs(smoothed[1].x - smoothed[0].x)
        assert delta <= max_allowed_delta + 2  # within rounding tolerance

    def test_scene_cut_snaps_instantly_without_panning(self):
        """Across a scene boundary, the camera snaps immediately without panning."""
        src_w = 1920
        crop_w = 606
        raw = [
            {"frame": 0, "time": 0.0, "target_x": 100, "crop_h": 1080},
            {"frame": 30, "time": 1.0, "target_x": 100, "crop_h": 1080},
            # Cut at 1.0s: scene 2 starts at time 1.01s with target at 1000px
            {"frame": 31, "time": 1.01, "target_x": 1000, "crop_h": 1080},
        ]
        scenes = [(0.0, 1.0), (1.0, 2.0)]
        smoothed = smooth_crop_trajectory(raw, scenes, src_w, crop_w)
        # In scene 2, camera immediately snaps to 1000px (instead of slowly panning)
        assert smoothed[2].x == 1000

    def test_boundary_clamping(self):
        """Crop window left edge never goes below 0 or beyond (src_w - crop_w)."""
        src_w = 1920
        crop_w = 606
        max_x = src_w - crop_w
        raw = [
            {"frame": 0, "time": 0.0, "target_x": -500, "crop_h": 1080},
            {"frame": 15, "time": 0.5, "target_x": 5000, "crop_h": 1080},
        ]
        smoothed = smooth_crop_trajectory(raw, [(0.0, 1.0)], src_w, crop_w)
        assert smoothed[0].x >= 0
        assert smoothed[1].x <= max_x


# ── 6. FFmpeg Expression & Filter Generation ──────────────────────────────────

class TestFilterExpressions:
    def test_static_crop_filter_when_stationary(self):
        keyframes = [
            CropKeyframe(frame=0, time=0.0, x=656, y=0, w=606, h=1080),
            CropKeyframe(frame=15, time=0.5, x=656, y=0, w=606, h=1080),
        ]
        expr = generate_crop_filter_expression(keyframes, 606, 1080, 1920)
        assert expr == "crop=606:1080:656:0"

    def test_dynamic_crop_filter_when_moving(self):
        keyframes = [
            CropKeyframe(frame=0, time=0.0, x=300, y=0, w=606, h=1080),
            CropKeyframe(frame=30, time=1.0, x=500, y=0, w=606, h=1080),
        ]
        expr = generate_crop_filter_expression(keyframes, 606, 1080, 1920)
        assert "crop=606:1080:x='clip(" in expr
        assert "if(lt(t,1.00)" in expr

    def test_blur_bg_filter_complex_generation(self):
        fc = build_blur_bg_filter_complex(1080, 1920, ass_path="/tmp/sub.ass")
        assert "split=2" in fc
        assert "boxblur=25:5" in fc
        assert "overlay=(W-w)/2:(H-h)/2" in fc
        assert "ass='/tmp/sub.ass'" in fc


# ── 7. ReframeResult Serialization & End-to-End Execution ─────────────────────

class TestReframeIntegration:
    def test_reframe_result_roundtrip_dict(self):
        clip = _make_clip(0, 10)
        kf = [CropKeyframe(frame=0, time=0.0, x=656, y=0, w=606, h=1080)]
        res = ReframeResult(
            clip=clip,
            video_path=Path("/tmp/vid.mp4"),
            keyframes=kf,
            crop_w=606,
            crop_h=1080,
            layout="vertical",
            face_in_frame_ratio=0.98,
            crop_filter_expr="crop=606:1080:656:0",
        )
        d = res.to_dict()
        assert d["crop_w"] == 606
        assert d["face_in_frame_ratio"] == 0.98
        assert len(d["keyframes"]) == 1

        loaded = ReframeResult.from_dict(d, clip=clip)
        assert loaded.crop_w == res.crop_w
        assert loaded.keyframes[0].x == 656

    def test_compute_reframe_vertical_mode(self, sample_video_path, tmp_path):
        clip = _make_clip(0.0, 5.0)
        res = compute_reframe(
            clip=clip,
            source_video=sample_video_path,
            work_dir=tmp_path,
            src_w=1280,
            src_h=720,
            fps=25.0,
            layout="vertical",
        )
        assert isinstance(res, ReframeResult)
        assert len(res.keyframes) >= 1
        assert res.crop_w % 2 == 0
        assert res.crop_filter_expr != ""

    def test_compute_reframe_blur_bg_mode(self, sample_video_path, tmp_path):
        clip = _make_clip(0.0, 5.0)
        res = compute_reframe(
            clip=clip,
            source_video=sample_video_path,
            work_dir=tmp_path,
            src_w=1280,
            src_h=720,
            fps=25.0,
            layout="blur_bg",
        )
        assert res.layout == "blur_bg"
        assert res.crop_w == 1280
        assert res.crop_h == 720

    def test_split_screen_filter_complex_generation(self):
        fc = build_split_screen_filter_complex(1080, 1920)
        assert "vstack" in fc
        assert "scale=1080:960" in fc
        assert "[out]" in fc

    def test_compute_reframe_split_screen(self, sample_video_path, tmp_path):
        clip = _make_clip(0.0, 3.0)
        res = compute_reframe(
            clip=clip,
            source_video=sample_video_path,
            work_dir=tmp_path,
            src_w=1280,
            src_h=720,
            fps=25.0,
            layout="split_screen",
        )
        assert res.layout == "split_screen"
        assert res.crop_w == 1280
        assert res.crop_h == 720

    def test_reframe_all_clips_exports_keyframes_json(self, sample_video_path, tmp_path):
        clips = [_make_clip(0.0, 3.0), _make_clip(3.0, 6.0)]
        results = reframe_all_clips(
            clips=clips,
            source_video=sample_video_path,
            work_dir=tmp_path,
            src_w=1280,
            src_h=720,
            fps=25.0,
        )
        assert len(results) == 2
        kf_path = tmp_path / "clips" / "reframe_keyframes.json"
        assert kf_path.exists()
        saved = json.loads(kf_path.read_text())
        assert len(saved) == 2
        assert "keyframes" in saved[0]
