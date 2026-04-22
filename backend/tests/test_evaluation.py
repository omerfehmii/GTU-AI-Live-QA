from __future__ import annotations

from types import SimpleNamespace

from app.services.evaluation import answer_keyword_hit, source_hit, summarize_results, EvaluationResult


def test_source_hit_matches_title_or_url() -> None:
    traces = [
        SimpleNamespace(
            source_title="YN-0001 On Lisans ve Lisans Egitim Ogretim Yonetmeligi",
            source_url="https://www.gtu.edu.tr/fileman/yonetmelik.pdf",
            snippet="Guz ve bahar yariyillari",
        )
    ]

    assert source_hit(traces, ["YN-0001"])
    assert source_hit(traces, ["fileman"])
    assert not source_hit(traces, ["Erasmus"])


def test_answer_keyword_hit_is_case_insensitive() -> None:
    answer = "Guz ve bahar yariyillarinin her biri 14 haftadir."
    assert answer_keyword_hit(answer, ["14 HAFTA"])
    assert not answer_keyword_hit(answer, ["erasmus"])


def test_summarize_results_calculates_basic_rates() -> None:
    results = [
        EvaluationResult(
            id="1",
            question="q1",
            category="web",
            top1_source_hit=True,
            source_hit=True,
            answer_keyword_hit=False,
            fallback_used=False,
            latency_ms=1000,
            confidence=0.7,
            top_source_title="A",
            top_source_url="u1",
            answer_preview="x",
        ),
        EvaluationResult(
            id="2",
            question="q2",
            category="pdf",
            top1_source_hit=False,
            source_hit=False,
            answer_keyword_hit=True,
            fallback_used=True,
            latency_ms=3000,
            confidence=0.3,
            top_source_title="B",
            top_source_url="u2",
            answer_preview="y",
        ),
    ]

    summary = summarize_results(results)

    assert summary["question_count"] == 2
    assert summary["top1_source_hit_rate"] == 0.5
    assert summary["source_hit_rate"] == 0.5
    assert summary["answer_keyword_hit_rate"] == 0.5
    assert summary["fallback_rate"] == 0.5
    assert summary["avg_latency_ms"] == 2000
    assert summary["p50_latency_ms"] == 1000
    assert summary["p95_latency_ms"] == 1000
    assert summary["max_latency_ms"] == 3000
