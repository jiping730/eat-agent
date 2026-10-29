import pytest

from core.persistence import ConversationStore
from core.conversation_runtime import ConversationRuntime


class FakeMemory:
    def __init__(self):
        self.saved = []

    def add_interaction(self, user_input, agent_output, user_id):
        self.saved.append((user_input, agent_output, user_id))


class RecordingWorkflow:
    def __init__(self, answer="已完成"):
        self.answer = answer
        self.calls = []

    def invoke(self, state, config):
        self.calls.append((state, config))
        return {
            **state,
            "messages": [*state["messages"], {"role": "assistant", "content": self.answer}],
            "grill_result": {"action": "execute", "target_field": None, "candidates": [], "assumptions": []},
            "tool_outputs": {"meal_planner": "ok"},
        }


def test_conversation_store_round_trip_and_idempotency(tmp_path):
    store = ConversationStore(database_url=f"sqlite:///{tmp_path / 'conversation.db'}")

    store.load("conversation-1", "user-1")
    store.save_turn(
        conversation_id="conversation-1",
        user_id="user-1",
        request_id="request-1",
        user_message="我想减肥",
        assistant_message="你想安排哪一餐？",
        grill_context={"intent": "meal_planner", "pending_field": "meal_type"},
        current_goal="meal_planner",
        response_type="clarification",
        target_field="meal_type",
    )
    store.save_turn(
        conversation_id="conversation-1",
        user_id="user-1",
        request_id="request-1",
        user_message="我想减肥",
        assistant_message="你想安排哪一餐？",
        grill_context={"intent": "meal_planner", "pending_field": "meal_type"},
        current_goal="meal_planner",
        response_type="clarification",
        target_field="meal_type",
    )

    snapshot = store.load("conversation-1", "user-1")
    assert snapshot.messages == [
        {"role": "user", "content": "我想减肥"},
        {"role": "assistant", "content": "你想安排哪一餐？"},
    ]
    assert snapshot.grill_context["pending_field"] == "meal_type"


def test_runtime_recovers_history_after_a_new_process(tmp_path):
    store = ConversationStore(database_url=f"sqlite:///{tmp_path / 'conversation.db'}")
    first_workflow = RecordingWorkflow(answer="你想安排哪一餐？")
    first_runtime = ConversationRuntime(workflow=first_workflow, memory_mgr=FakeMemory(), store=store)
    first_runtime.ask("我想减肥", user_id="user-1", conversation_id="conversation-1", request_id="request-1")

    second_workflow = RecordingWorkflow(answer="信息已补齐")
    second_runtime = ConversationRuntime(workflow=second_workflow, memory_mgr=FakeMemory(), store=store)
    response = second_runtime.ask("晚餐", user_id="user-1", conversation_id="conversation-1", request_id="request-2")

    assert response.answer == "信息已补齐"
    assert [message["content"] for message in second_workflow.calls[0][0]["messages"]] == [
        "我想减肥",
        "你想安排哪一餐？",
        "晚餐",
    ]
    assert second_workflow.calls[0][1] == {"configurable": {"thread_id": "conversation-1"}}


def test_conversation_cannot_be_read_by_another_user(tmp_path):
    store = ConversationStore(database_url=f"sqlite:///{tmp_path / 'conversation.db'}")
    store.load("conversation-1", "user-1")

    with pytest.raises(PermissionError):
        store.load("conversation-1", "user-2")
