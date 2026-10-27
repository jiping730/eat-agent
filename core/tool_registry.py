"""Canonical and reliable tool execution boundary.

All application entry points use this module to discover and execute tools.
The registry deliberately remains an in-process component for the small
platform: policy checks, schema validation, timeout, retry, circuit breaking,
and audit logging happen at one boundary instead of being duplicated by the
Workflow, skills, or MCP adapters.
"""

from __future__ import annotations

import logging
import random
import threading
import time
from collections.abc import Callable, Iterable, Mapping
from concurrent.futures import Future, ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeoutError
from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field, ValidationError, model_validator
from tavily import TavilyClient

from config import settings
from core.logging_config import configure_logging, fingerprint, log_event
from core.observability import get_observation_context, record_tool_execution, start_span
from rag.retriever import get_retriever_with_score

TOOL_STATUSES = {
    "success",
    "validation_error",
    "permission_denied",
    "tool_not_found",
    "timeout",
    "retry_exhausted",
    "circuit_open",
    "configuration_error",
    "tool_execution_failed",
    "error",
}

RETRYABLE_ERROR_CODES = {
    "tool_timeout",
    "tool_transient_failure",
    "upstream_unavailable",
    "rate_limited",
    "temporary_failure",
}

DEFAULT_CALLERS = frozenset({"workflow", "mcp", "skill", "legacy"})


class ToolTransientError(RuntimeError):
    """A tool error that is safe to retry when the tool is idempotent."""


class ToolTimeoutError(TimeoutError):
    """Raised internally when a handler exceeds its execution deadline."""


class QueryToolInput(BaseModel):
    query: str = Field(min_length=1, max_length=20_000)


class ContextToolInput(QueryToolInput):
    fields: dict[str, Any] = Field(default_factory=dict)
    intent: str | None = None


class CalorieToolInput(ContextToolInput):
    @model_validator(mode="after")
    def require_food(self) -> "CalorieToolInput":
        if not self.fields.get("food"):
            raise ValueError("food is required")
        return self


class ToolResult(BaseModel):
    """Stable result envelope returned by every registered tool."""

    status: str = "success"
    data: Any = None
    sources: list[dict[str, Any]] = Field(default_factory=list)
    error_code: str | None = None
    trace_id: str = Field(default_factory=lambda: str(uuid4()))
    attempts: int = 1
    duration_ms: float = 0.0

    @property
    def text(self) -> str:
        """Compatibility view for callers that still expect plain text."""

        if isinstance(self.data, str):
            return self.data
        if isinstance(self.data, Mapping) and "text" in self.data:
            return str(self.data["text"])
        return str(self.data or "")


ToolHandler = Callable[[str, Mapping[str, Any]], str | ToolResult]


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    input_schema: dict[str, Any]
    output_schema: dict[str, Any] = field(default_factory=dict)
    timeout_seconds: float | None = None
    max_attempts: int | None = None
    retryable: bool = True
    allowed_callers: frozenset[str] = DEFAULT_CALLERS
    allowed_intents: frozenset[str] = frozenset()
    input_model: type[BaseModel] | None = field(default=None, repr=False, compare=False)


@dataclass
class _CircuitState:
    failures: int = 0
    opened_at: float | None = None
    half_open: bool = False


class ToolNotFoundError(LookupError):
    """Raised when a workflow requests a tool that is not registered."""


