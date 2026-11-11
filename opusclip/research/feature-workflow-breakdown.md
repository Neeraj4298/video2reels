# OpusClip Feature Workflow Breakdown

**Document Scope:** End-to-end user journeys and data flows for the primary interaction loops within OpusClip, derived from public documentation.

---

## 1. The Standard Clipping Workflow
1.  **Ingestion:** User inputs a public URL (e.g., YouTube) or uploads a local file (MP4/MOV).
2.  **Co-Pilot Configuration (Optional):**
    *   User sets target duration (<30s, 30-60s, 60-90s, Auto).
    *   User restricts the processing timeframe (e.g., "05:00 to 20:00").
    *   User provides keyword filters or a **ClipAnything** natural language prompt (e.g., "Find the funniest moments").
3.  **Processing (Async):** OpusClip transcribes the audio, detects active speakers, tracks faces, reframes to 9:16, generates captions, and isolates highlights.
4.  **Review Dashboard:** User is presented with a gallery of 5–30 clips.
    *   Clips are sorted descending by **Virality Score** (0–99).
    *   Each clip has an Auto Headline (Hook) and a 3-point score rationale.
5.  **Polishing:** User enters the Web Editor to fix typos, adjust caption styles, or trim the clip using text-based editing.
6.  **Delivery:** User clicks Export to render a final MP4 or pushes it directly to the Social Scheduler.

---

## 2. The Professional NLE Hand-off Workflow (Export to XML)
*Required: Pro Plan*
1.  **Curation:** User generates clips using the standard workflow above.
2.  **Export Selection:** Instead of rendering an MP4, the user selects "Export to XML".
3.  **Download:** OpusClip generates a `.zip` package.
4.  **Post-Production:** 
    *   User opens Adobe Premiere Pro or DaVinci Resolve.
    *   User imports the `.xml` file.
    *   The timeline populates with the raw video cut exactly to the AI's highlight boundaries, with auto-reframe spatial data preserved as motion keyframes.
    *   *Note:* Captions are NOT editable in the XML timeline directly; the user imports the provided `.srt` file if custom caption manipulation is required in the NLE.

---

## 3. The Agentic Workflow (Model Context Protocol - MCP)
1.  **Setup:** Developer/User connects the OpusClip MCP server (`mcp.opus.pro/mcp`) to an agent like Claude Code or Cursor.
2.  **Authentication:** The first tool call triggers a browser-based OAuth sign-in flow (no API keys required).
3.  **Conversational Prompt:** User types in their IDE: "Take this podcast URL, find the segment where they talk about AI agents, apply my 'TechVlog' brand template, and schedule it to my X account for tomorrow."
4.  **Agent Execution:** 
    *   The LLM calls `submit_video_project` with the URL and parameters.
    *   The LLM polls `get_project_status`.
    *   Once ready, the LLM calls `list_curated_clips`, filters for the desired content.
    *   The LLM calls `schedule_social_post`.
5.  **Result:** The entire video production and scheduling pipeline is completed headlessly via the chat interface.

---

## 4. The Generative Workflow (Audio-to-Video / Agent Opus)
1.  **Input:** User uploads an audio file (e.g., a 2-minute podcast snippet or a song) up to 50MB / 5 mins.
2.  **Parameter Tuning:** User selects a generation mode (Standard, Premium, Ultra) affecting visual complexity.
3.  **Generation:** The AI generates synthetic B-roll, visualizers, and scenes matched to the semantic content and rhythm of the audio track.
4.  **Export:** A complete video is rendered without the user ever providing source footage.
