"use client";

import { useCallback, useRef, useState } from "react";
import useSWR from "swr";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { Sidebar } from "@/components/Sidebar";
import { ToastContainer, toast } from "@/components/Toast";
import { api, fetcher } from "@/lib/api";
import type { Project } from "@/lib/types";
import { formatDate } from "@/lib/utils";

// ─── Status helpers ───────────────────────────────────────────────────────────

function StatusBadge({ status }: { status: string }) {
  const icons: Record<string, string> = {
    pending: "⏳",
    processing: "⚡",
    done: "✅",
    failed: "❌",
    paused: "⏸",
  };
  return (
    <span className={`badge status-badge-${status}`}>
      {icons[status] ?? "•"} {status}
    </span>
  );
}

// ─── Create Project Modal ─────────────────────────────────────────────────────

type Tab = "url" | "upload";

function CreateModal({ onClose, onCreated }: {
  onClose: () => void;
  onCreated: (p: Project) => void;
}) {
  const [tab, setTab] = useState<Tab>("url");
  const [url, setUrl] = useState("");
  const [name, setName] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [dragging, setDragging] = useState(false);
  const [loading, setLoading] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);

  const handleDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    setDragging(false);
    const f = e.dataTransfer.files[0];
    if (f && f.type.startsWith("video/")) {
      setFile(f);
      if (!name) setName(f.name.replace(/\.[^.]+$/, ""));
    }
  }, [name]);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setLoading(true);
    try {
      if (tab === "url") {
        if (!url.trim()) { toast("Enter a URL", "error"); return; }
        const project = await api.projects.create({ name: name || undefined, source_url: url.trim() });
        onCreated(project);
      } else {
        // Upload mode: create project first, then get presigned URL, then PUT file
        if (!file) { toast("Select a video file", "error"); return; }
        const project = await api.projects.create({ name: name || file.name });
        const { upload_url, storage_key } = await api.projects.presignedUpload(
          project.id,
          file.name
        );
        // Upload directly to MinIO via presigned PUT
        await fetch(upload_url, {
          method: "PUT",
          body: file,
          headers: { "Content-Type": file.type },
        });
        // Notify API that upload is complete
        await fetch(`${localStorage.getItem("api_base") || "http://localhost:8000"}/api/uploads/complete`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ project_id: project.id, storage_key }),
        });
        onCreated(project);
      }
    } catch (err) {
      toast(`Error: ${String(err)}`, "error");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="modal-overlay" onClick={(e) => e.target === e.currentTarget && onClose()}>
      <div className="modal">
        <div className="flex items-center justify-between mb-6">
          <h2>New Project</h2>
          <button className="btn btn-ghost btn-sm" onClick={onClose}>✕</button>
        </div>

        <div className="tab-bar mb-6">
          <button
            id="tab-url"
            className={`tab-btn ${tab === "url" ? "active" : ""}`}
            onClick={() => setTab("url")}
          >
            🔗 URL / YouTube
          </button>
          <button
            id="tab-upload"
            className={`tab-btn ${tab === "upload" ? "active" : ""}`}
            onClick={() => setTab("upload")}
          >
            📤 Upload File
          </button>
        </div>

        <form onSubmit={submit} className="flex-col gap-4" style={{ display: "flex" }}>
          <div className="form-group">
            <label htmlFor="project-name">Project Name (optional)</label>
            <input
              id="project-name"
              className="input"
              placeholder="My Podcast Episode 42"
              value={name}
              onChange={(e) => setName(e.target.value)}
            />
          </div>

          {tab === "url" ? (
            <div className="form-group">
              <label htmlFor="source-url">Video URL</label>
              <input
                id="source-url"
                className="input"
                placeholder="https://youtube.com/watch?v=..."
                value={url}
                onChange={(e) => setUrl(e.target.value)}
                required
              />
              <small>Supports YouTube, Vimeo, direct MP4 URLs, and anything yt-dlp handles.</small>
            </div>
          ) : (
            <div
              className={`drop-zone ${dragging ? "dragging" : ""}`}
              onDragOver={(e) => { e.preventDefault(); setDragging(true); }}
              onDragLeave={() => setDragging(false)}
              onDrop={handleDrop}
              onClick={() => fileRef.current?.click()}
            >
              <input
                ref={fileRef}
                type="file"
                accept="video/*"
                className="sr-only"
                onChange={(e) => {
                  const f = e.target.files?.[0];
                  if (f) { setFile(f); if (!name) setName(f.name.replace(/\.[^.]+$/, "")); }
                }}
              />
              <div className="drop-zone-icon">🎥</div>
              {file ? (
                <>
                  <p style={{ color: "var(--text-primary)", fontWeight: 600 }}>{file.name}</p>
                  <small>{(file.size / 1e6).toFixed(1)} MB</small>
                </>
              ) : (
                <>
                  <p style={{ color: "var(--text-primary)", fontWeight: 600 }}>Drop your video here</p>
                  <small>or click to browse · MP4, MOV, MKV, WebM</small>
                </>
              )}
            </div>
          )}

          <div className="flex gap-3 mt-4" style={{ justifyContent: "flex-end" }}>
            <button type="button" className="btn btn-secondary" onClick={onClose}>
              Cancel
            </button>
            <button type="submit" id="create-project-submit" className="btn btn-primary" disabled={loading}>
              {loading ? <><span className="spinner" /> Processing…</> : "🚀 Create Project"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

// ─── Project Card ─────────────────────────────────────────────────────────────

function ProjectCard({ project, onDelete }: { project: Project; onDelete: () => void }) {
  const router = useRouter();
  const [deleting, setDeleting] = useState(false);

  async function handleDelete(e: React.MouseEvent) {
    e.preventDefault();
    e.stopPropagation();
    if (!confirm(`Delete "${project.name}"? This cannot be undone.`)) return;
    setDeleting(true);
    try {
      await api.projects.delete(project.id);
      toast("Project deleted", "success");
      onDelete();
    } catch {
      toast("Failed to delete project", "error");
      setDeleting(false);
    }
  }

  const href = project.status === "done"
    ? `/projects/${project.id}/clips`
    : `/projects/${project.id}`;

  return (
    <Link href={href} className="card" style={{ display: "block", textDecoration: "none" }}>
      <div className="card-body">
        {/* Top row */}
        <div className="flex items-center justify-between mb-4">
          <StatusBadge status={project.status} />
          <button
            className="btn btn-ghost btn-sm"
            onClick={handleDelete}
            disabled={deleting}
            style={{ padding: "4px 8px", minWidth: 0 }}
            title="Delete project"
          >
            {deleting ? <span className="spinner" /> : "🗑"}
          </button>
        </div>

        {/* Title */}
        <h3 className="truncate" style={{ marginBottom: "var(--space-2)" }}>
          {project.name ?? "Untitled Project"}
        </h3>

        {/* Source */}
        {project.source_url && (
          <p className="truncate" style={{ fontSize: "0.8rem", marginBottom: "var(--space-3)" }}>
            {project.source_url}
          </p>
        )}

        {/* Footer */}
        <div className="flex items-center justify-between mt-4" style={{ borderTop: "1px solid var(--border-subtle)", paddingTop: "var(--space-3)" }}>
          <small>{formatDate(project.created_at)}</small>
          <span style={{ fontSize: "0.75rem", color: "var(--text-muted)", textTransform: "uppercase", letterSpacing: "0.05em" }}>
            {project.source_type}
          </span>
        </div>
      </div>
    </Link>
  );
}

// ─── Dashboard Page ───────────────────────────────────────────────────────────

export default function DashboardPage() {
  const router = useRouter();
  const [showCreate, setShowCreate] = useState(false);
  const { data: projects, error, mutate } = useSWR<Project[]>("/api/projects", fetcher, {
    refreshInterval: 5000,
  });

  function handleCreated(p: Project) {
    setShowCreate(false);
    toast("Project created! Processing will begin shortly.", "success");
    mutate();
    router.push(`/projects/${p.id}`);
  }

  const loading = !projects && !error;

  const statusOrder: Record<string, number> = {
    processing: 0, pending: 1, failed: 2, done: 3, paused: 4,
  };
  const sorted = [...(projects ?? [])].sort(
    (a, b) => (statusOrder[a.status] ?? 9) - (statusOrder[b.status] ?? 9)
  );

  return (
    <div className="app-shell">
      <Sidebar />
      <main className="main-content">
        {/* Header */}
        <div className="page-header">
          <div>
            <h1 className="page-title">Projects</h1>
            <p className="page-subtitle">
              {projects ? `${projects.length} project${projects.length !== 1 ? "s" : ""}` : "Loading…"}
            </p>
          </div>
          <button
            id="new-project-btn"
            className="btn btn-primary btn-lg"
            onClick={() => setShowCreate(true)}
          >
            + New Project
          </button>
        </div>

        {/* State: Loading */}
        {loading && (
          <div className="empty-state">
            <div className="spinner spinner-lg" />
            <p>Loading projects…</p>
          </div>
        )}

        {/* State: Error */}
        {error && (
          <div className="card" style={{ borderColor: "var(--rose-500)" }}>
            <div className="card-body text-center">
              <p style={{ color: "var(--rose-400)" }}>⚠️ Could not connect to the API.</p>
              <small>Make sure the backend is running on localhost:8000</small>
              <div className="mt-4">
                <button className="btn btn-secondary btn-sm" onClick={() => mutate()}>
                  Retry
                </button>
              </div>
            </div>
          </div>
        )}

        {/* State: Empty */}
        {!loading && !error && projects?.length === 0 && (
          <div className="empty-state">
            <div className="empty-icon">🎬</div>
            <h2>No projects yet</h2>
            <p>Paste a YouTube URL or upload a video to get started.</p>
            <button
              className="btn btn-primary btn-lg mt-4"
              onClick={() => setShowCreate(true)}
            >
              Create your first project
            </button>
          </div>
        )}

        {/* Project Grid */}
        {sorted.length > 0 && (
          <div
            style={{
              display: "grid",
              gridTemplateColumns: "repeat(auto-fill, minmax(300px, 1fr))",
              gap: "var(--space-5)",
            }}
          >
            {sorted.map((p) => (
              <ProjectCard key={p.id} project={p} onDelete={() => mutate()} />
            ))}
          </div>
        )}

        {/* Stats row */}
        {projects && projects.length > 0 && (
          <div
            className="card mt-6"
            style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)" }}
          >
            {(["pending", "processing", "done", "failed"] as const).map((s) => (
              <div key={s} className="card-body text-center" style={{ borderRight: "1px solid var(--border-subtle)" }}>
                <div style={{ fontSize: "1.75rem", fontWeight: 800, color: "var(--text-primary)" }}>
                  {projects.filter((p) => p.status === s).length}
                </div>
                <small style={{ textTransform: "capitalize" }}>{s}</small>
              </div>
            ))}
          </div>
        )}
      </main>

      {showCreate && (
        <CreateModal onClose={() => setShowCreate(false)} onCreated={handleCreated} />
      )}
      <ToastContainer />
    </div>
  );
}
