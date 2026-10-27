"""Canonical tool registry used by every application entry point.

The project previously had tool implementations spread across the LangGraph
workflow, the ReAct executor, skills, and the MCP server.  This module is the
single in-process tool boundary for the CLI and Web workflows.  MCP adapters
can delegate to the same handlers without becoming a second implementation.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field
from config import settings
from rag.retriever import get_retriever_with_score
from tavily import TavilyClient


ToolHandler = Callable[[str, Mapping[str, Any]], str]


class ToolResult(BaseModel):
    """Stable tool boundary shared by Workflow, Skill adapters, and MCP."""

    status: str = "success"
    data: Any = None
    sources: list[dict[str, Any]] = Field(default_factory=list)
    error_code: str | None = None
    trace_id: str = Field(default_factory=lambda: str(uuid4()))

    @property
    def text(self) -> str:
        if isinstance(self.data, str):
            return self.data
        return str(self.data or "")


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    input_schema: dict[str, Any]


class ToolNotFoundError(LookupError):
    """Raised when a workflow requests a tool that is not registered."""


class ToolRegistry:
    """Small explicit registry that keeps tool selection deterministic."""

    def __init__(self) -> None:
        self._handlers: dict[str, ToolHandler] = {}
        self._specs: dict[str, ToolSpec] = {}

    def register(
        self,
        name: str,
        handler: ToolHandler,
        *,
        description: str = "",
        input_schema: dict[str, Any] | None = None,
    ) -> None:
        if not name or not name.strip():
            raise ValueError("tool name 不能为空")
        if name in self._handlers:
            raise ValueError(f"工具已注册: {name}")
        self._handlers[name] = handler
        self._specs[name] = ToolSpec(name, description, input_schema or {"type": "object"})

    @property
    def names(self) -> tuple[str, ...]:
        return tuple(self._handlers.keys())

    @property
    def specs(self) -> tuple[ToolSpec, ...]:
        return tuple(self._specs.values())

    def execute_result(self, name: str, query: str, context: Mapping[str, Any] | None = None) -> ToolResult:
        trace_id = str(uuid4())
        handler = self._handlers.get(name)
        if handler is None:
            return ToolResult(status="error", error_code="tool_not_found", trace_id=trace_id)
        try:
            result = handler(query, context or {})
            if isinstance(result, ToolResult):
                return result.model_copy(update={"trace_id": trace_id})
            if not isinstance(result, str):
                return ToolResult(status="error", error_code="invalid_tool_result", trace_id=trace_id)
            return ToolResult(status="success", data=result, trace_id=trace_id)
        except Exception:
            return ToolResult(status="error", error_code="tool_execution_failed", trace_id=trace_id)

    def execute(self, name: str, query: str, context: Mapping[str, Any] | None = None) -> str:
        """Compatibility text API; new callers should use ``execute_result``."""
        result = self.execute_result(name, query, context)
        if result.status == "success":
            return result.text
        return "工具暂时不可用，请稍后重试。"


def retrieve_knowledge(query: str, *, score_threshold: float = 2.0) -> str:
    """Run the canonical local knowledge-base retrieval implementation."""

    retriever = get_retriever_with_score(score_threshold=score_threshold)
    docs = retriever(query)
    if not docs:
        return "未找到相关信息。"
    return "\n\n".join(doc.page_content for doc in docs)


def search_web(query: str) -> str:
    """Run the canonical Tavily search implementation with a safe fallback."""

    api_key = settings.tavily_api_key
    if not api_key:
        return "联网搜索未配置：缺少 TAVILY_API_KEY 环境变量。"
    try:
        client = TavilyClient(api_key=api_key)
        response = client.search(query, max_results=3)
        results = [item.get("content", "") for item in response.get("results", [])]
        results = [item for item in results if item]
        return "\n\n".join(results) if results else "未找到相关信息。"
    except Exception:
        return "搜索暂时不可用，请稍后重试。"


def _retrieval_handler(query: str, _: Mapping[str, Any]) -> str:
    return retrieve_knowledge(query)


def _calorie_handler(query: str, context: Mapping[str, Any]) -> str:
    if not settings.zhipuai_api_key:
        fields = context.get("fields", {})
        return (
            "当前为离线模式，已确认热量查询参数："
            f"食物={fields.get('food', '未说明')}，"
            f"份量={fields.get('amount', '100g')}，"
            f"口径={fields.get('cooking_state', '未说明')}。"
            "配置知识库 API Key 后可返回具体热量数据。"
        )
    return retrieve_knowledge(query)


def _meal_planner_handler(_: str, context: Mapping[str, Any]) -> str:
    fields = context.get("fields", {})
    return f"餐食规划参数已确认：{dict(fields)}"


def build_default_tool_registry() -> ToolRegistry:
    """Build the tools allowed by the canonical application workflow."""

    registry = ToolRegistry()
    registry.register(
        "retrieval_tool",
        _retrieval_handler,
        description="查询本地营养知识库",
        input_schema={"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]},
    )
    registry.register(
        "calorie_query",
        _calorie_handler,
        description="查询食物热量",
        input_schema={"type": "object", "properties": {"food": {"type": "string"}}, "required": ["food"]},
    )
    registry.register(
        "meal_planner",
        _meal_planner_handler,
        description="根据已确认参数生成餐食规划",
        input_schema={"type": "object", "properties": {"meal_type": {"type": "string"}}},
    )
    registry.register(
        "web_search",
        lambda query, _: search_web(query),
        description="查询实时网络信息",
        input_schema={"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]},
    )
    return registry
