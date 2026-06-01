from __future__ import annotations

from datetime import UTC, datetime
from enum import Enum
from typing import Any
from uuid import uuid4

from pgvector.sqlalchemy import Vector
from sqlalchemy import JSON, DateTime, Enum as SqlEnum, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from app.core.config import get_settings

settings = get_settings()
EmbeddingColumn = Vector(settings.embedding_dimensions).with_variant(JSON(), "sqlite")


class Base(DeclarativeBase):
    pass


class SourceType(str, Enum):
    WEB = "web"
    PDF = "pdf"
    MANUAL = "manual"
    YOUTUBE = "youtube"


class QuestionStatus(str, Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    ANSWERED = "answered"
    FAILED = "failed"


class StreamStatus(str, Enum):
    CONNECTED = "connected"
    DISCONNECTED = "disconnected"
    STOPPED = "stopped"
    ERROR = "error"


def timestamp() -> datetime:
    return datetime.now(UTC)


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    source_type: Mapped[SourceType] = mapped_column(SqlEnum(SourceType), nullable=False)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    source_url: Mapped[str | None] = mapped_column(String(1000))
    file_name: Mapped[str | None] = mapped_column(String(255))
    checksum: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=timestamp)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=timestamp, onupdate=timestamp)

    chunks: Mapped[list["Chunk"]] = relationship(
        back_populates="document",
        cascade="all, delete-orphan",
        order_by="Chunk.ordinal",
    )


class AppSetting(Base):
    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    value: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=timestamp, onupdate=timestamp)


class Chunk(Base):
    __tablename__ = "chunks"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    document_id: Mapped[str] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), nullable=False)
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    token_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    embedding: Mapped[list[float] | None] = mapped_column(EmbeddingColumn)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=timestamp)

    document: Mapped[Document] = relationship(back_populates="chunks")
    traces: Mapped[list["AnswerTrace"]] = relationship(back_populates="chunk", passive_deletes=True)


class StreamSession(Base):
    __tablename__ = "stream_sessions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    youtube_video_id: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    live_chat_id: Mapped[str] = mapped_column(String(128), nullable=False)
    title: Mapped[str | None] = mapped_column(String(500))
    status: Mapped[StreamStatus] = mapped_column(SqlEnum(StreamStatus), default=StreamStatus.CONNECTED)
    next_page_token: Mapped[str | None] = mapped_column(String(256))
    last_polled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=timestamp)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=timestamp, onupdate=timestamp)

    questions: Mapped[list["Question"]] = relationship(back_populates="stream_session")


class Question(Base):
    __tablename__ = "questions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    source_type: Mapped[SourceType] = mapped_column(SqlEnum(SourceType), nullable=False)
    source_message_id: Mapped[str | None] = mapped_column(String(128), unique=True)
    author_name: Mapped[str | None] = mapped_column(String(255))
    content: Mapped[str] = mapped_column(Text, nullable=False)
    normalized_content: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[QuestionStatus] = mapped_column(SqlEnum(QuestionStatus), default=QuestionStatus.PENDING)
    error_message: Mapped[str | None] = mapped_column(Text)
    stream_session_id: Mapped[str | None] = mapped_column(ForeignKey("stream_sessions.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=timestamp)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=timestamp, onupdate=timestamp)

    stream_session: Mapped[StreamSession | None] = relationship(back_populates="questions")
    answer: Mapped["Answer | None"] = relationship(back_populates="question", cascade="all, delete-orphan", uselist=False)


class Answer(Base):
    __tablename__ = "answers"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    question_id: Mapped[str] = mapped_column(ForeignKey("questions.id", ondelete="CASCADE"), unique=True, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    model_name: Mapped[str] = mapped_column(String(255), nullable=False)
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    fallback_used: Mapped[bool] = mapped_column(default=False)
    audio_url: Mapped[str | None] = mapped_column(String(1000))
    audio_duration_ms: Mapped[int | None] = mapped_column(Integer)
    audio_model_name: Mapped[str | None] = mapped_column(String(255))
    audio_error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=timestamp)

    question: Mapped[Question] = relationship(back_populates="answer")
    traces: Mapped[list["AnswerTrace"]] = relationship(back_populates="answer", cascade="all, delete-orphan")


class AnswerTrace(Base):
    __tablename__ = "answer_traces"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    answer_id: Mapped[str] = mapped_column(ForeignKey("answers.id", ondelete="CASCADE"), nullable=False)
    chunk_id: Mapped[str] = mapped_column(ForeignKey("chunks.id", ondelete="CASCADE"), nullable=False)
    source_title: Mapped[str] = mapped_column(String(500), nullable=False)
    source_url: Mapped[str | None] = mapped_column(String(1000))
    snippet: Mapped[str] = mapped_column(Text, nullable=False)
    vector_score: Mapped[float] = mapped_column(Float, default=0.0)
    keyword_score: Mapped[float] = mapped_column(Float, default=0.0)
    final_score: Mapped[float] = mapped_column(Float, default=0.0)

    answer: Mapped[Answer] = relationship(back_populates="traces")
    chunk: Mapped[Chunk] = relationship(back_populates="traces")
