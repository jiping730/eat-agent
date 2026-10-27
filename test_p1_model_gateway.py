from types import SimpleNamespace

import pytest

from config import settings
from core.contracts import ModelRouteRequest
from core.intent_router import classify_request_with_model
from utils.llm import InMemoryBudgetStore, ModelBudgetExceeded, ModelGateway


def _response(content="answer", input_tokens=12, output_tokens=5):
    return SimpleNamespace(
        usage=SimpleNamespace(prompt_tokens=input_tokens, completion_tokens=output_tokens),
        choices=[SimpleNamespace(message=SimpleNamespace(content=content))],
    )


def test_gateway_uses_low_cost_intent_route_and_extracts_usage(monkeypatch):
    calls = []

    def completion(**kwargs):
        calls.append(kwargs)
        return _response()

    monkeypatch.setattr(settings, "zhipuai_api_key", "test-key")
    monkeypatch.setattr(settings, "llm_intent_model", "glm-4-flash")
    monkeypatch.setattr(settings, "llm_max_tokens", 512)
    monkeypatch.setattr(settings, "llm_input_cost_per_1k", 1.0)
    monkeypatch.setattr(settings, "llm_output_cost_per_1k", 2.0)

    result = ModelGateway(completion_fn=completion).complete("请帮我查热量", task="intent", user_id="user-1")

    assert result.content == "answer"
    assert result.decision.model == "glm-4-flash"
    assert result.decision.route == "primary"
    assert result.usage.total_tokens == 17
    assert result.cost == pytest.approx(0.022)
    assert calls[0]["model"] == "openai/glm-4-flash"
    assert calls[0]["max_tokens"] == 512


def test_gateway_retries_primary_then_switches_to_configured_fallback(monkeypatch):
    calls = []

    def completion(**kwargs):
        calls.append(kwargs["model"])
        if len(calls) < 3:
            raise TimeoutError("upstream timeout")
        return _response("fallback-answer")

    monkeypatch.setattr(settings, "zhipuai_api_key", "test-key")
    monkeypatch.setattr(settings, "llm_fallback_models", "glm-4-air")
    monkeypatch.setattr(settings, "llm_max_attempts", 2)
    monkeypatch.setattr(settings, "llm_retry_base_delay_ms", 0)

    result = ModelGateway(completion_fn=completion, sleep_fn=lambda _: None).complete("复杂问题")

    assert result.content == "fallback-answer"
    assert result.decision.route == "fallback"
    assert result.decision.fallback_used is True
    assert calls == ["openai/glm-4-flash", "openai/glm-4-flash", "openai/glm-4-air"]


def test_gateway_enforces_daily_token_budget_before_call(monkeypatch):
    called = False

    def completion(**_kwargs):
        nonlocal called
        called = True
        return _response()

    monkeypatch.setattr(settings, "zhipuai_api_key", "test-key")
    monkeypatch.setattr(settings, "llm_user_daily_token_limit", 5)
    monkeypatch.setattr(settings, "llm_max_tokens", 8)
    request = ModelRouteRequest(task="answer", max_tokens=8)

    with pytest.raises(ModelBudgetExceeded):
        ModelGateway(completion_fn=completion, budget_store=InMemoryBudgetStore()).complete(
            "预算测试", request, user_id="user-budget"
        )

    assert called is False


def test_uncertain_intent_can_use_gateway_json_and_invalid_output_falls_back(monkeypatch):
    monkeypatch.setattr(settings, "zhipuai_api_key", "test-key")
    monkeypatch.setattr(settings, "llm_intent_enabled", True)
    monkeypatch.setattr(settings, "llm_intent_min_confidence", 0.8)

    class FakeGateway:
        available = True

        def complete(self, prompt, *, task, user_id):
            assert task == "intent"
            assert user_id == "user-intent"
            return SimpleNamespace(
                content='{"domain":"general","operation":"advice","task":null,"goal":"improve_sleep",'
                '"entities":{},"slots":{},"confidence":0.91,"continuation":false}'
            )

    result = classify_request_with_model("最近状态有点差", user_id="user-intent", gateway=FakeGateway())
    assert result.operation == "advice"
    assert result.goal == "improve_sleep"

    class InvalidGateway(FakeGateway):
        def complete(self, prompt, *, task, user_id):
            return SimpleNamespace(content="not-json")

    fallback = classify_request_with_model("最近状态有点差", user_id="user-intent", gateway=InvalidGateway())
    assert fallback.operation == "answer"
