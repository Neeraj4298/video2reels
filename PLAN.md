# Video2Reels → OpusClip-Class Platform: Architecture & Divide-and-Conquer Execution Plan

## 1. Executive Summary & Architectural Premise

Following a full audit of `opusclip/research/*` (12 documents), `opusclip/specifications/*` (7 documents), `suggestions.md`, and the existing `video2reels` codebase, the central architectural shift is:

> **Separate "Analysis" from "Composition" via a Canonical Edit Decision List (EDL) and Versioned Artifacts.**

Instead of piping raw transcripts through Celery payloads straight into a hardcoded FFmpeg command, the system produces structured analysis artifacts (`words`, `signals`, `tracks`, `scenes`, `candidates`) with stable word IDs (`w_000001`), compiles an editable **EDL (`edl.json`)** as the single source of truth for both browser preview and server rendering, tracks every stage execution in `stage_runs`, enforces security boundaries (path sanitization, SSRF protection, FFmpeg filter escaping), fails loudly instead of fabricating transcripts, and measures quality continuously via an automated **Evaluation Harness**.

---

## 2. Divide-and-Conquer Workstreams

### Workstream 1: Security, Fail-Loudly & Ingest/Storage Hardening (`suggestions.md` §1, §6, §8 Phase A, §9 #1–#2)
1. **Storage Path Traversal Prevention (`api/storage.py`, `api/routers/clips.py`)**:
   - Add `sanitize_storage_key(bucket, key)` rejecting `..`, null bytes, absolute paths, or resolved paths outside `_LOCAL_STORAGE_ROOT`.
   - Gate `/api/clips/storage/{bucket}/{key:path}` behind `settings.allow_local_storage_routes` and enforce path sanitization.
2. **SSRF Protection & Stream Normalization (`workers/ingest.py`)**:
   - Add `validate_source_url(url)` allowlisting `http`/`https` and blocking loopback, RFC1918 private networks, link-local (`169.254.0.0/16`), and cloud metadata endpoints.
   - Add Constant Frame Rate (CFR) detection & normalization (`needs_cfr_normalization`, `normalize_to_cfr`) for non-integer framerates (e.g., 29.97 fps) and VFR streams, plus 720p proxy generation (`generate_proxy_video`).
3. **FFmpeg Filter Path Escaping (`workers/render.py`, `workers/reframe.py`)**:
   - Add `escape_ffmpeg_filter_path(path)` to safely escape `:`, `\`, `'`, `[`, `]`, `,`, `;` inside `ass='...'` filter expressions.
4. **Fail Loudly in ASR & Flagged Heuristic Fallback (`workers/transcribe.py`, `workers/select_clips.py`)**:
   - Remove silent `_fallback_transcript_from_wav` fabrication from default `transcribe()` execution so missing/broken ASR raises a clear error instead of producing `"Spoken highlight segment N"`.
   - Mark any heuristic clip fallback with `low_confidence=True` on `Clip` and make heuristic fallback explicitly opt-in/configurable.

### Workstream 2: Data Model, Multi-Tenancy, Credits, Stage Runs & Artifact Orchestration (`suggestions.md` §2, §5, §6, §9 #3–#4)
1. **ORM Models (`api/models/__init__.py`) & Migration (`infra/migrations/versions/002_opusclip_platform_schema.py`)**:
   - Add `Organization`, `User`, `StageRun`, `Artifact`, `ClipVersion`, `CreditLedger`, `ApiKey`, `WebhookSubscription`, and `FeedbackEvent`.
   - Extend `RenderSettings` with `excluded_word_indices`, `word_overrides`, and `edl`.
2. **Per-Stage Job & StageRun Tracking (`workers/tasks.py`)**:
   - Stop overwriting a single `Job` row per project; maintain one `Job` row per `(project_id, stage)` and append `StageRun` records with attempt count, duration, and model/prompt version.
