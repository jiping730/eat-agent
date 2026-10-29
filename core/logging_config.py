"""Small JSON logging helpers for HTTP and workflow diagnostics."""

from __future__ import annotations

import json
import logging
import hashlib
import os
import re
import sys
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler
from typing import Any

from core.observability import observation_fields


_SENSITIVE_KEY = re.compile(r"(password|token|secret|api[_-]?key|authorization|cookie)", re.IGNORECASE)
_SENSITIVE_TEXT = re.compile(r"(?i)(bearer\s+)[^\s,}]+")


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": sanitize_text(record.getMessage()),
        }
        event_data = getattr(record, "event_data", None)
        if isinstance(event_data, dict):
            payload.update(sanitize_mapping(event_data))
        payload.update(observation_fields())
        return json.dumps(payload, ensure_ascii=False, default=str)


def _handler_matches_file(handler: logging.Handler, log_file: str) -> bool:
    if not isinstance(handler, RotatingFileHandler):
        return False
    return os.path.abspath(handler.baseFilename) == os.path.abspath(log_file)


def configure_logging(
    level: str = "INFO",
    log_file: str | None = None,
    max_bytes: int = 10 * 1024 * 1024,
    backup_count: int = 5,
) -> logging.Logger:
    """Configure JSON console logging and optional size-based file rotation.

    The function is intentionally idempotent because most application modules
    obtain the shared logger during import.  Console output remains enabled in
    every mode; the file handler is only added when ``log_file`` is non-empty.
    """

    logger = logging.getLogger("eat_agent")
    # Alembic's fileConfig may disable existing named loggers while running a
    # migration.  Re-enabling the shared application logger keeps later
    # requests and repeated test/application initialization observable.
    logger.disabled = False
    logger.setLevel(getattr(logging, level.upper(), logging.INFO))
    formatter = JsonFormatter()
    if not any(
        isinstance(handler, logging.StreamHandler) and not isinstance(handler, logging.FileHandler)
        for handler in logger.handlers
    ):
        stream = sys.stderr if os.getenv("MCP_STDIO", "").lower() == "1" else sys.stdout
        handler = logging.StreamHandler(stream)
        handler.setFormatter(formatter)
        logger.addHandler(handler)
    if log_file:
        path = os.path.abspath(os.path.expanduser(log_file))
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        if not any(_handler_matches_file(handler, path) for handler in logger.handlers):
            file_handler = RotatingFileHandler(
                path,
                maxBytes=max(1, int(max_bytes)),
                backupCount=max(0, int(backup_count)),
                encoding="utf-8",
            )
            file_handler.setFormatter(formatter)
            logger.addHandler(file_handler)
    for handler in logger.handlers:
        handler.setLevel(logger.level)
    logger.propagate = False
    return logger


def log_event(logger: logging.Logger, level: int, message: str, **data: Any) -> None:
    logger.log(level, sanitize_text(message), extra={"event_data": sanitize_mapping(data)})


def sanitize_text(value: str) -> str:
    return _SENSITIVE_TEXT.sub(r"\1[REDACTED]", value)


def sanitize_mapping(data: dict[str, Any]) -> dict[str, Any]:
    sanitized: dict[str, Any] = {}
    for key, value in data.items():
        if _SENSITIVE_KEY.search(str(key)):
            sanitized[key] = "[REDACTED]"
        elif isinstance(value, dict):
            sanitized[key] = sanitize_mapping(value)
        elif isinstance(value, str):
            sanitized[key] = sanitize_text(value)
        else:
            sanitized[key] = value
    return sanitized


def fingerprint(value: str | None) -> str | None:
    if not value:
        return None
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:12]
