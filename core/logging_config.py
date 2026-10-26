"""Small JSON logging helpers for HTTP and workflow diagnostics."""

from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, timezone
from typing import Any


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        event_data = getattr(record, "event_data", None)
        if isinstance(event_data, dict):
            payload.update(event_data)
        return json.dumps(payload, ensure_ascii=False, default=str)


def configure_logging(level: str = "INFO") -> logging.Logger:
    logger = logging.getLogger("eat_agent")
    logger.setLevel(getattr(logging, level.upper(), logging.INFO))
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(JsonFormatter())
        logger.addHandler(handler)
    logger.propagate = False
    return logger


def log_event(logger: logging.Logger, level: int, message: str, **data: Any) -> None:
    logger.log(level, message, extra={"event_data": data})
