import json

from langchain_core.documents import Document

from rag.ingestion import active_version, ingest_documents, load_active_documents, rollback_version
from rag.retriever import HybridRetriever, retrieve_with_contract, rewrite_query


def test_ingestion_cleans_deduplicates_and_publishes_atomically(tmp_path):
    source = tmp_path / "documents"
    index = tmp_path / "index"
    source.mkdir()
    (source / "one.txt").write_text("\ufeff蛋白质  主要来源：鸡蛋。\n\n重复段落。", encoding="utf-8")
    (source / "two.txt").write_text("重复段落。\n\n碳水化合物主要来源：米饭。", encoding="utf-8")

    manifest = ingest_documents(source, index, version="v1")

    assert manifest["chunk_count"] == 3
    assert active_version(index) == "v1"
    assert len(load_active_documents(index)) == 3
    assert json.loads((index / "current.json").read_text(encoding="utf-8"))["version"] == "v1"


def test_publish_and_rollback_keep_previous_versions(tmp_path):
    source = tmp_path / "documents"
    index = tmp_path / "index"
    source.mkdir()
    document = source / "guide.txt"
    document.write_text("第一版：蛋白质。", encoding="utf-8")
    ingest_documents(source, index, version="v1")
    document.write_text("第二版：碳水化合物。", encoding="utf-8")
    ingest_documents(source, index, version="v2")

    rollback_version(index, "v1")

    assert active_version(index) == "v1"
    assert "第一版" in load_active_documents(index)[0].page_content


def test_hybrid_retriever_uses_lexical_recall_and_access_filter(monkeypatch, tmp_path):
    public = Document(
        page_content="鸡胸肉是常见的蛋白质来源。",
        metadata={"source": "public.txt", "access_groups": ["public"]},
    )
    private = Document(
        page_content="内部实验配方。",
        metadata={"source": "private.txt", "access_groups": ["internal"]},
    )
    retriever = HybridRetriever(
        source_dir=str(tmp_path / "documents"),
        index_dir=str(tmp_path / "index"),
        vector_loader=None,
        access_groups={"public"},
    )
    monkeypatch.setattr(retriever, "_corpus", lambda: [public, private])

    results = retriever.retrieve("鸡胸肉蛋白质")

    assert len(results) == 1
    assert "鸡胸肉" in results[0].page_content
    assert results[0].metadata["retrieval_method"] == "bm25"
    assert results[0].metadata["source"] == "public.txt"


def test_query_rewrite_is_deterministic_and_vector_results_remain_compatible(tmp_path):
    rewrite = rewrite_query("卡路里：鸡胸肉")
    assert rewrite.normalized == "热量:鸡胸肉"
    assert "热" in rewrite.terms

    def fake_vector_loader():
        return type(
            "VectorStore",
            (),
            {"similarity_search_with_score": lambda self, query, k: [(Document(page_content="向量结果"), 0.2)]},
        )()

    retriever = HybridRetriever(
        source_dir=str(tmp_path / "missing"),
        index_dir=str(tmp_path / "missing-index"),
        vector_loader=fake_vector_loader,
    )
    results = retriever.retrieve("任意查询")

    assert results[0].metadata["retrieval_method"] == "vector"


def test_retrieval_contract_contains_evidence_and_rerank_metadata(monkeypatch, tmp_path):
    document = Document(
        page_content="鸡胸肉是常见的蛋白质来源。",
        metadata={"source": "nutrition/protein.txt", "title": "蛋白质来源", "access_groups": ["public"]},
    )
    retriever = HybridRetriever(
        source_dir=str(tmp_path / "documents"),
        index_dir=str(tmp_path / "index"),
        vector_loader=None,
    )
    monkeypatch.setattr(retriever, "_corpus", lambda: [document])
    monkeypatch.setattr("rag.retriever.HybridRetriever", lambda **_: retriever)

    response = retrieve_with_contract("鸡胸肉蛋白质", top_k=1)

    assert response.status == "success"
    assert response.documents[0].content.startswith("鸡胸肉")
    assert response.sources[0].source == "nutrition/protein.txt"
    assert response.documents[0].metadata["rerank_method"] == "deterministic_coverage"
