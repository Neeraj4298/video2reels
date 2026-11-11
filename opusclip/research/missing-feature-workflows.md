# OpusClip Detailed Feature Workflows & API Inventory

**Document Scope:** In-depth end-to-end workflows, interaction models, parameter schemas, and technical mechanics for all newly audited modules and interfaces.

---

## 1. AI Producer Workflow (`producer.opus.pro`)

Unlike standard clipping, which slices an existing long video into excerpts, **AI Producer** is an autonomous video editing agent that finishes raw talking-head footage.

```
[Raw Talking-Head Footage]
          │
          ▼
┌────────────────────────────────────────────────────────┐
│ 1. Ingestion & Rough Cut                               │
│    - Detect Retakes (removes stumbles, false starts)   │
│    - Trims filler words ("um", "uh") & dead pauses     │
└──────────────────────────┬─────────────────────────────┘
                           ▼
┌────────────────────────────────────────────────────────┐
│ 2. Automated Production Pass                           │
│    - Renders animated kinetic captions & keyword pops  │
│    - Contextual B-roll placement (Stock / AI media)    │
│    - Background music selection & auto ducking         │
│    - Auto SFX (whooshes, pops on scene/graphic entry)  │
│    - Auto color correction & eye-contact alignment     │
└──────────────────────────┬─────────────────────────────┘
                           ▼
┌────────────────────────────────────────────────────────┐
│ 3. Edit Log & Reasoning Generation                     │
│    - Emits structured natural language changelog       │
│      justifying each cut, asset choice, and transition │
└──────────────────────────┬─────────────────────────────┘
                           ▼
┌────────────────────────────────────────────────────────┐
│ 4. Conversational Chat Refinement                      │
│    - User instructs agent: "Make captions bigger",     │
│      "Swap B-roll at 0:12", "Change music to lo-fi"    │
└──────────────────────────┬─────────────────────────────┘
                           ▼
┌────────────────────────────────────────────────────────┐
│ 5. Delivery & NLE Hand-off                             │
│    - Direct export to 1080p/4K MP4 or Premiere XML     │
└────────────────────────────────────────────────────────┘
```

---

## 2. AI Voiceover vs. AI Video Dubbing Workflows

### 2.1 AI Voiceover (Text-to-Speech Hook Generator)
*   **Workflow:**
    1.  User opens clip in Editor -> selects **AI Hook / AI Voiceover** on the right sidebar.
    2.  User writes or pastes text script (max 6,000 characters).
    3.  User previews and chooses from **20+ pre-trained AI voices**.
    4.  User sets **Tone Stability** (0.0 to 1.0) and **Original Audio Volume** (ducking slider: 0% to 100%).
    5.  User clicks **Generate AI Hook**.
    6.  The synthetic audio is placed on the audio track at $t = 0.0\text{s}$, ducking the original background audio.

### 2.2 Video Clone & Dubbing (Multilingual Voice Localization)
*   **Workflow:**
    1.  User opens clip in Editor -> selects **AI Enhance** -> **Video Dubbing**.
    2.  User selects target language (Spanish, German, French, Portuguese, Hindi, Japanese, etc. from 25+ options).
    3.  System analyzes source speech to extract acoustic voice embeddings (timbre, pitch, cadences).
    4.  System transcribes, translates, and generates synthesized speech matching the speaker's vocal characteristics in the target language.
    5.  System generates a cloned, dubbed MP4 asset with translated subtitles.

---

## 3. Web Editor Controls & Multi-Track Timeline

