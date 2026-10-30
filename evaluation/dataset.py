"""Load and normalize the small-platform evaluation fixtures.

The repository started with separate RAG and Grill JSON shapes.  This module
keeps those files readable while exposing one validated :class:`EvalCase`
shape to every later evaluation stage.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable

from core.contracts import EvalCase

EVALUATION_DIR = Path(__file__).resolve().parent
DEFAULT_SUITE_PATHS = {
    "rag": EVALUATION_DIR / "rag_cases.json",
    "grill": EVALUATION_DIR / "grill_cases.json",
}


def _normalize_case(payload: dict[str, Any], *, suite: str, source: Path) -> EvalCase:
    """Map legacy fixture fields into the unified contract before validation."""

    normalized = dict(payload)
    normalized.setdefault("suite", suite)
    normalized.setdefault("category", suite)

    # The first Grill fixture version used ``name`` and ``task``.  Keep both
    # source files unchanged so the existing parametrized tests remain useful.
    normalized.setdefault("case_id", normalized.pop("name", None))
    normalized.setdefault("expected_task", normalized.pop("task", None))
    if normalized.get("required_slots") and not normalized.get("required_fields"):
        normalized["required_fields"] = list(normalized["required_slots"])
    if normalized.get("required_fields") and not normalized.get("required_slots"):
        normalized["required_slots"] = list(normalized["required_fields"])

    if not normalized.get("case_id"):
        raise ValueError(f"评测用例缺少 case_id/name: {source}")
    try:
        return EvalCase.model_validate(normalized)
    except Exception as exc:
        raise ValueError(f"评测用例无效 ({source}, case_id={normalized.get('case_id')}): {exc}") from exc


def load_cases(path: str | Path, *, suite: str | None = None) -> list[EvalCase]:
    """Load a JSON array and validate every item as an :class:`EvalCase`."""

    fixture_path = Path(path)
    payload = json.loads(fixture_path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError(f"评测文件必须是 JSON 数组: {fixture_path}")
    inferred_suite = suite or fixture_path.stem.removesuffix("_cases")
    cases: list[EvalCase] = []
    seen_ids: set[str] = set()
    for item in payload:
        if not isinstance(item, dict):
            raise ValueError(f"评测用例必须是 JSON 对象: {fixture_path}")
        case = _normalize_case(item, suite=inferred_suite, source=fixture_path)
        if case.case_id in seen_ids:
            raise ValueError(f"评测用例 case_id 重复: {case.case_id}")
        seen_ids.add(case.case_id)
        cases.append(case)
    return cases


def load_suite(suite: str) -> list[EvalCase]:
    """Load one named built-in suite (``rag`` or ``grill``)."""

    try:
        path = DEFAULT_SUITE_PATHS[suite]
    except KeyError as exc:
        raise ValueError(f"未知评测套件: {suite}; 可选值: {', '.join(DEFAULT_SUITE_PATHS)}") from exc
    return load_cases(path, suite=suite)


def iter_cases(suites: Iterable[str] = ("rag", "grill")) -> list[EvalCase]:
    """Load multiple built-in suites in stable suite/file order."""

    cases: list[EvalCase] = []
    for suite in suites:
        cases.extend(load_suite(suite))
    return cases
