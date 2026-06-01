from __future__ import annotations

import math
import re
import time
import unicodedata
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urldefrag

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, joinedload

from app.core.config import get_settings
from app.models import Answer, AnswerTrace, Chunk, Document, Question, QuestionStatus, SourceType, StreamSession, StreamStatus
from app.schemas import LiveStateRead, MetricsRead, QuestionRead
from app.services.chunker import normalize_text, tokenize
from app.services.embeddings import EmbeddingService
from app.services.llm import LLMService
from app.services.tts import TTSService


@dataclass
class RetrievedChunk:
    chunk: Chunk
    vector_score: float
    keyword_score: float
    final_score: float


@dataclass
class CandidateChunk:
    chunk: Chunk
    string_hint: float = 0.0


class RagService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.settings = get_settings()
        self.embedding_service = EmbeddingService()
        self.llm_service = LLMService()
        self.tts_service = TTSService(db=self.db)

    def ask_manual_question(self, content: str, author_name: str | None = None) -> Question:
        question = self.enqueue_manual_question(content, author_name)
        return self.process_question(question.id)

    def enqueue_manual_question(self, content: str, author_name: str | None = None) -> Question:
        question = Question(
            source_type=SourceType.MANUAL,
            author_name=author_name,
            content=content,
            normalized_content=normalize_text(content).lower(),
            status=QuestionStatus.PENDING,
        )
        self.db.add(question)
        self.db.commit()
        self.db.refresh(question)
        return question

    def upsert_youtube_question(
        self,
        content: str,
        author_name: str | None,
        source_message_id: str,
        stream_session_id: str,
    ) -> Question:
        existing = self.db.scalar(select(Question).where(Question.source_message_id == source_message_id))
        if existing:
            return existing
        question = Question(
            source_type=SourceType.YOUTUBE,
            source_message_id=source_message_id,
            author_name=author_name,
            content=content,
            normalized_content=normalize_text(content).lower(),
            status=QuestionStatus.PENDING,
            stream_session_id=stream_session_id,
        )
        self.db.add(question)
        self.db.commit()
        self.db.refresh(question)
        return question

    def process_question(self, question_id: str) -> Question:
        question = self.db.scalar(
            select(Question)
            .where(Question.id == question_id)
            .options(joinedload(Question.answer).joinedload(Answer.traces))
        )
        if not question:
            raise ValueError("Question not found")
        if question.answer:
            return question

        try:
            start = time.perf_counter()
            question.status = QuestionStatus.PROCESSING
            self.db.commit()

            retrieved = self.retrieve(question.content)
            candidate_contexts = [
                self._format_context(question.content, item) for item in retrieved[: self.settings.llm_context_limit]
            ]
            contexts = candidate_contexts if self._should_use_contexts(retrieved, candidate_contexts) else []
            confidence = retrieved[0].final_score if retrieved else 0.0
            answer_text, model_name, fallback_used = self.llm_service.answer(
                question.content,
                contexts,
            )

            latency_ms = int((time.perf_counter() - start) * 1000)
            answer = Answer(
                question_id=question.id,
                content=answer_text,
                model_name=model_name,
                latency_ms=latency_ms,
                confidence=confidence,
                fallback_used=fallback_used,
            )
            self.db.add(answer)
            self.db.flush()
            for item in retrieved[: self.settings.retrieval_top_k]:
                self.db.add(
                    AnswerTrace(
                        answer_id=answer.id,
                        chunk_id=item.chunk.id,
                        source_title=item.chunk.document.title,
                        source_url=item.chunk.document.source_url,
                        snippet=self._excerpt_for_question(question.content, item.chunk.content),
                        vector_score=item.vector_score,
                        keyword_score=item.keyword_score,
                        final_score=item.final_score,
                    )
                )
            self.tts_service.synthesize_answer(answer)
            answer.created_at = datetime.now(UTC)
            question.status = QuestionStatus.ANSWERED
            question.error_message = None
            self.db.commit()
        except Exception as exc:
            question.status = QuestionStatus.FAILED
            question.error_message = str(exc)
            self.db.commit()
            raise
        self.db.refresh(question)
        return self.db.scalar(
            select(Question)
            .where(Question.id == question.id)
            .options(joinedload(Question.answer).joinedload(Answer.traces))
        )

    def process_pending_questions(self, max_items: int = 1) -> int:
        statement = (
            select(Question)
            .where(Question.status == QuestionStatus.PENDING)
            .order_by(Question.created_at.asc())
            .limit(max_items)
        )
        questions = self.db.scalars(statement).all()
        processed = 0
        for question in questions:
            try:
                self.process_question(question.id)
            except Exception:
                pass
            processed += 1
        return processed

    def retrieve(self, query: str) -> list[RetrievedChunk]:
        normalized = normalize_text(query).lower()
        if not normalized:
            return []
        query_embedding = self.embedding_service.embed(normalized)
        query_tokens = self._normalized_tokens(normalized)
        if not query_tokens:
            return []
        query_hints = self._query_hint_tokens(query_tokens)
        filter_tokens = list(dict.fromkeys([*query_tokens, *query_hints]))
        candidates = self._candidate_chunks(normalized, query_embedding, filter_tokens)
        scored: list[RetrievedChunk] = []
        for candidate in candidates:
            chunk = candidate.chunk
            embedding = list(chunk.embedding) if chunk.embedding is not None else []
            vector_score = self._cosine_similarity(query_embedding, embedding)
            keyword_score = self._string_relevance(normalized, query_tokens, query_hints, chunk, candidate.string_hint)
            intent_bonus = self._intent_match_score(normalized, query_tokens, query_hints, chunk)
            page_penalty = self._page_kind_penalty(chunk) * self._document_quality_penalty(chunk)
            final_score = round(((max(vector_score, 0.0) * 0.35) + (keyword_score * 0.55) + intent_bonus) * page_penalty, 6)
            if final_score <= 0:
                continue
            scored.append(
                RetrievedChunk(
                    chunk=chunk,
                    vector_score=round(vector_score, 6),
                    keyword_score=round(keyword_score, 6),
                    final_score=final_score,
                )
            )
        scored.sort(key=lambda item: item.final_score, reverse=True)
        return self._diversified_results(scored, self.settings.retrieval_top_k, query_tokens)

    def list_questions(self, limit: int = 30) -> list[Question]:
        statement = (
            select(Question)
            .options(joinedload(Question.answer).joinedload(Answer.traces))
            .order_by(Question.created_at.desc())
            .limit(limit)
        )
        return self.db.scalars(statement).unique().all()

    def live_state(self, queue_limit: int = 6) -> LiveStateRead:
        queue_statement = (
            select(Question)
            .options(joinedload(Question.answer).joinedload(Answer.traces))
            .where(Question.status.in_([QuestionStatus.PENDING, QuestionStatus.PROCESSING]))
            .order_by(Question.created_at.asc())
            .limit(queue_limit)
        )
        queue = self.db.scalars(queue_statement).unique().all()
        processing = next((question for question in queue if question.status == QuestionStatus.PROCESSING), None)
        pending = next((question for question in queue if question.status == QuestionStatus.PENDING), None)
        queue_size = self.db.scalar(
            select(func.count(Question.id)).where(Question.status.in_([QuestionStatus.PENDING, QuestionStatus.PROCESSING]))
        ) or 0

        latest_answered = self.db.scalar(
            select(Question)
            .join(Answer)
            .options(joinedload(Question.answer).joinedload(Answer.traces))
            .where(Question.status == QuestionStatus.ANSWERED)
            .order_by(Answer.created_at.desc())
            .limit(1)
        )
        latest_failed = self.db.scalar(
            select(Question)
            .where(Question.status == QuestionStatus.FAILED)
            .order_by(Question.updated_at.desc())
            .limit(1)
        )
        active_streams = self.db.scalar(
            select(func.count(StreamSession.id)).where(StreamSession.status == StreamStatus.CONNECTED)
        ) or 0

        now = datetime.now(UTC)
        recent_error = bool(
            latest_failed and latest_failed.updated_at and self._seconds_since(now, latest_failed.updated_at) < 12
        )
        answer_age_seconds = (
            self._seconds_since(now, latest_answered.answer.created_at)
            if latest_answered and latest_answered.answer
            else None
        )
        answer_speech_seconds = self._answer_speech_seconds(latest_answered.answer) if latest_answered and latest_answered.answer else 0
        recent_answer_speaking = answer_age_seconds is not None and answer_age_seconds < answer_speech_seconds
        recent_answer_handoff = (
            answer_age_seconds is not None
            and answer_age_seconds < self._speech_window_seconds(latest_answered.answer)
        )

        avatar_state = "idle"
        if recent_answer_speaking:
            avatar_state = "speaking"
        elif processing:
            avatar_state = "thinking"
        elif recent_error:
            avatar_state = "error"
        elif pending:
            avatar_state = "listening"

        current_question = latest_answered if recent_answer_handoff else processing or pending or latest_answered
        return LiveStateRead(
            avatar_state=avatar_state,
            current_question=QuestionRead.model_validate(current_question) if current_question else None,
            latest_answered=QuestionRead.model_validate(latest_answered) if latest_answered else None,
            queue=[QuestionRead.model_validate(question) for question in queue],
            queue_size=int(queue_size),
            active_streams=int(active_streams),
            generated_at=now,
        )

    def _speech_window_seconds(self, answer: Answer) -> float:
        handoff_pause_seconds = 2.0
        return min(self._answer_speech_seconds(answer) + handoff_pause_seconds, 55.0)

    def _answer_speech_seconds(self, answer: Answer) -> float:
        if answer.audio_duration_ms:
            return min(max(answer.audio_duration_ms / 1000, 4.0), 50.0)
        return min(max(len(answer.content) * 0.06, 5.0), 30.0)

    def _seconds_since(self, now: datetime, value: datetime) -> float:
        if value.tzinfo is None:
            value = value.replace(tzinfo=UTC)
        return (now - value).total_seconds()

    def list_streams(self) -> list[StreamSession]:
        return self.db.scalars(select(StreamSession).order_by(StreamSession.created_at.desc())).all()

    def metrics(self) -> MetricsRead:
        documents = self.db.scalar(select(func.count(Document.id))) or 0
        chunks = self.db.scalar(select(func.count(Chunk.id))) or 0
        questions_total = self.db.scalar(select(func.count(Question.id))) or 0
        questions_answered = self.db.scalar(
            select(func.count(Question.id)).where(Question.status == QuestionStatus.ANSWERED)
        ) or 0
        active_streams = self.db.scalar(
            select(func.count(StreamSession.id)).where(StreamSession.status == StreamStatus.CONNECTED)
        ) or 0
        avg_latency = self.db.scalar(select(func.avg(Answer.latency_ms))) or 0.0
        return MetricsRead(
            documents=documents,
            chunks=chunks,
            questions_total=questions_total,
            questions_answered=questions_answered,
            active_streams=active_streams,
            avg_latency_ms=float(avg_latency),
        )

    def serialize_question(self, question: Question) -> QuestionRead:
        return QuestionRead.model_validate(question)

    def _candidate_chunks(
        self,
        query: str,
        query_embedding: list[float],
        query_tokens: list[str],
    ) -> list[CandidateChunk]:
        statement = select(Chunk).options(joinedload(Chunk.document))
        candidates: dict[str, CandidateChunk] = {}
        if self.db.bind and self.db.bind.dialect.name == "postgresql":
            vector_candidates = self.db.scalars(
                statement.order_by(Chunk.embedding.cosine_distance(query_embedding)).limit(self.settings.retrieval_candidate_count)
            ).all()
        else:
            vector_candidates = self.db.scalars(statement).all()
        for chunk in vector_candidates:
            candidates[chunk.id] = CandidateChunk(chunk=chunk)

        for candidate in self._string_candidates(query, query_tokens):
            existing = candidates.get(candidate.chunk.id)
            if existing:
                existing.string_hint = max(existing.string_hint, candidate.string_hint)
                continue
            candidates[candidate.chunk.id] = candidate
        return list(candidates.values())

    def _string_candidates(self, query: str, query_tokens: list[str]) -> list[CandidateChunk]:
        if not query_tokens:
            return []
        if self.db.bind and self.db.bind.dialect.name == "postgresql":
            return self._postgres_string_candidates(query, query_tokens)
        return self._fallback_string_candidates(query_tokens)

    def _postgres_string_candidates(self, query: str, query_tokens: list[str]) -> list[CandidateChunk]:
        compact_query = " ".join(query_tokens[:8])
        content_vector = func.to_tsvector("simple", func.immutable_unaccent(func.coalesce(Chunk.content, "")))
        title_vector = func.to_tsvector("simple", func.immutable_unaccent(func.coalesce(Document.title, "")))
        ts_query = func.plainto_tsquery("simple", func.immutable_unaccent(compact_query))
        title_similarity = func.similarity(
            func.lower(func.immutable_unaccent(func.coalesce(Document.title, ""))),
            func.lower(func.immutable_unaccent(compact_query)),
        )
        url_similarity = func.similarity(
            func.lower(func.immutable_unaccent(func.coalesce(Document.source_url, ""))),
            func.lower(func.immutable_unaccent(compact_query)),
        )
        lexical_rank = (
            func.ts_rank_cd(content_vector, ts_query)
            + (func.ts_rank_cd(title_vector, ts_query) * 1.45)
            + (title_similarity * 0.9)
            + (url_similarity * 0.55)
        ).label("lexical_rank")

        filters = [
            content_vector.op("@@")(ts_query),
            title_vector.op("@@")(ts_query),
            title_similarity > 0.08,
            url_similarity > 0.05,
        ]
        for token in query_tokens[:4]:
            like = f"%{token}%"
            filters.extend(
                [
                    Chunk.content.ilike(like),
                    Document.title.ilike(like),
                    Document.source_url.ilike(like),
                ]
            )

        rows = self.db.execute(
            select(Chunk, lexical_rank)
            .join(Chunk.document)
            .options(joinedload(Chunk.document))
            .where(or_(*filters))
            .order_by(lexical_rank.desc())
            .limit(self.settings.retrieval_candidate_count)
        ).all()
        return [
            CandidateChunk(chunk=chunk, string_hint=self._normalize_score(float(rank or 0.0)))
            for chunk, rank in rows
        ]

    def _fallback_string_candidates(self, query_tokens: list[str]) -> list[CandidateChunk]:
        filters = []
        for token in query_tokens[:6]:
            like = f"%{token}%"
            filters.extend(
                [
                    Chunk.content.ilike(like),
                    Document.title.ilike(like),
                    Document.source_url.ilike(like),
                ]
            )
        if not filters:
            return []
        chunks = self.db.scalars(
            select(Chunk)
            .join(Chunk.document)
            .options(joinedload(Chunk.document))
            .where(or_(*filters))
            .limit(self.settings.retrieval_candidate_count * 2)
        ).unique().all()
        scored = [
            CandidateChunk(
                chunk=chunk,
                string_hint=self._string_relevance(
                    " ".join(query_tokens),
                    query_tokens,
                    self._query_hint_tokens(query_tokens),
                    chunk,
                    0.0,
                ),
            )
            for chunk in chunks
        ]
        scored.sort(key=lambda item: item.string_hint, reverse=True)
        return scored[: self.settings.retrieval_candidate_count]

    def _keyword_overlap(self, query: str, content: str) -> float:
        query_tokens = set(tokenize(query))
        content_tokens = set(tokenize(content))
        if not query_tokens or not content_tokens:
            return 0.0
        overlap = len(query_tokens & content_tokens)
        return overlap / len(query_tokens)

    def _string_relevance(
        self,
        query: str,
        query_tokens: list[str],
        query_hints: list[str],
        chunk: Chunk,
        string_hint: float,
    ) -> float:
        if not query_tokens:
            return self._normalize_score(string_hint)

        content = self._fold_text(chunk.content)
        title = self._fold_text(chunk.document.title)
        source_url = self._fold_text(chunk.document.source_url or "")
        query_phrase = " ".join(query_tokens)

        content_overlap = self._token_overlap(query_tokens, self._normalized_tokens(content))
        title_overlap = self._token_overlap(query_tokens, self._normalized_tokens(title))
        url_overlap = self._token_overlap(
            query_tokens,
            self._normalized_tokens(source_url.replace("/", " ").replace("-", " ")),
        )
        phrase_match = 0.0
        if query_phrase and query_phrase in title:
            phrase_match = 1.0
        elif query_phrase and query_phrase in source_url:
            phrase_match = 0.92
        elif query_phrase and query_phrase in content:
            phrase_match = 0.7

        ordered_pair_match = self._ordered_pair_coverage(query_tokens, f"{title} {source_url} {content[:3000]}")
        document_type_boost = 0.0
        if chunk.document.source_type == SourceType.PDF and any(
            token in query for token in ("yonetmelik", "yönerge", "yonerge", "kilavuz", "kılavuz")
        ):
            document_type_boost = 0.12

        hint_bonus = self._hint_match_score(query_hints, title, source_url, content)
        topic_bonus = self._topic_match_score(query_tokens, query_hints, title, source_url, content)

        normalized_hint = self._normalize_score(string_hint)
        score = (
            (content_overlap * 0.34)
            + (title_overlap * 0.3)
            + (url_overlap * 0.12)
            + (phrase_match * 0.12)
            + (ordered_pair_match * 0.12)
            + document_type_boost
            + hint_bonus
            + topic_bonus
        )
        if normalized_hint:
            score = max(score, normalized_hint * 0.85) + (normalized_hint * 0.15)
        return round(min(score, 1.0), 6)

    def _intent_match_score(
        self,
        query: str,
        query_tokens: list[str],
        query_hints: list[str],
        chunk: Chunk,
    ) -> float:
        content = self._fold_text(chunk.content[:3500])
        title = self._fold_text(chunk.document.title)
        source_url = self._fold_text(chunk.document.source_url or "")
        haystack = f"{title} {source_url} {content}"
        haystack_tokens = set(self._normalized_tokens(haystack))
        query_token_set = set(query_tokens)
        score = 0.0

        language_intent = bool(
            query_token_set & {"ingilizce", "turkce", "yuzde", "dili"} or "egitim dili" in query
        )
        department_intent = bool(query_token_set & {"bolum", "program", "muhendisligi", "mimarlik", "isletme"})
        if language_intent and department_intent:
            if "egitim dili" in haystack and haystack_tokens & {"ingilizce", "turkce"}:
                score += 0.24
            elif haystack_tokens & {"ingilizce", "turkce"} and query_token_set & haystack_tokens:
                score += 0.12
            if self._ordered_pair_coverage(query_tokens, haystack) >= 0.34:
                score += 0.08

        if "takvim" in query_token_set and "akademik takvim" in haystack:
            score += 0.08
        if query_token_set & {"yonetmelik", "yonerge", "mevzuat"}:
            if "lisans" in query_token_set and (
                "on lisans ve lisans" in haystack
                or "lisans egitim ogretim yonetmeligi" in haystack
                or "lisans yonetmelik" in haystack
            ):
                score += 0.22
            elif any(token in haystack for token in ("yonetmelik", "yonerge", "mevzuat")):
                score += 0.08
        if "hazirlik" in query_token_set and haystack_tokens & {"hazirlik", "oliys", "yeterlik", "muafiyet"}:
            score += 0.08
        if query_hints and len(set(query_hints) & haystack_tokens) >= 2:
            score += 0.04
        return min(score, 0.34)

    def _diversified_results(
        self,
        scored: list[RetrievedChunk],
        limit: int,
        query_tokens: list[str],
    ) -> list[RetrievedChunk]:
        if len(scored) <= limit:
            return scored

        selected: list[RetrievedChunk] = []
        selected_ids: set[str] = set()
        per_source: dict[str, int] = {}

        for topic in self._required_result_topics(query_tokens):
            match = next((item for item in scored if self._result_matches_topic(item, topic)), None)
            if not match or match.chunk.id in selected_ids:
                continue
            selected.append(match)
            selected_ids.add(match.chunk.id)
            source_key = self._source_key(match.chunk)
            per_source[source_key] = per_source.get(source_key, 0) + 1
            if len(selected) == limit:
                return selected

        for item in scored:
            if item.chunk.id in selected_ids:
                continue
            source_key = self._source_key(item.chunk)
            source_count = per_source.get(source_key, 0)
            if source_count >= 2:
                continue
            selected.append(item)
            selected_ids.add(item.chunk.id)
            per_source[source_key] = source_count + 1
            if len(selected) == limit:
                return selected

        for item in scored:
            if item.chunk.id in selected_ids:
                continue
            selected.append(item)
            if len(selected) == limit:
                break
        return selected

    def _source_key(self, chunk: Chunk) -> str:
        source_url = chunk.document.source_url or chunk.document.id
        return urldefrag(source_url)[0]

    def _required_result_topics(self, query_tokens: list[str]) -> list[str]:
        query_token_set = set(query_tokens)
        topics: list[str] = []
        if "takvim" in query_token_set:
            topics.append("takvim")
        if query_token_set & {"yonetmelik", "yonerge", "mevzuat"}:
            topics.append("mevzuat")
        return topics if len(topics) > 1 else []

    def _result_matches_topic(self, item: RetrievedChunk, topic: str) -> bool:
        chunk = item.chunk
        title_url = self._fold_text(f"{chunk.document.title} {chunk.document.source_url or ''}")
        haystack = self._fold_text(f"{title_url} {chunk.content[:1200]}")
        if topic == "takvim":
            return "takvim" in title_url
        if topic == "mevzuat":
            return any(token in haystack for token in ("yonetmelik", "yonerge", "mevzuat"))
        return False

    def _token_overlap(self, query_tokens: list[str], candidate_tokens: list[str]) -> float:
        query_token_set = set(query_tokens)
        candidate_token_set = set(candidate_tokens)
        if not query_token_set or not candidate_token_set:
            return 0.0
        return len(query_token_set & candidate_token_set) / len(query_token_set)

    def _normalized_tokens(self, value: str) -> list[str]:
        return [self._canonical_token(token) for token in tokenize(self._fold_text(value))]

    def _canonical_token(self, token: str) -> str:
        if token.startswith("yonetmel"):
            return "yonetmelik"
        if token.startswith("yonerg"):
            return "yonerge"
        if token.startswith("muhendislig"):
            return "muhendisligi"
        if token.startswith("ingilizc"):
            return "ingilizce"
        if token.startswith("turkc"):
            return "turkce"
        if token.startswith("lisansustu"):
            return "lisansustu"
        return token

    def _ordered_pair_coverage(self, query_tokens: list[str], haystack: str) -> float:
        if len(query_tokens) < 2:
            return 0.0
        pairs = [f"{query_tokens[index]} {query_tokens[index + 1]}" for index in range(len(query_tokens) - 1)]
        hits = sum(pair in haystack for pair in pairs)
        return hits / len(pairs)

    def _normalize_score(self, value: float) -> float:
        if value <= 0:
            return 0.0
        return value / (1.0 + value)

    def _page_kind_penalty(self, chunk: Chunk) -> float:
        page_kind = str((chunk.document.metadata_json or {}).get("page_kind", "")).lower()
        if page_kind == "listing":
            return 0.82
        if page_kind == "homepage":
            return 0.92
        return 1.0

    def _document_quality_penalty(self, chunk: Chunk) -> float:
        title = self._fold_text(chunk.document.title)
        content = self._fold_text(chunk.content[:1600])
        penalty = 1.0
        if "lorem ipsum" in content:
            penalty *= 0.12
        if "kurumsal kimlik rehberi" in title or "yokak kurumsal kimlik" in title:
            penalty *= 0.18
        if "abc cdef" in content or "abcdefghijklmn" in content:
            penalty *= 0.3
        if title in {"gebze teknik universitesi", "gebze technical university"} and "egitim dili" not in content:
            announcement_markers = (
                "duyuru",
                "sinav program",
                "ders program",
                "guncelle",
                "basvuru tarih",
                "staj sonucu",
                "tek ders",
            )
            marker_hits = sum(marker in content for marker in announcement_markers)
            if marker_hits >= 3:
                penalty *= 0.35
        return penalty

    def _query_hint_tokens(self, query_tokens: list[str]) -> list[str]:
        query_token_set = set(query_tokens)
        hints: list[str] = []

        def add(*values: str) -> None:
            for value in values:
                if value and value not in query_token_set and value not in hints:
                    hints.append(value)

        if "hazirlik" in query_token_set:
            add("ingilizce", "yabanci", "diller", "ydb", "sinifi", "programi")
        if "hazirlik" in query_token_set and any(
            token in query_token_set for token in ("sure", "suresi", "nekadar", "kadar", "surer", "suruyor")
        ):
            add("egitim", "yariyil", "guz", "bahar", "iki", "sene", "yil", "yillik", "akademik", "azami")
        if "muafiyet" in query_token_set or "yeterlik" in query_token_set:
            add("oliys", "sinav", "yeterlik")

        # AKTS / ECTS
        if query_token_set & {"akts", "ects"}:
            add("ects", "akts", "bilgi", "paketi", "kredi", "abl")
        # Program egitim dili
        if query_token_set & {"ingilizce", "turkce", "yuzde", "dili"}:
            add("egitim", "dili", "program", "lisans", "ingilizce", "turkce")
        # Akademik takvim
        if "takvim" in query_token_set:
            add("akademik", "yariyil", "donem", "tarih", "kayit", "sinav", "ders")
        # Staj
        if "staj" in query_token_set:
            add("zorunlu", "isyeri", "endustri", "uygulama", "pratik")
        # Burs
        if "burs" in query_token_set:
            add("destek", "maddi", "calisma", "imkan")
        # Mezuniyet / diploma
        if query_token_set & {"mezuniyet", "diploma", "mezun"}:
            add("mezuniyet", "diploma", "bitirme", "belge", "defter", "yonerge")
        # Yurt / barınma
        if query_token_set & {"yurt", "barinma", "konaklama"}:
            add("yurt", "barinma", "konaklama", "ogrenci", "kampus")
        # Kayıt
        if query_token_set & {"kayit", "basvuru", "kabul"}:
            add("kayit", "kabul", "basvuru", "otomasyon", "ogrenci")
        # Erasmus
        if "erasmus" in query_token_set:
            add("degisim", "yurtdisi", "hareketlilik", "personel", "ogrenci", "yonerge")
        # Araştırma / politika
        if query_token_set & {"arastirma", "politika", "research", "policy"}:
            add("arastirma", "politika", "research", "policy", "belge")
        # El kitabı
        if query_token_set & {"kitabi", "kitap", "kitapcik"}:
            add("ogrenci", "rehber", "kilavuz")
        # Lisansüstü
        if query_token_set & {"lisansustu", "yukseklisans", "doktora", "master"}:
            add("lisansustu", "yukseklisans", "doktora", "enstitu", "tez", "yonetmelik")
        # Tez
        if "tez" in query_token_set:
            add("yazim", "kilavuz", "enstitu", "lisansustu")
        # Yönetmelik / yönerge
        if query_token_set & {"yonetmelik", "yonerge", "mevzuat"}:
            add("yonetmelik", "yonerge", "lisans", "ogrenci", "isleri", "esaslar")
        # Bölüm
        if query_token_set & {"bolum", "muhendislik", "bilgisayar", "elektronik", "kimya"}:
            add("bolum", "muhendislik", "fakulte", "program", "ogretim")
        return hints

    def _hint_match_score(self, query_hints: list[str], title: str, source_url: str, content: str) -> float:
        if not query_hints:
            return 0.0
        haystack_tokens = set(self._normalized_tokens(f"{title} {source_url} {content[:2000]}"))
        if not haystack_tokens:
            return 0.0
        overlap = len(set(query_hints) & haystack_tokens) / len(set(query_hints))
        return min(overlap * 0.18, 0.18)

    def _topic_match_score(self, query_tokens: list[str], query_hints: list[str], title: str, source_url: str, content: str) -> float:
        query_token_set = set(query_tokens)
        haystack = f"{title} {source_url} {content[:2500]}"
        haystack_tokens = set(self._normalized_tokens(haystack))
        if not query_token_set or not haystack_tokens:
            return 0.0

        score = 0.0
        if query_token_set & {"ingilizce", "turkce", "yuzde", "dili"}:
            if "egitim dili" in haystack and haystack_tokens & {"ingilizce", "turkce"}:
                score += 0.22
            if query_token_set & {"bilgisayar", "elektronik", "kimya", "makine", "endustri"} and query_token_set & haystack_tokens:
                score += 0.06

        if "hazirlik" in query_token_set:
            prep_tokens = {"hazirlik", "ingilizce", "yabanci", "diller", "ydb", "hazirliksinifi"}
            if haystack_tokens & prep_tokens:
                score += 0.12
            duration_tokens = {"sene", "yil", "yillik", "yariyil", "azami", "iki", "bir", "egitim", "suresince"}
            duration_intent = {"sure", "suresi", "surer", "suruyor"}
            if (query_token_set & duration_intent or {"yil", "yillik", "sene"} & set(query_hints)) and haystack_tokens & duration_tokens:
                score += 0.12
            if {"yonerge", "yonetmelik", "el", "kitabi"} & haystack_tokens:
                score += 0.05

        if {"muafiyet", "yeterlik"} & query_token_set and haystack_tokens & {"oliys", "sinav", "yeterlik", "muafiyet"}:
            score += 0.12

        return min(score, 0.38)

    def _should_use_contexts(self, retrieved: list[RetrievedChunk], contexts: list[str]) -> bool:
        if not contexts or not retrieved:
            return False
        top = retrieved[0]
        if top.final_score >= self.settings.low_confidence_threshold:
            return True
        if top.keyword_score >= 0.18:
            return True
        if top.chunk.document.source_type == SourceType.PDF and top.keyword_score >= 0.14 and top.final_score >= 0.16:
            return True
        return False

    def _fold_text(self, value: str) -> str:
        normalized = unicodedata.normalize("NFKD", normalize_text(value).lower())
        return "".join(character for character in normalized if not unicodedata.combining(character))

    def _cosine_similarity(self, left: list[float], right: list[float]) -> float:
        if not left or not right:
            return 0.0
        numerator = sum(a * b for a, b in zip(left, right, strict=False))
        left_norm = math.sqrt(sum(value * value for value in left))
        right_norm = math.sqrt(sum(value * value for value in right))
        if left_norm == 0 or right_norm == 0:
            return 0.0
        return numerator / (left_norm * right_norm)

    def _format_context(self, query: str, item: RetrievedChunk) -> str:
        source = item.chunk.document.title
        excerpt = self._excerpt_for_question(query, item.chunk.content)
        return f"Kaynak: {source}\nIcerik: {excerpt}"

    def _excerpt_for_question(self, query: str, content: str) -> str:
        collapsed = normalize_text(content)
        if not collapsed:
            return ""
        limit = self.settings.llm_context_chars
        query_tokens = self._normalized_tokens(query)
        query_hints = self._query_hint_tokens(query_tokens)
        if not query_tokens:
            return collapsed[:limit]

        targeted_excerpt = self._targeted_excerpt(query_tokens, collapsed, limit)
        if targeted_excerpt:
            return targeted_excerpt

        segments = self._context_segments(collapsed, limit)
        if not segments:
            return collapsed[:limit]

        scored_segments: list[tuple[float, int, str]] = []
        for index, segment in enumerate(segments):
            score = self._context_segment_score(query_tokens, query_hints, segment)
            scored_segments.append((score, index, segment))

        scored_segments.sort(key=lambda item: (item[0], len(item[2])), reverse=True)
        best_score, best_index, best_segment = scored_segments[0]
        if best_score <= 0:
            return collapsed[:limit]

        selected_indices = {best_index}
        total_length = len(best_segment)
        neighbor_candidates = sorted(
            (
                (abs(index - best_index), -score, index, segment)
                for score, index, segment in scored_segments[1:]
                if abs(index - best_index) <= 2
            )
        )
        for _, neg_score, index, segment in neighbor_candidates:
            score = -neg_score
            if score < max(best_score * 0.4, 0.08):
                continue
            if total_length + len(segment) + 1 > limit:
                continue
            selected_indices.add(index)
            total_length += len(segment) + 1

        selected = [segments[index] for index in range(len(segments)) if index in selected_indices]
        excerpt = " ".join(selected).strip()
        if not excerpt:
            excerpt = best_segment.strip()
        if len(excerpt) > limit:
            excerpt = excerpt[: limit - 3].rstrip(" ,;:") + "..."
        return excerpt

    def _targeted_excerpt(self, query_tokens: list[str], text: str, limit: int) -> str:
        query_token_set = set(query_tokens)
        language_intent = bool(query_token_set & {"ingilizce", "turkce", "yuzde", "dili"})
        if not language_intent:
            return ""

        department_patterns = self._department_patterns_for_query(query_token_set)
        if not department_patterns:
            return ""

        candidates: list[tuple[float, str]] = []
        for pattern in department_patterns:
            for match in re.finditer(pattern, text, flags=re.IGNORECASE):
                start = max(0, match.start() - min(260, limit // 3))
                end = min(len(text), match.end() + limit - (match.start() - start))
                excerpt = text[start:end].strip(" ,;:")
                folded_excerpt = self._fold_text(excerpt)
                score = 0.0
                if "egitim dili" in folded_excerpt:
                    score += 0.45
                if folded_excerpt and query_token_set & set(self._normalized_tokens(folded_excerpt)):
                    score += 0.15
                if folded_excerpt and {"ingilizce", "turkce"} & set(self._normalized_tokens(folded_excerpt)):
                    score += 0.25
                if re.search(r"\b(program|fakultesi|lisans)\b", folded_excerpt):
                    score += 0.08
                candidates.append((score, excerpt[:limit].rstrip(" ,;:")))

        if not candidates:
            return ""
        candidates.sort(key=lambda item: (item[0], len(item[1])), reverse=True)
        best_score, best_excerpt = candidates[0]
        return best_excerpt if best_score >= 0.4 else ""

    def _department_patterns_for_query(self, query_token_set: set[str]) -> list[str]:
        departments = {
            ("bilgisayar", "muhendisligi"): r"Bilgisayar\s+M[uü]hendisli[gğ]i",
            ("elektronik", "muhendisligi"): r"Elektronik\s+M[uü]hendisli[gğ]i",
            ("cevre", "muhendisligi"): r"[CÇ]evre\s+M[uü]hendisli[gğ]i",
            ("endustri", "muhendisligi"): r"End[uü]stri\s+M[uü]hendisli[gğ]i",
            ("insaat", "muhendisligi"): r"[Iİ]n[sş]aat\s+M[uü]hendisli[gğ]i",
            ("harita", "muhendisligi"): r"Harita\s+M[uü]hendisli[gğ]i",
            ("kimya", "muhendisligi"): r"Kimya\s+M[uü]hendisli[gğ]i",
            ("makine", "muhendisligi"): r"Makine\s+M[uü]hendisli[gğ]i",
            ("ucak", "muhendisligi"): r"U[cç]ak\s+M[uü]hendisli[gğ]i",
            ("mimarlik",): r"Mimarl[iı]k",
            ("isletme",): r"[Iİ][sş]letme",
            ("iktisat",): r"[Iİ]ktisat",
        }
        return [
            pattern
            for required_tokens, pattern in departments.items()
            if set(required_tokens).issubset(query_token_set)
        ]

    def _context_segments(self, text: str, limit: int) -> list[str]:
        collapsed = normalize_text(text)
        if not collapsed:
            return []
        raw_segments = re.split(r"(?<=[.!?])\s+|\s+(?=Madde\s+\d+)", collapsed)
        segments: list[str] = []
        for raw_segment in raw_segments:
            segment = raw_segment.strip()
            if not segment:
                continue
            if len(segment) <= limit:
                segments.append(segment)
                continue
            words = segment.split()
            window_size = max(40, min(90, limit // 8))
            step = max(window_size // 2, 20)
            for start in range(0, len(words), step):
                window = " ".join(words[start : start + window_size]).strip()
                if not window:
                    continue
                segments.append(window)
                if start + window_size >= len(words):
                    break
        return segments

    def _context_segment_score(self, query_tokens: list[str], query_hints: list[str], segment: str) -> float:
        segment_tokens = self._normalized_tokens(segment)
        if not segment_tokens:
            return 0.0
        folded_segment = self._fold_text(segment)
        segment_token_set = set(segment_tokens)
        score = (
            (self._token_overlap(query_tokens, segment_tokens) * 0.58)
            + (self._token_overlap(query_hints, segment_tokens) * 0.18 if query_hints else 0.0)
            + (self._ordered_pair_coverage(query_tokens, folded_segment) * 0.14)
        )

        query_token_set = set(query_tokens)
        if query_token_set & {"ingilizce", "turkce", "yuzde", "dili"}:
            if "egitim dili" in folded_segment and segment_token_set & {"ingilizce", "turkce"}:
                score += 0.2
            if query_token_set & segment_token_set:
                score += 0.04

        if query_token_set & {"sure", "suresi", "azami", "kac", "kaç"}:
            has_number = bool(re.search(r"\b(\d+|bir|iki|uc|dort|bes|alti|yedi|sekiz|dokuz|on)\b", folded_segment))
            has_time_unit = bool(segment_token_set & {"yil", "yillik", "yariyil", "donem", "hafta", "ay", "gun", "sene"})
            has_duration_verb = bool(segment_token_set & {"sureli", "surer", "surmektedir", "surerken", "azami"})
            if "devam etmek zorundadir" in folded_segment or "devam etmek zorundadirlar" in folded_segment:
                has_duration_verb = True
            if has_number:
                score += 0.08
            if has_time_unit:
                score += 0.1
            if has_number and has_time_unit:
                score += 0.12
            if has_duration_verb:
                score += 0.1

        quality_factor = self._segment_quality_factor(segment, folded_segment)
        return score * quality_factor

    def _segment_quality_factor(self, segment: str, folded_segment: str) -> float:
        penalty = 1.0
        if any(marker in folded_segment for marker in ("dokuman no", "yayin tarihi", "revizyon no", "form no", "sayfa")):
            penalty *= 0.45
        letters = [character for character in segment if character.isalpha()]
        if letters:
            uppercase_ratio = sum(character.isupper() for character in letters) / len(letters)
            if uppercase_ratio > 0.45:
                penalty *= 0.55
            elif uppercase_ratio > 0.3:
                penalty *= 0.78
        if len(segment.split()) <= 4:
            penalty *= 0.65
        return penalty
