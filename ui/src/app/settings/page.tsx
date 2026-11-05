"use client";

import { useEffect, useState } from "react";
import { Sidebar } from "@/components/Sidebar";
import { ToastContainer, toast } from "@/components/Toast";

const DEFAULTS = {
  api_base: "http://localhost:8000",
  default_layout: "vertical",
  default_clip_max_duration: "90",
  default_clip_min_duration: "30",
};

type Settings = typeof DEFAULTS;

export default function SettingsPage() {
  const [settings, setSettings] = useState<Settings>(DEFAULTS);
  const [apiStatus, setApiStatus] = useState<"checking" | "ok" | "error">("checking");

  // Load from localStorage
  useEffect(() => {
    const loaded: Partial<Settings> = {};
    for (const key of Object.keys(DEFAULTS) as (keyof Settings)[]) {
      const v = localStorage.getItem(key);
      if (v !== null) loaded[key] = v;
    }
    setSettings((prev) => ({ ...prev, ...loaded }));
    checkApi(loaded.api_base ?? DEFAULTS.api_base);
  }, []);

  async function checkApi(base: string) {
    setApiStatus("checking");
    try {
      const res = await fetch(`${base}/health`, { signal: AbortSignal.timeout(3000) });
      setApiStatus(res.ok ? "ok" : "error");
    } catch {
      setApiStatus("error");
    }
  }

  function save() {
    for (const [k, v] of Object.entries(settings)) {
      localStorage.setItem(k, v);
    }
    toast("Settings saved!", "success");
    checkApi(settings.api_base);
  }

  function reset() {
    for (const k of Object.keys(DEFAULTS)) localStorage.removeItem(k);
    setSettings(DEFAULTS);
    toast("Settings reset to defaults", "info");
    checkApi(DEFAULTS.api_base);
  }

  const statusColor =
    apiStatus === "ok" ? "var(--green-400)" :
    apiStatus === "error" ? "var(--rose-400)" :
    "var(--amber-400)";

  const statusLabel =
    apiStatus === "ok" ? "✅ Connected" :
    apiStatus === "error" ? "❌ Unreachable" :
    "⏳ Checking…";

  return (
    <div className="app-shell">
      <Sidebar />
      <main className="main-content">
        <div className="page-header">
          <div>
            <h1 className="page-title">Settings</h1>
            <p className="page-subtitle">Configure the API endpoint and pipeline defaults.</p>
          </div>
        </div>

        <div style={{ maxWidth: 640, display: "flex", flexDirection: "column", gap: "var(--space-6)" }}>

          {/* API Configuration */}
          <div className="card">
            <div className="card-body">
              <h3 style={{ marginBottom: "var(--space-5)" }}>API Configuration</h3>

              <div className="form-group mb-4">
                <label htmlFor="api-base-input">Backend URL</label>
                <div className="flex gap-3" style={{ alignItems: "center" }}>
                  <input
                    id="api-base-input"
                    className="input"
                    placeholder="http://localhost:8000"
                    value={settings.api_base}
                    onChange={(e) => setSettings((s) => ({ ...s, api_base: e.target.value }))}
                  />
                  <button
                    className="btn btn-secondary btn-sm"
                    style={{ whiteSpace: "nowrap" }}
                    onClick={() => checkApi(settings.api_base)}
                  >
                    Test
                  </button>
                </div>
              </div>

              <div
                className="flex items-center gap-3"
                style={{
                  padding: "var(--space-3) var(--space-4)",
                  background: "var(--bg-elevated)",
                  borderRadius: "var(--radius-md)",
                  border: "1px solid var(--border-subtle)",
                }}
              >
                <span
                  style={{
                    width: 10,
                    height: 10,
                    borderRadius: "50%",
                    background: statusColor,
                    display: "inline-block",
                    boxShadow: `0 0 8px ${statusColor}`,
                    flexShrink: 0,
                  }}
                />
                <span style={{ fontSize: "0.875rem", color: statusColor, fontWeight: 600 }}>
                  {statusLabel}
                </span>
              </div>
            </div>
          </div>

          {/* Pipeline Defaults */}
          <div className="card">
            <div className="card-body">
              <h3 style={{ marginBottom: "var(--space-5)" }}>Pipeline Defaults</h3>

              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "var(--space-4)", marginBottom: "var(--space-4)" }}>
                <div className="form-group">
                  <label htmlFor="min-dur">Min Clip Duration (s)</label>
                  <input
                    id="min-dur"
                    className="input font-mono"
                    type="number"
                    min={10}
                    max={120}
                    value={settings.default_clip_min_duration}
                    onChange={(e) => setSettings((s) => ({ ...s, default_clip_min_duration: e.target.value }))}
                  />
                </div>
                <div className="form-group">
                  <label htmlFor="max-dur">Max Clip Duration (s)</label>
                  <input
                    id="max-dur"
                    className="input font-mono"
                    type="number"
                    min={30}
                    max={300}
                    value={settings.default_clip_max_duration}
                    onChange={(e) => setSettings((s) => ({ ...s, default_clip_max_duration: e.target.value }))}
                  />
                </div>
              </div>

              <div className="form-group">
                <label htmlFor="default-layout">Default Layout</label>
                <select
                  id="default-layout"
                  className="select"
                  value={settings.default_layout}
                  onChange={(e) => setSettings((s) => ({ ...s, default_layout: e.target.value }))}
                >
                  <option value="vertical">Vertical (face-tracked crop)</option>
                  <option value="blur_bg">Blur Background (letterbox)</option>
                  <option value="split_screen">Split Screen (50/50 vertical stack)</option>
                </select>
              </div>
            </div>
          </div>

          {/* About */}
          <div className="card">
            <div className="card-body">
              <h3 style={{ marginBottom: "var(--space-4)" }}>About</h3>
              <div style={{ display: "grid", gridTemplateColumns: "auto 1fr", gap: "var(--space-2) var(--space-6)", fontSize: "0.875rem" }}>
                {[
                  ["Version", "v2.0.0 (Phase 5)"],
                  ["Backend", "FastAPI + Celery + PostgreSQL"],
                  ["AI Models", "Gemini 2.0 Flash / Claude / Ollama · Faster-Whisper + Diarization"],
                  ["Reframing", "MediaPipe BlazeFace · PySceneDetect · Kalman + EMA smoothing"],
                  ["Export", "FFmpeg H.264 1080×1920 @ 30fps + Brand Kit Watermark"],
                ].map(([label, value]) => (
                  <>
                    <span key={`l-${label}`} style={{ color: "var(--text-muted)", fontWeight: 500 }}>{label}</span>
                    <span key={`v-${label}`} style={{ color: "var(--text-secondary)" }}>{value}</span>
                  </>
                ))}
              </div>
            </div>
          </div>

          {/* Actions */}
          <div className="flex gap-3" style={{ justifyContent: "flex-end" }}>
            <button className="btn btn-ghost" onClick={reset}>
              Reset Defaults
            </button>
            <button
              id="save-settings-btn"
              className="btn btn-primary"
              onClick={save}
            >
              💾 Save Settings
            </button>
          </div>
        </div>
      </main>
      <ToastContainer />
    </div>
  );
}
