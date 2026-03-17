from langchain.tools import Tool
from rag.retriever import get_retriever_with_score

def create_retrieval_tool():
    retrieve_func = get_retriever_with_score(score_threshold=2.0)
    def retrieval_func(query: str) -> str:
        docs = retrieve_func(query)
        if not docs:
            return "未找到相关信息。"   # 简洁，不加额外解释
        # 合并文档内容
        return "\n\n".join([doc.page_content for doc in docs])
    return Tool(
        name="retrieval_tool",
        func=retrieval_func,
        description="当需要查询知识库中的信息时使用此工具。输入：查询问题。输出：相关文档片段。"
    )