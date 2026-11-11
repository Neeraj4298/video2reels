# Independent Technical Architecture & Systems Specification

**Target Product:** AI Video Clipping & Social Repurposing SaaS (OpusClip Alternative)  
**Document Classification:** Technical Architecture & System Design Document (TADD)  
**Standard Compliance:** Independent, clean-room implementation architecture adhering strictly to public standards, open-source technologies, and verifiable software engineering patterns.

---

## 1. System Topology & Distributed Architecture

The platform is designed as an asynchronous, event-driven distributed system that decouples I/O-intensive web traffic from compute-intensive audio/video AI pipelines and GPU rendering.

```
                                      [ Web / Mobile Clients ]
                                      [ MCP / AI Agents / IDEs]
                                                 │
                                                 ▼
                                     ┌───────────────────────┐
                                     │   API Gateway / Auth  │
                                     │   (FastAPI / Node.js) │
                                     └───────────┬───────────┘
                                                 │
                   ┌─────────────────────────────┼─────────────────────────────┐
                   ▼                             ▼                             ▼
       ┌───────────────────────┐     ┌───────────────────────┐     ┌───────────────────────┐
       │   PostgreSQL 16 DB    │     │   Redis Event Broker  │     │ S3 Object Storage     │
       │   (Prisma / Drizzle)  │     │   & BullMQ / Celery   │     │ (Uploads/Assets/Renders)
       └───────────────────────┘     └───────────┬───────────┘     └───────────────────────┘
                                                 │
         ┌───────────────────┬───────────────────┼───────────────────┬───────────────────┐
         ▼                   ▼                   ▼                   ▼                   ▼
┌─────────────────┐ ┌─────────────────┐ ┌─────────────────┐ ┌─────────────────┐ ┌─────────────────┐
│ Worker 1:       │ │ Worker 2:       │ │ Worker 3:       │ │ Worker 4:       │ │ Worker 5:       │
│ Ingestion &     │ │ Transcription & │ │ Vision, Face &  │ │ Highlight &     │ │ Remotion /      │
│ Demuxing (CPU)  │ │ Alignment (GPU) │ │ Reframing (GPU) │ │ Scoring (LLM)   │ │ FFmpeg NVENC    │
└─────────────────┘ └─────────────────┘ └─────────────────┘ └─────────────────┘ └─────────────────┘
```

### 1.1 Service Responsibilities
1.  **API Gateway & Web Server (FastAPI / NestJS):**
    *   Authentication (OAuth2, JWT, API Keys).
    *   Project lifecycle management and billing/credit accounting.
    *   Presigned multipart S3 upload link generation.
    *   WebSocket gateway for real-time processing progress streaming.
    *   Model Context Protocol (MCP) server endpoint (`/mcp`) supporting external AI agent tools.
2.  **Job Orchestrator (BullMQ / Celery + Redis):**
    *   Manages job state machine: `QUEUED` -> `DOWNLOADING` -> `INGESTED` -> `TRANSCRIBING` -> `ANALYZING_VISION` -> `CURATING_CLIPS` -> `READY_FOR_PREVIEW` -> `RENDERING` -> `COMPLETED`.
    *   Enforces priority queues (Enterprise > Pro > Free).
    *   Handles retry logic with exponential backoff and dead-letter queues.
3.  **Specialized Worker Pools:**
    *   **Ingestion Pool (CPU-optimized):** Handles `yt-dlp` stream pulls, container validation, audio extraction, and audio loudness normalization.
    *   **ASR & Diarization Pool (GPU-optimized - Nvidia T4 / A10G):** Executes WhisperX for word-level speech recognition and PyAnnote for speaker clustering.
    *   **Computer Vision Pool (GPU-optimized - Nvidia A10G / RTX 4090):** Executes PySceneDetect, YOLOv8-face tracking, and SyncNet active speaker audio-visual alignment.
    *   **LLM Curation & Scoring Pool (I/O & API-optimized):** Asynchronously dispatches transcript payloads to LLM APIs (Anthropic Claude 3.5 Sonnet / OpenAI GPT-4o / vLLM self-hosted Llama 3) for highlight detection, hook generation, and virality scoring.
    *   **Rendering & Compositing Pool (GPU-accelerated NVENC / Remotion):** Renders vertical 9:16 video clips with dynamic animated typography, layout splits, and audio mixing.