class ToolRegistry:
    """Explicit registry with a single, guarded execution path."""

    def __init__(
        self,
        *,
        logger: logging.Logger | None = None,
        max_workers: int | None = None,
    ) -> None:
        self._handlers: dict[str, ToolHandler] = {}
        self._specs: dict[str, ToolSpec] = {}
        self._circuits: dict[str, _CircuitState] = {}
        self._circuit_lock = threading.RLock()
        self._executor = ThreadPoolExecutor(
            max_workers=max_workers or max(1, settings.tool_executor_max_workers),
            thread_name_prefix="eat-agent-tool",
        )
        self.logger = logger or configure_logging(settings.log_level)

    def register(
        self,
        name: str,
        handler: ToolHandler,
        *,
        description: str = "",
        input_schema: dict[str, Any] | None = None,
        input_model: type[BaseModel] | None = None,
        output_schema: dict[str, Any] | None = None,
        timeout_seconds: float | None = None,
        max_attempts: int | None = None,
        retryable: bool = True,
        allowed_callers: Iterable[str] | None = None,
        allowed_intents: Iterable[str] | None = None,
    ) -> None:
        if not name or not name.strip():
            raise ValueError("tool name 不能为空")
        if not callable(handler):
            raise TypeError("tool handler 必须可调用")
        if name in self._handlers:
            raise ValueError(f"工具已注册: {name}")

        resolved_timeout = settings.tool_default_timeout_seconds if timeout_seconds is None else timeout_seconds
        resolved_attempts = settings.tool_max_attempts if max_attempts is None else max_attempts
        if resolved_timeout <= 0:
            raise ValueError("工具超时时间必须大于 0")
        if resolved_attempts < 1:
            raise ValueError("工具最大尝试次数必须至少为 1")

        resolved_schema = input_schema
        if resolved_schema is None and input_model is not None:
            resolved_schema = input_model.model_json_schema()
        resolved_schema = resolved_schema or {"type": "object"}
        resolved_output_schema = output_schema or ToolResult.model_json_schema()

        self._handlers[name] = handler
        self._specs[name] = ToolSpec(
            name=name,
            description=description,
            input_schema=resolved_schema,
            output_schema=resolved_output_schema,
            timeout_seconds=float(resolved_timeout),
            max_attempts=int(resolved_attempts),
            retryable=retryable,
            allowed_callers=frozenset(allowed_callers or DEFAULT_CALLERS),
            allowed_intents=frozenset(allowed_intents or ()),
            input_model=input_model,
        )
        with self._circuit_lock:
            self._circuits[name] = _CircuitState()

    @property
    def names(self) -> tuple[str, ...]:
        return tuple(self._handlers.keys())

    @property
    def specs(self) -> tuple[ToolSpec, ...]:
        return tuple(self._specs.values())

    def execute_result(
        self,
        name: str,
        query: str,
        context: Mapping[str, Any] | None = None,
        *,
        caller: str = "workflow",
    ) -> ToolResult:
        """Execute a registered tool through policy and resilience controls."""

        trace_id = str(uuid4())
        started_at = time.perf_counter()
        raw_context = dict(context or {})
        parent_trace_id = raw_context.get("trace_id") or get_observation_context().trace_id
        with start_span(
            "tool.execute",
            {
                "tool.name": name,
                "tool.caller": caller,
                "tool.parent_trace_id": parent_trace_id,
            },
        ):
            result = self._execute_result(name, query, raw_context, caller, trace_id)

        result = result.model_copy(update={"duration_ms": round((time.perf_counter() - started_at) * 1000, 2)})
        record_tool_execution(
            name,
            result.status,
            result.duration_ms,
            error_code=result.error_code,
            attempts=result.attempts,
        )
        self._audit(name, caller, raw_context, result, started_at, parent_trace_id=parent_trace_id)
        return result

    def _execute_result(
        self,
        name: str,
        query: str,
        raw_context: Mapping[str, Any],
        caller: str,
        trace_id: str,
    ) -> ToolResult:
        """Run policy, resilience, and handler logic without side effects for telemetry."""

        spec = self._specs.get(name)
        if spec is None:
            return ToolResult(status="tool_not_found", error_code="tool_not_found", trace_id=trace_id)

        permission_error = self._check_permission(spec, caller, raw_context, trace_id)
        if permission_error is not None:
            return permission_error

        payload = dict(raw_context)
        payload.setdefault("query", query or "")
        validation_error = self._validate_input(spec, payload, trace_id)
        if validation_error is not None:
            return validation_error

        if not self._circuit_allows(name):
            return ToolResult(status="circuit_open", error_code="circuit_open", trace_id=trace_id)

        handler = self._handlers[name]
        max_attempts = max(1, spec.max_attempts or 1)
        last_result: ToolResult | None = None

        for attempt in range(1, max_attempts + 1):
            try:
                raw_result = self._call_with_timeout(handler, query, payload, spec.timeout_seconds or 1.0)
                attempt_result = self._normalize_result(raw_result, trace_id)
            except ToolTimeoutError:
                attempt_result = ToolResult(
                    status="timeout",
                    error_code="tool_timeout",
                    trace_id=trace_id,
                )
            except (ToolTransientError, ConnectionError, TimeoutError, OSError):
                attempt_result = ToolResult(
                    status="tool_execution_failed",
                    error_code="tool_transient_failure",
                    trace_id=trace_id,
                )
            except Exception:
                # Do not expose handler exception details to the API caller.
                attempt_result = ToolResult(
                    status="tool_execution_failed",
                    error_code="tool_execution_failed",
                    trace_id=trace_id,
                )

            attempt_result = attempt_result.model_copy(update={"trace_id": trace_id, "attempts": attempt})
            last_result = attempt_result
            if attempt_result.status == "success":
                self._record_circuit_success(name)
                return attempt_result

            if not self._should_retry(spec, attempt_result, attempt):
                break
            delay_seconds = self._retry_delay(attempt)
            if delay_seconds > 0:
                time.sleep(delay_seconds)

        assert last_result is not None
        if last_result.status not in {"validation_error", "permission_denied", "tool_not_found", "configuration_error"}:
            self._record_circuit_failure(name)
        final_result = last_result
        if final_result.attempts > 1 and final_result.status in {"timeout", "tool_execution_failed", "error"}:
            final_result = final_result.model_copy(update={"status": "retry_exhausted"})
        return final_result

    def execute(
        self,
        name: str,
        query: str,
        context: Mapping[str, Any] | None = None,
        *,
        caller: str = "workflow",
    ) -> str:
        """Compatibility text API; new callers should use ``execute_result``."""

        result = self.execute_result(name, query, context, caller=caller)
        if result.status == "success":
            return result.text
        return tool_error_message(result)

    def circuit_state(self, name: str) -> dict[str, Any]:
        """Return safe diagnostic state for tests and operational inspection."""

        with self._circuit_lock:
            state = self._circuits.get(name)
            if state is None:
                return {"exists": False}
            return {
                "exists": True,
                "failures": state.failures,
                "open": state.opened_at is not None,
                "half_open": state.half_open,
            }

    def close(self) -> None:
        """Release worker threads when a registry is explicitly short-lived."""

        self._executor.shutdown(wait=False, cancel_futures=True)

    def _call_with_timeout(
        self,
        handler: ToolHandler,
        query: str,
        payload: Mapping[str, Any],
        timeout_seconds: float,
    ) -> str | ToolResult:
        future: Future[str | ToolResult] = self._executor.submit(handler, query, payload)
        try:
            return future.result(timeout=timeout_seconds)
        except FutureTimeoutError as exc:
            future.cancel()
            raise ToolTimeoutError from exc

    @staticmethod
    def _normalize_result(raw_result: Any, trace_id: str) -> ToolResult:
        if isinstance(raw_result, ToolResult):
            result = raw_result.model_copy(update={"trace_id": trace_id})
        elif isinstance(raw_result, str):
            result = ToolResult(status="success", data=raw_result, trace_id=trace_id)
        elif isinstance(raw_result, Mapping):
            try:
                result = ToolResult.model_validate(raw_result).model_copy(update={"trace_id": trace_id})
            except ValidationError:
                return ToolResult(status="tool_execution_failed", error_code="invalid_tool_result", trace_id=trace_id)
        else:
            return ToolResult(status="tool_execution_failed", error_code="invalid_tool_result", trace_id=trace_id)

        if result.status not in TOOL_STATUSES:
            return ToolResult(status="tool_execution_failed", error_code="invalid_tool_result", trace_id=trace_id)
        return result

    @staticmethod
    def _validate_input(spec: ToolSpec, payload: Mapping[str, Any], trace_id: str) -> ToolResult | None:
        if spec.input_model is not None:
            try:
                spec.input_model.model_validate(payload)
                return None
            except ValidationError:
                return ToolResult(
                    status="validation_error",
                    error_code="invalid_tool_input",
                    trace_id=trace_id,
                )

        schema = spec.input_schema or {}
        if schema.get("type") == "object" and not isinstance(payload, Mapping):
            return ToolResult(status="validation_error", error_code="invalid_tool_input", trace_id=trace_id)
        for required in schema.get("required", []):
            if required not in payload or payload[required] in (None, ""):
                return ToolResult(status="validation_error", error_code="invalid_tool_input", trace_id=trace_id)
        for key, property_schema in schema.get("properties", {}).items():
            if key not in payload or payload[key] is None:
                continue
            expected_type = property_schema.get("type")
            value = payload[key]
            if expected_type == "string" and not isinstance(value, str):
                return ToolResult(status="validation_error", error_code="invalid_tool_input", trace_id=trace_id)
            if expected_type == "object" and not isinstance(value, Mapping):
                return ToolResult(status="validation_error", error_code="invalid_tool_input", trace_id=trace_id)
            if expected_type == "number" and (not isinstance(value, (int, float)) or isinstance(value, bool)):
                return ToolResult(status="validation_error", error_code="invalid_tool_input", trace_id=trace_id)
            if expected_type == "boolean" and not isinstance(value, bool):
                return ToolResult(status="validation_error", error_code="invalid_tool_input", trace_id=trace_id)
        return None

    @staticmethod
    def _check_permission(
        spec: ToolSpec,
        caller: str,
        context: Mapping[str, Any],
        trace_id: str,
    ) -> ToolResult | None:
        if caller not in spec.allowed_callers:
            return ToolResult(status="permission_denied", error_code="tool_not_allowed", trace_id=trace_id)
        intent = context.get("intent")
        if spec.allowed_intents and intent and intent not in spec.allowed_intents:
            return ToolResult(status="permission_denied", error_code="tool_not_allowed", trace_id=trace_id)
        return None

    @staticmethod
    def _should_retry(spec: ToolSpec, result: ToolResult, attempt: int) -> bool:
        if not spec.retryable or attempt >= (spec.max_attempts or 1):
            return False
        if result.status == "timeout":
            return True
        return result.error_code in RETRYABLE_ERROR_CODES

    @staticmethod
    def _retry_delay(attempt: int) -> float:
        base = max(0.0, settings.tool_retry_base_delay_ms / 1000)
        if base == 0:
            return 0.0
        jitter = random.uniform(0, base * 0.25)
        return base * (2 ** (attempt - 1)) + jitter

    def _circuit_allows(self, name: str) -> bool:
        now = time.monotonic()
        recovery = max(0.0, settings.tool_circuit_recovery_seconds)
        with self._circuit_lock:
            state = self._circuits[name]
            if state.opened_at is None:
                return True
            if now - state.opened_at < recovery:
                return False
            if state.half_open:
                return False
            state.half_open = True
            return True

    def _record_circuit_success(self, name: str) -> None:
        with self._circuit_lock:
            state = self._circuits[name]
            state.failures = 0
            state.opened_at = None
            state.half_open = False

    def _record_circuit_failure(self, name: str) -> None:
        with self._circuit_lock:
            state = self._circuits[name]
            state.failures += 1
            threshold = max(1, settings.tool_circuit_failure_threshold)
            if state.half_open or state.failures >= threshold:
                state.opened_at = time.monotonic()
                state.half_open = False

    def _audit(
        self,
        name: str,
        caller: str,
        context: Mapping[str, Any],
        result: ToolResult,
        started_at: float,
        *,
        parent_trace_id: str | None = None,
    ) -> None:
        log_event(
            self.logger,
            logging.INFO if result.status == "success" else logging.WARNING,
            "tool_execution",
            tool_name=name,
            caller=caller,
            status=result.status,
            error_code=result.error_code,
            trace_id=result.trace_id,
            tool_trace_id=result.trace_id,
            parent_trace_id=parent_trace_id,
            request_id=context.get("request_id") or context.get("_request_id"),
            conversation_id=context.get("conversation_id") or context.get("_conversation_id"),
            user=(
                fingerprint(str(context.get("user_id") or context.get("_user_id")))
                if context.get("user_id") or context.get("_user_id")
                else None
            ),
            attempts=result.attempts,
            duration_ms=result.duration_ms or round((time.perf_counter() - started_at) * 1000, 2),
            source_count=len(result.sources),
        )


