from __future__ import annotations

import re
import unicodedata
from dataclasses import asdict, dataclass
from statistics import mean
from urllib.parse import unquote

from app.models import AnswerTrace


@dataclass
class EvaluationCase:
    id: str
    question: str
    expected_source_contains: list[str]
    expected_answer_keywords: list[str]
    category: str
    notes: str = ""


@dataclass
class EvaluationResult:
    id: str
    question: str
    category: str
    top1_source_hit: bool
    source_hit: bool
    answer_keyword_hit: bool
    fallback_used: bool
    latency_ms: int
    confidence: float
    top_source_title: str | None
    top_source_url: str | None
    answer_preview: str

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def source_hit(traces: list[AnswerTrace], expected_fragments: list[str]) -> bool:
    if not expected_fragments:
        return True
    lowered_fragments = [_fold_match_text(fragment) for fragment in expected_fragments]
    for trace in traces:
        haystacks = [trace.source_title or "", trace.source_url or "", trace.snippet or ""]
        joined = _fold_match_text(" ".join(_safe_unquote(haystack) for haystack in haystacks))
        if any(fragment in joined for fragment in lowered_fragments):
            return True
    return False


def _safe_unquote(value: str) -> str:
    # URL-encoded titles/filenames escape spaces as %20 and so have no literal
    # whitespace. A value that already contains spaces is natural language where
    # "%" denotes a percentage (e.g. "%30 Ingilizce") and must not be decoded.
    if not value or "%" not in value or " " in value:
        return value
    return unquote(value)


def _fold_match_text(value: str) -> str:
    decoded = (
        value
        .replace("ç", "c")
        .replace("Ç", "c")
        .replace("ğ", "g")
        .replace("Ğ", "g")
        .replace("ı", "i")
        .replace("I", "i")
        .replace("İ", "i")
        .replace("ö", "o")
        .replace("Ö", "o")
        .replace("ş", "s")
        .replace("Ş", "s")
        .replace("ü", "u")
        .replace("Ü", "u")
    )
    normalized = unicodedata.normalize("NFKD", decoded.lower())
    without_accents = "".join(character for character in normalized if not unicodedata.combining(character))
    return re.sub(r"\s+", " ", without_accents).strip()


def answer_keyword_hit(answer_text: str, expected_keywords: list[str]) -> bool:
    if not expected_keywords:
        return True
    folded_answer = _fold_match_text(answer_text)
    return any(_fold_match_text(keyword) in folded_answer for keyword in expected_keywords)


def summarize_results(results: list[EvaluationResult]) -> dict[str, float | int]:
    if not results:
        return {
            "question_count": 0,
            "top1_source_hit_rate": 0.0,
            "source_hit_rate": 0.0,
            "answer_keyword_hit_rate": 0.0,
            "fallback_rate": 0.0,
            "avg_latency_ms": 0.0,
            "p50_latency_ms": 0.0,
            "p95_latency_ms": 0.0,
            "max_latency_ms": 0.0,
            "avg_confidence": 0.0,
        }

    latencies = sorted(result.latency_ms for result in results)
    p50_index = (len(latencies) - 1) // 2
    p95_index = max(int(len(latencies) * 0.95) - 1, 0)

    return {
        "question_count": len(results),
        "top1_source_hit_rate": round(sum(result.top1_source_hit for result in results) / len(results), 4),
        "source_hit_rate": round(sum(result.source_hit for result in results) / len(results), 4),
        "answer_keyword_hit_rate": round(sum(result.answer_keyword_hit for result in results) / len(results), 4),
        "fallback_rate": round(sum(result.fallback_used for result in results) / len(results), 4),
        "avg_latency_ms": round(mean(latencies), 2),
        "p50_latency_ms": latencies[p50_index],
        "p95_latency_ms": latencies[p95_index],
        "max_latency_ms": max(latencies),
        "avg_confidence": round(mean(result.confidence for result in results), 4),
    }