---

## 2. Feature-by-Feature Technical Specifications

---

### Feature 1: Video Ingestion & Stream Normalization

#### Expected Inputs
*   **Case A (Direct File):** Binary multipart upload (MP4, MOV, WebM, MKV), file sizes up to 10 GB, durations 10s to 10 hours.
*   **Case B (External URL):** Public HTTPS URL string (YouTube, Vimeo, Twitch, Google Drive, Loom, Zoom recording).

#### Expected Outputs
*   Canonical raw media file stored in S3: `s3://bucket/projects/{project_id}/raw_source.mp4`.
*   Standardized audio track: `s3://bucket/projects/{project_id}/audio_16k_mono.wav` (16 kHz, 16-bit PCM, single channel).
*   Media metadata manifest JSON:
    ```json
    {
      "duration_seconds": 3614.25,
      "width": 1920,
      "height": 1080,
      "fps": 30.0,
      "video_codec": "h264",
      "audio_codec": "aac",
      "audio_sample_rate": 48000,
      "audio_channels": 2,
      "bitrate_kbps": 4500
    }
    ```

#### Possible Independent Implementation
1.  **URL Extraction:** Use `yt-dlp` encapsulated in a containerized worker. Use Python `subprocess` with timeout and proxy rotation if necessary for public platforms.
    ```bash
    yt-dlp -f "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best" \
           --merge-output-format mp4 \
           --max-filesize 10G \
           -o "/tmp/{project_id}/raw.mp4" "{video_url}"
    ```
2.  **Container & Stream Probe:** Execute `ffprobe -v quiet -print_format json -show_format -show_streams`. Validate that video and audio streams exist, non-zero duration, and valid dimensions.
3.  **Audio Extraction & Normalization:**
    ```bash
    ffmpeg -y -i raw.mp4 -vn -af "loudnorm=I=-16:TP=-1.5:LRA=11" -ar 16000 -ac 1 -c:a pcm_s16le audio_16k_mono.wav
    ```
4.  **Framerate Normalization:** If VFR (Variable Frame Rate) or non-integer framerate (e.g., 29.97 fps) is detected, flag for CFR conversion or pass `-vsync cfr -r 30` during segment extraction.

#### Required Technologies
*   `yt-dlp` (Python CLI / library)
*   `ffmpeg` 6.1+ / `ffprobe`
*   `boto3` / `@aws-sdk/client-s3` (Multipart upload)
*   Python 3.11 / FastAPI

#### Technical Unknowns & Edge Cases
*   *Rate limiting / IP blocking* on major video platforms during high volume. Mitigation: Residential proxy pool or encourage direct file uploads.
*   *Live streams or active premieres:* Ingestion must detect if a video is still streaming and reject with `VIDEO_CURRENTLY_LIVE` until finalized.
*   *Multi-track audio:* Zoom and podcast recordings often have separate tracks for host and guest. Solution: Inspect audio stream count; if multiple audio tracks exist, mix down or preserve individual tracks for diarization.

#### Testing Strategy
*   **Unit Tests:** Test `ffprobe` JSON parsing with mock outputs representing corrupt files, audio-only files, extreme aspect ratios (32:9), and non-standard framerates.
*   **Integration Tests:** End-to-end download test on public Creative Commons YouTube videos, Vimeo links, and direct S3 presigned uploads.
*   **Benchmark:** Verify processing throughput: 1-hour 1080p video ingestion, probe, and audio extraction completed under 90 seconds.

---

### Feature 2: Transcription & Audio Diarization

#### Expected Inputs
*   Normalized 16 kHz mono WAV file (`audio_16k_mono.wav`).
*   Optional user parameters: `language_code` (e.g. `en`, `es`, `auto`), `custom_vocabulary` (`["SaaS", "Kubernetes", "OpusClip"]`), user-provided `.srt` file.

