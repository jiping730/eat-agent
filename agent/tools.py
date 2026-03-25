# agent/tools.py

from langchain.tools import Tool
from rag.retriever import get_retriever_with_score
import os
from tavily import TavilyClient  # 使用官方 SDK


def retrieval_func(query: str) -> str:
    retriever = get_retriever_with_score(score_threshold=2.0)
    docs = retriever(query)
    if not docs:
        return "未找到相关信息。"
    return "\n\n".join([doc.page_content for doc in docs])


def create_retrieval_tool():
    return Tool(
        name="retrieval_tool",
        func=retrieval_func,
        description="当需要查询知识库中的信息时使用此工具。输入：查询问题。输出：相关文档片段。"
    )


def create_web_search_tool():
    """创建联网搜索工具（使用 Tavily 官方 SDK）"""
    api_key = os.getenv("TAVILY_API_KEY")
    if not api_key:
        raise ValueError("请设置 TAVILY_API_KEY 环境变量")
    client = TavilyClient(api_key=api_key)

    def search(query: str) -> str:
        try:
            response = client.search(query, max_results=3)
            # 提取结果文本
            results = []
            for result in response.get("results", []):
                results.append(result.get("content", ""))
            return "\n\n".join(results) if results else "未找到相关信息。"
        except Exception as e:
            return f"搜索失败: {e}"

    return Tool(
        name="web_search",
        func=search,
        description="当需要查询实时信息、最新资讯、网络热点或用户明确要求搜索时使用。输入：搜索查询（如'2025年低脂饮食趋势'）。输出：相关网页的摘要。"
    )