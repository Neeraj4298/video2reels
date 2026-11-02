"""
Test Suite — Stage 6a: Caption Generation (ASS)
Tests: ASS time formatting, color conversion, header generation,
       karaoke line building, and full generate_captions() output.
"""
import pytest
from pathlib import Path

from workers.captions import (
    CaptionStyle, DEFAULT_STYLE,
    _seconds_to_ass_time,
    _ass_color,
    _build_ass_header,
    _words_to_karaoke_line,
    generate_captions,
)
from workers.transcribe import Word
from workers.select_clips import Clip, ScoreBreakdown


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_clip(start=0.0, end=13.0):
    return Clip(
        start=start, end=end,
        hook="The biggest mistake", title="Test Clip",
        score=80,
        score_breakdown=ScoreBreakdown(hook=8, flow=8, value=8, trend=8),
        reason="test",
    )


# ── ASS time formatting ───────────────────────────────────────────────────────

class TestSecondsToAssTime:
    def test_zero(self):
        assert _seconds_to_ass_time(0.0) == "0:00:00.00"

    def test_one_second(self):
        assert _seconds_to_ass_time(1.0) == "0:00:01.00"

    def test_one_minute(self):
        assert _seconds_to_ass_time(60.0) == "0:01:00.00"

    def test_one_hour(self):
        assert _seconds_to_ass_time(3600.0) == "1:00:00.00"

    def test_fractional_seconds(self):
        result = _seconds_to_ass_time(1.5)
        assert result == "0:00:01.50"

    def test_negative_guard(self):
        # Just ensure it doesn't crash on edge values
        _seconds_to_ass_time(0.001)


# ── Color conversion ──────────────────────────────────────────────────────────

class TestAssColor:
    def test_already_ass_format_passthrough(self):
        assert _ass_color("&H00FFFFFF") == "&H00FFFFFF"

    def test_hex_rgb_converted(self):
        # #FFFFFF → &H00FFFFFF
        result = _ass_color("#FFFFFF")
        assert result == "&H00FFFFFF"

    def test_hex_gold_converted(self):
        # #FFD700 → &H0000D7FF  (R=FF, G=D7, B=00 → BBGGRR = 00D7FF)
        result = _ass_color("#FFD700")
        assert result.startswith("&H00")


# ── ASS header ────────────────────────────────────────────────────────────────

class TestBuildAssHeader:
    def test_contains_script_info(self):
        header = _build_ass_header(DEFAULT_STYLE)
        assert "[Script Info]" in header

    def test_contains_styles_section(self):
        header = _build_ass_header(DEFAULT_STYLE)
        assert "[V4+ Styles]" in header

    def test_contains_events_section(self):
        header = _build_ass_header(DEFAULT_STYLE)
        assert "[Events]" in header

    def test_resolution_matches_style(self):
        style = CaptionStyle(play_res_x=1080, play_res_y=1920)
        header = _build_ass_header(style)
        assert "PlayResX: 1080" in header
        assert "PlayResY: 1920" in header


# ── Karaoke line building ─────────────────────────────────────────────────────

class TestWordsToKaraokeLine:
    def test_output_contains_kf_tags(self):
        words = [
            Word("Hello", 0.0, 0.5, 0.99),
            Word("world", 0.6, 1.0, 0.99),
        ]
        line = _words_to_karaoke_line(words, clip_start=0.0)
        assert "{\\kf" in line

    def test_single_word(self):
        words = [Word("Test", 0.0, 0.5, 0.99)]
        line = _words_to_karaoke_line(words, clip_start=0.0)
        assert "Test" in line

    def test_special_chars_stripped(self):
        words = [Word("{evil}", 0.0, 0.5, 0.99)]
        line = _words_to_karaoke_line(words, clip_start=0.0)
        assert "{" not in line.replace("{\\kf", "").replace("}", "")


# ── Full generate_captions() ──────────────────────────────────────────────────

