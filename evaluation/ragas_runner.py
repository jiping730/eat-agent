"""Optional RAGAS adapter.

RAGAS needs generated answers in addition to retrieved contexts.  The adapter
therefore accepts a local JSON file keyed by ``case_id`` and never invents
answers or sends user content to an external provider implicitly.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from core.contracts import EvalCase
from evaluation.runner import REPORT_PATH, FixtureRetriever, _load_fixture_documents, write_report


def run_ragas(
    cases: Iterable[EvalCase],
    *,
    answers_path: Path | None,
    report_path: Path = REPORT_PATH,
) -> dict[str, Any]:
    """Run RAGAS for RAG cases when optional dependencies and answers exist."""

    if answers_path is None:
        raise ValueError("RAGAS 模式必须通过 --answers-file 提供模型回答 JSON")
    try:
        from datasets import Dataset
        from ragas import evaluate
        from ragas.metrics import answer_relevancy, context_precision, context_recall, faithfulness
    except ImportError as exc:
        raise RuntimeError("未安装 RAGAS 评测依赖，请安装 .[eval]") from exc

    answers_payload = json.loads(answers_path.read_text(encoding="utf-8"))
    if not isinstance(answers_payload, dict):
        raise ValueError("--answers-file 必须是按 case_id 索引的 JSON 对象")
    documents = _load_fixture_documents()
    retriever = FixtureRetriever(
        fixture_documents=documents,
        source_dir=str(Path(__file__).parent / "fixtures"),
        index_dir=str(Path(__file__).parent / "fixtures" / ".index-not-used"),
        vector_loader=None,
        top_k=4,
    )
    rows: list[dict[str, Any]] = []
    for case in cases:
        if case.suite != "rag":
            continue
        answer = answers_payload.get(case.case_id)
        if not isinstance(answer, dict) or not isinstance(answer.get("answer"), str):
            raise ValueError(f"RAGAS 回答缺少 case_id={case.case_id} 的 answer")
        contexts = answer.get("contexts")
        if not isinstance(contexts, list):
            contexts = [document.page_content for document in retriever.retrieve(case.question)]
        rows.append(
            {
                "user_input": case.question,
                "response": answer["answer"],
                "retrieved_contexts": [str(item) for item in contexts],
                "reference": str(answer.get("reference") or " ".join(case.answer_points)),
            }
        )
    if not rows:
        raise ValueError("没有可供 RAGAS 评测的 RAG 用例")

    score = evaluate(
        Dataset.from_list(rows),
        metrics=[faithfulness, context_precision, context_recall, answer_relevancy],
    )
    report = {
        "schema_version": "1.0",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "mode": "ragas",
        "passed": True,
        "metrics": {"ragas": {key: float(value) for key, value in score.items()}},
        "case_count": len(rows),
        "source_answers_file": str(answers_path),
    }
    write_report(report, report_path)
    return report
