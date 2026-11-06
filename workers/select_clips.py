"""
Stage 4: Clip Selection (LLM)
──────────────────────────────
Two-pass approach:
  Pass A — Segmentation: split transcript into topic blocks
  Pass B — LLM:          pick best clips with virality scores

Supports: Gemini (default), Claude, Ollama (local).
Output: clips.json saved to work_dir/clips/
"""
from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional
import urllib.request

from loguru import logger
from workers.config import (
    LLM_PROVIDER, GEMINI_API_KEY, ANTHROPIC_API_KEY,
    OLLAMA_BASE_URL, OLLAMA_MODEL, ENABLE_CRITIC_PASS,
    CLIP_MIN_DURATION, CLIP_MAX_DURATION, TOP_N_CLIPS,
)
from workers.transcribe import Transcript, Segment, Word


# ── Data model ────────────────────────────────────────────────────────────────

@dataclass
class ScoreBreakdown:
    hook: int
    flow: int
    value: int
    trend: int

    @property
    def average(self) -> float:
        return (self.hook + self.flow + self.value + self.trend) / 4


@dataclass
class Clip:
    start: float
    end: float
    hook: str
    title: str
    score: int
    score_breakdown: ScoreBreakdown
    reason: str
    description: str = ""
    hashtags: list[str] = field(default_factory=list)

    @property
    def duration(self) -> float:
        return self.end - self.start

    def to_dict(self) -> dict:
        return {
            "start": self.start,
            "end": self.end,
            "duration": round(self.duration, 2),
            "hook": self.hook,
            "title": self.title,
            "score": self.score,
            "score_breakdown": {
                "hook": self.score_breakdown.hook,
                "flow": self.score_breakdown.flow,
                "value": self.score_breakdown.value,
                "trend": self.score_breakdown.trend,
            },
            "reason": self.reason,
            "description": self.description,
            "hashtags": self.hashtags,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Clip":
        sb_raw = data.get("score_breakdown") or {}
        raw_tags = data.get("hashtags") or []
        tags = [str(h).lstrip("#") for h in raw_tags if str(h).strip()] if isinstance(raw_tags, list) else []
        return cls(
            start=float(data.get("start", 0.0)),
            end=float(data.get("end", 0.0)),
            hook=str(data.get("hook", "")),
            title=str(data.get("title", "")),
            score=int(data.get("score", 50)),
            score_breakdown=ScoreBreakdown(
                hook=int(sb_raw.get("hook", 7)),
                flow=int(sb_raw.get("flow", 7)),
                value=int(sb_raw.get("value", 7)),
                trend=int(sb_raw.get("trend", 7)),
            ),
            reason=str(data.get("reason", "")),
            description=str(data.get("description", "")),
            hashtags=tags,
        )


# ── Pass A: Topic & Turn Segmentation ─────────────────────────────────────────

@dataclass
class TopicSegment:
    start: float
    end: float
    text: str
    speaker: Optional[str] = None
    segment_indices: list[int] = field(default_factory=list)

    @property
    def duration(self) -> float:
        return self.end - self.start


def segment_transcript(
    transcript: Transcript,
    pause_threshold: float = 1.5,
    target_block_duration: float = 45.0,
) -> list[TopicSegment]:
    """
    Pass A — Segmentation:
    Split transcript into coherent topic blocks at:
      - Sentence boundaries (. ! ?) when target duration is reached
      - Long pauses (> pause_threshold seconds of silence)
      - Speaker changes (e.g., S1 -> S2)
    """
    if not transcript.segments:
        return []

    blocks: list[TopicSegment] = []
    curr_segs: list[tuple[int, Segment]] = []

    for idx, seg in enumerate(transcript.segments, 1):
        if not curr_segs:
            curr_segs.append((idx, seg))
            continue

        prev_idx, prev_seg = curr_segs[-1]
        block_start = curr_segs[0][1].start
        block_dur = prev_seg.end - block_start
        pause_gap = max(0.0, seg.start - prev_seg.end)
        speaker_changed = (
            bool(seg.speaker and prev_seg.speaker)
            and seg.speaker != prev_seg.speaker
        )
        sentence_end = bool(re.search(r"[.!?][\"']?$", prev_seg.text.strip()))

        should_split = (
            pause_gap >= pause_threshold
            or (speaker_changed and block_dur >= 10.0)
            or (sentence_end and block_dur >= target_block_duration)
        )

        if should_split:
            blocks.append(
                TopicSegment(
                    start=curr_segs[0][1].start,
                    end=prev_seg.end,
                    text=" ".join(s.text.strip() for _, s in curr_segs),
                    speaker=curr_segs[0][1].speaker,
                    segment_indices=[i for i, _ in curr_segs],
                )
            )
            curr_segs = [(idx, seg)]
        else:
            curr_segs.append((idx, seg))

    if curr_segs:
        blocks.append(
            TopicSegment(
                start=curr_segs[0][1].start,
                end=curr_segs[-1][1].end,
                text=" ".join(s.text.strip() for _, s in curr_segs),
                speaker=curr_segs[0][1].speaker,
                segment_indices=[i for i, _ in curr_segs],
            )
        )

    return blocks


# ── Transcript formatting & chunking ──────────────────────────────────────────

def _format_segment_line(index: int, seg: Segment) -> str:
    speaker_prefix = f"({seg.speaker}) " if seg.speaker else ""
    clean_text = re.sub(r"(\S+)(?:\s+\1){4,}", r"\1", seg.text.strip())[:300]
    return f"[{index:04d}] {seg.start:.2f}s–{seg.end:.2f}s: {speaker_prefix}{clean_text}"


def _format_transcript_for_llm(transcript: Transcript, max_chars: int = 80_000) -> str:
    """
    Format transcript as numbered, timestamped lines for LLM consumption.
    Keeps lines short to avoid overwhelming the context window.
    """
    lines = [
        _format_segment_line(i, seg)
        for i, seg in enumerate(transcript.segments, 1)
    ]

    text = "\n".join(lines)
    if len(text) > max_chars:
        logger.warning(
            "Transcript too long ({} chars), truncating single window to {}.",
            len(text), max_chars,
        )
        text = text[:max_chars]
    return text


def _chunk_transcript_for_llm(
    transcript: Transcript,
    max_chars: int = 80_000,
    overlap_segments: int = 5,
) -> list[str]:
    """
    Split a long transcript into overlapping formatted text chunks so multi-hour
    videos are processed without losing tail content.
    """
    lines = [
        _format_segment_line(i, seg)
        for i, seg in enumerate(transcript.segments, 1)
    ]
    if not lines:
        return [""]

    full_text = "\n".join(lines)
    if len(full_text) <= max_chars:
        return [full_text]

    chunks: list[str] = []
    n = len(lines)
    start_idx = 0

    while start_idx < n:
        curr_lines: list[str] = []
        curr_len = 0
        idx = start_idx

        while idx < n:
            line = lines[idx]
            add_len = len(line) + (1 if curr_lines else 0)
            if curr_lines and curr_len + add_len > max_chars:
                break
            curr_lines.append(line)
            curr_len += add_len
            idx += 1

        chunks.append("\n".join(curr_lines))
        if idx >= n:
            break

        # Advance with overlap
        next_start = max(start_idx + 1, idx - max(0, overlap_segments))
        start_idx = next_start

    return chunks


# ── Word-boundary snapping ────────────────────────────────────────────────────

def _snap_to_word_boundary(
    start: float,
    end: float,
    all_words: list[Word],
    pad: float = 0.3,
) -> tuple[float, float]:
    """
    Adjust start/end to nearest word boundary + padding.
    Prevents clips from cutting off mid-word.
    """
    if not all_words:
        return start, end

    # Find nearest word start <= requested start
    snap_start = start
    for w in all_words:
        if w.start <= start + 0.5:
            snap_start = w.start
        else:
            break

    # Find nearest word end >= requested end
    snap_end = end
    for w in reversed(all_words):
        if w.end >= end - 0.5:
            snap_end = w.end
        else:
            break

    return max(0, snap_start - pad), snap_end + pad


# ── LLM callers ──────────────────────────────────────────────────────────────

def _call_gemini(prompt: str) -> str:
    if not GEMINI_API_KEY or GEMINI_API_KEY.startswith("your_"):
        raise RuntimeError("GEMINI_API_KEY is not configured (placeholder key in .env)")
    from google import genai
    from google.genai import types

    client = genai.Client(api_key=GEMINI_API_KEY)
    for model_name in ("gemini-2.5-flash", "gemini-2.0-flash"):
        try:
            cfg_kwargs: dict[str, Any] = {"response_mime_type": "application/json"}
            if "2.5" in model_name and hasattr(types, "ThinkingConfig"):
                cfg_kwargs["thinking_config"] = types.ThinkingConfig(thinking_budget=0)
            response = client.models.generate_content(
                model=model_name,
                contents=prompt,
                config=types.GenerateContentConfig(**cfg_kwargs),
            )
            return response.text
        except Exception as exc:
            if model_name == "gemini-2.0-flash" or "NOT_FOUND" not in str(exc):
                raise
    raise RuntimeError("Gemini model call failed")


def _call_anthropic(prompt: str) -> str:
    if not ANTHROPIC_API_KEY or ANTHROPIC_API_KEY.startswith("your_"):
        raise RuntimeError("ANTHROPIC_API_KEY is not configured (placeholder key in .env)")
    import anthropic
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    message = client.messages.create(
        model="claude-3-5-haiku-20241022",
        max_tokens=4096,
        messages=[{"role": "user", "content": prompt}],
    )
    return message.content[0].text


def _call_ollama(prompt: str) -> str:
    """Call local Ollama HTTP API (/api/generate) in JSON mode."""
    url = f"{OLLAMA_BASE_URL.rstrip('/')}/api/generate"
    payload = json.dumps({
        "model": OLLAMA_MODEL,
        "prompt": prompt,
        "format": "json",
        "stream": False,
    }).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=180) as resp:
        body = json.loads(resp.read().decode("utf-8"))
        return body.get("response", "{}")


