from core.auth import AuthService
from core.conversation_runtime import ConversationRuntime
from core.persistence import ConversationStore


class FakeMemory:
    def add_interaction(self, user_input, agent_output, user_id):
        return None


class RecordingWorkflow:
    def __init__(self):
        self.calls = 0

    def invoke(self, state, config):
        self.calls += 1
        return {
            **state,
            "messages": [*state["messages"], {"role": "assistant", "content": "你想安排哪一餐？"}],
            "grill_result": {
                "action": "clarify",
                "target_field": "meal_type",
                "candidates": [],
                "assumptions": [],
            },
        }


def test_jwt_auth_round_trip(monkeypatch):
    from config import settings

    monkeypatch.setattr(settings, "jwt_secret", "test-secret")
    monkeypatch.setattr(settings, "jwt_issuer", "test-issuer")
    service = AuthService()

    tokens = service.issue_tokens("user-1", ("user",))
    principal = service.decode_access_token(tokens.access_token)

    assert principal.user_id == "user-1"
    assert principal.roles == ("user",)
    assert service.verify_password(service.hash_password("password-123"), "password-123")


def test_idempotency_avoids_duplicate_workflow_calls(tmp_path):
    store = ConversationStore(database_url=f"sqlite:///{tmp_path / 'conversation.db'}")
    workflow = RecordingWorkflow()
    runtime = ConversationRuntime(workflow=workflow, memory_mgr=FakeMemory(), store=store)

    first = runtime.ask(
        "我想减肥",
        user_id="user-1",
        conversation_id="conversation-1",
        request_id="request-1",
    )
    second = runtime.ask(
        "我想减肥",
        user_id="user-1",
        conversation_id="conversation-1",
        request_id="request-1",
    )

    assert workflow.calls == 1
    assert first.to_dict() == second.to_dict()


def test_conversation_listing_and_archiving_are_user_scoped(tmp_path):
    store = ConversationStore(database_url=f"sqlite:///{tmp_path / 'conversation.db'}")
    store.create_conversation(conversation_id="conversation-1", user_id="user-1", title="早餐计划")
    store.create_conversation(conversation_id="conversation-2", user_id="user-2", title="晚餐计划")

    assert [item.id for item in store.list_conversations("user-1")] == ["conversation-1"]
    store.archive_conversation("conversation-1", "user-1")
    assert store.list_conversations("user-1") == []
