"""
Test Suite — Stage 3: Transcription
Tests: Transcript data model, from_dict/to_dict round-trip, word queries.
Whisper inference is NOT run in unit tests (it would take too long).
The inference path is exercised via the integration test / prototype run.
"""
import json
import pytest
from pathlib import Path

from workers.transcribe import Transcript, Segment, Word, transcribe


class TestTranscriptModel:
    def test_full_text_joins_segments(self, sample_transcript):
        text = sample_transcript.full_text
        assert "mistake" in text
        assert "perfect" in text

    def test_all_words_flattens(self, sample_transcript):
        words = sample_transcript.all_words
        # conftest fixture has 14 + 16 + 5 = 35 words across 3 segments
        assert len(words) == 35, f"Expected 35 words, got {len(words)}"

    def test_to_dict_round_trip(self, sample_transcript):
        d = sample_transcript.to_dict()
        t2 = Transcript.from_dict(d)
        assert t2.language == sample_transcript.language
        assert len(t2.segments) == len(sample_transcript.segments)
        assert len(t2.all_words) == len(sample_transcript.all_words)

    def test_word_probabilities_preserved(self, sample_transcript):
        words = sample_transcript.all_words
        for w in words:
            assert 0.0 <= w.probability <= 1.0

    def test_segment_timestamps_ordered(self, sample_transcript):
        for seg in sample_transcript.segments:
            assert seg.start < seg.end

    def test_json_serialization_valid(self, sample_transcript):
        raw = json.dumps(sample_transcript.to_dict())
        data = json.loads(raw)
        assert "segments" in data
        assert "language" in data


class TestTranscribeCaching:
    def test_cached_transcript_loaded(self, sample_transcript, tmp_path):
        """If transcript.json already exists, transcribe() should load it."""
        transcript_dir = tmp_path / "transcripts"
        transcript_dir.mkdir()
        cache_path = transcript_dir / "transcript.json"
        cache_path.write_text(
            json.dumps(sample_transcript.to_dict()),
            encoding="utf-8",
        )

        # Provide a dummy audio path — should never be read because cache hit
        dummy_audio = tmp_path / "audio.wav"
        result = transcribe(dummy_audio, tmp_path)

        assert result.language == sample_transcript.language
        assert len(result.segments) == len(sample_transcript.segments)
