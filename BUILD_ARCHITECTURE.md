# 🎬 video2reels — Build Architecture & Roadmap

> **Product:** AI Short-Form Video Clipper (OpusClip-style)
> **Goal:** Turn long-form videos into scored, captioned, vertical short-form clips automatically.
> **Owner:** Solo creator / personal use (designed to scale to multi-user later)
> **Doc Version:** 1.0 | **Created:** 2026-10-31 | **Status:** Planning

---

## Table of Contents

1. [Product Vision](#1-product-vision)
2. [System Architecture](#2-system-architecture)
3. [Tech Stack](#3-tech-stack)
4. [Repository Structure](#4-repository-structure)
5. [Database Schema](#5-database-schema)
6. [API Design](#6-api-design)
7. [Processing Pipeline](#7-processing-pipeline)
8. [Version Roadmap](#8-version-roadmap)
9. [Feature Documentation](#9-feature-documentation)
10. [Non-Functional Requirements](#10-non-functional-requirements)
11. [Infrastructure & Cost Estimate](#11-infrastructure--cost-estimate)
12. [Success Metrics](#12-success-metrics)
13. [Risks & Mitigations](#13-risks--mitigations)
14. [Open Questions](#14-open-questions)

---

## 1. Product Vision

A **self-owned, self-hosted pipeline** where you paste a link or upload a video file, and ~15-20 minutes later you have a set of **scored, captioned, vertical (9:16) clips** ready to lightly edit and publish on TikTok, Instagram Reels, and YouTube Shorts.

### Why Build This?

| Pain Point | Solution |
|---|---|
| Manual clipping of 60-min video takes hours | Fully automated clip detection via LLM |
| Subscription tools (OpusClip) are expensive | Self-hosted, runs on your own GPU |
| Watermarks on free tiers | No watermarks, full control |
| Limited caption/brand customization | Fully configurable caption styles & brand kits |

### Goals (All Versions)

- Generate **5-15 usable clips** from a 30-90 min video with minimal manual effort
- **>=60% clip acceptance rate** (usable without edits)
- Processing time: **<0.3x video duration** on GPU (60-min video in ~20 min)
- Cost: **<$1 per processed hour** of video
- Full control over caption styles, branding, and clip length

---

## 2. System Architecture

### 2.1 High-Level Architecture Diagram

```
+--------------------------------------------------------------+
|                        CLIENT LAYER                          |
|   +------------------------------------------------------+   |
|   |           Next.js Web UI (React + Tailwind)          |   |
|   |  Upload / Project Dashboard / Clip Review / Editor   |   |
|   +----------------------+-------------------------------+   |
+-------------------------+------------------------------------+
                          | REST + SSE
+-------------------------v------------------------------------+
|                        API LAYER                             |
|   +------------------------------------------------------+   |
|   |         FastAPI (Python) -- API Server               |   |
|   |  Auth . Project CRUD . Job Creation . Signed URLs    |   |
|   +----------+-----------------------------+-------------+   |
|              |                             |                  |
|   +----------v---------+   +--------------v--------------+   |
|   |   PostgreSQL DB    |   |  Object Storage (MinIO/R2)  |   |
|   |  projects/videos/  |   |  originals . audio . clips  |   |
|   |  transcripts/      |   +-----------------------------+   |
|   |  clips/jobs/kits   |                                      |
|   +--------------------+                                      |
+--------------------------------------------------------------+
                          |
             +------------v-----------+
             |    Redis (Job Queue)   |
             |  CPU Queue . GPU Queue |
             +------------+-----------+
                          | Celery Workers
+-------------------------v------------------------------------+
|                      WORKER LAYER                            |
|                                                              |
|  Stage 1: Ingest            Stage 2: Audio Extract          |
|  [ ingest.py          ] --> [ audio_extract.py         ]    |
|  [ yt-dlp / upload    ]     [ FFmpeg -> mono 16kHz WAV ]    |
|  [ ffprobe validate   ]                  |                   |
|                                          v                   |
|  Stage 3: Transcription     Stage 4: Clip Selection         |
|  [ transcribe.py      ] --> [ select_clips.py          ]    |
|  [ faster-whisper     ]     [ Segmentation + LLM       ]    |
|  [ word timestamps    ]     [ Virality scoring 0-100   ]    |
|                                          |                   |
|              (parallelized per clip)     v                   |
|  Stage 5: Reframing         Stage 6: Caption + Render       |
|  [ reframe.py         ] --> [ captions.py + render.py  ]    |
|  [ Face detection     ]     [ ASS generation           ]    |
|  [ 9:16 crop path     ]     [ FFmpeg export 1080x1920  ]    |
+--------------------------------------------------------------+
```

### 2.2 Data Flow

```
User Input
    |
    +--- File Upload (chunked multipart / resumable tus)
    |
    +--- URL Paste (yt-dlp download)
                        |
                        v
              [Object Storage] original_video.mp4
                        |
              ffprobe: validate + normalize
                        |
              ffmpeg: extract audio.wav (mono 16kHz PCM)
                        |
              faster-whisper: transcript.json (word-level)
                        |
              Segmentation + LLM: clips[] with scores
                        |
          (per clip, parallelized)
                        |
              Face tracking + 9:16 crop path
                        |
              Caption render + FFmpeg export
                        |
              clip_N.mp4 -> Object Storage
```

---

## 3. Tech Stack

| Layer | Technology | Rationale |
|---|---|---|
| **Frontend** | Next.js 14 (App Router) + Tailwind CSS | SSR, streaming updates; Video.js for preview |
| **API Server** | FastAPI (Python 3.11+) | Native ML ecosystem; async support |
| **Job Queue** | Redis + Celery | Separate GPU/CPU queues, retries, progress |
| **Database** | PostgreSQL 15+ | JSONB for transcripts & render settings |
| **Object Storage** | MinIO (local) / Cloudflare R2 (cloud) | R2 has zero egress fees -- ideal for video |
| **Transcription** | faster-whisper (local) / Deepgram API | Word-level timestamps; VAD filtering |
| **LLM** | Google Gemini / Claude API | Clip selection, scoring, title generation |
| **Face Tracking** | MediaPipe + YOLOv8-face | Per-frame face boxes for reframing |
| **Rendering** | FFmpeg + ASS subtitles | GPU-accelerated via NVENC |
| **URL Download** | yt-dlp | Best-quality download with audio merge |
| **Observability** | Structured logs + Sentry | Per-stage timing, error tracking |
| **Deployment** | Docker Compose (local) | GPU worker on RunPod/Modal for cloud scale |

---

## 4. Repository Structure

```
video2reels/
├── README.md
├── BUILD_ARCHITECTURE.md        # This file
├── CHANGELOG.md                 # Version history
├── docker-compose.yml           # Full local dev stack
├── docker-compose.prod.yml      # Production overrides
├── .env.example                 # Environment variables template
|
├── apps/
│   ├── web/                     # Next.js 14 Frontend
│   │   ├── app/
│   │   │   ├── (dashboard)/
│   │   │   │   ├── page.tsx     # Project list
│   │   │   │   └── projects/
│   │   │   │       └── [id]/
│   │   │   │           ├── page.tsx     # Clip review grid
│   │   │   │           └── clips/[clipId]/
│   │   │   │               └── page.tsx # Clip editor
│   │   │   └── layout.tsx
│   │   ├── components/
│   │   │   ├── upload/          # Drag-drop + URL input
│   │   │   ├── progress/        # Pipeline stage tracker
│   │   │   ├── clip-card/       # Thumbnail, score, hook
│   │   │   ├── video-player/    # HTML5 player + trim handles
│   │   │   ├── caption-editor/  # Style picker, text edit
│   │   │   └── brand-kit/       # Logo, font, color settings
│   │   └── lib/
│   │       ├── api.ts           # API client
│   │       └── types.ts         # Shared TypeScript types
│   │
│   └── api/                     # FastAPI Backend
│       ├── main.py              # App entry + router registration
│       ├── routers/
│       │   ├── projects.py      # Project CRUD
│       │   ├── uploads.py       # Presigned URL generation
│       │   ├── clips.py         # Clip read/update/render
│       │   └── brand_kits.py    # Brand kit CRUD
│       ├── models/              # SQLAlchemy ORM models
│       ├── schemas/             # Pydantic request/response schemas
│       ├── services/
│       │   ├── storage.py       # MinIO/R2 client wrapper
│       │   ├── queue.py         # Celery task dispatch
│       │   └── events.py        # SSE progress events
│       ├── db.py                # SQLAlchemy async session
│       └── config.py            # Settings from env vars
|
├── workers/                     # Celery Worker Scripts
│   ├── celery_app.py            # Celery config, queues, retries
│   ├── ingest.py                # Stage 1: Download & validate
│   ├── audio_extract.py         # Stage 2: FFmpeg audio extraction
│   ├── transcribe.py            # Stage 3: faster-whisper ASR
│   ├── select_clips.py          # Stage 4: Segmentation + LLM
│   ├── reframe.py               # Stage 5: Face tracking, crop path
│   ├── captions.py              # Stage 6a: ASS subtitle generation
│   └── render.py                # Stage 6b: FFmpeg export
|
├── prompts/                     # Versioned LLM Prompt Templates
│   ├── v1/
│   │   ├── clip_selection.txt
│   │   └── metadata_gen.txt
│   └── v2/
│       ├── clip_selection.txt
│       └── prompt_based_clip.txt
|
├── infra/
│   ├── Dockerfile.api
│   ├── Dockerfile.worker
│   ├── Dockerfile.web
│   ├── nginx/nginx.conf
│   └── migrations/              # Alembic DB migrations
|
└── tests/
    ├── unit/
    ├── integration/
    └── fixtures/
        ├── sample_short.mp4     # 5-min test video
        └── expected_clips.json  # Golden output
```

---

## 5. Database Schema

### Tables

#### `projects`
| Column | Type | Description |
|---|---|---|
| `id` | UUID PK | |
| `name` | TEXT | User-defined project name |
| `source_type` | ENUM | `upload` or `url` |
| `source_url` | TEXT | Original URL (if applicable) |
| `status` | ENUM | `pending`, `processing`, `done`, `failed` |
| `created_at` | TIMESTAMPTZ | |

#### `videos`
| Column | Type | Description |
|---|---|---|
| `id` | UUID PK | |
| `project_id` | UUID FK | -> projects |
| `storage_key` | TEXT | Object storage path |
| `duration` | FLOAT | Seconds |
| `width` | INT | Pixels |
| `height` | INT | Pixels |
| `fps` | FLOAT | |
| `codec` | TEXT | e.g. h264 |
| `language` | TEXT | Detected language |

#### `transcripts`
| Column | Type | Description |
|---|---|---|
| `id` | UUID PK | |
| `video_id` | UUID FK | -> videos |
| `json` | JSONB | Full transcript with word-level timestamps |
| `model` | TEXT | e.g. faster-whisper-large-v3 |
| `created_at` | TIMESTAMPTZ | |

#### `clips`
| Column | Type | Description |
|---|---|---|
| `id` | UUID PK | |
| `project_id` | UUID FK | -> projects |
| `start` | FLOAT | Start time (seconds) |
| `end` | FLOAT | End time (seconds) |
| `score` | INT | Virality score 0-100 |
| `score_breakdown` | JSONB | `{hook, flow, value, trend}` |
| `hook` | TEXT | First hook sentence |
| `title` | TEXT | Generated title |
| `description` | TEXT | Generated description |
| `hashtags` | TEXT[] | Suggested hashtags |
| `status` | ENUM | `pending`, `rendering`, `done`, `failed` |
| `selected` | BOOL | User selected |

#### `render_settings`
| Column | Type | Description |
|---|---|---|
| `id` | UUID PK | |
| `clip_id` | UUID FK | -> clips |
| `layout` | ENUM | `vertical`, `split_screen`, `blur_bg` |
| `caption_style` | JSONB | `{font, size, color, highlight_color, position}` |
| `crop_keyframes` | JSONB | Face-tracking crop path |
| `brand_kit_id` | UUID FK | -> brand_kits (nullable) |

#### `renders`
| Column | Type | Description |
|---|---|---|
| `id` | UUID PK | |
| `clip_id` | UUID FK | -> clips |
| `storage_key` | TEXT | Final MP4 path |
| `resolution` | TEXT | e.g. 1080x1920 |
| `size_bytes` | BIGINT | |
| `created_at` | TIMESTAMPTZ | |

#### `jobs`
| Column | Type | Description |
|---|---|---|
| `id` | UUID PK | |
| `project_id` | UUID FK | -> projects |
| `stage` | TEXT | Current pipeline stage |
| `status` | ENUM | `queued`, `running`, `done`, `failed` |
| `progress` | INT | 0-100 |
| `error` | TEXT | Error message if failed |
| `attempts` | INT | Retry count (max 3) |
| `started_at` | TIMESTAMPTZ | |
| `finished_at` | TIMESTAMPTZ | |

#### `brand_kits`
| Column | Type | Description |
|---|---|---|
| `id` | UUID PK | |
| `name` | TEXT | |
| `logo_key` | TEXT | Storage path |
| `fonts` | JSONB | `{primary, secondary}` |
| `colors` | JSONB | `{primary, secondary, accent}` |
| `default_caption_style` | JSONB | |

---

## 6. API Design

### REST Endpoints

| Method | Endpoint | Purpose |
|---|---|---|
| `POST` | `/api/projects` | Create project from URL or start upload |
| `POST` | `/api/uploads/sign` | Get presigned multipart upload URLs |
| `GET` | `/api/projects` | List all projects |
| `GET` | `/api/projects/{id}` | Project status, progress, stage |
| `DELETE` | `/api/projects/{id}` | Delete project and all stored files |
| `GET` | `/api/projects/{id}/clips` | List generated clips |
| `PATCH` | `/api/clips/{id}` | Update trim points, title, caption text/style |
| `POST` | `/api/clips/{id}/render` | Re-render with new settings |
| `GET` | `/api/clips/{id}/download` | Signed URL for final MP4 |
| `GET` | `/api/brand-kits` | List brand kits |
| `POST` | `/api/brand-kits` | Create brand kit |
| `PATCH` | `/api/brand-kits/{id}` | Update brand kit |

### Real-time Progress (Server-Sent Events)

```
GET /api/projects/{id}/events
Content-Type: text/event-stream

data: {"stage": "transcribing", "progress": 42, "message": "Processing audio..."}
data: {"stage": "selecting_clips", "progress": 67, "message": "LLM analyzing 847 segments..."}
data: {"stage": "rendering", "progress": 90, "clips_done": 3, "clips_total": 8}
data: {"stage": "done", "progress": 100, "clip_count": 8}
```

---

## 7. Processing Pipeline

### Stage Overview

| Stage | Name | Worker Type | Avg. Time (60-min video) |
|---|---|---|---|
| 1 | Ingestion & Validation | CPU | ~2-5 min |
| 2 | Audio Extraction | CPU | ~1 min |
| 3 | Transcription (ASR) | GPU | ~5-8 min |
| 4 | Clip Selection (LLM) | CPU | ~2-3 min |
| 5 | Vertical Reframing | GPU | ~3-5 min |
| 6 | Caption Render + Export | GPU | ~3-5 min (parallelized) |

### Stage 1: Ingestion

- If URL: `yt-dlp --format bestvideo+bestaudio --merge-output-format mp4`
- If upload: retrieve from presigned URL
- `ffprobe`: read duration, resolution, codec, fps, audio streams
- Validate: reject if corrupt, >3hr, no audio, or resolution <480p
- Normalize: transcode to H.264 + AAC constant-framerate if needed

### Stage 2: Audio Extraction

```bash
ffmpeg -i input.mp4 -vn -ac 1 -ar 16000 -c:a pcm_s16le audio.wav
```

Mono 16 kHz PCM WAV -- standard Whisper input format.

### Stage 3: Transcription (ASR)

```python
from faster_whisper import WhisperModel
model = WhisperModel("large-v3", device="cuda", compute_type="float16")
segments, info = model.transcribe("audio.wav", word_timestamps=True, vad_filter=True)
```

Output JSON:
```json
{
  "language": "en",
  "segments": [
    {
      "start": 12.34, "end": 18.9, "speaker": "S1",
      "text": "Here is the thing most people get wrong...",
      "words": [{"w": "Here", "s": 12.34, "e": 12.61, "p": 0.98}]
    }
  ]
}
```

### Stage 4: Clip Selection (Two-Pass)

**Pass A -- Segmentation:**
- Split at sentence boundaries (spaCy / regex)
- Split at long pauses (>1.5s silence)
- Split at speaker changes (v2+)

**Pass B -- LLM:**
- Send numbered timestamped transcript
- Request structured JSON clips with start/end/score/hook
- Validate all returned timestamps exist in transcript
- Post-process: snap to word boundaries (+/-0.3s), remove overlaps, rank top-N

**Blended scoring:**

| Signal | Weight |
|---|---|
| LLM holistic score | 60% |
| Speech energy + pace | 15% |
| Emotional intensity (NLP) | 15% |
| Hook pattern match | 10% |

### Stage 5: Vertical Reframing (9:16)

Target: 1080x1920 from 1920x1080 source (608px crop window, scaled up)

1. Scene detection: PySceneDetect -> scene boundaries
2. Sample 1 frame/sec per scene, run face detector (MediaPipe / YOLOv8-face)
3. Center crop on primary face (largest bounding box)
4. Smooth crop path with Kalman filter / EMA; max pan 15%/sec
5. Store keyframes: `[{frame: 0, x: 340, y: 0, w: 608, h: 1080}, ...]`

### Stage 6: Caption Render + FFmpeg Export

```bash
ffmpeg \
  -i clip.mp4 \
  -vf "crop=608:1080:x_offset:0,scale=1080:1920,ass=captions.ass" \
  -af "loudnorm=I=-14:TP=-2:LRA=11" \
  -c:v libx264 -preset fast \
  -c:a aac -b:a 128k \
  -movflags +faststart \
  output_clip.mp4
```

GPU acceleration (when NVENC available):
```bash
-c:v h264_nvenc -preset p4 -rc vbr -cq 23
```

---

## 8. Version Roadmap

### Version Matrix

| Feature | v0 Proto | v1 MVP | v2 Full | v3+ Scale |
|---|:---:|:---:|:---:|:---:|
| CLI single-script | YES | - | - | - |
| File upload | - | YES | YES | YES |
| URL input (yt-dlp) | - | YES | YES | YES |
| Whisper transcription | YES | YES | YES | YES |
| LLM clip detection | YES | YES | YES | YES |
| Virality score 0-100 | - | YES | YES | YES |
| 9:16 center crop | YES | YES | YES | YES |
| Face tracking reframe | - | YES | YES | YES |
| Word-highlight captions | YES | YES | YES | YES |
| Export 1080x1920 H.264 | YES | YES | YES | YES |
| SRT/VTT export | - | YES | YES | YES |
| Web UI | - | YES | YES | YES |
| Real-time progress (SSE) | - | YES | YES | YES |
| Transcript-based editor | - | - | YES | YES |
| Caption style presets | - | - | YES | YES |
| Brand kits | - | - | YES | YES |
| Speaker diarization | - | - | YES | YES |
| Split-screen layout | - | - | YES | YES |
| Metadata (title/desc/hashtags) | - | - | YES | YES |
| Prompt-based clipping | - | - | YES | YES |
| Platform publishing API | - | - | YES | YES |
| Multi-language / dubbing | - | - | - | YES |
| Analytics feedback loop | - | - | - | YES |
| Team workspaces + billing | - | - | - | YES |

---

### Phase 0 -- Prototype CLI (`v0.1.0`)

**Duration:** 2-4 days
**Goal:** Validate clip quality end-to-end before investing in infrastructure.

**Deliverables:**
- [x] Single Python script `scripts/prototype.py`
- [x] Takes local video file as input (`--input`) or URL (`--url`)
- [x] Runs faster-whisper for transcription (Stage 3, cached)
- [x] Calls LLM API for clip selection — Gemini 2.0 Flash via `google-genai` SDK (Stage 4)
- [x] Applies center-crop reframe (no face tracking) (Stage 5)
- [x] Burns ASS captions with word highlighting (Stage 6a)
- [x] Exports MP4 clips to `./output/` (Stage 6b)
- [x] All stages cache intermediate results — re-runs skip completed stages
- [x] Unit test suite (86 tests, 0 warnings) covering all 6 stages

**Success Criteria:**
- Script runs end-to-end on a 30-min test video
- At least 3 of 5 generated clips feel postable
- Total processing time < 30 min on local machine

---

### Phase 1 -- Pipeline & Infrastructure (`v0.2.0 to v0.9.0`)

**Duration:** 1-2 weeks
**Goal:** Replace script with async pipeline + database.

| Version | Milestone | Deliverables |
|---|---|---|
| `v0.2.0` ✅ | Infrastructure up | Docker Compose: Postgres, Redis, MinIO, API skeleton |
| `v0.3.0` ✅ | Job queue working | Celery tasks for all 6 stages; idempotent; retries |
| `v0.4.0` ✅ | DB & storage | All models + Alembic migrations; MinIO integration |
| `v0.5.0` ✅ | Stage resumability | Failed jobs resume from last completed stage |
| `v0.6.0` ✅ | API complete | All REST endpoints; SSE progress events |
| `v0.9.0` ✅ | Integration tests | Full pipeline test with sample video (107 passing tests) |


**Technical Requirements:**
- All stages idempotent (safe to retry)
- Max 3 retry attempts with exponential backoff (60s -> 300s -> 900s)
- Jobs resume from last completed stage after failure
- Separate GPU queue and CPU queue in Celery
- Structured JSON logging with per-stage timing

---

### Phase 2 -- Smart Reframing (`v1.0.0-beta`)

**Duration:** 1-2 weeks
**Goal:** Replace static crop with intelligent face-tracking.

**Deliverables:**
- [x] Face detection per-frame (MediaPipe BlazeFace + OpenCV Haar cascade fallback)
- [x] Crop path smoothing (Kalman filter / EMA)
- [x] Max pan speed limiting (15% frame width / sec)
- [x] Scene boundary detection (PySceneDetect)
- [x] Fallback to center crop when no face detected
- [x] Blur-background layout option
- [x] Crop keyframes stored in render_settings

**Success Criterion:** Face-in-frame rate >= 95% ✅ (117 total passing tests)


---

### Phase 3 -- Web UI (`v1.0.0`)

**Duration:** 1-2 weeks

| Page | Features |
|---|---|
| Home / Project List | Create project (URL input + drag-drop upload) |
| Processing View | Live stage progress bar (SSE), ETA |
| Clip Review Grid | Thumbnail, duration, score badge, hook text |
| Clip Detail / Preview | Video player, trim handles, download button |
| Settings | API keys, default clip length, default caption style |

---

### Phase 4 -- Editing (`v1.1.0`)

**Duration:** 1-2 weeks

**Deliverables:**
- [x] Trim handles: drag start/end on waveform visualization
- [x] Transcript editor: click word to jump; delete words to cut
- [x] Caption style picker: font, size, color, presets
- [x] Re-render button: queue new render with updated settings
- [x] SRT/VTT export alongside MP4 download

---

### Phase 5 -- Polish & Publishing (`v2.0.0`)

**Duration:** 2+ weeks

**Deliverables:**
- [x] Metadata generation: title, description, hashtags per clip (AI-generated via Gemini & endpoint)
- [x] Brand kits: logo watermark overlay in FFmpeg, font & color scheme management, logo upload API & UI
- [x] Split-screen layout: speaker + screen share/gameplay (50/50 vertical stack in FFmpeg)
- [x] Prompt-based clipping ("find moments about pricing" in Stage 4 + `POST /api/projects/{id}/reclip`)
- [x] Scheduling & publishing: TikTok, Instagram Reels, YouTube Shorts publishing stubs & caption copy
- [x] Batch download as ZIP (`GET /api/projects/{id}/export/zip` with MP4s, SRTs, VTTs, and metadata)

---

## 9. Feature Documentation

### Feature: Virality Score

**What it is:** A 0-100 integer score + breakdown for each suggested clip.

**Computation:**
```
final_score = (
    llm_score        * 0.60 +  # LLM holistic assessment
    energy_score     * 0.15 +  # Audio RMS + words-per-minute
    sentiment_score  * 0.15 +  # Emotional intensity (NLP)
    hook_score       * 0.10    # Rule-based hook pattern match
)
```

**Breakdown fields:** `{hook: 0-10, flow: 0-10, value: 0-10, trend: 0-10}`

**Display:** Color gradient badge (red <50, yellow <80, green >=80)

---

### Feature: Word-Highlight Captions

**What it is:** Animated captions where each word changes color as it is spoken.

**Implementation:** ASS (Advanced SubStation Alpha) subtitle format with per-word timing tags.

**Caption style properties:**
```json
{
  "font_family": "Inter",
  "font_size": 52,
  "font_weight": "bold",
  "primary_color": "#FFFFFF",
  "highlight_color": "#FFD700",
  "background": "shadow",
  "position": "bottom",
  "animation": "karaoke"
}
```

**Timing accuracy target:** < 100 ms drift from audio

---

### Feature: Vertical Reframing

**What it is:** Automatic 16:9 -> 9:16 conversion with speaker kept in frame.

**Algorithm:**
1. Detect faces every N frames
2. Compute smooth crop center using Kalman filter
3. Limit pan speed to avoid jarring motion (max 15% frame width/sec)
4. Store keyframes in DB for re-rendering without re-detection
5. FFmpeg crop filter with interpolated keyframe values

**Fallback priority:**
1. Primary speaker face (largest bounding box)
2. Most recently visible face
3. Center of frame

---

### Feature: LLM Clip Selection

**What it is:** LLM analyzes the full transcript and identifies the most engaging, self-contained moments.

**Prompt requirements:**
- Numbered, timestamped transcript lines (prevents timestamp hallucination)
- Structured JSON output requirement
- Validation: all returned timestamps must exist in transcript
- Chunking with overlap for long transcripts exceeding context window

**Post-LLM critic pass (v2+):**
A second LLM call reviews selected clips and refines based on:
- Content uniqueness (no repetitive clips)
- Stronger hook alternatives
- Better end points

---

### Feature: Pipeline Resumability

**What it is:** Failed jobs resume from last completed stage, not from scratch.

**How it works:**
- Each stage writes output to DB + object storage before marking complete
- `jobs.stage` tracks current stage; `jobs.status` tracks completion
- On retry: skip all `done` stages, resume from first incomplete

**Retry policy:**
- Max attempts: 3
- Backoff: 60s -> 300s -> 900s (exponential)

---

## 10. Non-Functional Requirements

| Area | Requirement |
|---|---|
| **Performance** | 60-min video processed in <20 min on one mid-range GPU |
| **Scalability** | Stateless workers; scale by adding queue consumers; separate GPU/CPU queues |
| **Reliability** | Idempotent stages; retries with backoff (3 attempts); resume from last stage |
| **Storage** | Lifecycle rules: delete originals/intermediates after N days; keep final clips |
| **Security** | Presigned URLs with expiry; file type + size validation; sandboxed FFmpeg; no command injection |
| **Privacy** | Fully local mode (local Whisper + local LLM) -- content never leaves machine |
| **Observability** | Structured JSON logs; per-stage timing; Sentry error tracking; Flower monitoring |
| **Accessibility** | Captions burned in; SRT/VTT also exported |

---

## 11. Infrastructure & Cost Estimate

### Local Setup (Personal Use)

| Component | Spec |
|---|---|
| GPU | NVIDIA with >=8 GB VRAM (RTX 3060+ recommended) |
| RAM | 16 GB+ system RAM |
| Storage | 100 GB+ for video files |
| Docker | Compose: Postgres + Redis + MinIO + API + Workers |

### Cost Per 60-Minute Video

| Item | Approach | Approx. Cost |
|---|---|---|
| Transcription | Local faster-whisper on GPU | Free (electricity) |
| Transcription | Deepgram/AssemblyAI API | ~$0.15-0.50/hr audio |
| LLM clip selection | ~15k-25k input tokens | ~$0.01-0.50 (model-dependent) |
| Face tracking | Local CPU/GPU | Free |
| Rendering | FFmpeg local | Free |
| Storage | MinIO local / R2 cloud | Cents/month |
| **Total (local)** | | **~$0.01-0.50** |
| **Total (cloud APIs)** | | **~$0.50-1.00** |

---

## 12. Success Metrics

| Metric | Target |
|---|---|
| Clip acceptance rate (no edits needed) | >= 60% |
| Time from upload to first clips | < 20 min for 60-min video |
| Caption timing error | < 100 ms |
| Face-in-frame rate in reframed clips | >= 95% |
| Pipeline failure rate | < 2% of jobs |
| Cost per processed hour of video | < ~$1 |

---

## 13. Risks & Mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| LLM picks weak clips | Low quality output | Critic prompt pass; blend audio signals; prompt-based clipping |
| Wrong face tracked | Speaker out of frame | Diarization + active-speaker detection; split/blur fallback |
| Caption drift vs audio | Unprofessional look | WhisperX forced alignment; timing validation in tests |
| Cuts mid-sentence | Awkward clips | Snap to word boundaries; +/-0.3s padding |
| Large files break uploads | Frustrating UX | Resumable multipart upload (tus / S3 multipart) |
| Long processing time | Slow feedback | Parallelize per-clip rendering; SSE progress with early results |
| Hallucinated LLM timestamps | Wrong clips | Numbered timestamped lines; validate times exist in transcript |
| yt-dlp ToS violations | Legal risk | Warn user; prefer direct uploads; own-content-only default |

---

## 14. Open Questions

1. **Scale:** Personal tool only, or multi-user product? (Affects auth, billing, legal)
2. **Content types:** Talking-head podcasts, gaming, tutorials, or webinars? (Affects reframing)
3. **LLM:** Run local (Ollama + Llama 3) or cloud APIs (Gemini / Claude)?
4. **Languages:** English only for v1, or multi-language from the start?
5. **Publishing:** Export files only (v1), or auto-publish to platforms (v2)?
6. **Max video length:** 90 min? 3 hr? (Affects LLM chunking strategy)
7. **GPU availability:** Dedicated local GPU, or cloud rental (RunPod/Modal)?

---

## Appendix: Environment Variables

```bash
# .env.example

# Database
DATABASE_URL=postgresql+asyncpg://user:pass@localhost:5432/video2reels

# Redis / Celery
REDIS_URL=redis://localhost:6379/0

# Object Storage
STORAGE_ENDPOINT=http://localhost:9000
STORAGE_ACCESS_KEY=minioadmin
STORAGE_SECRET_KEY=minioadmin
STORAGE_BUCKET=video2reels

# LLM
GEMINI_API_KEY=your_key_here
ANTHROPIC_API_KEY=your_key_here
LLM_PROVIDER=gemini  # or: anthropic, ollama

# Transcription
WHISPER_MODEL=large-v3
WHISPER_DEVICE=cuda  # or: cpu
TRANSCRIPTION_PROVIDER=local  # or: deepgram, assemblyai

# Pipeline Config
MAX_VIDEO_DURATION_HOURS=3
DEFAULT_CLIP_MIN_DURATION=20
DEFAULT_CLIP_MAX_DURATION=90
DEFAULT_TOP_N_CLIPS=10
MAX_JOB_ATTEMPTS=3

# Sentry (optional)
SENTRY_DSN=

# App
API_BASE_URL=http://localhost:8000
NEXT_PUBLIC_API_URL=http://localhost:8000
```

---

*This document is the living source of truth for the video2reels build. Update it as decisions are made and open questions are answered.*
