"""
ALPHA BIST — Analysis Engines v1.1

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

from __future__ import annotations

import numpy as np
import structlog

logger = structlog.get_logger()

# ─── Sabitler ────────────────────────────────────────────────────────
DEFAULT_VAR_CONFIDENCE_Z: float = 1.65  # %95 VaR z-score
DEFAULT_DATA_CONFIDENCE_WEIGHTS: tuple[float, float, float, float] = (0.30, 0.30, 0.20, 0.20)
BREAKOUT_TOLERANCE: float = 0.99
BREAKDOWN_TOLERANCE: float = 1.01
GAP_THRESHOLD_PCT: float = 1.0
CONSOLIDATION_RATIO: float = 0.5
HAMMER_SHADOW_RATIO: float = 2.0
DEFAULT_RELIABILITY: float = 0.5
MIN_CORRELATION_WINDOW: int = 5
EPSILON: float = 1e-10

__all__ = [
    "PriceActionEngine",
    "SupportResistanceEngine",
    "VolumeEngine",
    "SectorEngine",
    "RelativeStrengthEngine",
    "CorrelationEngine",
    "DrawdownEngine",
    "PositionRiskEngine",
    "ModelRiskEngine",
    "DataConfidenceEngine",
    "PortfolioOptimization",
    "price_action_engine",
    "support_resistance_engine",
    "volume_engine",
    "sector_engine",
    "relative_strength_engine",
    "correlation_engine",
    "drawdown_engine",
    "position_risk_engine",
    "model_risk_engine",
    "data_confidence_engine",
    "portfolio_optimization",
]


# ─── Price Action Engine ─────────────────────────────────────────────


class PriceActionEngine:
    """Price Action analiz motoru.

    Fiyat verisinden mum formasyonu ve yapısal patern tespiti yapar.
    """

    def __repr__(self) -> str:
        return "<PriceActionEngine>"

    def detect_patterns(
        self, open_: np.ndarray, high: np.ndarray, low: np.ndarray, close: np.ndarray
    ) -> dict[str, float]:
        """Fiyat paternlerini tespit et.

        Args:
            open_: Açılış fiyatları dizisi.
            high: En yüksek fiyatlar dizisi.
            low: En düşük fiyatlar dizisi.
            close: Kapanış fiyatları dizisi.

        Returns:
            Tespit edilen paternlerin isim-skor sözlüğü.

        Raises:
            ValueError: Diziler farklı uzunlukta ise.
        """
        if not (len(open_) == len(high) == len(low) == len(close)):
            raise ValueError("OHLC dizileri aynı uzunlukta olmalıdır.")

        n = len(close)
        if n < 5:
            logger.warning("pattern_veri_yetersiz", n=n, minimum=5)
            return {}

        features: dict[str, float] = {}

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
            features["breakout_up"] = 1.0 if close[-1] > high_20 * BREAKOUT_TOLERANCE else 0.0
            features["breakdown"] = 1.0 if close[-1] < low_20 * BREAKDOWN_TOLERANCE else 0.0

        # Consolidation (sıkışma)
        if n >= 10:
            range_10 = (np.max(high[-10:]) - np.min(low[-10:])) / close[-1] * 100
            range_20 = (
                (np.max(high[-20:]) - np.min(low[-20:])) / close[-1] * 100
                if n >= 20
                else range_10
            )
            features["consolidation"] = 1.0 if range_10 < range_20 * CONSOLIDATION_RATIO else 0.0

        # Gap
        if n >= 2:
            gap = (open_[-1] / close[-2] - 1) * 100
            features["gap_up"] = 1.0 if gap > GAP_THRESHOLD_PCT else 0.0
            features["gap_down"] = 1.0 if gap < -GAP_THRESHOLD_PCT else 0.0

        # Reversal patterns
        if n >= 3:
            body = abs(close[-1] - open_[-1])
            lower_shadow = min(close[-1], open_[-1]) - low[-1]
            upper_shadow = high[-1] - max(close[-1], open_[-1])
            if body > 0:
                features["hammer"] = (
                    1.0 if lower_shadow > body * HAMMER_SHADOW_RATIO and upper_shadow < body else 0.0
                )
                features["shooting_star"] = (
                    1.0 if upper_shadow > body * HAMMER_SHADOW_RATIO and lower_shadow < body else 0.0
                )

        return features


# ─── Support / Resistance Engine ─────────────────────────────────────


class SupportResistanceEngine:
    """Support/Resistance seviye tespiti motoru.

    Swing high/low noktalarından dinamik destek ve direnç seviyeleri üretir.
    """

    def __repr__(self) -> str:
        return "<SupportResistanceEngine>"

    def compute_levels(
        self, high: np.ndarray, low: np.ndarray, close: np.ndarray, period: int = 20
    ) -> dict[str, float]:
        """Destek ve direnç seviyeleri hesapla.

        Args:
            high: En yüksek fiyatlar dizisi.
            low: En düşük fiyatlar dizisi.
            close: Kapanış fiyatları dizisi.
            period: Geriye dönük bakış periyodu.

        Returns:
            resistance_N, support_N ve sr_position anahtarları içeren sözlük.

        Raises:
            ValueError: period <= 2 ise.
        """
        if period <= 2:
            raise ValueError("period parametresi 2'den büyük olmalıdır.")

        n = len(close)
        if n < period:
            logger.warning("sr_veri_yetersiz", n=n, period=period)
            return {}

        swing_highs: list[float] = []
        swing_lows: list[float] = []
        for i in range(2, min(period, n - 2)):
            if high[-i] > high[-i - 1] and high[-i] > high[-i + 1]:
                swing_highs.append(float(high[-i]))
            if low[-i] < low[-i - 1] and low[-i] < low[-i + 1]:
                swing_lows.append(float(low[-i]))

        resistance = sorted(swing_highs, reverse=True)[:3] if swing_highs else [float(np.max(high[-period:]))]
        support = sorted(swing_lows)[:3] if swing_lows else [float(np.min(low[-period:]))]

        features: dict[str, float] = {}
        for i, r in enumerate(resistance):
            features[f"resistance_{i + 1}"] = round(r, 2)
        for i, s in enumerate(support):
            features[f"support_{i + 1}"] = round(s, 2)

        price = float(close[-1])
        if resistance and support:
            range_val = resistance[0] - support[0]
            if range_val > 0:
                features["sr_position"] = round((price - support[0]) / range_val, 4)

        return features


# ─── Volume Engine ───────────────────────────────────────────────────


class VolumeEngine:
    """Hacim analiz motoru.

    OBV, hacim onayı ve hacim sapması metrikleri üretir.
    """

    def __repr__(self) -> str:
        return "<VolumeEngine>"

    def compute(self, close: np.ndarray, volume: np.ndarray) -> dict[str, float]:
        """Hacim analizi yap.

        Args:
            close: Kapanış fiyatları dizisi.
            volume: Hacim dizisi.

        Returns:
            obv_20d, volume_confirmation ve volume_divergence anahtarları.

        Raises:
            ValueError: Diziler farklı uzunlukta ise.
        """
        if len(close) != len(volume):
            raise ValueError("close ve volume dizileri aynı uzunlukta olmalıdır.")

        n = len(close)
        if n < 20:
            logger.warning("volume_veri_yetersiz", n=n, minimum=20)
            return {}

        features: dict[str, float] = {}

        # OBV (On Balance Volume)
        obv = 0
        for i in range(1, min(n, 20)):
            if close[-i] > close[-i - 1]:
                obv += volume[-i]
            elif close[-i] < close[-i - 1]:
                obv -= volume[-i]
        features["obv_20d"] = float(obv)

        # Volume confirmation
        price_up = close[-1] > close[-2]
        vol_up = volume[-1] > np.mean(volume[-20:])
        features["volume_confirmation"] = 1.0 if price_up and vol_up else 0.0

        # Volume divergence (fiyat yükseliyor ama hacim düşüyor)
        if n >= 5:
            price_trend = close[-1] > close[-5]
            vol_trend = np.mean(volume[-3:]) < np.mean(volume[-5:-2])
            features["volume_divergence"] = 1.0 if price_trend and vol_trend else 0.0

        return features


# ─── Sector Engine ───────────────────────────────────────────────────


class SectorEngine:
    """Sektör analiz motoru.

    Sektör getirilerinden momentum ve göreli güç hesaplar.
    """

    def __repr__(self) -> str:
        return "<SectorEngine>"

    def compute_sector_momentum(self, sector_returns: dict[str, list[float]]) -> dict[str, float]:
        """Sektör momentum hesapla.

        Args:
            sector_returns: Sektör adı → getiri listesi sözlüğü.

        Returns:
            sector_{ad}_momentum_Nd anahtarları içeren sözlük.
        """
        features: dict[str, float] = {}
        for sector, returns in sector_returns.items():
            if len(returns) >= 20:
                features[f"sector_{sector}_momentum_20d"] = round(float(np.mean(returns[-20:]) * 100), 2)
            if len(returns) >= 5:
                features[f"sector_{sector}_momentum_5d"] = round(float(np.mean(returns[-5:]) * 100), 2)
        return features

    def compute_sector_relative_strength(self, stock_return: float, sector_return: float) -> float:
        """Hisse vs sektör göreli gücü.

        Args:
            stock_return: Hisse getirisi.
            sector_return: Sektör getirisi.

        Returns:
            Göreli güç farkı (float).
        """
        if sector_return == 0:
            return 0.0
        return round(float(stock_return - sector_return), 4)


# ─── Relative Strength Engine ────────────────────────────────────────


class RelativeStrengthEngine:
    """Göreceli güç motoru.

    Hisse ve benchmark getirilerini karşılaştırarak göreli güç üretir.
    """

    def __repr__(self) -> str:
        return "<RelativeStrengthEngine>"

    def compute(
        self, stock_returns: list[float], benchmark_returns: list[float], period: int = 20
    ) -> dict[str, float]:
        """Göreceli güç hesapla.

        Args:
            stock_returns: Hisse getiri serisi.
            benchmark_returns: Benchmark getiri serisi.
            period: Hesaplama periyodu.

        Returns:
            relative_strength, outperforming ve rs_rank anahtarları.

        Raises:
            ValueError: period < 1 ise.
        """
        if period < 1:
            raise ValueError("period parametresi pozitif olmalıdır.")

        if len(stock_returns) < period or len(benchmark_returns) < period:
            logger.warning("rs_veri_yetersiz", stock_len=len(stock_returns), bench_len=len(benchmark_returns), period=period)
            return {}

        stock_ret = sum(stock_returns[-period:])
        bench_ret = sum(benchmark_returns[-period:])

        rs = stock_ret / bench_ret if abs(bench_ret) > EPSILON else 1.0

        return {
            "relative_strength": round(float(rs), 4),
            "outperforming": 1.0 if rs > 1.0 else 0.0,
            "rs_rank": round(float(stock_ret - bench_ret), 4),
        }


# ─── Correlation Engine ──────────────────────────────────────────────


class CorrelationEngine:
    """Korelasyon motoru.

    İki seri arasında rolling korelasyon hesaplar.
    """

    def __repr__(self) -> str:
        return "<CorrelationEngine>"

    def compute_rolling_correlation(
        self, series_a: list[float], series_b: list[float], window: int = 20
    ) -> float:
        """Rolling korelasyon hesapla.

        Args:
            series_a: Birinci seri.
            series_b: İkinci seri.
            window: Pencere boyutu.

        Returns:
            Korelasyon katsayısı (-1 ile 1 arası). Yetersiz veride 0.0.

        Raises:
            ValueError: window < MIN_CORRELATION_WINDOW ise.
        """
        if window < MIN_CORRELATION_WINDOW:
            raise ValueError(f"window en az {MIN_CORRELATION_WINDOW} olmalıdır.")

        if len(series_a) < window or len(series_b) < window:
            logger.warning("korelasyon_veri_yetersiz", a_len=len(series_a), b_len=len(series_b), window=window)
            return 0.0

        a = np.array(series_a[-window:])
        b = np.array(series_b[-window:])

        if np.std(a) == 0 or np.std(b) == 0:
            return 0.0

        corr = np.corrcoef(a, b)[0, 1]
        return round(float(corr), 4) if not np.isnan(corr) else 0.0


# ─── Drawdown Engine ─────────────────────────────────────────────────


class DrawdownEngine:
    """Drawdown motoru.

    Equity curve üzerinden maksimum ve güncel drawdown hesaplar.
    """

    def __repr__(self) -> str:
        return "<DrawdownEngine>"

    def compute(self, equity_curve: list[float]) -> dict[str, float]:
        """Drawdown hesapla.

        Args:
            equity_curve: Equity curve (zaman serisi).

        Returns:
            max_drawdown_pct, current_drawdown_pct ve max_drawdown_duration.

        Raises:
            ValueError: equity_curve None ise.
        """
        if equity_curve is None:
            raise ValueError("equity_curve None olamaz.")

        if len(equity_curve) < 2:
            logger.warning("drawdown_veri_yetersiz", n=len(equity_curve))
            return {}

        peak = equity_curve[0]
        max_dd = 0.0
        current_dd = 0.0
        dd_duration = 0
        max_dd_duration = 0

        for e in equity_curve:
            if e > peak:
                peak = e
                dd_duration = 0
            dd = (peak - e) / peak if peak > 0 else 0.0
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


# ─── Position Risk Engine ────────────────────────────────────────────


class PositionRiskEngine:
    """Pozisyon risk motoru.

    Pozisyon ağırlığı, volatilite katkısı ve VaR katkısı hesaplar.
    """

    def __repr__(self) -> str:
        return "<PositionRiskEngine>"

    def compute(
        self, position_value: float, portfolio_value: float, volatility: float, correlation: float
    ) -> dict[str, float]:
        """Pozisyon risk metrikleri.

        Args:
            position_value: Pozisyon değeri.
            portfolio_value: Portföy toplam değeri.
            volatility: Pozisyon volatilitesi.
            correlation: Portföy ile korelasyon.

        Returns:
            position_weight, volatility_contribution, var_contribution, correlation_to_portfolio.

        Raises:
            ValueError: portfolio_value <= 0 ise.
        """
        if portfolio_value <= 0:
            raise ValueError("portfolio_value pozitif olmalıdır.")

        weight = position_value / portfolio_value
        vol_contribution = weight * volatility
        var_contribution = weight * volatility * DEFAULT_VAR_CONFIDENCE_Z

        return {
            "position_weight": round(weight, 4),
            "volatility_contribution": round(vol_contribution, 4),
            "var_contribution": round(var_contribution, 4),
            "correlation_to_portfolio": round(correlation, 4),
        }


# ─── Model Risk Engine ───────────────────────────────────────────────


class ModelRiskEngine:
    """Model risk motoru.

    Tahmin vs gerçek değer karşılaştırmasıyla model güvenilirliği üretir.
    """

    def __repr__(self) -> str:
        return "<ModelRiskEngine>"

    def compute_reliability(self, predictions: list[float], actuals: list[float]) -> dict[str, float]:
        """Model güvenilirliği hesapla.

        Args:
            predictions: Model tahminleri.
            actuals: Gerçek değerler.

        Returns:
            model_reliability, model_calibration, mean_absolute_error.

        Raises:
            ValueError: predictions ve actuals farklı uzunlukta ise.
        """
        if len(predictions) != len(actuals):
            raise ValueError("predictions ve actuals aynı uzunlukta olmalıdır.")

        if len(predictions) < 5:
            logger.warning("model_reliability_veri_yetersiz", n=len(predictions), minimum=5)
            return {"model_reliability": DEFAULT_RELIABILITY}

        errors = [abs(p - a) for p, a in zip(predictions, actuals, strict=False)]
        mean_error = float(np.mean(errors))

        # Reliability: düşük hata = yüksek güvenilirlik
        mean_abs_actuals = float(np.mean(np.abs(actuals)))
        reliability = max(0.0, 1.0 - mean_error / (mean_abs_actuals + EPSILON))

        # Calibration: predicted vs actual correlation
        if np.std(predictions) > 0 and np.std(actuals) > 0:
            calibration = float(np.corrcoef(predictions, actuals)[0, 1])
        else:
            calibration = 0.0

        return {
            "model_reliability": round(reliability, 4),
            "model_calibration": round(calibration, 4) if not np.isnan(calibration) else 0.0,
            "mean_absolute_error": round(mean_error, 4),
        }


# ─── Data Confidence Engine ──────────────────────────────────────────


class DataConfidenceEngine:
    """Veri güvenilirliği motoru.

    Çoklu kaynaktan gelen güvenilirlik skorlarını ağırlıklı olarak birleştirir.
    """

    def __repr__(self) -> str:
        return "<DataConfidenceEngine>"

    def compute(
        self, data_quality: float, model_reliability: float, source_reliability: float, agreement: float
    ) -> dict[str, float]:
        """Genel güvenilirlik skoru hesapla.

        Args:
            data_quality: Veri kalitesi skoru (0-1).
            model_reliability: Model güvenilirliği (0-1).
            source_reliability: Kaynak güvenilirliği (0-1).
            agreement: Uzlaşı skoru (0-1).

        Returns:
            data_confidence ve bileşen skorları.
        """
        w_dq, w_mr, w_sr, w_ag = DEFAULT_DATA_CONFIDENCE_WEIGHTS
        confidence = (
            data_quality * w_dq
            + model_reliability * w_mr
            + source_reliability * w_sr
            + agreement * w_ag
        )

        return {
            "data_confidence": round(confidence, 4),
            "data_quality": round(data_quality, 4),
            "model_reliability": round(model_reliability, 4),
            "source_reliability": round(source_reliability, 4),
            "agreement": round(agreement, 4),
        }


# ─── Portfolio Optimization ──────────────────────────────────────────


class PortfolioOptimization:
    """Portföy optimizasyon motoru.

    Minimum varyans ve maksimum Sharpe yöntemleriyle optimal ağırlık üretir.
    """

    def __repr__(self) -> str:
        return "<PortfolioOptimization>"

    def compute_optimal_weights(
        self, expected_returns: np.ndarray, cov_matrix: np.ndarray, method: str = "min_volatility"
    ) -> np.ndarray:
        """Optimal ağırlıkları hesapla.

        Args:
            expected_returns: Beklenen getiri vektörü.
            cov_matrix: Kovaryans matrisi.
            method: Optimizasyon yöntemi ('min_volatility', 'max_sharpe' veya 'equal').

        Returns:
            Ağırlık vektörü (toplamı 1.0).

        Raises:
            ValueError: Bilinmeyen method ise.
        """
        n = len(expected_returns)
        if n == 0:
            logger.warning("portfolio_bos_varlik")
            return np.array([])

        if method == "min_volatility":
            try:
                inv_cov = np.linalg.inv(cov_matrix)
                ones = np.ones(n)
                weights = inv_cov @ ones / (ones @ inv_cov @ ones)
                weights = np.maximum(weights, 0)
                weights = weights / weights.sum() if weights.sum() > 0 else np.ones(n) / n
            except np.linalg.LinAlgError:
                logger.warning("portfolio_tekil_kovaryans", method=method)
                weights = np.ones(n) / n

        elif method == "max_sharpe":
            try:
                inv_cov = np.linalg.inv(cov_matrix)
                weights = inv_cov @ expected_returns
                weights = np.maximum(weights, 0)
                weights = weights / weights.sum() if weights.sum() > 0 else np.ones(n) / n
            except np.linalg.LinAlgError:
                logger.warning("portfolio_tekil_kovaryans", method=method)
                weights = np.ones(n) / n

        elif method == "equal":
            weights = np.ones(n) / n

        else:
            raise ValueError(f"Bilinmeyen optimizasyon yöntemi: {method!r}. 'min_volatility', 'max_sharpe' veya 'equal'.")

        return weights


# ─── Singletons ──────────────────────────────────────────────────────

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
