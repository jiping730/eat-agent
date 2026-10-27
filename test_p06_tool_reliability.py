import logging
import time

from pydantic import BaseModel, Field

from config import settings
from core.tool_registry import ToolRegistry, ToolResult, build_default_tool_registry


def test_default_tools_expose_input_and_output_schemas():
    registry = build_default_tool_registry()

    assert {spec.name for spec in registry.specs} == {
        "retrieval_tool",
        "calorie_query",
        "meal_planner",
        "web_search",
    }
    for spec in registry.specs:
        assert spec.input_schema["type"] == "object"
        assert spec.output_schema["type"] == "object"
        assert spec.timeout_seconds > 0
        assert spec.max_attempts >= 1


def test_invalid_input_is_rejected_before_handler_runs():
    calls = []

    class InputModel(BaseModel):
        query: str = Field(min_length=3)

    registry = ToolRegistry()
    registry.register("validated", lambda query, context: calls.append(query) or "ok", input_model=InputModel)

    result = registry.execute_result("validated", "x")

    assert result.status == "validation_error"
    assert result.error_code == "invalid_tool_input"
    assert calls == []
    registry.close()


def test_permission_whitelist_blocks_disallowed_caller():
    calls = []
    registry = ToolRegistry()
    registry.register("internal", lambda query, context: calls.append(query) or "ok", allowed_callers={"workflow"})

    result = registry.execute_result("internal", "query", caller="mcp")

    assert result.status == "permission_denied"
    assert result.error_code == "tool_not_allowed"
    assert calls == []
    registry.close()


def test_timeout_returns_safe_status_without_exposing_exception():
    registry = ToolRegistry()
    registry.register(
        "slow",
        lambda query, context: time.sleep(0.05) or "too late",
        timeout_seconds=0.005,
        max_attempts=1,
    )

    result = registry.execute_result("slow", "query")

    assert result.status == "timeout"
    assert result.error_code == "tool_timeout"
    assert "Traceback" not in result.text
    registry.close()


def test_transient_failure_retries_with_attempt_count(monkeypatch):
    monkeypatch.setattr(settings, "tool_retry_base_delay_ms", 0)
    calls = []

    def flaky(query, context):
        calls.append(query)
        if len(calls) < 3:
            return ToolResult(status="tool_execution_failed", error_code="tool_transient_failure")
        return ToolResult(status="success", data="ok", sources=[{"type": "test", "source": "fixture"}])

    registry = ToolRegistry()
    registry.register("flaky", flaky, max_attempts=3)

    result = registry.execute_result("flaky", "query")

    assert result.status == "success"
    assert result.attempts == 3
    assert result.sources == [{"type": "test", "source": "fixture"}]
    registry.close()


def test_circuit_breaker_opens_after_repeated_failures(monkeypatch):
    monkeypatch.setattr(settings, "tool_circuit_failure_threshold", 2)
    monkeypatch.setattr(settings, "tool_retry_base_delay_ms", 0)
    registry = ToolRegistry()
    registry.register(
        "broken",
        lambda query, context: ToolResult(status="tool_execution_failed", error_code="upstream_unavailable"),
        max_attempts=1,
        retryable=False,
    )

    first = registry.execute_result("broken", "query")
    second = registry.execute_result("broken", "query")
    third = registry.execute_result("broken", "query")

    assert first.status == "tool_execution_failed"
    assert second.status == "tool_execution_failed"
    assert third.status == "circuit_open"
    assert registry.circuit_state("broken")["open"] is True
    registry.close()


def test_unknown_tool_has_trace_id_and_safe_text():
    registry = ToolRegistry()

    result = registry.execute_result("not_registered", "query")
    text = registry.execute("not_registered", "query")

    assert result.status == "tool_not_found"
    assert result.trace_id
    assert text == "当前功能暂时不可用。"
    registry.close()


def test_audit_event_contains_correlation_fields(caplog):
    logger = logging.getLogger("p06-audit-test")
    logger.setLevel(logging.INFO)
    logger.propagate = True
    registry = ToolRegistry(logger=logger)
    registry.register("audited", lambda query, context: "ok")

    with caplog.at_level(logging.INFO, logger="p06-audit-test"):
        result = registry.execute_result(
            "audited",
            "query",
            {"request_id": "request-1", "conversation_id": "conversation-1", "user_id": "user-1"},
        )

    assert result.status == "success"
    assert any("tool_execution" in record.getMessage() for record in caplog.records)
    assert any(getattr(record, "event_data", {}).get("trace_id") == result.trace_id for record in caplog.records)
    assert any(getattr(record, "event_data", {}).get("request_id") == "request-1" for record in caplog.records)
    registry.close()
