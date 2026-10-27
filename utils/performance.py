"""Small performance measurement decorator backed by structured logging."""

import time
from functools import wraps

from core.logging_config import configure_logging, log_event


logger = configure_logging()


def performance_stats(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        start = time.perf_counter()
        result = func(*args, **kwargs)
        elapsed = time.perf_counter() - start
        log_event(
            logger,
            20,
            "performance_measurement",
            function=func.__name__,
            duration_ms=round(elapsed * 1000, 2),
        )
        return result

    return wrapper
