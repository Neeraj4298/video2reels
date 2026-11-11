# Evidence & Unknowns

**Document Scope:** Clear distinction between what has been directly observed from public documentation versus what is inferred architecturally for a clean-room implementation.

---

## 1. Direct Observations (Facts)

The following facts have been verified through OpusClip's official documentation, Help Center, pricing page, or API/MCP public repositories:

*   **Ingestion Limits:** Up to 10 GB (Web) or 30 GB (API). Max length is 10 hours.
*   **Framerate:** Requires integer frame rates; non-integer (29.97 fps) causes issues without YouTube preprocessing.
*   **Credit System:** 1 credit = 1 minute of video. Rounding is applied (under 1m rounds up to 1; over 1m rounds down to nearest integer). Minimum 10 credits per project. Expire in 60 days on monthly plans.
*   **Virality Score:** A 0–99 score based explicitly on Hook, Flow, Value, and Trend.
*   **Reframe Modes:** Documented modes include Fill, Fit, Split, Three/Four, Screenshare, and Gameplay. Split/grid modes explicitly require speakers to be in the same source frame.
*   **MCP Integration:** There is a live MCP server at `mcp.opus.pro/mcp` offering 29 tools using OAuth authentication.
*   **Agent Opus (Audio-to-Video):** Accepts audio (MP3/WAV) up to 50MB / 5 mins and generates visuals in Standard, Premium, or Ultra modes.
*   **NLE Export:** Pro users can export an XML file bundled with an `.srt` and raw media for Premiere and DaVinci. The XML contains auto-reframe data.
*   **Social Scheduler:** Schedules to YouTube, TikTok, IG, LinkedIn, Facebook, X, Pinterest, Threads, Bluesky. X incurs a 3-credit surcharge per post.

---

## 2. Architectural Inferences (Assumptions)

The following are architectural hypotheses required to build an independent, competing product. They are not extracted from OpusClip's proprietary code but represent standard industry best practices for achieving the observed behavior.

*   **Audio Pipeline:** Assumed use of `yt-dlp` for ingestion, `ffmpeg` for demuxing/normalization (16kHz mono), `WhisperX` (faster-whisper + Wav2Vec2) for word-level timestamps, and `PyAnnote` for diarization.
*   **Highlight Curation:** Assumed use of an LLM (like Claude 3.5 Sonnet or GPT-4o) with a JSON schema constraint and a sliding context window to find hooks and narrative arcs.
*   **Virality Scoring Math:** The exact weights of Hook, Flow, Value, and Trend are inferred. The use of audio RMS loudness for the "Hook" energy is a standard audio processing technique inferred for this application.
*   **Reframing Tech:** Assumed use of YOLOv8-face or MediaPipe for tracking, PySceneDetect for cut detection, and SyncNet/TalkNet for mapping audio energy to lip movement to determine the active speaker.
*   **Caption Rendering:** Assumed use of either Remotion (React-based renderer) or advanced FFmpeg `ass` filters to achieve the karaoke highlighting and drop shadows at scale.
*   **Emoji Matching:** Assumed use of a dictionary lookup mapped to embeddings to assign emojis to keywords contextually.
*   **Video Editing State:** Assumed use of a JSON-based Edit Decision List (EDL) in the frontend that maps text deletions to video timeline trims, skipping frames on playback without re-encoding until export.
*   **Export Engine:** Assumed use of FFmpeg with `h264_nvenc` on GPU instances for fast rendering, alongside an XML serializer for the Premiere/DaVinci hand-off.
