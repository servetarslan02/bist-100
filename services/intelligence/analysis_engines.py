"""
ALPHA BIST — Analysis Engines v1.0

Ek analiz motorları:
- Price Action Engine
- Support/Resistance Engine
- Volume Engine
- Volatility Engine
- Sector Engine
- Relative Strength Engine
- Correlation Engine
- Drawdown Engine
- Position Risk Engine
- Portfolio Optimization
- Model Risk Engine
- Data Confidence Engine
"""


import numpy as np
import structlog

logger = structlog.get_logger()


class PriceActionEngine:
    """Price Action analiz motoru."""

    def detect_patterns(self, open_: np.ndarray, high: np.ndarray, low: np.ndarray, close: np.ndarray) -> dict[str, float]:
        """Fiyat paternlerini tespit et."""
        n = len(close)
        if n < 5:
            return {}

        features = {}

        # Higher High / Higher Low / Lower High / Lower Low
        if n >= 3:
            features["higher_high"] = 1.0 if high[-1] > high[-2] > high[-3] else 0.0
            features["higher_low"] = 1.0 if low[-1] > low[-2] > low[-3] else 0.0
            features["lower_high"] = 1.0 if high[-1] < high[-2] < high[-3] else 0.0
            features["lower_low"] = 1.0 if low[-1] < low[-2] < low[-3] else 0.0

        # Breakout
        if n >= 20:
            high_20 = np.max(high[-20:])
            low_20 = np.min(low[-20:])
            features["breakout_up"] = 1.0 if close[-1] > high_20 * 0.99 else 0.0
            features["breakdown"] = 1.0 if close[-1] < low_20 * 1.01 else 0.0

        # Consolidation (sıkışma)
        if n >= 10:
            range_10 = (np.max(high[-10:]) - np.min(low[-10:])) / close[-1] * 100
            range_20 = (np.max(high[-20:]) - np.min(low[-20:])) / close[-1] * 100 if n >= 20 else range_10
            features["consolidation"] = 1.0 if range_10 < range_20 * 0.5 else 0.0

        # Gap
        if n >= 2:
            gap = (open_[-1] / close[-2] - 1) * 100
            features["gap_up"] = 1.0 if gap > 1.0 else 0.0
            features["gap_down"] = 1.0 if gap < -1.0 else 0.0

        # Reversal patterns
        if n >= 3:
            # Hammer (long lower shadow)
            body = abs(close[-1] - open_[-1])
            lower_shadow = min(close[-1], open_[-1]) - low[-1]
            upper_shadow = high[-1] - max(close[-1], open_[-1])
            if body > 0:
                features["hammer"] = 1.0 if lower_shadow > body * 2 and upper_shadow < body else 0.0
                features["shooting_star"] = 1.0 if upper_shadow > body * 2 and lower_shadow < body else 0.0

        return features


class SupportResistanceEngine:
    """Support/Resistance seviye tespiti."""

    def compute_levels(self, high: np.ndarray, low: np.ndarray, close: np.ndarray, period: int = 20) -> dict[str, float]:
        """Destek ve direnç seviyeleri."""
        n = len(close)
        if n < period:
            return {}

        # Swing points
        swing_highs = []
        swing_lows = []
        for i in range(2, min(period, n - 2)):
            if high[-i] > high[-i-1] and high[-i] > high[-i+1]:
                swing_highs.append(float(high[-i]))
            if low[-i] < low[-i-1] and low[-i] < low[-i+1]:
                swing_lows.append(float(low[-i]))

        # En güçlü seviyeler
        resistance = sorted(swing_highs, reverse=True)[:3] if swing_highs else [float(np.max(high[-period:]))]
        support = sorted(swing_lows)[:3] if swing_lows else [float(np.min(low[-period:]))]

        features = {}
        for i, r in enumerate(resistance):
            features[f"resistance_{i+1}"] = round(r, 2)
        for i, s in enumerate(support):
            features[f"support_{i+1}"] = round(s, 2)

        # Mevcut fiyatın konumu
        price = close[-1]
        if resistance and support:
            range_val = resistance[0] - support[0]
            if range_val > 0:
                features["sr_position"] = round(float((price - support[0]) / range_val), 4)

        return features