def _call_llm(prompt: str) -> str:
    """Dispatch to the configured LLM provider."""
    provider = LLM_PROVIDER.lower()
    logger.info("[Stage 4] Calling LLM provider: {}", provider)
    if provider == "gemini":
        return _call_gemini(prompt)
    elif provider == "anthropic":
        return _call_anthropic(prompt)
    elif provider == "ollama":
        return _call_ollama(prompt)
    else:
        raise ValueError(f"Unknown LLM_PROVIDER: {provider}. Use gemini, anthropic, or ollama.")


# ── JSON extraction ───────────────────────────────────────────────────────────

def _extract_json(raw: str) -> dict:
    """Extract JSON from LLM output (may be wrapped in markdown code fences)."""
    # Strip markdown code fences if present
    cleaned = re.sub(r"```(?:json)?\s*", "", raw).strip().rstrip("`").strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError as e:
        # Try to find JSON object/array in the text
        match = re.search(r"\{.*\}", cleaned, re.DOTALL)
        if match:
            return json.loads(match.group())
        raise ValueError(f"Could not parse LLM JSON output: {e}\nRaw:\n{raw[:500]}")


# ── Blended Virality Scoring (BUILD_ARCHITECTURE.md §7 & §9) ─────────────────

_HOOK_PATTERNS = [
    r"\b(?:biggest|number one|#1|worst|best|secret|mistake|truth|never|always|stop|why|how)\b",
    r"\b\d+(?:\s*%|\s*x|\s*million|\s*billion|\s*reasons|\s*steps|\s*ways|\s*things)\b",
    r"\b(?:nobody tells you|here(?:'s| is) the thing|unpopular opinion|most people|if you want)\b",
    r"\?",
]

