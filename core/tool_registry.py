"""Canonical tool registry used by every application entry point.

The project previously had tool implementations spread across the LangGraph
workflow, the ReAct executor, skills, and the MCP server.  This module is the
single in-process tool boundary for the CLI and Web workflows.  MCP adapters
can delegate to the same handlers without becoming a second implementation.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from config import settings
from rag.retriever import get_retriever_with_score
from tavily import TavilyClient


ToolHandler = Callable[[str, Mapping[str, Any]], str]


class ToolNotFoundError(LookupError):
    """Raised when a workflow requests a tool that is not registered."""


class ToolRegistry:
    """Small explicit registry that keeps tool selection deterministic."""

    def __init__(self) -> None:
        self._handlers: dict[str, ToolHandler] = {}

    def register(self, name: str, handler: ToolHandler) -> None:
        if not name or not name.strip():
            raise ValueError("tool name 不能为空")
        if name in self._handlers:
            raise ValueError(f"工具已注册: {name}")
        self._handlers[name] = handler

    @property
    def names(self) -> tuple[str, ...]:
        return tuple(self._handlers.keys())

    def execute(self, name: str, query: str, context: Mapping[str, Any] | None = None) -> str:
        handler = self._handlers.get(name)
        if handler is None:
            raise ToolNotFoundError(f"未注册工具: {name}")
        result = handler(query, context or {})
        if not isinstance(result, str):
            raise TypeError(f"工具 {name} 必须返回字符串，实际为 {type(result).__name__}")
        return result


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
    except Exception as exc:
        return f"搜索失败: {exc}"


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
    registry.register("retrieval_tool", _retrieval_handler)
    registry.register("calorie_query", _calorie_handler)
    registry.register("meal_planner", _meal_planner_handler)
    registry.register("web_search", lambda query, _: search_web(query))
    return registry
