# OpusClip Complete Feature Catalog (Post-Audit Verified)

**Document Scope:** Exhaustive, verified catalog of every publicly documented feature, module, and capability within the OpusClip product ecosystem, following the final product coverage audit.

---

## 1. Core Clipping & Curation Engines

### 1.1 AI Producer (`producer.opus.pro`)
*   **Problem Solved:** Slashes the hours required to edit and assemble raw talking-head footage into a polished video.
*   **Functionality:** An autonomous editing agent that performs rough cuts, Detect Retakes (removing false starts and repeated takes), dead pause trimming, B-roll insertion, music scoring with auto-ducking, auto SFX, and animated captioning. It outputs a human-readable **Edit Log** explaining every decision, and accepts conversational revision commands (via chat or MCP).
*   **Inputs:** Raw video recording (URL or file).
*   **Outputs:** Finished short video + decision reasoning log.
*   **Plan Restrictions:** Accessible via Pro and standalone portal.

### 1.2 ClipAnything (Multimodal Prompt Clipping)
*   **Problem Solved:** Finding non-verbal actions, visual events, or specific moments in videos that standard speech-to-text models miss (e.g. gaming, sports, vlogs).
*   **Functionality:** Multimodal model analyzing video pixels, acoustic events (laughter, cheers), and sentiment. Users supply natural language search prompts (e.g. "Find every goal celebration").
*   **Inputs:** Text prompt + video.
*   **Outputs:** Filtered, scored clips matching prompt semantics.

### 1.3 Virality Score Engine (0–99)
*   **Problem Solved:** Predicts which video segments will generate the highest social retention and shares.
*   **Functionality:** Evaluates clips across 4 core pillars: **Hook** (first 3–5s audio energy/curiosity), **Flow** (narrative cohesion), **Value** (actionable insight), and **Trend** (topic relevance). Generates 3-point score justifications.
*   **Plan Restrictions:** Starter and Pro plans only.

---

## 2. Visual Layouts & Computer Vision

### 2.1 AI Reframe (Auto & Manual)
*   **Problem Solved:** Translates widescreen 16:9 video to vertical 9:16 for mobile feeds.
*   **Functionality:** Face detection and active speaker tracking keeping the subject centered.
*   **Layout Modes:** Fill (dynamic crop), Fit (padded 4:3), Split (2 speakers stacked), Three/Four (panel grid), Screenshare (50/50), Gameplay (30/70).
*   **Constraint:** Multi-speaker layouts require all subjects to be present in the *same* source video frame.

### 2.2 AI B-Roll
*   **Problem Solved:** Covers jump cuts and illustrates abstract concepts to elevate retention.
*   **Functionality:** Identifies transcript placement spots automatically or via manual selection.
*   **Asset Modes:** Stock Video, AI-Generated Images, and Generative AI Video (Hailuo 3 / Seedance 2.5).
*   **Plan Restrictions:** Starter: Stock & AI Images only; Pro: Full AI Video B-Roll.

### 2.3 AI Expand (Opus Labs Beta)
*   **Problem Solved:** Converting aspect ratios without cropping out critical background elements.
*   **Functionality:** Generative outpainting expanding scene edges into Portrait, Landscape, Square, or Cinematic ratios.
*   **Plan Restrictions:** Dynamically consumes credits based on model, resolution, and clip duration.

### 2.4 Multi-Angle Video Processing (Opus Labs)
*   **Problem Solved:** Automates multi-camera switching for podcasts and panel interviews.
*   **Inputs:** Up to 4 GB file size, max 1 hour duration.
*   **Outputs:** 480p or 720p dynamically switched camera cuts. Consumes credits per completed shot.

---

## 3. Speech, Subtitles & Audio Engineering

### 3.1 AI Animated Captions
*   **Problem Solved:** Retains viewers watching on mute across TikTok, Reels, and Shorts.
*   **Functionality:** Word-level karaoke highlighting (Hormozi, MrBeast, Minimal presets), AI Emoji injection, keyword emphasis.
*   **Customization:** Font family (custom TTF/OTF on Pro), text case, color, stroke, drop shadow, corner radius, frame width, on-screen drag-and-drop.

### 3.2 AI Voiceover (Text-to-Speech / AI Hook)
*   **Problem Solved:** Adding high-energy audio hooks, narration, or commentary to clips.
*   **Functionality:** Synthesizes speech from a text script (up to 6,000 characters) across 20+ preset voices. Includes Tone Stability control and original audio ducking sliders.
*   **Distinction:** Distinct from Dubbing; Voiceover generates new audio from written text rather than translating source speech.

### 3.3 Video Clone & Dubbing (AI Dubbing)
*   **Problem Solved:** Global content distribution in international languages.
*   **Functionality:** Neural voice cloning capturing the source speaker's pitch, timbre, and cadence, combined with translation into 25+ target languages.

### 3.4 Enhance Speech
*   **Problem Solved:** Eliminates room echo, background noise, and leveling inconsistencies.
*   **Functionality:** Studio-grade audio cleanup and volume leveling.
*   **Plan Restrictions:** Disabled on Free and Starter. Included for Pro and Business at **10 free uses per day**.

