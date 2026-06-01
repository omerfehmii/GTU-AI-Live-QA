export type SourceType = "web" | "pdf" | "manual" | "youtube";
export type QuestionStatus = "pending" | "processing" | "answered" | "failed";
export type StreamStatus = "connected" | "disconnected" | "stopped" | "error";
export type AvatarState = "idle" | "listening" | "thinking" | "speaking" | "error";

export interface Answer {
  id: string;
  content: string;
  fallback_used: boolean;
  audio_url: string | null;
  audio_duration_ms: number | null;
  audio_model_name: string | null;
  created_at: string;
}

export interface Question {
  id: string;
  source_type: SourceType;
  source_message_id: string | null;
  author_name: string | null;
  content: string;
  status: QuestionStatus;
  error_message: string | null;
  created_at: string;
  answer: Answer | null;
}

export interface Metrics {
  documents: number;
  chunks: number;
  questions_total: number;
  questions_answered: number;
  active_streams: number;
  avg_latency_ms: number;
}

export interface LiveState {
  avatar_state: AvatarState;
  current_question: Question | null;
  latest_answered: Question | null;
  queue: Question[];
  queue_size: number;
  active_streams: number;
  generated_at: string;
}

export interface StreamSession {
  id: string;
  youtube_video_id: string;
  live_chat_id: string;
  title: string | null;
  status: StreamStatus;
  error_message: string | null;
  last_polled_at: string | null;
  created_at: string;
}

export interface AdminSettings {
  tts_enabled: boolean;
  tts_provider: string;
  tts_model: string;
  tts_voice: string;
}

export interface DocumentItem {
  id: string;
  source_type: SourceType;
  title: string;
  source_url: string | null;
  file_name: string | null;
  metadata_json: Record<string, unknown>;
  created_at: string;
}

export interface IngestSummary {
  documents_created: number;
  chunks_created: number;
  skipped: number;
}

export interface ArchiveCrawlSummary {
  sources_archived: number;
  sources_loaded_from_cache: number;
  sitemap_urls_discovered: number;
  skipped: number;
}

export interface ArchiveStats {
  total_sources: number;
  web_sources: number;
  pdf_sources: number;
  raw_files_present: number;
  total_bytes: number;
  indexed_documents: number;
  last_cached_at: string | null;
}