_SENTIMENT_INTENSITY_WORDS = {
    "amazing", "insane", "incredible", "shocking", "massive", "critical", "crucial",
    "mistake", "fail", "failed", "failure", "million", "billion", "secret", "breakthrough",
    "never", "always", "obsessed", "love", "hate", "terrifying", "genius", "wrong",
    "guaranteed", "instantly", "powerful", "proven", "exact", "urgent", "warning",
}


def compute_energy_score(clip_start: float, clip_end: float, all_words: list[Word]) -> float:
    """
    Compute speech pace & vocal confidence energy score (0–100) for a clip window.
    """
    duration = max(1.0, clip_end - clip_start)
    clip_words = [w for w in all_words if clip_start <= w.start <= clip_end]
    if not clip_words:
        return 65.0

    wpm = (len(clip_words) / duration) * 60.0
    if 130 <= wpm <= 195:
        pace_score = 90.0
    elif 100 <= wpm < 130:
        pace_score = 70.0 + ((wpm - 100.0) / 30.0) * 20.0
    elif 195 < wpm <= 240:
        pace_score = 90.0 - ((wpm - 195.0) / 45.0) * 20.0
    else:
        pace_score = max(45.0, min(70.0, (wpm / 130.0) * 70.0))

    avg_conf = sum(w.probability for w in clip_words) / len(clip_words)
    conf_score = max(50.0, min(100.0, avg_conf * 100.0))
    return round(0.65 * pace_score + 0.35 * conf_score, 2)


