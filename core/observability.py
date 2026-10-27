"""Metrics, correlation context, and optional tracing for the small platform.

The application always exposes low-cardinality Prometheus metrics and JSON
correlation fields. OpenTelemetry and Langfuse are deliberately optional:
missing exporters or credentials must never prevent the conversation workflow
from starting or answering in offline mode.
"""

from __future__ import annotations

import contextlib
import contextvars
import logging
import sys
from dataclasses import dataclass, replace
from typing import Any, Iterator, Mapping
from uuid import uuid4

from prometheus_client import Counter, Gauge, Histogram


# HTTP and conversation metrics that existed before P0-7.
HTTP_REQUESTS = Counter(
    "eat_agent_http_requests_total",
    "Total HTTP requests handled by the application.",
    ("method", "path", "status"),
)
HTTP_DURATION = Histogram(
    "eat_agent_http_request_duration_seconds",
    "HTTP request duration in seconds.",
    ("method", "path"),
    buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1, 2, 5, 10, 30, 60),
)
CONVERSATION_RESPONSES = Counter(
    "eat_agent_conversation_responses_total",
    "Conversation responses grouped by stable workflow outcome.",
    ("response_type", "grill_action"),
)
CONVERSATION_DURATION = Histogram(
    "eat_agent_conversation_duration_seconds",
    "Conversation workflow duration in seconds.",
    ("response_type",),
    buckets=(0.05, 0.1, 0.25, 0.5, 1, 2, 5, 10, 30, 60),
)
GRILL_DECISIONS = Counter(
    "eat_agent_grill_decisions_total",
    "Grill decisions grouped by action and target field.",
    ("action", "target_field"),
)
LLM_REQUESTS = Counter(
    "eat_agent_llm_requests_total",
    "LLM calls grouped by outcome.",
    ("outcome",),
)
LLM_DURATION = Histogram(
    "eat_agent_llm_duration_seconds",
    "LLM call duration in seconds.",
    buckets=(0.1, 0.5, 1, 2, 5, 10, 30, 60),
)
RATE_LIMIT_REJECTIONS = Counter(
    "eat_agent_rate_limit_rejections_total",
    "Requests rejected by the rate limiter.",
)
APP_INFO = Gauge(
    "eat_agent_info",
    "Static application information.",
    ("version", "environment"),
)

# P0-7 business metrics. Labels are deliberately bounded; IDs and user data
# belong in logs/traces, never in Prometheus labels.
WORKFLOW_REQUESTS = Counter(
    "eat_agent_workflow_runs_total",
    "Workflow runs grouped by intent and outcome.",
    ("intent", "status"),
)
WORKFLOW_DURATION = Histogram(
    "eat_agent_workflow_duration_seconds",
    "Workflow duration grouped by intent.",
    ("intent",),
    buckets=(0.05, 0.1, 0.25, 0.5, 1, 2, 5, 10, 30, 60),
)
GRILL_ROUNDS = Histogram(
    "eat_agent_grill_rounds",
    "Number of clarification rounds in a conversation turn.",
    ("intent",),
    buckets=(0, 1, 2, 3, 4, 5, 8, 13),
)
GRILL_ISSUES = Counter(
    "eat_agent_grill_issues_total",
    "Grill validation and clarification issues.",
    ("intent", "reason"),
)
TOOL_CALLS = Counter(
    "eat_agent_tool_calls_total",
    "Tool calls grouped by tool, status, and error code.",
    ("tool_name", "status", "error_code"),
)
TOOL_DURATION = Histogram(
    "eat_agent_tool_duration_seconds",
    "Tool execution duration grouped by tool.",
    ("tool_name",),
    buckets=(0.005, 0.01, 0.05, 0.1, 0.25, 0.5, 1, 2, 5, 10, 30),
)
TOOL_RETRIES = Counter(
    "eat_agent_tool_retries_total",
    "Tool retry attempts grouped by tool.",
    ("tool_name",),
)
TOOL_CIRCUIT_EVENTS = Counter(
    "eat_agent_tool_circuit_events_total",
    "Tool circuit breaker events.",
    ("tool_name", "event"),
)
LLM_TOKENS = Counter(
    "eat_agent_llm_tokens_total",
    "LLM tokens grouped by model and direction.",
    ("model", "direction"),
)
LLM_COST = Counter(
    "eat_agent_llm_cost_total",
    "Estimated LLM cost in configured currency units.",
    ("model",),
)
RAG_REQUESTS = Counter(
    "eat_agent_rag_requests_total",
    "RAG calls grouped by status and hit state.",
    ("status", "hit"),
)
RAG_DURATION = Histogram(
    "eat_agent_rag_duration_seconds",
    "RAG retrieval duration.",
    buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1, 2, 5, 10, 30),
)
RAG_DOCUMENTS = Histogram(
    "eat_agent_rag_documents",
    "Number of documents returned by RAG.",
    buckets=(0, 1, 2, 3, 4, 5, 8, 10),
)
FALLBACKS = Counter(
    "eat_agent_fallbacks_total",
    "Fallback paths grouped by bounded reason.",
    ("kind",),
)


