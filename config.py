import os
from typing import Optional

from dotenv import load_dotenv
from pydantic_settings import BaseSettings

load_dotenv()


class Settings(BaseSettings):
    # 基础配置
    zhipuai_api_key: str = os.getenv("ZHIPUAI_API_KEY")
    embedding_model: str = "embedding-2"
    llm_model: str = "glm-4-flash"

    # 路径配置
    BASE_DIR: str = os.path.dirname(os.path.abspath(__file__))
    vector_store_path: str = os.path.join(BASE_DIR, "data/vector_store")
    documents_path: str = os.path.join(BASE_DIR, "data/documents")
    memory_path: str = os.path.join(BASE_DIR, "data/memory")

    # 记忆配置
    short_term_size: int = 10  # 短期记忆保留轮数
    long_term_top_k: int = 5  # 长期记忆检索数量

    # MCP 配置
    enable_mcp: bool = True
    local_mcp_server: str = "stdio"  # 可选 stdio, sse
    firecrawl_api_key: Optional[str] = None

    # GraphRAG 配置
    use_graphrag: bool = False  # 临时关闭 GraphRAG
    neo4j_uri: str = os.getenv("NEO4J_URI", "bolt://localhost:7687")
    neo4j_user: str = os.getenv("NEO4J_USER", "neo4j")
    neo4j_password: str = os.getenv("NEO4J_PASSWORD", "password")


settings = Settings()