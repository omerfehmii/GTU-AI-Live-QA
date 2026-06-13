from __future__ import annotations

import hashlib
from collections.abc import Sequence
from pathlib import Path

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.models import Answer, BroadcastSegment, SpeechJob, SpeechJobKind, SpeechJobStatus
from app.services.tts import TTSService


class SpeechService:
    def __init__(
        self,
        db: Session,
        settings: Settings | None = None,
        tts_service: TTSService | None = None,
    ) -> None:
        self.db = db
        self.settings = settings or get_settings()
        self.tts_service = tts_service or TTSService(settings=self.settings, db=self.db)

    def tts_available(self) -> bool:
        return self.tts_service.tts_enabled() and self.tts_service.client is not None

    def enqueue_answer(self, answer: Answer) -> SpeechJob | None:
        speech_text = self._answer_speech_text(answer)
        if not self.tts_available() or not speech_text:
            return None

        text_hash = self._text_hash(speech_text)
        cache_key = self._cache_key(speech_text)
        existing = self.db.scalar(select(SpeechJob).where(SpeechJob.answer_id == answer.id))
        if existing:
            if (
                existing.text_hash != text_hash
                or existing.cache_key != cache_key
                or (existing.status == SpeechJobStatus.FAILED and not existing.audio_url)
            ):
                existing.text = speech_text
                existing.text_hash = text_hash
                existing.cache_key = cache_key
                existing.attempts = 0
                existing.audio_url = None
                existing.audio_duration_ms = None
                existing.audio_model_name = None
                existing.error_message = None
                answer.audio_url = None
                answer.audio_duration_ms = None
                answer.audio_model_name = None
                answer.audio_error_message = None
                output_path = self._cache_path(cache_key)
                if output_path.exists():
                    self._mark_ready_from_file(existing, output_path)
                else:
                    existing.status = SpeechJobStatus.PENDING
            self._sync_answer_audio(answer, existing)
            return existing

        return self._enqueue(
            kind=SpeechJobKind.ANSWER,
            text=speech_text,
            answer=answer,
        )

    def ensure_segment_job(self, segment: BroadcastSegment) -> SpeechJob | None:
        if not self.tts_available() or not segment.content.strip():
            return None

        job = self.find_segment_job(
            segment,
            statuses=[
                SpeechJobStatus.PENDING,
                SpeechJobStatus.GENERATING,
                SpeechJobStatus.READY,
            ],
        )
        if job:
            return job

        return self._enqueue(
            kind=SpeechJobKind.AMBIENT,
            text=segment.content,
            segment=segment,
        )

    def find_segment_job(
        self,
        segment: BroadcastSegment,
        statuses: Sequence[SpeechJobStatus] | None = None,
    ) -> SpeechJob | None:
        text_hash = self._text_hash(segment.content)
        cache_key = self._cache_key(segment.content)
        statement = (
            select(SpeechJob)
            .where(
                SpeechJob.segment_id == segment.id,
                SpeechJob.text_hash == text_hash,
                SpeechJob.cache_key == cache_key,
            )
            .order_by(SpeechJob.created_at.desc())
            .limit(1)
        )
        if statuses is not None:
            statement = statement.where(SpeechJob.status.in_(list(statuses)))
        return self.db.scalar(statement)

    def segment_audio_ready(self, segment: BroadcastSegment) -> bool:
        job = self.find_segment_job(segment, statuses=[SpeechJobStatus.READY])
        return bool(job and job.audio_url)

    def process_pending_jobs(self, max_items: int = 1) -> int:
        if not self.tts_available():
            return 0

        jobs = self.db.scalars(
            select(SpeechJob)
            .where(SpeechJob.status == SpeechJobStatus.PENDING)
            .order_by(
                case((SpeechJob.kind == SpeechJobKind.ANSWER, 0), else_=1),
                SpeechJob.created_at.asc(),
            )
            .limit(max_items)
        ).all()
        processed = 0
        for job in jobs:
            self._process_job(job)
            processed += 1
        return processed

    def pending_count(self) -> int:
        return int(
            self.db.scalar(
                select(func.count(SpeechJob.id)).where(
                    SpeechJob.status.in_([SpeechJobStatus.PENDING, SpeechJobStatus.GENERATING])
                )
            )
            or 0
        )

    def estimate_duration_ms(self, text: str) -> int:
        return self.tts_service.estimate_duration_ms(text)

    def _answer_speech_text(self, answer: Answer) -> str:
        return (answer.speech_content or answer.content).strip()

    def _enqueue(
        self,
        kind: SpeechJobKind,
        text: str,
        answer: Answer | None = None,
        segment: BroadcastSegment | None = None,
    ) -> SpeechJob:
        cache_key = self._cache_key(text)
        output_path = self._cache_path(cache_key)
        job = SpeechJob(
            kind=kind,
            status=SpeechJobStatus.PENDING,
            text=text,
            text_hash=self._text_hash(text),
            cache_key=cache_key,
            answer_id=answer.id if answer else None,
            segment_id=segment.id if segment else None,
        )
        if output_path.exists():
            self._mark_ready_from_file(job, output_path)

        self.db.add(job)
        self.db.flush()
        if answer:
            self._sync_answer_audio(answer, job)
        return job

    def _process_job(self, job: SpeechJob) -> None:
        output_path = self._cache_path(job.cache_key)
        try:
            job.status = SpeechJobStatus.GENERATING
            job.attempts = (job.attempts or 0) + 1
            job.error_message = None
            self.db.commit()

            if output_path.exists():
                self._mark_ready_from_file(job, output_path)
            else:
                duration_ms = self.tts_service.synthesize_text_to_path(job.text, output_path)
                if not output_path.exists():
                    raise ValueError("TTS response did not produce an audio file.")
                job.audio_url = self._media_url(output_path)
                job.audio_duration_ms = duration_ms or self.tts_service.estimate_duration_ms(job.text)
                job.audio_model_name = self.settings.tts_model
                job.status = SpeechJobStatus.READY
                job.error_message = None

            if job.answer:
                self._sync_answer_audio(job.answer, job)
            self.db.commit()
        except Exception as exc:
            self.db.rollback()
            fresh_job = self.db.get(SpeechJob, job.id)
            if fresh_job:
                fresh_job.status = SpeechJobStatus.FAILED
                fresh_job.audio_model_name = self.settings.tts_model
                fresh_job.error_message = str(exc)[:1000]
                if fresh_job.answer:
                    fresh_job.answer.audio_model_name = self.settings.tts_model
                    fresh_job.answer.audio_error_message = fresh_job.error_message
                self.db.commit()

    def _mark_ready_from_file(self, job: SpeechJob, output_path: Path) -> None:
        job.status = SpeechJobStatus.READY
        job.audio_url = self._media_url(output_path)
        job.audio_duration_ms = self.tts_service.audio_duration_ms(output_path) or self.tts_service.estimate_duration_ms(
            job.text
        )
        job.audio_model_name = self.settings.tts_model
        job.error_message = None

    def _sync_answer_audio(self, answer: Answer, job: SpeechJob) -> None:
        if job.status != SpeechJobStatus.READY or not job.audio_url:
            return
        answer.audio_url = job.audio_url
        answer.audio_duration_ms = job.audio_duration_ms
        answer.audio_model_name = job.audio_model_name
        answer.audio_error_message = None

    def _cache_path(self, cache_key: str) -> Path:
        output_dir = self.settings.generated_audio_path / "cache"
        output_dir.mkdir(parents=True, exist_ok=True)
        return output_dir / f"{cache_key}.{self.settings.tts_response_format}"

    def _media_url(self, output_path: Path) -> str:
        return f"/media/cache/{output_path.name}"

    def _cache_key(self, text: str) -> str:
        payload = "|".join(
            [
                self.settings.tts_provider,
                self.settings.tts_model,
                self.settings.tts_voice,
                self.settings.tts_response_format,
                self._text_hash(text),
            ]
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def _text_hash(self, text: str) -> str:
        normalized = " ".join(text.strip().split())
        return hashlib.sha256(normalized.encode("utf-8")).hexdigest()
