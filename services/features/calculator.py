"""ALPHA BIST - Feature Calculator (50+ Technical & Derived Features)"""

import numpy as np
import polars as pl
from typing import Dict, List, Optional, Any
from datetime import datetime, timedelta
import structlog

logger = structlog.get_logger()


class FeatureCalculator:
    """Calculates technical and derived features for market data."""

    def compute_all_features(self, df: pl.DataFrame) -> Dict[str, float]:
        """Compute all features for a single instrument's OHLCV data."""
        if df.is_empty() or len(df) < 20:
            return {}

        features = {}

        # Ensure sorted by timestamp
        df = df.sort("timestamp")

        close = df["close"].to_numpy()
        high = df["high"].to_numpy()
        low = df["low"].to_numpy()
        volume = df["volume"].to_numpy()
        open_ = df["open"].to_numpy()

        # === Price Returns ===
        features.update(self._compute_returns(close))

        # === Volume Features ===
        features.update(self._compute_volume_features(volume))

        # === Momentum Features ===
        features.update(self._compute_momentum(close))

        # === Volatility Features ===
        features.update(self._compute_volatility(close, high, low))

        # === Technical Indicators ===
        features.update(self._compute_technical(close, high, low, volume))

        # === Trend Features ===
        features.update(self._compute_trend(close, high, low))

        # === Price Pattern Features ===
        features.update(self._compute_price_patterns(close, high, low, open_))

        return features

    # =====================================================
    # Returns
    # =====================================================

    def _compute_returns(self, close: np.ndarray) -> Dict[str, float]:
        """Compute return features."""
        features = {}
        n = len(close)

        if n < 2:
            return features

        features["return_1d"] = (close[-1] / close[-2] - 1) * 100 if n >= 2 else 0
        features["return_5d"] = (close[-1] / close[-5] - 1) * 100 if n >= 5 else 0
        features["return_10d"] = (close[-1] / close[-10] - 1) * 100 if n >= 10 else 0
        features["return_20d"] = (close[-1] / close[-20] - 1) * 100 if n >= 20 else 0
        features["return_60d"] = (close[-1] / close[-60] - 1) * 100 if n >= 60 else 0

        # Log returns
        log_returns = np.diff(np.log(np.maximum(close, 1e-10)))
        features["log_return_1d"] = log_returns[-1] * 100 if len(log_returns) > 0 else 0

        return features

    # =====================================================
    # Volume Features
    # =====================================================

    def _compute_volume_features(self, volume: np.ndarray) -> Dict[str, float]:
        """Compute volume-based features."""
        features = {}
        n = len(volume)

        if n < 5:
            return features

        current_vol = volume[-1]

        # Volume moving averages
        vol_ma5 = np.mean(volume[-5:])
        vol_ma20 = np.mean(volume[-20:]) if n >= 20 else vol_ma5

        features["volume"] = float(current_vol)
        features["volume_ma5"] = float(vol_ma5)
        features["volume_ma20"] = float(vol_ma20)

        # Volume ratios
        features["volume_ratio_5d"] = current_vol / vol_ma5 if vol_ma5 > 0 else 0
        features["volume_ratio_20d"] = current_vol / vol_ma20 if vol_ma20 > 0 else 0

        # Volume z-score (20-day)
        if n >= 20:
            vol_std20 = np.std(volume[-20:])
            features["volume_zscore"] = (current_vol - vol_ma20) / vol_std20 if vol_std20 > 0 else 0
        else:
            features["volume_zscore"] = 0

        # Unusual volume flag
        features["unusual_volume"] = 1 if features.get("volume_zscore", 0) > 2.0 else 0

        # Volume trend
        if n >= 10:
            vol_trend = np.polyfit(range(10), volume[-10:], 1)[0]
            features["volume_trend"] = float(vol_trend / vol_ma5) if vol_ma5 > 0 else 0
        else:
            features["volume_trend"] = 0

        return features

    # =====================================================
    # Momentum
    # =====================================================

    def _compute_momentum(self, close: np.ndarray) -> Dict[str, float]:
        """Compute momentum features."""
        features = {}
        n = len(close)

        if n < 5:
            return features

        # Rate of change
        features["roc_5d"] = ((close[-1] / close[-5]) - 1) * 100 if n >= 5 else 0
        features["roc_10d"] = ((close[-1] / close[-10]) - 1) * 100 if n >= 10 else 0
        features["roc_20d"] = ((close[-1] / close[-20]) - 1) * 100 if n >= 20 else 0

        # Momentum (price difference)
        features["momentum_5d"] = close[-1] - close[-5] if n >= 5 else 0
        features["momentum_20d"] = close[-1] - close[-20] if n >= 20 else 0

        # Price acceleration
        if n >= 10:
            mom_5_now = close[-1] - close[-5]
            mom_5_prev = close[-5] - close[-10]
            features["price_acceleration"] = mom_5_now - mom_5_prev
        else:
            features["price_acceleration"] = 0

        return features

    # =====================================================
    # Volatility
    # =====================================================

    def _compute_volatility(self, close: np.ndarray, high: np.ndarray, low: np.ndarray) -> Dict[str, float]:
        """Compute volatility features."""
        features = {}
        n = len(close)

        if n < 5:
            return features

        # ATR (Average True Range)
        if n >= 14:
            tr = np.maximum(
                high[1:] - low[1:],
                np.maximum(
                    np.abs(high[1:] - close[:-1]),
                    np.abs(low[1:] - close[:-1])
                )
            )
            atr_14 = np.mean(tr[-14:])
            features["atr_14"] = float(atr_14)
            features["atr_14_pct"] = float(atr_14 / close[-1] * 100) if close[-1] > 0 else 0
        else:
            features["atr_14"] = 0
            features["atr_14_pct"] = 0

        # Realized volatility
        log_returns = np.diff(np.log(np.maximum(close, 1e-10)))

        if n >= 5:
            features["realized_vol_5d"] = float(np.std(log_returns[-5:]) * np.sqrt(252) * 100)
        if n >= 20:
            features["realized_vol_20d"] = float(np.std(log_returns[-20:]) * np.sqrt(252) * 100)

        # Bollinger Bands
        if n >= 20:
            ma20 = np.mean(close[-20:])
            std20 = np.std(close[-20:])
            features["bb_upper"] = float(ma20 + 2 * std20)
            features["bb_lower"] = float(ma20 - 2 * std20)
            features["bb_width"] = float(4 * std20 / ma20 * 100) if ma20 > 0 else 0
            features["bb_position"] = float((close[-1] - features["bb_lower"]) / (features["bb_upper"] - features["bb_lower"])) if (features["bb_upper"] - features["bb_lower"]) > 0 else 0.5

        # Volatility regime
        if n >= 20:
            vol_5 = np.std(log_returns[-5:]) if len(log_returns) >= 5 else 0
            vol_20 = np.std(log_returns[-20:])
            features["volatility_ratio"] = float(vol_5 / vol_20) if vol_20 > 0 else 1.0

            if features["volatility_ratio"] > 1.5:
                features["volatility_regime"] = 3  # HIGH
            elif features["volatility_ratio"] < 0.5:
                features["volatility_regime"] = 1  # LOW
            else:
                features["volatility_regime"] = 2  # NORMAL
        else:
            features["volatility_regime"] = 2

        return features

    # =====================================================
    # Technical Indicators
    # =====================================================

    def _compute_technical(self, close: np.ndarray, high: np.ndarray, low: np.ndarray, volume: np.ndarray) -> Dict[str, float]:
        """Compute technical indicators."""
        features = {}
        n = len(close)

        # RSI
        if n >= 14:
            features["rsi_14"] = self._rsi(close, 14)

        # MACD
        if n >= 26:
            macd, signal, histogram = self._macd(close)
            features["macd"] = macd
            features["macd_signal"] = signal
            features["macd_histogram"] = histogram

        # Stochastic
        if n >= 14:
            k, d = self._stochastic(high, low, close, 14, 3)
            features["stochastic_k"] = k
            features["stochastic_d"] = d

        # ADX
        if n >= 14:
            features["adx"] = self._adx(high, low, close, 14)

        # CCI
        if n >= 20:
            features["cci"] = self._cci(high, low, close, 20)

        # Williams %R
        if n >= 14:
            features["williams_r"] = self._williams_r(high, low, close, 14)

        # MFI (Money Flow Index)
        if n >= 14:
            features["mfi"] = self._mfi(high, low, close, volume, 14)

        return features

    # =====================================================
    # Trend Features
    # =====================================================

    def _compute_trend(self, close: np.ndarray, high: np.ndarray, low: np.ndarray) -> Dict[str, float]:
        """Compute trend features."""
        features = {}
        n = len(close)

        if n < 10:
            return features

        # Moving averages
        features["sma_5"] = float(np.mean(close[-5:]))
        features["sma_10"] = float(np.mean(close[-10:]))
        features["sma_20"] = float(np.mean(close[-20:])) if n >= 20 else features["sma_10"]
        features["sma_50"] = float(np.mean(close[-50:])) if n >= 50 else features["sma_20"]

        # EMA
        features["ema_12"] = float(self._ema(close, 12))
        features["ema_26"] = float(self._ema(close, 26))

        # Price relative to MAs
        features["price_vs_sma20"] = (close[-1] / features["sma_20"] - 1) * 100 if features["sma_20"] > 0 else 0
        features["price_vs_sma50"] = (close[-1] / features["sma_50"] - 1) * 100 if features["sma_50"] > 0 else 0

        # MA crossover signals
        if n >= 50:
            sma20 = np.mean(close[-20:])
            sma50 = np.mean(close[-50:])
            features["ma_cross_signal"] = 1 if sma20 > sma50 else -1

        # Trend strength (linear regression slope)
        if n >= 20:
            slope = np.polyfit(range(20), close[-20:], 1)[0]
            features["trend_slope_20d"] = float(slope / close[-1] * 100) if close[-1] > 0 else 0

        return features

    # =====================================================
    # Price Patterns
    # =====================================================

    def _compute_price_patterns(self, close: np.ndarray, high: np.ndarray, low: np.ndarray, open_: np.ndarray) -> Dict[str, float]:
        """Compute price pattern features."""
        features = {}
        n = len(close)

        if n < 5:
            return features

        # Gap detection
        if n >= 2:
            features["gap_pct"] = (open_[-1] / close[-2] - 1) * 100

        # Range
        features["daily_range_pct"] = (high[-1] - low[-1]) / close[-1] * 100 if close[-1] > 0 else 0

        # Upper/lower shadow ratio
        body = abs(close[-1] - open_[-1])
        upper_shadow = high[-1] - max(close[-1], open_[-1])
        lower_shadow = min(close[-1], open_[-1]) - low[-1]

        features["upper_shadow_ratio"] = upper_shadow / body if body > 0 else 0
        features["lower_shadow_ratio"] = lower_shadow / body if body > 0 else 0

        # Consecutive up/down days
        if n >= 5:
            up_days = sum(1 for i in range(-5, 0) if close[i] > close[i-1])
            features["consecutive_up"] = up_days
            features["consecutive_down"] = 5 - up_days

        # New high/low
        if n >= 20:
            features["near_20d_high"] = 1 if close[-1] >= max(high[-20:]) * 0.98 else 0
            features["near_20d_low"] = 1 if close[-1] <= min(low[-20:]) * 1.02 else 0

        return features

    # =====================================================
    # Helper Functions
    # =====================================================

    def _rsi(self, close: np.ndarray, period: int = 14) -> float:
        """Calculate RSI."""
        deltas = np.diff(close)
        gains = np.where(deltas > 0, deltas, 0)
        losses = np.where(deltas < 0, -deltas, 0)

        avg_gain = np.mean(gains[-period:])
        avg_loss = np.mean(losses[-period:])

        if avg_loss == 0:
            return 100.0

        rs = avg_gain / avg_loss
        return 100 - (100 / (1 + rs))

    def _ema(self, data: np.ndarray, period: int) -> float:
        """Calculate EMA."""
        multiplier = 2 / (period + 1)
        ema = data[0]
        for price in data[1:]:
            ema = (price - ema) * multiplier + ema
        return ema

    def _macd(self, close: np.ndarray) -> tuple:
        """Calculate MACD."""
        ema12 = self._ema(close, 12)
        ema26 = self._ema(close, 26)
        macd_line = ema12 - ema26

        # Signal line (9-period EMA of MACD)
        # Simplified: use last value
        signal = macd_line * 0.9  # Approximate
        histogram = macd_line - signal

        return macd_line, signal, histogram

    def _stochastic(self, high: np.ndarray, low: np.ndarray, close: np.ndarray, k_period: int, d_period: int) -> tuple:
        """Calculate Stochastic oscillator."""
        lowest_low = np.min(low[-k_period:])
        highest_high = np.max(high[-k_period:])

        if highest_high == lowest_low:
            return 50.0, 50.0

        k = (close[-1] - lowest_low) / (highest_high - lowest_low) * 100
        d = k  # Simplified

        return k, d

    def _adx(self, high: np.ndarray, low: np.ndarray, close: np.ndarray, period: int) -> float:
        """Calculate ADX."""
        n = len(close)
        if n < period + 1:
            return 0

        # True Range
        tr = np.maximum(
            high[1:] - low[1:],
            np.maximum(
                np.abs(high[1:] - close[:-1]),
                np.abs(low[1:] - close[:-1])
            )
        )

        # Directional Movement
        up_move = high[1:] - high[:-1]
        down_move = low[:-1] - low[1:]

        plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0)
        minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0)

        atr = np.mean(tr[-period:])
        if atr == 0:
            return 0

        plus_di = np.mean(plus_dm[-period:]) / atr * 100
        minus_di = np.mean(minus_dm[-period:]) / atr * 100

        dx = abs(plus_di - minus_di) / (plus_di + minus_di) * 100 if (plus_di + minus_di) > 0 else 0

        return dx

    def _cci(self, high: np.ndarray, low: np.ndarray, close: np.ndarray, period: int) -> float:
        """Calculate CCI."""
        tp = (high + low + close) / 3
        tp_ma = np.mean(tp[-period:])
        tp_std = np.std(tp[-period:])

        if tp_std == 0:
            return 0

        return (tp[-1] - tp_ma) / (0.015 * tp_std)

    def _williams_r(self, high: np.ndarray, low: np.ndarray, close: np.ndarray, period: int) -> float:
        """Calculate Williams %R."""
        highest_high = np.max(high[-period:])
        lowest_low = np.min(low[-period:])

        if highest_high == lowest_low:
            return -50

        return (highest_high - close[-1]) / (highest_high - lowest_low) * -100

    def _mfi(self, high: np.ndarray, low: np.ndarray, close: np.ndarray, volume: np.ndarray, period: int) -> float:
        """Calculate Money Flow Index."""
        tp = (high + low + close) / 3
        mf = tp * volume

        positive_mf = 0
        negative_mf = 0

        for i in range(-period, 0):
            if tp[i] > tp[i-1]:
                positive_mf += mf[i]
            else:
                negative_mf += mf[i]

        if negative_mf == 0:
            return 100

        mf_ratio = positive_mf / negative_mf
        return 100 - (100 / (1 + mf_ratio))


# Singleton
feature_calculator = FeatureCalculator()
