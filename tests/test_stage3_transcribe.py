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


class TestSpeakerDiarization:
    def test_diarize_segments_assigns_speakers_on_pause_and_question(self):
        from workers.transcribe import diarize_segments

        segs = [
            Segment(start=0.0, end=3.0, text="What is the biggest challenge in scaling?"),
            Segment(start=3.6, end=8.0, text="Hiring the right engineering team early on."),
            Segment(start=8.2, end=12.0, text="And keeping the product vision focused."),
            Segment(start=14.0, end=17.5, text="That makes total sense."),
        ]
        diarized = diarize_segments(segs, pause_threshold=1.2, max_speakers=2)
        assert diarized[0].speaker == "S1"
        # After question + 0.6s gap -> S2
        assert diarized[1].speaker == "S2"
        # Continuation with 0.2s gap -> stays S2
        assert diarized[2].speaker == "S2"
        # After 2.0s pause (>= 1.2s) -> switches back to S1
        assert diarized[3].speaker == "S1"

    def test_diarize_transcript_round_trip_preserves_speaker(self, sample_transcript):
        from workers.transcribe import diarize_transcript

        t = diarize_transcript(sample_transcript)
        for seg in t.segments:
            assert seg.speaker in ("S1", "S2")
        restored = Transcript.from_dict(t.to_dict())
        assert [s.speaker for s in restored.segments] == [s.speaker for s in t.segments]