class VolumeEngine:
    """Volume analiz motoru."""

    def compute(self, close: np.ndarray, volume: np.ndarray) -> dict[str, float]:
        """Hacim analizi."""
        n = len(close)
        if n < 20:
            return {}

        features = {}

        # OBV (On Balance Volume)
        obv = 0
        for i in range(1, min(n, 20)):
            if close[-i] > close[-i-1]:
                obv += volume[-i]
            elif close[-i] < close[-i-1]:
                obv -= volume[-i]
        features["obv_20d"] = float(obv)

        # Volume confirmation
        price_up = close[-1] > close[-2] if n >= 2 else False
        vol_up = volume[-1] > np.mean(volume[-20:])
        features["volume_confirmation"] = 1.0 if price_up and vol_up else 0.0

        # Volume divergence (fiyat yükseliyor ama hacim düşüyor)
        if n >= 5:
            price_trend = close[-1] > close[-5]
            vol_trend = np.mean(volume[-3:]) < np.mean(volume[-5:-2])
            features["volume_divergence"] = 1.0 if price_trend and vol_trend else 0.0

        return features


class SectorEngine:
    """Sektör analiz motoru."""

    def compute_sector_momentum(self, sector_returns: dict[str, list[float]]) -> dict[str, float]:
        """Sektör momentum hesapla."""
        features = {}
        for sector, returns in sector_returns.items():
            if len(returns) >= 20:
                features[f"sector_{sector}_momentum_20d"] = round(float(np.mean(returns[-20:]) * 100), 2)
            if len(returns) >= 5:
                features[f"sector_{sector}_momentum_5d"] = round(float(np.mean(returns[-5:]) * 100), 2)
        return features

    def compute_sector_relative_strength(self, stock_return: float, sector_return: float) -> float:
        """Hisse vs sektör göreli gücü."""
        if sector_return == 0:
            return 0.0
        return round(float(stock_return - sector_return), 4)


class RelativeStrengthEngine:
    """Göreceli güç motoru."""

    def compute(self, stock_returns: list[float], benchmark_returns: list[float], period: int = 20) -> dict[str, float]:
        """Göreceli güç hesapla."""
        if len(stock_returns) < period or len(benchmark_returns) < period:
            return {}

        stock_ret = sum(stock_returns[-period:])
        bench_ret = sum(benchmark_returns[-period:])

        rs = stock_ret / bench_ret if bench_ret != 0 else 1.0

        return {
            "relative_strength": round(float(rs), 4),
            "outperforming": 1.0 if rs > 1.0 else 0.0,
            "rs_rank": round(float(stock_ret - bench_ret), 4),
        }


class CorrelationEngine:
    """Korelasyon motoru."""

    def compute_rolling_correlation(self, series_a: list[float], series_b: list[float], window: int = 20) -> float:
        """Rolling korelasyon hesapla."""
        if len(series_a) < window or len(series_b) < window:
            return 0.0

        a = np.array(series_a[-window:])
        b = np.array(series_b[-window:])

        if np.std(a) == 0 or np.std(b) == 0:
            return 0.0

        corr = np.corrcoef(a, b)[0, 1]
        return round(float(corr), 4) if not np.isnan(corr) else 0.0


class DrawdownEngine:
    """Drawdown motoru."""

    def compute(self, equity_curve: list[float]) -> dict[str, float]:
        """Drawdown hesapla."""
        if not equity_curve or len(equity_curve) < 2:
            return {}

        peak = equity_curve[0]
        max_dd = 0
        current_dd = 0
        dd_duration = 0
        max_dd_duration = 0

        for e in equity_curve:
            if e > peak:
                peak = e
                dd_duration = 0
            dd = (peak - e) / peak if peak > 0 else 0
            if dd > max_dd:
                max_dd = dd
            if dd > 0:
                dd_duration += 1
                max_dd_duration = max(max_dd_duration, dd_duration)
            current_dd = dd

        return {
            "max_drawdown_pct": round(max_dd * 100, 2),
            "current_drawdown_pct": round(current_dd * 100, 2),
            "max_drawdown_duration": max_dd_duration,
        }


