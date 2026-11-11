"""
Platform, Credits, Evaluation Harness, Stage Runs & MCP Server Router
─────────────────────────────────────────────────────────────────────
Implements:
  - Credit system (OpusClip rules: 1 credit/min, <1m -> 1, >=1m -> floor, X post = +3 credits)
  - Clip feedback & Virality Score weight calibration (`POST /api/clips/{id}/feedback`)
  - Stage runs history (`GET /api/projects/{id}/stage-runs`)
  - Evaluation harness report (`GET /api/eval/report`)
  - Model Context Protocol (MCP) agentic tool discovery & execution (`/api/mcp/tools`, `/api/mcp/call`)
"""
from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.db import get_db
from api.models import (
    Clip,
    CreditLedger,
    FeedbackEvent,
    Organization,
    Project,
    ProjectStatus,
    SourceType,
    StageRun,
)
from workers.eval_harness import run_golden_eval_suite
from workers.ingest import compute_video_credits
from workers.select_clips import calibrate_blend_weights

router = APIRouter(tags=["platform"])


class CreditEstimateRequest(BaseModel):
    duration_seconds: float
    platform: str | None = None


class CreditChargeRequest(BaseModel):
    org_id: uuid.UUID | None = None
    project_id: uuid.UUID | None = None
    credits: int
    reason: str = "video_processing"


class FeedbackCreateRequest(BaseModel):
    action: str  # "kept", "trimmed", "exported", "published", "rejected"
    notes: str | None = None


class MCPToolCallRequest(BaseModel):
    tool: str
    arguments: dict[str, Any] = {}


def compute_operation_credits(duration_seconds: float, platform: str | None = None) -> int:
    """
    Compute total credits for processing a video or publishing to a social platform.
    Posting to X (Twitter) incurs a mandatory 3-credit surcharge per post.
    """
    base = compute_video_credits(duration_seconds) if duration_seconds > 0 else 0
    surcharge = 3 if (platform or "").strip().lower() in ("x", "twitter") else 0
    return base + surcharge


@router.post("/api/credits/estimate", response_model=dict)
async def estimate_credits(body: CreditEstimateRequest):
    """Estimate credit consumption before processing a video or social post."""
    cost = compute_operation_credits(body.duration_seconds, body.platform)
    return {
        "duration_seconds": body.duration_seconds,
        "platform": body.platform,
        "estimated_credits": cost,
    }


@router.get("/api/credits/balance", response_model=dict)
async def get_credit_balance(db: AsyncSession = Depends(get_db)):
    """Return current organization credit balance and recent ledger entries."""
    org = (await db.execute(select(Organization))).scalars().first()
    if not org:
        org = Organization(name="Default Workspace", plan_tier="PRO", credits_remaining=300)
        db.add(org)
        await db.commit()
        await db.refresh(org)

    ledger = (
        await db.execute(
            select(CreditLedger).where(CreditLedger.org_id == org.id).order_by(CreditLedger.created_at.desc()).limit(20)
        )
    ).scalars().all()
    return {
        "org_id": str(org.id),
        "plan_tier": org.plan_tier,
        "credits_remaining": org.credits_remaining,
        "ledger": [
            {
                "id": str(entry.id),
                "delta": entry.delta,
                "reason": entry.reason,
                "balance_after": entry.balance_after,
            }
            for entry in ledger
        ],
    }


@router.post("/api/credits/charge", response_model=dict)
async def charge_credits(body: CreditChargeRequest, db: AsyncSession = Depends(get_db)):
    """Deduct (or refund if negative) credits in the append-only ledger."""
    org = (await db.execute(select(Organization))).scalars().first()
    if not org:
        org = Organization(name="Default Workspace", plan_tier="PRO", credits_remaining=300)
        db.add(org)
        await db.flush()

    if body.credits > 0 and org.credits_remaining < body.credits:
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail=f"Insufficient credits: need {body.credits}, have {org.credits_remaining}",
        )

    delta = -body.credits
    org.credits_remaining += delta
    entry = CreditLedger(
        org_id=org.id,
        project_id=body.project_id,
        delta=delta,
        reason=body.reason,
        balance_after=org.credits_remaining,
    )
    db.add(entry)
    await db.commit()
    return {
        "org_id": str(org.id),
        "delta": delta,
        "credits_remaining": org.credits_remaining,
        "reason": body.reason,
    }


@router.post("/api/clips/{clip_id}/feedback", response_model=dict)

