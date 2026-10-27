import logging
from types import SimpleNamespace

import pytest
from prometheus_client import generate_latest

from config import settings
from core.logging_config import JsonFormatter
from core.observability import (
    bind_observation_context,
    get_observation_context,
    observation_fields,
    record_fallback,
    record_llm_call,
    record_rag_retrieval,
    record_tool_execution,
    reset_observation_context,
    start_span,
)
from core.tool_registry import ToolRegistry
from rag.retriever import get_retriever_with_score


def test_observation_context_and_json_log_correlation_fields():
    token = bind_observation_context(
        request_id="request-p07",
        trace_id="trace-p07",
        conversation_id="conversation-p07",
        user_id_hash="user-hash-p07",
        intent="meal_planner",
    )
    try:
        assert get_observation_context().trace_id == "trace-p07"
        assert observation_fields()["conversation_id"] == "conversation-p07"

        record = logging.LogRecord("p07-test", logging.INFO, __file__, 1, "workflow completed", (), None)
        rendered = JsonFormatter().format(record)
        assert '"request_id": "request-p07"' in rendered
        assert '"trace_id": "trace-p07"' in rendered
        assert '"conversation_id": "conversation-p07"' in rendered
        assert '"user_id_hash": "user-hash-p07"' in rendered
    finally:
        reset_observation_context(token)


def test_tool_registry_records_duration_and_parent_trace(caplog):
    logger = logging.getLogger("p07-tool-test")
    logger.setLevel(logging.INFO)
    logger.propagate = True
    registry = ToolRegistry(logger=logger)
    registry.register("observed", lambda query, context: "ok")

    with caplog.at_level(logging.INFO, logger="p07-tool-test"):
        result = registry.execute_result("observed", "query", {"trace_id": "parent-trace"})

    assert result.status == "success"
    assert result.duration_ms >= 0
    event = next(record for record in caplog.records if record.getMessage() == "tool_execution")
    assert event.event_data["trace_id"] == result.trace_id
    assert event.event_data["parent_trace_id"] == "parent-trace"
    registry.close()


def test_observability_metrics_do_not_use_request_ids_as_labels():
    record_tool_execution("observed-p07", "success", 12.0)
    record_llm_call("success", 0.01, model="test-model", input_tokens=11, output_tokens=7, cost=0.02)
    record_rag_retrieval("success", True, 0.02, 2)
    record_fallback("test-fallback")

    rendered = generate_latest().decode("utf-8")
    assert "eat_agent_tool_calls_total" in rendered
    assert "eat_agent_llm_tokens_total" in rendered
    assert "eat_agent_rag_requests_total" in rendered
    assert "eat_agent_fallbacks_total" in rendered
    assert "request_id" not in rendered
    assert "parent_trace" not in rendered


def test_rag_retriever_records_hit_and_returns_documents(monkeypatch):
    class FakeVectorStore:
        def similarity_search_with_score(self, query, k):
            return [(SimpleNamespace(page_content="nutrition"), 0.2), (SimpleNamespace(page_content="other"), 3.0)]

    monkeypatch.setattr("rag.retriever.get_or_create_vector_store", lambda: FakeVectorStore())
    docs = get_retriever_with_score(score_threshold=2.0)("safe query")

    assert len(docs) == 1
    assert docs[0].page_content == "nutrition"
    rendered = generate_latest().decode("utf-8")
    assert 'eat_agent_rag_requests_total{hit="true",status="success"}' in rendered


def test_otel_disabled_is_a_noop(monkeypatch):
    import core.observability as observability

    monkeypatch.setattr(settings, "otel_enabled", False)
    monkeypatch.setattr(observability, "_TRACING_INITIALIZED", True)
    monkeypatch.setattr(observability, "_TRACER", None)
    with start_span("p07.noop", {"safe.attribute": "value"}) as span:
        assert span is None


def test_llm_usage_helpers_accept_provider_response_shapes():
    from utils.llm import _estimate_cost, _response_usage

    response = SimpleNamespace(usage=SimpleNamespace(prompt_tokens=100, completion_tokens=25))
    assert _response_usage(response) == (100, 25)
    monkeypatch_values = (settings.llm_input_cost_per_1k, settings.llm_output_cost_per_1k)
    try:
        settings.llm_input_cost_per_1k = 1.0
        settings.llm_output_cost_per_1k = 2.0
        assert _estimate_cost(100, 25) == pytest.approx(0.15)
    finally:
        settings.llm_input_cost_per_1k, settings.llm_output_cost_per_1k = monkeypatch_values


def test_llm_call_records_provider_usage_without_prompt_content(monkeypatch):
    import utils.llm as llm_module

    class FakeCompletions:
        def create(self, **kwargs):
            assert "messages" in kwargs
            return SimpleNamespace(
                usage=SimpleNamespace(prompt_tokens=10, completion_tokens=4),
                choices=[SimpleNamespace(message=SimpleNamespace(content="answer"))],
            )

    class FakeClient:
        chat = SimpleNamespace(completions=FakeCompletions())

    monkeypatch.setattr(settings, "zhipuai_api_key", "test-key")
    monkeypatch.setattr(settings, "llm_input_cost_per_1k", 1.0)
    monkeypatch.setattr(settings, "llm_output_cost_per_1k", 2.0)
    monkeypatch.setattr(llm_module, "ZhipuAI", lambda api_key: FakeClient())

    answer = llm_module.CustomZhipuChat()._call("private prompt")

    assert answer == "answer"
    rendered = generate_latest().decode("utf-8")
    assert 'eat_agent_llm_tokens_total{direction="input",model="glm-4-flash"}' in rendered
    assert 'eat_agent_llm_tokens_total{direction="output",model="glm-4-flash"}' in rendered
    assert "private prompt" not in rendered
