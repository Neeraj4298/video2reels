// ─── Projects ────────────────────────────────────────────────────────────────

export type ProjectStatus =
  | "pending"
  | "processing"
  | "done"
  | "failed"
  | "paused";

export type SourceType = "url" | "upload";

export interface Project {
  id: string;
  name: string | null;
  source_type: SourceType;
  source_url: string | null;
  status: ProjectStatus;
  created_at: string;
}

export interface ProjectDetail extends Project {
  clips: Clip[];
  jobs: Job[];
}

// ─── Clips ────────────────────────────────────────────────────────────────────

export type ClipStatus = "pending" | "rendering" | "done" | "failed";

export interface ScoreBreakdown {
  llm?: number;
  energy?: number;
  emotion?: number;
  hook?: number;
}

export interface Clip {
  id: string;
  project_id: string;
  start: number;
  end: number;
  score: number | null;
  score_breakdown: ScoreBreakdown | null;
  hook: string | null;
  title: string | null;
  description: string | null;
  hashtags: string[] | null;
  status: ClipStatus;
  selected: boolean;
}

export interface ClipUpdate {
  start?: number;
  end?: number;
  title?: string;
  hook?: string;
  selected?: boolean;
  caption_style?: Record<string, unknown>;
  excluded_word_indices?: number[];
  word_overrides?: Record<string, string>;
  edl?: Record<string, unknown>;
}


// ─── Jobs ─────────────────────────────────────────────────────────────────────

export type JobStatus = "queued" | "running" | "done" | "failed" | "skipped";

export interface Job {
  id: string;
  project_id: string;
  stage: string | null;
  status: JobStatus;
  progress: number;
  error: string | null;
  attempts: number;
  started_at: string | null;
  finished_at: string | null;
}

// ─── SSE Events ───────────────────────────────────────────────────────────────

export interface ProgressEvent {
  stage: string;
  progress: number;
  message: string;
  clips_done?: number;
  clips_total?: number;
  clip_count?: number;
}

// ─── Uploads ─────────────────────────────────────────────────────────────────

export interface PresignedUploadResponse {
  upload_url: string;
  storage_key: string;
  project_id: string;
}

// ─── Render ───────────────────────────────────────────────────────────────────

export interface RenderRequest {
  layout?: "vertical" | "blur_bg" | "split_screen";
  caption_style?: Record<string, unknown>;
  brand_kit_id?: string;
  excluded_word_indices?: number[];
  word_overrides?: Record<string, string>;
  edl?: Record<string, unknown>;
}


export interface ReclipRequest {
  user_prompt?: string;
}

export interface PublishRequest {
  platform: "youtube" | "tiktok" | "instagram";
  title?: string;
  description?: string;
  scheduled_at?: string;
}

export interface PublishResponse {
  clip_id: string;
  platform: string;
  status: "published" | "scheduled";
  scheduled_at: string | null;
  message: string;
}

export interface ClipMetadataResponse {
  title: string;
  description: string;
  hashtags: string[];
}

export interface BrandKit {
  id: string;
  name: string;
  logo_key: string | null;
  fonts: Record<string, unknown> | null;
  colors: Record<string, unknown> | null;
  default_caption_style: Record<string, unknown> | null;
}

export interface DownloadResponse {
  download_url: string;
  expires_in: number;
}

// ─── Transcripts & Captions (Phase 4) ─────────────────────────────────────────

export interface TranscriptWord {
  id?: string;
  w: string;
  s: number;
  e: number;
  p: number;
  speaker?: string;
}

export interface ClipTranscript {
  clip_id: string;
  start: number;
  end: number;
  words: TranscriptWord[];
  text: string;
  excluded_word_indices?: number[];
  word_overrides?: Record<string, string>;
}


export interface CaptionStyleConfig {
  preset?: string;
  font_name?: string;
  font_size?: number;
  bold?: boolean;
  primary_color?: string;
  highlight_color?: string;
  outline_color?: string;
}

