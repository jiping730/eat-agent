"""LLM adapter with provider-agnostic observability and safe fallbacks."""

from __future__ import annotations

import time
from collections.abc import Mapping
from typing import Any, List, Optional

from langchain.llms.base import LLM
from zhipuai import ZhipuAI

from config import settings
from core.observability import record_fallback, record_langfuse_trace, record_llm_call, start_span


def _usage_value(usage: Any, *names: str) -> int | None:
    """Read provider usage fields without assuming a concrete SDK response type."""

    if usage is None:
        return None
    for name in names:
        value = usage.get(name) if isinstance(usage, Mapping) else getattr(usage, name, None)
        if isinstance(value, int) and not isinstance(value, bool):
            return max(0, value)
        if isinstance(value, float) and value.is_integer():
            return max(0, int(value))
    return None


def _response_usage(response: Any) -> tuple[int | None, int | None]:
    usage = response.get("usage") if isinstance(response, Mapping) else getattr(response, "usage", None)
    return (
        _usage_value(usage, "prompt_tokens", "input_tokens"),
        _usage_value(usage, "completion_tokens", "output_tokens"),
    )


def _estimate_cost(input_tokens: int | None, output_tokens: int | None) -> float | None:
    if input_tokens is None and output_tokens is None:
        return None
    input_cost = (input_tokens or 0) / 1000 * settings.llm_input_cost_per_1k
    output_cost = (output_tokens or 0) / 1000 * settings.llm_output_cost_per_1k
    return input_cost + output_cost


class CustomZhipuChat(LLM):
    def __init__(self):
        super().__init__()
        # Bypass Pydantic field validation for the SDK client.
        object.__setattr__(self, "client", ZhipuAI(api_key=settings.zhipuai_api_key))
        object.__setattr__(self, "model", settings.llm_model)
        object.__setattr__(self, "temperature", 0.7)

    @property
    def _llm_type(self) -> str:
        return "zhipuai"

    def _call(self, prompt: str, stop: Optional[List[str]] = None, **kwargs) -> str:
        started_at = time.perf_counter()
        model = str(self.model)
        if not settings.zhipuai_api_key:
            elapsed = time.perf_counter() - started_at
            record_llm_call("fallback", elapsed, model=model)
            record_fallback("llm_unavailable")
            raise RuntimeError("ZHIPUAI_API_KEY is not configured")

        try:
            with start_span(
                "llm.call",
                {
                    "llm.model": model,
                    "llm.prompt_length": len(prompt),
                },
            ):
                response = self.client.chat.completions.create(
                    model=self.model,
                    messages=[{"role": "user", "content": prompt}],
                    temperature=self.temperature,
                    timeout=30.0,
                )

            input_tokens, output_tokens = _response_usage(response)
            answer = response.choices[0].message.content
            cost = _estimate_cost(input_tokens, output_tokens)
            elapsed = time.perf_counter() - started_at
            record_llm_call(
                "success",
                elapsed,
                model=model,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                cost=cost,
            )
            record_langfuse_trace(
                "llm.call",
                metadata={
                    "model": model,
                    "outcome": "success",
                    "input_tokens": input_tokens,
                    "output_tokens": output_tokens,
                    "cost": cost,
                },
            )
            return str(answer or "")
        except Exception as exc:
            elapsed = time.perf_counter() - started_at
            record_llm_call("failure", elapsed, model=model)
            record_langfuse_trace(
                "llm.call",
                metadata={"model": model, "outcome": "failure", "error_type": type(exc).__name__},
            )
            raise RuntimeError("LLM request failed") from exc


def get_llm():
    return CustomZhipuChat()
