# Product Requirements Document (PRD)

**Product Name:** ClipEngine (Working Title)  
**Document Status:** MVP Draft  
**Target:** Independent AI Video Clipping SaaS  

---

## 1. Product Vision & MVP Scope

Our goal is to build an end-to-end, automated pipeline that transforms long-form video content into highly engaging, vertical short-form clips. The Minimum Viable Product (MVP) focuses on a strict subset of features to ensure high quality, stability, and speed to market.

### 1.1 Core MVP Capabilities (In-Scope)
1.  **Video Ingestion:** Direct file upload (MP4/MOV up to 2GB) and public YouTube URL ingestion.
2.  **Transcription & Diarization:** Highly accurate, word-level timestamped transcription with speaker identification.
3.  **AI Highlight Detection:** Semantic analysis of transcripts to find self-contained, engaging stories.
4.  **Clip Scoring & Selection:** Ranking candidate clips based on Hook, Flow, Value, and Trend potential.
5.  **Smart 9:16 Reframing:** Active speaker face tracking to automatically crop and center horizontal videos to vertical.
6.  **Animated Captions:** Word-by-word highlighted subtitles in popular social media styles.
7.  **Video Rendering & Export:** Hardware-accelerated rendering to 1080p MP4.

### 1.2 Out of Scope for MVP
*   Multi-angle / multicam processing.
*   AI Generative B-Roll or image insertion.
*   Direct social media scheduling (users will download MP4s).
*   AI voiceovers or dubbing.
*   Public API or MCP server.

---

## 2. User Workflows

1.  **Project Creation:** User logs in, pastes a YouTube link, or drops an MP4. They select a target clip duration (e.g., 30-60s) and click "Generate".
2.  **Processing State:** User sees a real-time progress indicator (Downloading -> Transcribing -> Analyzing -> Reframing -> Ready).
3.  **Review Dashboard:** User is presented with a gallery of generated clips, sorted by Virality Score.
4.  **Export:** User clicks "Download" to receive a high-quality 1080x1920 MP4 file with burned-in animated captions.

---

## 3. Compliance, Security & Production Requirements

### 3.1 Security & User Data Isolation
*   **Multi-Tenancy:** All database records (Projects, Transcripts, Clips) must enforce strict Row-Level Security (RLS) or mandatory `org_id` / `tenant_id` WHERE clauses on every query.
*   **Storage Isolation:** S3 objects must be path-isolated: `s3://bucket/org_{id}/project_{id}/`. Pre-signed URLs must be short-lived (e.g., 15 minutes) and strictly bound to the requesting user.

### 3.2 Copyright & Fair Use
*   **DMCA Compliance:** The platform must include a clear DMCA takedown process. We will act as a conduit/service provider.
*   **Download Protections:** `yt-dlp` will only be permitted on public, non-DRM, non-paywalled videos. We will not bypass DRM or authentication mechanisms on third-party sites.

### 3.3 Video Retention & Lifecycle
*   **Storage Policy:** To control AWS/Cloudflare R2 costs, raw video files and generated MP4s will be strictly deleted **30 days** after generation for paid users, and **3 days** for free/trial users.
*   **Automated Cleanup:** A daily CRON job will permanently prune expired S3 assets and scrub corresponding DB records.

### 3.4 Rate Limiting & Abuse Prevention
*   **Redis-based Throttling:** Strict rate limits on project creation API endpoints (e.g., max 5 submissions per hour per user) to prevent queue flooding.
*   **Payload Limits:** Enforce 2GB max file size on presigned S3 POST policies.

### 3.5 Payment Processing
*   **Stripe Integration:** Stripe Checkout for subscription management. Webhooks will sync credit balances in our PostgreSQL database.
*   **Credit System:** 1 processed minute = 1 credit. Deducted immediately upon successful ingestion and audio extraction.

### 3.6 Production Monitoring
*   **Observability:** Datadog or Sentry for application error tracking.
*   **Queue Health:** BullMQ UI / Grafana dashboards monitoring queue depth, job failure rates, and GPU worker utilization.