async def record_clip_feedback(
    clip_id: uuid.UUID,
    body: FeedbackCreateRequest,
    db: AsyncSession = Depends(get_db),
):
    """Record human clip feedback (kept, trimmed, exported, published, rejected) and recalibrate weights."""
    valid_actions = {"kept", "trimmed", "exported", "published", "rejected"}
    action = body.action.strip().lower()
    if action not in valid_actions:
        raise HTTPException(status_code=400, detail=f"Invalid feedback action {body.action!r}")

    clip = await db.get(Clip, clip_id)
    if not clip:
        raise HTTPException(status_code=404, detail="Clip not found")

    ev = FeedbackEvent(
        project_id=clip.project_id,
        clip_id=clip.id,
        action=action,
        payload={"score": clip.score, "score_breakdown": clip.score_breakdown, "notes": body.notes},
    )
    db.add(ev)
    await db.commit()

    all_events = (await db.execute(select(FeedbackEvent))).scalars().all()
    event_dicts = [
        {"action": e.action, "score_breakdown": (e.payload or {}).get("score_breakdown") or {}}
        for e in all_events
    ]
    calibrated = calibrate_blend_weights(event_dicts)
    return {
        "clip_id": str(clip_id),
        "action": action,
        "total_feedback_events": len(event_dicts),
        "calibrated_weights": calibrated,
    }


@router.get("/api/projects/{project_id}/stage-runs", response_model=list[dict])
async def list_project_stage_runs(project_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    """Return granular per-(stage, attempt) execution records for a project."""
    runs = (
        await db.execute(
            select(StageRun).where(StageRun.project_id == project_id).order_by(StageRun.started_at.asc())
        )
    ).scalars().all()
    return [
        {
            "id": str(r.id),
            "project_id": str(r.project_id),
            "stage": r.stage,
            "status": r.status.value if hasattr(r.status, "value") else str(r.status),
            "attempt": r.attempt,
            "progress": r.progress,
            "model_version": r.model_version,
            "prompt_version": r.prompt_version,
            "error": r.error,
        }
        for r in runs
    ]


@router.get("/api/eval/report", response_model=dict)
async def get_evaluation_report():
    """Run the golden evaluation harness and return all quality metrics & target gates."""
    report = run_golden_eval_suite()
    return report.to_dict()


MCP_TOOLS_CATALOG = [
    {"name": "opusclip_list_projects", "category": "read", "description": "List video clipping projects."},
    {"name": "opusclip_list_clips", "category": "read", "description": "List generated viral clips for a project."},
    {"name": "opusclip_get_usage", "category": "read", "description": "Retrieve plan tier and remaining credits."},
    {"name": "opusclip_submit_project", "category": "write", "description": "Submit a video URL for clipping."},
    {"name": "opusclip_edit_clip", "category": "write", "description": "Update a clip's EDL or metadata."},
]


@router.get("/api/mcp/tools", response_model=dict)
async def list_mcp_tools():
    """Expose MCP tool definitions for AI agents (Claude Code, Cursor, Codex)."""
    return {"version": "0.4.0", "tools": MCP_TOOLS_CATALOG}


@router.post("/api/mcp/call", response_model=dict)
async def call_mcp_tool(body: MCPToolCallRequest, db: AsyncSession = Depends(get_db)):
    """Execute an MCP tool call against the video2reels service layer."""
    tool = body.tool.strip()
    args = body.arguments or {}

    if tool == "opusclip_list_projects":
        projs = (await db.execute(select(Project).order_by(Project.created_at.desc()).limit(25))).scalars().all()
        return {
            "tool": tool,
            "result": [{"id": str(p.id), "name": p.name, "status": p.status.value} for p in projs],
        }
    if tool == "opusclip_list_clips":
        pid = uuid.UUID(str(args["project_id"]))
        clips = (
            await db.execute(select(Clip).where(Clip.project_id == pid).order_by(Clip.score.desc().nullslast()))
        ).scalars().all()
        return {
            "tool": tool,
            "result": [
                {"id": str(c.id), "title": c.title, "hook": c.hook, "score": c.score, "start": c.start, "end": c.end}
                for c in clips
            ],
        }
    if tool == "opusclip_get_usage":
        balance = await get_credit_balance(db)
        return {"tool": tool, "result": balance}
    if tool == "opusclip_submit_project":
        url = str(args.get("source_url") or "")
        p = Project(
            name=str(args.get("name") or "MCP Project"),
            source_type=SourceType.url if url else SourceType.upload,
            source_url=url or None,
            status=ProjectStatus.pending,
        )
        db.add(p)
        await db.commit()
        await db.refresh(p)
        return {"tool": tool, "result": {"project_id": str(p.id), "status": p.status.value}}
    if tool == "opusclip_edit_clip":
        cid = uuid.UUID(str(args["clip_id"]))
        clip = await db.get(Clip, cid)
        if not clip:
            raise HTTPException(status_code=404, detail="Clip not found")
        if "title" in args:
            clip.title = str(args["title"])
        if "hook" in args:
            clip.hook = str(args["hook"])
        await db.commit()
        return {"tool": tool, "result": {"clip_id": str(clip.id), "title": clip.title, "hook": clip.hook}}

    raise HTTPException(status_code=400, detail=f"Unknown MCP tool: {tool}")

