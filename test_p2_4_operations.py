from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from alembic import command
from alembic.config import Config

from core.logging_config import configure_logging, log_event
from scripts import docker_cleanup, migration_check


def test_migration_check_reports_pending_then_up_to_date(tmp_path, monkeypatch):
    database_url = f"sqlite:///{tmp_path / 'migration.db'}"
    monkeypatch.setattr("config.settings.database_url", database_url)

    pending = migration_check.inspect_migrations()
    assert pending.pending is True
    assert pending.multiple_heads is False
    assert migration_check.main(["--require-up-to-date", "--json"]) == 1

    config = Config(str(Path.cwd() / "alembic.ini"))
    command.upgrade(config, "head")

    current = migration_check.inspect_migrations()
    assert current.up_to_date is True
    assert current.current_heads == current.heads
    assert migration_check.main(["--require-up-to-date", "--json"]) == 0


def test_logging_can_rotate_json_file(tmp_path):
    log_path = tmp_path / "logs" / "eat-agent.jsonl"
    logger = configure_logging("INFO", str(log_path), max_bytes=100, backup_count=1)
    try:
        for index in range(12):
            log_event(logger, 20, "rotation_test", index=index, message_value="x" * 80)
        for handler in logger.handlers:
            handler.flush()

        assert log_path.exists()
        assert log_path.with_name("eat-agent.jsonl.1").exists()
        assert json.loads(log_path.read_text(encoding="utf-8"))["logger"] == "eat_agent"
    finally:
        for handler in list(logger.handlers):
            if getattr(handler, "baseFilename", None) == str(log_path):
                handler.close()
                logger.removeHandler(handler)


def test_health_endpoints_expose_component_checks(monkeypatch, tmp_path):
    monkeypatch.setattr("config.settings.database_url", f"sqlite:///{tmp_path / 'health.db'}")
    import front.app as app_module

    monkeypatch.setattr(app_module.runtime.store, "ping", lambda: None)
    monkeypatch.setattr(app_module.runtime, "coordinator", SimpleNamespace(enabled=False, ping=lambda: None))

    live = app_module.health_live()
    ready = app_module.health_ready(SimpleNamespace(state=SimpleNamespace(request_id="test-request")))

    assert live["checks"] == {"application": "ok"}
    assert ready["status"] == "ready"
    assert ready["checks"] == {"database": "ok", "coordination": "disabled"}


def test_health_endpoint_returns_503_when_database_is_unavailable(monkeypatch, tmp_path):
    monkeypatch.setattr("config.settings.database_url", f"sqlite:///{tmp_path / 'health.db'}")
    import front.app as app_module

    def fail_ping():
        raise RuntimeError("database unavailable")

    monkeypatch.setattr(app_module.runtime.store, "ping", fail_ping)
    monkeypatch.setattr(app_module.runtime, "coordinator", SimpleNamespace(enabled=False, ping=lambda: None))

    response = app_module.health_ready(SimpleNamespace(state=SimpleNamespace(request_id="test-request")))

    assert response.status_code == 503
    payload = json.loads(response.body)
    assert payload["status"] == "not_ready"
    assert payload["checks"]["database"] == "error"


def test_docker_cleanup_plan_preserves_running_and_recent_images(monkeypatch):
    monkeypatch.setattr(
        docker_cleanup,
        "_project_containers",
        lambda project_name: [
            {"ID": "stopped-1", "Status": "Exited (0) 2 hours ago"},
            {"ID": "running-1", "Status": "Up 2 hours"},
        ],
    )
    monkeypatch.setattr(docker_cleanup, "_running_image_ids", lambda: {"sha-running-old"})
    monkeypatch.setattr(
        docker_cleanup,
        "_project_images",
        lambda repository: [
            {"ID": "sha-new", "Tag": "p2-4"},
            {"ID": "sha-rollback", "Tag": "p2-3"},
            {"ID": "sha-old", "Tag": "p1-4"},
            {"ID": "sha-running-old", "Tag": "legacy"},
        ],
    )

    plan = docker_cleanup.build_plan(project_name="eat-agent", keep_images=2)

    assert plan.stopped_containers == ("stopped-1",)
    assert plan.removable_images == ("sha-old",)
    assert set(plan.preserved_images) == {"sha-new", "sha-rollback", "sha-running-old"}
    assert plan.to_dict()["volumes_removed"] is False


def test_platform_script_has_safe_compose_actions():
    script = (Path(__file__).parent / "scripts" / "platform.ps1").read_text(encoding="utf-8")

    assert 'ValidateSet("start", "stop", "restart", "status", "logs")' in script
    assert 'Invoke-Compose @("stop")' in script
    assert 'Invoke-Compose @("up", "-d", "--build")' in script
    assert 'Invoke-Compose @("logs", "--tail", "200", "-f")' in script
    assert "down -v" not in script
