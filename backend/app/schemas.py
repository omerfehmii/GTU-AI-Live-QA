from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, HttpUrl

from app.models import QuestionStatus, SourceType, StreamStatus


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
    fallback_used: bool
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