@dataclass(frozen=True)
class ObservationContext:
    request_id: str | None = None
    trace_id: str | None = None
    conversation_id: str | None = None
    user_id_hash: str | None = None
    intent: str | None = None


_OBSERVATION_CONTEXT: contextvars.ContextVar[ObservationContext] = contextvars.ContextVar(
    "eat_agent_observation_context",
    default=ObservationContext(),
)


def get_observation_context() -> ObservationContext:
    return _OBSERVATION_CONTEXT.get()


def bind_observation_context(**values: str | None) -> contextvars.Token[ObservationContext]:
    """Set correlation values for the current request/task."""

    current = get_observation_context()
    allowed = {key: value for key, value in values.items() if hasattr(current, key)}
    return _OBSERVATION_CONTEXT.set(replace(current, **allowed))


def reset_observation_context(token: contextvars.Token[ObservationContext]) -> None:
    _OBSERVATION_CONTEXT.reset(token)


def new_trace_id() -> str:
    return uuid4().hex


def observation_fields() -> dict[str, str]:
    """Return non-empty correlation fields for JSON logging."""

    context = get_observation_context()
    return {
        key: value
        for key, value in {
            "request_id": context.request_id,
            "trace_id": context.trace_id,
            "conversation_id": context.conversation_id,
            "user_id_hash": context.user_id_hash,
            "intent": context.intent,
        }.items()
        if value
    }


def record_http_request(method: str, path: str, status: int, elapsed: float) -> None:
    HTTP_REQUESTS.labels(method=method, path=path, status=str(status)).inc()
    HTTP_DURATION.labels(method=method, path=path).observe(max(0.0, elapsed))


def record_conversation(response_type: str, grill_action: str, elapsed: float) -> None:
    CONVERSATION_RESPONSES.labels(response_type=response_type, grill_action=grill_action or "none").inc()
    CONVERSATION_DURATION.labels(response_type=response_type).observe(max(0.0, elapsed))


def record_workflow(intent: str | None, status: str, elapsed: float) -> None:
    normalized_intent = intent or "unknown"
    WORKFLOW_REQUESTS.labels(intent=normalized_intent, status=status).inc()
    WORKFLOW_DURATION.labels(intent=normalized_intent).observe(max(0.0, elapsed))


def record_grill_decision(action: str, target_field: str | None, *, intent: str | None = None, reason: str | None = None) -> None:
    GRILL_DECISIONS.labels(action=action or "unknown", target_field=target_field or "none").inc()
    if reason:
        GRILL_ISSUES.labels(intent=intent or "unknown", reason=reason).inc()


def record_grill_rounds(intent: str | None, rounds: int) -> None:
    GRILL_ROUNDS.labels(intent=intent or "unknown").observe(max(0, rounds))


def record_tool_execution(
    tool_name: str,
    status: str,
    duration_ms: float,
    *,
    error_code: str | None = None,
    attempts: int = 1,
) -> None:
    TOOL_CALLS.labels(
        tool_name=tool_name or "unknown",
        status=status or "unknown",
        error_code=error_code or "none",
    ).inc()
    TOOL_DURATION.labels(tool_name=tool_name or "unknown").observe(max(0.0, duration_ms) / 1000)
    if attempts > 1:
        TOOL_RETRIES.labels(tool_name=tool_name or "unknown").inc(attempts - 1)
    if status in {"circuit_open", "retry_exhausted"}:
        TOOL_CIRCUIT_EVENTS.labels(tool_name=tool_name or "unknown", event=status).inc()


def record_llm_call(
    outcome: str,
    elapsed: float,
    *,
    model: str = "unknown",
    input_tokens: int | None = None,
    output_tokens: int | None = None,
    cost: float | None = None,
) -> None:
    LLM_REQUESTS.labels(outcome=outcome).inc()
    LLM_DURATION.observe(max(0.0, elapsed))
    normalized_model = model or "unknown"
    if input_tokens is not None:
        LLM_TOKENS.labels(model=normalized_model, direction="input").inc(max(0, input_tokens))
    if output_tokens is not None:
        LLM_TOKENS.labels(model=normalized_model, direction="output").inc(max(0, output_tokens))
    if cost is not None and cost >= 0:
        LLM_COST.labels(model=normalized_model).inc(cost)


