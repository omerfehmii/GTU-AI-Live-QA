from __future__ import annotations

import secrets
from typing import Annotated

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db import get_db
from app.schemas import (
    AdminSettingsRead,
    AdminSettingsUpdate,
    ArchiveCrawlSummary,
    ArchiveIndexRequest,
    ArchiveStatsRead,
    DocumentRead,
    IndexRebuildRequest,
    IngestSummary,
    LiveStateRead,
    ManualQuestionRequest,
    MetricsRead,
    QuestionRead,
    StreamSessionRead,
    WebIngestRequest,
    YoutubeConnectRequest,
)
from app.services.ingest import IngestService
from app.services.rag import RagService
from app.services.runtime_settings import RuntimeSettingsService
from app.services.youtube import YouTubeService

router = APIRouter()
security = HTTPBasic()
settings = get_settings()


def require_admin(credentials: Annotated[HTTPBasicCredentials, Depends(security)]) -> str:
    correct_username = secrets.compare_digest(credentials.username, settings.admin_username)
    correct_password = secrets.compare_digest(credentials.password, settings.admin_password)
    if not correct_username or not correct_password:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Admin kimlik bilgileri gecersiz.",
            headers={"WWW-Authenticate": "Basic"},
        )
    return credentials.username


@router.get("/health")
def healthcheck() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/questions", response_model=list[QuestionRead])
def get_questions(limit: int = 30, db: Session = Depends(get_db)) -> list[QuestionRead]:
    service = RagService(db)
    return [service.serialize_question(question) for question in service.list_questions(limit=limit)]


@router.post("/questions/manual", response_model=QuestionRead)
def create_manual_question(payload: ManualQuestionRequest, db: Session = Depends(get_db)) -> QuestionRead:
    service = RagService(db)
    question = service.ask_manual_question(payload.content, payload.author_name)
    return service.serialize_question(question)


@router.post("/questions/manual/queue", response_model=QuestionRead)
def enqueue_manual_question(payload: ManualQuestionRequest, db: Session = Depends(get_db)) -> QuestionRead:
    service = RagService(db)
    question = service.enqueue_manual_question(payload.content, payload.author_name)
    return service.serialize_question(question)


@router.get("/metrics", response_model=MetricsRead)
def get_metrics(db: Session = Depends(get_db)) -> MetricsRead:
    service = RagService(db)
    return service.metrics()


@router.get("/live/state", response_model=LiveStateRead)
def get_live_state(db: Session = Depends(get_db)) -> LiveStateRead:
    service = RagService(db)
    return service.live_state()


@router.get("/streams", response_model=list[StreamSessionRead])
def list_streams(
    _: str = Depends(require_admin),
    db: Session = Depends(get_db),
) -> list[StreamSessionRead]:
    service = RagService(db)
    return [StreamSessionRead.model_validate(stream) for stream in service.list_streams()]


@router.get("/admin/settings", response_model=AdminSettingsRead)
def get_admin_settings(
    _: str = Depends(require_admin),
    db: Session = Depends(get_db),
) -> AdminSettingsRead:
    service = RuntimeSettingsService(db)
    return service.read()


@router.post("/admin/settings", response_model=AdminSettingsRead)
def update_admin_settings(
    payload: AdminSettingsUpdate,
    _: str = Depends(require_admin),
    db: Session = Depends(get_db),
) -> AdminSettingsRead:
    service = RuntimeSettingsService(db)
    return service.update(payload)


@router.post("/streams/youtube/connect", response_model=StreamSessionRead)
def connect_stream(
    payload: YoutubeConnectRequest,
    _: str = Depends(require_admin),
    db: Session = Depends(get_db),
) -> StreamSessionRead:
    service = YouTubeService(db)
    try:
        stream = service.connect_stream(payload.video_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return StreamSessionRead.model_validate(stream)


@router.post("/admin/ingest/web", response_model=IngestSummary)
def ingest_web(
    payload: WebIngestRequest,
    _: str = Depends(require_admin),
    db: Session = Depends(get_db),
) -> IngestSummary:
    service = IngestService(db)
    return service.ingest_web(payload)


@router.post("/admin/archive/crawl", response_model=ArchiveCrawlSummary)
def crawl_archive(
    payload: WebIngestRequest,
    _: str = Depends(require_admin),
    db: Session = Depends(get_db),
) -> ArchiveCrawlSummary:
    service = IngestService(db)
    return service.crawl_to_archive(payload)


@router.post("/admin/archive/index", response_model=IngestSummary)
def index_archive(
    payload: ArchiveIndexRequest,
    _: str = Depends(require_admin),
    db: Session = Depends(get_db),
) -> IngestSummary:
    service = IngestService(db)
    return service.index_archive(payload)


@router.post("/admin/ingest/pdf", response_model=IngestSummary)
async def ingest_pdf(
    _: str = Depends(require_admin),
    db: Session = Depends(get_db),
    files: list[UploadFile] = File(...),
) -> IngestSummary:
    payload: list[tuple[str, bytes]] = []
    for item in files:
        payload.append((item.filename or "document.pdf", await item.read()))
    service = IngestService(db)
    return service.ingest_pdf_uploads(payload)


@router.post("/admin/index/rebuild", response_model=IngestSummary)
def rebuild_index(
    payload: IndexRebuildRequest,
    _: str = Depends(require_admin),
    db: Session = Depends(get_db),
) -> IngestSummary:
    service = IngestService(db)
    return service.rebuild_index(payload.document_ids)


@router.get("/admin/documents", response_model=list[DocumentRead])
def list_documents(
    _: str = Depends(require_admin),
    db: Session = Depends(get_db),
) -> list[DocumentRead]:
    service = IngestService(db)
    return [DocumentRead.model_validate(document) for document in service.list_documents()]


@router.get("/admin/archive/stats", response_model=ArchiveStatsRead)
def get_archive_stats(
    _: str = Depends(require_admin),
    db: Session = Depends(get_db),
) -> ArchiveStatsRead:
    service = IngestService(db)
    return service.archive_stats()
