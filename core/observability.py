"""Low-cardinality Prometheus metrics for the modular monolith."""

from __future__ import annotations

from prometheus_client import Counter, Gauge, Histogram


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


def record_http_request(method: str, path: str, status: int, elapsed: float) -> None:
    HTTP_REQUESTS.labels(method=method, path=path, status=str(status)).inc()
    HTTP_DURATION.labels(method=method, path=path).observe(max(0.0, elapsed))


def record_conversation(response_type: str, grill_action: str, elapsed: float) -> None:
    CONVERSATION_RESPONSES.labels(response_type=response_type, grill_action=grill_action or "none").inc()
    CONVERSATION_DURATION.labels(response_type=response_type).observe(max(0.0, elapsed))


def record_grill_decision(action: str, target_field: str | None) -> None:
    GRILL_DECISIONS.labels(action=action or "unknown", target_field=target_field or "none").inc()


def record_llm_call(outcome: str, elapsed: float) -> None:
    LLM_REQUESTS.labels(outcome=outcome).inc()
    LLM_DURATION.observe(max(0.0, elapsed))


def record_rate_limit_rejection() -> None:
    RATE_LIMIT_REJECTIONS.inc()


def set_app_info(version: str, environment: str) -> None:
    APP_INFO.labels(version=version, environment=environment).set(1)
