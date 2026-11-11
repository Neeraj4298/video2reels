"use client";
export const dynamic = "force-dynamic";

import { useEffect, useRef, useState, useMemo } from "react";
import { useParams } from "next/navigation";
import useSWR from "swr";
import Link from "next/link";
import { Sidebar } from "@/components/Sidebar";
import { ToastContainer, toast } from "@/components/Toast";
import { ScoreRing } from "@/components/ScoreRing";
import { api, fetcher } from "@/lib/api";
import type { BrandKit, Clip, ClipTranscript, CaptionStyleConfig, TranscriptWord } from "@/lib/types";
import { formatDuration } from "@/lib/utils";

// ─── Style Presets ─────────────────────────────────────────────────────────────
const STYLE_PRESETS: Record<string, { label: string; icon: string; style: CaptionStyleConfig }> = {
  karaoke: {
    label: "Karaoke Gold",
    icon: "🟡",
    style: {
      preset: "karaoke",
      font_name: "Arial",
      font_size: 52,
      bold: true,
      primary_color: "#FFFFFF",
      highlight_color: "#FFD700",
      outline_color: "#000000",
    },
  },
  bold_yellow: {
    label: "Bold Yellow",
    icon: "⚡",
    style: {
      preset: "bold_yellow",
      font_name: "Arial",
      font_size: 56,
      bold: true,
      primary_color: "#FFD700",
      highlight_color: "#FFFFFF",
      outline_color: "#000000",
    },
  },
  cyberpunk_neon: {
    label: "Cyberpunk Neon",
    icon: "🌌",
    style: {
      preset: "cyberpunk_neon",
      font_name: "Arial",
      font_size: 54,
      bold: true,
      primary_color: "#00FFFF",
      highlight_color: "#FF007F",
      outline_color: "#000000",
    },
  },
  minimal_clean: {
    label: "Minimal Clean",
    icon: "⚪",
    style: {
      preset: "minimal_clean",
      font_name: "Arial",
      font_size: 46,
      bold: false,
      primary_color: "#F3F4F6",
      highlight_color: "#60A5FA",
      outline_color: "#000000",
    },
  },
  fire_red: {
    label: "Fire Red",
    icon: "🔥",
    style: {
      preset: "fire_red",
      font_name: "Arial",
      font_size: 56,
      bold: true,
      primary_color: "#FFFFFF",
      highlight_color: "#EF4444",
      outline_color: "#000000",
    },
  },
};

// ─── Score Breakdown Bar ──────────────────────────────────────────────────────
function ScoreBar({ label, value }: { label: string; value: number }) {
  const pct = value <= 10 ? Math.min(100, Math.round(value * 10)) : Math.min(100, Math.round(value));
  const color =
    pct >= 80 ? "var(--green-400)" :
    pct >= 60 ? "var(--amber-400)" :
    "var(--rose-400)";

  return (
    <div>
      <div className="flex items-center justify-between mb-1">
        <span style={{ fontSize: "0.8125rem", color: "var(--text-secondary)" }}>{label}</span>
        <span style={{ fontSize: "0.8125rem", fontFamily: "var(--font-mono)", color }}>
          {value <= 10 ? `${value}/10` : value}
        </span>
      </div>
      <div className="progress-track" style={{ height: 4 }}>
        <div
          style={{
            height: "100%",
            width: `${pct}%`,
            background: color,
            borderRadius: "var(--radius-full)",
            transition: "width 0.8s ease",
          }}
        />
      </div>
    </div>
  );
}

// ─── Waveform Visualization ───────────────────────────────────────────────────
function WaveformBars({
  count = 48,
  seed = 42,
  words = [],
  clipStart = 0,
  clipEnd = 30,
}: {
  count?: number;
  seed?: number;
  words?: TranscriptWord[];
  clipStart?: number;
  clipEnd?: number;
}) {
  const bars = useMemo(() => {
    const dur = Math.max(0.5, clipEnd - clipStart);
    if (words && words.length > 0) {
      return Array.from({ length: count }, (_, i) => {
        const binStart = clipStart + (i / count) * dur;
        const binEnd = clipStart + ((i + 1) / count) * dur;
        const active = words.filter((w) => w.e >= binStart && w.s <= binEnd);
        if (active.length === 0) return 14;
        const avgProb = active.reduce((acc, w) => acc + (w.p || 0.9), 0) / active.length;
        const charDensity = Math.min(1, active.reduce((acc, w) => acc + w.w.length, 0) / 10);
        return Math.max(22, Math.min(96, Math.round((0.55 * avgProb + 0.45 * charDensity) * 95)));
      });
    }
    return Array.from({ length: count }, (_, i) => {
      const sinVal = Math.sin((i + seed) * 0.45) * 0.35 + Math.cos((i + seed) * 0.2) * 0.25;
      const height = Math.max(15, Math.min(95, Math.round((sinVal + 0.6) * 70)));
      return height;
    });
  }, [count, seed, words, clipStart, clipEnd]);


  return (
    <div
      style={{
        display: "flex",
        alignItems: "center",
        justifyContent: "space-between",
        height: "100%",
        width: "100%",
        padding: "0 4px",
        opacity: 0.35,
        pointerEvents: "none",
      }}
    >
      {bars.map((h, idx) => (
        <div
          key={idx}
          style={{
            width: 3,
            height: `${h}%`,
            background: "var(--text-muted)",
            borderRadius: 2,
          }}
        />
      ))}
    </div>
  );
}

