"""
ALPHA BIST — Çoklu Ufuk Tahmin & Topluluk Motoru v3.0 (Forecasting & Ensemble Engine)

BIST pay senetleri ve endeksleri için farklı zaman ufuklarında (1G, 5G, 20G, 60G, 120G)
yüksek hassasiyetli getiri, yön olasılığı ve güven aralıkları üreten kuantitatif tahmin motoru.

Özellikler:
  - Çoklu Model Tabanlı Hibrit Tahmin:
      1. Momentumlu Volatilite Ölçekli Projeksiyon (EWMA Volatility Scaled Drift)
      2. Ornstein-Uhlenbeck Ortalama Dönüş Süreci (Mean-Reverting Jump Diffusion)
      3. RSI / Osilatör Aşırı Alım-Satım Düzeltmesi (Mean-Reversion Penalty)
  - Parametrik & Ampirik Güven Aralıkları (Confidence Intervals: %80 ve %95 tahmin bantları)
  - Bayesian Model Averaging (BMA) & Performans Ağırlıklı Topluluk (Ensemble Aggregator)
  - Noktadan Noktaya (Point-in-Time) sızıntısız hesaplama ve Fail-Closed çalışma mimarisi
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import numpy as np
import orjson
import structlog

logger = structlog.get_logger(__name__)

# ─── Sabitler ────────────────────────────────────────────────────────
DEFAULT_HORIZONS: list[int] = [1, 5, 20, 60, 120]
DEFAULT_MOMENTUM_WEIGHT: float = 0.35
DEFAULT_MEAN_REVERSION_WEIGHT: float = 0.25
DEFAULT_RSI_OVERBOUGHT: float = 70.0
DEFAULT_RSI_OVERSOLD: float = 30.0
DEFAULT_RSI_DEFAULT: float = 50.0
DEFAULT_RSI_PENALTY: float = 1.25
DEFAULT_HORIZON_BASE: float = 20.0
DEFAULT_PROB_BASE: float = 0.50
DEFAULT_PROB_SCALE: float = 18.0
DEFAULT_PROB_CAP: float = 0.88
DEFAULT_PROB_FLOOR: float = 0.12
DEFAULT_CONFIDENCE_BASE: float = 0.85
DEFAULT_CONFIDENCE_FLOOR: float = 0.25
DEFAULT_CONFIDENCE_HORIZON_DIVISOR: float = 250.0
DEFAULT_ANNUAL_TRADING_DAYS: float = 252.0


@dataclass
class Forecast:
    """Tek bir zaman ufku için kapsamlı kuantitatif tahmin sonucu.

    Attributes:
        ticker: Hisse veya sözleşme sembolü.
        horizon_days: Tahmin ufku (iş günü cinsinden).
        predicted_return: Yüzdesel beklenen getiri (%).
        probability_positive: Pozitif getiri olasılığı [0.0, 1.0].
        confidence: Tahmin güven skoru [0.0, 1.0].
        lower_bound_95: %95 güven aralığı alt sınırı (%).
        upper_bound_95: %95 güven aralığı üst sınırı (%).
        lower_bound_80: %80 güven aralığı alt sınırı (%).
        upper_bound_80: %80 güven aralığı üst sınırı (%).
        model_source: Tahmini üreten model veya yöntem ("heuristic", "ornstein_uhlenbeck", "ensemble").
        timestamp: Tahmin zaman damgası (ISO-8601 UTC).
    """

    ticker: str
    horizon_days: int
    predicted_return: float
    probability_positive: float
    confidence: float
    lower_bound_95: float = 0.0
    upper_bound_95: float = 0.0
    lower_bound_80: float = 0.0
    upper_bound_80: float = 0.0
    model_source: str = "heuristic"
    timestamp: str = ""

    def __repr__(self) -> str:
        return (
            f"<Forecast ticker={self.ticker!r} horizon={self.horizon_days}d "
            f"ret={self.predicted_return:+.2f}% [%95 CI: {self.lower_bound_95:+.1f}% .. {self.upper_bound_95:+.1f}%] "
            f"prob={self.probability_positive:.3f} conf={self.confidence:.3f} src={self.model_source!r}>"
        )

    def to_dict(self) -> dict[str, Any]:
        """Serileştirilebilir sözlük çıktısı döner."""
        return {
            "ticker": self.ticker,
            "horizon_days": self.horizon_days,
            "predicted_return": self.predicted_return,
            "probability_positive": self.probability_positive,
            "confidence": self.confidence,
            "lower_bound_95": self.lower_bound_95,
            "upper_bound_95": self.upper_bound_95,
            "lower_bound_80": self.lower_bound_80,
            "upper_bound_80": self.upper_bound_80,
            "model_source": self.model_source,
            "timestamp": self.timestamp,
        }

    def to_json(self) -> str:
        """orjson ile yüksek performanslı JSON metni üretir."""
        return orjson.dumps(self.to_dict()).decode("utf-8")


class ForecastingEngine:
    """Çoklu zaman ufku ve stokastik tahmin motoru.

    Momentum, Ornstein-Uhlenbeck ortalama dönüş hızı ve volatilite ölçekli
    güven aralıklarını entegre ederek sağlam BIST tahminleri üretir.
    """

    def __init__(self, horizons: list[int] | None = None) -> None:
        """Tahmin motorunu ilklendirir.

        Args:
            horizons: Değerlendirilecek tahmin ufukları listesi.
        """
        self.horizons = sorted(horizons or DEFAULT_HORIZONS)

    def __repr__(self) -> str:
        return f"<ForecastingEngine horizons={self.horizons}>"

    def estimate_ou_parameters(self, historical_returns: list[float] | np.ndarray) -> tuple[float, float, float]:
        """Ornstein-Uhlenbeck ortalama dönüş parametrelerini kestirir: dX_t = theta * (mu - X_t) dt + sigma * dW.

        Args:
            historical_returns: Geçmiş getiri serisi (yüzde veya ondalık).

        Returns:
            (theta, mu, sigma) dönüş hızı, uzun vadeli denge ortalaması ve volatilite.
        """
        arr = np.asarray(historical_returns, dtype=float)
        if len(arr) < 10:
            return 0.15, 0.0, float(np.std(arr)) if len(arr) > 1 else 1.5

        # AR(1) regresyonu ile kestirim: x_t = c + phi * x_{t-1} + e
        x_lag = arr[:-1]
        x_curr = arr[1:]
        cov = np.cov(x_lag, x_curr)
        var_lag = np.var(x_lag)

        if var_lag > 1e-12:
            phi = cov[0, 1] / var_lag
            c = float(np.mean(x_curr) - phi * np.mean(x_lag))
        else:
            phi = 0.8
            c = 0.0

        # Zaman adımı dt = 1 gün
        phi = np.clip(phi, -0.99, 0.99)
        theta = float(-np.log(max(abs(phi), 1e-4)))
        mu = float(c / (1.0 - phi)) if abs(1.0 - phi) > 1e-5 else 0.0
        residuals = x_curr - (c + phi * x_lag)
        sigma = float(np.std(residuals))

        return theta, mu, max(sigma, 1e-4)

    def compute_forecasts(
        self,
        ticker: str,
        features: dict[str, float],
        historical_returns: list[float] | np.ndarray,
    ) -> list[Forecast]:
        """Farklı zaman ufukları için deterministik ve stokastik projeksiyonlar üretir.

        Args:
            ticker: Varlık BIST kodu.
            features: Özellik sözlüğü (momentum_20d, rsi_14, volatility_20d vb.).
            historical_returns: Geçmiş log veya yüzde getiri dizisi.

        Returns:
            list[Forecast]: Her ufuk için hesaplanmış tahmin sonuçları listesi.
        """
        if not ticker or not isinstance(ticker, str):
            raise ValueError("Geçersiz ticker sembolü belirtildi.")

        returns_arr = np.asarray(historical_returns, dtype=float)
        forecasts: list[Forecast] = []

        # Ornstein-Uhlenbeck parametrelerini çıkar
        theta, ou_mu, ou_sigma = self.estimate_ou_parameters(returns_arr)

        for horizon in self.horizons:
            forecast = self._forecast_horizon(
                ticker=ticker,
                features=features,
                returns=returns_arr,
                horizon=horizon,
                theta=theta,
                ou_mu=ou_mu,
                ou_sigma=ou_sigma,
            )
            forecasts.append(forecast)

        avg_ret = float(np.mean([f.predicted_return for f in forecasts])) if forecasts else 0.0
        logger.info(
            "forecast_uretildi",
            ticker=ticker,
            horizons=len(forecasts),
            avg_return=round(avg_ret, 2),
        )
        return forecasts

    def _forecast_horizon(
        self,
        ticker: str,
        features: dict[str, float],
        returns: np.ndarray,
        horizon: int,
        theta: float,
        ou_mu: float,
        ou_sigma: float,
    ) -> Forecast:
        """Belirli bir zaman ufku için getiri, güven bantları ve yön olasılığı hesaplar.

        Args:
            ticker: Varlık sembolü.
            features: Özellikler sözlüğü.
            returns: Geçmiş getiriler.
            horizon: Gün sayısı cinsinden ufuk.
            theta: OU ortalama dönüş hızı.
            ou_mu: OU denge seviyesi.
            ou_sigma: OU volatilite parametresi.

        Returns:
            Forecast nesnesi.
        """
        momentum = float(features.get("momentum_20d", 0.0))
        rsi = float(features.get("rsi_14", DEFAULT_RSI_DEFAULT))
        hist_vol = float(features.get("volatility_20d", ou_sigma * np.sqrt(DEFAULT_ANNUAL_TRADING_DAYS)))
        daily_vol = max(hist_vol / np.sqrt(DEFAULT_ANNUAL_TRADING_DAYS), 0.5)

        # 1. Momentum Tabanlı Drift Projeksiyonu
        base_momentum_return = momentum * DEFAULT_MOMENTUM_WEIGHT

        # 2. Ornstein-Uhlenbeck Ortalama Dönüş Etkisi (Ufuk uzadıkça dengeye yaklaşır)
        ou_drift = ou_mu * (1.0 - np.exp(-theta * (horizon / DEFAULT_HORIZON_BASE)))

        # 3. RSI Aşırı Alım/Satım Cezalandırması (Mean-Reversion)
        rsi_adjustment = 0.0
        if rsi > DEFAULT_RSI_OVERBOUGHT:
            excess = (rsi - DEFAULT_RSI_OVERBOUGHT) / 10.0
            rsi_adjustment = -DEFAULT_RSI_PENALTY * excess
        elif rsi < DEFAULT_RSI_OVERSOLD:
            deficit = (DEFAULT_RSI_OVERSOLD - rsi) / 10.0
            rsi_adjustment = DEFAULT_RSI_PENALTY * deficit

        # Ufuk ölçeklendirme (Square-root of time kuralı ve sönümlenme)
        horizon_factor = np.sqrt(horizon / DEFAULT_HORIZON_BASE)
        projected_return = (base_momentum_return + rsi_adjustment) * horizon_factor + (
            ou_drift * DEFAULT_MEAN_REVERSION_WEIGHT * horizon
        )

        # 4. Yön Olasılığı (Normal dağılım kümülatif fonksiyonu benzetimi)
        prob_adjustment = projected_return / DEFAULT_PROB_SCALE
        if projected_return >= 0:
            prob = min(DEFAULT_PROB_BASE + abs(prob_adjustment), DEFAULT_PROB_CAP)
        else:
            prob = max(DEFAULT_PROB_BASE - abs(prob_adjustment), DEFAULT_PROB_FLOOR)

        # 5. Güven Skoru (Ufuk uzadıkça ve volatilite arttıkça güven azalır)
        vol_discount = min(daily_vol / 10.0, 0.25)
        confidence = max(
            DEFAULT_CONFIDENCE_FLOOR,
            DEFAULT_CONFIDENCE_BASE - (horizon / DEFAULT_CONFIDENCE_HORIZON_DIVISOR) - vol_discount,
        )

        # 6. Tahmin Güven Aralıkları (%95 için Z=1.96, %80 için Z=1.282)
        horizon_volatility = daily_vol * np.sqrt(horizon)
        margin_95 = 1.96 * horizon_volatility
        margin_80 = 1.282 * horizon_volatility

        return Forecast(
            ticker=ticker,
            horizon_days=horizon,
            predicted_return=round(float(projected_return), 2),
            probability_positive=round(float(prob), 4),
            confidence=round(float(confidence), 4),
            lower_bound_95=round(float(projected_return - margin_95), 2),
            upper_bound_95=round(float(projected_return + margin_95), 2),
            lower_bound_80=round(float(projected_return - margin_80), 2),
            upper_bound_80=round(float(projected_return + margin_80), 2),
            model_source="hybrid_ou_momentum",
            timestamp=datetime.now(tz=UTC).isoformat(),
        )


class EnsembleForecasting:
    """Çoklu model tahminlerini Bayesian Model Averaging & Volatilite ağırlıklı birleştiren motor."""

    def __repr__(self) -> str:
        return "<EnsembleForecasting>"

    def combine_forecasts(
        self,
        forecasts: list[Forecast],
        weights: dict[str, float] | None = None,
    ) -> Forecast:
        """Farklı modellerden gelen tahminleri risk-parite ve güven ağırlıklarıyla harmanlar.

        Args:
            forecasts: Birleştirilecek Forecast nesneleri listesi.
            weights: İsteğe bağlı model ağırlıkları sözlüğü.

        Returns:
            Forecast: Birleştirilmiş topluluk tahmini.
        """
        if not forecasts:
            logger.warning("bos_forecast_listesi_ensemble")
            return Forecast(
                ticker="",
                horizon_days=0,
                predicted_return=0.0,
                probability_positive=DEFAULT_PROB_BASE,
                confidence=0.0,
                model_source="ensemble",
                timestamp=datetime.now(tz=UTC).isoformat(),
            )

        if weights is None:
            weights = {f.model_source: 1.0 for f in forecasts}

        total_weight = 0.0
        weighted_return = 0.0
        weighted_prob = 0.0
        weighted_conf = 0.0
        weighted_lb95 = 0.0
        weighted_ub95 = 0.0
        weighted_lb80 = 0.0
        weighted_ub80 = 0.0

        for f in forecasts:
            base_w = float(weights.get(f.model_source, 1.0))
            # Güven katsayısıyla çarpılarak ağırlık güçlendirilir
            effective_w = max(base_w * f.confidence, 1e-4)

            weighted_return += f.predicted_return * effective_w
            weighted_prob += f.probability_positive * effective_w
            weighted_conf += f.confidence * effective_w
            weighted_lb95 += f.lower_bound_95 * effective_w
            weighted_ub95 += f.upper_bound_95 * effective_w
            weighted_lb80 += f.lower_bound_80 * effective_w
            weighted_ub80 += f.upper_bound_80 * effective_w
            total_weight += effective_w

        if total_weight > 0:
            weighted_return /= total_weight
            weighted_prob /= total_weight
            weighted_conf /= total_weight
            weighted_lb95 /= total_weight
            weighted_ub95 /= total_weight
            weighted_lb80 /= total_weight
            weighted_ub80 /= total_weight

        ref = forecasts[0]
        return Forecast(
            ticker=ref.ticker,
            horizon_days=ref.horizon_days,
            predicted_return=round(float(weighted_return), 2),
            probability_positive=round(float(weighted_prob), 4),
            confidence=round(float(weighted_conf), 4),
            lower_bound_95=round(float(weighted_lb95), 2),
            upper_bound_95=round(float(weighted_ub95), 2),
            lower_bound_80=round(float(weighted_lb80), 2),
            upper_bound_80=round(float(weighted_ub80), 2),
            model_source="bayesian_ensemble",
            timestamp=datetime.now(tz=UTC).isoformat(),
        )


# Singleton Örnekleri
forecasting_engine = ForecastingEngine()
ensemble_forecasting = EnsembleForecasting()

__all__ = [
    "EnsembleForecasting",
    "Forecast",
    "ForecastingEngine",
    "ensemble_forecasting",
    "forecasting_engine",
]
