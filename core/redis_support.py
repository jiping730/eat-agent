"""Optional Redis coordination for multi-worker and multi-pod deployments."""

from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

from config import settings

try:
    import redis
except ImportError:  # pragma: no cover - production dependencies include redis
    redis = None  # type: ignore[assignment]


class RedisCoordinator:
    def __init__(self, url: str | None = None) -> None:
        self.url = url or settings.redis_url
        self.client = None
        if self.url and redis is not None:
            self.client = redis.Redis.from_url(self.url, decode_responses=True)

    def ping(self) -> None:
        if self.client is not None:
            self.client.ping()

    @property
    def enabled(self) -> bool:
        return self.client is not None

    @contextmanager
    def conversation_lock(self, conversation_id: str) -> Iterator[None]:
        if self.client is None:
            yield
            return

        lock = self.client.lock(
            f"eat-agent:conversation:{conversation_id}",
            timeout=max(5, settings.redis_lock_timeout_seconds),
            blocking_timeout=max(1, settings.redis_lock_timeout_seconds),
        )
        acquired = lock.acquire(blocking=True)
        if not acquired:
            raise TimeoutError("会话正在处理中，请稍后重试")
        try:
            yield
        finally:
            try:
                lock.release()
            except redis.exceptions.LockError:
                pass
