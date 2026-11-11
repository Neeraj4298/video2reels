# OpusClip Product Research & System Analysis

**Status:** Completed (Extended Investigation)  
**Domain:** https://www.opus.pro/  
**Methodology:** Non-intrusive static public reconnaissance, verified documentation inspection, public pricing/feature matrices, public API and MCP references.  
**Constraint Compliance:** Only publicly accessible, authorized content was inspected. No private endpoints, proprietary models, user data, or protected systems were accessed. Observed facts are strictly distinguished from architectural inferences (detailed in `evidence-and-unknowns.md`).

---

## 1. Executive Summary & Brand Positioning

OpusClip (operated by Opusclip Inc.) is positioned as the `#1 AI video clipping and editing tool` designed to automatically transform long-form video footage into short-form, high-engagement video assets at scale.

Beyond simple clipping, OpusClip 3.0/4.0 has evolved into an **Agentic Video Ecosystem**. It now incorporates multimodal prompting (ClipAnything), generative AI (Agent Opus, AI B-Roll, AI Expand), and developer tools (REST API, MCP Server) to fully automate the video post-production pipeline for creators, agencies, and LLM-driven agents.

---

## 2. Product Ecosystem & Navigation Architecture

Based on public site indexing at `opus.pro` and `help.opus.pro`:

### 2.1 Core Creator Web Application
*   **AI Producer:** The core automated editing agent managing cuts, B-roll, and music.
*   **Clip Curation:** AI highlight detection ranked by a proprietary **Virality Score (0-99)**.
*   **Visual Layouts:** AI Reframe (Fill, Fit, Split, Grid), AI Expand (synthetic outpainting).
*   **Audio/Text:** Animated Captions, Enhance Speech, AI Video Dubbing.
*   **Studio Enhancements:** AI B-Roll (Stock, AI Image, AI Video), Thumbnail Generator, Brand Templates.
*   **Agent Opus (Audio-to-Video):** Generates full videos purely from audio uploads.

### 2.2 Professional & Team Capabilities
*   **Export to XML:** Export sequences, reframing data, and `.srt` files for Adobe Premiere Pro and DaVinci Resolve.
*   **Team Workspace:** Shared credit pools, templates, and collaborative access (2-4 seats on Pro, unlimited on Business).
*   **Social Scheduler:** In-app calendar publishing directly to YouTube, TikTok, IG, LinkedIn, Facebook, X, Pinterest, Threads, Bluesky.

### 2.3 Developer & Agentic Interfaces
*   **OpusClip API:** REST architecture for programmatic uploads and webhook notifications.
*   **OpusClip MCP Server (`mcp.opus.pro/mcp`):** Exposes 29 tools via the Model Context Protocol, allowing AI agents (Claude, Cursor) to drive the OpusClip engine conversationally.
*   **Inspiration Gallery:** Showcase of agentic workflows demonstrating the MCP capabilities.

---

## 3. Supported Input and Output Formats

### 3.1 Inputs
*   **Video Containers:** MP4, MOV, WebM, MKV.
*   **Audio Containers (Agent Opus):** MP3, M4A, WAV, AAC, OGG, Opus, FLAC.
*   **External Subtitles:** `.srt` upload.
*   **Maximum File Size:** Up to 10 GB for standard web uploads; up to 30 GB via API; 4 GB for multi-angle; 500 MB for AI Expand; 50 MB for Audio-to-Video.
*   **Video Length:** Up to 10 hours continuous duration.
*   **Framerate Restriction:** Requires integer frame rates (e.g., 30 fps); 29.97 fps requires pre-processing.

### 3.2 Outputs
*   **Video Containers:** MP4 (H.264 / AAC).
*   **Aspect Ratios:** 9:16, 1:1, 16:9, 4:3, 3:4, 21:9.
*   **Resolution:** Up to 4K UHD (tier dependent).
*   **NLE Timelines:** FCPXML / Premiere Pro XML interchange sequences.

---

## 4. Pricing Architecture & Plan Tiers

*Observed from public `opus.pro/pricing` and help documentation:*

OpusClip uses a unified compute-credit system (1 Credit = 1 Minute of processed video, rounded appropriately).

| Plan | Price | Credit Quota | Key Feature Boundaries |
| :--- | :--- | :--- | :--- |
| **Free** | $0 | 60 credits (Lifetime) | Watermarked, Max 1080p, No manual editor, 3-day storage retention, No Enhance Speech. |
| **Starter** | $15 / mo | 150 credits/mo | No watermark, Full editor, 1 Brand Template, 30-day storage, Basic AI B-Roll (Image/Stock). |
| **Pro** | $29/mo (or $174/yr) | 300 credits/mo | Unlocks full AI B-Roll (Video), Export to XML, Enhance Speech (10/day), Social Scheduler, 2+ team seats, 100GB fixed storage, API access. |
| **Business** | Custom | Custom | 4K support, priority GPU queue, unlimited seats, SSO, SOC 2 Type II, custom fonts, unlimited storage. |

*Surcharges:* Publishing to X (Twitter) costs 3 credits per clip. AI Expand consumes dynamic credits based on resolution and model.

---

## 5. Directory of Technical Specifications

For detailed architectural breakdowns and engineering blueprints required to independently implement this functionality, please refer to:
*   `research/complete-feature-catalog.md`: Exhaustive list of all public features and plan restrictions.
*   `research/feature-workflow-breakdown.md`: End-to-end user journeys for Web, Pro, and Agentic workflows.
*   `research/integrations-and-platforms.md`: Social networks, NLEs, and Developer API/MCP endpoints.
*   `research/plan-restrictions-and-credit-system.md`: Deep dive into credit math, rounding, and expiration rules.
*   `research/evidence-and-unknowns.md`: Distinction between verified public facts and architectural engineering assumptions.
*   `research/feature-inventory.md`: Complete functional mapping of 10 core subsystems.
*   `specifications/technical-architecture.md`: Distributed system topology, database schemas, and microservice definitions.
*   `specifications/mvp-roadmap.md`: Phased engineering delivery plan and risk matrix.
