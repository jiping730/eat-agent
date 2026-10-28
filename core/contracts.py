"""Stable cross-module contracts for the P1 capability modules.

These models intentionally live below FastAPI and LangGraph so that RAG,
model routing, SSE, MCP, and evaluation code share the same vocabulary. They
are additive in P1-0: existing response payloads remain backward compatible
until each module adopts the corresponding contract.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field


class ContractModel(BaseModel):
    """Base model that rejects accidental contract drift."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class SourceRef(ContractModel):
    """A safe, serializable reference to knowledge or tool provenance."""

    type: str = Field(min_length=1, max_length=64)
    source: str = Field(min_length=1, max_length=512)
    title: str | None = Field(default=None, max_length=512)
    uri: str | None = Field(default=None, max_length=2048)
    document_id: str | None = Field(default=None, max_length=128)
    version: str | None = Field(default=None, max_length=64)
    chunk_id: str | None = Field(default=None, max_length=128)
    score: float | None = Field(default=None, ge=0)
    metadata: dict[str, Any] = Field(default_factory=dict)


class RetrievedDocument(ContractModel):
    """A retrieved chunk with enough provenance to support citations."""

    content: str = Field(min_length=1, max_length=100_000)
    source: SourceRef
    score: float | None = Field(default=None, ge=0)
    metadata: dict[str, Any] = Field(default_factory=dict)


class RetrievalResponse(ContractModel):
    """The stable envelope returned by a future RAG retriever."""

    status: Literal["success", "no_results", "error", "fallback"]
    documents: list[RetrievedDocument] = Field(default_factory=list)
    sources: list[SourceRef] = Field(default_factory=list)
    query_id: str = Field(default_factory=lambda: uuid4().hex, min_length=1, max_length=128)
    trace_id: str | None = Field(default=None, max_length=128)
    elapsed_ms: float = Field(default=0.0, ge=0)
    error_code: str | None = Field(default=None, max_length=128)


class ModelRouteRequest(ContractModel):
    """Inputs used by the model gateway to choose a provider and model."""

    task: str = Field(min_length=1, max_length=128)
    preferred_model: str | None = Field(default=None, max_length=128)
    fallback_models: list[str] = Field(default_factory=list, max_length=8)
    max_tokens: int = Field(default=2048, ge=1, le=32_768)
    timeout_seconds: float = Field(default=30.0, gt=0, le=120)
    temperature: float = Field(default=0.2, ge=0, le=2)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ModelRouteDecision(ContractModel):
    """Auditable result of model selection and fallback."""

    provider: str = Field(min_length=1, max_length=128)
    model: str = Field(min_length=1, max_length=128)
    route: Literal["primary", "fallback"] = "primary"
    reason: str = Field(min_length=1, max_length=256)
    attempt: int = Field(default=1, ge=1, le=10)
    fallback_used: bool = False


StreamEventName = Literal[
    "conversation.started",
    "model.started",
    "model.delta",
    "grill.clarify",
    "retrieval.started",
    "retrieval.completed",
    "tool.started",
    "tool.completed",
    "answer.completed",
    "conversation.completed",
    "error",
]


class StreamEvent(ContractModel):
    """SSE event contract reserved for the P1 streaming module."""

    event: StreamEventName
    sequence: int = Field(ge=0)
    request_id: str = Field(min_length=1, max_length=128)
    conversation_id: str = Field(min_length=1, max_length=128)
    trace_id: str | None = Field(default=None, max_length=128)
    data: dict[str, Any] = Field(default_factory=dict)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    def to_sse(self) -> str:
        """Serialize one event using the browser EventSource wire format."""

        payload = self.model_dump(mode="json")
        return (
            f"event: {self.event}\n"
            f"id: {self.request_id}:{self.sequence}\n"
            f"data: {json.dumps(payload, ensure_ascii=False, separators=(',', ':'))}\n\n"
        )


class McpToolContract(ContractModel):
    """Versioned MCP tool metadata shared with the Tool Registry."""

    server_name: str = Field(min_length=1, max_length=128)
    name: str = Field(min_length=1, max_length=128)
    version: str = Field(default="1", min_length=1, max_length=64)
    description: str = Field(default="", max_length=4_000)
    input_schema: dict[str, Any] = Field(default_factory=dict)
    output_schema: dict[str, Any] = Field(default_factory=dict)
    allowed_callers: list[str] = Field(default_factory=list, max_length=32)


class McpServerConfig(ContractModel):
    """Configuration for one MCP server in the small-platform registry."""

    name: str = Field(min_length=1, max_length=128)
    version: str = Field(default="1", min_length=1, max_length=64)
    transport: Literal["stdio"] = "stdio"
    command: str = Field(min_length=1, max_length=512)
    args: list[str] = Field(default_factory=list, max_length=32)
    env: dict[str, str] = Field(default_factory=dict)
    enabled: bool = True
    startup_timeout_seconds: float = Field(default=10.0, gt=0, le=120)


class McpCallRequest(ContractModel):
    """Auditable request envelope used by the MCP gateway."""

    server_name: str = Field(min_length=1, max_length=128)
    tool_name: str = Field(min_length=1, max_length=128)
    arguments: dict[str, Any] = Field(default_factory=dict)
    request_id: str | None = Field(default=None, max_length=128)
    conversation_id: str | None = Field(default=None, max_length=128)
    trace_id: str | None = Field(default=None, max_length=128)
    user_id: str | None = Field(default=None, max_length=128)


class EvalCase(ContractModel):
    """Golden-case contract for RAG and end-to-end P1 evaluation."""

    case_id: str = Field(min_length=1, max_length=128)
    question: str = Field(min_length=1, max_length=20_000)
    expected_domain: str | None = Field(default=None, max_length=128)
    expected_task: str | None = Field(default=None, max_length=128)
    required_fields: list[str] = Field(default_factory=list, max_length=32)
    expected_sources: list[str] = Field(default_factory=list, max_length=32)
    must_not_execute: bool = False
    tags: list[str] = Field(default_factory=list, max_length=32)
