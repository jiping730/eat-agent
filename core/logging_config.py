"""Small JSON logging helpers for HTTP and workflow diagnostics."""

from __future__ import annotations

import json
import logging
import hashlib
import os
import re
import sys
from datetime import datetime, timezone
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


def configure_logging(level: str = "INFO") -> logging.Logger:
    logger = logging.getLogger("eat_agent")
    logger.setLevel(getattr(logging, level.upper(), logging.INFO))
    if not logger.handlers:
        stream = sys.stderr if os.getenv("MCP_STDIO", "").lower() == "1" else sys.stdout
        handler = logging.StreamHandler(stream)
        handler.setFormatter(JsonFormatter())
        logger.addHandler(handler)
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
