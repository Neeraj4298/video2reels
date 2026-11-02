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
from typing import Optional

from loguru import logger
from workers.config import (
    LLM_PROVIDER, GEMINI_API_KEY, ANTHROPIC_API_KEY,
    CLIP_MIN_DURATION, CLIP_MAX_DURATION, TOP_N_CLIPS,
)
from workers.transcribe import Transcript, Word


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


# ── Transcript formatting ─────────────────────────────────────────────────────

def _format_transcript_for_llm(transcript: Transcript, max_chars: int = 80_000) -> str:
    """
    Format transcript as numbered, timestamped lines for LLM consumption.
    Keeps lines short to avoid overwhelming the context window.
    """
    lines = []
    for i, seg in enumerate(transcript.segments, 1):
        lines.append(f"[{i:04d}] {seg.start:.2f}s–{seg.end:.2f}s: {seg.text.strip()}")

    text = "\n".join(lines)
    if len(text) > max_chars:
        # Truncate with warning — split into chunks in v2
        logger.warning(
            "Transcript too long ({} chars), truncating to {}. "
            "Some content may be missed.",
            len(text), max_chars,
        )
        text = text[:max_chars]
    return text


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
    from google import genai
    from google.genai import types

    client = genai.Client(api_key=GEMINI_API_KEY)
    response = client.models.generate_content(
        model="gemini-2.0-flash",
        contents=prompt,
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
        ),
    )
    return response.text


def _call_anthropic(prompt: str) -> str:
    import anthropic
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    message = client.messages.create(
        model="claude-3-5-haiku-20241022",
        max_tokens=4096,
        messages=[{"role": "user", "content": prompt}],
    )
    return message.content[0].text


def _call_llm(prompt: str) -> str:
    """Dispatch to the configured LLM provider."""
    provider = LLM_PROVIDER.lower()
    logger.info("[Stage 4] Calling LLM provider: {}", provider)
    if provider == "gemini":
        return _call_gemini(prompt)
    elif provider == "anthropic":
        return _call_anthropic(prompt)
    else:
        raise ValueError(f"Unknown LLM_PROVIDER: {provider}. Use gemini or anthropic.")


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


# ── Deduplication ─────────────────────────────────────────────────────────────

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

    # ── Build prompt ──────────────────────────────────────────────────────────
    prompt_template = (
        Path(__file__).parent.parent / "prompts" / "v1" / "clip_selection.txt"
    ).read_text()

    formatted_transcript = _format_transcript_for_llm(transcript)
    prompt = (
        prompt_template
        .replace("{CLIP_MIN}", str(CLIP_MIN_DURATION))
        .replace("{CLIP_MAX}", str(CLIP_MAX_DURATION))
        .replace("{TOP_N}", str(TOP_N_CLIPS))
        .replace("{TRANSCRIPT}", formatted_transcript)
    )

    if user_prompt:
        prompt += (
            f"\n\nIMPORTANT USER DIRECTIVE / FOCUS TOPIC:\n"
            f"The user explicitly requested clips covering: \"{user_prompt}\".\n"
            f"Prioritize moments from the transcript that directly relate to this theme while maintaining high virality.\n"
        )

    # ── LLM call ──────────────────────────────────────────────────────────────
    logger.info("[Stage 4] Sending transcript to LLM ({} chars in prompt) …", len(prompt))
    t0 = time.time()
    raw_response = _call_llm(prompt)
    elapsed = time.time() - t0
    logger.info("[Stage 4] LLM responded in {:.1f}s", elapsed)

    # ── Parse & validate ──────────────────────────────────────────────────────
    parsed = _extract_json(raw_response)
    raw_clips = parsed.get("clips", [])
    logger.info("[Stage 4] LLM returned {} raw clip candidates", len(raw_clips))

    all_words = transcript.all_words
    valid_start_times = {round(w.start, 1) for w in all_words}

    clips: list[Clip] = []
    for rc in raw_clips:
        try:
            start = float(rc["start"])
            end = float(rc["end"])

            # Validate timestamps exist in transcript (within 2s tolerance)
            if not any(abs(t - start) < 2.0 for t in valid_start_times):
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

            clips.append(Clip(
                start=round(start, 3),
                end=round(end, 3),
                hook=rc.get("hook", ""),
                title=rc.get("title", ""),
                score=int(rc.get("score", 50)),
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

    # ── Deduplicate & rank ────────────────────────────────────────────────────
    clips = _remove_overlapping(clips)
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

