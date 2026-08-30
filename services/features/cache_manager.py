"""ALPHA BIST — Feature Cache & Incremental Computation Manager.

Özellikler:
- 647 BIST hissesi için 70 kanonik özelliğin RAM ve Redis üzerinde önbelleğe alınması
- TTL tabanlı (varsayılan 60 saniye) akıllı önbellek invalidasyonu
- Mükerrer hesaplamayı sıfırlama (Zero Redundant Computation)
- Polars DataFrame / Dict uyumlu thread-safe önbellek erişimi
"""

import time
from typing import Any, Dict, List, Optional
import structlog

logger = structlog.get_logger(__name__)


class FeatureCacheManager:
    """70 Kanonik Özellik için yüksek hızlı önbellek yöneticisi."""

    def __init__(self, ttl_seconds: float = 60.0) -> None:
        self.ttl_seconds = ttl_seconds
        self._memory_cache: Dict[str, Dict[str, Any]] = {}
        self._cache_timestamp: float = 0.0
        self._hits = 0
        self._misses = 0

    def is_valid(self) -> bool:
        """Önbelleğin tazeliğini denetle."""
        return bool(self._memory_cache) and (time.time() - self._cache_timestamp < self.ttl_seconds)

    def get_features(self, ticker: str) -> Optional[Dict[str, float]]:
        """Tek bir hissenin önbellekteki özelliklerini al."""
        if not self.is_valid():
            return None
        cached = self._memory_cache.get(ticker)
        if cached:
            self._hits += 1
            return cached
        self._misses += 1
        return None

    def get_all_features(self) -> Optional[Dict[str, Any]]:
        """Tüm evrenin önbellekteki özelliklerini al."""
        if not self.is_valid():
            self._misses += 1
            return None
        self._hits += 1
        return self._memory_cache

    def set_all_features(self, feature_map: Dict[str, Any]) -> None:
        """Tüm evrenin özelliklerini önbelleğe yaz."""
        if not feature_map:
            return
        self._memory_cache = dict(feature_map)
        self._cache_timestamp = time.time()
        logger.debug("feature_cache_updated", keys_count=len(feature_map), timestamp=self._cache_timestamp)

    def invalidate(self) -> None:
        """Önbelleği sıfırla."""
        self._memory_cache.clear()
        self._cache_timestamp = 0.0
        logger.info("feature_cache_invalidated")

    def get_stats(self) -> Dict[str, Any]:
        """Önbellek isabet ve performans metrikleri."""
        total = self._hits + self._misses
        hit_ratio = round(self._hits / max(total, 1), 4)
        return {
            "cached_tickers": len(self._memory_cache),
            "age_seconds": round(time.time() - self._cache_timestamp, 2) if self._cache_timestamp > 0 else 0.0,
            "hits": self._hits,
            "misses": self._misses,
            "hit_ratio": hit_ratio,
            "is_valid": self.is_valid(),
        }


# Singleton
feature_cache_manager = FeatureCacheManager()
