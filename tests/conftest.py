"""
Pytest configuration and shared fixtures for video2reels prototype tests.
"""
import sys
import json
import subprocess
import tempfile
from pathlib import Path

import pytest

# Make workers importable
sys.path.insert(0, str(Path(__file__).parent.parent))

# ── Paths ─────────────────────────────────────────────────────────────────────
FIXTURES_DIR = Path(__file__).parent / "fixtures"
FIXTURES_DIR.mkdir(exist_ok=True)

SAMPLE_VIDEO = FIXTURES_DIR / "sample_short.mp4"
WORK_DIR = FIXTURES_DIR / "work"
WORK_DIR.mkdir(exist_ok=True)


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(scope="session")
def sample_video_path():
    """
    Creates a tiny synthetic test video (10s, 1280x720, with audio tone)
    using FFmpeg if it doesn't already exist.
    Requires FFmpeg to be available.
    """
    if SAMPLE_VIDEO.exists():
        return SAMPLE_VIDEO

    # Find ffmpeg
    import shutil, os
    ffmpeg = None
    # Check static binary first
    static = Path(__file__).parent.parent / "bin" / "ffmpeg"
    if static.exists():
        ffmpeg = str(static)
    else:
        ffmpeg = shutil.which("ffmpeg")

    if not ffmpeg:
        pytest.skip("FFmpeg not available — cannot create test video")

    # Generate: 1280x720, 25fps, 30 seconds, with 440Hz sine audio
    cmd = [
        ffmpeg, "-y",
        "-f", "lavfi",
        "-i", "testsrc=duration=30:size=1280x720:rate=25",
        "-f", "lavfi",
        "-i", "sine=frequency=440:duration=30",
        "-c:v", "libx264", "-preset", "ultrafast", "-crf", "30",
        "-c:a", "aac", "-b:a", "64k",
        "-shortest",
        str(SAMPLE_VIDEO),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        pytest.skip(f"Could not create test video: {result.stderr[:200]}")

    return SAMPLE_VIDEO


@pytest.fixture(scope="session")
def work_dir():
    return WORK_DIR


@pytest.fixture(scope="session")
def sample_transcript():
    """Minimal synthetic transcript for testing clip selection & captions."""
    from workers.transcribe import Transcript, Segment, Word
    words_data = [
        ("The", 0.0, 0.2), ("biggest", 0.2, 0.5), ("mistake", 0.5, 0.9),
        ("founders", 0.9, 1.3), ("make", 1.3, 1.6), ("is", 1.6, 1.8),
        ("thinking", 1.8, 2.2), ("they", 2.2, 2.4), ("need", 2.4, 2.7),
        ("to", 2.7, 2.9), ("be", 2.9, 3.1), ("perfect", 3.1, 3.6),
        ("before", 3.6, 4.0), ("launching.", 4.0, 4.8),

        ("I", 5.0, 5.1), ("shipped", 5.1, 5.5), ("our", 5.5, 5.7),
        ("first", 5.7, 6.0), ("product", 6.0, 6.4), ("with", 6.4, 6.6),
        ("twenty", 6.6, 7.0), ("bugs", 7.0, 7.3), ("and", 7.3, 7.5),
        ("made", 7.5, 7.7), ("ten", 7.7, 8.0), ("thousand", 8.0, 8.5),
        ("dollars", 8.5, 9.0), ("in", 9.0, 9.2), ("month", 9.2, 9.6), ("one.", 9.6, 10.2),

        ("Done", 11.0, 11.4), ("is", 11.4, 11.6), ("better", 11.6, 12.0),
        ("than", 12.0, 12.3), ("perfect.", 12.3, 12.9),
    ]

    words = [Word(text=w, start=s, end=e, probability=0.98) for w, s, e in words_data]
    seg1 = Segment(start=0.0, end=4.8, text="The biggest mistake founders make is thinking they need to be perfect before launching.", words=words[:14])
    seg2 = Segment(start=5.0, end=10.2, text="I shipped our first product with twenty bugs and made ten thousand dollars in month one.", words=words[14:30])
    seg3 = Segment(start=11.0, end=12.9, text="Done is better than perfect.", words=words[30:])

    return Transcript(language="en", language_probability=0.99, duration=13.0, segments=[seg1, seg2, seg3])
