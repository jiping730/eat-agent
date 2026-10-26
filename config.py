from __future__ import annotations

import os
from typing import Optional

from dotenv import load_dotenv
from pydantic_settings import BaseSettings, SettingsConfigDict

load_dotenv()


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # 基础配置
    # API Key 由部署环境注入；本地开发和离线测试允许为空，调用层会走兜底逻辑。
    zhipuai_api_key: Optional[str] = None
    tavily_api_key: Optional[str] = None
    embedding_model: str = "embedding-2"
    llm_model: str = "glm-4-flash"

    # P03 持久化与生产运行配置
    app_env: str = "development"
    app_version: str = "0.3.0"
    database_url: str = "sqlite:///data/app.db"
    auto_create_schema: bool = True
    app_api_key: Optional[str] = None
    cors_origins: str = "*"
    max_request_bytes: int = 64 * 1024
    rate_limit_per_minute: int = 120
    log_level: str = "INFO"

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
    neo4j_uri: str = "bolt://localhost:7687"
    neo4j_user: str = "neo4j"
    neo4j_password: Optional[str] = None

    def startup_warnings(self) -> list[str]:
        warnings: list[str] = []
        if not self.zhipuai_api_key:
            warnings.append("未配置 ZHIPUAI_API_KEY，将使用离线降级能力。")
        if self.use_graphrag and not self.neo4j_password:
            warnings.append("USE_GRAPHRAG 已开启，但未配置 NEO4J_PASSWORD，GraphRAG 将不可用。")
        return warnings

    def cors_origin_list(self) -> list[str] | str:
        if self.cors_origins.strip() == "*":
            return "*"
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


settings = Settings()
