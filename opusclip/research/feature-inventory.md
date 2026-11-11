# OpusClip Feature Inventory & Functional Breakdown

**Document Scope:** Detailed breakdown of all functional modules, capabilities, sub-features, user interactions, and boundary behaviors observed across the OpusClip ecosystem, mapped to independent engineering specifications.

---

## 1. Feature Map Overview

```
                      ┌──────────────────────────────────────┐
                      │        Long-Form Video/Audio Input   │
                      │  (YouTube/Direct Upload/Agent Opus)  │
                      └──────────────────┬───────────────────┘
                                         ▼
                      ┌──────────────────────────────────────┐
                      │         1. Video Ingestion           │
                      │  (Validation, Extraction, Normalize) │
                      └──────────────────┬───────────────────┘
                                         ▼
                      ┌──────────────────────────────────────┐
                      │    2. Speech-to-Text & Diarization   │
                      │ (Word Timestamps, Speaker Clustering)│
                      └──────────────────┬───────────────────┘
                                         ▼
         ┌───────────────────────────────┴───────────────────────────────┐
         ▼                                                               ▼
┌─────────────────────────────────┐                     ┌─────────────────────────────────┐
│ 3. AI Highlight Detection &     │                     │ 5. Vision & Active Speaker      │
│    Clip Selection (LLM / VLM)   │                     │    Tracking (Faces, Motion)     │
└────────────────┬────────────────┘                     └────────────────┬────────────────┘
                 ▼                                                       ▼
┌─────────────────────────────────┐                     ┌─────────────────────────────────┐
│ 4. Virality Scoring Engine      │                     │ 6. Smart Reframing, Expand &    │
│    (Hook, Flow, Value, Trend)   │                     │    Layouts (9:16, Split, Fit)   │
└────────────────┬────────────────┘                     └────────────────┬────────────────┘
                 └───────────────────────┬───────────────────────────────┘
                                         ▼
                      ┌──────────────────────────────────────┐
                      │    7. Dynamic Subtitle Generation    │
                      │  (Karaoke, AI Emojis, Enhancements)  │
                      └──────────────────┬───────────────────┘
                                         ▼
                      ┌──────────────────────────────────────┐
                      │    8. Interactive Web Studio/Editor  │
                      │ (Text Trimming, AI B-Roll, Dubbing)  │
                      └──────────────────┬───────────────────┘
                                         ▼
                      ┌──────────────────────────────────────┐
                      │    9. Rendering & Export Engine      │
                      │  (MP4 H.264, XML Export, Multi-angle)│
                      └──────────────────┬───────────────────┘
                                         ▼
                      ┌──────────────────────────────────────┐
                      │   10. Publishing & Agentic Flow      │
                      │  (Social Scheduler, API, MCP Tools)  │
                      └──────────────────────────────────────┘
```

---

## 2. Deep-Dive Feature Specifications

### 2.1 Video Ingestion & Stream Normalization
*   **Purpose:** Securely acquire, inspect, validate, and normalize long-form multimedia streams before processing.
*   **Observed Functionality:**
    *   **URL Ingestion:** Direct link resolution for YouTube, Vimeo, Google Drive, Zoom, Rumble, Twitch, StreamYard, Riverside, Facebook, LinkedIn, Twitter/X, and Loom.
    *   **Direct File Upload:** Support for MP4, MOV, WebM, MKV up to 10 GB (API supports up to 30 GB).
    *   **Agent Opus (Audio-to-Video):** Audio file ingestion (MP3, WAV, M4A, FLAC, AAC, Opus) up to 50MB/5mins converted to visual video.
    *   **Length Support:** Up to 10 hours continuous length.
    *   **Integrity Verification:** Handling non-integer frame rates (29.97 fps must be normalized via external tools like YouTube first).
*   **Independent Engineering Requirements:**
    *   Resumable client-side multipart uploads directly to S3-compatible object storage.
    *   `yt-dlp` microservice for compliant public URL downloading with proxy rotation.
    *   FFprobe container validator checking duration, codecs, and framerate.

### 2.2 Transcription & Audio Diarization
*   **Purpose:** Convert speech audio into machine-readable text with millisecond-accurate word-level alignment and speaker separation.
*   **Observed Functionality:**
    *   Support for 25+ languages.
    *   Millisecond-level word timing and Automatic speaker diarization.
    *   User `.srt` file upload to override automated speech recognition.
    *   Automated filler word flagging ("um", "uh") and silence pause identification (Enhance Speech).
*   **Independent Engineering Requirements:**
    *   State-of-the-art ASR: OpenAI Whisper (large-v3) or Deepgram Nova-2 API.
    *   Word-level forced alignment: WhisperX (Wav2Vec2 CTC alignment).
    *   Speaker diarization: PyAnnote.audio 3.1 clustering embeddings.