#### Expected Outputs
*   Hierarchical transcript JSON containing word-level timestamps and speaker labels:
    ```json
    {
      "language": "en",
      "speakers": ["SPEAKER_00", "SPEAKER_01"],
      "segments": [
        {
          "id": 0,
          "speaker": "SPEAKER_00",
          "start": 0.00,
          "end": 3.42,
          "text": "The single biggest mistake founders make is ignoring distribution.",
          "words": [
            {"word": "The", "start": 0.00, "end": 0.18, "confidence": 0.98},
            {"word": "single", "start": 0.20, "end": 0.54, "confidence": 0.99},
            {"word": "biggest", "start": 0.56, "end": 0.92, "confidence": 0.99},
            {"word": "mistake", "start": 0.94, "end": 1.35, "confidence": 0.99},
            {"word": "founders", "start": 1.40, "end": 1.88, "confidence": 0.97},
            {"word": "make", "start": 1.90, "end": 2.15, "confidence": 0.99},
            {"word": "is", "start": 2.20, "end": 2.38, "confidence": 0.98},
            {"word": "ignoring", "start": 2.42, "end": 2.85, "confidence": 0.99},
            {"word": "distribution.", "start": 2.88, "end": 3.42, "confidence": 0.99}
          ]
        }
      ]
    }
    ```

#### Possible Independent Implementation
1.  **Pipeline:** Use `WhisperX`, which executes in three stages:
    *   **Stage A (ASR):** Transcribe with `faster-whisper` (CTranslate2 implementation of Whisper large-v3) with VAD filtering (Silero VAD) to eliminate silence hallucinations.
    *   **Stage B (Phoneme Forced Alignment):** Align transcribed text tokens to audio frames using Wav2Vec2 CTC models to achieve millisecond precision per word.
    *   **Stage C (Diarization):** Run `pyannote.audio` pipeline (`pyannote/speaker-diarization-3.1`) on the audio to extract speaker turn intervals; intersect speaker turns with word timestamps.
2.  **Fallback / Cloud Alternative:** Deepgram Nova-2 API (`deepgram.listen.prerecorded`) configured with `diarize=true`, `punctuate=true`, `utterances=true`, `smart_format=true`.

#### Required Technologies
*   `faster-whisper` + `WhisperX`
*   `pyannote.audio` 3.1 (PyTorch)
*   `silero-vad`
*   Nvidia GPU (CUDA 12.x, minimum 8 GB VRAM)

#### Technical Unknowns & Edge Cases
*   *Overlapping speech:* When two speakers talk simultaneously, standard diarization merges or clips words. WhisperX handles primary speaker; PyAnnote overlap detection flags overlapping speech regions.
*   *Heavy background music / noise:* Degrades transcription accuracy. Mitigation: Pre-process with speech separation (e.g. Demucs / DeepFilterNet) if SNR (Signal-to-Noise Ratio) is low.

#### Testing Strategy
*   **Benchmark:** Measure Word Error Rate (WER) and Speaker Diarization Error Rate (DER) against LibriSpeech and VoxCeleb test sets. Target: WER < 5% on clear English audio; diarization accuracy > 92%.
*   **Unit Tests:** Validate alignment parser output matches word timing constraints ($t_{\text{start}} < t_{\text{end}}$ strictly monotonic).

---

### Feature 3 & 4: AI Highlight Detection, Clip Selection & Virality Scoring

#### Expected Inputs
*   Full transcript with word timestamps and speaker labels.
*   Curation parameters: `target_duration` (e.g. `30-60`), `topic_keywords`, `user_prompt` (if ClipAnything mode), `min_clips` (default 5), `max_clips` (default 20).
*   Audio RMS loudness curve (sampled every 100ms).

#### Expected Outputs
*   Array of ranked clip candidates:
    ```json
    {
      "clips": [
        {
          "clip_id": "clip_01",
          "start_time": 142.15,
          "end_time": 194.80,
          "duration": 52.65,
          "headline": "Why 99% of Startups Fail at Distribution",
          "hook_sentence": "The single biggest mistake founders make is ignoring distribution.",
          "summary": "Speaker explains the difference between building product and building channels.",
          "virality_score": 93,
          "score_breakdown": {
            "hook": 95,
            "flow": 92,
            "value": 94,
            "trend": 88
          },
          "score_reasons": [
            "Strong provocative opening question that triggers curiosity.",
            "High energy delivery in the first 5 seconds.",
            "Self-contained actionable advice with clear resolution."
          ],
          "start_word_index": 450,
          "end_word_index": 598
        }
      ]
    }
    ```

