# Architecture Decisions (Build vs. Integrate)

**Document Scope:** Technology selection for the MVP, optimizing for speed to market, clean-room independent development, and serverless scalability without owning hardware.

---

## 1. Hardware Strategy: Serverless GPU Computing
**Decision: NO owned GPU hardware for launch.**
*   **Rationale:** Purchasing or renting dedicated GPU instances (AWS g5, EC2) requires high fixed monthly costs regardless of traffic.
*   **Solution:** We will use Serverless GPU platforms like **Modal.com** or **RunPod Serverless**. These platforms spin up containers (e.g., Nvidia A10G / L4) in seconds, execute our Python scripts, shut down immediately, and bill by the exact second of compute used.

---

## 2. Core Subsystem Decisions

### 2.1 Video Ingestion
*   **Decision:** Build (using Open Source)
*   **Tech:** `yt-dlp` (for public URL extraction) and `ffmpeg` (for demuxing/normalization).
*   **Why:** Industry standard, highly robust, no need for a paid API.

### 2.2 Transcription & Diarization
*   **Decision:** Integrate (API) for MVP; Build (WhisperX) for V2.
*   **Tech:** **Deepgram Nova-2 API**.
*   **Why:** Running Whisper large-v3 + PyAnnote on our own GPUs is complex to scale instantly. Deepgram costs ~$0.26 per hour of audio, is incredibly fast (sub-10 seconds for an hour), handles diarization perfectly, and removes GPU queue bottlenecks from our MVP.

### 2.3 AI Highlight Detection & Scoring
*   **Decision:** Integrate (API).
*   **Tech:** **Anthropic Claude 3.5 Sonnet** (via API) or **OpenAI GPT-4o mini**.
*   **Why:** State-of-the-art reasoning. We will pass the chunked transcript (with word indices) to the LLM with a strict Pydantic JSON schema to extract boundaries and generate scores. Building a custom LLM is unnecessary and cost-prohibitive.

### 2.4 Smart Reframing & Face Tracking
*   **Decision:** Build (Custom Serverless Pipeline).
*   **Tech:** Python, **YOLOv8-face** (via Ultralytics), and **OpenCV** (for Kalman filter smoothing and crop coordinate generation).
*   **Why:** No off-the-shelf API provides the exact cinematic panning and active speaker tracking we need. We will deploy this as a serverless function on Modal.com.

### 2.5 Animated Captions & Rendering
*   **Decision:** Build.
*   **Tech:** **Remotion** (React-based video rendering) or **FFmpeg (with ASS filters)**.
*   **Selection:** **Remotion**.
*   **Why:** Remotion allows us to build the captions using React/CSS, which means we can use the exact same React components for the interactive Web Editor preview in the browser *and* the server-side rendering pipeline (via AWS Lambda or Modal). FFmpeg is faster but extremely difficult to style creatively.

---

## 3. Technology Stack Summary
*   **Frontend:** Next.js 14 (App Router), React, TailwindCSS, Zustand.
*   **Backend API:** Node.js (NestJS or Express) or Python (FastAPI). *Selected: TypeScript / Node.js for ecosystem sharing with Remotion.*
*   **Database:** PostgreSQL 16 (hosted on Supabase or Neon).
*   **ORM:** Prisma or Drizzle.
*   **Queues:** Redis + BullMQ.
*   **Object Storage:** Cloudflare R2 (zero egress fees) or AWS S3.
*   **AI Pipelines (GPU):** Modal.com (Serverless Python functions).
*   **LLM API:** Anthropic (Claude 3.5 Sonnet).
*   **Speech-to-Text API:** Deepgram.
*   **Payments:** Stripe.
