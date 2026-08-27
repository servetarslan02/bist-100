# Seven Motors Feature Engine
# Core feature motors for BIST quantitative analysis

from __future__ import annotations

import numpy as np


class SevenMotorsEngine:
    """Seven core feature motors for comprehensive market analysis.

    Motors:
    1. Momentum Motor - Trend strength and direction
    2. Volatility Motor - Risk and regime detection
    3. Volume Motor - Liquidity and participation
    4. Mean Reversion Motor - Overbought/oversold detection
    5. Seasonality Motor - Calendar and time effects
    6. Correlation Motor - Cross-asset relationships
    7. Microstructure Motor - Order flow and market quality
    """

    def __init__(self):
        self._cache: dict[str, dict[str, float]] = {}

    def compute_all(
        self,
        ticker: str,
        ohlcv: dict[str, np.ndarray],
        lookback: int = 20,
    ) -> dict[str, float]:
        """Compute all seven motor features for a ticker."""
        result = {}

        close = ohlcv.get("close", np.array([]))
        volume = ohlcv.get("volume", np.array([]))
        high = ohlcv.get("high", np.array([]))
        low = ohlcv.get("low", np.array([]))

        if len(close) < lookback:
            return result

        # 1. Momentum Motor
        returns = np.diff(np.log(close[-lookback:]))
        result["motor_momentum"] = float(np.mean(returns)) if len(returns) > 0 else 0.0
        result["motor_momentum_strength"] = float(abs(np.mean(returns))) if len(returns) > 0 else 0.0

        # 2. Volatility Motor
        result["motor_volatility"] = float(np.std(returns)) if len(returns) > 0 else 0.0
        if len(returns) >= 2:
            half = len(returns) // 2
            vol_recent = np.std(returns[half:])
            vol_older = np.std(returns[:half])
            result["motor_vol_regime"] = float(vol_recent / vol_older) if vol_older > 1e-10 else 1.0
        else:
            result["motor_vol_regime"] = 1.0

        # 3. Volume Motor
        if len(volume) >= lookback:
            vol_arr = volume[-lookback:]
            avg_vol = np.mean(vol_arr)
            result["motor_volume_ratio"] = float(vol_arr[-1] / avg_vol) if avg_vol > 0 else 1.0
            result["motor_volume_trend"] = float(np.polyfit(range(len(vol_arr)), vol_arr, 1)[0]) if len(vol_arr) > 1 else 0.0
        else:
            result["motor_volume_ratio"] = 1.0
            result["motor_volume_trend"] = 0.0

        # 4. Mean Reversion Motor
        if len(close) >= lookback:
            sma = np.mean(close[-lookback:])
            result["motor_mean_reversion"] = float((close[-1] - sma) / sma) if sma > 0 else 0.0
        else:
            result["motor_mean_reversion"] = 0.0

        # 5. Seasonality Motor (simplified)
        result["motor_seasonality"] = 0.0  # Placeholder for calendar effects

        # 6. Correlation Motor (simplified)
        result["motor_correlation"] = 0.0  # Requires market index data

        # 7. Microstructure Motor
        if len(high) >= lookback and len(low) >= lookback:
            hl_range = high[-lookback:] - low[-lookback:]
            result["motor_spread"] = float(np.mean(hl_range / close[-lookback:])) if np.all(close[-lookback:] > 0) else 0.0
        else:
            result["motor_spread"] = 0.0

        self._cache[ticker] = result
        return result

    def get_cached(self, ticker: str) -> dict[str, float]:
        """Get cached motor features."""
        return self._cache.get(ticker, {})


# Singleton
seven_motors = SevenMotorsEngine()