### 3.1 Keyboard Shortcuts Map
*   `->`: Step forward 1 frame (1/30 second).
*   `<-`: Step backward 1 frame (1/30 second).
*   `1` or `Home` (Mac: `Fn + Left Arrow`): Jump to timeline start.
*   `End` (Mac: `Fn + Right Arrow`): Jump to timeline end.
*   `D` or `CMD + B`: Split clip at playhead position.
*   `Backspace` or `Delete`: Delete active segment, overlay, or word.
*   `S`: Toggle Snap Editing (magnetic snapping to edit boundaries and playhead).
*   `+` / `-`: Zoom in / out timeline scale.
*   `\`: Fit timeline to screen width.
*   `J` / `K` / `L`: Rewind (2x), Play/Pause, Fast-forward (2x).

### 3.2 Track & Layer Hierarchy
```
┌────────────────────────────────────────────────────────┐
│ Track 1: Text Overlay 1 (Headline / Banner)            │
├────────────────────────────────────────────────────────┤
│ Track 2: Text Overlay 2 (Animated Subtitles / Karaoke) │
├────────────────────────────────────────────────────────┤
│ Track 3: Text Overlays 3–5 (Custom stickers / tags)    │
├────────────────────────────────────────────────────────┤
│ Track 4: B-Roll Video / Image Layer (Overlay with trim)│
├────────────────────────────────────────────────────────┤
│ Track 5: Primary Video Layer (Reframed 9:16 cuts)      │
├────────────────────────────────────────────────────────┤
│ Track 6: Audio Voiceover / SFX / Background Music      │
└────────────────────────────────────────────────────────┘
```

---

## 4. Social Scheduler & Multi-Platform Calendar

### 4.1 Step-by-Step Workflow
1.  **Account Connection:** User connects social accounts via OAuth in Account Settings.
    *   *Supported:* YouTube, TikTok, Instagram (Business/Creator), Facebook (Pages only), LinkedIn, X (Twitter), Pinterest, Threads, Bluesky.
2.  **Clip Dispatch:** In the clip gallery or editor, user clicks **Schedule**.
3.  **Post Composition:**
    *   AI automatically drafts platform-optimized title, description, and hashtags based on transcript semantics.
    *   User selects or customizes thumbnail (frame picker or image upload).
    *   For Pinterest, user selects target `boardId`.
4.  **Calendar Placement:** User picks date and time, or drags the post onto the visual **Social Media Calendar**.
5.  **Bulk Scheduling (Pro, YouTube):** User sets interval (e.g. every 3 hours) and schedules an entire batch of 10 clips in one click.
6.  **Platform Surcharges & Constraints:**
    *   Posting to X costs **3 credits per post**.
    *   Editing a clip in OpusClip *after* scheduling does NOT update the scheduled post; it must be rescheduled.

---

## 5. Team Workspace Roles & Permissions

| Capability / Action | Team Owner | Admin | Member |
| :--- | :---: | :---: | :---: |
| Create Team Workspace & Upload Logo | Yes | No | No |
| Purchase Plans & Add Credit Packs | Yes | No | No |
| Billing & Invoice Management | Yes | No | No |
| Invite / Remove Team Members | Yes | Yes (Invite only) | No |
| Configure OpusSearch & Video Indexing | Yes | Yes | No |
| Connect Team YouTube Channel | Yes | Yes | No |
| Create Projects & Generate Clips | Yes | Yes | Yes |
| Spend from Shared Credit Pool | Yes | Yes | Yes |
| View Shared Team Video Library | Yes | Yes | Yes |
| Apply Shared Brand Templates / Kits | Yes | Yes | Yes |

*Team Ownership Constraint:* A user can only be the **Owner of 1 team** at any given time, but can be a Member of multiple teams.

---

## 6. Complete REST API Endpoint Inventory

**Base URL:** `https://api.opus.pro/api`  
**Authentication:** Header `Authorization: Bearer <API_KEY>` + `x-opus-org-id: <ORG_ID>`

### Endpoints Table

| Method | Endpoint | Description | Request Body / Parameters | Response Summary |
| :--- | :--- | :--- | :--- | :--- |
| `POST` | `/api/upload-links` | Obtains pre-signed GCS upload URL for local video. | `{ "filename": "video.mp4", "fileSize": 10485760 }` | `{ "uploadUrl": "...", "uploadId": "..." }` |
| `POST` | `/api/clip-projects` | Submits URL or uploaded video for clipping. | `{ "videoUrl": "...", "uploadId": "...", "durations": "30,60", "webhook": "...", "brandTemplateId": "...", "removeFiller": true }` | `{ "projectId": "proj_123", "status": "PROCESSING" }` |
| `GET` | `/api/clip-projects/{id}` | Polls project processing state. | Path parameter `id` | `{ "id": "proj_123", "status": "COMPLETED", "progress": 100 }` |
| `POST` | `/api/clip-projects/{id}/update-visibility` | Updates project sharing permissions. | `{ "visibility": "PUBLIC" }` | `{ "success": true }` |
| `GET` | `/api/clips` | Retrieves generated clips for a project. | Query: `projectId={id}` | Array of clip objects (scores, URLs, hooks, durations). |
| `GET` | `/api/exportable-clips` | Fetches export-ready clip download URLs. | Query: `q=findByProjectId&projectId={id}` | Array of download links and metadata. |
| `GET` | `/api/transcripts` | Fetches full timestamped transcript. | Query: `projectId={id}` | Full word-level JSON transcript. |
| `GET` | `/api/brand-templates` | Lists organization brand templates. | Query: `q=mine` | Array of template configurations. |
| `POST` | `/api/censor-jobs` | Triggers profanity bleeping on a clip. | `{ "clipId": "...", "mode": "BLEEP" }` | `{ "jobId": "censor_456", "status": "QUEUED" }` |
| `GET` | `/api/censor-job-status` | Checks status of a censor job. | Query: `jobId={id}` | `{ "status": "COMPLETED", "downloadUrl": "..." }` |
| `POST` | `/api/social-copy-jobs` | Generates platform headlines/hashtags. | `{ "clipId": "...", "platform": "TIKTOK" }` | `{ "title": "...", "description": "...", "hashtags": [...] }` |

---

## 7. Model Context Protocol (MCP) Complete Tool Catalog (37 Tools)

