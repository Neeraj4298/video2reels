# Changelog

All notable changes to video2reels will be documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).
Versioning follows [Semantic Versioning](https://semver.org/).

---

## [Unreleased] — v0.1.0 (Phase 0: Prototype CLI)

### Added
- Phase 0 CLI prototype [`scripts/prototype.py`](file:///home/racharlaneeraj/Documents/neeraj/ai_projects/video2reels/scripts/prototype.py) running end-to-end 6-stage pipeline.
- Stage 1: Ingestion & FFprobe validation ([`workers/ingest.py`](file:///home/racharlaneeraj/Documents/neeraj/ai_projects/video2reels/workers/ingest.py)).
- Stage 2: Audio extraction to 16kHz mono WAV ([`workers/audio_extract.py`](file:///home/racharlaneeraj/Documents/neeraj/ai_projects/video2reels/workers/audio_extract.py)).
- Stage 3: Transcription with `faster-whisper` and word-level timestamps ([`workers/transcribe.py`](file:///home/racharlaneeraj/Documents/neeraj/ai_projects/video2reels/workers/transcribe.py)).
- Stage 4: AI clip selection and virality scoring using Google Gemini (`gemini-2.0-flash` via `google-genai` SDK) and Claude fallback ([`workers/select_clips.py`](file:///home/racharlaneeraj/Documents/neeraj/ai_projects/video2reels/workers/select_clips.py)).
- Stage 5: Center-crop 9:16 vertical reframing with EMA smoothing ([`workers/reframe.py`](file:///home/racharlaneeraj/Documents/neeraj/ai_projects/video2reels/workers/reframe.py)).
- Stage 6a: Word-level karaoke ASS caption generation with customizable styles ([`workers/captions.py`](file:///home/racharlaneeraj/Documents/neeraj/ai_projects/video2reels/workers/captions.py)).
- Stage 6b: FFmpeg 1080x1920 MP4 export with burned subtitles and loudness normalization ([`workers/render.py`](file:///home/racharlaneeraj/Documents/neeraj/ai_projects/video2reels/workers/render.py)).
- Complete test suite with 86 passing tests across all 6 stages.

---

## [v0.9.0] — Phase 1: Pipeline & Infrastructure

### Added
- **Infrastructure (`v0.2.0`)**: Docker Compose configuration running PostgreSQL 15, Redis 7, MinIO S3 object storage, FastAPI API server, Celery CPU and GPU workers, Flower dashboard, and Nginx reverse proxy.
- **Job Queue (`v0.3.0`)**: Celery distributed task pipeline across all 6 stages with explicit task routing into `cpu` (ingest, audio extraction, clip selection, captions) and `gpu` (transcription, reframing, rendering) queues.
- **Database & Storage (`v0.4.0`)**: SQLAlchemy async ORM models for all 7 entities (`projects`, `videos`, `transcripts`, `clips`, `render_settings`, `renders`, `jobs`, `brand_kits`) with UUID primary keys and JSONB metadata; initial Alembic migration (`001_initial_schema.py`); MinIO client integration with presigned upload/download URLs.
- **Stage Resumability (`v0.5.0`)**: Intelligent pipeline restart (`resume_pipeline`) that inspects DB and MinIO state to resume from the earliest uncompleted stage; all 6 stage tasks are strictly idempotent with cached-output detection and 3-attempt exponential backoff (60s -> 300s -> 900s).
- **REST API & SSE (`v0.6.0`)**: Full FastAPI REST API covering project lifecycle, direct browser uploads, clip editing/trimming/re-rendering, brand kits CRUD, and real-time Server-Sent Events (SSE) progress streaming via Redis pub/sub.
- **Integration Tests (`v0.9.0`)**: Comprehensive test suite expanded from 86 to 107 passing tests covering API endpoints, resumability logic, Celery task idempotence, SSE streaming, and schema migrations.

## [v1.0.0-beta] — Phase 2: Smart Reframing

### Added
- **Multi-Backend Face Detection**: Integrated MediaPipe BlazeFace (`blaze_face_short_range.tflite`) with automatic fallback to OpenCV Haar Cascade (`haarcascade_frontalface_default.xml`).
- **Primary Speaker Selection**: Face prioritization algorithm balancing bounding box area with distance to tracked speaker and centering bias.
- **Scene Cut Detection**: Integrated PySceneDetect (`ContentDetector`) to detect shot transitions and prevent nauseating pans across scene cuts.
- **Motion Smoothing & Pan Limiter**: Deadband jitter suppression (4% width), maximum pan velocity limit (15% width / sec), and EMA trajectory smoothing.
- **Scene Boundary Snapping**: Camera immediately snaps to new subject at scene cuts without interpolating across cuts.
- **Blur-Background Layout (`blur_bg`)**: Generates 9:16 portrait video with heavily blurred background and centered letterboxed 16:9 foreground.
- **Dynamic FFmpeg Expressions**: Evaluated per-frame piecewise interpolation for smooth horizontal camera panning during export.
- **Database & JSON Keyframe Storage**: Keyframes serialized into `render_settings.crop_keyframes` and `reframe_keyframes.json`.
- **Test Suite Expansion**: Test suite expanded from 107 to 117 passing tests covering all Smart Reframing components.

## [v1.0.0] — Phase 3: Web UI
- **Next.js 16 Web Dashboard**: Built responsive web client with rich dark-mode theme, glassmorphism cards, and Google Fonts typography.
- **Home / Project Creation**: Drag-and-drop file upload with presigned URLs or direct URL ingestion (`yt-dlp`).
- **Live Pipeline Monitor**: Real-time stage progress bar with Server-Sent Events (SSE) streaming, per-stage status indicators, and live retry controls.
- **Clip Review Grid**: Gallery view of generated vertical short clips with virality score rings, sort/filter options, and score breakdown stats.
- **Clip Detail & Player**: Built-in video player with signed download links, format preview, and metadata display.
- **Application Settings**: Persistent backend API URL configuration with live connectivity health check, layout defaults, and theme management.
- **Multi-Stage Docker Packaging**: Production Dockerfile and Compose integration for standalone Next.js deployment.

---

## [v1.1.0] — Phase 4: Editing, Custom Caption Styling, & Subtitles
- **Interactive Trim & Waveform**: Drag-and-drop / range slider trim handles with synthetic audio waveform visualization, playhead tracking, and quick nudge buttons (-1s, -0.1s, +0.1s, +1s).
- **Transcript Word Editor**: Word-by-word transcript synchronized with video playback (`/api/clips/{id}/transcript`); click any word to seek the video player to that exact moment; word strike-through/cut functionality to trim unwanted text.
- **Caption Style Presets & Customizer**: 5 distinct presets (*Karaoke Gold*, *Bold Yellow*, *Cyberpunk Neon*, *Minimal Clean*, *Fire Red*) plus customizable font family, font size, primary color, and active highlight color with live preview.
- **SRT & WebVTT Subtitle Export**: Direct subtitle generators (`generate_srt`, `generate_vtt`) and API endpoints (`GET /api/clips/{id}/subtitles?format=srt|vtt`) with file download attachments.
- **Celery Worker Render Optimization & Bugfix**: Fixed parameter mismatch in `stage_render_clip` to accurately load PostgreSQL `Transcript` and `RenderSettings` models and construct `ReframeResult` and `CaptionStyle` for FFmpeg rendering.
- **Test Suite Expansion**: Test suite expanded from 117 to 127 passing tests (0 failures, 100% pass rate).

---

## [v2.0.0] — Phase 5: Polish & Publishing
- **Split-Screen Layout (`split_screen`)**: 50/50 vertical canvas stack (1080×960 top / 1080×960 bottom stacked via FFmpeg `vstack`) ideal for gameplay + webcam or interview formats.
- **Brand Kits & Watermark Overlay**: Full Brand Kit management API and UI (`/brand-kits`), logo image upload endpoint (`POST /api/brand-kits/{id}/logo`), and FFmpeg logo watermark overlay placed in the top-right corner (`W-w-36:36`) rendered behind ASS subtitles.
- **AI Social Metadata Generation**: Integrated Gemini-powered platform metadata generation (`generate_clip_metadata` and `POST /api/clips/{id}/metadata`) producing catchy short titles (<50 chars), engaging descriptions with emojis, and trending hashtags (`#fyp`, `#shorts`, `#reels`).
- **Prompt-Based Re-Clipping**: Added `user_prompt` support to Stage 4 clip selection (`POST /api/projects/{id}/reclip`) allowing users to extract moments tailored to specific prompts (e.g. "find moments about pricing and revenue").
- **Batch Export as ZIP**: Added `GET /api/projects/{id}/export/zip` streaming an in-memory ZIP bundle containing all rendered `.mp4` video clips, `.srt` and `.vtt` subtitles, clip `metadata.json`, and `project_summary.json`.
- **Social Publishing**: Multi-platform publishing scheduler stubs (`POST /api/clips/{id}/publish`) and one-click copy buttons for YouTube Shorts, TikTok, and Instagram Reels formatted captions in the web UI.
- **Speaker Diarization (`workers/transcribe.py`)**: Acoustic + conversational turn-taking speaker diarization (`diarize_segments`, `diarize_transcript`) assigning `"S1"`, `"S2"`, etc. speaker labels to segments and formatting speaker tags into LLM prompts.
- **Two-Pass Clip Selection, Blended Virality Scoring, Chunking, Ollama & Critic Pass (`workers/select_clips.py`)**: Pass A topic segmentation (`segment_transcript`), overlapping transcript chunking (`_chunk_transcript_for_llm`), 4-signal blended virality score (`compute_blended_score`), local Ollama LLM support (`_call_ollama`), and optional post-LLM critic pass (`critic_pass`).
- **1D Kalman Filter Smoothing (`workers/reframe.py`)**: Integrated `KalmanFilter1D` and `_kalman_smooth` with EMA and scene-cut snapping in `smooth_crop_trajectory`.
- **Direct Upload & Prompt Propagation Fixes (`api/routers/uploads.py`, `api/routers/projects.py`, `workers/tasks.py`)**: Added `GET /api/uploads/presigned` and `POST /api/uploads/complete` endpoints matching the Next.js Web UI flow, and forwarded `user_prompt` end-to-end across the Celery pipeline.
- **Test Suite Expansion**: Test suite expanded from 127 to 143 passing tests (0 failures, 0 warnings, 100% pass rate).

---

## Roadmap

| Version | Phase | Description | Target |
|---|---|---|---|
| `v0.1.0` | Phase 0 | Prototype CLI script | Complete |
| `v0.2.0` | Phase 1 | Docker Compose infrastructure | Complete |
| `v0.3.0` | Phase 1 | Celery job queue, all 6 stages | Complete |
| `v0.4.0` | Phase 1 | DB models + object storage | Complete |
| `v0.5.0` | Phase 1 | Stage resumability + retries | Complete |
| `v0.6.0` | Phase 1 | REST API + SSE progress | Complete |
| `v0.9.0` | Phase 1 | Integration tests | Complete |
| `v1.0.0-beta` | Phase 2 | Face tracking reframe | Complete |
| `v1.0.0` | Phase 3 | Web UI (upload, review, download) | Complete |
| `v1.1.0` | Phase 4 | Trim editor + caption style picker | Complete |
| `v2.0.0` | Phase 5 | Brand kits, diarization, publishing | Complete |