class PositionRiskEngine:
    """Pozisyon risk motoru."""

    def compute(self, position_value: float, portfolio_value: float, volatility: float, correlation: float) -> dict[str, float]:
        """Pozisyon risk metrikleri."""
        if portfolio_value <= 0:
            return {}

        weight = position_value / portfolio_value
        vol_contribution = weight * volatility
        var_contribution = weight * volatility * 1.65  # 95% VaR

        return {
            "position_weight": round(weight, 4),
            "volatility_contribution": round(vol_contribution, 4),
            "var_contribution": round(var_contribution, 4),
            "correlation_to_portfolio": round(correlation, 4),
        }


class ModelRiskEngine:
    """Model risk motoru."""

    def compute_reliability(self, predictions: list[float], actuals: list[float]) -> dict[str, float]:
        """Model güvenilirliği hesapla."""
        if len(predictions) != len(actuals) or len(predictions) < 5:
            return {"model_reliability": 0.5}

        errors = [abs(p - a) for p, a in zip(predictions, actuals, strict=False)]
        mean_error = np.mean(errors)
        np.std(errors)

        # Reliability: düşük hata = yüksek güvenilirlik
        reliability = max(0, 1 - mean_error / (np.mean(np.abs(actuals)) + 0.001))

        # Calibration: predicted vs actual correlation
        if np.std(predictions) > 0 and np.std(actuals) > 0:
            calibration = np.corrcoef(predictions, actuals)[0, 1]
        else:
            calibration = 0.0

        return {
            "model_reliability": round(float(reliability), 4),
            "model_calibration": round(float(calibration), 4) if not np.isnan(calibration) else 0.0,
            "mean_absolute_error": round(float(mean_error), 4),
        }


class DataConfidenceEngine:
    """Veri güvenilirliği motoru."""

    def compute(self, data_quality: float, model_reliability: float, source_reliability: float, agreement: float) -> dict[str, float]:
        """Genel güvenilirlik skoru."""
        # Weighted average
        confidence = (
            data_quality * 0.30 +
            model_reliability * 0.30 +
            source_reliability * 0.20 +
            agreement * 0.20
        )

        return {
            "data_confidence": round(confidence, 4),
            "data_quality": round(data_quality, 4),
            "model_reliability": round(model_reliability, 4),
            "source_reliability": round(source_reliability, 4),
            "agreement": round(agreement, 4),
        }


class PortfolioOptimization:
    """Portföy optimizasyon motoru."""

    def compute_optimal_weights(self, expected_returns: np.ndarray, cov_matrix: np.ndarray, method: str = "min_volatility") -> np.ndarray:
        """Optimal ağırlıkları hesapla."""
        n = len(expected_returns)
        if n == 0:
            return np.array([])

        if method == "min_volatility":
            # Minimum variance portfolio
            try:
                inv_cov = np.linalg.inv(cov_matrix)
                ones = np.ones(n)
                weights = inv_cov @ ones / (ones @ inv_cov @ ones)
                weights = np.maximum(weights, 0)  # No short selling
                weights = weights / weights.sum() if weights.sum() > 0 else np.ones(n) / n
            except np.linalg.LinAlgError:
                weights = np.ones(n) / n

        elif method == "max_sharpe":
            # Maximum Sharpe (simplified)
            try:
                inv_cov = np.linalg.inv(cov_matrix)
                weights = inv_cov @ expected_returns
                weights = np.maximum(weights, 0)
                weights = weights / weights.sum() if weights.sum() > 0 else np.ones(n) / n
            except np.linalg.LinAlgError:
                weights = np.ones(n) / n

        else:
            # Equal weight
            weights = np.ones(n) / n

        return weights


# Singletons
price_action_engine = PriceActionEngine()
support_resistance_engine = SupportResistanceEngine()
volume_engine = VolumeEngine()
sector_engine = SectorEngine()
relative_strength_engine = RelativeStrengthEngine()
correlation_engine = CorrelationEngine()
drawdown_engine = DrawdownEngine()
position_risk_engine = PositionRiskEngine()
model_risk_engine = ModelRiskEngine()
data_confidence_engine = DataConfidenceEngine()
portfolio_optimization = PortfolioOptimization()
