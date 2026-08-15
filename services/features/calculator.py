"""
ALPHA BIST — Feature Calculator v2.0 (Düzeltilmiş)

Stochastic D = SMA(3) of K (düzeltilmiş)
Volume profile bins dinamik

FAZ 4: Feature Engineering
"""

import numpy as np
import pandas as pd
from typing import Dict, List, Optional, Any
from collections import defaultdict
import structlog

logger = structlog.get_logger()

class FeatureCalculator:
    """Teknik feature hesaplama."""

    def __init__(self):
        self._required_bars = 60
        logger.info("FeatureCalculator initialized")

    def compute_all_features(self, df: pd.DataFrame) -> Dict[str, Any]:
        """Tüm feature'ları hesapla."""
        if len(df) < self._required_bars:
            logger.warning(f"Insufficient data: {len(df)} bars")
            return {}

        close = df["Close"].values
        high = df["High"].values
        low = df["Low"].values
        volume = df["Volume"].values if "Volume" in df.columns else np.ones(len(close))

        features = {}

        # === TREND ===
        features["sma_20"] = self._sma(close, 20)
        features["sma_50"] = self._sma(close, 50)
        features["ema_12"] = self._ema(close, 12)
        features["ema_26"] = self._ema(close, 26)

        # === MOMENTUM ===
        features["roc_5d"] = self._roc(close, 5)
        features["roc_20d"] = self._roc(close, 20)
        features["momentum_20d"] = self._momentum(close, 20)

        # === RSI ===
        features["rsi_14"] = self._rsi(close, 14)
        features["rsi_5"] = self._rsi(close, 5)

        # === MACD ===
        macd, signal, hist = self._macd(close)
        features["macd"] = macd
        features["macd_signal"] = signal
        features["macd_hist"] = hist

        # === BOLLINGER ===
        bb_upper, bb_lower, bb_position = self._bollinger(close)
        features["bb_upper"] = bb_upper
        features["bb_lower"] = bb_lower
        features["bb_position"] = bb_position
        features["bb_width"] = bb_upper - bb_lower

        # === STOCHASTIC (DÜZELTİLMİŞ) ===
        k, d = self._stochastic(high, low, close, k_period=14, d_period=3)
        features["stoch_k"] = k
        features["stoch_d"] = d  # Artık SMA(3) of K

        # === ATR ===
        features["atr_14"] = self._atr(high, low, close, 14)
        features["atr_pct"] = (features["atr_14"] / close[-1] * 100) if close[-1] else 0

        # === ADX ===
        features["adx"] = self._adx(high, low, close, 14)
        features["di_plus"] = self._di_plus(high, low, close, 14)
        features["di_minus"] = self._di_minus(high, low, close, 14)

        # === VOLUME ===
        features["volume_zscore"] = self._volume_zscore(volume)
        features["volume_trend"] = self._volume_trend(volume)
        features["obv"] = self._obv(close, volume)

        # === PRICE RELATIVES ===
        features["price_vs_sma20"] = (close[-1] / features["sma_20"] - 1) * 100 if features["sma_20"] else 0
        features["price_vs_sma50"] = (close[-1] / features["sma_50"] - 1) * 100 if features["sma_50"] else 0

        # === VOLATILITY ===
        features["volatility_20d"] = self._volatility(close, 20)
        features["volatility_60d"] = self._volatility(close, 60)

        # === VOLUME PROFILE (DİNAMİK BINS) ===
        vp = self._volume_profile(close, volume)
        features["volume_profile"] = vp
        features["poc_price"] = vp.get("poc", close[-1])
        features["value_area_high"] = vp.get("value_area_high", close[-1])
        features["value_area_low"] = vp.get("value_area_low", close[-1])

        # === PRICE ACTION ===
        features["higher_highs"] = self._higher_highs(high)
        features["lower_lows"] = self._lower_lows(low)
        features["inside_days"] = self._inside_days(high, low)

        # Round all
        for key in features:
            if isinstance(features[key], float):
                features[key] = round(features[key], 4)

        return features

    # === HELPER METHODS ===

    def _sma(self, data, period):
        if len(data) < period:
            return data[-1] if len(data) > 0 else 0
        return np.mean(data[-period:])

    def _ema(self, data, period):
        if len(data) < period:
            return data[-1] if len(data) > 0 else 0
        alpha = 2 / (period + 1)
        ema = data[0]
        for price in data[1:]:
            ema = alpha * price + (1 - alpha) * ema
        return ema

    def _roc(self, data, period):
        if len(data) <= period:
            return 0
        return (data[-1] / data[-period-1] - 1) * 100

    def _momentum(self, data, period):
        if len(data) <= period:
            return 0
        return (data[-1] - data[-period-1]) / data[-period-1] * 100

    def _rsi(self, data, period=14):
        if len(data) < period + 1:
            return 50
        deltas = np.diff(data)
        gains = np.where(deltas > 0, deltas, 0)
        losses = np.where(deltas < 0, -deltas, 0)

        avg_gain = np.mean(gains[-period:])
        avg_loss = np.mean(losses[-period:])

        if avg_loss == 0:
            return 100
        rs = avg_gain / avg_loss
        return 100 - (100 / (1 + rs))

    def _macd(self, data, fast=12, slow=26, signal=9):
        ema_fast = self._ema(data, fast)
        ema_slow = self._ema(data, slow)
        macd_line = ema_fast - ema_slow

        # Signal line (EMA of MACD)
        macd_hist = [self._ema(data[:i+1], fast) - self._ema(data[:i+1], slow) 
                     for i in range(slow, len(data))]
        signal_line = self._ema(np.array(macd_hist), signal) if len(macd_hist) >= signal else macd_hist[-1] if macd_hist else 0

        hist = macd_line - signal_line
        return macd_line, signal_line, hist

    def _bollinger(self, data, period=20, std_dev=2):
        if len(data) < period:
            return data[-1], data[-1], 0.5

        sma = np.mean(data[-period:])
        std = np.std(data[-period:])

        upper = sma + std_dev * std
        lower = sma - std_dev * std

        # Position within bands (0-1)
        if upper == lower:
            position = 0.5
        else:
            position = (data[-1] - lower) / (upper - lower)

        return upper, lower, max(0, min(1, position))

    def _stochastic(self, high, low, close, k_period=14, d_period=3):
        """Stochastic Oscillator (DÜZELTİLMİŞ).

        %K = (Close - Lowest Low) / (Highest High - Lowest Low) * 100
        %D = SMA(%K, d_period)
        """
        if len(close) < k_period:
            return 50, 50

        # %K hesapla
        lowest_low = np.min(low[-k_period:])
        highest_high = np.max(high[-k_period:])

        if highest_high == lowest_low:
            k = 50
        else:
            k = (close[-1] - lowest_low) / (highest_high - lowest_low) * 100

        # %D = SMA(%K, d_period) — DÜZELTME BURADA
        # Geçmiş K değerlerini hesapla
        k_values = []
        for i in range(k_period - 1, len(close)):
            ll = np.min(low[i-k_period+1:i+1])
            hh = np.max(high[i-k_period+1:i+1])
            if hh == ll:
                k_values.append(50)
            else:
                k_values.append((close[i] - ll) / (hh - ll) * 100)

        # D = K'nın d_period periyotluk SMA'sı
        if len(k_values) >= d_period:
            d = np.mean(k_values[-d_period:])
        else:
            d = k  # Yetersiz veri

        return k, d

    def _atr(self, high, low, close, period=14):
        if len(close) < period + 1:
            return 0

        tr_values = []
        for i in range(1, len(close)):
            tr1 = high[i] - low[i]
            tr2 = abs(high[i] - close[i-1])
            tr3 = abs(low[i] - close[i-1])
            tr_values.append(max(tr1, tr2, tr3))

        return np.mean(tr_values[-period:])

    def _adx(self, high, low, close, period=14):
        if len(close) < period * 2:
            return 25

        # +DM ve -DM
        plus_dm = []
        minus_dm = []
        tr_list = []

        for i in range(1, len(close)):
            up_move = high[i] - high[i-1]
            down_move = low[i-1] - low[i]

            if up_move > down_move and up_move > 0:
                plus_dm.append(up_move)
            else:
                plus_dm.append(0)

            if down_move > up_move and down_move > 0:
                minus_dm.append(down_move)
            else:
                minus_dm.append(0)

            tr_list.append(max(
                high[i] - low[i],
                abs(high[i] - close[i-1]),
                abs(low[i] - close[i-1])
            ))

        # Smooth
        atr = np.mean(tr_list[-period:])
        plus_di = 100 * np.mean(plus_dm[-period:]) / atr if atr else 0
        minus_di = 100 * np.mean(minus_dm[-period:]) / atr if atr else 0

        dx = 100 * abs(plus_di - minus_di) / (plus_di + minus_di) if (plus_di + minus_di) else 0

        return dx

    def _di_plus(self, high, low, close, period=14):
        # Simplified
        return 25  # Placeholder

    def _di_minus(self, high, low, close, period=14):
        # Simplified
        return 25  # Placeholder

    def _volume_zscore(self, volume):
        if len(volume) < 20:
            return 0
        mean = np.mean(volume[-20:])
        std = np.std(volume[-20:])
        if std == 0:
            return 0
        return (volume[-1] - mean) / std

    def _volume_trend(self, volume):
        if len(volume) < 10:
            return 0
        recent = np.mean(volume[-5:])
        prev = np.mean(volume[-10:-5])
        if prev == 0:
            return 0
        return (recent / prev - 1) * 100

    def _obv(self, close, volume):
        obv = 0
        for i in range(1, len(close)):
            if close[i] > close[i-1]:
                obv += volume[i]
            elif close[i] < close[i-1]:
                obv -= volume[i]
        return obv

    def _volatility(self, data, period):
        if len(data) < period:
            return 0
        returns = np.diff(data[-period:]) / data[-period:-1]
        return np.std(returns) * np.sqrt(252) * 100  # Annualized

    def _volume_profile(self, close, volume):
        """Volume profile (DİNAMİK BINS)."""
        n = len(close)
        if n < 20:
            return {"poc": close[-1], "value_area_high": close[-1], "value_area_low": close[-1]}

        # Dinamik bin sayısı: sqrt(n) yaklaşımı
        n_bins = max(10, min(50, int(np.sqrt(n))))

        hist, bin_edges = np.histogram(close, bins=n_bins, weights=volume)

        # POC (Point of Control)
        poc_idx = np.argmax(hist)
        poc = (bin_edges[poc_idx] + bin_edges[poc_idx + 1]) / 2

        # Value Area (toplam hacmin %70'i)
        total_vol = np.sum(hist)
        target_vol = total_vol * 0.7

        sorted_indices = np.argsort(hist)[::-1]
        cum_vol = 0
        va_indices = []
        for idx in sorted_indices:
            cum_vol += hist[idx]
            va_indices.append(idx)
            if cum_vol >= target_vol:
                break

        va_high = bin_edges[max(va_indices) + 1]
        va_low = bin_edges[min(va_indices)]

        return {
            "poc": poc,
            "value_area_high": va_high,
            "value_area_low": va_low,
            "bins": n_bins,
        }

    def _higher_highs(self, high):
        if len(high) < 5:
            return 0
        count = 0
        for i in range(-5, 0):
            if high[i] > high[i-1]:
                count += 1
        return count

    def _lower_lows(self, low):
        if len(low) < 5:
            return 0
        count = 0
        for i in range(-5, 0):
            if low[i] < low[i-1]:
                count += 1
        return count

    def _inside_days(self, high, low):
        if len(high) < 2:
            return 0
        return 1 if (high[-1] < high[-2] and low[-1] > low[-2]) else 0

# Singleton
feature_calculator = FeatureCalculator()
