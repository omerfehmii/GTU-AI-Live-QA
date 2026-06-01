from __future__ import annotations

from collections.abc import Generator

from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings
from app.models import Base

settings = get_settings()

connect_args = (
    {"check_same_thread": False, "timeout": 30}
    if settings.database_url.startswith("sqlite")
    else {}
)

engine = create_engine(settings.database_url, future=True, pool_pre_ping=True, connect_args=connect_args)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


if settings.database_url.startswith("sqlite"):
    @event.listens_for(engine, "connect")
    def _configure_sqlite(connection, _connection_record) -> None:  # type: ignore[no-untyped-def]
        cursor = connection.cursor()
        cursor.execute("PRAGMA busy_timeout = 30000")
        cursor.execute("PRAGMA journal_mode = WAL")
        cursor.execute("PRAGMA foreign_keys = ON")
        cursor.close()


def init_db() -> None:
    if engine.dialect.name == "postgresql":
        with engine.begin() as connection:
            connection.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
            connection.execute(text("CREATE EXTENSION IF NOT EXISTS unaccent"))
            connection.execute(text("CREATE EXTENSION IF NOT EXISTS pg_trgm"))
            connection.execute(
                text(
                    """
                    CREATE OR REPLACE FUNCTION immutable_unaccent(input text)
                    RETURNS text
                    LANGUAGE sql
                    IMMUTABLE
                    PARALLEL SAFE
                    AS $$
                        SELECT unaccent('public.unaccent', input)
                    $$;
                    """
                )
            )
    Base.metadata.create_all(bind=engine)
    _ensure_answer_audio_columns()
    if engine.dialect.name == "postgresql":
        with engine.begin() as connection:
            connection.execute(
                text(
                    """
                    CREATE INDEX IF NOT EXISTS ix_chunks_content_fts
                    ON chunks
                    USING GIN (to_tsvector('simple', immutable_unaccent(content)))
                    """
                )
            )
            connection.execute(
                text(
                    """
                    CREATE INDEX IF NOT EXISTS ix_documents_title_fts
                    ON documents
                    USING GIN (to_tsvector('simple', immutable_unaccent(title)))
                    """
                )
            )
            connection.execute(
                text(
                    """
                    CREATE INDEX IF NOT EXISTS ix_documents_title_trgm
                    ON documents
                    USING GIN (lower(immutable_unaccent(title)) gin_trgm_ops)
                    """
                )
            )
            connection.execute(
                text(
                    """
                    CREATE INDEX IF NOT EXISTS ix_documents_source_url_trgm
                    ON documents
                    USING GIN (lower(immutable_unaccent(coalesce(source_url, ''))) gin_trgm_ops)
                    """
                )
            )


def _ensure_answer_audio_columns() -> None:
    inspector = inspect(engine)
    if not inspector.has_table("answers"):
        return

    existing_columns = {column["name"] for column in inspector.get_columns("answers")}
    missing_columns = [
        ("audio_url", "TEXT"),
        ("audio_duration_ms", "INTEGER"),
        ("audio_model_name", "VARCHAR(255)"),
        ("audio_error_message", "TEXT"),
    ]
    with engine.begin() as connection:
        for column_name, column_type in missing_columns:
            if column_name not in existing_columns:
                connection.execute(text(f"ALTER TABLE answers ADD COLUMN {column_name} {column_type}"))


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