### 2.3 AI Highlight Detection & Semantic Boundary Segmentation
*   **Purpose:** Analyze transcript and audio-visual cues to locate self-contained, engaging stories.
*   **Observed Functionality:**
    *   Extracts narrative arcs with Hook, Body, and Conclusion.
    *   Duration constraints: User selectable (<30s, 30–60s, 60–90s, Auto).
    *   Timeframe filtering and Keyword / Topic guidance (Co-Pilot).
    *   **ClipAnything:** Multimodal search using natural language prompts across audio-visual events.
*   **Independent Engineering Requirements:**
    *   Transcript chunking with sliding context windows.
    *   LLM-based semantic segmentation (Claude 3.5 Sonnet / GPT-4o) prompted with strict JSON schemas.
    *   Vision-Language Models (VLM) for action clips based on prompt semantics.

### 2.4 Clip Selection & Virality Scoring
*   **Purpose:** Predict social media engagement and viral potential to rank clips.
*   **Observed Functionality:**
    *   Boundary snapping to natural sentence pauses.
    *   Calculates a numerical **Virality Score from 0 to 99**.
    *   Evaluates 4 core pillars: Hook, Flow, Value, and Trend.
*   **Independent Engineering Requirements:**
    *   Boundary-snapping algorithm locking candidate cuts to acoustic silence (Silero VAD).
    *   Composite multi-feature scoring model (heuristics + LLM evaluation of the 4 pillars).
    *   Audio Energy Metric (RMS/pitch) to evaluate the hook.

### 2.5 Face Tracking & Smart Reframing
*   **Purpose:** Dynamically convert landscape (16:9) footage into mobile vertical (9:16) format.
*   **Observed Functionality:**
    *   **Layout Modes:** Fill (dynamic crop), Fit (padded 4:3), Split Screen (2 speakers), Three/Four Layout, Screenshare, Gameplay.
    *   **Active Speaker Tracking:** Continuous face tracking and audio-visual correlation.
    *   **AI Expand (Beta):** Synthetically generates missing background to reframe videos into various aspect ratios.
*   **Independent Engineering Requirements:**
    *   Shot Boundary Detection (PySceneDetect).
    *   Face Detection & Tracking (YOLOv8-face / ByteTrack).
    *   Active Speaker Detection (SyncNet / TalkNet).
    *   Camera motion controller (Kalman filter / EMA).
    *   Generative fill model (e.g., Stable Diffusion Outpainting) for AI Expand.

### 2.6 Animated Captions & Typography Engine
*   **Purpose:** Render high-retention, stylish animated subtitles.
*   **Observed Functionality:**
    *   **Karaoke Highlighting:** Word-by-word color syncing.
    *   **Brand Templates / Presets:** Saved fonts, colors, strokes (Hormozi, MrBeast styles).
    *   **AI Emojis:** Auto-placement of relevant emojis.
*   **Independent Engineering Requirements:**
    *   Time-synced subtitle data structure.
    *   Rendering Engine: Remotion or FFmpeg `ass` filter.
    *   Emoji engine mapped via embeddings to keywords.

### 2.7 Video Studio & Enhancements
*   **Purpose:** Allow creators to quickly adjust and polish AI-generated clips inside a browser editor.
*   **Observed Functionality:**
    *   **Text-Based Trimming:** Deleting transcript words cuts video frames.
    *   **AI B-Roll:** Inserts stock footage, AI-generated images, or AI-generated video based on transcript context.
    *   **AI Video Dubbing:** Translates and dubs video into 25+ languages maintaining original voice.
    *   **Auto SFX & Hooks:** Sound effects and generated title banners.
*   **Independent Engineering Requirements:**
    *   Non-destructive Edit Decision List (EDL) in React/Zustand.
    *   Integrations with Pexels/Pixabay and Generative Video APIs (Runway/Fal.ai) for B-Roll.
    *   Voice cloning and TTS engine (ElevenLabs) for dubbing.

### 2.8 Export Engine & Integrations
*   **Purpose:** Export finalized video assets and manage social distribution.
*   **Observed Functionality:**
    *   **Export to XML:** FCPXML/Premiere XML package with `.srt` and raw media for NLE handoff.
    *   **Social Scheduler:** Built-in calendar posting to YouTube, TikTok, IG, LinkedIn, Facebook, X, Pinterest, Threads, Bluesky.
    *   **Thumbnail Generator:** One-click generation for Shorts/Reels based on video content.
*   **Independent Engineering Requirements:**
    *   FFmpeg with NVENC support on GPU instances.
    *   XML Serializer (`xmlbuilder2`) mapped to Adobe/FCP standards.
    *   OAuth integrations and async scheduling queues (BullMQ) for social dispatch.

### 2.9 Developer & Agentic Ecosystem
*   **Purpose:** Enable programmatic access and LLM orchestration.
*   **Observed Functionality:**
    *   **OpusClip API:** REST endpoints for project creation and webhooks.
    *   **OpusClip MCP Server:** 29 tools via Model Context Protocol for Claude/Cursor, allowing conversational video editing.
*   **Independent Engineering Requirements:**
    *   FastAPI / NestJS REST gateway with JWT/Bearer auth.
    *   MCP Server implementation exposing EDL manipulation, curation retrieval, and export triggers via JSON-RPC.
