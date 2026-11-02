"use client";
export const dynamic = "force-dynamic";

import { useState } from "react";
import { useParams } from "next/navigation";
import useSWR from "swr";
import Link from "next/link";
import { Sidebar } from "@/components/Sidebar";
import { ToastContainer, toast } from "@/components/Toast";
import { ScoreRing } from "@/components/ScoreRing";
import { api, fetcher } from "@/lib/api";
import type { Clip, ProjectDetail } from "@/lib/types";
import { formatDuration, scoreColor } from "@/lib/utils";

// ─── Sort / Filter ────────────────────────────────────────────────────────────
type SortKey = "score" | "duration" | "start";

function sortClips(clips: Clip[], key: SortKey): Clip[] {
  return [...clips].sort((a, b) => {
    if (key === "score") return (b.score ?? -1) - (a.score ?? -1);
    if (key === "duration") return (b.end - b.start) - (a.end - a.start);
    return a.start - b.start;
  });
}

// ─── Clip Card ─────────────────────────────────────────────────────────────────
function ClipCard({ clip, projectId, onToggle }: {
  clip: Clip;
  projectId: string;
  onToggle: () => void;
}) {
  const [toggling, setToggling] = useState(false);
  const colorClass = scoreColor(clip.score);
  const duration = clip.end - clip.start;

  async function toggleSelected(e: React.MouseEvent) {
    e.preventDefault();
    e.stopPropagation();
    setToggling(true);
    try {
      await api.clips.update(clip.id, { selected: !clip.selected });
      onToggle();
    } catch {
      toast("Failed to update clip", "error");
    } finally {
      setToggling(false);
    }
  }

  return (
    <Link
      href={`/projects/${projectId}/clips/${clip.id}`}
      className={`clip-card ${clip.selected ? "selected-clip" : ""}`}
      style={{ display: "block", textDecoration: "none" }}
    >
      {/* Thumbnail */}
      <div className="clip-thumbnail">
        <div className="clip-thumbnail-placeholder">🎬</div>

        {/* Score overlay */}
        <div className="clip-score-overlay">
          <ScoreRing score={clip.score} size={42} />
        </div>

        {/* Duration overlay */}
        <div className="clip-duration-overlay">
          {formatDuration(duration)}
        </div>
      </div>

      {/* Card body */}
      <div className="clip-card-body">
        <div className="clip-title">
          {clip.title ?? `Clip ${formatDuration(clip.start)}–${formatDuration(clip.end)}`}
        </div>
        {clip.hook && <div className="clip-hook">{clip.hook}</div>}

        <div className="flex items-center justify-between mt-3">
          {/* Score badge */}
          <span className={`score-badge ${colorClass}`}>
            {clip.score ?? "—"}
          </span>

          {/* Select toggle */}
          <button
            className={`btn btn-sm ${clip.selected ? "btn-primary" : "btn-secondary"}`}
            onClick={toggleSelected}
            disabled={toggling}
            id={`select-clip-${clip.id}`}
            title={clip.selected ? "Deselect clip" : "Select clip"}
          >
            {toggling ? <span className="spinner" /> : clip.selected ? "✓ Selected" : "Select"}
          </button>
        </div>

        {/* Hashtags */}
        {clip.hashtags && clip.hashtags.length > 0 && (
          <div className="flex gap-1 mt-2" style={{ flexWrap: "wrap" }}>
            {clip.hashtags.slice(0, 3).map((tag) => (
              <span
                key={tag}
                className="badge"
                style={{
                  background: "rgba(124,58,237,0.1)",
                  color: "var(--accent-400)",
                  border: "1px solid var(--border-subtle)",
                  fontSize: "0.7rem",
                }}
              >
                #{tag}
              </span>
            ))}
          </div>
        )}
      </div>
    </Link>
  );
}