def record_rag_retrieval(status: str, hit: bool, elapsed: float, document_count: int = 0) -> None:
    RAG_REQUESTS.labels(status=status or "unknown", hit="true" if hit else "false").inc()
    RAG_DURATION.observe(max(0.0, elapsed))
    RAG_DOCUMENTS.observe(max(0, document_count))


def record_fallback(kind: str) -> None:
    FALLBACKS.labels(kind=kind or "unknown").inc()


def record_rate_limit_rejection() -> None:
    RATE_LIMIT_REJECTIONS.inc()


def set_app_info(version: str, environment: str) -> None:
    APP_INFO.labels(version=version, environment=environment).set(1)


_TRACING_INITIALIZED = False
_TRACER = None
_LANGFUSE_CLIENT = None
_OBSERVABILITY_LOGGER = logging.getLogger("eat_agent.observability")


def configure_optional_observability() -> None:
    """Initialize optional exporters without making them runtime dependencies."""

    global _TRACING_INITIALIZED, _TRACER, _LANGFUSE_CLIENT
    if _TRACING_INITIALIZED:
        return
    _TRACING_INITIALIZED = True

    try:
        from config import settings
    except Exception:
        return

    if settings.otel_enabled:
        try:
            from opentelemetry import trace
            from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
            from opentelemetry.sdk.resources import Resource
            from opentelemetry.sdk.trace import TracerProvider
            from opentelemetry.sdk.trace.export import BatchSpanProcessor

            resource = Resource.create({"service.name": settings.otel_service_name})
            provider = TracerProvider(resource=resource)
            exporter_kwargs = {}
            if settings.otel_exporter_otlp_endpoint:
                exporter_kwargs["endpoint"] = settings.otel_exporter_otlp_endpoint
            provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(**exporter_kwargs)))
            trace.set_tracer_provider(provider)
            _TRACER = trace.get_tracer("eat-agent")
        except Exception as exc:  # optional integration must fail open
            _OBSERVABILITY_LOGGER.warning("OpenTelemetry 初始化失败，继续使用基础指标: %s", type(exc).__name__)

    if settings.langfuse_enabled and settings.langfuse_public_key and settings.langfuse_secret_key:
        try:
            from langfuse import Langfuse

            kwargs = {
                "public_key": settings.langfuse_public_key,
                "secret_key": settings.langfuse_secret_key,
            }
            if settings.langfuse_host:
                kwargs["host"] = settings.langfuse_host
            _LANGFUSE_CLIENT = Langfuse(**kwargs)
        except Exception as exc:  # optional integration must fail open
            _OBSERVABILITY_LOGGER.warning("Langfuse 初始化失败，继续使用基础指标: %s", type(exc).__name__)


@contextlib.contextmanager
def start_span(name: str, attributes: Mapping[str, Any] | None = None) -> Iterator[Any]:
    """Create an OTel span when enabled; otherwise yield a no-op context."""

    configure_optional_observability()
    if _TRACER is None:
        yield None
        return
    span_context = None
    try:
        span_context = _TRACER.start_as_current_span(name)
        span = span_context.__enter__()
    except Exception:
        # Exporter errors must never affect the business workflow.
        yield None
        return
    try:
        for key, value in (attributes or {}).items():
            if value is not None:
                span.set_attribute(key, value)
        yield span
    except BaseException:
        span_context.__exit__(*sys.exc_info())
        raise
    else:
        span_context.__exit__(None, None, None)


def record_langfuse_trace(name: str, *, metadata: Mapping[str, Any] | None = None) -> None:
    """Emit metadata-only Langfuse traces when the optional client is enabled."""

    configure_optional_observability()
    if _LANGFUSE_CLIENT is None:
        return
    context = get_observation_context()
    safe_metadata = dict(metadata or {})
    safe_metadata.update({key: value for key, value in observation_fields().items() if key != "user_id_hash"})
    try:
        trace = _LANGFUSE_CLIENT.trace(
            id=context.trace_id or new_trace_id(),
            name=name,
            metadata=safe_metadata,
        )
        if hasattr(trace, "update"):
            trace.update(metadata=safe_metadata)
    except Exception:
        _OBSERVABILITY_LOGGER.debug("Langfuse trace 写入失败", exc_info=True)


def flush_optional_observability() -> None:
    if _LANGFUSE_CLIENT is not None:
        try:
            _LANGFUSE_CLIENT.flush()
        except Exception:
            _OBSERVABILITY_LOGGER.debug("Langfuse flush 失败", exc_info=True)
