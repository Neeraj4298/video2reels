"use client";

import { STAGES, stageIndex } from "@/lib/utils";
import type { ProgressEvent } from "@/lib/types";

interface PipelineProps {
  currentEvent: ProgressEvent | null;
  jobs?: { stage: string | null; status: string }[];
}

type StepState = "idle" | "active" | "done" | "failed";

export function PipelineSteps({ currentEvent, jobs = [] }: PipelineProps) {
  function getState(stageKey: string): StepState {
    // Check job records first
    const job = jobs.find((j) => j.stage === stageKey);
    if (job) {
      if (job.status === "done") return "done";
      if (job.status === "running") return "active";
      if (job.status === "failed") return "failed";
    }

    // Fall back to SSE event
    if (!currentEvent) return "idle";
    const activeIdx = stageIndex(currentEvent.stage);
    const thisIdx = stageIndex(stageKey);
    if (activeIdx === -1) return "idle";
    if (thisIdx < activeIdx) return "done";
    if (thisIdx === activeIdx) return "active";
    return "idle";
  }

  return (
    <div className="pipeline-steps">
      {STAGES.map((stage) => {
        const state = getState(stage.key);
        return (
          <div key={stage.key} className={`pipeline-step ${state}`}>
            <div className={`step-dot ${state}`}>
              {state === "done" ? "✓" : state === "failed" ? "✗" : stage.icon}
            </div>
            <span className="step-label">{stage.label}</span>
          </div>
        );
      })}
    </div>
  );
}
