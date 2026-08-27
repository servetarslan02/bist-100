# Seven Motors Feature Engine
# Core feature motors for BIST quantitative analysis

from __future__ import annotations

import numpy as np
import structlog

logger = structlog.get_logger(__name__)


class RelativeStrengthMotor:
    """Computes relative strength features vs benchmark."""

    def compute(
        self,
        ticker: str,
        stock_close: np.ndarray,
        benchmark_close: np.ndarray,
    ) -> dict[str, float]:
        """Compute relative strength features.

        Args:
            ticker: Stock ticker
            stock_close: Stock closing prices
            benchmark_close: Benchmark closing prices

        Returns:
            Dict of feature_name -> value
        """
        result: dict[str, float] = {}

        if len(stock_close) < 20 or len(benchmark_close) < 20:
            return result

        # Relative strength (stock / benchmark ratio)
        rs = stock_close / benchmark_close
        rs = rs[~np.isnan(rs)]
        if len(rs) < 5:
            return result

        # RS momentum (5d, 20d)
        result["rs_5d"] = float((rs[-1] / rs[-5] - 1.0) * 100) if len(rs) >= 5 else 0.0
        result["rs_20d"] = float((rs[-1] / rs[-20] - 1.0) * 100) if len(rs) >= 20 else 0.0

        # RS trend (linear regression slope)
        if len(rs) >= 20:
            x = np.arange(20)
            slope = np.polyfit(x, rs[-20:], 1)[0]
            result["rs_trend"] = float(slope)

        return result


class SeasonalityMotor:
    """Computes seasonality features based on historical patterns."""

    def compute(
        self,
        ticker: str,
        close_arr: np.ndarray,
        dates_list: list | None = None,
    ) -> dict[str, float]:
        """Compute seasonality features.

        Args:
            ticker: Stock ticker
            close_arr: Closing prices (at least 252 days)
            dates_list: Optional list of dates for calendar effects

        Returns:
            Dict of feature_name -> value
        """
        result: dict[str, float] = {}

        if len(close_arr) < 252:
            return result

        # Monthly returns pattern
        returns = np.diff(np.log(close_arr))
        if len(returns) < 20:
            return result

        # Recent vs historical momentum
        ret_5d = float((close_arr[-1] / close_arr[-5] - 1.0) * 100) if len(close_arr) >= 5 else 0.0
        ret_20d = float((close_arr[-1] / close_arr[-20] - 1.0) * 100) if len(close_arr) >= 20 else 0.0
        ret_60d = float((close_arr[-1] / close_arr[-60] - 1.0) * 100) if len(close_arr) >= 60 else 0.0

        result["seasonality_5d"] = ret_5d
        result["seasonality_20d"] = ret_20d
        result["seasonality_60d"] = ret_60d

        # Volatility regime
        vol_recent = float(np.std(returns[-20:])) if len(returns) >= 20 else 0.0
        vol_hist = float(np.std(returns[-252:])) if len(returns) >= 252 else float(np.std(returns))
        result["seasonality_vol_ratio"] = vol_recent / vol_hist if vol_hist > 1e-10 else 1.0

        return result


class MomentumMotor:
    """Computes momentum features."""

    def compute(self, ticker: str, close: np.ndarray, lookback: int = 20) -> dict[str, float]:
        result: dict[str, float] = {}
        if len(close) < lookback:
            return result
        returns = np.diff(np.log(close[-lookback:]))
        result["momentum_mean"] = float(np.mean(returns))
        result["momentum_std"] = float(np.std(returns))
        return result


class VolumeMotor:
    """Computes volume-based features."""

    def compute(self, ticker: str, volume: np.ndarray, lookback: int = 20) -> dict[str, float]:
        result: dict[str, float] = {}
        if len(volume) < lookback:
            return result
        vol_arr = volume[-lookback:]
        avg = np.mean(vol_arr)
        result["volume_ratio"] = float(vol_arr[-1] / avg) if avg > 0 else 1.0
        return result


class VolatilityMotor:
    """Computes volatility features."""

    def compute(self, ticker: str, close: np.ndarray, lookback: int = 20) -> dict[str, float]:
        result: dict[str, float] = {}
        if len(close) < lookback:
            return result
        returns = np.diff(np.log(close[-lookback:]))
        result["volatility"] = float(np.std(returns) * np.sqrt(252))
        return result


class MeanReversionMotor:
    """Computes mean reversion features."""

    def compute(self, ticker: str, close: np.ndarray, lookback: int = 20) -> dict[str, float]:
        result: dict[str, float] = {}
        if len(close) < lookback:
            return result
        sma = np.mean(close[-lookback:])
        result["mean_reversion"] = float((close[-1] - sma) / sma) if sma > 0 else 0.0
        return result


class MicrostructureMotor:
    """Computes microstructure features."""

    def compute(self, ticker: str, high: np.ndarray, low: np.ndarray, close: np.ndarray, lookback: int = 20) -> dict[str, float]:
        result: dict[str, float] = {}
        if len(close) < lookback:
            return result
        hl_range = high[-lookback:] - low[-lookback:]
        result["spread"] = float(np.mean(hl_range / close[-lookback:])) if np.all(close[-lookback:] > 0) else 0.0
        return result