def compute_sentiment_score(text: str) -> float:
    """
    Compute emotional intensity / sentiment arousal score (0–100) from clip text.
    """
    if not text or not text.strip():
        return 60.0

    words = re.findall(r"\b[a-zA-Z']+\b", text.lower())
    if not words:
        return 60.0

    hits = sum(1 for w in words if w in _SENTIMENT_INTENSITY_WORDS)
    exclamations = text.count("!") + text.count("?")
    density = (hits + 0.5 * exclamations) / max(10, len(words))
    score = 60.0 + min(40.0, density * 350.0)
    return round(max(0.0, min(100.0, score)), 2)


def compute_hook_score(hook_text: str, opening_text: str = "") -> float:
    """
    Rule-based hook pattern score (0–100) inspecting the clip's hook and first 5s.
    """
    combined = f"{hook_text} {opening_text}".strip().lower()
    if not combined:
        return 55.0

    matches = sum(1 for pat in _HOOK_PATTERNS if re.search(pat, combined, re.IGNORECASE))
    score = 60.0 + min(40.0, matches * 14.0)
    return round(max(0.0, min(100.0, score)), 2)


def compute_blended_score(
    llm_score: float,
    clip_start: float,
    clip_end: float,
    hook_text: str,
    transcript: Transcript,
) -> int:
    """
    Combine LLM virality score with speech energy, emotional sentiment, and hook pattern:
        final_score = (
            llm_score       * 0.60 +
            energy_score    * 0.15 +
            sentiment_score * 0.15 +
            hook_score      * 0.10
        )
    """
    all_words = transcript.all_words
    clip_words = [w for w in all_words if clip_start <= w.start <= clip_end]
    clip_text = " ".join(w.text.strip() for w in clip_words)
    opening_words = [w for w in clip_words if w.start <= clip_start + 5.0]
    opening_text = " ".join(w.text.strip() for w in opening_words)

    energy = compute_energy_score(clip_start, clip_end, all_words)
    sentiment = compute_sentiment_score(clip_text or hook_text)
    hook = compute_hook_score(hook_text, opening_text)

    blended = (
        float(llm_score) * 0.60
        + energy * 0.15
        + sentiment * 0.15
        + hook * 0.10
    )
    return int(max(0, min(100, round(blended))))


# ── Post-LLM Critic Pass (v2) ─────────────────────────────────────────────────

