# Evolving video2reels into an OpusClip-class platform

## 1. Where the codebase stands

You have a working Phase-0 pipeline with a UI shell. The structure is sound (staged workers, idempotent tasks, SSE progress, brand kits, tests). But several parts that look finished are prototype-grade, and they are exactly where OpusClip's quality comes from.

| Area | Current state | Problem |
|---|---|---|
| Diarization | `diarize_segments` toggles speakers on pauses and question marks | Not real diarization. Nothing downstream can trust the speaker labels. |
| Active speaker | `select_primary_face` picks the largest, most centered face | No audio-visual correlation. It will track the wrong person in interviews. |
| Split-screen | Stacks the same centered crop twice | Not a real two-speaker layout. |
| ASR | `base` Whisper model, no forced alignment | Word-timing drift hurts caption sync, and `base` is weak for accuracy. |
| Clip selection | LLM returns float timestamps, validated only to within 2s of any word start | Boundary and hallucination risk. Your own docs recommend word indices. |
| Fallbacks | `_fallback_transcript_from_wav` emits "Spoken highlight segment N…"; `_heuristic_select_clips` fabricates clips | In production, a failure becomes "successful" garbage. These should fail loudly. |
| Editor | Waveform is synthetic; excluded words live only in React state; trim edits don't re-render | The editor is a mock, not an editor. |
| Publishing | `/publish` returns "successfully published" without doing anything | Misleading. Remove it or build it properly. |
| Jobs | One `Job` row per project, overwritten per stage, read via `.first()` | The stage table in the UI can't be accurate. |
| Orchestration | The full transcript is passed through Celery/Redis payloads | Breaks at 2–3 hour videos. |
| Dev fallbacks | SQLite fallback, local-disk storage, thread-based pipeline runner, unauthenticated PUT/GET on `/api/clips/storage/{bucket}/{key:path}` | Remove from production. The storage route needs path sanitization at minimum. |
| Platform | No auth, tenancy, credits, billing, or API keys | None of the SaaS layer exists yet. |

The main idea for the redesign: **separate "analysis" from "composition."** Today the pipeline goes straight from transcript to an FFmpeg command. OpusClip-class tools produce analysis artifacts (words, speakers, faces, audio events, scenes, candidate clips), then compile an editable **timeline (EDL)** that renders identically in the browser and on the server.

## 2. Target architecture

```
 Next.js Studio (timeline editor, gallery, publish)         MCP / REST API / Webhooks
                         │                                           │
                 ┌───────▼───────────────────────────────────────────▼──────┐
                 │  API (FastAPI): auth, orgs, credits, projects, EDL CRUD   │
                 └───────┬──────────────┬───────────────┬────────────────────┘
                         │              │               │
                   Postgres        Object store     Orchestrator
                (RLS by org_id)   (artifacts only)  (stage graph + stage_runs)
                                                        │
   ┌──────────┬───────────┬──────────────┬─────────────┼──────────────┬───────────┐
   │ ingest   │ asr/align │ vision       │ highlight   │ compose      │ render    │
   │ (CPU)    │ diarize   │ faces+ASD    │ (LLM+rank)  │ EDL compiler │ FFmpeg /  │
   │ yt-dlp,  │ (GPU)     │ scenes (GPU) │ eval-gated  │ (pure code)  │ Remotion  │
   │ CFR,proxy│           │              │             │              │ (GPU/CPU) │
   └──────────┴───────────┴──────────────┴─────────────┴──────────────┴───────────┘
                              Artifact store: words.json, signals.parquet,
                              tracks.json, scenes.json, candidates.json, edl.json
```

**Principles**
1. **Artifacts, not payloads.** Each stage reads and writes versioned artifacts in object storage. Celery messages carry only IDs.
2. **EDL is the source of truth.** The AI proposes an EDL, the user edits it, and the renderer consumes it. Trim, text-delete, layout, caption style, B-roll, and music are all EDL operations.
3. **Stage rows.** A `stage_runs` table with one row per (project, stage, attempt) records status, timing, cost, and the model version used.
4. **Fail loudly.** No fabricated fallbacks. A stage fails, and the project shows "needs retry."
5. **Compute abstraction.** A `ComputeBackend` interface (local worker, Modal, RunPod) lets you start serverless-GPU and move later without rewrites.

**Stack decision.** Your `architecture-decisions.md` proposes Node, NestJS, and Remotion, but your code is Python and your ML stack (WhisperX, pyannote, YOLO, OpenCV) is Python. Keep Python for API and workers. Add Node only as a small render service if you adopt Remotion.

## 3. Quality upgrades per stage