// ─── Clips Page ────────────────────────────────────────────────────────────────
export default function ClipsPage() {
  const { id } = useParams<{ id: string }>();
  const [sortKey, setSortKey] = useState<SortKey>("score");
  const [filterSelected, setFilterSelected] = useState(false);

  const { data: project } = useSWR<ProjectDetail>(
    id ? `/api/projects/${id}` : null,
    fetcher
  );
  const { data: clips, mutate } = useSWR<Clip[]>(
    id ? `/api/projects/${id}/clips` : null,
    fetcher,
    { refreshInterval: 10000 }
  );

  const [showReclipModal, setShowReclipModal] = useState(false);
  const [userPrompt, setUserPrompt] = useState("");
  const [reclipping, setReclipping] = useState(false);

  async function handleReclip(e: React.FormEvent) {
    e.preventDefault();
    setReclipping(true);
    try {
      await api.projects.reclip(id as string, userPrompt.trim() || undefined);
      toast("Re-clipping initiated! Processing in background…", "success");
      setShowReclipModal(false);
      mutate();
    } catch (err: unknown) {
      toast(err instanceof Error ? err.message : "Failed to initiate re-clipping", "error");
    } finally {
      setReclipping(false);
    }
  }

  const displayed = (() => {
    let c = clips ?? [];
    if (filterSelected) c = c.filter((cl) => cl.selected);
    return sortClips(c, sortKey);
  })();

  const selectedCount = clips?.filter((c) => c.selected).length ?? 0;
  const avgScore = clips && clips.length > 0
    ? Math.round(clips.reduce((s, c) => s + (c.score ?? 0), 0) / clips.length)
    : null;

  return (
    <div className="app-shell">
      <Sidebar />
      <main className="main-content">
        {/* Breadcrumb */}
        <div className="flex items-center gap-3 mb-6" style={{ color: "var(--text-muted)", fontSize: "0.875rem" }}>
          <Link href="/" style={{ color: "var(--text-muted)", textDecoration: "none" }}>Projects</Link>
          <span>/</span>
          <Link href={`/projects/${id}`} style={{ color: "var(--text-muted)", textDecoration: "none" }}>
            {project?.name ?? id}
          </Link>
          <span>/</span>
          <span style={{ color: "var(--text-primary)" }}>Clips</span>
        </div>

        {/* Header */}
        <div className="page-header">
          <div>
            <h1 className="page-title">Clips</h1>
            <p className="page-subtitle">
              {clips ? `${clips.length} clips · ${selectedCount} selected` : "Loading…"}
              {avgScore !== null && ` · avg score ${avgScore}`}
            </p>
          </div>
          <div className="flex gap-2 items-center">
            <a
              href={api.projects.exportZipUrl(id as string)}
              download
              className="btn btn-secondary btn-sm"
              id="export-zip-btn"
              title="Download ZIP bundle containing all rendered reels, subtitles, and metadata"
            >
              📦 Export All (ZIP)
            </a>
            <button
              onClick={() => setShowReclipModal(true)}
              className="btn btn-primary btn-sm"
              id="reclip-btn"
            >
              ✨ Re-clip with Prompt
            </button>
            <Link href={`/projects/${id}`} className="btn btn-secondary btn-sm">
              ← Project
            </Link>
          </div>
        </div>

        {/* Re-clip Modal */}
        {showReclipModal && (
          <div
            style={{
              position: "fixed",
              inset: 0,
              background: "rgba(0,0,0,0.75)",
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              zIndex: 1000,
              backdropFilter: "blur(4px)",
            }}
          >
            <div className="card" style={{ maxWidth: 480, width: "90%", margin: "auto" }}>
              <div className="card-body">
                <div className="flex items-center justify-between mb-4">
                  <h3 style={{ fontSize: "1.25rem", fontWeight: 700 }}>✨ Re-clip with AI Prompt</h3>
                  <button
                    className="btn btn-secondary btn-sm"
                    onClick={() => setShowReclipModal(false)}
                  >
                    ✕
                  </button>
                </div>
                <p style={{ color: "var(--text-secondary)", fontSize: "0.875rem", marginBottom: "var(--space-4)" }}>
                  Direct the AI to find specific moments (e.g. &ldquo;Find actionable tips about scaling&rdquo;, &ldquo;Extract humorous banter&rdquo;, or &ldquo;Focus on the product demo&rdquo;).
                </p>
                <form onSubmit={handleReclip}>
                  <div className="form-group mb-4">
                    <label htmlFor="user-prompt">AI Extraction Prompt (Optional)</label>
                    <textarea
                      id="user-prompt"
                      className="input"
                      rows={3}
                      placeholder="e.g. Find moments where the speaker discusses pricing and revenue growth..."
                      value={userPrompt}
                      onChange={(e) => setUserPrompt(e.target.value)}
                    />
                  </div>
                  <div className="flex justify-end gap-3">
                    <button
                      type="button"
                      className="btn btn-secondary"
                      onClick={() => setShowReclipModal(false)}
                      disabled={reclipping}
                    >
                      Cancel
                    </button>
                    <button
                      type="submit"
                      className="btn btn-primary"
                      disabled={reclipping}
                    >
                      {reclipping ? <><span className="spinner" /> Re-clipping…</> : "Run AI Clipping"}
                    </button>
                  </div>
                </form>
              </div>
            </div>
          </div>
        )}

        {/* Toolbar */}
        <div className="card mb-6">
          <div className="card-body" style={{ padding: "var(--space-4)", display: "flex", alignItems: "center", gap: "var(--space-4)", flexWrap: "wrap" }}>
            {/* Sort */}
            <div className="flex items-center gap-2">
              <label style={{ fontSize: "0.875rem" }}>Sort:</label>
              <select
                className="select"
                style={{ width: "auto" }}
                value={sortKey}
                onChange={(e) => setSortKey(e.target.value as SortKey)}
              >
                <option value="score">By Score ↓</option>
                <option value="duration">By Duration ↓</option>
                <option value="start">By Time ↑</option>
              </select>
            </div>

            {/* Filter */}
            <label className="flex items-center gap-2" style={{ cursor: "pointer", fontSize: "0.875rem" }}>
              <input
                type="checkbox"
                checked={filterSelected}
                onChange={(e) => setFilterSelected(e.target.checked)}
                style={{ accentColor: "var(--accent-500)", width: 16, height: 16 }}
              />
              Show selected only
            </label>

            <span style={{ marginLeft: "auto", color: "var(--text-muted)", fontSize: "0.875rem" }}>
              {displayed.length} clip{displayed.length !== 1 ? "s" : ""}
            </span>
          </div>
        </div>

        {/* Score distribution */}
        {clips && clips.length > 0 && (
          <div
            className="card mb-6"
            style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)" }}
          >
            {(["score-green", "score-yellow", "score-red"] as const).map((cls, i) => {
              const labels = ["High (80+)", "Medium (60–79)", "Low (<60)"];
              const counts = [
                clips.filter((c) => (c.score ?? 0) >= 80).length,
                clips.filter((c) => (c.score ?? 0) >= 60 && (c.score ?? 0) < 80).length,
                clips.filter((c) => (c.score ?? 0) < 60).length,
              ];
              return (
                <div
                  key={cls}
                  className="card-body text-center"
                  style={{ borderRight: i < 2 ? "1px solid var(--border-subtle)" : undefined }}
                >
                  <div style={{ fontSize: "1.75rem", fontWeight: 800 }} className={cls.replace("score-", "text-")}>
                    {counts[i]}
                  </div>
                  <small>{labels[i]}</small>
                </div>
              );
            })}
          </div>
        )}

        {/* Loading */}
        {!clips && (
          <div className="empty-state">
            <div className="spinner spinner-lg" />
            <p>Loading clips…</p>
          </div>
        )}

        {/* Empty */}
        {clips?.length === 0 && (
          <div className="empty-state">
            <div className="empty-icon">✂️</div>
            <h2>No clips yet</h2>
            <p>The pipeline hasn't completed clip selection.</p>
            <Link href={`/projects/${id}`} className="btn btn-secondary mt-4">
              Check progress →
            </Link>
          </div>
        )}

        {/* Clip Grid */}
        {displayed.length > 0 && (
          <div className="clip-grid">
            {displayed.map((clip) => (
              <ClipCard
                key={clip.id}
                clip={clip}
                projectId={id}
                onToggle={() => mutate()}
              />
            ))}
          </div>
        )}
      </main>
      <ToastContainer />
    </div>
  );
}
