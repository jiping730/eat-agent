import json
from pathlib import Path

from langchain_core.documents import Document

from core.contracts import EvalCase
from rag.retriever import HybridRetriever


def test_rag_golden_cases_keep_expected_source_in_top_k(monkeypatch, tmp_path):
    documents = [
        Document(
            page_content="鸡胸肉是常见的蛋白质来源，适合搭配蔬菜。",
            metadata={"source": "nutrition/protein.txt", "title": "蛋白质来源", "access_groups": ["public"]},
        ),
        Document(
            page_content="鸡胸肉每100克的热量会随生熟和品牌变化，查询时需要说明口径。",
            metadata={"source": "nutrition/calorie.txt", "title": "热量查询", "access_groups": ["public"]},
        ),
        Document(
            page_content="减肥期间应关注总热量、蛋白质、蔬菜和长期可执行性，不建议极端节食。",
            metadata={"source": "nutrition/weight-loss.txt", "title": "减肥建议", "access_groups": ["public"]},
        ),
        Document(
            page_content="花生过敏者应避开花生及可能含花生的食品，必要时咨询专业人士。",
            metadata={"source": "safety/allergens.txt", "title": "过敏原安全", "access_groups": ["public"]},
        ),
    ]
    retriever = HybridRetriever(
        source_dir=str(tmp_path / "documents"),
        index_dir=str(tmp_path / "index"),
        vector_loader=None,
        top_k=2,
    )
    monkeypatch.setattr(retriever, "_corpus", lambda: documents)

    cases = [
        EvalCase.model_validate(item)
        for item in json.loads(Path("evaluation/rag_cases.json").read_text(encoding="utf-8"))
    ]
    for case in cases:
        results = retriever.retrieve(case.question)
        result_sources = {str(document.metadata.get("source")) for document in results}
        assert result_sources.intersection(case.expected_sources), case.case_id