def critic_pass(clips: list[Clip], transcript: Transcript) -> list[Clip]:
    """
    Second-pass LLM review that evaluates candidate clips for thematic uniqueness,
    stronger hook phrasing, and score refinement. Falls back gracefully on error.
    """
    if len(clips) <= 1:
        return clips

    candidates_payload = [c.to_dict() for c in clips]
    prompt = f"""You are a senior short-form video executive producer reviewing candidate clips.
Review these candidate clips and return a refined JSON object {{"clips": [...]}} where:
1. Near-duplicate topics are removed (keep the strongest version).
2. Each "hook" is sharpened to maximize curiosity in the first 3 seconds.
3. "score" (0-100) reflects true viral potential on TikTok, Reels, and YouTube Shorts.
Preserve the exact "start" and "end" timestamps of kept clips.

CANDIDATES:
{json.dumps(candidates_payload, indent=2)}
"""
    try:
        raw = _call_llm(prompt)
        parsed = _extract_json(raw)
        reviewed = parsed.get("clips", [])
        if not reviewed:
            return clips

        refined: list[Clip] = []
        for rc in reviewed:
            start = float(rc["start"])
            end = float(rc["end"])
            sb_raw = rc.get("score_breakdown", {})
            raw_tags = rc.get("hashtags", [])
            tags = [str(h).lstrip("#") for h in raw_tags if str(h).strip()] if isinstance(raw_tags, list) else []
            refined.append(
                Clip(
                    start=round(start, 3),
                    end=round(end, 3),
                    hook=rc.get("hook", ""),
                    title=rc.get("title", ""),
                    score=int(rc.get("score", 70)),
                    score_breakdown=ScoreBreakdown(
                        hook=int(sb_raw.get("hook", 7)),
                        flow=int(sb_raw.get("flow", 7)),
                        value=int(sb_raw.get("value", 7)),
                        trend=int(sb_raw.get("trend", 7)),
                    ),
                    reason=rc.get("reason", ""),
                    description=rc.get("description", ""),
                    hashtags=tags,
                )
            )
        return sorted(refined, key=lambda c: c.score, reverse=True)
    except Exception as exc:
        logger.warning("[Stage 4] Critic pass fallback to initial selection: {}", exc)
        return clips


# ── Deduplication ─────────────────────────────────────────────────────────────

def _heuristic_select_clips(
    transcript: Transcript,
    user_prompt: Optional[str] = None,
) -> list[dict[str, Any]]:
    """
    Fallback clip candidate generator when cloud LLM API keys are missing/invalid.
    Builds self-contained windows of CLIP_MIN_DURATION..CLIP_MAX_DURATION from
    transcript segments and ranks them by hook strength, sentiment, and speech energy.
    """
    segs = transcript.segments
    if not segs:
        return []

    prompt_keywords = set(re.findall(r"\b[a-zA-Z]{3,}\b", (user_prompt or "").lower()))
    candidates: list[dict[str, Any]] = []
    n = len(segs)
    i = 0

    while i < n:
        start_t = segs[i].start
        j = i
        texts: list[str] = []
        while j < n and (segs[j].end - start_t) < CLIP_MIN_DURATION:
            texts.append(segs[j].text.strip())
            j += 1

        # Extend up to target ~45s or sentence boundary under CLIP_MAX_DURATION
        while j < n and (segs[j].end - start_t) <= min(CLIP_MAX_DURATION, 55):
            texts.append(segs[j].text.strip())
            curr_dur = segs[j].end - start_t
            if curr_dur >= max(CLIP_MIN_DURATION, 30) and re.search(r"[.!?][\"']?$", segs[j].text.strip()):
                j += 1
                break
            j += 1

        end_idx = min(n - 1, max(i, j - 1))
        end_t = segs[end_idx].end
        dur = end_t - start_t

        if CLIP_MIN_DURATION <= dur <= CLIP_MAX_DURATION:
            combined_text = " ".join(t for t in texts if t).strip()
            first_sentence = re.split(r"(?<=[.!?])\s+", combined_text)[0][:90].strip()
            words_in_title = re.findall(r"\b[A-Za-z0-9']+\b", first_sentence)[:6]
            title_str = " ".join(w.capitalize() for w in words_in_title) or f"Highlight {len(candidates) + 1}"

            h_score = compute_hook_score(first_sentence, combined_text[:160])
            s_score = compute_sentiment_score(combined_text)
            e_score = compute_energy_score(start_t, end_t, transcript.all_words)
            base_score = int(round(0.40 * h_score + 0.35 * s_score + 0.25 * e_score))

            if prompt_keywords:
                lower_text = combined_text.lower()
                kw_hits = sum(1 for kw in prompt_keywords if kw in lower_text)
                base_score = min(98, base_score + kw_hits * 8)

            sub_hook = max(5, min(10, int(round(h_score / 10.0))))
            sub_flow = max(5, min(10, int(round(e_score / 10.0))))
            sub_val = max(5, min(10, int(round(s_score / 10.0))))
            sub_trend = max(5, min(10, int(round(base_score / 10.0))))

            candidates.append({
                "start": round(start_t, 2),
                "end": round(end_t, 2),
                "hook": first_sentence or title_str,
                "title": title_str,
                "score": base_score,
                "score_breakdown": {
                    "hook": sub_hook,
                    "flow": sub_flow,
                    "value": sub_val,
                    "trend": sub_trend,
                },
                "reason": "High vocal energy and strong opening statement.",
                "description": f"{first_sentence} 🔥",
                "hashtags": ["shorts", "reels", "fyp", "viral", "highlights"],
            })

        i = max(i + 1, end_idx + 1)

    # If segment boundaries were too wide/sparse to land in [CLIP_MIN_DURATION, CLIP_MAX_DURATION],
    # create uniform 35s windows snapped to word timestamps
    if not candidates and transcript.duration >= CLIP_MIN_DURATION and transcript.all_words:
        all_w = transcript.all_words
        win_dur = min(40.0, float(CLIP_MAX_DURATION))
        t_cur = max(0.0, all_w[0].start)
        while t_cur + CLIP_MIN_DURATION <= transcript.duration and len(candidates) < TOP_N_CLIPS:
            t_end = min(transcript.duration, t_cur + win_dur)
            win_words = [w for w in all_w if t_cur <= w.start <= t_end]
            if win_words:
                s_real = win_words[0].start
                e_real = win_words[-1].end
                if e_real - s_real < CLIP_MIN_DURATION:
                    e_real = min(transcript.duration, s_real + max(CLIP_MIN_DURATION + 2.0, 25.0))
                text_snip = " ".join(w.text.strip() for w in win_words[:20]).strip()
                text_snip = re.sub(r"(\S+)(?:\s+\1){3,}", r"\1", text_snip)[:80]
                idx_num = len(candidates) + 1
                candidates.append({
                    "start": round(s_real, 2),
                    "end": round(e_real, 2),
                    "hook": text_snip or f"Key Moment #{idx_num}",
                    "title": f"Highlight Clip #{idx_num}",
                    "score": max(70, 88 - idx_num * 3),
                    "score_breakdown": {"hook": 8, "flow": 8, "value": 8, "trend": 8},
                    "reason": "Engaging spoken segment",
                    "description": f"{text_snip or 'Inspirational message'} 🔥",
                    "hashtags": ["shorts", "reels", "fyp", "viral", "inspiration"],
                })
            t_cur += win_dur + 5.0

    candidates.sort(key=lambda c: c["score"], reverse=True)
    return candidates[:TOP_N_CLIPS]

