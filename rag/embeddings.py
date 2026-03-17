try:
    from langchain_community.embeddings import ZhipuAIEmbeddings
    _has_embeddings = True
except ImportError:
    _has_embeddings = False
    from typing import List
    from zhipuai import ZhipuAI
    from config import settings
    from langchain_core.embeddings import Embeddings  # 导入基类

    class CustomZhipuEmbeddings(Embeddings):  # 继承 Embeddings
        def __init__(self):
            self.client = ZhipuAI(api_key=settings.zhipuai_api_key)
            self.model = settings.embedding_model

        def embed_documents(self, texts: List[str]) -> List[List[float]]:
            embeddings = []
            for text in texts:
                resp = self.client.embeddings.create(
                    model=self.model,
                    input=text
                )
                embeddings.append(resp.data[0].embedding)
            return embeddings

        def embed_query(self, text: str) -> List[float]:
            resp = self.client.embeddings.create(
                model=self.model,
                input=text
            )
            return resp.data[0].embedding

def get_embeddings():
    if _has_embeddings:
        return ZhipuAIEmbeddings(
            model=settings.embedding_model,
            api_key=settings.zhipuai_api_key
        )
    else:
        return CustomZhipuEmbeddings()