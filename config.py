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
    openai_api_key: Optional[str] = None
    tavily_api_key: Optional[str] = None
    embedding_model: str = "embedding-2"
    llm_model: str = "glm-4-flash"
    llm_primary_provider: str = "zhipuai"
    llm_fallback_provider: str = "zhipuai"
    llm_api_base: str = "https://open.bigmodel.cn/api/paas/v4"
    openai_api_base: str = "https://api.openai.com/v1"
    llm_intent_model: str = "glm-4-flash"
    llm_answer_model: Optional[str] = None
    llm_fallback_models: str = ""
    llm_intent_enabled: bool = True
    llm_intent_min_confidence: float = 0.8
    llm_timeout_seconds: float = 30.0
    llm_max_attempts: int = 2
    llm_retry_base_delay_ms: int = 200
    llm_max_tokens: int = 4096
    llm_user_daily_token_limit: int = 0
    llm_user_daily_cost_limit: float = 0.0

    # P03 持久化与生产运行配置
    app_env: str = "development"
    app_version: str = "0.7.0"
    database_url: str = "sqlite:///data/app.db"
    auto_create_schema: bool = True
    app_api_key: Optional[str] = None
    auth_mode: str = "auto"  # auto, none, api_key, jwt, hybrid
    jwt_secret: Optional[str] = None
    jwt_issuer: str = "eat-agent"
    jwt_access_ttl_minutes: int = 30
    jwt_refresh_ttl_days: int = 30
    conversation_ttl_days: int = 30
    redis_url: Optional[str] = None
    redis_lock_timeout_seconds: int = 30
    strict_security: bool = False
    metrics_enabled: bool = True
    metrics_api_key: Optional[str] = None
    cors_origins: str = "*"
    max_request_bytes: int = 64 * 1024
    rate_limit_per_minute: int = 120
    log_level: str = "INFO"

    # P0-6 工具执行可靠性。小型平台采用进程内线程池和熔断状态；
    # 跨 Pod 的统一熔断状态留到后续规模化阶段。
    tool_default_timeout_seconds: float = 15.0
    tool_max_attempts: int = 3
    tool_retry_base_delay_ms: int = 200
    tool_circuit_failure_threshold: int = 5
    tool_circuit_recovery_seconds: float = 30.0
    tool_executor_max_workers: int = 8

    # P0-7 可选链路追踪和 LLM 观测。未配置时使用本地 JSON 日志和 Prometheus。
    otel_enabled: bool = False
    otel_service_name: str = "eat-agent"
    otel_exporter_otlp_endpoint: Optional[str] = None
    langfuse_enabled: bool = False
    langfuse_public_key: Optional[str] = None
    langfuse_secret_key: Optional[str] = None
    langfuse_host: Optional[str] = None
    langfuse_capture_content: bool = False
    llm_input_cost_per_1k: float = 0.0
    llm_output_cost_per_1k: float = 0.0

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
    mcp_local_server_name: str = "nutrition_local"
    mcp_local_allowed_tools: str = "calorie_query,meal_planner"
    mcp_servers_json: str = ""
    mcp_startup_timeout_seconds: float = 10.0
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
        if self.auth_mode in {"jwt", "hybrid"} and not self.jwt_secret:
            warnings.append("AUTH_MODE 已启用 JWT，但未配置 JWT_SECRET，用户认证不可用。")
        return warnings

    def startup_errors(self) -> list[str]:
        """Return configuration errors that must stop a strict deployment."""
        if not self.strict_security:
            return []

        errors: list[str] = []
        if self.app_env.lower() not in {"production", "prod"}:
            errors.append("STRICT_SECURITY 只能用于 production/prod 环境")
        if self.auth_mode.lower() not in {"jwt", "hybrid"}:
            errors.append("生产环境 AUTH_MODE 必须是 jwt 或 hybrid")
        if not self.jwt_secret or len(self.jwt_secret) < 32:
            errors.append("生产环境 JWT_SECRET 至少需要 32 个字符")
        if self.cors_origins.strip() == "*":
            errors.append("生产环境 CORS_ORIGINS 不能使用 *")
        if not self.database_url.lower().startswith(("postgresql://", "postgresql+")):
            errors.append("生产环境 DATABASE_URL 必须指向 PostgreSQL")
        if not self.redis_url:
            errors.append("生产环境必须配置 REDIS_URL")
        if self.metrics_enabled and not self.metrics_api_key:
            errors.append("生产环境启用 metrics 时必须配置 METRICS_API_KEY")
        return errors

    def cors_origin_list(self) -> list[str] | str:
        if self.cors_origins.strip() == "*":
            return "*"
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


settings = Settings()
