from datetime import timedelta

from fastapi.testclient import TestClient

from core.persistence import ConversationStore, utc_now
from core.tool_registry import build_default_tool_registry


def test_tool_registry_exposes_one_canonical_boundary():
    registry = build_default_tool_registry()

    assert {spec.name for spec in registry.specs} == {
        "retrieval_tool",
        "calorie_query",
        "meal_planner",
        "web_search",
    }
    result = registry.execute_result("meal_planner", "晚餐", {"fields": {"meal_type": "dinner"}})
    assert result.status == "success"
    assert result.trace_id
    assert result.data.startswith("餐食规划参数已确认")


def test_conversation_expiry_and_permanent_delete(tmp_path, monkeypatch):
    from config import settings

    monkeypatch.setattr(settings, "conversation_ttl_days", 30)
    store = ConversationStore(database_url=f"sqlite:///{tmp_path / 'conversation.db'}")
    conversation = store.create_conversation(conversation_id="conversation-1", user_id="user-1")

    assert conversation.expires_at > utc_now() + timedelta(days=29)
    assert len(store.list_conversations("user-1")) == 1

    store.delete_conversation("conversation-1", "user-1")
    assert store.list_conversations("user-1") == []


def test_fastapi_has_typed_health_and_validation_error_contract(monkeypatch):
    from config import settings
    from front import app as front_app

    monkeypatch.setattr(settings, "auth_mode", "auto")
    monkeypatch.setattr(settings, "app_api_key", None)
    monkeypatch.setattr(settings, "jwt_secret", None)
    client = TestClient(front_app.app)

    live = client.get("/health/live")
    assert live.status_code == 200
    assert live.json()["status"] == "ok"

    invalid = client.post("/ask", json={})
    assert invalid.status_code == 422
    assert invalid.json()["error_code"] == "validation_error"
    assert invalid.json()["request_id"]
