"""Thread-safe SWR (Stale-While-Revalidate) in-memory cache for API endpoints."""

from __future__ import annotations

import hashlib
import threading
import time
from typing import Any

import orjson


class SWRCache:
    """Thread-safe Stale-While-Revalidate cache.

    Replaces global mutable state (_CACHE, _TIME, _ETAG) patterns.
    """

    def __init__(self, ttl_seconds: int = 60):
        self._ttl = ttl_seconds
        self._data: Any = None
        self._timestamp: float = 0.0
        self._etag: str = ""
        self._lock = threading.Lock()

    @property
    def is_fresh(self) -> bool:
        """Cache hâlâ taze mi?"""
        return (time.time() - self._timestamp) < self._ttl

    @property
    def etag(self) -> str:
        """Mevcut ETag değeri."""
        return self._etag

    def get(self) -> Any | None:
        """Taze cache varsa döndür, yoksa None."""
        with self._lock:
            if self.is_fresh:
                return self._data
            return None

    def set(self, data: Any) -> str:
        """Cache'i güncelle ve yeni ETag döndür."""
        etag = hashlib.md5(orjson.dumps(data)).hexdigest()[:16]
        with self._lock:
            self._data = data
            self._timestamp = time.time()
            self._etag = etag
        return etag

    def invalidate(self) -> None:
        """Cache'i temizle."""
        with self._lock:
            self._data = None
            self._timestamp = 0.0
            self._etag = ""
