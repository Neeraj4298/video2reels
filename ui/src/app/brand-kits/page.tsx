"use client";
export const dynamic = "force-dynamic";

import { useState } from "react";
import useSWR from "swr";
import { Sidebar } from "@/components/Sidebar";
import { ToastContainer, toast } from "@/components/Toast";
import { api, fetcher } from "@/lib/api";
import type { BrandKit } from "@/lib/types";

export default function BrandKitsPage() {
  const { data: kits, error, mutate } = useSWR<BrandKit[]>("/api/brand-kits", fetcher);
  const [creating, setCreating] = useState(false);
  const [name, setName] = useState("");
  const [primaryColor, setPrimaryColor] = useState("#FFD700");
  const [accentColor, setAccentColor] = useState("#8B5CF6");
  const [submitting, setSubmitting] = useState(false);
  const [uploadingId, setUploadingId] = useState<string | null>(null);

  async function handleCreate(e: React.FormEvent) {
    e.preventDefault();
    if (!name.trim()) return;
    setSubmitting(true);
    try {
      await api.brandKits.create({
        name: name.trim(),
        colors: { primary: primaryColor, accent: accentColor },
        default_caption_style: {
          primary_color: primaryColor,
          highlight_color: accentColor,
        },
      });
      toast("Brand Kit created successfully!", "success");
      setName("");
      setCreating(false);
      mutate();
    } catch (err: unknown) {
      toast(err instanceof Error ? err.message : "Failed to create Brand Kit", "error");
    } finally {
      setSubmitting(false);
    }
  }

  async function handleDelete(id: string) {
    if (!confirm("Are you sure you want to delete this Brand Kit?")) return;
    try {
      await api.brandKits.delete(id);
      toast("Brand Kit deleted", "success");
      mutate();
    } catch {
      toast("Failed to delete Brand Kit", "error");
    }
  }

  async function handleLogoUpload(kitId: string, file: File) {
    setUploadingId(kitId);
    try {
      await api.brandKits.uploadLogo(kitId, file);
      toast("Brand logo uploaded successfully!", "success");
      mutate();
    } catch (err: unknown) {
      toast(err instanceof Error ? err.message : "Failed to upload logo", "error");
    } finally {
      setUploadingId(null);
    }
  }

  return (
    <div className="layout">
      <Sidebar />
      <main className="main-content">
        {/* Header */}
        <div className="flex items-center justify-between mb-8">
          <div>
            <h1 style={{ fontSize: "1.75rem", fontWeight: 700, marginBottom: "4px" }}>
              Brand Kits
            </h1>
            <p style={{ color: "var(--text-secondary)", fontSize: "0.875rem" }}>
              Customize your short-form video watermark logos, brand color palettes, and default caption styling.
            </p>
          </div>
          <button
            className="btn btn-primary"
            onClick={() => setCreating(!creating)}
            id="create-brand-kit-btn"
          >
            {creating ? "Cancel" : "＋ New Brand Kit"}
          </button>
        </div>

        {/* Create Kit Form */}
        {creating && (
          <div className="card mb-8">
            <div className="card-body">
              <h3 style={{ marginBottom: "var(--space-4)" }}>Create New Brand Kit</h3>
              <form onSubmit={handleCreate}>
                <div className="form-group mb-4">
                  <label htmlFor="kit-name">Brand Name</label>
                  <input
                    id="kit-name"
                    type="text"
                    className="input"
                    placeholder="e.g. Acme Media, DevPulse"
                    value={name}
                    onChange={(e) => setName(e.target.value)}
                    required
                  />
                </div>

                <div className="flex gap-4 mb-6">
                  <div className="form-group" style={{ flex: 1 }}>
                    <label>Primary Caption Color</label>
                    <div className="flex items-center gap-2">
                      <input
                        type="color"
                        value={primaryColor}
                        onChange={(e) => setPrimaryColor(e.target.value)}
                        style={{ width: 44, height: 38, border: "none", cursor: "pointer", borderRadius: "var(--radius-sm)" }}
                      />
                      <input
                        type="text"
                        className="input"
                        value={primaryColor}
                        onChange={(e) => setPrimaryColor(e.target.value)}
                      />
                    </div>
                  </div>

                  <div className="form-group" style={{ flex: 1 }}>
                    <label>Highlight Word Accent</label>
                    <div className="flex items-center gap-2">
                      <input
                        type="color"
                        value={accentColor}
                        onChange={(e) => setAccentColor(e.target.value)}
                        style={{ width: 44, height: 38, border: "none", cursor: "pointer", borderRadius: "var(--radius-sm)" }}
                      />
                      <input
                        type="text"
                        className="input"
                        value={accentColor}
                        onChange={(e) => setAccentColor(e.target.value)}
                      />
                    </div>
                  </div>
                </div>

                <div className="flex justify-end gap-3">
                  <button
                    type="button"
                    className="btn btn-secondary"
                    onClick={() => setCreating(false)}
                  >
                    Cancel
                  </button>
                  <button
                    type="submit"
                    className="btn btn-primary"
                    disabled={submitting}
                  >
                    {submitting ? <><span className="spinner" /> Creating…</> : "Save Brand Kit"}
                  </button>
                </div>
              </form>
            </div>
          </div>
        )}

        {/* Brand Kits Grid */}
        {error && (
          <div className="card">
            <div className="card-body text-center" style={{ color: "var(--rose-400)" }}>
              Failed to load brand kits. Make sure the backend API is running.
            </div>
          </div>
        )}

        {!kits && !error && (
          <div className="card">
            <div className="card-body text-center" style={{ padding: "var(--space-12)" }}>
              <span className="spinner" style={{ width: 28, height: 28 }} />
              <p style={{ marginTop: "var(--space-3)", color: "var(--text-muted)" }}>Loading Brand Kits…</p>
            </div>
          </div>
        )}

        {kits && kits.length === 0 && (
          <div className="card">
            <div className="card-body text-center" style={{ padding: "var(--space-12)" }}>
              <div style={{ fontSize: "3rem", marginBottom: "var(--space-3)" }}>🎨</div>
              <h3 style={{ marginBottom: "var(--space-2)" }}>No Brand Kits Yet</h3>
              <p style={{ color: "var(--text-secondary)", maxWidth: 440, margin: "0 auto var(--space-6)" }}>
                Create a Brand Kit to burn your company logo watermark into your Reels and apply custom color palettes.
              </p>
              <button className="btn btn-primary" onClick={() => setCreating(true)}>
                ＋ Create Brand Kit
              </button>
            </div>
          </div>
        )}

        {kits && kits.length > 0 && (
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(320px, 1fr))", gap: "var(--space-6)" }}>
            {kits.map((kit) => (
              <div key={kit.id} className="card" style={{ display: "flex", flexDirection: "column" }}>
                <div className="card-body" style={{ flex: 1 }}>
                  <div className="flex items-center justify-between mb-4">
                    <h3 style={{ fontSize: "1.2rem", fontWeight: 700 }}>{kit.name}</h3>
                    <button
                      className="btn btn-danger btn-sm"
                      onClick={() => handleDelete(kit.id)}
                      title="Delete Brand Kit"
                    >
                      Delete
                    </button>
                  </div>

                  {/* Logo Watermark section */}
                  <div className="mb-4">
                    <label style={{ fontSize: "0.8125rem", color: "var(--text-secondary)", display: "block", marginBottom: 6 }}>
                      Logo Watermark (Top-Right of Reel)
                    </label>
                    <div
                      style={{
                        padding: "var(--space-4)",
                        background: "rgba(255,255,255,0.03)",
                        border: "1px dashed var(--border-subtle)",
                        borderRadius: "var(--radius-md)",
                        textAlign: "center",
                      }}
                    >
                      {kit.logo_key ? (
                        <div className="flex items-center justify-center gap-3">
                          <span style={{ fontSize: "1.5rem" }}>🖼️</span>
                          <span style={{ fontSize: "0.8125rem", color: "var(--green-400)", fontWeight: 600 }}>
                            Logo Uploaded ✓
                          </span>
                        </div>
                      ) : (
                        <p style={{ fontSize: "0.8125rem", color: "var(--text-muted)", marginBottom: "var(--space-2)" }}>
                          No logo uploaded. Upload a PNG/JPEG logo.
                        </p>
                      )}

                      <label
                        className="btn btn-secondary btn-sm"
                        style={{ cursor: "pointer", display: "inline-block", marginTop: "var(--space-2)" }}
                      >
                        {uploadingId === kit.id ? (
                          <><span className="spinner" /> Uploading…</>
                        ) : (
                          kit.logo_key ? "Change Logo" : "Upload Logo"
                        )}
                        <input
                          type="file"
                          accept="image/png,image/jpeg"
                          style={{ display: "none" }}
                          disabled={uploadingId === kit.id}
                          onChange={(e) => {
                            const file = e.target.files?.[0];
                            if (file) handleLogoUpload(kit.id, file);
                          }}
                        />
                      </label>
                    </div>
                  </div>

                  {/* Colors */}
                  <div className="mb-2">
                    <label style={{ fontSize: "0.8125rem", color: "var(--text-secondary)", display: "block", marginBottom: 6 }}>
                      Palette Preview
                    </label>
                    <div className="flex items-center gap-2">
                      <div
                        style={{
                          width: 28,
                          height: 28,
                          borderRadius: "50%",
                          background: (kit.colors?.primary as string) || "#FFD700",
                          border: "2px solid rgba(255,255,255,0.15)",
                        }}
                        title={`Primary: ${(kit.colors?.primary as string) || "#FFD700"}`}
                      />
                      <div
                        style={{
                          width: 28,
                          height: 28,
                          borderRadius: "50%",
                          background: (kit.colors?.accent as string) || "#8B5CF6",
                          border: "2px solid rgba(255,255,255,0.15)",
                        }}
                        title={`Accent: ${(kit.colors?.accent as string) || "#8B5CF6"}`}
                      />
                      <span style={{ fontSize: "0.8125rem", color: "var(--text-muted)", marginLeft: 6 }}>
                        {(kit.colors?.primary as string) || "#FFD700"} / {(kit.colors?.accent as string) || "#8B5CF6"}
                      </span>
                    </div>
                  </div>
                </div>
              </div>
            ))}
          </div>
        )}
      </main>
      <ToastContainer />
    </div>
  );
}
