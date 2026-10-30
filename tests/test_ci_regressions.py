from __future__ import annotations

import json

import pytest

from core.conversation_runtime import ConversationRuntime
from core.intent_router import RequestIntent
from core.persistence import ConversationStore
from core.tool_registry import ToolResult
from core.workflow import create_workflow


class MemoryStub:
    def retrieve_relevant_memories(self, query, user_id=None):
        return []

    def save_meta(self, user_input, agent_output, score, user_id=None):
        return None

    def add_interaction(self, user_input, agent_output, user_id, tenant_id=None):
        return None


def workflow_state(question: str) -> dict:
    return {
        "messages": [{"role": "user", "content": question}],
        "user_id": "ci-regression-user",
        "tenant_id": "default",
        "tenant_settings": {},
        "memory_context": [],
        "user_profile": {},
        "current_goal": "",
        "current_operation": "answer",
        "request_intent": {},
        "plan": [],
        "tool_outputs": {},
        "reflection": "",
        "iteration": 0,
        "followup": False,
        "grill_context": {},
        "grill_result": {},
        "tool_results": {},
        "tool_sources": {},
        "request_id": "ci-regression-request",
        "conversation_id": "ci-regression-conversation",
        "trace_id": "ci-regression-trace",
        "tool_failures": [],
        "safety": {},
    }


def test_workflow_falls_back_to_offline_answer_when_model_is_unavailable(monkeypatch):
    monkeypatch.setattr(
        "core.workflow.classify_request_with_model",
        lambda *_args, **_kwargs: RequestIntent(domain="general", operation="answer"),
    )

    def unavailable_model(*_args, **_kwargs):
        raise RuntimeError("model unavailable")

    monkeypatch.setattr("core.workflow.get_llm", unavailable_model)
    result = create_workflow(memory_mgr=MemoryStub()).invoke(workflow_state("请给我一个通用建议"))

    assert result["answer_mode"] == "offline"
    assert result["answer_reason"]
    assert result["tool_sources"]["offline_fallback"]
    assert result["messages"][-1]["role"] == "assistant"


class FailedToolRegistry:
    def execute_result(self, *_args, **_kwargs):
        return ToolResult(status="tool_execution_failed", error_code="upstream_unavailable")


def test_workflow_turns_tool_failure_into_safe_answer(monkeypatch):
    monkeypatch.setattr(
        "core.workflow.classify_request_with_model",
        lambda *_args, **_kwargs: RequestIntent(
            domain="nutrition",
            operation="lookup",
            task="calorie_query",
            entities={"topic": "calorie"},
        ),
    )
    result = create_workflow(
        memory_mgr=MemoryStub(),
        tool_registry=FailedToolRegistry(),
    ).invoke(workflow_state("苹果多少热量"))

    assert result["tool_failures"][-1]["error_code"] == "upstream_unavailable"
    assert result["messages"][-1]["role"] == "assistant"
    assert "工具" in result["messages"][-1]["content"]


class RaisingWorkflow:
    def invoke(self, *_args, **_kwargs):
        raise RuntimeError("workflow failed")


class CancelledWorkflow:
    def invoke(self, state, _config):
        state["cancel_event"].set()
        state["stream_emit"]("model.started", {"stage": "answer"})
        return state


def test_runtime_does_not_persist_when_workflow_fails(tmp_path):
    store = ConversationStore(database_url=f"sqlite:///{tmp_path / 'runtime-error.db'}")
    runtime = ConversationRuntime(workflow=RaisingWorkflow(), memory_mgr=MemoryStub(), store=store)

    with pytest.raises(RuntimeError, match="workflow failed"):
        runtime.ask("你好", user_id="error-user", conversation_id="error-conversation")

    assert store.load("error-conversation", "error-user").messages == []


def test_stream_reports_cancellation_from_workflow(tmp_path):
    store = ConversationStore(database_url=f"sqlite:///{tmp_path / 'stream-cancel.db'}")
    runtime = ConversationRuntime(workflow=CancelledWorkflow(), memory_mgr=MemoryStub(), store=store)

    events = list(runtime.ask_stream("你好", user_id="cancel-user", conversation_id="cancel-conversation"))
    payloads = [
        json.loads(line[6:])
        for event in events
        for line in event.splitlines()
        if line.startswith("data: ")
    ]

    assert any(payload["event"] == "conversation.started" for payload in payloads)
    assert any(payload["data"].get("code") == "cancelled" for payload in payloads)
