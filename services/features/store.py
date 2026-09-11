"""ALPHA BIST — Real Feature Store.

Redis ve bellek üzerinden anlık canlı öznitelikleri depolar ve sorgular.

Kullanım:
    from services.features.store import feature_store
    features = feature_store.get_all("GARAN")
    feature_store.set_features("GARAN", {"rsi_14": 65.3})
"""

import math
import threading

import structlog

from services.core.redis_helper import get_cached, set_cached

logger = structlog.get_logger()

# Feature varsayılan TTL (saniye)
DEFAULT_FEATURE_TTL_SECONDS: int = 3600


class FeatureStore:
    """Canlı Feature Store erişim katmanı.

    Thread-safe: Paylaşılan singleton erişimi threading.Lock ile korunur.
    """

    def __repr__(self) -> str:
        return "FeatureStore()"

    def __init__(self) -> None:
        """Feature Store başlatıcısı."""
        self._lock = threading.Lock()

    def get_all(self, ticker: str) -> dict[str, float]:
        """Hisseye ait tüm güncel öznitelikleri getir.

        Args:
            ticker: Hisse senedi kodu.

        Returns:
            Feature adı → değer dict'i. NaN/Inf değerler filtrelenir.

        Raises:
            RuntimeError: Redis erişiminde hata oluşursa.
        """
        with self._lock:
            try:
                cached = get_cached(f"features:{ticker}")
            except Exception as exc:
                logger.error("feature_store_redis_error", ticker=ticker, error=str(exc))
                raise RuntimeError(f"Redis erişimi başarısız (ticker={ticker}): {exc}") from exc

            if cached is None:
                logger.warning("feature_store_cache_miss", ticker=ticker)
                return {}

            if not isinstance(cached, dict):
                logger.warning("feature_store_invalid_cache_type", ticker=ticker)
                return {}

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

    def set_features(self, ticker: str, features: dict[str, float], ttl: int | None = None) -> None:
        """Öznitelikleri Redis'e kaydet.

        Args:
            ticker: Hisse senedi kodu.
            features: Feature adı → değer dict'i.
            ttl: Önbellek süresi (saniye). None ise varsayılan kullanılır.

        Raises:
            RuntimeError: Redis yazma hatası oluşursa.
        """
        if ttl is None:
            ttl = DEFAULT_FEATURE_TTL_SECONDS
        if not features:
            logger.debug("feature_store_empty_features", ticker=ticker)
            return
        try:
            set_cached(f"features:{ticker}", features, ttl=ttl)
        except Exception as exc:
            logger.error("feature_store_write_error", ticker=ticker, error=str(exc))
            raise RuntimeError(f"Redis yazma başarısız (ticker={ticker}): {exc}") from exc
        logger.debug("feature_store_written", ticker=ticker, feature_count=len(features), ttl=ttl)


__all__: list[str] = ["FeatureStore", "feature_store"]

feature_store = FeatureStore()
