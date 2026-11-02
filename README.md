# video2reels

> **AI Short-Form Video Clipper** — an OpusClip-style tool that turns long-form videos into vertical short-form clips.

## What it does

1. **Input:** Paste a YouTube URL or upload a video file (MP4, MOV, MKV, WebM)
2. **Transcribe:** Speech-to-text with word-level timestamps (faster-whisper)
3. **Select:** LLM picks the 5-15 most engaging, self-contained moments with virality scores
4. **Reframe:** Auto-crop to 9:16 with face/speaker tracking
5. **Caption:** Animated word-highlight captions burned in
6. **Export:** 1080×1920 H.264 MP4, loudness-normalized audio

## Quick Start (Phase 0 — CLI)

```bash
# Clone the repo
git clone <repo-url>
cd video2reels

# Set up environment
python -m venv .venv
source .venv/bin/activate
pip install -r requirements-prototype.txt

# Copy and fill in env vars
cp .env.example .env

# Run prototype on a local file
python scripts/prototype.py --input myvideo.mp4 --output ./output/

# Or on a URL (ensure you own the content)
python scripts/prototype.py --url "https://..." --output ./output/
```

## Documentation

- [BUILD_ARCHITECTURE.md](./BUILD_ARCHITECTURE.md) — Full system architecture, version roadmap, and feature docs
- [CHANGELOG.md](./CHANGELOG.md) — Version history

## Version Roadmap

| Version | Phase | Description |
|---|---|---|
| `v0.1.0` | Prototype | CLI script end-to-end |
| `v1.0.0` | MVP | Web UI, pipeline, face tracking |
| `v2.0.0` | Full | Brand kits, diarization, publishing |

## Tech Stack

- **Backend:** FastAPI + Python 3.11
- **Queue:** Redis + Celery
- **DB:** PostgreSQL 15
- **Storage:** MinIO / Cloudflare R2
- **Transcription:** faster-whisper (local GPU)
- **LLM:** Google Gemini / Claude API
- **Face Tracking:** MediaPipe + YOLOv8-face
- **Rendering:** FFmpeg + NVENC

## License

Personal use. See [legal considerations](./BUILD_ARCHITECTURE.md#risks--mitigations) re: yt-dlp and third-party content.
