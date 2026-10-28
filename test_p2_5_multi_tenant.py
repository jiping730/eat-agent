from pathlib import Path

import pytest

from core.knowledge_base import KnowledgeBaseService
from core.persistence import ConversationStore
from core.profile import ProfileService, UserProfileUpdate
from core.tenant import TenantAccessError, TenantService
from utils.llm import GatewayLLM, ModelGateway


def _store(tmp_path: Path) -> ConversationStore:
    return ConversationStore(database_url=f"sqlite:///{tmp_path / 'tenant.db'}")


def test_tenant_roles_and_cross_tenant_access_are_isolated(tmp_path: Path):
    store = _store(tmp_path)
    service = TenantService(store)
    tenant_a = service.create("user-1", "家庭空间", "family-space")
    tenant_b = service.create("user-1", "工作空间", "work-space")
    store.add_or_update_member(tenant_b["id"], user_id="user-2", role="member")

    assert service.require_role("user-1", tenant_a["id"], {"owner"}).role == "owner"
    assert service.require_member("user-2", tenant_b["id"]).role == "member"
    with pytest.raises(TenantAccessError):
        service.require_member("user-2", tenant_a["id"])

    store.create_conversation(
        conversation_id="conversation-a", user_id="user-1", tenant_id=tenant_a["id"], title="A"
    )
    store.create_conversation(
        conversation_id="conversation-b", user_id="user-1", tenant_id=tenant_b["id"], title="B"
    )
    assert store.load("conversation-a", "user-1", tenant_id=tenant_a["id"]).title == "A"
    assert store.load("conversation-b", "user-1", tenant_id=tenant_b["id"]).title == "B"
    with pytest.raises(PermissionError):
        store.load("conversation-a", "user-1", tenant_id=tenant_b["id"])
    store.engine.dispose()


def test_profile_and_memory_are_scoped_by_tenant(tmp_path: Path):
    store = _store(tmp_path)
    first = store.get_or_create_personal_tenant("user-1")
    second = TenantService(store).create("user-1", "第二空间", "second-space")["id"]
    profiles = ProfileService(store)

    profiles.update(
        "user-1",
        UserProfileUpdate(health_goal="weight_control", consent_granted=True),
        tenant_id=first,
    )
    profiles.update(
        "user-1",
        UserProfileUpdate(health_goal="muscle_gain", consent_granted=True),
        tenant_id=second,
    )
    assert profiles.get("user-1", first)["profile"]["health_goal"] == "weight_control"
    assert profiles.get("user-1", second)["profile"]["health_goal"] == "muscle_gain"

    store.set_memory_consent("user-1", True, first)
    store.save_memory(
        user_id="user-1",
        tenant_id=first,
        user_input="A",
        assistant_output="A answer",
    )
    assert len(store.list_memory("user-1", tenant_id=first)) == 1
    assert store.list_memory("user-1", tenant_id=second) == []
    store.engine.dispose()


def test_knowledge_documents_allow_same_source_in_different_tenants(tmp_path: Path):
    store = _store(tmp_path)
    tenant_service = TenantService(store)
    first = tenant_service.create("user-1", "A", "tenant-a")["id"]
    second = tenant_service.create("user-1", "B", "tenant-b")["id"]
    service = KnowledgeBaseService(store, index_dir=str(tmp_path / "indexes"))

    service.upload_document(
        source_name="guide.md", content="A 内容", actor="user-1", tenant_id=first
    )
    service.upload_document(
        source_name="guide.md", content="B 内容", actor="user-1", tenant_id=second
    )
    assert service.list_documents(tenant_id=first)[0]["tenant_id"] == first
    assert service.list_documents(tenant_id=second)[0]["tenant_id"] == second
    first_id = service.list_documents(tenant_id=first)[0]["id"]
    second_id = service.list_documents(tenant_id=second)[0]["id"]
    assert service.get_document(first_id, first)["versions"][0]["content"] == "A 内容"
    assert service.get_document(second_id, second)["versions"][0]["content"] == "B 内容"
    store.engine.dispose()


def test_tenant_settings_can_select_model_for_gateway(monkeypatch):
    calls: list[dict] = []

    def completion(**kwargs):
        calls.append(kwargs)
        return {
            "choices": [{"message": {"content": "ok"}}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1},
        }

    monkeypatch.setattr("utils.llm.settings.zhipuai_api_key", "test-key")
    monkeypatch.setattr("utils.llm.settings.llm_max_attempts", 1)
    gateway = ModelGateway(completion_fn=completion)
    llm = GatewayLLM(gateway, task="answer", user_id="user-1", preferred_model="glm-4-air")

    assert llm.invoke("hello") == "ok"
    assert calls[0]["model"] == "openai/glm-4-air"

