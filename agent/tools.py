# agent/tools.py

from langchain.tools import Tool
from core.tool_registry import retrieve_knowledge, search_web


def retrieval_func(query: str) -> str:
    return retrieve_knowledge(query)


def create_retrieval_tool():
    return Tool(
        name="retrieval_tool",
        func=retrieval_func,
        description="当需要查询知识库中的信息时使用此工具。输入：查询问题。输出：相关文档片段。"
    )


def create_web_search_tool():
    """创建与主 Workflow 共用实现的联网搜索工具。"""
    return Tool(
        name="web_search",
        func=search_web,
        description="当需要查询实时信息、最新资讯、网络热点或用户明确要求搜索时使用。输入：搜索查询（如'2025年低脂饮食趋势'）。输出：相关网页的摘要。"
    )
