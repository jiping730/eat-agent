import json
from pathlib import Path

import pytest
from prometheus_client import generate_latest

from config import settings
from core.grill_engine import GrillEngine, get_profile
from core.logging_config import JsonFormatter
from core.observability import record_http_request
from scripts.backup_postgres import _pg_database_url as backup_pg_database_url
from scripts.restore_postgres import _pg_database_url as restore_pg_database_url


def test_production_security_validation_rejects_insecure_defaults(monkeypatch):
    monkeypatch.setattr(settings, "strict_security", True)
    monkeypatch.setattr(settings, "app_env", "production")
    monkeypatch.setattr(settings, "auth_mode", "auto")
    monkeypatch.setattr(settings, "jwt_secret", "short")
    monkeypatch.setattr(settings, "cors_origins", "*")
    monkeypatch.setattr(settings, "database_url", "sqlite:///data/app.db")
    monkeypatch.setattr(settings, "redis_url", None)
    monkeypatch.setattr(settings, "metrics_enabled", True)
    monkeypatch.setattr(settings, "metrics_api_key", None)

    errors = settings.startup_errors()

    assert "生产环境 AUTH_MODE 必须是 jwt 或 hybrid" in errors
    assert "生产环境 JWT_SECRET 至少需要 32 个字符" in errors
    assert "生产环境 CORS_ORIGINS 不能使用 *" in errors
    assert "生产环境 DATABASE_URL 必须指向 PostgreSQL" in errors
    assert "生产环境必须配置 REDIS_URL" in errors
    assert "生产环境启用 metrics 时必须配置 METRICS_API_KEY" in errors


def test_logging_formatter_redacts_credentials():
    import logging

    record = logging.LogRecord("test", logging.INFO, __file__, 1, "authorization=%s", ("Bearer secret",), None)
    record.event_data = {"authorization": "Bearer secret", "request_id": "request-1"}

    rendered = JsonFormatter().format(record)

    assert "secret" not in rendered
    assert "request-1" in rendered


def test_prometheus_metrics_have_stable_names_and_labels():
    record_http_request("GET", "/healthz", 200, 0.01)

    rendered = generate_latest().decode("utf-8")

    assert "eat_agent_http_requests_total" in rendered
    assert 'path="/healthz"' in rendered
    assert "conversation_id" not in rendered


def test_database_maintenance_scripts_accept_sqlalchemy_postgres_urls():
    sqlalchemy_url = "postgresql+psycopg://user:password@postgres:5432/eat_agent"
    libpq_url = "postgresql://user:password@postgres:5432/eat_agent"

    assert backup_pg_database_url(sqlalchemy_url) == libpq_url
    assert restore_pg_database_url(sqlalchemy_url) == libpq_url


@pytest.mark.parametrize("case", json.loads(Path("evaluation/grill_cases.json").read_text(encoding="utf-8")))
def test_grill_evaluation_cases(case):
    profile = get_profile("meal_planner")
    assert profile is not None

    result = GrillEngine().process(
        profile,
        case["question"],
        case.get("context"),
        current_intent="meal_planner",
    )

    assert result.action == case["expected_action"]
    assert result.target_field == case["expected_field"]