def _remove_overlapping(clips: list[Clip]) -> list[Clip]:
    """Remove overlapping clips, keeping the one with the higher score."""
    clips_sorted = sorted(clips, key=lambda c: c.score, reverse=True)
    kept: list[Clip] = []
    for candidate in clips_sorted:
        overlap = False
        for existing in kept:
            # Check for >50% overlap
            overlap_start = max(candidate.start, existing.start)
            overlap_end = min(candidate.end, existing.end)
            if overlap_end > overlap_start:
                overlap_len = overlap_end - overlap_start
                if overlap_len / min(candidate.duration, existing.duration) > 0.5:
                    overlap = True
                    break
        if not overlap:
            kept.append(candidate)
    return kept


# ── Main ──────────────────────────────────────────────────────────────────────

def select_clips(
    transcript: Transcript,
    work_dir: Path,
    user_prompt: Optional[str] = None,
) -> list[Clip]:
    """
    Stage 4 main entry point.

    Args:
        transcript:  output from Stage 3
        work_dir:    project scratch dir
        user_prompt: optional user directive (e.g. 'find moments about pricing')

    Returns:
        List of Clip objects, sorted by score (best first)
    """
    clips_dir = work_dir / "clips"
    clips_dir.mkdir(parents=True, exist_ok=True)
    cache_path = clips_dir / "clips.json"

    # ── Cache hit ─────────────────────────────────────────────────────────────
    # Only reuse cache if there is no specific user_prompt overriding it
    if cache_path.exists() and not user_prompt:
        logger.info("[Stage 4] Loading cached clip selection from {}", cache_path)
        raw = json.loads(cache_path.read_text())
        clips = []
        for c in raw:
            sb = c["score_breakdown"]
            clips.append(Clip(
                start=c["start"], end=c["end"],
                hook=c["hook"], title=c["title"],
                score=c["score"],
                score_breakdown=ScoreBreakdown(**sb),
                reason=c["reason"],
                description=c.get("description", ""),
                hashtags=c.get("hashtags", []),
            ))
        logger.success("[Stage 4] ✓ Loaded {} cached clips", len(clips))
        return clips

    # ── Pass A: Segment transcript into topic blocks ──────────────────────────
    topic_blocks = segment_transcript(transcript)
    logger.info("[Stage 4] Pass A segmented transcript into {} topic blocks", len(topic_blocks))

    # ── Build prompt(s) & call LLM across chunks ──────────────────────────────
    prompt_template = (
        Path(__file__).parent.parent / "prompts" / "v1" / "clip_selection.txt"
    ).read_text()

    transcript_chunks = _chunk_transcript_for_llm(transcript)
    raw_clips: list[dict[str, Any]] = []

    for chunk_idx, formatted_chunk in enumerate(transcript_chunks, 1):
        prompt = (
            prompt_template
            .replace("{CLIP_MIN}", str(CLIP_MIN_DURATION))
            .replace("{CLIP_MAX}", str(CLIP_MAX_DURATION))
            .replace("{TOP_N}", str(TOP_N_CLIPS))
            .replace("{TRANSCRIPT}", formatted_chunk)
        )

        if user_prompt:
            prompt += (
                f"\n\nIMPORTANT USER DIRECTIVE / FOCUS TOPIC:\n"
                f"The user explicitly requested clips covering: \"{user_prompt}\".\n"
                f"Prioritize moments from the transcript that directly relate to this theme while maintaining high virality.\n"
            )

        logger.info(
            "[Stage 4] Sending transcript chunk {}/{} to LLM ({} chars in prompt) …",
            chunk_idx, len(transcript_chunks), len(prompt),
        )
        t0 = time.time()
        try:
            raw_response = _call_llm(prompt)
            elapsed = time.time() - t0
            logger.info("[Stage 4] LLM responded for chunk {}/{} in {:.1f}s", chunk_idx, len(transcript_chunks), elapsed)
            parsed = _extract_json(raw_response)
            chunk_clips = parsed.get("clips", [])
            raw_clips.extend(chunk_clips)
        except Exception as llm_exc:
            logger.warning(
                "[Stage 4] LLM call/parse failed ({}); using heuristic topic & hook selector fallback",
                llm_exc,
            )
            raw_clips = _heuristic_select_clips(transcript, user_prompt=user_prompt)
            break

    logger.info("[Stage 4] LLM returned {} raw clip candidates", len(raw_clips))
    if not raw_clips and transcript.duration >= CLIP_MIN_DURATION:
        logger.info("[Stage 4] Using heuristic clip selector fallback for {:.1f}s video", transcript.duration)
        raw_clips = _heuristic_select_clips(transcript, user_prompt=user_prompt)

    all_words = transcript.all_words
    valid_start_times = {round(w.start, 1) for w in all_words}

    def _build_clips_from_raw(candidates_list: list[dict[str, Any]]) -> list[Clip]:
        built: list[Clip] = []
        for rc in candidates_list:
            try:
                start = float(rc["start"])
                end = float(rc["end"])

                # Validate timestamps exist in transcript (within 2s tolerance)
                if valid_start_times and not any(abs(t - start) < 2.0 for t in valid_start_times):
                    logger.warning(
                        "[Stage 4] Skipping clip {:.1f}s — start time not in transcript",
                        start,
                    )
                    continue

                # Validate duration constraints
                duration = end - start
                if duration < CLIP_MIN_DURATION or duration > CLIP_MAX_DURATION:
                    logger.warning(
                        "[Stage 4] Skipping clip {:.1f}s–{:.1f}s — duration {:.1f}s out of range",
                        start, end, duration,
                    )
                    continue

                # Snap to word boundaries
                start, end = _snap_to_word_boundary(start, end, all_words)

                sb_raw = rc.get("score_breakdown", {})
                raw_tags = rc.get("hashtags", [])
                tags = [str(h).lstrip("#") for h in raw_tags if str(h).strip()] if isinstance(raw_tags, list) else []
                hook_str = rc.get("hook", "")
                llm_score = float(rc.get("score", 50))
                final_score = compute_blended_score(
                    llm_score=llm_score,
                    clip_start=start,
                    clip_end=end,
                    hook_text=hook_str,
                    transcript=transcript,
                )

                built.append(Clip(
                    start=round(start, 3),
                    end=round(end, 3),
                    hook=hook_str,
                    title=rc.get("title", ""),
                    score=final_score,
                    score_breakdown=ScoreBreakdown(
                        hook=int(sb_raw.get("hook", 5)),
                        flow=int(sb_raw.get("flow", 5)),
                        value=int(sb_raw.get("value", 5)),
                        trend=int(sb_raw.get("trend", 5)),
                    ),
                    reason=rc.get("reason", ""),
                    description=rc.get("description", ""),
                    hashtags=tags,
                ))
            except (KeyError, ValueError, TypeError) as e:
                logger.warning("[Stage 4] Skipping malformed clip: {} — {}", rc, e)
        return built

    clips = _build_clips_from_raw(raw_clips)
    if not clips and transcript.duration >= CLIP_MIN_DURATION:
        fallback_raw = _heuristic_select_clips(transcript, user_prompt=user_prompt)
        clips = _build_clips_from_raw(fallback_raw)

    # ── Deduplicate, optional critic pass, & rank ─────────────────────────────
    clips = _remove_overlapping(clips)
    if ENABLE_CRITIC_PASS and len(clips) > 1:
        clips = critic_pass(clips, transcript)
    clips = sorted(clips, key=lambda c: c.score, reverse=True)[:TOP_N_CLIPS]

    # ── Save ──────────────────────────────────────────────────────────────────
    cache_path.write_text(
        json.dumps([c.to_dict() for c in clips], indent=2, ensure_ascii=False)
    )

    logger.success(
        "[Stage 4] ✓ Selected {} clips | scores: {}",
        len(clips),
        [c.score for c in clips],
    )
    return clips