#### Possible Independent Implementation
1.  **Chunking & Boundary Search:**
    *   Convert transcript into timestamped sentence blocks.
    *   Create sliding windows of 1500–2500 words with 300-word overlaps.
2.  **LLM Highlight Discovery:**
    *   Submit windowed transcript to an LLM (Claude 3.5 Sonnet / GPT-4o) using structured outputs (JSON schema mode).
    *   Prompt instructs the model to identify self-contained narrative units with an explicit Hook (first 3s), Body (context/example), and Conclusion (takeaway/climax).
    *   Strict boundary constraint: Start and end must coincide with sentence boundaries; no dangling dependent clauses ("Because...", "Which means...").
3.  **Boundary Snapping (VAD Alignment):**
    *   Query Silero VAD around the LLM's suggested `start_time` ($\pm 1.5\text{s}$) to find the preceding natural acoustic pause.
    *   Snap `start_time` to silence start and `end_time` to silence end to ensure no audible word truncations.
4.  **Multi-Pillar Virality Scoring Algorithm:**
    *   **Hook Score ($S_{\text{hook}}$):**
        *   Text analysis: Curiosity gap detection, presence of interrogatives, negative superlatives ("biggest mistake", "never do this"), and sentiment polarity shift.
        *   Audio analysis: Measure RMS energy ratio: $\frac{\text{RMS}(0\text{s} \to 3\text{s})}{\text{RMS}_{\text{mean}}}$. High opening energy boosts $S_{\text{hook}}$.
    *   **Flow Score ($S_{\text{flow}}$):** Measures narrative completeness. Check if conclusion answers premise. Penalize sudden topic shifts.
    *   **Value Score ($S_{\text{value}}$):** Information density score: Ratio of substantive nouns and action verbs vs. filler words; actionable takeaway rating.
    *   **Trend Score ($S_{\text{trend}}$):** Semantic similarity (via embeddings) against current high-performing social media topics.
    *   **Formula:**
        $$\text{ViralityScore} = \text{clamp}\left(0.35 \cdot S_{\text{hook}} + 0.25 \cdot S_{\text{flow}} + 0.25 \cdot S_{\text{value}} + 0.15 \cdot S_{\text{trend}}, 0, 99\right)$$

#### Required Technologies
*   Anthropic Claude 3.5 Sonnet API or OpenAI GPT-4o API (or self-hosted vLLM Mistral-Large / Llama-3-70B)
*   Pydantic / Instructor for strict JSON schema enforcement
*   `librosa` / `scipy` for audio RMS and pitch trajectory calculation
*   `sentence-transformers` for embedding similarity

#### Technical Unknowns & Edge Cases
*   *Monotone or low-energy speakers:* May cause algorithm to undervalue highly insightful technical lectures. Solution: Provide genre selection (e.g., "Educational / Technical" vs. "Entertainment / Viral Shorts").
*   *Hallucinated timestamps by LLM:* Mitigation: Never allow the LLM to output arbitrary float timestamps; LLM selects exact `start_word_index` and `end_word_index` from the provided input array, and the backend maps them to ground-truth WhisperX timestamps.

#### Testing Strategy
*   **Golden Dataset:** Curate 50 known viral TikTok/Reels clips from public podcasts (e.g. Lex Fridman, Joe Rogan, Diary of a CEO). Measure Recall: Does the algorithm select the exact 45-second segment that humans chose? Target: > 80% overlap.
*   **Unit Tests:** Validate score bounds ($0 \le \text{Score} \le 99$) and verify boundary snapping never cuts across word boundaries.

---

### Feature 5 & 6: Face Tracking, Active Speaker Detection & Smart Reframing

#### Expected Inputs
*   Source video file.
*   Candidate clip time intervals (`start_time`, `end_time`).
*   Selected layout mode (`FILL`, `FIT`, `SPLIT_2`, `SCREENSHARE`, `GAMEPLAY`).
*   Target aspect ratio: `9:16` ($1080 \times 1920$).

