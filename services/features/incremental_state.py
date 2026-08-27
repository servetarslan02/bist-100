# Incremental State Manager
# Maintains rolling feature state for incremental computation

from __future__ import annotations

import time

import numpy as np


class IncrementalStateManager:
    """Maintains incremental rolling state for features to avoid full recomputation."""

    def __init__(self, max_window: int = 500):
        self.max_window = max_window
        self._buffers: dict[str, dict[str, list[float]]] = {}
        self._last_update: dict[str, float] = {}

    def update(self, ticker: str, feature_name: str, value: float) -> None:
        """Append a new value to the rolling buffer."""
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
        """Get rolling window of values."""
        buf = self._buffers.get(ticker, {}).get(feature_name, [])
        if not buf:
            return np.array([])
        w = window or len(buf)
        return np.array(buf[-w:])

    def get_stats(self, ticker: str, feature_name: str, window: int = 20) -> dict[str, float]:
        """Get rolling statistics for a feature."""
        arr = self.get_rolling(ticker, feature_name, window)
        if len(arr) == 0:
            return {"mean": 0.0, "std": 0.0, "min": 0.0, "max": 0.0, "last": 0.0}
        return {
            "mean": float(np.mean(arr)),
            "std": float(np.std(arr)),
            "min": float(np.min(arr)),
            "max": float(np.max(arr)),
            "last": float(arr[-1]),
        }

    def get_all_features(self, ticker: str) -> dict[str, float]:
        """Get latest values of all features for a ticker."""
        result = {}
        for fname, buf in self._buffers.get(ticker, {}).items():
            if buf:
                result[fname] = float(buf[-1])
        return result

    def clear(self, ticker: str | None = None) -> None:
        """Clear state for a ticker or all."""
        if ticker:
            self._buffers.pop(ticker, None)
            self._last_update.pop(ticker, None)
        else:
            self._buffers.clear()
            self._last_update.clear()


# Singleton
incremental_state = IncrementalStateManager()
