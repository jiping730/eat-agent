"""Shared Redis limiter with a process-local fallback for development."""

from __future__ import annotations

import threading
import time
from collections import defaultdict, deque

from config import settings

try:
    import redis
except ImportError:  # pragma: no cover - production dependencies include redis
    redis = None


class SlidingWindowRateLimiter:
    def __init__(self, limit: int, window_seconds: int = 60, redis_url: str | None = None) -> None:
        self.limit = max(0, limit)
        self.window_seconds = window_seconds
        self._events: defaultdict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()
        self._redis = None
        configured_url = redis_url or settings.redis_url
        if configured_url and redis is not None:
            self._redis = redis.Redis.from_url(configured_url, decode_responses=True)

    def allow(self, key: str) -> bool:
        if self.limit <= 0:
            return True
        if self._redis is not None:
            bucket = int(time.time() // self.window_seconds)
            redis_key = f"eat-agent:rate:{key}:{bucket}"
            count = self._redis.incr(redis_key)
            if count == 1:
                self._redis.expire(redis_key, self.window_seconds + 1)
            return count <= self.limit

        now = time.monotonic()
        cutoff = now - self.window_seconds
        with self._lock:
            events = self._events[key]
            while events and events[0] <= cutoff:
                events.popleft()
            if len(events) >= self.limit:
                return False
            events.append(now)
            return True