#### Expected Outputs
*   Reframing coordinate trajectory file (JSON / binary track):
    ```json
    {
      "layout": "FILL",
      "target_width": 1080,
      "target_height": 1920,
      "keyframes": [
        {"timestamp": 0.00, "crop_x": 420, "crop_y": 0, "crop_w": 1080, "crop_h": 1920, "speaker_id": "SPEAKER_00"},
        {"timestamp": 0.50, "crop_x": 428, "crop_y": 0, "crop_w": 1080, "crop_h": 1920, "speaker_id": "SPEAKER_00"},
        {"timestamp": 4.20, "crop_x": 1100, "crop_y": 0, "crop_w": 1080, "crop_h": 1920, "speaker_id": "SPEAKER_01"}
      ]
    }
    ```

#### Possible Independent Implementation
1.  **Shot Boundary Detection:** Run PySceneDetect (`ContentDetector(threshold=27.0)`). Identify hard cuts. Reframing camera MUST jump instantaneously on scene cuts rather than panning.
2.  **Face Detection & Tracking:**
    *   Sample video frames at 10 fps.
    *   Run YOLOv8-face or MediaPipe Face Detection to get bounding boxes $[x, y, w, h]$ and facial landmarks (eyes, nose, mouth).
    *   Track identities across frames using ByteTrack.
3.  **Active Speaker Detection (ASD):**
    *   Extract audio Mel-spectrogram for the frame window.
    *   Extract lip landmark coordinates and optical flow vectors around the mouth.
    *   Compute cross-correlation or run SyncNet to determine which face's mouth motion synchronizes with audio speech energy.
    *   When Speaker A finishes and Speaker B speaks, transition camera to Speaker B.
4.  **Camera Planning & Motion Smoothing:**
    *   Calculate optimal 9:16 window centered horizontally on the active speaker: $x_{\text{target}} = x_{\text{face}} + \frac{w_{\text{face}}}{2} - \frac{W_{\text{crop}}}{2}$.
    *   Apply a 1D Kalman filter or Exponential Moving Average (EMA) ($\alpha = 0.15$) to prevent trembling or abrupt camera movements while the speaker gestures.
    *   If speaker moves beyond a threshold margin (deadband zone of 50px), initiate smooth cubic spline camera pan over 0.4s.
5.  **Multi-Layout Compositing Engine:**
    *   **Split Layout (2 Speakers):** Detect 2 active faces in the 16:9 source. Crop Speaker 1 to $1080 \times 960$ (top), crop Speaker 2 to $1080 \times 960$ (bottom).
    *   **Fit Layout:** Scale original 16:9 into center ($1080 \times 608$), generate background by scaling to $1080 \times 1920$ with `boxblur=30:30`, and overlay center video.

#### Required Technologies
*   OpenCV 4.9+
*   `PySceneDetect`
*   `ultralytics` (YOLOv8-face)
*   `filterpy` (Kalman Filtering)
*   PyTorch (SyncNet / TalkNet ASD model)

#### Technical Unknowns & Edge Cases
*   *Speaker turns head completely away from camera:* Face detector loses bounding box. Solution: Fall back to upper-body bounding box (YOLOv8 pose) or hold last known camera crop position until face re-enters.
*   *Both speakers talking at once in split mode:* Keep both active; do not jump back and forth rapidly (hysteresis filter: minimum 1.5s hold time on a speaker before switching).

#### Testing Strategy
*   **Synthetic Test Suite:** Videos with rapid left-to-right moving subjects, multi-speaker interview podcasts, and presentation screen shares.
*   **Metrics:** Camera jitter metric (standard deviation of second-order derivative of crop position); Active Speaker Accuracy compared against manual speaker timeline.

---

### Feature 7: Animated Captions & Typography Engine

#### Expected Inputs
*   Word-level transcript segment corresponding to the clip.
*   Style configuration object:
    ```json
    {
      "preset": "HORMOZI_BOLD",
      "font_family": "Montserrat-Black",
      "font_size": 72,
      "text_case": "UPPERCASE",
      "primary_color": "#FFFFFF",
      "highlight_color": "#FFD700",
      "stroke_color": "#000000",
      "stroke_width": 12,
      "shadow_offset": [4, 4],
      "max_words_per_line": 3,
      "position_y": 0.75,
      "enable_ai_emoji": true
    }
    ```

