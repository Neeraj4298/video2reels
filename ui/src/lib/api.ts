/**
 * Typed API client for video2reels FastAPI backend.
 * Reads API_BASE from NEXT_PUBLIC_API_URL env var (default: http://localhost:8000)
 */

import type {
  BrandKit,
  Clip,
  ClipMetadataResponse,
  ClipTranscript,
  ClipUpdate,
  DownloadResponse,
  PresignedUploadResponse,
  Project,
  ProjectDetail,
  PublishRequest,
  PublishResponse,
  RenderRequest,
} from "./types";

const getBase = () =>
  (typeof window !== "undefined"
    ? localStorage.getItem("api_base")
    : null) ||
  process.env.NEXT_PUBLIC_API_URL ||
  "http://localhost:8000";

async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${getBase()}${path}`, {
    headers: { "Content-Type": "application/json", ...init?.headers },
    ...init,
  });
  if (!res.ok) {
    const text = await res.text().catch(() => res.statusText);
    throw new Error(`${res.status} ${text}`);
  }
  if (res.status === 204) return undefined as T;
  return res.json() as Promise<T>;
}

// ─── Projects ─────────────────────────────────────────────────────────────────

export const api = {
  projects: {
    list: () => apiFetch<Project[]>("/api/projects"),

    get: (id: string) => apiFetch<ProjectDetail>(`/api/projects/${id}`),

    create: (body: { name?: string; source_url?: string; user_prompt?: string }) =>
      apiFetch<Project>("/api/projects", {
        method: "POST",
        body: JSON.stringify(body),
      }),

    delete: (id: string) =>
      apiFetch<void>(`/api/projects/${id}`, { method: "DELETE" }),

    resume: (id: string) =>
      apiFetch<{ message: string; task_id: string }>(
        `/api/projects/${id}/resume`,
        { method: "POST" }
      ),

    reclip: (id: string, userPrompt?: string) =>
      apiFetch<{ message: string; project_id: string; task_id: string; user_prompt?: string }>(
        `/api/projects/${id}/reclip`,
        {
          method: "POST",
          body: JSON.stringify({ user_prompt: userPrompt || null }),
        }
      ),

    exportZipUrl: (id: string) => `${getBase()}/api/projects/${id}/export/zip`,

    // Returns a presigned PUT URL for direct browser → MinIO upload
    presignedUpload: (projectId: string, filename: string) =>
      apiFetch<PresignedUploadResponse>(
        `/api/uploads/presigned?project_id=${projectId}&filename=${encodeURIComponent(filename)}`
      ),
  },

  clips: {
    list: (projectId: string) =>
      apiFetch<Clip[]>(`/api/projects/${projectId}/clips`),

    update: (clipId: string, body: ClipUpdate) =>
      apiFetch<Clip>(`/api/clips/${clipId}`, {
        method: "PATCH",
        body: JSON.stringify(body),
      }),

    render: (clipId: string, body: RenderRequest) =>
      apiFetch<{ task_id: string; clip_id: string; status: string }>(
        `/api/clips/${clipId}/render`,
        { method: "POST", body: JSON.stringify(body) }
      ),

    download: (clipId: string) =>
      apiFetch<DownloadResponse>(`/api/clips/${clipId}/download`),

    transcript: (clipId: string) =>
      apiFetch<ClipTranscript>(`/api/clips/${clipId}/transcript`),

    subtitlesUrl: (clipId: string, format: "srt" | "vtt" = "srt") =>
      `${getBase()}/api/clips/${clipId}/subtitles?format=${format}`,

    exportXmlUrl: (clipId: string) =>
      `${getBase()}/api/clips/${clipId}/export-xml`,

    edl: (clipId: string) =>
      apiFetch<Record<string, unknown>>(`/api/clips/${clipId}/edl`),

    updateEdl: (clipId: string, body: Record<string, unknown>) =>
      apiFetch<Record<string, unknown>>(`/api/clips/${clipId}/edl`, {
        method: "PATCH",
        body: JSON.stringify(body),
      }),


    regenerateMetadata: (clipId: string) =>
      apiFetch<ClipMetadataResponse>(`/api/clips/${clipId}/metadata`, {
        method: "POST",
      }),

    publish: (clipId: string, body: PublishRequest) =>
      apiFetch<PublishResponse>(`/api/clips/${clipId}/publish`, {
        method: "POST",
        body: JSON.stringify(body),
      }),
  },

  brandKits: {
    list: () => apiFetch<BrandKit[]>("/api/brand-kits"),

    create: (body: Partial<BrandKit>) =>
      apiFetch<BrandKit>("/api/brand-kits", {
        method: "POST",
        body: JSON.stringify(body),
      }),

    delete: (id: string) =>
      apiFetch<void>(`/api/brand-kits/${id}`, { method: "DELETE" }),

    uploadLogo: async (kitId: string, file: File): Promise<BrandKit> => {
      const formData = new FormData();
      formData.append("file", file);
      const res = await fetch(`${getBase()}/api/brand-kits/${kitId}/logo`, {
        method: "POST",
        body: formData,
      });
      if (!res.ok) {
        const text = await res.text().catch(() => res.statusText);
        throw new Error(`${res.status} ${text}`);
      }
      return res.json() as Promise<BrandKit>;
    },
  },
};

// ─── SSE helper ──────────────────────────────────────────────────────────────

export function createEventSource(projectId: string): EventSource {
  return new EventSource(
    `${getBase()}/api/projects/${projectId}/events`
  );
}

// ─── SWR fetcher ─────────────────────────────────────────────────────────────

export const fetcher = (url: string) =>
  fetch(`${getBase()}${url}`).then((r) => {
    if (!r.ok) throw new Error(r.statusText);
    return r.json();
  });
