"""ALPHA BIST — Real Feature Store.

Redis ve bellek üzerinden anlık canlı öznitelikleri depolar ve sorgular.
"""

import math
import threading
from typing import Any

import structlog

from services.core.redis_helper import get_cached, set_cached

logger = structlog.get_logger()

# Feature varsayılan TTL (saniye)
DEFAULT_FEATURE_TTL_SECONDS: int = 3600


class FeatureStore:
    """Canlı Feature Store erişim katmanı.

    Thread-safe: Paylaşılan singleton erişimi threading.Lock ile korunur.
    """

    def __init__(self) -> None:
        """Feature Store başlatıcısı."""
        self._lock = threading.Lock()

    def get_all(self, ticker: str) -> dict[str, float]:
        """Hisseye ait tüm güncel öznitelikleri getir.

        Args:
            ticker: Hisse senedi kodu.

        Returns:
            Feature adı → değer dict'i. NaN/Inf değerler filtrelenir.
        """
        with self._lock:
            cached = get_cached(f"features:{ticker}")
            if cached and isinstance(cached, dict):
                result = {}
                for k, v in cached.items():
                    if isinstance(v, (int, float)):
                        val = float(v)
                        if not (math.isnan(val) or math.isinf(val)):
                            result[k] = val
                    elif isinstance(v, str):
                        try:
                            val = float(v)
                            if not (math.isnan(val) or math.isinf(val)):
                                result[k] = val
                        except (ValueError, TypeError):
                            continue
                return result
            return {}

    def set_features(self, ticker: str, features: dict[str, float], ttl: int | None = None) -> None:
        """Öznitelikleri Redis'e kaydet.

        Args:
            ticker: Hisse senedi kodu.
            features: Feature adı → değer dict'i.
            ttl: Önbellek süresi (saniye). None ise varsayılan kullanılır.
        """
        if ttl is None:
            ttl = DEFAULT_FEATURE_TTL_SECONDS
        if features:
            set_cached(f"features:{ticker}", features, ttl=ttl)


feature_store = FeatureStore()