#### Expected Outputs
*   Rendered subtitle stream (either pre-rendered Alpha MOV / WebM overlay or ASS subtitle script or Remotion composition).
*   ASS Subtitle Format Example:
    ```
    [Events]
    Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
    Dialogue: 0,0:00:01.24,0:00:01.62,HormoziStyle,,0,0,0,,{\1c&H00D7FF&}MINDSET{\1c&HFFFFFF&} IS EVERYTHING 🧠
    ```

#### Possible Independent Implementation
1.  **Line & Phrase Grouping:**
    *   Group words into high-impact visual phrases (1 to 4 words maximum per frame) according to speech cadence and punctuation.
2.  **AI Emoji Mapping:**
    *   Dictionary lookup table of 2,500 common conversational words to Unicode emojis (e.g. `money` -> 💰, `fire` -> 🔥, `brain` -> 🧠, `idea` -> 💡, `stop` -> 🛑).
    *   For unmapped keywords, run lightweight semantic matching against emoji description embeddings.
3.  **Rendering Approaches:**
    *   **Approach A (Remotion - Modern React Engine):**
        *   Write caption component in React using CSS transform animations, spring physics for word pop, and SVG filters for stroke/shadow.
        *   Headless render via `@remotion/renderer` using Chromium GPU acceleration.
    *   **Approach B (FFmpeg ASS Filter - High Speed Server-Side):**
        *   Generate Advanced SubStation Alpha (`.ass`) file with `{\k<centiseconds>}` karaoke tags.
        *   Pass into FFmpeg `-vf "ass=captions.ass"`. Fastest possible encoding without browser overhead.

#### Required Technologies
*   Remotion (`@remotion/core`, `@remotion/renderer`) OR `libass` / FFmpeg ASS filter
*   Google Fonts library (Montserrat, Anton, Komika Axis, Bebas Neue)
*   Twemoji / Apple Emoji SVG asset set

#### Technical Unknowns & Edge Cases
*   *Emoji rendering in headless Linux:* Standard Linux servers lack native emoji color fonts (Noto Color Emoji). Solution: Embed PNG/SVG emoji sprites directly into the compositing layer rather than relying on system font glyphs.
*   *Rapid speech overflow:* Auctioneer-style fast talking. Solution: Dynamic font-size scaling based on word count per second.

#### Testing Strategy
*   **Visual Regression Testing:** Render 100 test phrases with Playwright / Remotion snapshot testing; compare rendered pixels against golden references.
*   **Timing Synchronization Test:** Verify that caption highlight triggers within $\pm 30\text{ms}$ (1 video frame) of audio acoustic energy onset.

---

### Feature 8: Video Studio & Non-Destructive Text Editor

#### Expected Inputs
*   User edits in the web UI: word deletion, word replacement, timeline trim handles, layout switcher, B-roll insertion coordinates, manual hook text edits.

#### Expected Outputs
*   Updated Edit Decision List (EDL) JSON:
    ```json
    {
      "clip_id": "clip_01",
      "timeline": [
        {"type": "source_cut", "source_start": 142.15, "source_end": 158.40},
        {"type": "b_roll", "source_url": "s3://assets/broll_stock_01.mp4", "duration": 3.5, "timeline_start": 12.0},
        {"type": "source_cut", "source_start": 161.20, "source_end": 194.80}
      ],
      "caption_overrides": {
        "word_idx_452": {"text": "founders", "deleted": false}
      },
      "sfx": [
        {"name": "whoosh.wav", "timestamp": 12.0, "volume": 0.6}
      ]
    }
    ```

#### Possible Independent Implementation
1.  **Frontend Interactive Player:**
    *   Built with React, HTML5 `<video>`, and Web Audio API.
    *   Transcript text synchronized to video `currentTime`.
    *   Selecting words and pressing `Delete` marks `deleted: true` in the local EDL state.
    *   Video player automatically skips over deleted word intervals during playback without re-rendering the video file.
2.  **Filler Word & Silence Cleaner:**
    *   Algorithmic pass scanning word array: Flag any word in `["um", "uh", "er", "ah", "like"]` where duration is short and confidence is high.
    *   Scan silence gaps between words: If $t_{\text{start}}[i+1] - t_{\text{end}}[i] > 1.2\text{s}$, trim silence down to $0.3\text{s}$.
