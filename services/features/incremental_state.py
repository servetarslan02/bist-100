"""ALPHA BIST — Incremental State Manager

Rolling feature state yönetimi. Feature'ların tam yeniden hesaplama olmadan
güncellenmesini sağlar. Her ticker ve feature için rolling buffer tutar.

Thread-safe: Paylaşılan singleton erişimi threading.Lock ile korunur.

Kullanım:
    from services.features.incremental_state import incremental_state

    # Yeni değer ekle
    incremental_state.update("GARAN", "rsi_14", 65.3)

    # Rolling penceredeki değerler
    values = incremental_state.get_rolling("GARAN", "rsi_14", window=20)

    # İstatistikler
    stats = incremental_state.get_stats("GARAN", "rsi_14", window=20)
"""

from __future__ import annotations

import threading
import time
from collections import deque

import numpy as np
import structlog

logger = structlog.get_logger()

# ---------------------------------------------------------------------------
# Sabitler
# ---------------------------------------------------------------------------

_DEFAULT_EMPTY_STAT: float = float("nan")
_DEFAULT_MAX_WINDOW: int = 500


# ---------------------------------------------------------------------------
# Ana sınıf
# ---------------------------------------------------------------------------


class IncrementalStateManager:
    """Artan (incremental) rolling state yöneticisi.

    Feature'ların tam yeniden hesaplama olmadan güncellenmesini sağlar.
    Her ticker ve feature için rolling buffer tutar.

    Thread-safe: Paylaşılan singleton erişimi threading.Lock ile korunur.
    Performans: deque ile O(1) ekleme/silme operasyonları.

    Özellikler:
        - Rolling buffer yönetimi (O(1) ekleme/silme)
        - Rolling istatistikler (mean, std, min, max, last)
        - NaN/Inf değer filtreleme
        - Thread-safe singleton erişimi
    """

    def __init__(self, max_window: int = _DEFAULT_MAX_WINDOW) -> None:
        """Incremental state manager başlatıcısı.

        Args:
            max_window: Her feature için maksimum rolling pencere boyutu.
                Değeri pozitif integer olmalıdır.

        Returns:
            None.

        Raises:
            ValueError: max_window pozitif değilse.
        """
        if max_window <= 0:
            raise ValueError(f"max_window pozitif olmalıdır, alınan: {max_window}")
        self.max_window = max_window
        self._buffers: dict[str, dict[str, deque[float]]] = {}
        self._last_update: dict[str, float] = {}
        self._lock = threading.Lock()

    def __repr__(self) -> str:
        """IncrementalStateManager kısa temsili.

        Returns:
            max_window ve toplam ticker sayısı.
        """
        with self._lock:
            ticker_count = len(self._buffers)
        return f"IncrementalStateManager(max_window={self.max_window}, tickers={ticker_count})"

    # ------------------------------------------------------------------
    # Dış API
    # ------------------------------------------------------------------

    def update(self, ticker: str, feature_name: str, value: float) -> None:
        """Rolling buffer'a yeni değer ekler.

        NaN ve Inf değerler filtrelenir — buffer'a eklenmez.
        Buffer max_window boyutunu aştığında en eski değer atılır (O(1)).

        Args:
            ticker: Hisse senedi kodu (örn: "GARAN").
            feature_name: Feature adı (örn: "rsi_14").
            value: Eklenecek değer.

        Returns:
            None.

        Raises:
            Yok — NaN/Inf değerler sessizce filtrelenir.
        """
        # NaN/Inf filtreleme
        if isinstance(value, float) and (value != value or value == float("inf") or value == float("-inf")):
            logger.debug(
                "nan_inf_filtered",
                ticker=ticker,
                feature=feature_name,
                value=str(value),
            )
            return

        with self._lock:
            if ticker not in self._buffers:
                self._buffers[ticker] = {}
            if feature_name not in self._buffers[ticker]:
                self._buffers[ticker][feature_name] = deque(maxlen=self.max_window)

            self._buffers[ticker][feature_name].append(value)
            self._last_update[ticker] = time.time()

    def get_rolling(self, ticker: str, feature_name: str, window: int | None = None) -> np.ndarray:
        """Rolling penceredeki değerleri döndürür.

        Args:
            ticker: Hisse senedi kodu.
            feature_name: Feature adı.
            window: Pencere boyutu. None ise tüm buffer döndürülür.
                Pozitif integer olmalıdır.

        Returns:
            Rolling değerlerin NumPy dizisi. Boş ise boş array döner.

        Raises:
            Yok — bulunamayan ticker/feature için boş array döner.
        """
        with self._lock:
            buf = self._buffers.get(ticker, {}).get(feature_name)
            if buf is None or len(buf) == 0:
                return np.array([])

            if window is not None and window <= 0:
                logger.warning(
                    "invalid_window",
                    ticker=ticker,
                    feature=feature_name,
                    window=window,
                )
                return np.array([])

            w = window if window is not None else len(buf)
            return np.array(list(buf))[-w:]

    def get_stats(self, ticker: str, feature_name: str, window: int = 20) -> dict[str, float]:
        """Feature için rolling istatistikleri döndürür.

        Args:
            ticker: Hisse senedi kodu.
            feature_name: Feature adı.
            window: İstatistik penceresi.

        Returns:
            İstatistik dict'i: mean, std, min, max, last.
            Boş array durumunda tüm değerler NaN döner.
        """
        arr = self.get_rolling(ticker, feature_name, window)
        if len(arr) == 0:
            return {
                "mean": _DEFAULT_EMPTY_STAT,
                "std": _DEFAULT_EMPTY_STAT,
                "min": _DEFAULT_EMPTY_STAT,
                "max": _DEFAULT_EMPTY_STAT,
                "last": _DEFAULT_EMPTY_STAT,
            }
        return {
            "mean": float(np.mean(arr)),
            "std": float(np.std(arr)),
            "min": float(np.min(arr)),
            "max": float(np.max(arr)),
            "last": float(arr[-1]),
        }

    def get_all_features(self, ticker: str) -> dict[str, float]:
        """Ticker için tüm feature'ların son değerlerini döndürür.

        Args:
            ticker: Hisse senedi kodu.

        Returns:
            Feature adı → son değer dict'i. Boş ticker için boş dict döner.
        """
        with self._lock:
            result: dict[str, float] = {}
            for fname, buf in self._buffers.get(ticker, {}).items():
                if buf:
                    result[fname] = float(buf[-1])
            return result

    def get_last_update(self, ticker: str) -> float | None:
        """Ticker'ın son güncelleme zamanını döndürür.

        Args:
            ticker: Hisse senedi kodu.

        Returns:
            Son güncelleme zamanı (epoch saniye) veya None.
        """
        with self._lock:
            return self._last_update.get(ticker)

    def get_buffer_size(self, ticker: str, feature_name: str) -> int:
        """Belirli bir ticker/feature buffer'ının mevcut boyutunu döndürür.

        Args:
            ticker: Hisse senedi kodu.
            feature_name: Feature adı.

        Returns:
            Buffer boyutu. Bulunamazsa 0 döner.
        """
        with self._lock:
            buf = self._buffers.get(ticker, {}).get(feature_name)
            return len(buf) if buf is not None else 0

    def get_ticker_count(self) -> int:
        """Kayıtlı ticker sayısını döndürür.

        Returns:
            Ticker sayısı.
        """
        with self._lock:
            return len(self._buffers)

    def get_feature_count(self, ticker: str) -> int:
        """Ticker için kayıtlı feature sayısını döndürür.

        Args:
            ticker: Hisse senedi kodu.

        Returns:
            Feature sayısı. Ticker bulunamazsa 0 döner.
        """
        with self._lock:
            return len(self._buffers.get(ticker, {}))

    def clear(self, ticker: str | None = None) -> int:
        """State'i sıfırlar.

        Args:
            ticker: Belirli bir ticker'ın state'ini sıfırlar.
                None ise tümünü sıfırlar.

        Returns:
            Silinen buffer sayısı.
        """
        with self._lock:
            if ticker is not None:
                removed = len(self._buffers.get(ticker, {}))
                self._buffers.pop(ticker, None)
                self._last_update.pop(ticker, None)
                logger.info("state_cleared", ticker=ticker, removed=removed)
                return removed
            else:
                total = sum(len(bufs) for bufs in self._buffers.values())
                self._buffers.clear()
                self._last_update.clear()
                logger.info("state_cleared_all", removed=total)
                return total


# Singleton
incremental_state = IncrementalStateManager()