# ── Metadata Generator for Existing Clips ─────────────────────────────────────

def generate_clip_metadata(clip: Clip, transcript: Transcript) -> dict[str, Any]:
    """
    Generate platform-optimized social metadata for a clip:
    - title: catchy, hooky title (under 50 chars)
    - description: engaging 1-2 sentence video caption with emojis
    - hashtags: 6-8 trending tags (#fyp, #shorts, #reels, etc.)
    """
    clip_text = " ".join(
        w.text for seg in transcript.segments for w in seg.words
        if clip.start - 0.5 <= w.start <= clip.end + 0.5
    )

    prompt = f"""You are an expert social media manager for TikTok, YouTube Shorts, and Instagram Reels.
Given the following spoken dialogue from a short-form video clip, generate:
1. "title": A high-converting, curiosity-inducing title (max 50 chars).
2. "description": A punchy 1-2 sentence caption with 2-3 emojis.
3. "hashtags": An array of 6-8 relevant hashtags without the '#' symbol.

CLIP TRANSCRIPT:
"{clip_text or clip.hook or clip.title}"

Return ONLY a valid JSON object matching this schema:
{{
  "title": "string",
  "description": "string",
  "hashtags": ["string"]
}}
"""
    try:
        raw = _call_llm(prompt)
        res = _extract_json(raw)
        tags = [str(h).lstrip("#") for h in res.get("hashtags", []) if str(h).strip()]
        return {
            "title": res.get("title", clip.title),
            "description": res.get("description", ""),
            "hashtags": tags or ["viral", "shorts", "reels", "fyp", "trending"],
        }
    except Exception as exc:
        logger.warning("[Stage 4] Metadata generation fallback: {}", exc)
        return {
            "title": clip.title or "Viral Moment",
            "description": clip.hook or "Check out this key takeaway! 🔥",
            "hashtags": ["viral", "shorts", "reels", "fyp", "trending"],
        }

