from __future__ import annotations

from datetime import datetime
from typing import Literal
from typing import Any

from pydantic import BaseModel, Field, HttpUrl

from app.models import QuestionStatus, SourceType, SpeechJobKind, SpeechJobStatus, StreamStatus


class WebIngestRequest(BaseModel):
    seed_urls: list[HttpUrl]
    pdf_urls: list[HttpUrl] = Field(default_factory=list)
    sitemap_urls: list[HttpUrl] = Field(default_factory=list)
    allowed_domains: list[str] = Field(default_factory=list)
    include_url_patterns: list[str] = Field(default_factory=list)
    prioritize_url_patterns: list[str] = Field(default_factory=list)
    discover_sitemaps: bool = True
    use_cached_sources: bool = True
    refresh_cached_sources: bool = False
    max_pages: int = Field(default=12, ge=1, le=500)


class IndexRebuildRequest(BaseModel):
    document_ids: list[str] | None = None


class ArchiveIndexRequest(BaseModel):
    cache_keys: list[str] | None = None


class YoutubeConnectRequest(BaseModel):
    video_id: str = Field(min_length=3, max_length=64)


class ManualQuestionRequest(BaseModel):
    content: str = Field(min_length=5, max_length=2000)
    author_name: str | None = Field(default="Demo kullanici", max_length=255)


PetVariant = Literal["screen_touch", "yarn", "box"]


class LiveDisplaySettingsRead(BaseModel):
    live_pet_enabled: bool
    live_pet_variant: PetVariant
    live_pet_animation_seconds: float
    live_pet_interval_seconds: float
    live_pet_size_px: int
    avatar_blink_interval_seconds: float
    avatar_blink_duration_seconds: float


class AdminSettingsUpdate(BaseModel):
    tts_enabled: bool | None = None
    live_pet_enabled: bool | None = None
    live_pet_variant: PetVariant | None = None
    live_pet_animation_seconds: float | None = Field(default=None, ge=1.5, le=12)
    live_pet_interval_seconds: float | None = Field(default=None, ge=15, le=300)
    live_pet_size_px: int | None = Field(default=None, ge=50, le=180)
    avatar_blink_interval_seconds: float | None = Field(default=None, ge=3, le=12)
    avatar_blink_duration_seconds: float | None = Field(default=None, ge=0.1, le=0.5)


class AdminSettingsRead(BaseModel):
    tts_enabled: bool
    tts_provider: str
    tts_model: str
    tts_voice: str
    live_pet_enabled: bool
    live_pet_variant: PetVariant
    live_pet_animation_seconds: float
    live_pet_interval_seconds: float
    live_pet_size_px: int
    avatar_blink_interval_seconds: float
    avatar_blink_duration_seconds: float


class DocumentRead(BaseModel):
    id: str
    source_type: SourceType
    title: str
    source_url: str | None
    file_name: str | None
    metadata_json: dict[str, Any]
    created_at: datetime

    model_config = {"from_attributes": True}


class StreamSessionRead(BaseModel):
    id: str
    youtube_video_id: str
    live_chat_id: str
    title: str | None
    status: StreamStatus
    error_message: str | None
    last_polled_at: datetime | None
    created_at: datetime

    model_config = {"from_attributes": True}


class AnswerTraceRead(BaseModel):
    id: str
    chunk_id: str
    source_title: str
    source_url: str | None
    snippet: str
    vector_score: float
    keyword_score: float
    final_score: float

    model_config = {"from_attributes": True}


class AnswerRead(BaseModel):
    id: str
    content: str
    speech_content: str | None
    fallback_used: bool
    audio_url: str | None
    audio_duration_ms: int | None
    audio_model_name: str | None
    created_at: datetime

    model_config = {"from_attributes": True}


class QuestionRead(BaseModel):
    id: str
    source_type: SourceType
    source_message_id: str | None
    author_name: str | None
    content: str
    status: QuestionStatus
    error_message: str | None
    created_at: datetime
    answer: AnswerRead | None = None

    model_config = {"from_attributes": True}


class SpeechJobRead(BaseModel):
    id: str
    kind: SpeechJobKind
    status: SpeechJobStatus
    audio_url: str | None
    audio_duration_ms: int | None
    audio_model_name: str | None
    error_message: str | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class PlaybackItemRead(BaseModel):
    kind: Literal["idle", "ambient", "answer", "transition", "queue_wait", "error"]
    phase: Literal[
        "idle",
        "ambient",
        "preparing_answer",
        "answer_ready_waiting",
        "handoff",
        "answering",
        "queue_mode",
        "error",
    ]
    title: str
    text: str
    speech_key: str
    audio_url: str | None
    audio_duration_ms: int | None
    speech_status: Literal["none", "disabled", "pending", "generating", "ready", "failed", "text_only"]
    question_id: str | None = None
    answer_id: str | None = None
    segment_id: str | None = None
    started_at: datetime
    expected_end_at: datetime
    can_interrupt_after: datetime
    max_interrupt_at: datetime


class LiveStateRead(BaseModel):
    avatar_state: Literal["idle", "listening", "thinking", "speaking", "ambient", "handoff", "error"]
    current_phase: Literal[
        "idle",
        "ambient",
        "preparing_answer",
        "answer_ready_waiting",
        "handoff",
        "answering",
        "queue_mode",
        "error",
    ]
    playback_item: PlaybackItemRead | None
    current_question: QuestionRead | None
    latest_answered: QuestionRead | None
    queue: list[QuestionRead]
    queue_size: int
    answer_ready_count: int
    speech_queue_size: int
    active_streams: int
    display_settings: LiveDisplaySettingsRead
    generated_at: datetime


class IngestSummary(BaseModel):
    documents_created: int
    chunks_created: int
    skipped: int


class ArchiveCrawlSummary(BaseModel):
    sources_archived: int
    sources_loaded_from_cache: int
    sitemap_urls_discovered: int
    skipped: int


class ArchiveStatsRead(BaseModel):
    total_sources: int
    web_sources: int
    pdf_sources: int
    raw_files_present: int
    total_bytes: int
    indexed_documents: int
    last_cached_at: datetime | None


class MetricsRead(BaseModel):
    documents: int
    chunks: int
    questions_total: int
    questions_answered: int
    active_streams: int
    avg_latency_ms: float
