# Incremental State Manager
# Maintains rolling feature state for incremental computation

from __future__ import annotations

import time
import threading

import numpy as np


# Boş array istatistiği yerine döndürülecek değer
DEFAULT_EMPTY_STAT: float = float("nan")


class IncrementalStateManager:
    """Artan (incremental) rolling state yöneticisi.

    Feature'ların tam yeniden hesaplama olmadan güncellenmesini sağlar.
    Her ticker ve feature için rolling buffer tutar.

    Thread-safe: Paylaşılan singleton erişimi threading.Lock ile korunur.
    """

    def __init__(self, max_window: int = 500) -> None:
        """Incremental state manager başlatıcısı.

        Args:
            max_window: Her feature için maksimum rolling pencere boyutu.
                Değeri pozitif integer olmalıdır.

        Raises:
            ValueError: max_window pozitif değilse.
        """
        if max_window <= 0:
            raise ValueError(f"max_window pozitif olmalıdır, alınan: {max_window}")
        self.max_window = max_window
        self._buffers: dict[str, dict[str, list[float]]] = {}
        self._last_update: dict[str, float] = {}
        self._lock = threading.Lock()

    def update(self, ticker: str, feature_name: str, value: float) -> None:
        """Rolling buffer'a yeni değer ekle.

        Args:
            ticker: Hisse senedi kodu.
            feature_name: Feature adı.
            value: Eklenecek değer.
        """
        with self._lock:
            if ticker not in self._buffers:
                self._buffers[ticker] = {}
            if feature_name not in self._buffers[ticker]:
                self._buffers[ticker][feature_name] = []

            buf = self._buffers[ticker][feature_name]
            buf.append(value)
            if len(buf) > self.max_window:
                buf.pop(0)

            self._last_update[ticker] = time.time()

    def get_rolling(self, ticker: str, feature_name: str, window: int | None = None) -> np.ndarray:
        """Rolling penceredeki değerleri döndür.

        Args:
            ticker: Hisse senedi kodu.
            feature_name: Feature adı.
            window: Pencere boyutu (None = tüm buffer).

        Returns:
            Rolling değerlerin NumPy dizisi.
        """
        with self._lock:
            buf = self._buffers.get(ticker, {}).get(feature_name, [])
            if not buf:
                return np.array([])
            w = window or len(buf)
            return np.array(buf[-w:])

    def get_stats(self, ticker: str, feature_name: str, window: int = 20) -> dict[str, float]:
        """Feature için rolling istatistikleri döndür.

        Args:
            ticker: Hisse senedi kodu.
            feature_name: Feature adı.
            window: İstatistik penceresi.

        Returns:
            İstatistik dict'i: mean, std, min, max, last.
            Boş array durumunda NaN döndürür.
        """
        arr = self.get_rolling(ticker, feature_name, window)
        if len(arr) == 0:
            return {
                "mean": DEFAULT_EMPTY_STAT,
                "std": DEFAULT_EMPTY_STAT,
                "min": DEFAULT_EMPTY_STAT,
                "max": DEFAULT_EMPTY_STAT,
                "last": DEFAULT_EMPTY_STAT,
            }
        return {
            "mean": float(np.mean(arr)),
            "std": float(np.std(arr)),
            "min": float(np.min(arr)),
            "max": float(np.max(arr)),
            "last": float(arr[-1]),
        }

    def get_all_features(self, ticker: str) -> dict[str, float]:
        """Ticker için tüm feature'ların son değerlerini döndür.

        Args:
            ticker: Hisse senedi kodu.

        Returns:
            Feature adı → son değer dict'i.
        """
        with self._lock:
            result = {}
            for fname, buf in self._buffers.get(ticker, {}).items():
                if buf:
                    result[fname] = float(buf[-1])
            return result

    def clear(self, ticker: str | None = None) -> None:
        """State'i sıfırla.

        Args:
            ticker: Belirli bir ticker'ın state'ini sıfırla. None ise tümünü sıfırla.
        """
        with self._lock:
            if ticker:
                self._buffers.pop(ticker, None)
                self._last_update.pop(ticker, None)
            else:
                self._buffers.clear()
                self._last_update.clear()


# Singleton
incremental_state = IncrementalStateManager()
