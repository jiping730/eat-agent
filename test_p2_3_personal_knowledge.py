from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config

from core.knowledge_base import KnowledgeBaseService
from core.offline_answer import OfflineAnswerService
from core.personal_knowledge import PersonalKnowledgeService
from core.persistence import ConversationStore
from core.tenant import TenantService


def _services(tmp_path: Path):
    store = ConversationStore(database_url=f"sqlite:///{tmp_path / 'p2-3.db'}")
    knowledge = KnowledgeBaseService(store, index_dir=str(tmp_path / "indexes"))
    return store, PersonalKnowledgeService(store, knowledge_service=knowledge)


def test_personal_documents_are_indexed_and_deleted_without_leaking(tmp_path: Path):
    store, service = _services(tmp_path)
    tenant = TenantService(store).create("user-1", "共享空间", "p2-3-shared")
    tenant_id = tenant["id"]
    store.add_or_update_member(tenant_id, user_id="user-2", role="member")

    imported = service.import_text(
        user_id="user-1",
        tenant_id=tenant_id,
        source_name="notes.md",
        title="我的目标",
        content="我的目标是每天保持规律饮食，并优先选择高纤维食物。",
    )
    assert imported["document"]["scope"] == "personal"
    assert imported["document"]["owner_user_id"] == "user-1"
    assert service.list_documents(user_id="user-2", tenant_id=tenant_id) == []

    hit = service.retrieval_test(
        user_id="user-1",
        tenant_id=tenant_id,
        query="我的饮食目标是什么",
    )
    assert hit["status"] == "success"
    assert hit["rewritten_query"]
    assert hit["sources"][0]["type"] == "personal_knowledge"
    assert hit["sources"][0]["metadata"]["scope"] == "personal"

    deleted = service.delete_document(
        user_id="user-1",
        tenant_id=tenant_id,
        document_id=imported["document"]["id"],
    )
    assert deleted["document"]["status"] == "deleted"
    assert service.list_documents(user_id="user-1", tenant_id=tenant_id) == []
    assert service.retrieval_test(user_id="user-1", tenant_id=tenant_id, query="我的饮食目标")['status'] == "no_results"
    store.engine.dispose()


def test_personal_same_source_name_isolated_by_owner(tmp_path: Path):
    store, service = _services(tmp_path)
    tenant_id = TenantService(store).create("user-1", "同一空间", "p2-3-same-source")["id"]
    store.add_or_update_member(tenant_id, user_id="user-2", role="member")

    first = service.import_text(
        user_id="user-1",
        tenant_id=tenant_id,
        source_name="plan.md",
        content="用户一的私有计划。",
    )
    second = service.import_text(
        user_id="user-2",
        tenant_id=tenant_id,
        source_name="plan.md",
        content="用户二的私有计划。",
    )
    assert first["document"]["id"] != second["document"]["id"]
    assert service.list_documents(user_id="user-1", tenant_id=tenant_id)[0]["owner_user_id"] == "user-1"
    assert service.list_documents(user_id="user-2", tenant_id=tenant_id)[0]["owner_user_id"] == "user-2"
    store.engine.dispose()


def test_offline_answer_has_explicit_contract(monkeypatch):
    monkeypatch.setattr("core.offline_answer.settings.zhipuai_api_key", None)
    monkeypatch.setattr("core.offline_answer.settings.openai_api_key", None)
    result = OfflineAnswerService().answer(
        operation="advice",
        request_intent={"domain": "nutrition", "goal": "weight_control"},
        current_goal="general",
        error=RuntimeError("model unavailable"),
    )
    assert result.to_dict() == {
        "mode": "offline",
        "reason": "llm_unavailable",
        "confidence": "medium",
        "next_step": "配置 ZHIPUAI_API_KEY 或 OPENAI_API_KEY 后可获得更完整的个性化回答。",
    }
    assert "kcal" not in result.answer.lower()


def test_migrations_reach_p2_3_head(tmp_path: Path, monkeypatch):
    database_url = f"sqlite:///{tmp_path / 'migration.db'}"
    monkeypatch.setattr("config.settings.database_url", database_url)
    alembic_config = Config(str(Path.cwd() / "alembic.ini"))
    command.upgrade(alembic_config, "head")

    store = ConversationStore(database_url=database_url, auto_create_schema=False)
    with store.session_factory() as session:
        from sqlalchemy import inspect

        inspector = inspect(session.bind)
        document_columns = {item["name"] for item in inspector.get_columns("knowledge_documents")}
        assert {"scope", "owner_user_id", "deleted_at"}.issubset(document_columns)
        assert "0010_p2_3_personal_knowledge" in {
            row[0] for row in session.connection().exec_driver_sql("SELECT version_num FROM alembic_version").all()
        }
    store.engine.dispose()