3.  **B-Roll Integration:**
    *   Query Pexels / Pixabay API using keyword extracted from the corresponding sentence.
    *   Allow creator to select clip; add B-roll layer onto timeline spanning desired timestamps.

#### Required Technologies
*   React 18+ / Next.js / TailwindCSS
*   Zustand (State Management for EDL)
*   Web Codecs API / HTML5 Video
*   Pexels / Pixabay API

#### Technical Unknowns & Edge Cases
*   *Audio click/pop on cuts:* Splicing video frames without audio crossfades causes audible acoustic clicks. Solution: Apply a 15ms audio linear crossfade (`afade=t=in:d=0.015,afade=t=out:d=0.015`) on every edit splice point.

#### Testing Strategy
*   **Unit Tests:** Verify EDL compiler correctly computes total duration and preserves monotonic time progression.
*   **Frontend End-to-End Tests:** Playwright tests verifying word selection, delete keypress, and verification that playback skips deleted segment.

---

### Feature 9 & 10: Export Engine & XML NLE Generator

#### Expected Inputs
*   Compiled EDL JSON, caption styling, reframing coordinates, watermark status (based on user tier).
*   Target resolution ($1080 \times 1920$, $720 \times 1280$, or $2160 \times 3840$).

#### Expected Outputs
*   **Standard Deliverable:** Final MP4 video file (H.264 High Profile, Level 4.2, AAC stereo 320 kbps, $1080 \times 1920$, 30/60 fps).
*   **Professional Deliverable:** XML Package (`.zip` containing `timeline.xml`, `captions.srt`, and media assets).

#### Possible Independent Implementation
1.  **FFmpeg Hardware-Accelerated Export Pipeline:**
    *   Construct FFmpeg command utilizing `h264_nvenc` on GPU instances (AWS g4dn / g5):
    ```bash
    ffmpeg -y -ss 142.15 -to 194.80 -i raw_source.mp4 \
           -vf "crop=1080:1920:x='min(max(0, ...), in_w-1080)':y=0, \
                ass=subtitles.ass, \
                drawtext=text='MyBrand':x=w-tw-40:y=40:fontcolor=white@0.5" \
           -c:v h264_nvenc -preset p4 -tune hq -b:v 8M -maxrate 12M -bufsize 16M \
           -c:a aac -b:a 256k \
           output_clip.mp4
    ```
2.  **Adobe Premiere / DaVinci XML Serializer:**
    *   Generate standard Final Cut Pro 7 XML interchange format (`<xmeml version="4">`).
    *   Map video track items, `<clipitem>`, in/out points, and spatial transform parameters (`<effect><name>Basic Motion</name>...<parameter><name>Position</name>...`).
    *   Bundle XML + raw video segment + `.srt` subtitle file into a downloadable `.zip`.

#### Required Technologies
*   FFmpeg with NVENC support
*   `xmlbuilder2` (Node.js) or `xml.etree.ElementTree` (Python)
*   Zip archiving utility (`archiver` / `zipfile`)

#### Technical Unknowns & Edge Cases
*   *Frame accuracy across codecs:* MP4 keyframe (GOP) alignment can cause video freezing if cutting without re-encoding at the cut boundary. Solution: Always re-encode cuts with exact frame timestamps (`-ss` and `-to` after `-i` for frame accuracy).
*   *XML import path mismatches:* NLEs fail to link media if absolute file paths differ. Solution: Use relative file paths within the exported ZIP bundle (`./media/source_clip.mp4`).

#### Testing Strategy
*   **Automated NLE Validation:** Validate exported XML files against Adobe Premiere Pro XML DTD schema.
*   **Encoding Benchmark:** Ensure 60-second 1080p clip renders in under 15 seconds on an Nvidia T4/A10G GPU.

---

## 3. Storage, Database & Data Architecture

### 3.1 Object Storage Hierarchy (S3 / Cloudflare R2)
```
s3://video-saas-storage/
├── tenants/
│   └── {org_id}/
│       ├── projects/
│       │   └── {project_id}/
│       │       ├── raw/
│       │       │   └── source_video.mp4
│       │       ├── audio/
│       │       │   └── normalized_16k.wav
│       │       ├── transcripts/
│       │       │   ├── whisper_raw.json
│       │       │   └── diarized_aligned.json
│       │       ├── vision/
│       │       │   ├── scenes.json
│       │       │   └── speaker_tracks.json
│       │       └── clips/
│       │           └── {clip_id}/
│       │               ├── thumbnail.jpg
│       │               ├── preview.mp4
│       │               ├── final_1080p.mp4
│       │               ├── subtitles.ass
│       │               ├── subtitles.srt
│       │               └── nle_export.zip
```

