from __future__ import annotations

import shutil
from pathlib import Path
from uuid import uuid4

from core.contracts import RetrievedDocument, RetrievalResponse, SourceRef
from core.knowledge_base import KnowledgeBaseService
from core.persistence import ConversationStore
from rag.ingestion import active_version, ingest_document_entries, load_active_documents


def test_knowledge_document_lifecycle_publish_rollback_and_analytics(monkeypatch):
    suffix = uuid4().hex
    database_path = Path.cwd() / f"p1-6-knowledge-{suffix}.db"
    active = {"version": None}
    releases = {}

    def fake_ingest(index_dir, entries, *, version, publish):
        releases[version] = list(entries)
        return {"version": version, "document_count": len(releases[version]), "chunk_count": len(releases[version])}

    def fake_publish(index_dir, version):
        active["version"] = version

    def fake_rollback(index_dir, version):
        active["version"] = version

    source = SourceRef(type="knowledge_base", source="nutrition.txt", document_id="doc")
    retrieved = RetrievedDocument(content="蛋白质有助于维持肌肉。", source=source, score=1.0)
    monkeypatch.setattr("core.knowledge_base.ingest_document_entries", fake_ingest)
    monkeypatch.setattr("core.knowledge_base.publish_version", fake_publish)
    monkeypatch.setattr("core.knowledge_base.rollback_version", fake_rollback)
    monkeypatch.setattr("core.knowledge_base.active_version", lambda index_dir: active["version"])
    monkeypatch.setattr(
        "core.knowledge_base.retrieve_with_contract",
        lambda *args, **kwargs: RetrievalResponse(status="success", documents=[retrieved], sources=[source]),
    )
    store = None
    try:
        store = ConversationStore(database_url=f"sqlite:///{database_path}")
        service = KnowledgeBaseService(store, index_dir="unused-index")

        draft = service.upload_document(
            source_name="nutrition.txt",
            title="营养基础",
            content="蛋白质有助于维持肌肉。",
            actor="admin-1",
        )
        assert draft["status"] == "draft"
        assert draft["latest_version"] == 1

        approved = service.review_document(draft["id"], actor="reviewer-1", approved=True, note="内容已核验")
        assert approved["status"] == "approved"
        first_build = service.build_index(actor="admin-1")
        assert first_build["status"] == "published"
        assert first_build["progress"] == 100
        assert active["version"] == first_build["index_version"]
        assert releases[first_build["index_version"]][0]["content"] == "蛋白质有助于维持肌肉。"

        retrieval = service.retrieval_test("蛋白质", actor="admin-1")
        assert retrieval["status"] == "success"
        assert retrieval["sources"][0]["source"] == "nutrition.txt"
        analytics = service.analytics()
        assert analytics["total_queries"] == 1
        assert analytics["hit_rate"] == 1.0

        updated = service.upload_document(
            source_name="nutrition.txt",
            content="碳水化合物是常见的能量来源。",
            actor="admin-1",
        )
        assert updated["status"] == "draft"
        assert updated["latest_version"] == 2
        assert updated["published_version"] == 1
        assert releases[first_build["index_version"]][0]["content"] == "蛋白质有助于维持肌肉。"

        service.review_document(updated["id"], actor="reviewer-1", approved=True)
        second_build = service.build_index(actor="admin-1")
        assert second_build["index_version"] != first_build["index_version"]
        assert releases[second_build["index_version"]][0]["content"] == "碳水化合物是常见的能量来源。"

        rollback = service.rollback(first_build["index_version"], actor="admin-1")
        assert rollback["active_version"] == first_build["index_version"]
        assert active["version"] == first_build["index_version"]

        unpublished = service.unpublish_document(updated["id"], actor="admin-1")
        assert unpublished["document"]["status"] == "unpublished"
        assert releases[unpublished["build"]["index_version"]] == []
    finally:
        if store is not None:
            store.engine.dispose()
        if database_path.exists():
            database_path.unlink()


def test_managed_entries_publish_an_atomic_index_file():
    index_path = Path.cwd() / f"p1-6-real-index-{uuid4().hex}"
    try:
        manifest = ingest_document_entries(
            index_path,
            [
                {
                    "content": "蛋白质有助于维持肌肉。",
                    "source": "nutrition.txt",
                    "title": "营养基础",
                    "document_id": "managed-doc-1",
                    "access_groups": ["public"],
                }
            ],
            version="managed-v1",
        )
        assert manifest["document_count"] == 1
        assert active_version(index_path) == "managed-v1"
        documents = load_active_documents(index_path)
        assert documents[0].metadata["document_id"] == "managed-doc-1"
        assert documents[0].metadata["version"] == "managed-v1"
    finally:
        if index_path.exists():
            shutil.rmtree(index_path)
