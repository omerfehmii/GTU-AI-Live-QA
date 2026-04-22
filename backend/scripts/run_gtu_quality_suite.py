from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = PROJECT_ROOT / "backend"
DEFAULT_PROFILE = PROJECT_ROOT / "sample_data" / "gtu_seed_urls.json"
DEFAULT_EVAL_SET = PROJECT_ROOT / "sample_data" / "gtu_eval_questions.json"
DEFAULT_REPORT = PROJECT_ROOT / "docs" / "gtu_quality_report.json"

if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run GTU ingest and RAG quality evaluation.")
    parser.add_argument("--profile", type=Path, default=DEFAULT_PROFILE)
    parser.add_argument("--eval-set", type=Path, default=DEFAULT_EVAL_SET)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument(
        "--database-url",
        default=f"sqlite:///{PROJECT_ROOT / 'backend' / 'quality_suite.db'}",
        help="Database URL to use for the run.",
    )
    parser.add_argument("--max-pages", type=int, default=None, help="Override crawl max_pages from the profile.")
    parser.add_argument("--max-questions", type=int, default=None, help="Limit evaluation questions for quicker runs.")
    parser.add_argument("--skip-ingest", action="store_true", help="Reuse existing DB contents and skip ingest.")
    parser.add_argument(
        "--keep-shell-provider-keys",
        action="store_true",
        help="By default, provider keys from the shell are cleared so .env values are used.",
    )
    return parser.parse_args()


def configure_environment(args: argparse.Namespace) -> None:
    os.environ["DATABASE_URL"] = args.database_url
    if not args.keep_shell_provider_keys:
        os.environ.pop("OPENROUTER_API_KEY", None)
        os.environ.pop("OPENAI_API_KEY", None)


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> int:
    args = parse_args()
    configure_environment(args)

    from app.db import SessionLocal, init_db
    from app.schemas import WebIngestRequest
    from app.services.evaluation import (
        EvaluationCase,
        EvaluationResult,
        answer_keyword_hit,
        source_hit,
        summarize_results,
    )
    from app.services.ingest import IngestService
    from app.services.rag import RagService

    profile = load_json(args.profile)
    if args.max_pages is not None:
        profile["max_pages"] = args.max_pages

    evaluation_payload = load_json(args.eval_set)
    cases = [EvaluationCase(**item) for item in evaluation_payload]
    if args.max_questions is not None:
        cases = cases[: args.max_questions]

    args.report.parent.mkdir(parents=True, exist_ok=True)
    init_db()

    ingest_summary: dict[str, int] | None = None
    results: list[EvaluationResult] = []

    with SessionLocal() as db:
        if not args.skip_ingest:
            ingest_service = IngestService(db)
            request = WebIngestRequest.model_validate(profile)
            print(f"[ingest] starting with {len(request.seed_urls)} seed URL(s), {len(request.pdf_urls)} PDF URL(s)")
            summary = ingest_service.ingest_web(request)
            ingest_summary = summary.model_dump()
            print(f"[ingest] documents={summary.documents_created} chunks={summary.chunks_created} skipped={summary.skipped}")

        rag_service = RagService(db)
        metrics_before = rag_service.metrics().model_dump()
        print(f"[eval] questions={len(cases)} documents={metrics_before['documents']} chunks={metrics_before['chunks']}")

        for index, case in enumerate(cases, start=1):
            print(f"[eval] {index}/{len(cases)} {case.id}: {case.question}")
            question = rag_service.ask_manual_question(case.question, author_name="Quality Suite")
            answer = question.answer
            if answer is None:
                raise RuntimeError(f"No answer generated for case {case.id}")
            traces = answer.traces
            top_trace = traces[0] if traces else None
            result = EvaluationResult(
                id=case.id,
                question=case.question,
                category=case.category,
                top1_source_hit=source_hit([top_trace] if top_trace else [], case.expected_source_contains),
                source_hit=source_hit(traces, case.expected_source_contains),
                answer_keyword_hit=answer_keyword_hit(answer.content, case.expected_answer_keywords),
                fallback_used=answer.fallback_used,
                latency_ms=answer.latency_ms,
                confidence=answer.confidence,
                top_source_title=top_trace.source_title if top_trace else None,
                top_source_url=top_trace.source_url if top_trace else None,
                answer_preview=answer.content[:280],
            )
            results.append(result)
            print(
                "[eval]   source_hit=%s keyword_hit=%s fallback=%s latency=%sms top=%s"
                % (
                    result.source_hit,
                    result.answer_keyword_hit,
                    result.fallback_used,
                    result.latency_ms,
                    result.top_source_title or "-",
                )
            )

    report = {
        "profile": str(args.profile),
        "eval_set": str(args.eval_set),
        "database_url": args.database_url,
        "ingest_summary": ingest_summary,
        "summary": summarize_results(results),
        "results": [result.to_dict() for result in results],
    }
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[report] written to {args.report}")
    print(json.dumps(report["summary"], ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
