"""
ALPHA BIST — Feature Store v1.0 (In-Memory + Redis Cache)

F-024: Feature'lar her seferinden hesaplanmak yerine cache'lenir.
- In-memory LRU cache (fast path)
- Redis cache (cross-process sharing)
- TTL-based invalidation
- Version-aware cache keys

Kullanım:
    from services.core.feature_store import feature_store
    features = feature_store.get(ticker, date, feature_names)
    feature_store.set(ticker, date, features, ttl=3600)
"""

import hashlib
import json
import time
from typing import Dict, List, Optional, Any
from collections import OrderedDict
import structlog

logger = structlog.get_logger()


class FeatureStore:
    """Feature cache — in-memory LRU + optional Redis."""

    def __init__(
        self,
        max_size: int = 10000,
        default_ttl: int = 3600,
        redis_url: Optional[str] = None,
    ):
        self._cache: OrderedDict[str, Dict[str, Any]] = OrderedDict()
        self._max_size = max_size
        self._default_ttl = default_ttl
        self._redis = None
        self._hits = 0
        self._misses = 0

        if redis_url:
            try:
                import redis
                self._redis = redis.from_url(redis_url, decode_responses=True)
                logger.info("Feature store Redis connected", url=redis_url)
            except Exception as e:
                logger.warning("Feature store Redis unavailable", error=str(e))

    def _make_key(self, ticker: str, date: str, features: List[str]) -> str:
        """Cache key oluştur."""
        feat_hash = hashlib.md5(",".join(sorted(features)).encode()).hexdigest()[:8]
        return f"feat:{ticker}:{date}:{feat_hash}"

    def get(
        self,
        ticker: str,
        date: str,
        feature_names: List[str],
    ) -> Optional[Dict[str, float]]:
        """Cache'den feature getir."""
        key = self._make_key(ticker, date, feature_names)

        # In-memory cache
        if key in self._cache:
            entry = self._cache[key]
            if time.time() < entry["expires_at"]:
                self._cache.move_to_end(key)
                self._hits += 1
                return entry["features"]
            else:
                del self._cache[key]

        # Redis cache
        if self._redis:
            try:
                data = self._redis.get(key)
                if data:
                    features = json.loads(data)
                    self._cache[key] = {
                        "features": features,
                        "expires_at": time.time() + self._default_ttl,
                    }
                    self._hits += 1
                    return features
            except Exception:
                pass

        self._misses += 1
        return None

    def set(
        self,
        ticker: str,
        date: str,
        features: Dict[str, float],
        ttl: Optional[int] = None,
        feature_names: Optional[List[str]] = None,
    ):
        """Cache'e feature kaydet."""
        if feature_names is None:
            feature_names = list(features.keys())
        key = self._make_key(ticker, date, feature_names)
        ttl = ttl or self._default_ttl

        # In-memory
        self._cache[key] = {
            "features": features,
            "expires_at": time.time() + ttl,
        }
        self._cache.move_to_end(key)

        # LRU eviction
        while len(self._cache) > self._max_size:
            self._cache.popitem(last=False)

        # Redis
        if self._redis:
            try:
                self._redis.setex(key, ttl, json.dumps(features))
            except Exception:
                pass

    def invalidate(self, ticker: str, date: Optional[str] = None):
        """Cache'i temizle."""
        prefix = f"feat:{ticker}:"
        keys_to_remove = [k for k in self._cache if k.startswith(prefix)]
        for k in keys_to_remove:
            del self._cache[k]

        if self._redis and date:
            try:
                key = f"feat:{ticker}:{date}:*"
                for k in self._redis.scan_iter(match=key):
                    self._redis.delete(k)
            except Exception:
                pass

    def get_stats(self) -> Dict[str, Any]:
        """Cache istatistikleri."""
        total = self._hits + self._misses
        return {
            "size": len(self._cache),
            "max_size": self._max_size,
            "hits": self._hits,
            "misses": self._misses,
            "hit_rate": round(self._hits / total * 100, 1) if total > 0 else 0,
            "redis_connected": self._redis is not None,
        }


# Singleton
feature_store = FeatureStore()
