"""
ALPHA BIST — Technical Features

Teknik gösterge feature'ları:
- Trend: SMA, EMA, MACD, crossover
- Momentum: RSI, ROC, Stochastic
- Volatilite: ATR, Bollinger Bands, historical vol
- Volume: OBV, VWAP, MFI
- BIST-specific: USDTRY, TCMB, CDS
"""

import numpy as np
from typing import Dict, Any, Optional
import structlog

logger = structlog.get_logger()


class TechnicalFeatureEngine:
    """Teknik gösterge feature hesaplayıcı."""

    def compute_trend_features(self, prices: np.ndarray) -> Dict[str, float]:
        """Trend feature'ları."""
        if len(prices) < 20:
            return {}

        features = {}
        features["sma_20"] = float(np.mean(prices[-20:]))
        features["sma_50"] = float(np.mean(prices[-50:])) if len(prices) >= 50 else features["sma_20"]
        features["sma_200"] = float(np.mean(prices[-200:])) if len(prices) >= 200 else features["sma_50"]

        # EMA
        features["ema_20"] = self._ema(prices, 20)
        features["ema_50"] = self._ema(prices, 50) if len(prices) >= 50 else features["ema_20"]

        # MACD
        ema_12 = self._ema(prices, 12)
        ema_26 = self._ema(prices, 26)
        features["macd"] = ema_12 - ema_26
        features["macd_signal"] = features["macd"]  # Basitleştirilmiş

        # Crossover
        features["sma_20_50_cross"] = 1.0 if features["sma_20"] > features["sma_50"] else 0.0
        features["price_above_sma_20"] = 1.0 if prices[-1] > features["sma_20"] else 0.0

        return features

    def compute_momentum_features(
        self, prices: np.ndarray, highs: Optional[np.ndarray] = None,
        lows: Optional[np.ndarray] = None
    ) -> Dict[str, float]:
        """Momentum feature'ları."""
        if len(prices) < 14:
            return {}

        features = {}

        # RSI
        features["rsi_14"] = self._rsi(prices, 14)

        # ROC
        features["roc_5d"] = ((prices[-1] / prices[-6]) - 1) * 100 if len(prices) >= 6 else 0
        features["roc_20d"] = ((prices[-1] / prices[-21]) - 1) * 100 if len(prices) >= 21 else 0

        # Momentum
        features["momentum_20d"] = prices[-1] - prices[-21] if len(prices) >= 21 else 0

        # Stochastic (basitleştirilmiş)
        if highs is not None and lows is not None and len(highs) >= 14:
            h14 = np.max(highs[-14:])
            l14 = np.min(lows[-14:])
            features["stochastic_k"] = ((prices[-1] - l14) / (h14 - l14) * 100) if h14 != l14 else 50
        else:
            features["stochastic_k"] = 50.0

        return features

    def compute_volatility_features(
        self, prices: np.ndarray, highs: Optional[np.ndarray] = None,
        lows: Optional[np.ndarray] = None, closes: Optional[np.ndarray] = None
    ) -> Dict[str, float]:
        """Volatilite feature'ları."""
        if len(prices) < 20:
            return {}

        features = {}

        # Historical volatility
        returns = np.diff(np.log(prices))
        features["realized_vol_20d"] = float(np.std(returns[-20:]) * np.sqrt(252) * 100)
        features["realized_vol_60d"] = float(np.std(returns[-60:]) * np.sqrt(252) * 100) if len(returns) >= 60 else features["realized_vol_20d"]

        # ATR
        if highs is not None and lows is not None and closes is not None:
            features["atr_14"] = self._atr(highs, lows, closes, 14)
            features["atr_pct"] = (features["atr_14"] / prices[-1] * 100) if prices[-1] > 0 else 0
        else:
            features["atr_14"] = features["realized_vol_20d"] * prices[-1] / 100
            features["atr_pct"] = features["realized_vol_20d"]

        # Bollinger Bands
        sma_20 = np.mean(prices[-20:])
        std_20 = np.std(prices[-20:])
        features["bb_upper"] = sma_20 + 2 * std_20
        features["bb_lower"] = sma_20 - 2 * std_20
        features["bb_width"] = (features["bb_upper"] - features["bb_lower"]) / sma_20 if sma_20 > 0 else 0
        features["bb_position"] = (prices[-1] - features["bb_lower"]) / (features["bb_upper"] - features["bb_lower"]) if features["bb_upper"] != features["bb_lower"] else 0.5

        return features

    def compute_volume_features(
        self, prices: np.ndarray, volumes: np.ndarray
    ) -> Dict[str, float]:
        """Volume feature'ları."""
        if len(prices) < 20 or len(volumes) < 20:
            return {}

        features = {}

        # Volume SMA
        features["volume_sma_20"] = float(np.mean(volumes[-20:]))
        features["volume_ratio"] = volumes[-1] / features["volume_sma_20"] if features["volume_sma_20"] > 0 else 1

        # OBV (On Balance Volume)
        obv = 0
        for i in range(1, len(prices)):
            if prices[i] > prices[i-1]:
                obv += volumes[i]
            elif prices[i] < prices[i-1]:
                obv -= volumes[i]
        features["obv"] = float(obv)

        # Volume acceleration
        if len(volumes) >= 5:
            vol_5d = np.mean(volumes[-5:])
            vol_20d = np.mean(volumes[-20:])
            features["volume_acceleration"] = vol_5d / vol_20d if vol_20d > 0 else 1
        else:
            features["volume_acceleration"] = 1.0

        return features

    def _ema(self, data: np.ndarray, period: int) -> float:
        """Exponential Moving Average."""
        if len(data) < period:
            return float(data[-1])
        multiplier = 2 / (period + 1)
        ema = float(np.mean(data[:period]))
        for val in data[period:]:
            ema = (float(val) - ema) * multiplier + ema
        return ema

    def _rsi(self, prices: np.ndarray, period: int = 14) -> float:
        """Relative Strength Index."""
        if len(prices) < period + 1:
            return 50.0
        deltas = np.diff(prices[-(period+1):])
        gains = np.where(deltas > 0, deltas, 0)
        losses = np.where(deltas < 0, -deltas, 0)
        avg_gain = np.mean(gains)
        avg_loss = np.mean(losses)
        if avg_loss == 0:
            return 100.0
        rs = avg_gain / avg_loss
        return float(100 - (100 / (1 + rs)))

    def _atr(self, highs: np.ndarray, lows: np.ndarray, closes: np.ndarray, period: int = 14) -> float:
        """Average True Range."""
        if len(highs) < period + 1:
            return 0.0
        tr_list = []
        for i in range(1, len(highs)):
            tr = max(
                highs[i] - lows[i],
                abs(highs[i] - closes[i-1]),
                abs(lows[i] - closes[i-1])
            )
            tr_list.append(tr)
        if len(tr_list) < period:
            return float(np.mean(tr_list))
        atr = float(np.mean(tr_list[:period]))
        for tr in tr_list[period:]:
            atr = (atr * (period - 1) + tr) / period
        return atr


# Singleton
technical_feature_engine = TechnicalFeatureEngine()