**Ingest**
- Normalize to constant frame rate (the 29.97 fps issue in your own docs).
- Generate a 720p proxy for analysis and browser preview. Run analysis on the proxy and final render on the original.
- Reject live streams, DRM, and multi-hour videos that exceed credits. Compute the credit cost before processing.

**ASR, alignment, diarization**
- WhisperX with `large-v3` and Silero VAD, plus wav2vec2 forced alignment, replaces the `base` model.
- pyannote 3.1 replaces `diarize_segments`. Keep Deepgram as a swappable provider behind the same `Transcript` schema.
- Give every word a stable ID (`w_000123`), because every later stage references IDs, not seconds.
- Support a user-uploaded `.srt` override and a custom vocabulary.

**Signals layer (new stage, the key accuracy lever)**
Compute a time series at 10 Hz:
- RMS energy, pitch, and speech rate
- Laughter and applause (a YAMNet or PANNs audio-event model)
- Scene cuts (PySceneDetect), already in your reframe code
- Face tracks with ByteTrack and per-track "is speaking" probability from a light ASD model (Light-ASD or TalkNet)
- Optional on-screen-text OCR for screenshare detection

This feeds both highlight scoring and reframing, so they stop being independent.

**Highlight detection: retrieve, judge, refine**
1. **Candidates:** segment topics with embedding-based segmentation, then generate overlapping windows.
2. **LLM judge:** pass numbered words and have the model return `[start_word_id, end_word_id]`, hook, and the four rubric scores with a one-line reason each. Enforce a Pydantic schema. Your Gemini and Anthropic callers become one provider-agnostic interface.
3. **Refine:** snap to sentence boundaries, then to VAD silence (not just ±0.3s padding). Reject clips that begin with dependent clauses ("Because…", "And so…"). Dedupe by embedding similarity as well as time overlap.
4. **Score:** keep the 0–99 UI, but calibrate it. Learn the blend weights from human labels and user behavior (kept, exported, published) rather than hardcoding 60/15/15/10.

**Reframing**
- Fuse diarization, ASD, and face tracks to pick the speaker, with a 1.5s hysteresis so the camera doesn't ping-pong.
- Layout classifier: 1 face → Fill. 2 faces in one frame → Split with a real crop per speaker. Slides or text-dense frames → Screenshare (50/50). A webcam region plus busy content → Gameplay. No usable face → Fit with blur background.
- Replace the nested `if(lt(t,...))` expression, which is capped at 22 segments, with a `sendcmd` command file that updates the crop `x` at runtime. Verify this on your FFmpeg build; it removes the keyframe cap.
- Measure the face-in-frame rate for real. The current `face_in_frame_ratio` is only the fraction of samples with a detection.

**Captions and typography**
- Build a caption engine, not just an ASS generator: phrase grouping by cadence (1–4 words), per-word pop and scale animation, keyword emphasis, auto-emoji (dictionary plus embedding fallback), and brand fonts with real font files bundled in the render image.
- Persist caption overrides in the EDL, so deleted or edited words actually reach the render. Today `excludedWordIndices` is never sent to the server.

**Audio**
- Two-pass `loudnorm`, a 15 ms crossfade at every cut, and music ducking.
- Enhance Speech via DeepFilterNet or similar, with a daily cap if you copy OpusClip's model.

## 4. The EDL and the render decision

Define one `edl.json` schema covering source cuts (word-ID ranges), layout per segment, crop keyframes, caption track plus style, overlay tracks (text, B-roll, emoji, logo), and audio tracks (music, SFX, voiceover). Then:

- **Compiler:** `edl → FFmpeg filtergraph` (extends your existing `_build_ffmpeg_cmd`). This is the fast path for drafts and most exports.
- **Remotion (optional second backend):** use it only for complex animated captions or templates you can't express in libass. It lets the browser preview and the server render share the same React components. Check Remotion's commercial licensing terms before committing.

Build the **preview** in the browser from the same EDL (HTML5 video plus a canvas/CSS caption layer). Add a visual regression test that compares preview frames against server render frames, because preview/render parity is the usual failure point.

## 5. Data model changes

New or changed tables:
- `organizations`, `users`, `memberships` (Owner/Admin/Member). Add `org_id` to every table, with Postgres RLS.
- `assets` and `artifacts` (type, version, storage key, producing stage_run).
- `pipeline_runs` and `stage_runs` (replaces the single `jobs` row).
- `transcript_words` (or a JSONB artifact keyed by word ID) and `speakers`.
- `clips` plus `clip_versions` (EDL snapshots, for undo and variants).
- `renders` (EDL version, resolution, codec, watermark flag).
- `brand_kits` scoped to org.
- `credit_ledger` (append-only: grants, spends, refunds, expiries), plus `usage_events`.
- `social_accounts`, `scheduled_posts`.
- `api_keys`, `webhooks`.
- `feedback_events` (clip kept, trimmed, exported, published, rejected), which feeds score calibration.