### 3.5 Censor Curse Words
*   **Problem Solved:** Creating brand-safe and monetizable clips.
*   **Functionality:** Automated profanity detection that bleeps audio and masks subtitle text (`f***`). Available via editor and API/MCP (`opusclip_create_censor_job`).

---

## 4. Web NLE & Precision Editing

### 4.1 In-Browser Multi-Track Web Editor
*   **Problem Solved:** Eliminates need to export to external software for simple trims and overlays.
*   **Controls:** Multi-track timeline supporting up to **5 text overlay layers**, dedicated B-roll tracks, audio tracks, and snap editing (`S`).
*   **Keyboard Shortcuts:** Frame stepping (`->`/`<-`), clip splitting (`D`/`CMD+B`), element deletion (`Delete`), timeline zoom (`+`/`-`), fit-to-screen (`\`), and start/end jumps (`1`/`End`).
*   **Text-Based Editing:** Deleting words in the interactive transcript ripple-trims corresponding video frames.

### 4.2 Brand Kits & Brand Templates
*   **Problem Solved:** Ensures agency and brand consistency across high-volume video pipelines.
*   **Classic Templates (Mobile/API):** Free: 1, Starter: 1, Pro: 2.
*   **New Brand Kits (Web):** Free: 0 custom, Starter: 1, Pro: Up to 4. Manages fonts, logos, intro/outro cards, colors.

### 4.3 Thumbnail Generator & Custom Covers
*   **Problem Solved:** High-CTR thumbnail creation for short-form platforms.
*   **Functionality:** Video frame picker, custom image upload, or automated AI generation via MCP (`opusclip_create_thumbnail_job`).

---

## 5. Publishing, Teams & Professional NLE

### 5.1 Social Scheduler & Content Calendar
*   **Problem Solved:** Manual posting overhead across fragmented social platforms.
*   **Supported:** YouTube, TikTok, Instagram, Facebook Pages, LinkedIn, X (Twitter), Pinterest, Threads, Bluesky.
*   **Features:** Drag-and-drop calendar, automated headline/caption/hashtag generation, YouTube bulk scheduler (Pro).
*   **Surcharge:** Posting to X incurs a **3-credit surcharge per post**.

### 5.2 Team Workspace & Collaboration
*   **Problem Solved:** Shared asset management and resource pooling for teams and agencies.
*   **RBAC Structure:** Owner (billing, plan, invites), Admin (setup, invites), Member (editing, clipping).
*   **Resource Pooling:** Shared credit balance, centralized video library, shared brand kits. Pro includes 2 seats (up to 4); Business unlimited.

### 5.3 Export to XML (Professional NLE Hand-off)
*   **Problem Solved:** Seamless transition to Adobe Premiere Pro and DaVinci Resolve.
*   **Deliverable:** ZIP containing sequence XML (with reframing motion keyframes), original source video, and `.srt` subtitle file.
*   **Plan Restrictions:** Pro Plan and above.

---

## 6. Developer Interfaces & Agentic Suite

### 6.1 Public REST API (`api.opus.pro`)
*   **Endpoints:** 10+ documented endpoints for GCS presigned upload links, project submission, status polling, clip retrieval, transcripts, brand templates, and censor jobs.
*   **Auth:** Bearer Token + Organization ID header; webhooks for completion events.
*   **Plan Restrictions:** Gated to Pro (Beta), Max, and Business plans.

### 6.2 Model Context Protocol (MCP) Suite (`mcp.opus.pro/mcp`)
*   **Architecture:** Remote streamable HTTP MCP server (version 0.4.0) with OAuth 2.1 authentication; npm launcher `@opusclip/mcp`.
*   **Tool Catalog (37 Tools):**
    *   *Read Tools (15):* `opusclip_whoami`, `opusclip_get_usage`, `opusclip_list_projects`, `opusclip_list_clips`, `opusclip_describe_clip`, `opusclip_list_collections`, `opusclip_list_clips_in_collection`, `opusclip_list_brand_templates`, `opusclip_list_social_accounts`, `opusclip_list_scheduled_posts`, `opusclip_get_transcript`, `opusclip_get_social_copy_job`, `opusclip_analyze_video`, `opusclip_list_pinterest_boards`, `opusclip_preview_clips`.
    *   *Write Tools (14):* `opusclip_submit_project`, `opusclip_create_upload_link`, `opusclip_edit_clip`, `opusclip_create_censor_job`, `opusclip_share_project`, `opusclip_create_collection`, `opusclip_add_clip_to_collection`, `opusclip_export_clip`, `opusclip_export_collection`, `opusclip_duplicate_clip`, `opusclip_create_social_copy_job`, `opusclip_create_post_task`, `opusclip_schedule_publish`, `opusclip_unschedule_publish`.
    *   *Generative Media Tools (8):* `opusclip_create_thumbnail_job`, `opusclip_get_thumbnail_job`, `opusclip_create_speech_job`, `opusclip_create_music_job`, `opusclip_create_video_job`, `opusclip_get_media_generation_job`, `opusclip_analyze_reference_media`, `opusclip_get_reference_analysis`.

### 6.3 Inspiration Gallery Recipes
*   **Functionality:** Copy-paste prompt templates for LLM agents (Claude Code, Cursor) orchestrating multi-step tasks: Three-way hook testing, Sponsor-safe profanity purging, Album art release palette synchronization, and Fan comment timestamp clipping.
