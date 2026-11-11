# OpusClip Integrations & Platform Ecosystem

**Document Scope:** Detailed mapping of external platforms, input sources, export destinations, and developer interfaces supported by OpusClip.

---

## 1. Input Sources & Integrations

OpusClip supports acquiring media from a wide array of cloud and social platforms to reduce friction.

*   **Video Hosting & Social Platforms (Direct URL Parsing):**
    *   YouTube (Videos & Shorts)
    *   Vimeo
    *   Twitch (VODs & Clips)
    *   Rumble
    *   Facebook, LinkedIn, X (Twitter)
*   **Cloud Storage & Remote Drives:**
    *   Google Drive (Direct integration via OAuth)
    *   Google Cloud Storage (Supported via API parameters)
*   **Webinar & Recording Platforms:**
    *   Zoom (Cloud recordings)
    *   Riverside.fm
    *   StreamYard
    *   Loom
*   **Automation Triggers:**
    *   **Auto-Import:** Can be linked to a YouTube channel to automatically ingest and process new videos as they are published.

---

## 2. Output & Publishing Ecosystem

### 2.1 Direct Social Scheduling
The built-in Social Scheduler connects via OAuth to post directly to:
*   TikTok
*   YouTube (Shorts)
*   Instagram (Professional/Creator/Business accounts)
*   LinkedIn
*   Facebook Pages
*   X (Twitter) *Note: Incurs a 3-credit surcharge per post, per account.*
*   Pinterest
*   Threads
*   Bluesky

### 2.2 Professional Post-Production (NLEs)
*   **Adobe Premiere Pro:** Via FCPXML / Premiere XML.
*   **DaVinci Resolve:** Via FCPXML.

---

## 3. Developer Ecosystem

### 3.1 REST API (`api.opus.pro`)
*   **Auth:** Bearer Token + `x-opus-org-id`.
*   **Rate Limits:** 30 requests per minute.
*   **Webhooks:** HMAC-SHA256 signed POST callbacks for async job completion (`x-opus-signature`).
*   **Availability:** Restricted to Pro (Beta), Max, and Business plans.

### 3.2 Model Context Protocol (MCP) Server (`mcp.opus.pro/mcp`)
*   **Registry:** Officially listed as `io.github.opus-pro/opusclip`.
*   **Tool Count:** Exposes 29 discrete tools for curation, layout, captions, and publishing.
*   **Auth:** Browser-based OAuth flow triggered on first tool call.
*   **Supported Clients:** Claude Code, Claude Desktop, Cursor, any standard MCP-compliant host.
