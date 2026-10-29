import json

from fastapi.testclient import TestClient

from config import settings
from core.conversation_runtime import ConversationRuntime
from core.persistence import ConversationStore
from core.streaming import StreamCancelled, StreamEmitter
from front import app as front_app
from utils.llm import InMemoryBudgetStore, ModelGateway


def _response_chunks(*parts: str):
    return [{"choices": [{"delta": {"content": part}}]} for part in parts] + [
        {"choices": [{"delta": {}}], "usage": {"prompt_tokens": 4, "completion_tokens": len("".join(parts))}}
    ]


def _parse_sse(payload: str) -> list[dict]:
    events = []
    for frame in payload.strip().split("\n\n"):
        data_line = next(line for line in frame.splitlines() if line.startswith("data: "))
        events.append(json.loads(data_line[6:]))
    return events


def test_stream_emitter_orders_events_and_honors_cancellation():
    emitter = StreamEmitter(request_id="request-1", conversation_id="conversation-1")
    first = emitter.emit("conversation.started", {"status": "started"})
    second = emitter.emit("conversation.completed", {"status": "completed"})

    assert first.sequence == 0
    assert second.sequence == 1
    assert first.to_sse().startswith("event: conversation.started\n")

    emitter.cancel_event.set()
    try:
        emitter.emit("model.started")
    except StreamCancelled:
        pass
    else:  # pragma: no cover - defensive assertion for the cancellation contract.
        raise AssertionError("cancelled stream emitted a new event")


def test_model_gateway_streams_deltas_and_settles_budget(monkeypatch):
    calls = []

    def completion(**kwargs):
        calls.append(kwargs)
        return iter(_response_chunks("你好", "，世界"))

    monkeypatch.setattr(settings, "zhipuai_api_key", "test-key")
    monkeypatch.setattr(settings, "llm_max_attempts", 1)
    gateway = ModelGateway(completion_fn=completion, budget_store=InMemoryBudgetStore())

    chunks = list(gateway.stream("请回答", task="answer", user_id="user-1"))

    assert chunks == ["你好", "，世界"]
    assert calls[0]["stream"] is True
    assert gateway.budget_store.snapshot("user-1")["tokens"] == 9


class FakeMemory:
    def add_interaction(self, *_args, **_kwargs):
        return None


class StreamingWorkflow:
    def invoke(self, state, config=None):
        emit = state.get("stream_emit")
        if emit:
            emit("model.started", {"stage": "answer"})
            emit("model.delta", {"stage": "answer", "delta": "流式回答"})
        return {
            **state,
            "messages": [*state["messages"], {"role": "assistant", "content": "流式回答"}],
            "grill_result": {"action": "execute", "target_field": None, "candidates": [], "assumptions": []},
            "tool_outputs": {},
        }


def test_runtime_stream_persists_final_response_and_emits_completion(tmp_path):
    store = ConversationStore(database_url=f"sqlite:///{tmp_path / 'stream.db'}")
    runtime = ConversationRuntime(workflow=StreamingWorkflow(), memory_mgr=FakeMemory(), store=store)

    events = _parse_sse("".join(runtime.ask_stream("你好", user_id="user-1", conversation_id="conversation-1")))

    assert [event["event"] for event in events] == [
        "conversation.started",
        "model.started",
        "model.delta",
        "answer.completed",
        "conversation.completed",
    ]
    assert [event["sequence"] for event in events] == list(range(len(events)))
    assert events[-2]["data"]["answer"] == "流式回答"
    assert events[-2]["data"]["message_id"]
    assert [message["content"] for message in store.load("conversation-1", "user-1").messages] == ["你好", "流式回答"]


def test_feedback_and_regenerate_do_not_duplicate_user_message(tmp_path):
    store = ConversationStore(database_url=f"sqlite:///{tmp_path / 'feedback.db'}")
    runtime = ConversationRuntime(workflow=StreamingWorkflow(), memory_mgr=FakeMemory(), store=store)
    first = runtime.ask("你好", user_id="user-1", conversation_id="conversation-1", request_id="request-1")

    feedback = store.save_feedback(message_id=first.message_id, user_id="user-1", rating="up")
    regenerated = runtime.regenerate(user_id="user-1", conversation_id="conversation-1", request_id="request-2")
    messages = store.load("conversation-1", "user-1", include_metadata=True).messages

    assert feedback.rating == "up"
    assert regenerated.answer == "流式回答"
    assert [message["role"] for message in messages] == ["user", "assistant", "assistant"]
    assert [message["content"] for message in messages].count("你好") == 1


def test_stream_api_returns_sse_and_keeps_existing_ask_contract(monkeypatch):
    class FakeRuntime:
        def ask_stream(self, question, **_kwargs):
            yield StreamEmitter(request_id="request-1", conversation_id="conversation-1").emit_sse(
                "conversation.started", {"question": question}
            )

    monkeypatch.setattr(settings, "auth_mode", "auto")
    monkeypatch.setattr(settings, "app_api_key", None)
    monkeypatch.setattr(settings, "jwt_secret", None)
    monkeypatch.setattr(front_app, "runtime", FakeRuntime())
    client = TestClient(front_app.app)

    response = client.post("/ask/stream", headers={"X-User-ID": "user-1"}, json={"question": "你好"})

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert _parse_sse(response.text)[0]["event"] == "conversation.started"
