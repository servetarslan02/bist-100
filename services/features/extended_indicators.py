"""
ALPHA BIST — Extended Technical Indicators v1.0

FAZ 2'de eksik olan teknik indikatörler:
- Ichimoku Cloud
- Fibonacci Retracement
- VWAP
- Pivot Points
- Heikin-Ashi
- Elder Ray
- Keltner Channels
- Donchian Channels
- ROC çoklu periyot
- ATR çoklu periyot
"""

import numpy as np
from typing import Dict, List
import structlog

logger = structlog.get_logger()


class ExtendedIndicators:
    """Genişletilmiş teknik indikatörler."""

    def compute_ichimoku(self, high: np.ndarray, low: np.ndarray, close: np.ndarray) -> Dict[str, float]:
        """Ichimoku Cloud."""
        n = len(close)
        if n < 52:
            return {}

        # Tenkan-sen (Conversion Line): (9-period high + 9-period low) / 2
        tenkan = (np.max(high[-9:]) + np.min(low[-9:])) / 2

        # Kijun-sen (Base Line): (26-period high + 26-period low) / 2
        kijun = (np.max(high[-26:]) + np.min(low[-26:])) / 2

        # Senkou Span A: (Tenkan + Kijun) / 2
        span_a = (tenkan + kijun) / 2

        # Senkou Span B: (52-period high + 52-period low) / 2
        span_b = (np.max(high[-52:]) + np.min(low[-52:])) / 2

        # Cloud
        cloud_top = max(span_a, span_b)
        cloud_bottom = min(span_a, span_b)

        return {
            "ichimoku_tenkan": round(float(tenkan), 2),
            "ichimoku_kijun": round(float(kijun), 2),
            "ichimoku_span_a": round(float(span_a), 2),
            "ichimoku_span_b": round(float(span_b), 2),
            "ichimoku_cloud_top": round(float(cloud_top), 2),
            "ichimoku_cloud_bottom": round(float(cloud_bottom), 2),
            "ichimoku_above_cloud": 1.0 if close[-1] > cloud_top else 0.0,
            "ichimoku_below_cloud": 1.0 if close[-1] < cloud_bottom else 0.0,
        }

    def compute_fibonacci(self, high: np.ndarray, low: np.ndarray, close: np.ndarray, period: int = 20) -> Dict[str, float]:
        """Fibonacci Retracement levels."""
        if len(high) < period:
            return {}

        swing_high = np.max(high[-period:])
        swing_low = np.min(low[-period:])
        diff = swing_high - swing_low

        levels = {
            "fib_0": round(float(swing_low), 2),
            "fib_236": round(float(swing_low + diff * 0.236), 2),
            "fib_382": round(float(swing_low + diff * 0.382), 2),
            "fib_500": round(float(swing_low + diff * 0.500), 2),
            "fib_618": round(float(swing_low + diff * 0.618), 2),
            "fib_786": round(float(swing_low + diff * 0.786), 2),
            "fib_100": round(float(swing_high), 2),
        }

        # Mevcut fiyatın hangi seviyede olduğunu belirle
        price = close[-1]
        if diff > 0:
            position = (price - swing_low) / diff
            levels["fib_position"] = round(float(position), 4)

        return levels

    def compute_vwap(self, high: np.ndarray, low: np.ndarray, close: np.ndarray, volume: np.ndarray) -> Dict[str, float]:
        """VWAP (Volume Weighted Average Price)."""
        if len(close) < 1:
            return {}

        typical_price = (high + low + close) / 3
        cumulative_tp_vol = np.cumsum(typical_price * volume)
        cumulative_vol = np.cumsum(volume)

        vwap = cumulative_tp_vol[-1] / cumulative_vol[-1] if cumulative_vol[-1] > 0 else close[-1]

        # VWAP bands
        n = min(20, len(close))
        squared_diff = (typical_price[-n:] - vwap) ** 2
        vwap_std = np.sqrt(np.mean(squared_diff))

        return {
            "vwap": round(float(vwap), 2),
            "vwap_upper_1": round(float(vwap + vwap_std), 2),
            "vwap_upper_2": round(float(vwap + 2 * vwap_std), 2),
            "vwap_lower_1": round(float(vwap - vwap_std), 2),
            "vwap_lower_2": round(float(vwap - 2 * vwap_std), 2),
            "vwap_distance_pct": round(float((close[-1] / vwap - 1) * 100), 2),
        }

    def compute_pivot_points(self, high: np.ndarray, low: np.ndarray, close: np.ndarray) -> Dict[str, float]:
        """Pivot Points (Classic)."""
        if len(high) < 1:
            return {}

        h = float(high[-1])
        l = float(low[-1])
        c = float(close[-1])

        pivot = (h + l + c) / 3

        return {
            "pivot": round(pivot, 2),
            "pivot_r1": round(2 * pivot - l, 2),
            "pivot_r2": round(pivot + (h - l), 2),
            "pivot_r3": round(h + 2 * (pivot - l), 2),
            "pivot_s1": round(2 * pivot - h, 2),
            "pivot_s2": round(pivot - (h - l), 2),
            "pivot_s3": round(l - 2 * (h - pivot), 2),
        }

    def compute_heikin_ashi(self, open_: np.ndarray, high: np.ndarray, low: np.ndarray, close: np.ndarray) -> Dict[str, float]:
        """Heikin-Ashi candles."""
        if len(close) < 2:
            return {}

        # HA Close = (O + H + L + C) / 4
        ha_close = (open_[-1] + high[-1] + low[-1] + close[-1]) / 4

        # HA Open = (prev_HA_open + prev_HA_close) / 2
        prev_ha_close = (open_[-2] + high[-2] + low[-2] + close[-2]) / 4
        ha_open = (open_[-2] + prev_ha_close) / 2

        # HA High = max(H, HA_open, HA_close)
        ha_high = max(high[-1], ha_open, ha_close)

        # HA Low = min(L, HA_open, HA_close)
        ha_low = min(low[-1], ha_open, ha_close)

        # Trend
        bullish = ha_close > ha_open

        return {
            "ha_open": round(float(ha_open), 2),
            "ha_high": round(float(ha_high), 2),
            "ha_low": round(float(ha_low), 2),
            "ha_close": round(float(ha_close), 2),
            "ha_bullish": 1.0 if bullish else 0.0,
            "ha_body_size": round(float(abs(ha_close - ha_open)), 2),
        }

    def compute_elder_ray(self, close: np.ndarray, period: int = 13) -> Dict[str, float]:
        """Elder Ray (Bull/Bear Power)."""
        if len(close) < period:
            return {}

        ema = self._ema(close, period)
        bull_power = close[-1] - ema
        bear_power = close[-1] - ema  # Same calculation, interpretation differs

        return {
            "elder_bull_power": round(float(bull_power), 4),
            "elder_bear_power": round(float(bear_power), 4),
            "elder_signal": 1.0 if bull_power > 0 and bear_power > 0 else -1.0 if bull_power < 0 and bear_power < 0 else 0.0,
        }

    def compute_keltner(self, high: np.ndarray, low: np.ndarray, close: np.ndarray, period: int = 20, multiplier: float = 2.0) -> Dict[str, float]:
        """Keltner Channels."""
        if len(close) < period:
            return {}

        ema = self._ema(close, period)

        # ATR
        tr = np.maximum(
            high[1:] - low[1:],
            np.maximum(np.abs(high[1:] - close[:-1]), np.abs(low[1:] - close[:-1]))
        )
        atr = np.mean(tr[-period:])

        upper = ema + multiplier * atr
        lower = ema - multiplier * atr

        return {
            "keltner_middle": round(float(ema), 2),
            "keltner_upper": round(float(upper), 2),
            "keltner_lower": round(float(lower), 2),
            "keltner_position": round(float((close[-1] - lower) / (upper - lower)), 4) if (upper - lower) > 0 else 0.5,
        }

    def compute_donchian(self, high: np.ndarray, low: np.ndarray, close: np.ndarray, period: int = 20) -> Dict[str, float]:
        """Donchian Channels."""
        if len(high) < period:
            return {}

        upper = np.max(high[-period:])
        lower = np.min(low[-period:])
        middle = (upper + lower) / 2

        return {
            "donchian_upper": round(float(upper), 2),
            "donchian_middle": round(float(middle), 2),
            "donchian_lower": round(float(lower), 2),
            "donchian_width": round(float((upper - lower) / middle * 100), 2) if middle > 0 else 0,
        }

    def compute_roc_multi(self, close: np.ndarray, periods: List[int] = [5, 10, 20, 60]) -> Dict[str, float]:
        """ROC (Rate of Change) çoklu periyot."""
        features = {}
        n = len(close)
        for p in periods:
            if n > p and close[-p] > 0:
                features[f"roc_{p}d"] = round(float((close[-1] / close[-p] - 1) * 100), 2)
        return features

    def compute_atr_multi(self, high: np.ndarray, low: np.ndarray, close: np.ndarray, periods: List[int] = [5, 14, 20]) -> Dict[str, float]:
        """ATR çoklu periyot."""
        features = {}
        n = len(close)
        if n < 2:
            return features

        tr = np.maximum(
            high[1:] - low[1:],
            np.maximum(np.abs(high[1:] - close[:-1]), np.abs(low[1:] - close[:-1]))
        )

        for p in periods:
            if len(tr) >= p:
                atr = np.mean(tr[-p:])
                features[f"atr_{p}"] = round(float(atr), 4)
                features[f"atr_{p}_pct"] = round(float(atr / close[-1] * 100), 4) if close[-1] > 0 else 0

        return features

    def _ema(self, data: np.ndarray, period: int) -> float:
        """EMA hesapla."""
        alpha = 2.0 / (period + 1)
        ema = data[0]
        for price in data[1:]:
            ema = alpha * price + (1 - alpha) * ema
        return float(ema)

    def compute_all_extended(self, high: np.ndarray, low: np.ndarray, close: np.ndarray, volume: np.ndarray, open_: np.ndarray) -> Dict[str, float]:
        """Tüm extended indikatörleri hesapla."""
        features = {}
        features.update(self.compute_ichimoku(high, low, close))
        features.update(self.compute_fibonacci(high, low, close))
        features.update(self.compute_vwap(high, low, close, volume))
        features.update(self.compute_pivot_points(high, low, close))
        features.update(self.compute_heikin_ashi(open_, high, low, close))
        features.update(self.compute_elder_ray(close))
        features.update(self.compute_keltner(high, low, close))
        features.update(self.compute_donchian(high, low, close))
        features.update(self.compute_roc_multi(close))
        features.update(self.compute_atr_multi(high, low, close))
        return features


# Singleton
extended_indicators = ExtendedIndicators()
