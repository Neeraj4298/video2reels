# Source Evidence Register & Audit Traceability

**Document Scope:** Full evidence register tracing every factual claim, capability, limit, and architectural decision back to official source documentation, with explicit classification of evidentiary confidence and residual uncertainties.

---

## 1. Evidentiary Confidence Taxonomy
*   **Directly Observed (DO):** Verified by inspecting live schema definitions, GitHub code manifests, OpenAPI/llms.txt documents, or verbatim text in public resources.
*   **Officially Documented (OD):** Sourced directly from OpusClip's published Help Center articles, FAQs, pricing pages, or changelogs.
*   **Architecturally Inferred (AI):** Clean-room technical deduction for how to independently engineer an open-source equivalent to replicate observed behavior.

---

## 2. Complete Evidence Register

| ID | Topic / Claim | Official Source URL | Source Type | Date Accessed | Classification | Verified Finding / Exact Restriction | Remaining Uncertainty |
| :---: | :--- | :--- | :--- | :--- | :---: | :--- | :--- |
| **EV-01** | Free Plan Credit Grant | `https://help.opus.pro/billing/free-credits` | Help Article | 2026-11-07 | **OD** | Free accounts receive a 60-credit one-time grant (+ up to 25 onboarding bonus). Credits do not refresh monthly. | Exact onboarding bonus triggers vary slightly by campaign. |
| **EV-02** | Brand Template vs. Kit Limits | `https://help.opus.pro/brand-templates/limits` | Help Article | 2026-11-07 | **OD** | Classic Templates: Free 1, Starter 1, Pro 2. New Brand Kits: Free 0, Trial 2, Starter 1, Pro 4. | Timeline for full deprecation of Classic Templates is unannounced. |
| **EV-03** | Data Retention & Storage Expiry | `https://help.opus.pro/managing-projects/retention` | Help Article | 2026-11-07 | **OD** | Free clips delete after 3 days; Starter after 30 days; Pro has 100 GB persistent storage; Business unlimited. | Whether raw files expire earlier than rendered clips is not detailed. |
| **EV-04** | AI B-Roll Tier Gating | `https://help.opus.pro/ai-tools/b-roll` | Help Article | 2026-11-07 | **OD** | Free has none; Starter has Stock & AI Images; Pro unlocks full generative AI Video. | Exact generative model names (Hailuo 3, Seedance) appear in MCP tools, not web UI copy. |
| **EV-05** | Enhance Speech Daily Cap | `https://help.opus.pro/ai-tools/enhance-speech` | Help Article | 2026-11-07 | **OD** | Disabled on Free/Starter; Pro and Business get 10 free uses per calendar day. | Whether extra uses can be purchased with minute credits is unstated. |
| **EV-06** | Developer API Tier Requirement | `https://help.opus.pro/api-reference/agent-setup` | Help Article / Docs | 2026-11-07 | **OD** | Accessing the REST API or MCP tools requires an active Pro (Beta), Max, or Business plan. | Specific pricing of "Max" plan is unlisted on the public pricing page. |
| **EV-07** | Social Publishing & X Surcharge | `https://help.opus.pro/social-scheduler/billing` | Help Article | 2026-11-07 | **OD** | 9 platforms supported; X (Twitter) incurs a mandatory 3-credit surcharge per post. | Cause of X surcharge (likely X API pricing pass-through) is not explicitly named. |
| **EV-08** | Opus Labs Credit Mechanics | `https://help.opus.pro/opus-labs/ai-expand` | Help Article | 2026-11-07 | **OD** | AI Expand charges dynamically based on resolution/length; Multi-Angle charges per completed shot. | Dynamic pricing formula for AI Expand is not exposed in public tables. |
| **EV-09** | MCP Server Package & Endpoint | `https://raw.githubusercontent.com/opus-pro/opusclip-mcp/main/server.json` | Manifest / Code | 2026-11-07 | **DO** | Remote streamable HTTP at `https://mcp.opus.pro/mcp`; npm package `@opusclip/mcp`; version 0.4.0. | None. Full JSON manifest inspected. |
| **EV-10** | Complete 37 MCP Tool Catalog | `https://help.opus.pro/api-reference/agent-setup` | Official Docs | 2026-11-07 | **DO** | 15 Read, 14 Write, 8 Media tools officially documented with parameters and categories. | Internal API endpoint mapping inside remote MCP host is opaque. |
| **EV-11** | REST API Full Endpoints | `https://help.opus.pro/llms.txt` & `/api-reference` | Docs Index | 2026-11-07 | **DO** | 10+ core REST endpoints for upload links, projects, clips, transcripts, brand templates, censor jobs. | Full OpenAPI v3.1 YAML schema is not publicly downloadable without login. |
| **EV-12** | AI Voiceover vs. AI Dubbing | `https://help.opus.pro/editor/ai-voiceover` | Help Article | 2026-11-07 | **OD** | AI Voiceover is TTS from script (20+ voices, stability slider, ducking); Dubbing is multilingual voice cloning. | Voice provider backend (ElevenLabs vs. proprietary) is not disclosed. |
| **EV-13** | AI Producer Architecture | `https://producer.opus.pro/` & Help Docs | Product Page | 2026-11-07 | **OD** | Autonomous editing agent for raw footage; retake detection, B-roll/music auto-cut, reasoning edit log. | Model prompting architecture behind the reasoning log is proprietary. |
| **EV-14** | Web Editor Shortcuts & Layers | `https://help.opus.pro/editor/shortcuts` | Help Article | 2026-11-07 | **OD** | `->`/`<-` 1-frame stepping; `D`/`CMD+B` split; `S` snap; up to 5 stacked text layers; snap editing. | Exact maximum count for audio/SFX tracks is not specified. |
| **EV-15** | Team Workspace 3-Tier RBAC | `https://help.opus.pro/team-workspace/roles` | Help Article | 2026-11-07 | **OD** | Owner (sole billing/plan authority, 1 team ownership limit), Admin (invites, indexing setup), Member (clipping). | Custom enterprise permissions beyond the 3 tiers are negotiated via sales. |
| **EV-16** | Social Post Rate Limits | `https://help.opus.pro/social-scheduler/limits` | Help Article | 2026-11-07 | **OD** | TikTok 15/day, IG 40/day, YouTube ~15/day, X 150/day. Post edits do not update scheduled posts. | Third-party social platform token refresh timeouts are not documented. |
| **EV-17** | Inspiration Gallery MCP Recipes | `https://opus.pro/mcp` | Product Page | 2026-11-07 | **DO** | Agent recipes: Three-way hook testing, Sponsor-safe cut, Album art palette matching, Fan comment clipping. | Prompt lengths and system instructions inside the recipes are not downloadable. |
| **EV-18** | Input Constraints (10h, 10GB, CFR) | `https://help.opus.pro/video-processing/supported-formats`| Help Article | 2026-11-07 | **OD** | Max 10GB web / 30GB API; max 10 hours; non-integer framerate (29.97 fps) causes processing issues. | Root cause of framerate bug (likely strict timescale muxing in backend) is an engineering inference. |
| **EV-19** | NLE XML Export Package Content | `https://help.opus.pro/export-to-xml/import-to-adobe-premiere-faq` | Help Article | 2026-11-07 | **OD** | ZIP package containing sequence XML, raw video segment, and `.srt` file. XML contains reframing keyframes. | Whether Premiere Pro MGT (Motion Graphics Templates) can be embedded is unsupported. |
| **EV-20** | Independent Video Engine Stack | `specifications/technical-architecture.md` | Architecture Doc | 2026-11-07 | **AI** | Open-source equivalent: WhisperX, PyAnnote, YOLOv8-face, SyncNet, PySceneDetect, FFmpeg NVENC, Remotion. | Hardware costs and VRAM throughput must be empirically benchmarked under load. |
