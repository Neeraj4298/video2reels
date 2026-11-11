# Development Plan & Implementation Phases

**Document Scope:** A pragmatic, phased development roadmap mapping the architecture into executable sprints with measurable acceptance criteria.

---

## Phase 1: Foundation & Data Pipelines (Week 1)
**Focus:** Infrastructure, Auth, and reliable video ingestion.
*   **Tasks:**
    *   Set up Next.js 14 frontend, Node.js API, and PostgreSQL (Supabase/Neon).
    *   Implement user authentication and Stripe skeleton.
    *   Setup Cloudflare R2 bucket and S3 API clients.
    *   Deploy Redis and configure BullMQ `video_queue`.
    *   Implement `yt-dlp` and `ffmpeg` worker for downloading and audio extraction.
*   **Acceptance Criteria:** A user can submit a YouTube URL via the API, the system downloads it, extracts a 16kHz WAV, uploads both to R2, and marks the DB project as `AUDIO_EXTRACTED`.

---

## Phase 2: Intelligence & Curation (Week 2)
**Focus:** Speech-to-text and LLM highlight extraction.
*   **Tasks:**
    *   Integrate Deepgram Nova-2 API for transcription and diarization.
    *   Write Python/Node scripts to chunk the transcript JSON.
    *   Design and iterate the Claude 3.5 Sonnet prompt (Hook, Body, Payoff, Scoring).
    *   Implement boundary-snapping logic (aligning LLM word indices to exact timestamps).
*   **Acceptance Criteria:** System processes the extracted WAV, generates an accurate JSON transcript, and populates the DB with 5–10 valid candidate `clips` featuring headlines, scores, and correct start/end times.

---

## Phase 3: Vision & Smart Reframing (Week 3)
**Focus:** Converting horizontal video to vertical using serverless GPUs.
*   **Tasks:**
    *   Set up a Modal.com Python environment with OpenCV and Ultralytics (YOLOv8-face).
    *   Implement active speaker tracking script.
    *   Implement 1D Kalman Filter / Exponential Moving Average to smooth camera pan coordinates.
    *   Expose Modal function as a web endpoint callable by the Node orchestrator.
*   **Acceptance Criteria:** The system successfully passes a clip time-range to Modal; Modal downloads the segment, tracks the face, and returns an array of smooth 9:16 crop coordinates `(x, y, w, h)`.

---

## Phase 4: Subtitles & Rendering (Week 4)
**Focus:** Putting it all together into a final MP4.
*   **Tasks:**
    *   Set up a Remotion project (or FFmpeg complex filtergraph) to handle rendering.
    *   Map word-level timestamps to subtitle animations (Karaoke highlight style).
    *   Implement the crop logic in the renderer using the trajectory array from Phase 3.
    *   Deploy rendering worker.
*   **Acceptance Criteria:** The system automatically renders a 1080x1920 MP4 video where the speaker is centered, animated captions are perfectly synced to the audio, and the file is uploaded to R2.

---

## Phase 5: Web UI, Billing & Launch (Week 5)
**Focus:** User experience and commercialization.
*   **Tasks:**
    *   Build the Dashboard UI: Project list, upload modal, real-time progress bar.
    *   Build the Clip Review UI: Gallery of rendered clips with their Virality Scores and download buttons.
    *   Wire up Stripe webhooks for credit purchasing and monthly subscriptions.
    *   Implement daily CRON jobs for 3-day / 30-day data retention cleanup.
*   **Acceptance Criteria:** A non-technical user can sign up, purchase credits via Stripe, paste a podcast link, wait 5 minutes, and download a polished viral short directly from the web browser.
