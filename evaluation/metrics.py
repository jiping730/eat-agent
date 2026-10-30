"""Deterministic metrics for evaluation case results."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any


def _rate(numerator: int, denominator: int) -> float:
    return round(numerator / denominator, 4) if denominator else 0.0


def _results_for_suite(results: Iterable[Mapping[str, Any]], suite: str) -> list[Mapping[str, Any]]:
    return [result for result in results if result.get("suite") == suite]


def _check_passed(result: Mapping[str, Any], name: str) -> bool:
    return bool((result.get("checks") or {}).get(name))


def rag_metrics(results: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    """Calculate source-retrieval quality without an LLM judge."""

    cases = _results_for_suite(results, "rag")
    source_cases = [case for case in cases if case.get("expected_sources")]
    expected_source_count = sum(len(case.get("expected_sources") or []) for case in source_cases)
    covered_source_count = sum(int(case.get("details", {}).get("covered_source_count", 0)) for case in source_cases)

    reciprocal_ranks: list[float] = []
    for case in source_cases:
        rank = case.get("details", {}).get("first_expected_rank")
        reciprocal_ranks.append(1 / int(rank) if rank else 0.0)

    invalid_candidates = [
        case
        for case in cases
        if case.get("should_retrieve") is False and case.get("details", {}).get("retrieval_count", 0) > 0
    ]
    decision_cases = [case for case in cases if case.get("should_retrieve") is not None]
    decision_correct = sum(_check_passed(case, "should_retrieve") for case in decision_cases)

    return {
        "case_count": len(cases),
        "passed_count": sum(bool(case.get("passed")) for case in cases),
        "recall_at_k": _rate(covered_source_count, expected_source_count),
        "mrr": round(sum(reciprocal_ranks) / len(reciprocal_ranks), 4) if reciprocal_ranks else 0.0,
        "source_coverage": _rate(covered_source_count, expected_source_count),
        "invalid_retrieval_rate": _rate(len(invalid_candidates), len(decision_cases)),
        "retrieval_decision_accuracy": (_rate(decision_correct, len(decision_cases)) if decision_cases else None),
    }


def grill_metrics(results: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    """Calculate Grill action, field, and safety-gating quality."""

    cases = _results_for_suite(results, "grill")
    action_cases = [case for case in cases if case.get("expected_action")]
    field_cases = [case for case in action_cases if case.get("expected_field") is not None]
    action_correct = sum(_check_passed(case, "expected_action") for case in action_cases)
    field_correct = sum(_check_passed(case, "expected_field") for case in field_cases)

    premature_cases = [case for case in cases if case.get("must_not_execute")]
    premature_answers = sum(case.get("details", {}).get("actual_action") == "execute" for case in premature_cases)
    over_question_cases = [
        case
        for case in cases
        if case.get("expected_action") == "execute" and case.get("actual_action") in {"clarify", "fallback"}
    ]
    expected_clarification_cases = [case for case in action_cases if case.get("expected_action") == "clarify"]
    clarification_correct = sum(
        _check_passed(case, "expected_field") for case in field_cases if case.get("expected_action") == "clarify"
    )

    safety_cases = [
        case
        for case in cases
        if case.get("must_include") or case.get("must_not_include") or case.get("forbidden_action")
    ]
    safety_passed = sum(bool(case.get("passed")) for case in safety_cases)

    return {
        "case_count": len(cases),
        "passed_count": sum(bool(case.get("passed")) for case in cases),
        "action_accuracy": _rate(action_correct, len(action_cases)),
        "target_field_accuracy": _rate(field_correct, len(field_cases)),
        "clarification_field_f1": (
            _rate(clarification_correct, len(expected_clarification_cases)) if expected_clarification_cases else None
        ),
        "premature_answer_rate": _rate(premature_answers, len(premature_cases)),
        "over_question_rate": _rate(len(over_question_cases), len(action_cases)),
        "safety_case_pass_rate": _rate(safety_passed, len(safety_cases)) if safety_cases else None,
    }


def safety_metrics(results: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    """Calculate safety-gate metrics across RAG and Grill cases."""

    materialized = list(results)
    safety_cases = [
        case
        for case in materialized
        if case.get("must_not_execute")
        or case.get("must_include")
        or case.get("must_not_include")
        or case.get("forbidden_action")
    ]
    gating_cases = [case for case in safety_cases if case.get("must_not_execute")]
    content_required_cases = [case for case in safety_cases if case.get("must_include")]
    forbidden_content_cases = [case for case in safety_cases if case.get("must_not_include")]
    forbidden_action_cases = [case for case in safety_cases if case.get("forbidden_action")]

    return {
        "case_count": len(safety_cases),
        "passed_count": sum(bool(case.get("passed")) for case in safety_cases),
        "safety_case_pass_rate": (
            _rate(sum(bool(case.get("passed")) for case in safety_cases), len(safety_cases)) if safety_cases else None
        ),
        "safety_gating_accuracy": (
            _rate(sum(_check_passed(case, "must_not_execute") for case in gating_cases), len(gating_cases))
            if gating_cases
            else None
        ),
        "required_content_coverage": (
            _rate(
                sum(_check_passed(case, "must_include") for case in content_required_cases), len(content_required_cases)
            )
            if content_required_cases
            else None
        ),
        "forbidden_content_violation_rate": (
            _rate(
                sum(not _check_passed(case, "must_not_include") for case in forbidden_content_cases),
                len(forbidden_content_cases),
            )
            if forbidden_content_cases
            else None
        ),
        "forbidden_action_violation_rate": (
            _rate(
                sum(not _check_passed(case, "forbidden_action") for case in forbidden_action_cases),
                len(forbidden_action_cases),
            )
            if forbidden_action_cases
            else None
        ),
    }


def calculate_metrics(results: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    """Return suite metrics plus aggregate case counts."""

    materialized = list(results)
    return {
        "total": {
            "case_count": len(materialized),
            "passed_count": sum(bool(case.get("passed")) for case in materialized),
            "failed_count": sum(not bool(case.get("passed")) for case in materialized),
        },
        "rag": rag_metrics(materialized),
        "grill": grill_metrics(materialized),
        "safety": safety_metrics(materialized),
    }