def tool_error_message(result: ToolResult) -> str:
    """Map internal tool errors to safe, user-facing text."""

    messages = {
        "validation_error": "工具参数不完整，请补充必要信息后重试。",
        "permission_denied": "当前请求不允许调用该工具。",
        "tool_not_found": "当前功能暂时不可用。",
        "timeout": "工具响应超时，请稍后重试。",
        "retry_exhausted": "工具暂时不可用，请稍后重试。",
        "circuit_open": "该工具当前故障较多，请稍后重试。",
        "configuration_error": "该工具尚未完成配置，请稍后重试。",
    }
    return messages.get(result.status, "工具暂时不可用，请稍后重试。")


def retrieve_knowledge_result(
    query: str,
    *,
    score_threshold: float = 2.0,
    access_groups: set[str] | None = None,
) -> ToolResult:
    """Run local retrieval and preserve document provenance."""

    try:
        retriever = get_retriever_with_score(score_threshold=score_threshold, access_groups=access_groups)
        docs = retriever(query)
    except Exception as exc:
        raise ToolTransientError("知识库暂时不可用") from exc

    if not docs:
        return ToolResult(status="success", data="未找到相关信息。")

    sources: list[dict[str, Any]] = []
    for doc in docs:
        metadata = getattr(doc, "metadata", {}) or {}
        source = metadata.get("source") or metadata.get("file_path") or "local_knowledge_base"
        sources.append(
            {
                "type": "knowledge_base",
                "source": str(source),
                "title": metadata.get("title"),
                "document_id": metadata.get("document_id"),
                "version": metadata.get("version"),
                "chunk_id": metadata.get("chunk_id"),
                "score": metadata.get("retrieval_score"),
            }
        )
    return ToolResult(
        status="success",
        data="\n\n".join(doc.page_content for doc in docs),
        sources=sources,
    )


