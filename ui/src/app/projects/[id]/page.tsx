"use client";
export const dynamic = "force-dynamic";

import { useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import useSWR from "swr";
import Link from "next/link";
import { Sidebar } from "@/components/Sidebar";
import { ToastContainer, toast } from "@/components/Toast";
import { PipelineSteps } from "@/components/PipelineSteps";
import { api, createEventSource, fetcher } from "@/lib/api";
import type { ProgressEvent, ProjectDetail } from "@/lib/types";
import { formatDate } from "@/lib/utils";

export default function ProjectPage() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();

  const { data: project, error, mutate } = useSWR<ProjectDetail>(
    id ? `/api/projects/${id}` : null,
    fetcher,
    { refreshInterval: 3000 }
  );

  const [liveEvent, setLiveEvent] = useState<ProgressEvent | null>(null);
  const [messages, setMessages] = useState<{ time: string; text: string }[]>([]);
  const [resuming, setResuming] = useState(false);

  // Connect SSE when project is processing
  useEffect(() => {
    if (!id || !project) return;
    if (project.status !== "processing" && project.status !== "pending") return;

    const es = createEventSource(id);

    es.onmessage = (e) => {
      try {
        const data: ProgressEvent = JSON.parse(e.data);
        setLiveEvent(data);
        setMessages((prev) => [
          ...prev.slice(-49),
          { time: new Date().toLocaleTimeString(), text: `[${data.stage}] ${data.message}` },
        ]);
        // Refresh project data when stage changes
        if (data.progress >= 100) mutate();
      } catch {
        /* skip parse errors */
      }
    };

    es.onerror = () => {
      es.close();
      mutate();
    };

    return () => es.close();
  }, [id, project?.status, mutate]);

  async function handleResume() {
    if (!id) return;
    setResuming(true);
    try {
      await api.projects.resume(id);
      toast("Pipeline resumed!", "success");
      mutate();
    } catch {
      toast("Failed to resume", "error");
    } finally {
      setResuming(false);
    }
  }

  if (error) {
    return (
      <div className="app-shell">
        <Sidebar />
        <main className="main-content">
          <div className="empty-state">
            <div className="empty-icon">⚠️</div>
            <h2>Project not found</h2>
            <Link href="/" className="btn btn-primary mt-4">← Back to Projects</Link>
          </div>
        </main>
      </div>
    );
  }

  const isProcessing = project?.status === "processing" || project?.status === "pending";
  const isDone = project?.status === "done";
  const isFailed = project?.status === "failed";
  const activeJob = project?.jobs?.[0];
  const currentProgress = liveEvent?.progress ?? activeJob?.progress ?? 0;
  const currentStageLabel = liveEvent?.stage
    ? `${liveEvent.stage} — ${liveEvent.message}`
    : activeJob?.stage
      ? `${activeJob.stage} — Running (${activeJob.progress}%)…`
      : "Waiting for worker…";

  return (
    <div className="app-shell">
      <Sidebar />
      <main className="main-content">
        {/* Breadcrumb */}
        <div className="flex items-center gap-3 mb-6" style={{ color: "var(--text-muted)", fontSize: "0.875rem" }}>
          <Link href="/" style={{ color: "var(--text-muted)", textDecoration: "none" }}>
            Projects
          </Link>
          <span>/</span>
          <span style={{ color: "var(--text-primary)" }}>
            {project?.name ?? "Loading…"}
          </span>
        </div>

        {/* Header */}
        <div className="page-header">
          <div>
            <h1 className="page-title">{project?.name ?? "Processing…"}</h1>
            {project?.source_url && (
              <p className="page-subtitle truncate" style={{ maxWidth: 500 }}>
                {project.source_url}
              </p>
            )}
            {project?.created_at && (
              <p className="page-subtitle">{formatDate(project.created_at)}</p>
            )}
          </div>
          <div className="flex gap-3">
            {isFailed && (
              <button
                className="btn btn-secondary"
                onClick={handleResume}
                disabled={resuming}
              >
                {resuming ? <><span className="spinner" />Resuming…</> : "↺ Resume"}
              </button>
            )}
            {isDone && (
              <Link
                href={`/projects/${id}/clips`}
                className="btn btn-primary"
                id="view-clips-btn"
              >
                🎞 View Clips →
              </Link>
            )}
          </div>
        </div>

        {/* Status overview */}
        {!project ? (
          <div className="card card-body flex items-center gap-4 mb-6">
            <div className="spinner spinner-lg" />
            <p>Loading project…</p>
          </div>
        ) : (
          <>
            {/* Pipeline visualiser */}
            <div className="card mb-6">
              <div className="card-body">
                <h3 style={{ marginBottom: "var(--space-6)" }}>Pipeline Progress</h3>
                <PipelineSteps
                  currentEvent={liveEvent}
                  jobs={project.jobs}
                />

                {isProcessing && (
                  <div className="mt-6">
                    <div className="flex items-center justify-between mb-2">
                      <span style={{ fontSize: "0.875rem", color: "var(--text-secondary)" }}>
                        {currentStageLabel}
                      </span>
                      <span className="font-mono" style={{ fontSize: "0.875rem", color: "var(--accent-400)" }}>
                        {currentProgress}%
                      </span>
                    </div>
                    <div className="progress-track">
                      <div
                        className="progress-fill"
                        style={{ width: `${currentProgress}%` }}
                      />
                    </div>
                    {liveEvent?.clips_done !== undefined && liveEvent?.clips_total !== undefined && (
                      <small className="mt-2" style={{ display: "block" }}>
                        Clips rendered: {liveEvent.clips_done} / {liveEvent.clips_total}
                      </small>
                    )}
                  </div>
                )}

                {isDone && (
                  <div
                    className="mt-6"
                    style={{
                      display: "flex",
                      alignItems: "center",
                      gap: "var(--space-3)",
                      padding: "var(--space-4)",
                      background: "rgba(16,185,129,0.08)",
                      border: "1px solid rgba(16,185,129,0.25)",
                      borderRadius: "var(--radius-lg)",
                    }}
                  >
                    <span style={{ fontSize: "1.5rem" }}>✅</span>
                    <div>
                      <p style={{ color: "var(--green-400)", fontWeight: 600, marginBottom: 2 }}>
                        Processing complete!
                      </p>
                      <small>
                        {project.clips.length} clip{project.clips.length !== 1 ? "s" : ""} generated
                      </small>
                    </div>
                  </div>
                )}

                {isFailed && (
                  <div
                    className="mt-6"
                    style={{
                      display: "flex",
                      alignItems: "flex-start",
                      gap: "var(--space-3)",
                      padding: "var(--space-4)",
                      background: "rgba(244,63,94,0.08)",
                      border: "1px solid rgba(244,63,94,0.25)",
                      borderRadius: "var(--radius-lg)",
                    }}
                  >
                    <span style={{ fontSize: "1.5rem" }}>❌</span>
                    <div>
                      <p style={{ color: "var(--rose-400)", fontWeight: 600, marginBottom: 4 }}>
                        Pipeline failed
                      </p>
                      {project.jobs.find((j) => j.status === "failed")?.error && (
                        <code style={{ fontSize: "0.8rem", color: "var(--text-muted)" }}>
                          {project.jobs.find((j) => j.status === "failed")?.error}
                        </code>
                      )}
                    </div>
                  </div>
                )}
              </div>
            </div>

            {/* Job table */}
            <div className="card mb-6">
              <div className="card-body">
                <h3 style={{ marginBottom: "var(--space-4)" }}>Stage Details</h3>
                <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "0.875rem" }}>
                  <thead>
                    <tr style={{ borderBottom: "1px solid var(--border-subtle)" }}>
                      {["Stage", "Status", "Progress", "Attempts", "Started"].map((h) => (
                        <th key={h} style={{ textAlign: "left", padding: "8px 12px", color: "var(--text-muted)", fontWeight: 500 }}>
                          {h}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {project.jobs.map((job) => (
                      <tr key={job.id} style={{ borderBottom: "1px solid var(--border-subtle)" }}>
                        <td style={{ padding: "10px 12px", fontFamily: "var(--font-mono)", color: "var(--text-secondary)" }}>
                          {job.stage ?? "—"}
                        </td>
                        <td style={{ padding: "10px 12px" }}>
                          <span className={`badge status-badge-${job.status}`}>{job.status}</span>
                        </td>
                        <td style={{ padding: "10px 12px", color: "var(--accent-400)", fontFamily: "var(--font-mono)" }}>
                          {job.progress}%
                        </td>
                        <td style={{ padding: "10px 12px", color: "var(--text-muted)" }}>
                          {job.attempts}
                        </td>
                        <td style={{ padding: "10px 12px", color: "var(--text-muted)" }}>
                          {job.started_at ? formatDate(job.started_at) : "—"}
                        </td>
                      </tr>
                    ))}
                    {project.jobs.length === 0 && (
                      <tr>
                        <td colSpan={5} style={{ padding: "24px", textAlign: "center", color: "var(--text-muted)" }}>
                          No jobs yet
                        </td>
                      </tr>
                    )}
                  </tbody>
                </table>
              </div>
            </div>

            {/* Live log */}
            {messages.length > 0 && (
              <div className="card">
                <div className="card-body">
                  <h3 style={{ marginBottom: "var(--space-4)" }}>Live Log</h3>
                  <div
                    style={{
                      background: "var(--bg-base)",
                      border: "1px solid var(--border-subtle)",
                      borderRadius: "var(--radius-md)",
                      padding: "var(--space-4)",
                      maxHeight: 240,
                      overflowY: "auto",
                      fontFamily: "var(--font-mono)",
                      fontSize: "0.8rem",
                    }}
                  >
                    {messages.map((m, i) => (
                      <div key={i} style={{ color: "var(--text-muted)", marginBottom: 4 }}>
                        <span style={{ color: "var(--text-muted)", opacity: 0.5 }}>[{m.time}]</span>{" "}
                        <span style={{ color: "var(--accent-300)" }}>{m.text}</span>
                      </div>
                    ))}
                  </div>
                </div>
              </div>
            )}
          </>
        )}
      </main>
      <ToastContainer />
    </div>
  );
}
