"""
Test Suite — Stage 4: Clip Selection (LLM)
Tests: transcript formatting, word-boundary snapping, JSON extraction,
       overlap removal, duration filtering, and cache loading.
The live LLM call is mocked so no API key is required.
"""
import json
import pytest
from unittest.mock import patch, MagicMock
from pathlib import Path

from workers.select_clips import (
    Clip, ScoreBreakdown,
    _format_transcript_for_llm,
    _snap_to_word_boundary,
    _extract_json,
    _remove_overlapping,
    select_clips,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_clip(start, end, score=75):
    return Clip(
        start=start, end=end,
        hook="Test hook", title="Test title",
        score=score,
        score_breakdown=ScoreBreakdown(hook=8, flow=7, value=8, trend=7),
        reason="Test reason",
    )


# ── Transcript formatting ─────────────────────────────────────────────────────

class TestFormatTranscript:
    def test_numbered_lines(self, sample_transcript):
        text = _format_transcript_for_llm(sample_transcript)
        assert "[0001]" in text
        assert "[0002]" in text

    def test_timestamps_present(self, sample_transcript):
        text = _format_transcript_for_llm(sample_transcript)
        assert "0.00s" in text

    def test_truncation_at_max_chars(self, sample_transcript):
        text = _format_transcript_for_llm(sample_transcript, max_chars=50)
        assert len(text) <= 50


# ── Word-boundary snapping ────────────────────────────────────────────────────

class TestSnapToWordBoundary:
    def test_snaps_inside_word_list(self, sample_transcript):
        words = sample_transcript.all_words
        start, end = _snap_to_word_boundary(1.0, 5.0, words)
        assert start <= 1.0
        assert end >= 5.0

    def test_empty_word_list_returns_original(self):
        start, end = _snap_to_word_boundary(1.0, 5.0, [])
        assert start == 1.0
        assert end == 5.0

    def test_adds_padding(self, sample_transcript):
        words = sample_transcript.all_words
        # Nearest word start <= 1.0+0.5 will be found, then subtract pad=0.5
        # The result must be strictly less than 1.0 (padding was applied)
        start, end = _snap_to_word_boundary(1.0, 5.0, words, pad=0.5)
        assert start < 1.0, f"Start {start} should be less than 1.0 (padding applied)"
        assert end > 5.0,   f"End {end} should be greater than 5.0 (padding applied)"


# ── JSON extraction ───────────────────────────────────────────────────────────

class TestExtractJson:
    def test_plain_json(self):
        raw = '{"clips": [{"start": 1.0, "end": 30.0, "score": 80}]}'
        result = _extract_json(raw)
        assert result["clips"][0]["score"] == 80

    def test_markdown_fenced(self):
        raw = "```json\n{\"clips\": []}\n```"
        result = _extract_json(raw)
        assert "clips" in result

    def test_invalid_json_raises(self):
        with pytest.raises(ValueError):
            _extract_json("not json at all ##")


# ── Overlap removal ───────────────────────────────────────────────────────────

class TestRemoveOverlapping:
    def test_no_overlap_keeps_all(self):
        clips = [_make_clip(0, 30), _make_clip(35, 65), _make_clip(70, 100)]
        result = _remove_overlapping(clips)
        assert len(result) == 3

    def test_overlapping_keeps_higher_score(self):
        low  = _make_clip(0, 60, score=40)
        high = _make_clip(10, 70, score=90)   # overlaps with 'low'
        result = _remove_overlapping([low, high])
        assert len(result) == 1
        assert result[0].score == 90

    def test_identical_clips_deduplicated(self):
        clips = [_make_clip(0, 30, score=80), _make_clip(0, 30, score=70)]
        result = _remove_overlapping(clips)
        assert len(result) == 1


# ── ScoreBreakdown ────────────────────────────────────────────────────────────

class TestScoreBreakdown:
    def test_average(self):
        sb = ScoreBreakdown(hook=8, flow=6, value=7, trend=9)
        assert sb.average == pytest.approx(7.5)


# ── select_clips with mocked LLM ─────────────────────────────────────────────

class TestSelectClipsMocked:
    _LLM_RESPONSE = json.dumps({
        "clips": [
            {
                "start": 0.0, "end": 12.9,   # full fixture = 12.9s, within 5–90s range
                "hook": "The biggest mistake founders make",
                "title": "Ship Fast or Fail Slow",
                "score": 85,
                "score_breakdown": {"hook": 9, "flow": 8, "value": 8, "trend": 8},
                "reason": "Strong hook + concrete outcome.",
            }
        ]
    })

    @patch("workers.select_clips.CLIP_MIN_DURATION", 5)
    @patch("workers.select_clips._call_llm", return_value=_LLM_RESPONSE)
    def test_select_clips_returns_list(self, mock_llm, sample_transcript, tmp_path):
        clips = select_clips(sample_transcript, tmp_path)
        assert isinstance(clips, list)
        assert len(clips) >= 1

    @patch("workers.select_clips.CLIP_MIN_DURATION", 5)
    @patch("workers.select_clips._call_llm", return_value=_LLM_RESPONSE)
    def test_clips_have_required_fields(self, mock_llm, sample_transcript, tmp_path):
        clips = select_clips(sample_transcript, tmp_path)
        for clip in clips:
            assert clip.start < clip.end
            assert 0 <= clip.score <= 100
            assert isinstance(clip.hook, str)

    @patch("workers.select_clips.CLIP_MIN_DURATION", 5)
    @patch("workers.select_clips._call_llm", return_value=_LLM_RESPONSE)
    def test_clips_cached_to_disk(self, mock_llm, sample_transcript, tmp_path):
        select_clips(sample_transcript, tmp_path)
        cache = tmp_path / "clips" / "clips.json"
        assert cache.exists()
        data = json.loads(cache.read_text())
        assert len(data) >= 1

    @patch("workers.select_clips.CLIP_MIN_DURATION", 5)
    @patch("workers.select_clips._call_llm", return_value=_LLM_RESPONSE)
    def test_cache_loaded_on_second_call(self, mock_llm, sample_transcript, tmp_path):
        select_clips(sample_transcript, tmp_path)
        call_count_after_first = mock_llm.call_count

        # Second call — should use cache, NOT call LLM again
        select_clips(sample_transcript, tmp_path)
        assert mock_llm.call_count == call_count_after_first, (
            "LLM should not be called again on cache hit"
        )

    @patch("workers.select_clips._call_llm", return_value='{"clips": [{"start": 999.9, "end": 1030.0, "hook": "x", "title": "y", "score": 80, "score_breakdown": {"hook":8,"flow":8,"value":8,"trend":8}, "reason": "r"}]}')
    def test_hallucinated_timestamps_rejected(self, mock_llm, sample_transcript, tmp_path):
        """Timestamps that don't appear in the transcript should be skipped."""
        clips = select_clips(sample_transcript, tmp_path)
        assert len(clips) == 0, "Clips with timestamps not in transcript should be rejected"