def retrieve_knowledge(query: str, *, score_threshold: float = 2.0) -> str:
    """Legacy text API for the old LangChain Tool adapter."""

    try:
        result = retrieve_knowledge_result(query, score_threshold=score_threshold)
    except Exception:
        return "知识库暂时不可用，请稍后重试。"
    return result.text if result.status == "success" else tool_error_message(result)


def search_web_result(query: str) -> ToolResult:
    """Run Tavily search with structured status and URL provenance."""

    api_key = settings.tavily_api_key
    if not api_key:
        return ToolResult(status="configuration_error", error_code="missing_tavily_api_key")
    try:
        client = TavilyClient(api_key=api_key)
        response = client.search(query, max_results=3)
    except Exception as exc:
        raise ToolTransientError("搜索暂时不可用") from exc

    results = response.get("results", []) if isinstance(response, Mapping) else []
    sources = [
        {
            "type": "web",
            "url": item.get("url"),
            "title": item.get("title"),
        }
        for item in results
        if isinstance(item, Mapping) and (item.get("url") or item.get("title"))
    ]
    contents = [item.get("content", "") for item in results if isinstance(item, Mapping) and item.get("content")]
    return ToolResult(
        status="success",
        data="\n\n".join(contents) if contents else "未找到相关信息。",
        sources=sources,
    )


