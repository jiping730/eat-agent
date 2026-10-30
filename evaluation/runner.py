"""Run deterministic RAG and Grill evaluation suites.

The default runner has no network or model dependency.  It evaluates the
retriever and Grill decision boundary against local fixtures, making it safe
for pull-request CI.  RAGAS is intentionally exposed as a separate optional
mode and never runs as part of the deterministic path.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Sequence

from langchain_core.documents import Document

from core.contracts import EvalCase
from core.grill_engine import GrillEngine, get_profile
from evaluation.dataset import load_suite
from evaluation.metrics import calculate_metrics
from rag.retriever import HybridRetriever

REPORT_PATH = Path(__file__).resolve().parent / "reports" / "latest.json"
RAG_CORPUS_PATH = Path(__file__).resolve().parent / "fixtures" / "rag_corpus.json"


class FixtureRetriever(HybridRetriever):
    """HybridRetriever backed by a committed, deterministic evaluation corpus."""

    def __init__(self, fixture_documents: list[Document], **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.fixture_documents = fixture_documents

    def _corpus(self) -> list[Document]:
        return list(self.fixture_documents)


def _load_fixture_documents() -> list[Document]:
    payload = json.loads(RAG_CORPUS_PATH.read_text(encoding="utf-8"))
    return [Document(page_content=item["content"], metadata=dict(item.get("metadata") or {})) for item in payload]


def _git_sha() -> str | None:
    try:
        completed = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, check=True, text=True, timeout=5)
    except (OSError, subprocess.SubprocessError):
        return None
    return completed.stdout.strip() or None


def _contains_all(text: str, values: Iterable[str]) -> bool:
    normalized = text.casefold()
    return all(str(value).casefold() in normalized for value in values)


def _evaluate_rag_case(case: EvalCase, retriever: FixtureRetriever) -> dict[str, Any]:
    documents = retriever.retrieve(case.question)
    actual_sources = [str((document.metadata or {}).get("source") or "") for document in documents]
    expected_sources = list(case.expected_sources)
    covered = [source for source in expected_sources if source in actual_sources]
    ranks = [actual_sources.index(source) + 1 for source in expected_sources if source in actual_sources]
    should_retrieve = case.should_retrieve if case.should_retrieve is not None else bool(expected_sources)
    retrieved_text = "\n".join(document.page_content for document in documents)
    checks = {
        "expected_sources": not expected_sources or set(expected_sources).issubset(set(actual_sources)),
        "should_retrieve": should_retrieve,
        # Retrieval itself is not an answer/tool execution.  A safety RAG case
        # can therefore require evidence while still forbidding downstream
        # execution; this adapter has no downstream executor by design.
        "must_not_execute": True,
        "must_include": _contains_all(retrieved_text, case.must_include),
        "must_not_include": not any(value.casefold() in retrieved_text.casefold() for value in case.must_not_include),
        "expected_keywords": _contains_all(retrieved_text, case.expected_keywords),
    }
    details = {
        "retrieval_count": len(documents),
        "actual_sources": actual_sources,
        "covered_source_count": len(covered),
        "first_expected_rank": min(ranks) if ranks else None,
        "retrieval_attempted": True,
    }
    return _case_result(case, checks, details, actual_retrieved=True, expected_retrieval=should_retrieve)


def _run_grill_turns(case: EvalCase, profile: Any) -> Any:
    engine = GrillEngine()
    context: Any = case.context or None
    result = None
    for turn in case.conversation:
        if not isinstance(turn, dict):
            continue
        prompt = turn.get("question") or turn.get("content") or turn.get("message")
        if not isinstance(prompt, str) or not prompt.strip():
            continue
        result = engine.process(profile, prompt, context, current_intent=case.expected_task)
        context = result.context
    return engine.process(profile, case.question, context, current_intent=case.expected_task)


def _evaluate_grill_case(case: EvalCase) -> dict[str, Any]:
    task = case.expected_task
    profile = get_profile(task)
    if profile is None:
        return _case_result(
            case,
            {"profile_exists": False},
            {"error": f"未找到 Grill profile: {task}"},
            actual_retrieved=False,
        )

    result = _run_grill_turns(case, profile)
    output_text = " ".join(value for value in (result.message, result.question) if value)
    actual_action = str(result.action)
    checks: dict[str, bool] = {
        "profile_exists": True,
        "expected_action": case.expected_action is None or actual_action == case.expected_action,
        "expected_field": case.expected_field is None or result.target_field == case.expected_field,
        "expected_task": case.expected_task is None or result.task == case.expected_task,
        "required_fields": not (case.required_fields or case.required_slots)
        or set(case.required_fields or case.required_slots).issubset(
            set(result.missing_fields) | set(result.context.fields)
        ),
        "must_not_execute": not case.must_not_execute or actual_action != "execute",
        "forbidden_action": case.forbidden_action is None or actual_action != case.forbidden_action,
        "must_include": _contains_all(output_text, case.must_include),
        "must_not_include": not any(value.casefold() in output_text.casefold() for value in case.must_not_include),
        "expected_keywords": _contains_all(output_text, case.expected_keywords),
        "should_retrieve": case.should_retrieve is None or case.should_retrieve is False,
    }
    details = {
        "actual_action": actual_action,
        "actual_target_field": result.target_field,
        "actual_task": result.task,
        "message": result.message,
        "question": result.question,
        "retrieval_count": 0,
        "retrieval_attempted": False,
        "context_fields": dict(result.context.fields),
    }
    return _case_result(case, checks, details, actual_action=actual_action, actual_retrieved=False)


def _case_result(
    case: EvalCase,
    checks: dict[str, bool],
    details: dict[str, Any],
    *,
    actual_action: str | None = None,
    actual_retrieved: bool = False,
    expected_retrieval: bool | None = None,
) -> dict[str, Any]:
    return {
        "case_id": case.case_id,
        "suite": case.suite,
        "category": case.category,
        "question": case.question,
        "expected_sources": list(case.expected_sources),
        "expected_action": case.expected_action,
        "expected_field": case.expected_field,
        "must_not_execute": case.must_not_execute,
        "must_include": list(case.must_include),
        "must_not_include": list(case.must_not_include),
        "forbidden_action": case.forbidden_action,
        "should_retrieve": expected_retrieval if expected_retrieval is not None else case.should_retrieve,
        "actual_action": actual_action,
        "actual_retrieved": actual_retrieved,
        "checks": checks,
        "details": details,
        "passed": all(checks.values()),
    }


def run_deterministic(cases: Iterable[EvalCase], *, top_k: int = 2) -> list[dict[str, Any]]:
    """Evaluate cases using only local deterministic components."""

    documents = _load_fixture_documents()
    retriever = FixtureRetriever(
        fixture_documents=documents,
        source_dir=str(RAG_CORPUS_PATH.parent),
        index_dir=str(RAG_CORPUS_PATH.parent / ".index-not-used"),
        vector_loader=None,
        top_k=top_k,
    )
    results: list[dict[str, Any]] = []
    for case in cases:
        if case.suite == "rag":
            results.append(_evaluate_rag_case(case, retriever))
        elif case.suite == "grill":
            results.append(_evaluate_grill_case(case))
        else:
            results.append(_case_result(case, {"supported_suite": False}, {"error": f"不支持的 suite: {case.suite}"}))
    return results


def build_report(
    results: Sequence[dict[str, Any]],
    *,
    mode: str,
    thresholds: dict[str, float | None] | None = None,
) -> dict[str, Any]:
    metrics = calculate_metrics(results)
    threshold_values = thresholds or {}
    threshold_checks: dict[str, bool] = {}
    if threshold_values.get("min_rag_recall") is not None:
        threshold_checks["min_rag_recall"] = metrics["rag"]["recall_at_k"] >= threshold_values["min_rag_recall"]
    if threshold_values.get("min_grill_accuracy") is not None:
        threshold_checks["min_grill_accuracy"] = (
            metrics["grill"]["action_accuracy"] >= threshold_values["min_grill_accuracy"]
        )
    if threshold_values.get("max_invalid_retrieval_rate") is not None:
        threshold_checks["max_invalid_retrieval_rate"] = (
            metrics["rag"]["invalid_retrieval_rate"] <= threshold_values["max_invalid_retrieval_rate"]
        )
    if threshold_values.get("min_safety_pass_rate") is not None:
        safety_pass_rate = metrics["safety"]["safety_case_pass_rate"]
        threshold_checks["min_safety_pass_rate"] = (
            safety_pass_rate is not None and safety_pass_rate >= threshold_values["min_safety_pass_rate"]
        )
    all_cases_passed = all(bool(result["passed"]) for result in results)
    report = {
        "schema_version": "1.0",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "commit_sha": _git_sha(),
        "mode": mode,
        "metrics": metrics,
        "thresholds": threshold_values,
        "threshold_checks": threshold_checks,
        "passed": all_cases_passed and all(threshold_checks.values()),
        "cases": list(results),
    }
    return report


def write_report(report: dict[str, Any], path: str | Path = REPORT_PATH) -> Path:
    report_path = Path(path)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report_path


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="运行 Eat Agent 确定性评测")
    parser.add_argument("--suite", choices=("all", "rag", "grill"), default="all")
    parser.add_argument("--mode", choices=("deterministic", "ragas"), default="deterministic")
    parser.add_argument("--top-k", type=int, default=2)
    parser.add_argument("--report", type=Path, default=REPORT_PATH)
    parser.add_argument("--answers-file", type=Path, help="RAGAS 模式的模型回答 JSON 文件")
    parser.add_argument("--min-rag-recall", type=float)
    parser.add_argument("--min-grill-accuracy", type=float)
    parser.add_argument("--max-invalid-retrieval-rate", type=float)
    parser.add_argument("--min-safety-pass-rate", type=float)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    suites = ("rag", "grill") if args.suite == "all" else (args.suite,)
    cases = [case for suite in suites for case in load_suite(suite)]
    thresholds = {
        "min_rag_recall": args.min_rag_recall,
        "min_grill_accuracy": args.min_grill_accuracy,
        "max_invalid_retrieval_rate": args.max_invalid_retrieval_rate,
        "min_safety_pass_rate": args.min_safety_pass_rate,
    }
    if args.mode == "ragas":
        from evaluation.ragas_runner import run_ragas

        try:
            report = run_ragas(cases, answers_path=args.answers_file, report_path=args.report)
        except (OSError, RuntimeError, ValueError, json.JSONDecodeError) as exc:
            print(f"RAGAS 评测未执行：{exc}", file=sys.stderr)
            return 2
    else:
        report = build_report(run_deterministic(cases, top_k=max(1, args.top_k)), mode=args.mode, thresholds=thresholds)
        write_report(report, args.report)
    print(
        json.dumps(
            {"passed": report["passed"], "metrics": report["metrics"], "report": str(args.report)}, ensure_ascii=False
        )
    )
    return 0 if report["passed"] else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