### 3.2 Relational Database Schema (PostgreSQL 16)

```sql
-- Organizations / Multi-Tenant Boundary
CREATE TABLE organizations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(255) NOT NULL,
    plan_tier VARCHAR(50) NOT NULL DEFAULT 'FREE', -- FREE, STARTER, PRO, BUSINESS
    credits_remaining INT NOT NULL DEFAULT 60,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Users
CREATE TABLE users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id UUID REFERENCES organizations(id) ON DELETE CASCADE,
    email VARCHAR(255) UNIQUE NOT NULL,
    password_hash VARCHAR(255),
    role VARCHAR(50) DEFAULT 'MEMBER',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Video Ingestion Projects
CREATE TABLE projects (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id UUID REFERENCES organizations(id) ON DELETE CASCADE,
    title VARCHAR(255) NOT NULL,
    source_type VARCHAR(50) NOT NULL, -- 'FILE_UPLOAD', 'YOUTUBE_URL', etc.
    source_url TEXT,
    raw_s3_key TEXT NOT NULL,
    duration_seconds FLOAT,
    status VARCHAR(50) NOT NULL DEFAULT 'PENDING',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Transcripts & Word Sequences
CREATE TABLE transcripts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id UUID REFERENCES projects(id) ON DELETE CASCADE,
    language VARCHAR(10) NOT NULL,
    full_text TEXT NOT NULL,
    word_data JSONB NOT NULL, -- Array of {word, start, end, speaker, confidence}
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Generated Video Clips
CREATE TABLE clips (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id UUID REFERENCES projects(id) ON DELETE CASCADE,
    headline VARCHAR(255) NOT NULL,
    hook_sentence TEXT,
    start_time FLOAT NOT NULL,
    end_time FLOAT NOT NULL,
    duration FLOAT NOT NULL,
    virality_score INT NOT NULL,
    score_breakdown JSONB NOT NULL,
    score_reasons JSONB NOT NULL,
    layout_mode VARCHAR(50) DEFAULT 'FILL',
    reframing_data JSONB,
    edl_state JSONB,
    export_s3_key TEXT,
    status VARCHAR(50) DEFAULT 'READY',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);
```

---

## 4. API & Model Context Protocol (MCP) Design

### 4.1 Core REST API Endpoints
*   `POST /api/v1/uploads/presigned-url`: Obtains direct S3 multipart upload links.
*   `POST /api/v1/projects`: Submits project from URL or completed S3 upload.
*   `GET /api/v1/projects/{id}`: Returns project processing status, progress percentage, and stage.
*   `GET /api/v1/projects/{id}/clips`: Lists generated clips with scores and preview URLs.
*   `PATCH /api/v1/clips/{id}/edl`: Updates clip cuts, caption styles, or layout mode.
*   `POST /api/v1/clips/{id}/render`: Initiates high-resolution export render.
*   `POST /api/v1/clips/{id}/export-xml`: Generates NLE Premiere/DaVinci ZIP bundle.

### 4.2 Independent Model Context Protocol (MCP) Tools
To support agentic workflows (compatible with Claude, Cursor, and Gemini CLI), the SaaS exposes an MCP Server at `/mcp` with tools:

1.  `submit_video_project`: Submits a video URL with parameters (target duration, keywords, template).
2.  `get_project_status`: Checks pipeline progression and status events.
3.  `list_curated_clips`: Returns list of clips with Virality Scores, hooks, and timestamps.
4.  `update_clip_captions`: Programmatically modifies subtitle text, styling, or emoji mappings.
5.  `set_clip_reframing`: Sets layout (Fill, Fit, Split) and tracking subjects.
6.  `trigger_clip_export`: Triggers export of a clip to MP4 or XML package.
7.  `schedule_social_post`: Schedules a finalized clip to connected social accounts.