def search_web(query: str) -> str:
    """Legacy text API for the old LangChain Tool adapter."""

    try:
        result = search_web_result(query)
    except Exception:
        return "搜索暂时不可用，请稍后重试。"
    return result.text if result.status == "success" else tool_error_message(result)


def _retrieval_handler(query: str, context: Mapping[str, Any]) -> ToolResult:
    access_groups = context.get("access_groups")
    return retrieve_knowledge_result(query, access_groups=set(access_groups) if access_groups else None)


def _calorie_handler(query: str, context: Mapping[str, Any]) -> ToolResult:
    if not settings.zhipuai_api_key:
        fields = context.get("fields", {})
        return ToolResult(
            status="success",
            data=(
                "当前为离线模式，已确认热量查询参数："
                f"食物={fields.get('food', '未说明')}，"
                f"份量={fields.get('amount', '100g')}，"
                f"口径={fields.get('cooking_state', '未说明')}。"
                "配置知识库 API Key 后可返回具体热量数据。"
            ),
            sources=[{"type": "offline", "source": "local_fallback"}],
        )
    access_groups = context.get("access_groups")
    return retrieve_knowledge_result(query, access_groups=set(access_groups) if access_groups else None)


def _meal_planner_handler(_: str, context: Mapping[str, Any]) -> ToolResult:
    fields = context.get("fields", {})
    return ToolResult(
        status="success",
        data=f"餐食规划参数已确认：{dict(fields)}",
        sources=[{"type": "rule", "source": "meal_planner_profile"}],
    )


def build_default_tool_registry() -> ToolRegistry:
    """Build the tools allowed by the canonical application workflow."""

    registry = ToolRegistry()
    registry.register(
        "retrieval_tool",
        _retrieval_handler,
        description="查询本地营养知识库",
        input_schema=QueryToolInput.model_json_schema(),
        input_model=QueryToolInput,
        allowed_intents={"calorie_query", "meal_planner", "followup", "general"},
    )
    registry.register(
        "calorie_query",
        _calorie_handler,
        description="查询食物热量",
        input_schema={
            "type": "object",
            "properties": {
                "food": {"type": "string"},
                "amount": {"type": "string"},
                "cooking_state": {"type": "string"},
            },
            "required": ["food"],
        },
        input_model=CalorieToolInput,
        allowed_intents={"calorie_query"},
    )
    registry.register(
        "meal_planner",
        _meal_planner_handler,
        description="根据已确认参数生成餐食规划",
        input_schema={
            "type": "object",
            "properties": {
                "meal_type": {"type": "string"},
                "health_goal": {"type": "string"},
                "allergy_info": {"type": "string"},
            },
        },
        input_model=ContextToolInput,
        allowed_intents={"meal_planner"},
    )
    registry.register(
        "web_search",
        lambda query, _: search_web_result(query),
        description="查询实时网络信息",
        input_schema=QueryToolInput.model_json_schema(),
        input_model=QueryToolInput,
        allowed_intents={"web_search", "general", "followup", "meal_planner", "calorie_query"},
    )
    return registry