// ─── Main Clip Detail Page ────────────────────────────────────────────────────
export default function ClipDetailPage() {
  const { id: projectId, clipId } = useParams<{ id: string; clipId: string }>();

  // Clips SWR
  const { data: clips, mutate } = useSWR<Clip[]>(
    projectId ? `/api/projects/${projectId}/clips` : null,
    fetcher,
    { refreshInterval: 5000 }
  );
  const clip = clips?.find((c) => c.id === clipId);

  // Transcript SWR
  const { data: transcriptData, mutate: mutateTranscript } = useSWR<ClipTranscript>(
    clipId ? `/api/clips/${clipId}/transcript` : null,
    fetcher
  );

  const videoRef = useRef<HTMLVideoElement>(null);
  const [videoUrl, setVideoUrl] = useState<string | null>(null);
  const [loadingUrl, setLoadingUrl] = useState(false);
  const [currentTime, setCurrentTime] = useState(0);

  // Trim state
  const [editStart, setEditStart] = useState<number>(0);
  const [editEnd, setEditEnd] = useState<number>(0);
  const [saving, setSaving] = useState(false);

  // Metadata state
  const [editTitle, setEditTitle] = useState("");
  const [editHook, setEditHook] = useState("");
  const [editDescription, setEditDescription] = useState("");
  const [editHashtags, setEditHashtags] = useState<string[]>([]);
  const [regeneratingMeta, setRegeneratingMeta] = useState(false);
  const [publishingPlatform, setPublishingPlatform] = useState<string | null>(null);

  // Caption Styling state
  const [selectedPreset, setSelectedPreset] = useState<string>("karaoke");
  const [captionStyle, setCaptionStyle] = useState<CaptionStyleConfig>(STYLE_PRESETS.karaoke.style);

  // Brand Kits & Layout state
  const { data: brandKits } = useSWR<BrandKit[]>("/api/brand-kits", fetcher);
  const [selectedBrandKitId, setSelectedBrandKitId] = useState<string>("");
  const [layout, setLayout] = useState<"vertical" | "blur_bg" | "split_screen">("vertical");
  const [rendering, setRendering] = useState(false);

  // Transcript editing & excluded words
  const [excludedWordIndices, setExcludedWordIndices] = useState<Set<number>>(new Set());
  const [editedTranscriptText, setEditedTranscriptText] = useState("");
  const [activeTab, setActiveTab] = useState<"trim" | "transcript" | "captions">("trim");

  // Sync state with clip data
  useEffect(() => {
    if (clip) {
      setEditTitle(clip.title ?? "");
      setEditHook(clip.hook ?? "");
      setEditDescription(clip.description ?? "");
      setEditHashtags(clip.hashtags ?? []);
      setEditStart(clip.start);
      setEditEnd(clip.end);
    }
  }, [clip?.id]);

  useEffect(() => {
    if (transcriptData?.text) {
      setEditedTranscriptText(transcriptData.text);
    }
    if (transcriptData?.excluded_word_indices) {
      setExcludedWordIndices(new Set(transcriptData.excluded_word_indices));
    }
  }, [transcriptData?.text, transcriptData?.excluded_word_indices]);


  async function fetchVideoUrl() {
    if (!clipId || loadingUrl) return;
    setLoadingUrl(true);
    try {
      const { download_url } = await api.clips.download(clipId);
      setVideoUrl(download_url);
    } catch {
      toast("No rendered MP4 available yet. Click 'Re-render' to generate.", "info");
    } finally {
      setLoadingUrl(false);
    }
  }

  async function handleRegenerateMetadata() {
    if (!clipId || regeneratingMeta) return;
    setRegeneratingMeta(true);
    try {
      const res = await api.clips.regenerateMetadata(clipId);
      setEditTitle(res.title);
      setEditDescription(res.description);
      setEditHashtags(res.hashtags);
      toast("Metadata regenerated with AI! Remember to click 'Save Changes'.", "success");
      mutate();
    } catch (err: unknown) {
      toast(err instanceof Error ? err.message : "Failed to regenerate metadata", "error");
    } finally {
      setRegeneratingMeta(false);
    }
  }

  async function handlePublish(platform: "youtube" | "tiktok" | "instagram") {
    if (!clipId || publishingPlatform) return;
    setPublishingPlatform(platform);
    try {
      const res = await api.clips.publish(clipId, {
        platform,
        title: editTitle,
        description: editDescription,
      });
      toast(res.message, "success");
    } catch (err: unknown) {
      toast(err instanceof Error ? err.message : "Failed to publish clip", "error");
    } finally {
      setPublishingPlatform(null);
    }
  }

  function copyCaption(platform: string) {
    const tags = editHashtags.map((t) => (t.startsWith("#") ? t : `#${t}`)).join(" ");
    let text = "";
    if (platform === "youtube") {
      text = `${editTitle}\n\n${editDescription}\n\n${tags}`;
    } else if (platform === "tiktok") {
      text = `${editTitle} ${tags}\n\n${editDescription}`;
    } else {
      text = `${editDescription}\n.\n.\n${tags}`;
    }
    navigator.clipboard.writeText(text);
    toast(`Copied ${platform} caption & hashtags to clipboard!`, "success");
  }

  async function saveChanges() {
    if (!clipId || !clip) return;
    setSaving(true);
    try {
      await api.clips.update(clipId, {
        title: editTitle || undefined,
        hook: editHook || undefined,
        start: editStart,
        end: editEnd,
        caption_style: captionStyle as Record<string, unknown>,
        excluded_word_indices: Array.from(excludedWordIndices),
      });
      toast("Changes and EDL word edits saved!", "success");
      mutate();
      mutateTranscript();
    } catch {
      toast("Failed to save changes", "error");
    } finally {
      setSaving(false);
    }
  }

  async function triggerRender() {
    if (!clipId) return;
    setRendering(true);
    try {
      await api.clips.render(clipId, {
        layout,
        caption_style: captionStyle as Record<string, unknown>,
        brand_kit_id: selectedBrandKitId || undefined,
        excluded_word_indices: Array.from(excludedWordIndices),
      });
      toast("Render queued! Celery worker processing in background...", "info");
      mutate();
    } catch {
      toast("Failed to queue render", "error");
    } finally {
      setRendering(false);
    }
  }


  function handleSelectPreset(key: string) {
    setSelectedPreset(key);
    if (STYLE_PRESETS[key]) {
      setCaptionStyle({ ...STYLE_PRESETS[key].style });
    }
  }

  function handleWordClick(word: TranscriptWord) {
    if (!videoRef.current || !clip) return;
    // Word timestamp relative to clip start
    const relativeTime = Math.max(0, word.s - clip.start);
    videoRef.current.currentTime = relativeTime;
    videoRef.current.play().catch(() => {});
  }

  function toggleExcludeWord(idx: number, e: React.MouseEvent) {
    e.stopPropagation();
    const updated = new Set(excludedWordIndices);
    if (updated.has(idx)) {
      updated.delete(idx);
    } else {
      updated.add(idx);
    }
    setExcludedWordIndices(updated);
  }

  function nudge(field: "start" | "end", amount: number) {
    if (!clip) return;
    if (field === "start") {
      const next = Math.max(0, Math.min(editEnd - 0.5, Number((editStart + amount).toFixed(1))));
      setEditStart(next);
    } else {
      const next = Math.max(editStart + 0.5, Number((editEnd + amount).toFixed(1)));
      setEditEnd(next);
    }
  }

  if (!clip) {
    return (
      <div className="app-shell">
        <Sidebar />
        <main className="main-content">
          <div className="empty-state">
            <div className="spinner spinner-lg" />
            <p>Loading clip…</p>
          </div>
        </main>
      </div>
    );
  }

  const duration = Math.max(0, editEnd - editStart);
  const words = transcriptData?.words ?? [];
  const maxTime = Math.max(clip.end, editEnd, 1);
  const srtUrl = api.clips.subtitlesUrl(clipId, "srt");
  const vttUrl = api.clips.subtitlesUrl(clipId, "vtt");

  return (
    <div className="app-shell">
      <Sidebar />
      <main className="main-content">
        {/* Breadcrumb */}
        <div className="flex items-center gap-3 mb-6" style={{ color: "var(--text-muted)", fontSize: "0.875rem" }}>
          <Link href="/" style={{ color: "var(--text-muted)", textDecoration: "none" }}>Projects</Link>
          <span>/</span>
          <Link href={`/projects/${projectId}/clips`} style={{ color: "var(--text-muted)", textDecoration: "none" }}>
            Clips
          </Link>
          <span>/</span>
          <span style={{ color: "var(--text-primary)", maxWidth: 240 }} className="truncate">
            {clip.title ?? `${formatDuration(clip.start)}–${formatDuration(clip.end)}`}
          </span>
        </div>

        {/* Header with Title and Quick Actions */}
        <div className="flex items-center justify-between mb-6" style={{ flexWrap: "wrap", gap: "var(--space-4)" }}>
          <div>
            <h1 style={{ fontSize: "1.75rem", fontWeight: 700, margin: 0 }}>
              {clip.title || "Clip Editor"}
            </h1>
            <p style={{ color: "var(--text-secondary)", marginTop: 4, fontSize: "0.875rem" }}>
              Fine-tune trim boundaries, edit captions, customize styles, and export.
            </p>
          </div>
          <div className="flex items-center gap-3">
            <a
              href={srtUrl}
              download
              className="btn btn-secondary btn-sm"
              title="Download SRT Subtitle File"
            >
              📄 Export SRT
            </a>
            <a
              href={vttUrl}
              download
              className="btn btn-secondary btn-sm"
              title="Download WebVTT Subtitle File"
            >
              📝 Export VTT
            </a>
            <a
              href={api.clips.exportXmlUrl(clip.id)}
              download
              className="btn btn-secondary btn-sm"
              title="Export Premiere Pro / DaVinci Resolve XML Bundle"
            >
              🎬 Export XML
            </a>

            {clip.status === "done" && (
              <button
                className="btn btn-primary btn-sm"
                onClick={fetchVideoUrl}
                disabled={loadingUrl}
              >
                {loadingUrl ? <><span className="spinner" /> Loading…</> : "⬇ Download MP4"}
              </button>
            )}
          </div>
        </div>

        {/* 2-Column Editor Layout */}
        <div
          style={{
            display: "grid",
            gridTemplateColumns: "minmax(0, 1.4fr) minmax(340px, 1fr)",
            gap: "var(--space-6)",
            alignItems: "start",
          }}
        >
          {/* ── LEFT COLUMN: Preview & Tabs ── */}
          <div className="flex-col gap-6" style={{ display: "flex" }}>
            {/* Video Preview Card */}
            <div className="card">
              <div className="card-body">
                <div className="flex items-center justify-between mb-4">
                  <h3 style={{ margin: 0, fontSize: "1.125rem" }}>Live Preview</h3>
                  <span
                    className="badge"
                    style={{
                      background: clip.status === "done" ? "rgba(34,197,94,0.12)" : "rgba(234,179,8,0.12)",
                      color: clip.status === "done" ? "var(--green-400)" : "var(--amber-400)",
                    }}
                  >
                    {clip.status.toUpperCase()}
                  </span>
                </div>

                <div
                  style={{
                    background: "#08090d",
                    borderRadius: "var(--radius-lg)",
                    border: "1px solid var(--border-subtle)",
                    overflow: "hidden",
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "center",
                    minHeight: 360,
                    position: "relative",
                  }}
                >
                  {videoUrl ? (
                    <div style={{ position: "relative", width: "100%", display: "flex", justifyContent: "center" }}>
                      <video
                        ref={videoRef}
                        src={videoUrl}
                        controls
                        onTimeUpdate={() => {
                          if (videoRef.current) setCurrentTime(videoRef.current.currentTime);
                        }}
                        style={{
                          maxWidth: "100%",
                          maxHeight: 460,
                          borderRadius: "var(--radius-md)",
                          display: "block",
                        }}
                      />
                    </div>
                  ) : (
                    <div className="flex-col gap-4 text-center p-8" style={{ display: "flex", alignItems: "center" }}>
                      <div
                        style={{
                          width: 64,
                          height: 64,
                          borderRadius: "50%",
                          background: "var(--bg-overlay)",
                          display: "flex",
                          alignItems: "center",
                          justifyContent: "center",
                          fontSize: "1.75rem",
                          border: "1px solid var(--border-subtle)",
                        }}
                      >
                        🎬
                      </div>
                      <div>
                        <p style={{ fontWeight: 600, color: "var(--text-primary)", marginBottom: 4 }}>
                          {clip.status === "done" ? "Preview ready to stream" : `Clip status: ${clip.status}`}
                        </p>
                        <p style={{ fontSize: "0.8125rem", color: "var(--text-muted)" }}>
                          {clip.status === "done"
                            ? "Stream the rendered 1080×1920 MP4 directly with word-level captions"
                            : "Click 'Re-render Clip' in the export panel to render now"}
                        </p>
                      </div>
                      {clip.status === "done" && (
                        <button
                          className="btn btn-primary btn-sm"
                          onClick={fetchVideoUrl}
                          disabled={loadingUrl}
                          id="load-preview-btn"
                        >
                          {loadingUrl ? <><span className="spinner" /> Loading…</> : "▶ Load Video Player"}
                        </button>
                      )}
                    </div>
                  )}
                </div>
              </div>
            </div>

            {/* Navigation Tabs for Phase 4 Tools */}
            <div
              style={{
                display: "flex",
                gap: "var(--space-2)",
                background: "var(--bg-overlay)",
                padding: 4,
                borderRadius: "var(--radius-lg)",
                border: "1px solid var(--border-subtle)",
              }}
            >
              <button
                className={`btn btn-sm ${activeTab === "trim" ? "btn-primary" : "btn-secondary"}`}
                style={{ flex: 1, border: "none" }}
                onClick={() => setActiveTab("trim")}
              >
                ✂️ Trim Timeline
              </button>
              <button
                className={`btn btn-sm ${activeTab === "transcript" ? "btn-primary" : "btn-secondary"}`}
                style={{ flex: 1, border: "none" }}
                onClick={() => setActiveTab("transcript")}
              >
                📜 Transcript Editor ({words.length})
              </button>
              <button
                className={`btn btn-sm ${activeTab === "captions" ? "btn-primary" : "btn-secondary"}`}
                style={{ flex: 1, border: "none" }}
                onClick={() => setActiveTab("captions")}
              >
                🎨 Caption Style
              </button>
            </div>

            {/* TAB 1: TRIM TIMELINE */}
            {activeTab === "trim" && (
              <div className="card">
                <div className="card-body">
                  <div className="flex items-center justify-between mb-4">
                    <div>
                      <h3 style={{ margin: 0 }}>Interactive Trim Handles</h3>
                      <small style={{ color: "var(--text-secondary)" }}>
                        Clip Duration: <span style={{ color: "var(--accent-400)", fontFamily: "var(--font-mono)" }}>{duration.toFixed(1)}s</span>
                      </small>
                    </div>
                    <div className="flex gap-2">
                      <button
                        className="btn btn-secondary btn-sm"
                        onClick={() => { setEditStart(clip.start); setEditEnd(clip.end); }}
                      >
                        ↺ Reset
                      </button>
                      <button
                        id="save-trim-btn"
                        className="btn btn-primary btn-sm"
                        onClick={saveChanges}
                        disabled={saving}
                      >
                        {saving ? <><span className="spinner" /> Saving…</> : "💾 Save Trim"}
                      </button>
                    </div>
                  </div>

                  {/* Waveform & Interactive Timeline Range */}
                  <div
                    style={{
                      position: "relative",
                      height: 72,
                      background: "#0c0d14",
                      borderRadius: "var(--radius-md)",
                      border: "1px solid var(--border-subtle)",
                      overflow: "hidden",
                      margin: "var(--space-4) 0",
                    }}
                  >
                    {/* Real transcript-driven waveform */}
                    <WaveformBars
                      count={64}
                      seed={Math.round(clip.start * 10)}
                      words={words}
                      clipStart={clip.start}
                      clipEnd={clip.end}
                    />


                    {/* Active Trim Range Box */}
                    <div
                      style={{
                        position: "absolute",
                        top: 0,
                        bottom: 0,
                        left: `${(editStart / maxTime) * 100}%`,
                        width: `${((editEnd - editStart) / maxTime) * 100}%`,
                        background: "linear-gradient(90deg, rgba(124, 58, 237, 0.35), rgba(99, 102, 241, 0.45))",
                        borderLeft: "3px solid var(--accent-400)",
                        borderRight: "3px solid var(--accent-400)",
                        display: "flex",
                        alignItems: "center",
                        justifyContent: "center",
                        color: "#fff",
                        fontFamily: "var(--font-mono)",
                        fontSize: "0.8125rem",
                        fontWeight: 600,
                        boxShadow: "0 0 15px rgba(124, 58, 237, 0.3)",
                      }}
                    >
                      {formatDuration(duration)}
                    </div>

                    {/* Video playhead indicator */}
                    {videoUrl && (
                      <div
                        style={{
                          position: "absolute",
                          top: 0,
                          bottom: 0,
                          left: `${((editStart + currentTime) / maxTime) * 100}%`,
                          width: 2,
                          background: "#ef4444",
                          zIndex: 10,
                          pointerEvents: "none",
                        }}
                      />
                    )}
                  </div>

                  {/* Range Sliders */}
                  <div className="flex-col gap-4" style={{ display: "flex" }}>
                    <div>
                      <div className="flex justify-between text-sm mb-1">
                        <span>Start Timestamp: <strong>{editStart.toFixed(1)}s</strong> ({formatDuration(editStart)})</span>
                        <div className="flex gap-1">
                          <button className="btn btn-secondary btn-xs" onClick={() => nudge("start", -1)}>-1s</button>
                          <button className="btn btn-secondary btn-xs" onClick={() => nudge("start", -0.1)}>-0.1s</button>
                          <button className="btn btn-secondary btn-xs" onClick={() => nudge("start", +0.1)}>+0.1s</button>
                          <button className="btn btn-secondary btn-xs" onClick={() => nudge("start", +1)}>+1s</button>
                        </div>
                      </div>
                      <input
                        type="range"
                        className="w-full"
                        min={0}
                        max={editEnd - 0.5}
                        step={0.1}
                        value={editStart}
                        onChange={(e) => setEditStart(parseFloat(e.target.value))}
                        style={{ width: "100%", accentColor: "var(--accent-500)" }}
                      />
                    </div>

                    <div>
                      <div className="flex justify-between text-sm mb-1">
                        <span>End Timestamp: <strong>{editEnd.toFixed(1)}s</strong> ({formatDuration(editEnd)})</span>
                        <div className="flex gap-1">
                          <button className="btn btn-secondary btn-xs" onClick={() => nudge("end", -1)}>-1s</button>
                          <button className="btn btn-secondary btn-xs" onClick={() => nudge("end", -0.1)}>-0.1s</button>
                          <button className="btn btn-secondary btn-xs" onClick={() => nudge("end", +0.1)}>+0.1s</button>
                          <button className="btn btn-secondary btn-xs" onClick={() => nudge("end", +1)}>+1s</button>
                        </div>
                      </div>
                      <input
                        type="range"
                        className="w-full"
                        min={editStart + 0.5}
                        max={Math.max(clip.end + 10, editEnd + 5)}
                        step={0.1}
                        value={editEnd}
                        onChange={(e) => setEditEnd(parseFloat(e.target.value))}
                        style={{ width: "100%", accentColor: "var(--accent-500)" }}
                      />
                    </div>
                  </div>
                </div>
              </div>
            )}

            {/* TAB 2: TRANSCRIPT EDITOR */}
            {activeTab === "transcript" && (
              <div className="card">
                <div className="card-body">
                  <div className="flex items-center justify-between mb-4">
                    <div>
                      <h3 style={{ margin: 0 }}>Interactive Word Transcript</h3>
                      <small style={{ color: "var(--text-secondary)" }}>
                        Click a word to jump video playback. Click ✕ to strike-through/cut word.
                      </small>
                    </div>
                    <span className="badge" style={{ background: "rgba(124,58,237,0.15)", color: "var(--accent-400)" }}>
                      {words.length} Words
                    </span>
                  </div>

                  {/* Word Badges Grid */}
                  <div
                    style={{
                      maxHeight: 280,
                      overflowY: "auto",
                      padding: "var(--space-3)",
                      background: "var(--bg-base)",
                      borderRadius: "var(--radius-md)",
                      border: "1px solid var(--border-subtle)",
                      display: "flex",
                      flexWrap: "wrap",
                      gap: "6px",
                      lineHeight: 1.8,
                    }}
                  >
                    {words.length === 0 ? (
                      <p style={{ color: "var(--text-muted)", fontSize: "0.875rem" }}>
                        Transcript segments loading or unavailable for this clip window.
                      </p>
                    ) : (
                      words.map((w, idx) => {
                        const isExcluded = excludedWordIndices.has(idx);
                        const isCurrent =
                          currentTime >= w.s - clip.start &&
                          currentTime <= w.e - clip.start;

                        return (
                          <span
                            key={idx}
                            onClick={() => handleWordClick(w)}
                            title={`Jump to ${w.s.toFixed(2)}s (Confidence: ${(w.p * 100).toFixed(0)}%)`}
                            style={{
                              cursor: "pointer",
                              display: "inline-flex",
                              alignItems: "center",
                              gap: 4,
                              padding: "2px 8px",
                              borderRadius: "var(--radius-sm)",
                              fontSize: "0.875rem",
                              background: isCurrent
                                ? "var(--accent-500)"
                                : isExcluded
                                ? "rgba(239, 68, 68, 0.15)"
                                : "var(--bg-overlay)",
                              color: isCurrent
                                ? "#ffffff"
                                : isExcluded
                                ? "var(--text-muted)"
                                : "var(--text-primary)",
                              textDecoration: isExcluded ? "line-through" : "none",
                              border: isCurrent
                                ? "1px solid var(--accent-300)"
                                : "1px solid var(--border-subtle)",
                              transition: "all 0.15s ease",
                            }}
                          >
                            <span>{w.w}</span>
                            <button
                              onClick={(e) => toggleExcludeWord(idx, e)}
                              style={{
                                background: "transparent",
                                border: "none",
                                color: isExcluded ? "var(--green-400)" : "var(--text-muted)",
                                cursor: "pointer",
                                padding: 0,
                                fontSize: "0.75rem",
                              }}
                              title={isExcluded ? "Restore word" : "Cut word"}
                            >
                              {isExcluded ? "↩" : "×"}
                            </button>
                          </span>
                        );
                      })
                    )}
                  </div>

                  {/* Editable text box */}
                  <div className="mt-4">
                    <label className="text-sm font-semibold mb-1 block">Full Transcript Text</label>
                    <textarea
                      className="input"
                      rows={3}
                      value={editedTranscriptText}
                      onChange={(e) => setEditedTranscriptText(e.target.value)}
                      placeholder="Transcript text..."
                    />
                  </div>
                </div>
              </div>
            )}

            {/* TAB 3: CAPTION STYLE PICKER */}
            {activeTab === "captions" && (
              <div className="card">
                <div className="card-body">
                  <h3 style={{ marginBottom: "var(--space-4)" }}>Word-Highlight Caption Styling</h3>

                  {/* Preset Buttons */}
                  <label className="text-sm font-semibold mb-2 block">Choose Preset Style</label>
                  <div
                    style={{
                      display: "grid",
                      gridTemplateColumns: "repeat(auto-fit, minmax(130px, 1fr))",
                      gap: "var(--space-3)",
                      marginBottom: "var(--space-6)",
                    }}
                  >
                    {Object.entries(STYLE_PRESETS).map(([key, item]) => {
                      const isSelected = selectedPreset === key;
                      return (
                        <button
                          key={key}
                          type="button"
                          onClick={() => handleSelectPreset(key)}
                          className="btn"
                          style={{
                            display: "flex",
                            flexDirection: "column",
                            alignItems: "center",
                            gap: 6,
                            padding: "var(--space-3)",
                            borderRadius: "var(--radius-md)",
                            background: isSelected ? "rgba(124, 58, 237, 0.15)" : "var(--bg-base)",
                            border: isSelected ? "2px solid var(--accent-500)" : "1px solid var(--border-subtle)",
                            color: isSelected ? "var(--accent-300)" : "var(--text-primary)",
                          }}
                        >
                          <span style={{ fontSize: "1.25rem" }}>{item.icon}</span>
                          <span style={{ fontSize: "0.8125rem", fontWeight: 600 }}>{item.label}</span>
                        </button>
                      );
                    })}
                  </div>

                  {/* Live Caption Style Preview Box */}
                  <div
                    style={{
                      background: "#08090d",
                      borderRadius: "var(--radius-md)",
                      border: "1px solid var(--border-subtle)",
                      padding: "var(--space-6)",
                      textAlign: "center",
                      marginBottom: "var(--space-6)",
                    }}
                  >
                    <small style={{ color: "var(--text-muted)", display: "block", marginBottom: 12 }}>
                      Live Caption Style Preview
                    </small>
                    <div
                      style={{
                        fontFamily: captionStyle.font_name || "Arial",
                        fontSize: "1.5rem",
                        fontWeight: captionStyle.bold ? 700 : 400,
                        textTransform: "uppercase",
                        letterSpacing: "0.05em",
                        display: "flex",
                        justifyContent: "center",
                        gap: 8,
                        flexWrap: "wrap",
                      }}
                    >
                      <span style={{ color: captionStyle.highlight_color || "#FFD700", textShadow: "0 2px 8px rgba(0,0,0,0.8)" }}>
                        VIRAL
                      </span>
                      <span style={{ color: captionStyle.primary_color || "#FFFFFF", textShadow: "0 2px 8px rgba(0,0,0,0.8)" }}>
                        SHORT-FORM
                      </span>
                      <span style={{ color: captionStyle.primary_color || "#FFFFFF", textShadow: "0 2px 8px rgba(0,0,0,0.8)" }}>
                        HOOKS
                      </span>
                    </div>
                  </div>

                  {/* Custom Controls */}
                  <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "var(--space-4)" }}>
                    <div className="form-group">
                      <label>Font Family</label>
                      <select
                        className="select"
                        value={captionStyle.font_name}
                        onChange={(e) => {
                          setSelectedPreset("custom");
                          setCaptionStyle({ ...captionStyle, font_name: e.target.value });
                        }}
                      >
                        <option value="Arial">Arial (Standard)</option>
                        <option value="Inter">Inter (Modern Clean)</option>
                        <option value="Montserrat">Montserrat (Bold Pop)</option>
                        <option value="Impact">Impact (Bold Punchy)</option>
                      </select>
                    </div>

                    <div className="form-group">
                      <label>Font Size ({captionStyle.font_size}px)</label>
                      <input
                        type="range"
                        min={36}
                        max={72}
                        value={captionStyle.font_size || 52}
                        onChange={(e) => {
                          setSelectedPreset("custom");
                          setCaptionStyle({ ...captionStyle, font_size: parseInt(e.target.value) });
                        }}
                        style={{ accentColor: "var(--accent-500)", width: "100%" }}
                      />
                    </div>

                    <div className="form-group">
                      <label>Primary Text Color</label>
                      <div className="flex items-center gap-2">
                        <input
                          type="color"
                          value={captionStyle.primary_color || "#FFFFFF"}
                          onChange={(e) => {
                            setSelectedPreset("custom");
                            setCaptionStyle({ ...captionStyle, primary_color: e.target.value });
                          }}
                          style={{ width: 40, height: 36, border: "none", cursor: "pointer", background: "none" }}
                        />
                        <span className="font-mono text-sm">{captionStyle.primary_color || "#FFFFFF"}</span>
                      </div>
                    </div>

                    <div className="form-group">
                      <label>Active Highlight Color</label>
                      <div className="flex items-center gap-2">
                        <input
                          type="color"
                          value={captionStyle.highlight_color || "#FFD700"}
                          onChange={(e) => {
                            setSelectedPreset("custom");
                            setCaptionStyle({ ...captionStyle, highlight_color: e.target.value });
                          }}
                          style={{ width: 40, height: 36, border: "none", cursor: "pointer", background: "none" }}
                        />
                        <span className="font-mono text-sm">{captionStyle.highlight_color || "#FFD700"}</span>
                      </div>
                    </div>
                  </div>
                </div>
              </div>
            )}
          </div>

          {/* ── RIGHT COLUMN: Score, Metadata, Export ── */}
          <div className="flex-col gap-6" style={{ display: "flex" }}>
            {/* Virality Score Card */}
            <div className="card">
              <div className="card-body">
                <div className="flex items-center gap-4" style={{ marginBottom: "var(--space-4)" }}>
                  <ScoreRing score={clip.score} size={64} strokeWidth={5} />
                  <div>
                    <h3 style={{ margin: 0 }}>Virality Score</h3>
                    <small style={{ color: "var(--text-secondary)" }}>
                      {formatDuration(clip.start)} → {formatDuration(clip.end)} ({formatDuration(duration)})
                    </small>
                  </div>
                </div>

                {clip.score_breakdown && (
                  <div className="flex-col gap-3" style={{ display: "flex" }}>
                    {Object.entries(clip.score_breakdown).map(([key, val]) => (
                      <ScoreBar key={key} label={key.charAt(0).toUpperCase() + key.slice(1)} value={val as number} />
                    ))}
                  </div>
                )}
              </div>
            </div>

            {/* Metadata Editor */}
            <div className="card">
              <div className="card-body">
                <div className="flex items-center justify-between mb-4">
                  <h3 style={{ margin: 0 }}>Metadata</h3>
                  <button
                    className="btn btn-secondary btn-sm"
                    onClick={handleRegenerateMetadata}
                    disabled={regeneratingMeta}
                    title="Generate catchy title, description, and hashtags using Gemini AI"
                  >
                    {regeneratingMeta ? <><span className="spinner" /> Generating…</> : "✨ AI Regenerate"}
                  </button>
                </div>
                <div className="flex-col gap-4" style={{ display: "flex" }}>
                  <div className="form-group">
                    <label htmlFor="clip-title">Title</label>
                    <input
                      id="clip-title"
                      className="input"
                      placeholder="Enter clip title"
                      value={editTitle}
                      onChange={(e) => setEditTitle(e.target.value)}
                    />
                  </div>
                  <div className="form-group">
                    <label htmlFor="clip-hook">Hook</label>
                    <textarea
                      id="clip-hook"
                      className="input"
                      placeholder="The opening hook text"
                      value={editHook}
                      onChange={(e) => setEditHook(e.target.value)}
                      rows={2}
                    />
                  </div>
                  <div className="form-group">
                    <label htmlFor="clip-description">Description</label>
                    <textarea
                      id="clip-description"
                      className="input"
                      placeholder="Engaging caption for social media posts"
                      value={editDescription}
                      onChange={(e) => setEditDescription(e.target.value)}
                      rows={2}
                    />
                  </div>

                  {editHashtags && editHashtags.length > 0 && (
                    <div>
                      <label style={{ fontSize: "0.8125rem", color: "var(--text-secondary)", display: "block", marginBottom: 6 }}>
                        Social Hashtags
                      </label>
                      <div className="flex gap-2" style={{ flexWrap: "wrap" }}>
                        {editHashtags.map((tag) => (
                          <span
                            key={tag}
                            className="badge"
                            style={{
                              background: "rgba(124,58,237,0.1)",
                              color: "var(--accent-400)",
                              border: "1px solid var(--border-subtle)",
                            }}
                          >
                            #{tag.replace(/^#/, "")}
                          </span>
                        ))}
                      </div>
                    </div>
                  )}

                  <button
                    className="btn btn-primary w-full"
                    onClick={saveChanges}
                    disabled={saving}
                  >
                    {saving ? <><span className="spinner" /> Saving…</> : "💾 Save Changes"}
                  </button>
                </div>
              </div>
            </div>

            {/* Render & Export Card */}
            <div className="card">
              <div className="card-body">
                <h3 style={{ marginBottom: "var(--space-4)" }}>Render & Export (1080×1920)</h3>
                <div className="form-group mb-4">
                  <label htmlFor="layout-select">Reframing Layout</label>
                  <select
                    id="layout-select"
                    className="select"
                    value={layout}
                    onChange={(e) => setLayout(e.target.value as "vertical" | "blur_bg" | "split_screen")}
                  >
                    <option value="vertical">Vertical (Smart face-tracked crop)</option>
                    <option value="blur_bg">Blur Background (Letterboxed 16:9)</option>
                    <option value="split_screen">Split Screen (50/50 Vertical Stack)</option>
                  </select>
                </div>

                {brandKits && brandKits.length > 0 && (
                  <div className="form-group mb-4">
                    <label htmlFor="brand-kit-select">Brand Kit Watermark & Colors</label>
                    <select
                      id="brand-kit-select"
                      className="select"
                      value={selectedBrandKitId}
                      onChange={(e) => setSelectedBrandKitId(e.target.value)}
                    >
                      <option value="">No Brand Kit</option>
                      {brandKits.map((bk) => (
                        <option key={bk.id} value={bk.id}>
                          {bk.name} {bk.logo_key ? "🖼️ (Logo)" : ""}
                        </option>
                      ))}
                    </select>
                  </div>
                )}

                <div className="flex-col gap-3" style={{ display: "flex" }}>
                  <button
                    id="render-btn"
                    className="btn btn-primary w-full"
                    onClick={triggerRender}
                    disabled={rendering}
                  >
                    {rendering ? <><span className="spinner" /> Queuing…</> : "⚡ Re-render with Updated Settings"}
                  </button>

                  <div className="divider" style={{ margin: "var(--space-2) 0" }} />

                  <div className="flex gap-2">
                    <a
                      href={srtUrl}
                      download
                      className="btn btn-secondary btn-sm"
                      style={{ flex: 1, textDecoration: "none", textAlign: "center" }}
                    >
                      📄 SRT
                    </a>
                    <a
                      href={vttUrl}
                      download
                      className="btn btn-secondary btn-sm"
                      style={{ flex: 1, textDecoration: "none", textAlign: "center" }}
                    >
                      📝 VTT
                    </a>
                    {clip.status === "done" && (
                      <button
                        id="download-btn"
                        className="btn btn-secondary btn-sm"
                        style={{ flex: 1.5 }}
                        onClick={fetchVideoUrl}
                        disabled={loadingUrl}
                      >
                        {loadingUrl ? <span className="spinner" /> : "⬇ MP4"}
                      </button>
                    )}
                  </div>
                </div>

                <div className="divider" />
                <small style={{ display: "block", textAlign: "center", color: "var(--text-muted)" }}>
                  Render Status: <span style={{ color: "var(--accent-400)", fontWeight: 600 }}>{clip.status.toUpperCase()}</span>
                </small>
              </div>
            </div>

            {/* Social Publishing Card */}
            <div className="card">
              <div className="card-body">
                <h3 style={{ marginBottom: "var(--space-3)" }}>Social Publishing</h3>
                <p style={{ color: "var(--text-secondary)", fontSize: "0.8125rem", marginBottom: "var(--space-4)" }}>
                  One-click copy formatted captions or publish directly to social channels.
                </p>

                <div className="flex-col gap-3" style={{ display: "flex" }}>
                  {/* YouTube Shorts */}
                  <div
                    style={{
                      padding: "var(--space-3)",
                      background: "rgba(255,255,255,0.03)",
                      borderRadius: "var(--radius-md)",
                      border: "1px solid var(--border-subtle)",
                    }}
                  >
                    <div className="flex items-center justify-between mb-2">
                      <span style={{ fontWeight: 600, fontSize: "0.875rem" }}>🔴 YouTube Shorts</span>
                      <button
                        className="btn btn-secondary btn-sm"
                        style={{ fontSize: "0.75rem", padding: "2px 8px" }}
                        onClick={() => copyCaption("youtube")}
                      >
                        📋 Copy Text
                      </button>
                    </div>
                    <button
                      className="btn btn-secondary btn-sm w-full"
                      onClick={() => handlePublish("youtube")}
                      disabled={publishingPlatform === "youtube"}
                    >
                      {publishingPlatform === "youtube" ? <><span className="spinner" /> Publishing…</> : "🚀 Publish to YouTube"}
                    </button>
                  </div>

                  {/* TikTok */}
                  <div
                    style={{
                      padding: "var(--space-3)",
                      background: "rgba(255,255,255,0.03)",
                      borderRadius: "var(--radius-md)",
                      border: "1px solid var(--border-subtle)",
                    }}
                  >
                    <div className="flex items-center justify-between mb-2">
                      <span style={{ fontWeight: 600, fontSize: "0.875rem" }}>🎵 TikTok</span>
                      <button
                        className="btn btn-secondary btn-sm"
                        style={{ fontSize: "0.75rem", padding: "2px 8px" }}
                        onClick={() => copyCaption("tiktok")}
                      >
                        📋 Copy Text
                      </button>
                    </div>
                    <button
                      className="btn btn-secondary btn-sm w-full"
                      onClick={() => handlePublish("tiktok")}
                      disabled={publishingPlatform === "tiktok"}
                    >
                      {publishingPlatform === "tiktok" ? <><span className="spinner" /> Publishing…</> : "🚀 Publish to TikTok"}
                    </button>
                  </div>

                  {/* Instagram Reels */}
                  <div
                    style={{
                      padding: "var(--space-3)",
                      background: "rgba(255,255,255,0.03)",
                      borderRadius: "var(--radius-md)",
                      border: "1px solid var(--border-subtle)",
                    }}
                  >
                    <div className="flex items-center justify-between mb-2">
                      <span style={{ fontWeight: 600, fontSize: "0.875rem" }}>📸 Instagram Reels</span>
                      <button
                        className="btn btn-secondary btn-sm"
                        style={{ fontSize: "0.75rem", padding: "2px 8px" }}
                        onClick={() => copyCaption("instagram")}
                      >
                        📋 Copy Text
                      </button>
                    </div>
                    <button
                      className="btn btn-secondary btn-sm w-full"
                      onClick={() => handlePublish("instagram")}
                      disabled={publishingPlatform === "instagram"}
                    >
                      {publishingPlatform === "instagram" ? <><span className="spinner" /> Publishing…</> : "🚀 Publish to Instagram"}
                    </button>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>
      </main>
      <ToastContainer />
    </div>
  );
}
