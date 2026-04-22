from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal
from typing import Annotated

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=(".env", "../.env"), env_file_encoding="utf-8", extra="ignore")

    app_name: str = "GTU AI Live QA"
    api_prefix: str = "/api"
    database_url: str = "sqlite:///./gtu_ai.db"
    redis_url: str = "redis://localhost:6379/0"
    backend_cors_origins: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["http://localhost:3000"]
    )
    ai_provider: Literal["openai", "openrouter"] = "openai"
    ai_chat_model: str | None = None
    ai_embedding_model: str | None = None
    openai_api_key: str | None = None
    openai_chat_model: str = "gpt-4.1-mini"
    openai_embedding_model: str = "text-embedding-3-small"
    openrouter_api_key: str | None = None
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    openrouter_site_url: str | None = "http://localhost"
    openrouter_app_name: str = "GTU AI Live QA"
    embedding_dimensions: int = 1536
    embedding_batch_size: int = 32
    chunk_size: int = 400
    chunk_overlap: int = 80
    retrieval_top_k: int = 6
    retrieval_candidate_count: int = 24
    llm_context_limit: int = 3
    llm_context_chars: int = 1200
    llm_timeout_seconds: float = 20.0
    llm_max_output_tokens: int = 220
    low_confidence_threshold: float = 0.22
    source_archive_dir: str = "data/source_archive"
    youtube_api_key: str | None = None
    youtube_poll_interval_seconds: int = 5
    admin_username: str = "admin"
    admin_password: str = "change-me-demo"

    @field_validator("backend_cors_origins", mode="before")
    @classmethod
    def parse_origins(cls, value: str | list[str]) -> list[str]:
        if isinstance(value, list):
            return value
        return [item.strip() for item in value.split(",") if item.strip()]

    @property
    def active_chat_model(self) -> str:
        if self.ai_chat_model:
            return self.ai_chat_model
        if self.ai_provider == "openrouter":
            return "openai/gpt-4.1-mini"
        return self.openai_chat_model

    @property
    def active_embedding_model(self) -> str:
        if self.ai_embedding_model:
            return self.ai_embedding_model
        if self.ai_provider == "openrouter":
            return "openai/text-embedding-3-small"
        return self.openai_embedding_model

    @property
    def source_archive_path(self) -> Path:
        base_dir = Path(__file__).resolve().parents[2]
        archive_path = Path(self.source_archive_dir)
        if archive_path.is_absolute():
            return archive_path
        return base_dir / archive_path


@lru_cache
def get_settings() -> Settings:
    return Settings()
