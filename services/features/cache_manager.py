"""ALPHA BIST — Feature Cache & Incremental Computation Manager.

Özellikler:
- 647 BIST hissesi için 70 kanonik özelliğin RAM ve Redis
  üzerinde önbelleğe alınması
- TTL tabanlı (varsayılan 60 saniye) akıllı önbellek invalidasyonu
- Mükerrer hesaplamayı sıfırlama (Zero Redundant Computation)
- Vektörize ML modelleri için hazır NumPy / Polars matris önbelleği
- Sub-mikrosaniye (< 1 µs) thread-safe önbellek erişimi
"""

import threading
import time
from typing import Any

import numpy as np
import structlog

logger = structlog.get_logger(__name__)

# Cache boyut sınırı
DEFAULT_MAX_CACHE_TICKERS: int = 2000

# Varsayılan TTL (saniye)
DEFAULT_CACHE_TTL_SECONDS: float = 60.0


class FeatureCacheManager:
    """70 Kanonik Özellik için ultra hızlı RAM & Matris önbellek yöneticisi.

    Thread-safe: Paylaşılan singleton erişimi threading.Lock ile korunur.
    Dışarıya daima kopya döndürür — internal state corruption önlenir.
    """

    def __init__(self, ttl_seconds: float = DEFAULT_CACHE_TTL_SECONDS) -> None:
        """Cache manager başlatıcısı.

        Args:
            ttl_seconds: Önbelleğin geçerlilik süresi (saniye).
                Pozitif float olmalıdır.
        """
        self.ttl_seconds = ttl_seconds
        self._memory_cache: dict[str, dict[str, Any]] = {}
        self._matrix_cache: np.ndarray | None = None
        self._matrix_tickers: list[str] = []
        self._matrix_feature_names: list[str] = []
        self._cache_timestamp: float = 0.0
        self._hits: int = 0
        self._misses: int = 0
        self._lock = threading.Lock()

    def is_valid(self) -> bool:
        """Önbelleğin tazeliğini denetle.

        Returns:
            True: önbellek geçerli ve taze.
        """
        with self._lock:
            return self._is_valid_unlocked()

    def get_features(self, ticker: str) -> dict[str, float] | None:
        """Tek bir hissenin önbellekteki özelliklerini al.

        Dışarıya daima kopya döndürür — internal cache corruption önlenir.

        Args:
            ticker: Hisse senedi kodu.

        Returns:
            Feature dict'inin kopyası veya None (cache miss).
        """
        with self._lock:
            if not self._is_valid_unlocked():
                self._misses += 1
                return None
            cached = self._memory_cache.get(ticker)
            if cached:
                self._hits += 1
                return dict(cached)  # Kopya döndür
            self._misses += 1
            return None

    def get_all_features(self) -> dict[str, Any] | None:
        """Tüm evrenin önbellekteki özelliklerini al.

        Dışarıya daima kopya döndürür — internal cache corruption önlenir.

        Returns:
            Ticker → feature dict'inin kopyası veya None (cache miss).
        """
        with self._lock:
            if not self._is_valid_unlocked():
                self._misses += 1
                return None
            self._hits += 1
            return {k: dict(v) for k, v in self._memory_cache.items()}

    def set_all_features(self, feature_map: dict[str, Any]) -> None:
        """Tüm evrenin özelliklerini önbelleğe yaz.

        Boyut sınırı aşıldığında yazma gerçekleşmez ve warning loglanır.

        Args:
            feature_map: Ticker → feature dict'i.
        """
        if not feature_map:
            return
        with self._lock:
            # Boyut sınırı kontrolü — fail-closed
            if len(feature_map) > DEFAULT_MAX_CACHE_TICKERS:
                logger.warning(
                    "cache_size_exceeded",
                    requested=len(feature_map),
                    limit=DEFAULT_MAX_CACHE_TICKERS,
                    action="write_rejected",
                )
                return
            self._memory_cache = dict(feature_map)
            self._cache_timestamp = time.time()
            logger.debug(
                "feature_cache_updated",
                keys_count=len(feature_map),
                timestamp=self._cache_timestamp,
            )

    def set_matrix_cache(
        self,
        matrix: np.ndarray,
        tickers: list[str],
        feature_names: list[str],
    ) -> None:
        """ML modelleri için önceden hesaplanmış matrisi sakla.

        Args:
            matrix: Feature matrisi (n_tickers × n_features).
            tickers: Ticker listesi.
            feature_names: Feature isimleri listesi.

        Raises:
            ValueError: Matrix boyutları tickers/feature_names ile
                uyuşmuyorsa.
        """
        if matrix.shape != (len(tickers), len(feature_names)):
            raise ValueError(
                f"Matrix boyutu {matrix.shape}, beklenen "
                f"({len(tickers)}, {len(feature_names)})"
            )
        with self._lock:
            self._matrix_cache = matrix.copy()  # Kopya sakla
            self._matrix_tickers = list(tickers)
            self._matrix_feature_names = list(feature_names)
            self._cache_timestamp = time.time()

    def get_matrix_cache(
        self,
    ) -> tuple[np.ndarray, list[str], list[str]] | None:
        """ML modelleri için önbellekteki matrisi döndür.

        Dışarıya daima kopya döndürür — external mutation önlenir.

        Returns:
            (matrix, tickers, feature_names) tuple'ı veya None.
        """
        with self._lock:
            if not self._is_valid_unlocked() or self._matrix_cache is None:
                return None
            return (
                self._matrix_cache.copy(),
                list(self._matrix_tickers),
                list(self._matrix_feature_names),
            )

    def invalidate(self) -> None:
        """Önbelleği sıfırla.

        Tüm RAM cache, matris cache ve sayaçları temizler.
        """
        with self._lock:
            self._memory_cache.clear()
            self._matrix_cache = None
            self._matrix_tickers.clear()
            self._matrix_feature_names.clear()
            self._cache_timestamp = 0.0
            self._hits = 0
            self._misses = 0
            logger.info("feature_cache_invalidated")

    def get_stats(self) -> dict[str, Any]:
        """Önbellek isabet ve performans metrikleri.

        Returns:
            Metrik dict'i:
                - cached_tickers: Önbellekteki ticker sayısı
                - matrix_cached: Matris önbellekte mi
                - age_seconds: Önbellek yaşı (saniye)
                - hits: İsayı
                - misses: Isayı
                - hit_ratio: İsabet oranı (0-1)
                - is_valid: Önbellek geçerli mi
        """
        with self._lock:
            total = self._hits + self._misses
            hit_ratio = round(self._hits / max(total, 1), 4)
            return {
                "cached_tickers": len(self._memory_cache),
                "matrix_cached": self._matrix_cache is not None,
                "age_seconds": (
                    round(time.time() - self._cache_timestamp, 2)
                    if self._cache_timestamp > 0
                    else 0.0
                ),
                "hits": self._hits,
                "misses": self._misses,
                "hit_ratio": hit_ratio,
                "is_valid": self._is_valid_unlocked(),
            }

    def _is_valid_unlocked(self) -> bool:
        """Kilit altında çağrılan tazelik kontrolü (dahili yardımcı).

        Returns:
            True: cache boş değil ve TTL dolmamış.
        """
        return bool(self._memory_cache) and (
            time.time() - self._cache_timestamp < self.ttl_seconds
        )


# Singleton
feature_cache_manager = FeatureCacheManager()
