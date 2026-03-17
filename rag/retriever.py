from rag.vector_store import get_or_create_vector_store

def get_retriever_with_score(score_threshold=2.0):
    """
    返回一个检索函数，该函数接受查询，返回分数高于阈值的文档列表。
    """
    vectorstore = get_or_create_vector_store()
    def retrieve(query: str):
        # 返回 (文档, 分数) 列表，分数越低表示越相似（余弦距离）
        docs_with_scores = vectorstore.similarity_search_with_score(query, k=4)
        # 过滤掉分数高于阈值（即距离过大）的文档（根据实际距离含义调整）
        # 注意：FAISS 默认返回 L2 距离，越小越相似，所以用小于阈值
        filtered_docs = [doc for doc, score in docs_with_scores if score < score_threshold]
        return filtered_docs
    return retrieve