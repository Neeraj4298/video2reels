# MVP Roadmap & Phased Implementation Strategy

**Product Target:** Independent AI Video Clipping SaaS (Inspired by OpusClip)  
**Document Classification:** Product Delivery & Engineering Roadmap  
**Scope:** Architecture phasing, sprint deliverables, technical risk matrix, and resource requirements.

---

## 1. MVP Vision & Scope Definition

The goal of the Minimum Viable Product (MVP) is to deliver a rock-solid, production-grade end-to-end pipeline that takes a public YouTube link or uploaded video, generates word-accurate transcripts with diarization, isolates the top 5–10 viral highlights using LLM semantic curation, reframes horizontal 16:9 video to vertical 9:16 with active speaker tracking, renders dynamic animated karaoke captions, and allows one-click 1080p MP4 download.

### 1.1 In-Scope for MVP (Core Experience)
*   **Video Ingestion:** Direct file upload (MP4/MOV up to 2 GB) and YouTube URL ingestion via `yt-dlp`.
*   **Audio Pipeline:** Audio extraction, loudness normalization, and WhisperX transcription with word-level timestamps.
*   **AI Curation:** LLM-based boundary segmentation (Hook, Body, Payoff) with 0–99 Virality Scoring and explanatory bullet points.
*   **Smart Reframing:** Face detection (YOLOv8-face) and 9:16 vertical crop with Kalman smoothing (Fill mode).
*   **Animated Captions:** Hormozi-style karaoke word highlighting with auto-emoji injection.
*   **Clip Dashboard & Simple Web Player:** Video preview gallery with score badges and transcript inspection.
*   **Export:** GPU-accelerated 1080x1920 MP4 rendering via FFmpeg NVENC.

### 1.2 Out-of-Scope for Initial MVP (Post-MVP Enhancements)
*   *Multi-speaker Split / Screenshare / Gameplay layouts* (Phase 2).
*   *AI B-Roll generation and sound effects library* (Phase 3).
*   *Interactive full in-browser timeline/canvas editor* (Phase 3).
*   *Export to Premiere/DaVinci XML* (Phase 4).
*   *Social media auto-scheduling / multi-account publishing* (Phase 4).
*   *Model Context Protocol (MCP) server & public developer API* (Phase 5).

---

## 2. Phased Engineering Roadmap

```
  Phase 1: Foundations & Ingestion (Weeks 1–2)
  ├── S3 Multipart Storage & DB Schema
  ├── yt-dlp Ingestion & FFmpeg Normalizer
  └── BullMQ / Redis Task Orchestration
            │
            ▼
  Phase 2: Speech & Intelligence Core (Weeks 3–4)
  ├── WhisperX + PyAnnote Diarization Worker
  ├── LLM Highlight Curation & VAD Boundary Snapper
  └── Virality Scoring Engine (Hook, Flow, Value, Trend)
            │
            ▼
  Phase 3: Computer Vision & Smart Reframing (Weeks 5–6)
  ├── PySceneDetect Shot Transition Detector
  ├── YOLOv8-face Tracker & Active Speaker Detection
  └── Kalman Filter Camera Motion Smoothing (9:16 Fill)
            │
            ▼
  Phase 4: Captions, Studio & Rendering (Weeks 7–8)
  ├── Time-Synced Animated Subtitles (ASS / Remotion)
  ├── AI Emoji Dictionary & Highlight Color Engine
  └── FFmpeg NVENC 1080p Vertical Render Pipeline
            │
            ▼
  Phase 5: User Dashboard & Polishing (Weeks 9–10)
  ├── Web Application (Next.js 14 + TailwindCSS)
  ├── Interactive Clip Preview & Trim Adjuster
  └── Production Hardening, Monitoring & Load Testing
```

---

### Phase 1: Ingestion Pipeline & Storage Infrastructure (Weeks 1–2)
*   **Objective:** Establish fault-tolerant file ingestion, metadata extraction, and distributed worker queues.
*   **Deliverables:**
    1.  PostgreSQL database schema setup (Prisma ORM) for Users, Projects, Transcripts, and Clips.
    2.  S3-compatible object storage integration (Cloudflare R2 or AWS S3) with presigned multipart upload endpoints.
    3.  Containerized Python ingestion worker running `yt-dlp` and `ffmpeg` stream probe.
    4.  BullMQ / Celery Redis queue handling async task dispatch and progress reporting.
*   **Exit Criteria:** A 1-hour YouTube video link or 2 GB MP4 file successfully uploads, downloads, demuxes to 16 kHz mono WAV, and records metadata in DB in under 90 seconds.

---

### Phase 2: Speech-to-Text, Highlight Curation & Scoring (Weeks 3–4)
*   **Objective:** Transform audio into synchronized words and identify viral short clips with rationale.
*   **Deliverables:**
    1.  GPU transcription worker running `WhisperX` (Whisper large-v3 + Wav2Vec2 forced alignment) and `pyannote.audio` diarization.
    2.  Semantic chunking service that formats transcripts with token counts for LLM ingestion.
    3.  Anthropic Claude 3.5 Sonnet / OpenAI GPT-4o curation prompt with strict Pydantic JSON schema.
    4.  VAD boundary-snapping algorithm locking start/end cuts to natural speech pauses.
    5.  Virality scoring algorithm calculating 0–99 score based on Hook, Flow, Value, and Trend.
*   **Exit Criteria:** Ingested audio generates a full word-level JSON transcript with >95% word accuracy, extracting 5–10 candidate clips with start/end timestamps and virality score breakdowns.