3. **Artifact-Referenced Orchestration (`workers/tasks.py`)**:
   - Persist transcript and stage outputs as `Artifact` rows and pass lightweight IDs (`transcript_id`, `artifact_ids`) between Celery stages (while retaining backward compatibility when `prev["transcript"]` is passed in existing unit tests).

### Workstream 3: Core AI Accuracy — Stable Word IDs, Signals Layer, Word-ID Highlight Judge, ASD + Split Screen + `sendcmd` (`suggestions.md` §3, §8 Phase B, §9 #5, #8)
1. **Stable Word IDs & `.srt` / Vocabulary Support (`workers/transcribe.py`)**:
   - Assign deterministic word IDs (`w_000001`, `w_000002`, ...) to every `Word` in `Transcript`.
   - Add `transcript_from_srt(srt_content)` override parser and `custom_vocabulary` support.
2. **10 Hz Multimodal Signals Layer (`workers/signals.py`)**:
   - Compute 10 Hz `SignalFrame` series: RMS energy, pitch estimate, local speech rate, audio event classification (laughter/applause/speech/silence), scene cuts, face track positions with active-speaker probability (`speaking_prob`), and screen-text density.
3. **Word-ID Highlight Selection & Boundary Refinement (`workers/select_clips.py`)**:
   - Format words with `[w_000001]` IDs; resolve `[start_word_id, end_word_id]` deterministically to exact word timestamps (with fallback to float timestamps for legacy mocks).
   - Reject or snap clips starting with dependent clauses (`Because`, `And so`, `Which`, `Therefore`, `However`) and snap boundaries to sentence ends + VAD silence valleys.
   - Support feedback-calibrated blend weights (`calibrate_blend_weights`).
