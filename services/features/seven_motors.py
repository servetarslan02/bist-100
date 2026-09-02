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
        with np.errstate(divide="ignore", invalid="ignore"):
            rs = np.where(benchmark_close > 0, stock_close / benchmark_close, np.nan)
        rs = rs[np.isfinite(rs)]
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
        """Otomatik eklendi."""
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
        """Otomatik eklendi."""
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
        """Otomatik eklendi."""
        result: dict[str, float] = {}
        if len(close) < lookback:
            return result
        returns = np.diff(np.log(close[-lookback:]))
        result["volatility"] = float(np.std(returns) * np.sqrt(252))
        return result


class MeanReversionMotor:
    """Computes mean reversion features."""

    def compute(self, ticker: str, close: np.ndarray, lookback: int = 20) -> dict[str, float]:
        """Otomatik eklendi."""
        result: dict[str, float] = {}
        if len(close) < lookback:
            return result
        sma = np.mean(close[-lookback:])
        result["mean_reversion"] = float((close[-1] - sma) / sma) if sma > 0 else 0.0
        return result


class MicrostructureMotor:
    """Computes microstructure features."""

    def compute(
        self, ticker: str, high: np.ndarray, low: np.ndarray, close: np.ndarray, lookback: int = 20
    ) -> dict[str, float]:
        """Otomatik eklendi."""
        result: dict[str, float] = {}
        if len(close) < lookback:
            return result
        hl_range = high[-lookback:] - low[-lookback:]
        result["spread"] = float(np.mean(hl_range / close[-lookback:])) if np.all(close[-lookback:] > 0) else 0.0
        return result


class WhyFallingMotor:
    """Düşen bıçağı tutma hatasını önle — çok faktörlü analiz."""

    def compute(
        self,
        ticker: str,
        stock_return_5d: float,
        stock_return_20d: float,
        market_return_5d: float,
        market_return_20d: float,
        sector_return_5d: float,
        sector_return_20d: float,
        volume_change: float,
        volume_zscore: float,
        news_sentiment: float,
        kap_sentiment: float,
        rsi: float = 50,
        atr_pct: float = 0,
    ) -> dict[str, float]:
        """Düşüş nedeni sınıflandırması."""
        features: dict[str, float] = {}

        # Düşüş var mı?
        is_falling_5d = stock_return_5d < -2
        is_falling_20d = stock_return_20d < -5
        features["is_falling_5d"] = 1.0 if is_falling_5d else 0.0
        features["is_falling_20d"] = 1.0 if is_falling_20d else 0.0

        # Geriye uyumluluk: why_falling anahtarı
        features["why_falling"] = 1.0 if (is_falling_5d or is_falling_20d) else 0.0

        if not is_falling_5d and not is_falling_20d:
            features["falling_is_temporary"] = 0.5
            features["fall_severity"] = 0.0
            return features

        # Düşüş şiddeti
        features["fall_severity"] = round(abs(min(stock_return_5d, 0)), 4)

        # Market selloff tespiti (5d ve 20d)
        features["fall_market_selloff_5d"] = 1.0 if market_return_5d < -3 else 0.0
        features["fall_market_selloff_20d"] = 1.0 if market_return_20d < -5 else 0.0

        # Sector selloff tespiti
        features["fall_sector_selloff_5d"] = 1.0 if sector_return_5d < -5 else 0.0
        features["fall_sector_selloff_20d"] = 1.0 if sector_return_20d < -8 else 0.0

        # Company-specific (piyasa ve sektör düşmemişse)
        features["fall_company_specific_5d"] = (
            1.0 if (market_return_5d > -1 and sector_return_5d > -2 and stock_return_5d < -5) else 0.0
        )

        # Liquidity event (hacim patlaması + fiyat düşüşü)
        features["fall_liquidity_event"] = 1.0 if (volume_zscore > 2 and stock_return_5d < -5) else 0.0

        # Temporary panic (hızlı düşüş + negatif sentiment düşük)
        features["fall_temporary_panic"] = 1.0 if (stock_return_5d < -10 and news_sentiment > -0.3) else 0.0

        # Oversold bounce potential (RSI < 30 + düşüş şiddetli)
        features["fall_oversold_bounce"] = 1.0 if (rsi < 30 and stock_return_5d < -5) else 0.0

        # High volatility crash (ATR yüksek + düşüş)
        features["fall_high_vol_crash"] = 1.0 if (atr_pct > 5 and stock_return_5d < -5) else 0.0

        # Düşüş nedeni geçici mi kalıcı mı? (Çok faktörlü)
        temporary_score = 0.0
        if features.get("fall_market_selloff_5d", 0) == 1.0:
            temporary_score += 30
        if features.get("fall_sector_selloff_5d", 0) == 1.0:
            temporary_score += 20
        if features.get("fall_temporary_panic", 0) == 1.0:
            temporary_score += 25
        if features.get("fall_oversold_bounce", 0) == 1.0:
            temporary_score += 15
        if volume_zscore < 1:  # Düşük hacim = panik değil
            temporary_score += 10

        permanent_score = 0.0
        if features.get("fall_company_specific_5d", 0) == 1.0:
            permanent_score += 40
        if features.get("fall_liquidity_event", 0) == 1.0:
            permanent_score += 20
        if kap_sentiment < -0.5:
            permanent_score += 25
        if news_sentiment < -0.5:
            permanent_score += 15

        total = temporary_score + permanent_score
        if total > 0:
            features["falling_is_temporary"] = round(temporary_score / total, 4)
            features["falling_is_permanent"] = round(permanent_score / total, 4)
        else:
            features["falling_is_temporary"] = 0.5
            features["falling_is_permanent"] = 0.5

        # Catch falling knife risk (0 = güvenli, 1 = tehlikeli)
        risk_score = 0.0
        if features.get("fall_company_specific_5d", 0) == 1.0:
            risk_score += 40
        if features.get("fall_liquidity_event", 0) == 1.0:
            risk_score += 30
        if features.get("fall_high_vol_crash", 0) == 1.0:
            risk_score += 20
        if stock_return_20d < -15:
            risk_score += 10

        features["catch_falling_knife_risk"] = round(min(100, risk_score), 0)

        return features
