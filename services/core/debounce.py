"""SSD Write Debounce Utility — Dosya yazma sıklığını sınırlar."""

import time
from collections.abc import Callable
from functools import wraps
from typing import Any

import structlog

logger = structlog.get_logger(__name__)

# Global debounce state: key → last_write_timestamp
_last_writes: dict[str, float] = {}


def debounced_save(key: str, min_interval_sec: float = 30.0) -> Callable:
    """Decorator: Dosya save fonksiyonlarını debounce eder.

    Kullanım:
        @debounced_save("my_service", min_interval_sec=30)
        def save(self):
            ...  # Gerçek kayıt
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args, **kwargs) -> Any:
            now = time.time()
            last = _last_writes.get(key, 0)
            if now - last < min_interval_sec:
                logger.debug("Save debounced", key=key, elapsed=round(now - last, 1))
                return None
            _last_writes[key] = now
            return func(*args, **kwargs)
        return wrapper
    return decorator


def should_save(key: str, min_interval_sec: float = 30.0) -> bool:
    """Imperatif kullanım: Son yazmadan bu kadar süre geçtiyse True döner.

    Kullanım:
        if should_save("my_service", 30):
            _do_actual_save()
    """
    now = time.time()
    last = _last_writes.get(key, 0)
    if now - last < min_interval_sec:
        return False
    _last_writes[key] = now
    return True