4. **ASD-Fused Reframing, Real Two-Speaker Split Screen & `sendcmd` Crop (`workers/reframe.py`)**:
   - Fuse face tracks, diarization labels, and ASD speaking probability with a **1.5s hysteresis window** (`select_active_speaker_face`).
   - Add automatic layout classifier (`classify_layout`: `vertical`, `split_screen`, `screenshare`, `gameplay`, `blur_bg`).
   - Upgrade `build_split_screen_filter_complex` to crop two distinct speaker regions (top speaker vs. bottom speaker) instead of duplicating the same center crop.
   - Add `generate_sendcmd_crop_script` to support unlimited keyframes via FFmpeg `sendcmd`, bypassing the 22-segment nested `if(lt(t,...))` limit.
   - Compute true geometric `face_in_frame_ratio` (verifying the active speaker's face center lies inside the active crop window).

### Workstream 4: EDL Schema & Compiler, Caption Engine, XML Export & Studio Persistence (`suggestions.md` §3, §4, §8 Phase C & E, §9 #7)
1. **Canonical EDL Schema & FFmpeg Compiler (`workers/edl.py`)**:
   - Define `EDL`, `EDLCutSegment`, `EDLCaptionOverride`, `EDLAudioSettings`, and `EDLOverlay`.
   - Compile clip + `excluded_word_indices` + `word_overrides` into contiguous cut segments with 15ms audio crossfades (`afade=t=in:d=0.015`, `afade=t=out:d=0.015`) and EBU R128 loudness normalization.
2. **Upgraded Caption Engine (`workers/captions.py`)**:
   - Cadence-aware phrase grouping (1–4 words per phrase), auto-emoji injection (`inject_auto_emojis`), pop-scale emphasis tags, and filtering of `excluded_word_indices` + `word_overrides` across ASS, SRT, and VTT outputs.
3. **Premiere / DaVinci FCP7 XML Export (`workers/xml_export.py`)**:
   - Serialize clip EDL and reframing keyframes into `<xmeml version="4">` interchange XML and package with `.srt` subtitles into a downloadable ZIP (`GET /api/clips/{clip_id}/export-xml`).
4. **Server-Side Persistence & Studio UI Wiring (`api/routers/clips.py`, `ui/src/app/projects/[id]/clips/[clipId]/page.tsx`)**:
   - Persist `excluded_word_indices`, `word_overrides`, and `edl` on `PATCH /api/clips/{clip_id}`, `PATCH /api/clips/{clip_id}/edl`, and `POST /api/clips/{clip_id}/render`.

### Workstream 5: Evaluation Harness, Credit Ledger & MCP Server (`suggestions.md` §6, §7, §8 Phase A/D/E, §9 #6)
1. **Evaluation Harness (`workers/eval_harness.py`)**:
   - Implement `compute_wer`, `compute_caption_onset_error_ms`, `compute_der`, `compute_highlight_overlap_iou`, `compute_mid_sentence_boundary_rate`, `compute_reframing_metrics`, `compute_clip_acceptance_rate`, and `run_golden_eval_suite`.
2. **Credits, Feedback & MCP Endpoints (`api/routers/platform.py`)**:
   - OpusClip credit calculator & ledger API (`/api/credits/*`), clip feedback & weight calibration API (`/api/clips/{id}/feedback`), golden eval report endpoint (`/api/eval/report`), and MCP endpoints (`/api/mcp/tools`, `/api/mcp/call`).

---

## GSTACK REVIEW REPORT

### Phase 1: CEO / Product Review (Mode: SELECTIVE_EXPANSION)
- **Auto-decisions**: Prioritize the 9 "Do these first" items in `suggestions.md` plus the EDL compiler, Evaluation Harness, Credit Ledger, XML export, and MCP tool interface. Keep Python (FastAPI + Celery + FFmpeg) as the unified backend stack.

<!-- autoplan-accepted:ceo -->
- Eliminate silent garbage fallbacks (`_fallback_transcript_from_wav`), add explicit `low_confidence` flagging on heuristic clips, and enforce OpusClip credit math + evaluation harness gates.
<!-- /autoplan-accepted:ceo -->

### Phase 2: Design & Studio Review
- **Auto-decisions**: Persist `excluded_word_indices` and `word_overrides` to the backend and pass them on re-render; drive `WaveformBars` from real transcript word timing and probability/energy data.

<!-- autoplan-accepted:design -->
- Wire `excluded_word_indices` and `word_overrides` end-to-end from the Next.js clip studio to `PATCH /api/clips/{id}` and `POST /api/clips/{id}/render`, and drive waveform bars from real transcript word data.
<!-- /autoplan-accepted:design -->

### Phase 2.5: Developer Experience (DX) & Agentic Interface Review
- **Auto-decisions**: Expose `/api/mcp/tools` and `/api/mcp/call` for agentic workflows, `/api/clips/{id}/export-xml` for Premiere/DaVinci handoff, and `/api/eval/report` + `workers/eval_harness.py` for deterministic CI evaluation.

<!-- autoplan-accepted:dx -->
- Provide MCP tool discovery/invocation endpoints (`/api/mcp/tools`, `/api/mcp/call`), FCP7 XML export (`/api/clips/{id}/export-xml`), and a deterministic evaluation harness (`workers/eval_harness.py`).
<!-- /autoplan-accepted:dx -->

### Phase 3: Engineering Architecture Review (Mode: FULL_REVIEW)
- **Auto-decisions**: Enforce storage path traversal checks, URL SSRF validation, FFmpeg `ass` path escaping, per-stage `Job`/`StageRun` persistence, artifact-backed transcript passing, `sendcmd` crop support, real 2-speaker split-screen cropping, and 100% pass rate on all existing and new pytest suites.

<!-- autoplan-accepted:eng -->
- Enforce storage path traversal checks, URL SSRF validation, FFmpeg `ass` path escaping, per-stage `Job`/`StageRun` persistence, artifact-backed transcript passing, `sendcmd` crop support, real 2-speaker split-screen cropping, and 100% pass rate on all existing and new pytest suites.
<!-- /autoplan-accepted:eng -->
