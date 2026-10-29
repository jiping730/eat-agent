"""LLM adapter with provider-agnostic observability and safe fallbacks."""

from __future__ import annotations

import threading
import time
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, List, Literal, Optional

from langchain.llms.base import LLM
from langchain_core.callbacks.manager import CallbackManagerForLLMRun
from zhipuai import ZhipuAI

from config import settings
from core.contracts import ModelRouteDecision, ModelRouteRequest
from core.logging_config import configure_logging, fingerprint, log_event
from core.observability import (
    record_fallback,
    record_langfuse_trace,
    record_llm_call,
    record_model_route,
    start_span,
)
from core.streaming import StreamCancelled

try:
    from litellm import completion as litellm_completion
except ImportError:  # pragma: no cover - the production dependency is installed from pyproject.toml.
    litellm_completion = None


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

    def _call(
        self,
        prompt: str,
        stop: Optional[List[str]] = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> str:
        started_at = time.perf_counter()
        model = str(self.model)  # type: ignore[attr-defined]
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
                response = self.client.chat.completions.create(  # type: ignore[attr-defined]
                    model=self.model,  # type: ignore[attr-defined]
                    messages=[{"role": "user", "content": prompt}],
                    temperature=self.temperature,  # type: ignore[attr-defined]
                    timeout=settings.llm_timeout_seconds,
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


class ModelGatewayError(RuntimeError):
    """Base error for safe model gateway failures."""


class ModelUnavailable(ModelGatewayError):
    """Raised when no configured provider can serve the request."""


class ModelBudgetExceeded(ModelGatewayError):
    """Raised before a call when the user budget would be exceeded."""


@dataclass(frozen=True)
class ModelUsage:
    input_tokens: int | None = None
    output_tokens: int | None = None

    @property
    def total_tokens(self) -> int | None:
        if self.input_tokens is None and self.output_tokens is None:
            return None
        return (self.input_tokens or 0) + (self.output_tokens or 0)


@dataclass(frozen=True)
class GatewayResponse:
    content: str
    usage: ModelUsage
    cost: float | None
    decision: ModelRouteDecision


@dataclass(frozen=True)
class _BudgetReservation:
    key: tuple[str, str]
    tokens: int
    cost: float


class InMemoryBudgetStore:
    """Thread-safe daily token/cost ledger for the small-platform deployment."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._usage: dict[tuple[str, str], tuple[int, float]] = {}

    @staticmethod
    def _key(user_id: str) -> tuple[str, str]:
        day = datetime.now(timezone.utc).date().isoformat()
        return fingerprint(user_id or "anonymous") or "anonymous", day

    def reserve(self, user_id: str, tokens: int, cost: float) -> _BudgetReservation:
        key = self._key(user_id)
        with self._lock:
            current_tokens, current_cost = self._usage.get(key, (0, 0.0))
            token_limit = settings.llm_user_daily_token_limit
            cost_limit = settings.llm_user_daily_cost_limit
            if token_limit > 0 and current_tokens + tokens > token_limit:
                raise ModelBudgetExceeded("用户今日 Token 预算已用尽")
            if cost_limit > 0 and current_cost + cost > cost_limit:
                raise ModelBudgetExceeded("用户今日费用预算已用尽")
            self._usage[key] = (current_tokens + tokens, current_cost + cost)
        return _BudgetReservation(key=key, tokens=tokens, cost=cost)

    def settle(self, reservation: _BudgetReservation, tokens: int, cost: float) -> None:
        with self._lock:
            current_tokens, current_cost = self._usage.get(reservation.key, (0, 0.0))
            self._usage[reservation.key] = (
                max(0, current_tokens - reservation.tokens + max(0, tokens)),
                max(0.0, current_cost - reservation.cost + max(0.0, cost)),
            )

    def release(self, reservation: _BudgetReservation) -> None:
        with self._lock:
            current_tokens, current_cost = self._usage.get(reservation.key, (0, 0.0))
            self._usage[reservation.key] = (
                max(0, current_tokens - reservation.tokens),
                max(0.0, current_cost - reservation.cost),
            )

    def snapshot(self, user_id: str) -> dict[str, float | int]:
        with self._lock:
            tokens, cost = self._usage.get(self._key(user_id), (0, 0.0))
        return {"tokens": tokens, "cost": cost}


_DEFAULT_BUDGET_STORE = InMemoryBudgetStore()


@dataclass(frozen=True)
class _RouteCandidate:
    provider: str
    model: str
    route: Literal["primary", "fallback"]


class ModelGateway:
    """LiteLLM-backed model gateway with routing, retry, budget, and audit controls."""

    def __init__(
        self,
        *,
        completion_fn: Callable[..., Any] | None = None,
        budget_store: InMemoryBudgetStore | None = None,
        sleep_fn: Callable[[float], None] = time.sleep,
    ) -> None:
        self.completion_fn = completion_fn
        self.budget_store = budget_store or _DEFAULT_BUDGET_STORE
        self.sleep_fn = sleep_fn
        self.logger = configure_logging(settings.log_level)

    @property
    def available(self) -> bool:
        return bool(settings.zhipuai_api_key or settings.openai_api_key or settings.anthropic_api_key)

    @staticmethod
    def build_request(
        task: str,
        *,
        preferred_model: str | None = None,
        fallback_models: list[str] | None = None,
        max_tokens: int | None = None,
        timeout_seconds: float | None = None,
        temperature: float = 0.2,
    ) -> ModelRouteRequest:
        return ModelRouteRequest(
            task=task,
            preferred_model=preferred_model,
            fallback_models=fallback_models or [],
            max_tokens=max_tokens or settings.llm_max_tokens,
            timeout_seconds=timeout_seconds or settings.llm_timeout_seconds,
            temperature=temperature,
        )

    @staticmethod
    def _split_model(value: str, default_provider: str) -> tuple[str, str]:
        provider, separator, model = value.partition("/")
        if separator and provider in {"zhipuai", "zhipu", "openai", "deepseek", "anthropic"}:
            return str(provider), str(model)
        return str(default_provider), str(value)

    def _candidates(self, request: ModelRouteRequest) -> list[_RouteCandidate]:
        primary_provider = settings.llm_primary_provider.strip().lower() or "zhipuai"
        configured_primary = (
            settings.llm_intent_model if request.task == "intent" else (settings.llm_answer_model or settings.llm_model)
        )
        primary_model = request.preferred_model or configured_primary
        provider, model = self._split_model(primary_model, primary_provider)
        candidates = [_RouteCandidate(provider=provider, model=model, route="primary")]

        configured_fallbacks = [item.strip() for item in settings.llm_fallback_models.split(",") if item.strip()]
        fallback_values = request.fallback_models or configured_fallbacks
        fallback_provider = settings.llm_fallback_provider.strip().lower() or primary_provider
        seen = {(provider, model)}
        for value in fallback_values[:8]:
            fallback_provider_value, fallback_model = self._split_model(value, fallback_provider)
            if (fallback_provider_value, fallback_model) in seen:
                continue
            seen.add((fallback_provider_value, fallback_model))
            candidates.append(_RouteCandidate(provider=fallback_provider_value, model=fallback_model, route="fallback"))
        return candidates

    @staticmethod
    def _provider_kwargs(provider: str, model: str) -> dict[str, Any]:
        normalized_provider = provider.lower()
        if normalized_provider in {"zhipuai", "zhipu"}:
            if not settings.zhipuai_api_key:
                raise ModelUnavailable("主模型未配置 API Key")
            call_model = model if "/" in model else f"openai/{model}"
            return {
                "model": call_model,
                "api_key": settings.zhipuai_api_key,
                "api_base": settings.llm_api_base,
            }
        if normalized_provider == "openai":
            if not settings.openai_api_key:
                raise ModelUnavailable("备用模型未配置 API Key")
            call_model = model if "/" in model else f"openai/{model}"
            return {
                "model": call_model,
                "api_key": settings.openai_api_key,
                "api_base": settings.openai_api_base,
            }
        if normalized_provider == "anthropic":
            if not settings.anthropic_api_key:
                raise ModelUnavailable("Anthropic 兼容中转站未配置 API Key")
            call_model = model if "/" in model else f"anthropic/{model}"
            return {
                "model": call_model,
                "api_key": settings.anthropic_api_key,
                "api_base": settings.anthropic_api_base,
            }
        raise ModelUnavailable("当前模型提供商未配置")

    @staticmethod
    def _content(response: Any) -> str:
        choices = response.get("choices") if isinstance(response, Mapping) else getattr(response, "choices", None)
        if not choices:
            return ""
        first = choices[0]
        message = first.get("message") if isinstance(first, Mapping) else getattr(first, "message", None)
        content = message.get("content") if isinstance(message, Mapping) else getattr(message, "content", "")
        if isinstance(content, list):
            return "".join(
                str(item.get("text", "")) if isinstance(item, Mapping) else str(getattr(item, "text", ""))
                for item in content
            )
        return str(content or "")

    @staticmethod
    def _delta_content(response: Any) -> str:
        choices = response.get("choices") if isinstance(response, Mapping) else getattr(response, "choices", None)
        if not choices:
            return ""
        first = choices[0]
        delta = first.get("delta") if isinstance(first, Mapping) else getattr(first, "delta", None)
        content = delta.get("content") if isinstance(delta, Mapping) else getattr(delta, "content", "")
        if isinstance(content, list):
            return "".join(
                str(item.get("text", "")) if isinstance(item, Mapping) else str(getattr(item, "text", ""))
                for item in content
            )
        return str(content or "")

    def _completion(self) -> Callable[..., Any]:
        completion = self.completion_fn or litellm_completion
        if completion is None:
            raise ModelUnavailable("LiteLLM 未安装")
        return completion

    def _reservation(self, user_id: str, prompt: str, max_tokens: int) -> _BudgetReservation:
        estimated_input = max(1, len(prompt) // 4)
        reserved_tokens = estimated_input + max_tokens
        reserved_cost = _estimate_cost(estimated_input, max_tokens) or 0.0
        return self.budget_store.reserve(user_id, reserved_tokens, reserved_cost)

    def complete(
        self,
        prompt: str,
        request: ModelRouteRequest | None = None,
        *,
        task: str = "answer",
        user_id: str | None = None,
    ) -> GatewayResponse:
        if not isinstance(prompt, str) or not prompt.strip():
            raise ValueError("prompt 不能为空")
        resolved_request = request or self.build_request(task)
        max_tokens = min(resolved_request.max_tokens, settings.llm_max_tokens)
        timeout_seconds = min(resolved_request.timeout_seconds, settings.llm_timeout_seconds)
        candidates = self._candidates(resolved_request)
        completion = self._completion()
        last_error: Exception | None = None
        resolved_user_id = user_id or "anonymous"

        for candidate in candidates:
            for attempt in range(1, settings.llm_max_attempts + 1):
                reservation: _BudgetReservation | None = None
                started_at = time.perf_counter()
                try:
                    reservation = self._reservation(resolved_user_id, prompt, max_tokens)
                    call_kwargs = self._provider_kwargs(candidate.provider, candidate.model)
                    call_kwargs.update(
                        {
                            "messages": [{"role": "user", "content": prompt}],
                            "temperature": resolved_request.temperature,
                            "max_tokens": max_tokens,
                            "timeout": timeout_seconds,
                        }
                    )
                    with start_span(
                        "llm.gateway.call",
                        {
                            "llm.provider": candidate.provider,
                            "llm.model": candidate.model,
                            "llm.task": resolved_request.task,
                            "llm.route": candidate.route,
                            "llm.attempt": attempt,
                        },
                    ):
                        response = completion(**call_kwargs)
                    input_tokens, output_tokens = _response_usage(response)
                    usage = ModelUsage(input_tokens=input_tokens, output_tokens=output_tokens)
                    content = self._content(response)
                    if not content:
                        raise ModelGatewayError("模型返回为空")
                    cost = _estimate_cost(input_tokens, output_tokens)
                    self.budget_store.settle(
                        reservation,
                        usage.total_tokens or reservation.tokens,
                        cost if cost is not None else reservation.cost,
                    )
                    elapsed = time.perf_counter() - started_at
                    decision = ModelRouteDecision(
                        provider=candidate.provider,
                        model=candidate.model,
                        route=candidate.route,
                        reason="primary_success" if candidate.route == "primary" else "fallback_success",
                        attempt=attempt,
                        fallback_used=candidate.route == "fallback",
                    )
                    record_model_route(resolved_request.task, candidate.provider, candidate.model, candidate.route)
                    record_llm_call(
                        "success",
                        elapsed,
                        model=candidate.model,
                        input_tokens=input_tokens,
                        output_tokens=output_tokens,
                        cost=cost,
                    )
                    log_event(
                        self.logger,
                        20,
                        "llm_gateway_completed",
                        task=resolved_request.task,
                        provider=candidate.provider,
                        model=candidate.model,
                        route=candidate.route,
                        attempt=attempt,
                        fallback_used=decision.fallback_used,
                        input_tokens=input_tokens,
                        output_tokens=output_tokens,
                        cost=cost,
                        duration_ms=round(elapsed * 1000, 2),
                    )
                    record_langfuse_trace(
                        "llm.gateway.call",
                        metadata={
                            "task": resolved_request.task,
                            "provider": candidate.provider,
                            "model": candidate.model,
                            "route": candidate.route,
                            "fallback_used": decision.fallback_used,
                            "input_tokens": input_tokens,
                            "output_tokens": output_tokens,
                            "cost": cost,
                        },
                    )
                    return GatewayResponse(content=content, usage=usage, cost=cost, decision=decision)
                except ModelBudgetExceeded:
                    raise
                except Exception as exc:
                    if reservation is not None:
                        self.budget_store.release(reservation)
                    last_error = exc
                    elapsed = time.perf_counter() - started_at
                    record_model_route(resolved_request.task, candidate.provider, candidate.model, candidate.route)
                    record_llm_call("failure", elapsed, model=candidate.model)
                    log_event(
                        self.logger,
                        30,
                        "llm_gateway_failed",
                        task=resolved_request.task,
                        provider=candidate.provider,
                        model=candidate.model,
                        route=candidate.route,
                        attempt=attempt,
                        error_type=type(exc).__name__,
                        duration_ms=round(elapsed * 1000, 2),
                    )
                    if attempt < settings.llm_max_attempts:
                        delay = max(0.0, settings.llm_retry_base_delay_ms / 1000) * (2 ** (attempt - 1))
                        if delay:
                            self.sleep_fn(delay)

        record_fallback("llm_gateway_unavailable")
        if isinstance(last_error, ModelUnavailable):
            raise last_error
        raise ModelGatewayError("所有模型路由均不可用") from last_error

    def stream(
        self,
        prompt: str,
        request: ModelRouteRequest | None = None,
        *,
        task: str = "answer",
        user_id: str | None = None,
        cancel_event: Any | None = None,
    ) -> Iterator[str]:
        """Yield provider deltas while preserving P1-2 routing and budget rules.

        A fallback is attempted only before the first delta is emitted. Once a
        client has received content, switching models would produce a duplicate
        or contradictory answer, so the interrupted stream fails safely.
        """

        if not isinstance(prompt, str) or not prompt.strip():
            raise ValueError("prompt 不能为空")
        resolved_request = request or self.build_request(task)
        max_tokens = min(resolved_request.max_tokens, settings.llm_max_tokens)
        timeout_seconds = min(resolved_request.timeout_seconds, settings.llm_timeout_seconds)
        candidates = self._candidates(resolved_request)
        completion = self._completion()
        last_error: Exception | None = None
        resolved_user_id = user_id or "anonymous"

        for candidate in candidates:
            for attempt in range(1, settings.llm_max_attempts + 1):
                reservation: _BudgetReservation | None = None
                started_at = time.perf_counter()
                emitted = False
                input_tokens: int | None = None
                output_tokens: int | None = None
                try:
                    if cancel_event is not None and cancel_event.is_set():
                        raise StreamCancelled("stream cancelled by client")
                    reservation = self._reservation(resolved_user_id, prompt, max_tokens)
                    call_kwargs = self._provider_kwargs(candidate.provider, candidate.model)
                    call_kwargs.update(
                        {
                            "messages": [{"role": "user", "content": prompt}],
                            "temperature": resolved_request.temperature,
                            "max_tokens": max_tokens,
                            "timeout": timeout_seconds,
                            "stream": True,
                        }
                    )
                    with start_span(
                        "llm.gateway.stream",
                        {
                            "llm.provider": candidate.provider,
                            "llm.model": candidate.model,
                            "llm.task": resolved_request.task,
                            "llm.route": candidate.route,
                            "llm.attempt": attempt,
                        },
                    ):
                        response = completion(**call_kwargs)
                        for chunk in response:
                            if cancel_event is not None and cancel_event.is_set():
                                raise StreamCancelled("stream cancelled by client")
                            chunk_input, chunk_output = _response_usage(chunk)
                            input_tokens = chunk_input if chunk_input is not None else input_tokens
                            output_tokens = chunk_output if chunk_output is not None else output_tokens
                            delta = self._delta_content(chunk)
                            if delta:
                                emitted = True
                                yield delta
                    if not emitted:
                        raise ModelGatewayError("模型流式返回为空")
                    usage = ModelUsage(input_tokens=input_tokens, output_tokens=output_tokens)
                    cost = _estimate_cost(input_tokens, output_tokens)
                    self.budget_store.settle(
                        reservation,
                        usage.total_tokens or reservation.tokens,
                        cost if cost is not None else reservation.cost,
                    )
                    elapsed = time.perf_counter() - started_at
                    fallback_used = candidate.route == "fallback"
                    record_model_route(resolved_request.task, candidate.provider, candidate.model, candidate.route)
                    record_llm_call(
                        "success",
                        elapsed,
                        model=candidate.model,
                        input_tokens=input_tokens,
                        output_tokens=output_tokens,
                        cost=cost,
                    )
                    log_event(
                        self.logger,
                        20,
                        "llm_gateway_stream_completed",
                        task=resolved_request.task,
                        provider=candidate.provider,
                        model=candidate.model,
                        route=candidate.route,
                        attempt=attempt,
                        fallback_used=fallback_used,
                        input_tokens=input_tokens,
                        output_tokens=output_tokens,
                        cost=cost,
                        duration_ms=round(elapsed * 1000, 2),
                    )
                    record_langfuse_trace(
                        "llm.gateway.stream",
                        metadata={
                            "task": resolved_request.task,
                            "provider": candidate.provider,
                            "model": candidate.model,
                            "route": candidate.route,
                            "fallback_used": fallback_used,
                            "input_tokens": input_tokens,
                            "output_tokens": output_tokens,
                            "cost": cost,
                        },
                    )
                    return
                except StreamCancelled:
                    if reservation is not None:
                        self.budget_store.release(reservation)
                    record_llm_call("cancelled", time.perf_counter() - started_at, model=candidate.model)
                    raise
                except ModelBudgetExceeded:
                    raise
                except Exception as exc:
                    if reservation is not None:
                        self.budget_store.release(reservation)
                    last_error = exc
                    elapsed = time.perf_counter() - started_at
                    record_model_route(resolved_request.task, candidate.provider, candidate.model, candidate.route)
                    record_llm_call("failure", elapsed, model=candidate.model)
                    log_event(
                        self.logger,
                        30,
                        "llm_gateway_stream_failed",
                        task=resolved_request.task,
                        provider=candidate.provider,
                        model=candidate.model,
                        route=candidate.route,
                        attempt=attempt,
                        emitted=emitted,
                        error_type=type(exc).__name__,
                        duration_ms=round(elapsed * 1000, 2),
                    )
                    if emitted:
                        raise ModelGatewayError("流式模型调用中断") from exc
                    if attempt < settings.llm_max_attempts:
                        delay = max(0.0, settings.llm_retry_base_delay_ms / 1000) * (2 ** (attempt - 1))
                        if delay:
                            self.sleep_fn(delay)

        record_fallback("llm_gateway_stream_unavailable")
        if isinstance(last_error, ModelUnavailable):
            raise last_error
        raise ModelGatewayError("所有模型流式路由均不可用") from last_error


class GatewayLLM:
    """Minimal LangChain-compatible adapter used by the existing Workflow."""

    def __init__(
        self,
        gateway: ModelGateway,
        *,
        task: str,
        user_id: str | None = None,
        preferred_model: str | None = None,
    ) -> None:
        self.gateway = gateway
        self.task = task
        self.user_id = user_id
        self.preferred_model = preferred_model

    def invoke(self, prompt: str) -> str:
        request = self.gateway.build_request(self.task, preferred_model=self.preferred_model)
        return self.gateway.complete(prompt, request=request, task=self.task, user_id=self.user_id).content

    def stream(self, prompt: str, *, cancel_event: Any | None = None) -> Iterator[str]:
        request = self.gateway.build_request(self.task, preferred_model=self.preferred_model)
        return self.gateway.stream(
            prompt,
            request=request,
            task=self.task,
            user_id=self.user_id,
            cancel_event=cancel_event,
        )


_DEFAULT_GATEWAY = ModelGateway()


def get_model_gateway() -> ModelGateway:
    return _DEFAULT_GATEWAY


def get_llm(
    *, task: str = "answer", user_id: str | None = None, preferred_model: str | None = None
) -> GatewayLLM:
    return GatewayLLM(
        get_model_gateway(), task=task, user_id=user_id, preferred_model=preferred_model
    )