## 6. Platform layer

- **Auth:** Auth.js or Clerk, with API keys for programmatic access.
- **Credits:** 1 credit per minute, computed after probe and before the expensive stages, with refunds on failure (copy OpusClip's rounding if you want parity).
- **Billing:** Stripe subscriptions plus a webhook-synced ledger.
- **Publishing:** YouTube, TikTok, Instagram, and LinkedIn OAuth APIs. Budget time for platform app review, which can take weeks. Show "export and copy caption" until the integrations are real.
- **API, webhooks, MCP:** expose the same service layer through REST, signed webhooks, and an MCP server.
- **Retention:** a cleanup job per plan tier.
- **Security:** sanitize storage keys, allowlist URL schemes and block private IP ranges for `yt-dlp` (SSRF), escape the path passed into the FFmpeg `ass='…'` filter, and use per-user presigned URLs only.

## 7. Evaluation harness

Without this, you can't tell whether you are improving. Build it before the feature work.

| Component | Metric | Target |
|---|---|---|
| ASR | WER on a fixed multi-accent set | <5% (clean English) |
| Alignment | Caption onset error | <100 ms (ideally one frame) |
| Diarization | DER | <12% |
| Highlights | Overlap with human-picked clips on ~50 podcast episodes | >70–80% |
| Boundaries | % of clips that start or end mid-sentence | <2% |
| Reframing | Face-in-frame % and camera-jitter metric | ≥95% |
| Product | Clip acceptance rate (kept without edits) | ≥60% |

Run it in CI on every prompt, model, or threshold change, and log model and prompt versions on every stage run. Also build a small internal review tool where a human marks good and bad clips. That labeled data is your moat, because OpusClip's proprietary edge is largely its models plus engagement feedback. You will approach its quality through this loop, not through any single model choice.

## 8. Roadmap

| Phase | Weeks | Deliverables | Exit criteria |
|---|---|---|---|
| **A. Harden** | 1–3 | Delete fake fallbacks, fix security issues, add `stage_runs`, move to artifact-based stages, add the eval harness and golden set, remove the stub publish endpoint | Pipeline reruns resume per stage; the eval baseline is recorded |
| **B. Core accuracy** | 3–7 | WhisperX with alignment, pyannote, signals layer, word-ID highlight judge with boundary refinement, ASD-based reframing, real split layout, `sendcmd` crop | Hits the eval targets above on the golden set |
| **C. EDL and Studio** | 7–11 | EDL schema and compiler, persisted text-based editing, real waveform and timeline, caption engine with emoji, two-pass audio | A text edit in the browser changes the render |
| **D. SaaS** | 11–14 | Auth, orgs, credits, Stripe, retention, API keys and webhooks | A paying user can complete the full flow |
| **E. Distribution and extras** | 14+ | Social publishing, B-roll, music, voiceover, dubbing, XML export, MCP server | Per feature |

Keep AI Producer-style autonomous editing, ClipAnything-style multimodal search, AI Expand, and multi-angle for later, after the core clipper beats your own acceptance-rate target.

## 9. Do these first

1. Remove `_fallback_transcript_from_wav` and make the heuristic clip fallback an explicit, flagged "low-confidence" mode, or delete it.
2. Sanitize `_local_object_path` and gate the local-storage routes behind dev mode only.
3. Create `stage_runs` and stop overwriting the single `Job`.
4. Stop passing the transcript through Celery payloads; write it to an artifact and pass the ID.
5. Switch clip selection to word-ID output and validate against exact word boundaries.
6. Assemble a 30–50 video golden set with human-picked clips and wire up the metrics above.
7. Persist excluded words and caption edits server-side, even before the full EDL exists.
8. Decide on a diarization and ASD path (pyannote plus Light-ASD) and benchmark it on interview footage.

Two caveats. Parity with OpusClip is a moving target, because it ships constantly and its models are proprietary, so aim for "better on your chosen niche" (for example, podcasts) before "matches everything." And ingesting third-party URLs with `yt-dlp` carries ToS and DMCA risk that you should address in product design (own-content default, takedown process).

I can put this into a document (Word, PDF, or a Claude Doc) if you'd like, or go deeper on any one piece, such as the EDL schema, the new database migration, or the highlight-judge prompt and eval design.