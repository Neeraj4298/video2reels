"use client";

import { scoreColor } from "@/lib/utils";

interface ScoreRingProps {
  score: number | null;
  size?: number;
  strokeWidth?: number;
}

export function ScoreRing({ score, size = 48, strokeWidth = 4 }: ScoreRingProps) {
  const r = (size - strokeWidth * 2) / 2;
  const circumference = 2 * Math.PI * r;
  const pct = score ?? 0;
  const offset = circumference - (pct / 100) * circumference;

  const colorClass = scoreColor(score);
  const strokeColor =
    colorClass === "score-green"
      ? "var(--green-400)"
      : colorClass === "score-yellow"
      ? "var(--amber-400)"
      : colorClass === "score-red"
      ? "var(--rose-400)"
      : "var(--text-muted)";

  return (
    <div className="score-ring" style={{ width: size, height: size }}>
      <svg width={size} height={size}>
        <circle
          cx={size / 2}
          cy={size / 2}
          r={r}
          fill="none"
          stroke="rgba(255,255,255,0.06)"
          strokeWidth={strokeWidth}
        />
        <circle
          cx={size / 2}
          cy={size / 2}
          r={r}
          fill="none"
          stroke={strokeColor}
          strokeWidth={strokeWidth}
          strokeDasharray={circumference}
          strokeDashoffset={offset}
          strokeLinecap="round"
          style={{ transition: "stroke-dashoffset 0.8s ease" }}
        />
      </svg>
      <span className="score-ring-label" style={{ color: strokeColor }}>
        {score ?? "—"}
      </span>
    </div>
  );
}