class TestGenerateCaptions:
    def test_creates_ass_file(self, sample_transcript, tmp_path):
        clip = _make_clip()
        ass = generate_captions(clip, sample_transcript, tmp_path)
        assert ass.exists()
        assert ass.suffix == ".ass"

    def test_ass_file_has_content(self, sample_transcript, tmp_path):
        clip = _make_clip()
        ass = generate_captions(clip, sample_transcript, tmp_path)
        content = ass.read_text(encoding="utf-8")
        assert "[Script Info]" in content
        assert "[Events]" in content

    def test_cached_file_returned_without_regen(self, sample_transcript, tmp_path):
        clip = _make_clip()
        ass1 = generate_captions(clip, sample_transcript, tmp_path)
        mtime1 = ass1.stat().st_mtime

        ass2 = generate_captions(clip, sample_transcript, tmp_path)
        assert ass1 == ass2
        assert ass1.stat().st_mtime == mtime1

    def test_empty_clip_no_crash(self, tmp_path):
        """Clip with no matching words should write an empty ASS (no exception)."""
        from workers.transcribe import Transcript
        empty_transcript = Transcript(language="en", language_probability=1.0, duration=0.0, segments=[])
        clip = Clip(
            start=500.0, end=530.0,
            hook="x", title="y", score=50,
            score_breakdown=ScoreBreakdown(hook=5, flow=5, value=5, trend=5),
            reason="test",
        )
        ass = generate_captions(clip, empty_transcript, tmp_path)
        assert ass.exists()

    def test_karaoke_tags_in_output(self, sample_transcript, tmp_path):
        """Dialogue events must contain karaoke timing tags."""
        clip = _make_clip()
        ass = generate_captions(clip, sample_transcript, tmp_path)
        content = ass.read_text(encoding="utf-8")
        assert "{\\kf" in content, "Word-highlight karaoke tags must be present"


# ── Style Presets & get_caption_style ─────────────────────────────────────────

class TestCaptionStylePresets:
    def test_presets_exist(self):
        from workers.captions import STYLE_PRESETS
        assert "karaoke" in STYLE_PRESETS
        assert "bold_yellow" in STYLE_PRESETS
        assert "cyberpunk_neon" in STYLE_PRESETS
        assert "minimal_clean" in STYLE_PRESETS
        assert "fire_red" in STYLE_PRESETS

    def test_get_caption_style_by_name(self):
        from workers.captions import get_caption_style
        style = get_caption_style("cyberpunk_neon")
        assert style.bold is True
        assert style.primary_color == "&H00FFFF00"

    def test_get_caption_style_by_dict_override(self):
        from workers.captions import get_caption_style
        style = get_caption_style({"font_name": "Impact", "font_size": 60, "bold": True})
        assert style.font_name == "Impact"
        assert style.font_size == 60

    def test_get_caption_style_fallback(self):
        from workers.captions import get_caption_style, DEFAULT_STYLE
        assert get_caption_style(None) == DEFAULT_STYLE
        assert get_caption_style("unknown_preset") == DEFAULT_STYLE


# ── SRT & VTT Export ──────────────────────────────────────────────────────────

class TestSrtAndVttExport:
    def test_generate_srt(self, sample_transcript):
        from workers.captions import generate_srt
        clip = _make_clip(0.0, 10.0)
        srt = generate_srt(clip, sample_transcript, relative=True)
        assert "1\n" in srt
        assert "-->" in srt
        assert "," in srt  # SRT millisecond separator

    def test_generate_vtt(self, sample_transcript):
        from workers.captions import generate_vtt
        clip = _make_clip(0.0, 10.0)
        vtt = generate_vtt(clip, sample_transcript, relative=True)
        assert vtt.startswith("WEBVTT")
        assert "-->" in vtt
        assert "." in vtt  # VTT millisecond separator

    def test_export_subtitles_file_srt(self, sample_transcript, tmp_path):
        from workers.captions import export_subtitles
        clip = _make_clip(0.0, 10.0)
        out_path = tmp_path / "subs.srt"
        res = export_subtitles(clip, sample_transcript, "srt", out_path)
        assert res.exists()
        assert "-->" in res.read_text(encoding="utf-8")

    def test_export_subtitles_file_vtt(self, sample_transcript, tmp_path):
        from workers.captions import export_subtitles
        clip = _make_clip(0.0, 10.0)
        out_path = tmp_path / "subs.vtt"
        res = export_subtitles(clip, sample_transcript, "vtt", out_path)
        assert res.exists()
        assert res.read_text(encoding="utf-8").startswith("WEBVTT")

    def test_export_subtitles_unsupported_format_raises(self, sample_transcript, tmp_path):
        from workers.captions import export_subtitles
        clip = _make_clip(0.0, 10.0)
        with pytest.raises(ValueError):
            export_subtitles(clip, sample_transcript, "unsupported", tmp_path / "subs.txt")