Host Endpoint: `https://mcp.opus.pro/mcp`  
Protocol Transport: `streamable-http` (OAuth 2.1) or Stdio via `@opusclip/mcp`

### Category 1: Read Tools (15 Tools)
1.  `opusclip_whoami`: Returns identity, email, and connected organization ID.
2.  `opusclip_get_usage`: Returns organization credit usage, consumed minutes, and remaining allowance.
3.  `opusclip_list_projects`: Lists recent projects with status and creation timestamps.
4.  `opusclip_list_clips`: Lists all clips inside a specified `projectId`, ranked by Virality Score.
5.  `opusclip_describe_clip`: Returns single clip metadata (word transcript, layout mode, render status).
6.  `opusclip_list_collections`: Lists custom clip collections/folders.
7.  `opusclip_list_clips_in_collection`: Lists clips belonging to a specified collection.
8.  `opusclip_list_brand_templates`: Lists available brand templates and design tokens.
9.  `opusclip_list_social_accounts`: Returns connected social media platforms and profile names.
10. `opusclip_list_scheduled_posts`: Returns scheduled posts queue with `schedule_id` and timestamps.
11. `opusclip_get_transcript`: Fetches complete word-level source transcript.
12. `opusclip_get_social_copy_job`: Retrieves result of an async social copy generation job.
13. `opusclip_analyze_video`: Returns keyframe visual analysis (face positions, active speakers, bounding boxes).
14. `opusclip_list_pinterest_boards`: Lists boards for a connected Pinterest account.
15. `opusclip_preview_clips`: Returns a playable card grid of top clips inside chat interfaces.

### Category 2: Write Tools (14 Tools - Requires Confirmation)
16. `opusclip_submit_project`: Submits video URL (YouTube, Vimeo, etc.) for clipping (consumes credits).
17. `opusclip_create_upload_link`: Generates pre-signed URL to upload local files.
18. `opusclip_edit_clip`: Applies edits (trim, layout switch, caption text, emoji toggles, filler removal).
19. `opusclip_create_censor_job`: Executes profanity bleeping or masking.
20. `opusclip_share_project`: Toggles project public/private link sharing.
21. `opusclip_create_collection`: Creates a new named collection.
22. `opusclip_add_clip_to_collection`: Adds a clip into a collection.
23. `opusclip_export_clip`: Requests high-resolution 1080p/4K MP4 render URL.
24. `opusclip_export_collection`: Batches render URLs for an entire collection.
25. `opusclip_duplicate_clip`: Clones a clip for A/B testing or variant editing.
26. `opusclip_create_social_copy_job`: Initiates platform-tailored headline/copy generation.
27. `opusclip_create_post_task`: Publishes clip immediately to a connected social account.
28. `opusclip_schedule_publish`: Queues clip for future publishing at a specific date/time.
29. `opusclip_unschedule_publish`: Cancels and deletes a scheduled post using `schedule_id`.

### Category 3: Generative Media Tools (8 Tools)
30. `opusclip_create_thumbnail_job`: Generates high-CTR thumbnail variants for a clip.
31. `opusclip_get_thumbnail_job`: Retrieves generated thumbnail image URLs.
32. `opusclip_create_speech_job`: Generates voiceover audio from text (params: `text` max 6k chars, `voice`, `style`).
33. `opusclip_create_music_job`: Generates background music track (params: `genre`, `instruments`, `BPM`, `mood`, `lyrics`).
34. `opusclip_create_video_job`: Generates video clip from text/image prompt via Hailuo 3 or Seedance 2.5 (params: `prompt`, `firstFrame`, `duration`, `resolution`).
35. `opusclip_get_media_generation_job`: Polls status and download URLs for generative speech, music, or video tasks.
36. `opusclip_analyze_reference_media`: Evaluates reference audio/video clip up to 300s against prompt style.
37. `opusclip_get_reference_analysis`: Fetches reference analysis scores and credits charged.

---

## 8. Inspiration Gallery MCP Recipes

The Inspiration Gallery consists of copy-paste agent prompt recipes for Claude/Cursor:
1.  **Three-Way Hook Test:** Agent calls `opusclip_duplicate_clip` twice on the #1 viral clip, rewrites the first 5 seconds of captions with 3 different provocative questions, and schedules all three variants to test retention.
2.  **Sponsor-Safe Purge:** Agent calls `opusclip_create_censor_job` across a collection, checks transcript for brand-sensitive words, and generates a clean cut collection for advertisers.
3.  **Album Art Palette Match:** Agent parses cover art colors, extracts dominant hex codes, and calls `opusclip_edit_clip` to set caption primary, highlight, and stroke colors matching the album release.
4.  **Fan Comment Timestamp Clipper:** Agent parses YouTube comments for timestamp markers (e.g., "14:20 is hilarious"), maps them to project transcripts, and extracts targeted clips.
5.  **Loom Polisher:** Agent scans Loom recordings, cuts "Can you see my screen?", trims dead pauses >1.5s, adds zoom-ins on presentation details, and exports.