---

### Phase 3: Face Tracking & 9:16 Reframing Engine (Weeks 5–6)
*   **Objective:** Automatically crop 16:9 widescreen footage into centered, smooth 9:16 vertical clips.
*   **Deliverables:**
    1.  PySceneDetect shot boundary analyzer emitting cut timestamps.
    2.  YOLOv8-face detection pipeline processing candidate clip intervals at 10 fps.
    3.  TalkNet / SyncNet active speaker detector matching mouth movement to audio speech energy.
    4.  Camera motion planner utilizing Kalman filter smoothing to eliminate visual jitter.
    5.  FFmpeg dynamic crop generator applying computed keyframe crop coordinates.
*   **Exit Criteria:** Moving speakers in horizontal footage stay centered in 9:16 vertical crops with zero camera wobble and seamless scene cut transitions.

---

### Phase 4: Subtitles, Styling & High-Speed Rendering (Weeks 7–8)
*   **Objective:** Produce publication-ready viral shorts with animated captions and brand styling.
*   **Deliverables:**
    1.  ASS subtitle script generator with `{\k}` karaoke timing per word.
    2.  AI Emoji semantic lookup tagging high-impact verbs, nouns, and emotions.
    3.  Subtitle style presets (Alex Hormozi, Neon Yellow, Clean White, Minimal Subtitle).
    4.  FFmpeg NVENC rendering worker executing hardware-accelerated H.264 vertical video encoding.
    5.  Automated watermark applicator for Free tier accounts.
*   **Exit Criteria:** A 60-second vertical clip with burned-in animated karaoke subtitles renders in under 15 seconds on an Nvidia T4/A10G GPU.

---

### Phase 5: Web UI Studio, User Workflows & Polishing (Weeks 9–10)
*   **Objective:** Deliver an intuitive, modern web dashboard for video creators.
*   **Deliverables:**
    1.  Next.js 14 App Router frontend styled with TailwindCSS and Lucide icons.
    2.  Project upload page with URL paste bar, file drag-and-drop, and duration settings.
    3.  Results gallery displaying clips ordered by Virality Score with headline tags.
    4.  Interactive clip modal: preview player, word-level text editor (deleting text skips frames), caption style selector.
    5.  One-click MP4 download and shareable link generator.
*   **Exit Criteria:** Non-technical user can submit a podcast link and download a viral vertical short in under 4 minutes total elapsed time without human intervention.

---

## 3. Technical Risk Matrix & Mitigation Strategies

| Risk | Impact | Probability | Mitigation Strategy |
| :--- | :---: | :---: | :--- |
| **YouTube Rate Limiting / Bot Detection on `yt-dlp`** | High | High | Implement rotating residential proxy pool; encourage direct file upload; support Google Drive / Dropbox direct ingest. |
| **GPU Out-Of-Memory (OOM) during WhisperX / YOLOv8** | High | Medium | Enforce strict batch size caps (`batch_size=8` for alignment); process video frames in sliced chunks; deploy 16 GB+ VRAM GPUs (A10G / L4). |
| **Acoustic / Visual Desynchronization in Reframing** | Medium | Medium | Normalize all incoming video to Constant Frame Rate (CFR 30.0 fps) before running face tracking and audio alignment. |
| **Hallucinated Cut Timestamps from LLM** | High | Medium | Pass explicit word indices to LLM rather than float timestamps; LLM returns `[start_word_id, end_word_id]`; backend references deterministic WhisperX timestamps. |
| **Audio Clicks / Distortion at Splice Boundaries** | Low | High | Enforce mandatory 15ms audio crossfade (`afade=t=in:d=0.015,afade=t=out:d=0.015`) on all video cut points. |
| **High GPU Cloud Infrastructure Costs** | High | Medium | Auto-scale GPU workers to zero during idle periods; utilize Spot/Preemptible instances on AWS/RunPod/Lambda Labs; cache common models on worker disks. |

---

## 4. Compute & Infrastructure Resource Estimates

### 4.1 Cost per Video Processing Hour (Estimate)
*   **Ingestion (CPU t3.medium):** ~$0.01
*   **WhisperX + Diarization (1x Nvidia A10G for 3 minutes):** ~$0.05
*   **LLM Curation & Scoring (Claude 3.5 Sonnet ~25k tokens):** ~$0.10
*   **Face Tracking & ASD (A10G for 2 minutes):** ~$0.03
*   **FFmpeg NVENC Rendering (10 clips x 15s render time = 2.5 min GPU):** ~$0.04
*   **Storage & Bandwidth (Cloudflare R2, zero egress fees):** ~$0.02
*   **Total Cloud Compute Cost per 1-Hour Video:** **~$0.25 – $0.30**

At a $15/month subscription providing 150 processing minutes (~2.5 hours), total compute COGS is ~$0.75, yielding an attractive **~95% gross margin**.

---

## 5. Summary of Milestones & KPIs

*   **Milestone 1 (Week 2):** Ingestion engine accepts 10+ platforms with 99% download success rate.
*   **Milestone 2 (Week 4):** Transcription accuracy WER < 5%; Highlight extraction achieves >80% semantic overlap with human editor picks.
*   **Milestone 3 (Week 6):** Reframing keeps speaker centered in >95% of active speech frames without manual intervention.
*   **Milestone 4 (Week 8):** End-to-end rendering pipeline produces 1080p 60fps vertical short in < 20% of clip duration.
*   **Milestone 5 (Week 10):** Public Beta launch with complete web application, Stripe billing, and user feedback loop.
