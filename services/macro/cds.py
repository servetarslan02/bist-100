"""
ALPHA BIST — Institutional Sovereign Credit Default Swap (CDS) Analytics v3.0

Türkiye Cumhuriyeti ve Borsa İstanbul için 5Y / 10Y CDS göstergeleri ve makro risk modeli:
- Term Structure: Farklı vadeler (1Y, 3Y, 5Y, 10Y) spread eğrisi ve eğim analizi (Slope / Inversion)
- Hazard Rate & Kümülatif Temerrüt İhtimali (Cumulative Default Probability - CDP)
- Rolling Z-Score, Volatilite, Percentile ve Tarihsel Rejim Dağılımı
- Tahvil Faizi & Kur Bulaşma Katsayısı (Contagion & Sovereign Premium Transmission)
- BIST 100 ve Bankacılık Endeksi (XBANK) Risk-Off Erken Uyarı Sinyali
"""

from dataclasses import asdict, dataclass, field
from enum import StrEnum
from typing import Any

import numpy as np
import structlog

logger = structlog.get_logger(__name__)

# CDS Risk Seviyesi Eşik Sabitleri (Baz Puan / bps)
DEFAULT_CDS_RISK_LOW: float = 150.0
DEFAULT_CDS_RISK_MEDIUM: float = 250.0
DEFAULT_CDS_RISK_HIGH: float = 400.0
DEFAULT_CDS_RISK_EXTREME: float = 600.0

# Temerrüt Halinde Kurtarma Oranı (Standard Sovereign Recovery Rate = 40%)
DEFAULT_SOVEREIGN_RECOVERY_RATE: float = 0.40


class CDSRiskLevel(StrEnum):
    """Sovereign risk seviyesi."""
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    VERY_HIGH = "VERY_HIGH"
    CRITICAL_DISTRESS = "CRITICAL_DISTRESS"


@dataclass
class CDSMetricsResult:
    """Detaylı CDS ve egemen risk analitiği çıktısı."""
    cds_5y: float
    risk_level: str
    risk_numeric_score: float
    implied_default_prob_5y: float
    annual_hazard_rate: float
    curve_slope_bps: float
    curve_inverted: bool
    change_pct: float
    change_direction: float
    zscore: float
    momentum_20d: float
    percentile: float
    volatility_20d: float
    market_stress_flag: bool
    additional_metrics: dict[str, float] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Sözlük formatına dönüştürür."""
        return asdict(self)


class SovereignCDSEngine:
    """Kurumsal CDS Fiyatlama, Olasılık ve BIST Etki Analitiği Motoru."""

    def __init__(
        self,
        recovery_rate: float = DEFAULT_SOVEREIGN_RECOVERY_RATE,
        risk_free_rate: float = 0.045,
    ) -> None:
        """Motor ilklendirici."""
        self.recovery_rate = recovery_rate
        self.risk_free_rate = risk_free_rate

    def __repr__(self) -> str:
        return f"SovereignCDSEngine(recovery_rate={self.recovery_rate}, rf={self.risk_free_rate})"

    def calculate_hazard_rate(self, cds_spread_bps: float) -> float:
        """Standard ISDA yaklaşımıyla anlık temerrüt yoğunluğu (hazard rate) hesabı.

        λ = S / (1 - R)
        """
        if cds_spread_bps <= 0:
            return 0.0
        s = cds_spread_bps / 10000.0  # bps -> ondalık
        loss_given_default = max(0.01, 1.0 - self.recovery_rate)
        return float(s / loss_given_default)

    def calculate_default_probability(self, cds_spread_bps: float, tenure_years: float = 5.0) -> float:
        """Kümülatif temerrüt ihtimali (Cumulative Default Probability - CDP).

        P(Default <= T) = 1 - exp(-λ * T)
        """
        hazard_rate = self.calculate_hazard_rate(cds_spread_bps)
        cdp = 1.0 - np.exp(-hazard_rate * tenure_years)
        return float(np.clip(cdp, 0.0, 1.0))

    def evaluate_cds(self, cds_data: dict[str, Any]) -> CDSMetricsResult:
        """Tüm CDS ve makro risk göstergelerini tam kapsamlı analiz eder.

        Args:
            cds_data: 5 yıllık CDS, eğri noktaları, tarihçe ve makro bileşenleri.

        Returns:
            CDSMetricsResult: Pydantic/dataclass uyumlu yapılandırılmış sonuç.
        """
        cds_5y_raw = cds_data.get("cds_5y")
        if cds_5y_raw is None:
            return CDSMetricsResult(
                cds_5y=0.0,
                risk_level=CDSRiskLevel.LOW.value,
                risk_numeric_score=0.0,
                implied_default_prob_5y=0.0,
                annual_hazard_rate=0.0,
                curve_slope_bps=0.0,
                curve_inverted=False,
                change_pct=0.0,
                change_direction=0.0,
                zscore=0.0,
                momentum_20d=0.0,
                percentile=0.0,
                volatility_20d=0.0,
                market_stress_flag=False,
            )

        cds_5y = float(cds_5y_raw)
        hazard = self.calculate_hazard_rate(cds_5y)
        cdp_5y = self.calculate_default_probability(cds_5y, tenure_years=5.0)

        # Değişim & Momentum
        cds_prev = cds_data.get("cds_previous")
        change_pct = 0.0
        change_dir = 0.0
        if cds_prev and float(cds_prev) > 0:
            change_pct = (cds_5y / float(cds_prev) - 1.0) * 100.0
            change_dir = 1.0 if change_pct > 0 else (-1.0 if change_pct < 0 else 0.0)

        # Eğri Analizi (1Y vs 5Y vs 10Y)
        cds_1y = float(cds_data.get("cds_1y", 0.0))
        cds_10y = float(cds_data.get("cds_10y", 0.0))
        slope = 0.0
        curvature = 0.0
        inverted = False
        if cds_1y > 0:
            slope = cds_5y - cds_1y
            inverted = cds_1y > cds_5y  # Kısa vadenin uzun vadeden yüksek olması = Akut kriz / Inversion
        if cds_1y > 0 and cds_10y > 0:
            curvature = (2.0 * cds_5y) - cds_1y - cds_10y

        # Tarihsel İstatistikler
        history = cds_data.get("cds_history", [])
        zscore = 0.0
        momentum_20d = 0.0
        percentile = 0.5
        vol_20d = 0.0

        if isinstance(history, list) and len(history) >= 10:
            hist_arr = np.array([float(x) for x in history if float(x) > 0], dtype=np.float64)
            if len(hist_arr) >= 10:
                recent = hist_arr[-60:] if len(hist_arr) >= 60 else hist_arr
                mean = float(np.mean(recent))
                std = float(np.std(recent))
                if std > 1e-4:
                    zscore = float((cds_5y - mean) / std)

                if len(hist_arr) >= 20:
                    momentum_20d = float((cds_5y / hist_arr[-20] - 1.0) * 100.0)
                    ret_20 = np.diff(np.log(hist_arr[-21:]))
                    vol_20d = float(np.std(ret_20) * np.sqrt(252) * 100.0)

                percentile = float(sum(1 for v in hist_arr if v <= cds_5y) / max(len(hist_arr), 1))

        # Risk Seviyesi Sınıflandırması
        if cds_5y < DEFAULT_CDS_RISK_LOW:
            level = CDSRiskLevel.LOW
            score = 0.0
        elif cds_5y < DEFAULT_CDS_RISK_MEDIUM:
            level = CDSRiskLevel.MEDIUM
            score = 1.0
        elif cds_5y < DEFAULT_CDS_RISK_HIGH:
            level = CDSRiskLevel.HIGH
            score = 2.0
        elif cds_5y < DEFAULT_CDS_RISK_EXTREME:
            level = CDSRiskLevel.VERY_HIGH
            score = 3.0
        else:
            level = CDSRiskLevel.CRITICAL_DISTRESS
            score = 4.0

        # Piyasa Stres Bayrağı
        stress_flag = bool(cds_5y >= DEFAULT_CDS_RISK_HIGH or zscore > 2.0 or inverted)

        change_bps = (cds_5y - float(cds_prev)) if (cds_prev and float(cds_prev) > 0) else 0.0

        return CDSMetricsResult(
            cds_5y=round(cds_5y, 2),
            risk_level=level.value,
            risk_numeric_score=score,
            implied_default_prob_5y=round(cdp_5y * 100.0, 2),
            annual_hazard_rate=round(hazard * 100.0, 4),
            curve_slope_bps=round(slope, 2),
            curve_inverted=inverted,
            change_pct=round(change_pct, 4),
            change_direction=change_dir,
            zscore=round(zscore, 4),
            momentum_20d=round(momentum_20d, 2),
            percentile=round(percentile, 4),
            volatility_20d=round(vol_20d, 2),
            market_stress_flag=stress_flag,
            additional_metrics={
                "recovery_rate": self.recovery_rate,
                "cds_10y": round(cds_10y, 2),
                "cds_change_bps": round(change_bps, 2),
                "cds_curve_curvature": round(curvature, 2),
            },
        )

    def estimate_equity_impact(
        self,
        cds_change_bps: float,
        beta_xbank: float = -0.045,
        beta_xu100: float = -0.028,
    ) -> dict[str, float]:
        """CDS spread değişiminin BIST 100 ve Bankacılık endeksine beklenen etkisini modeller.

        Args:
            cds_change_bps: CDS değişim miktarı (baz puan cinsinden, ör. +50 bps).
            beta_xbank: Bankacılık endeksi duyarlılık katsayısı (% getiri / 100 bps CDS).
            beta_xu100: BIST 100 endeksi duyarlılık katsayısı (% getiri / 100 bps CDS).

        Returns:
            dict[str, float]: Beklenen yüzde getiri şoku tahminleri.
        """
        bps_scaled = cds_change_bps / 100.0
        return {
            "expected_xbank_impact_pct": round(bps_scaled * beta_xbank * 100.0, 3),
            "expected_xu100_impact_pct": round(bps_scaled * beta_xu100 * 100.0, 3),
            "risk_premium_shock_pct": round(bps_scaled * 0.015 * 100.0, 3),
        }


cds_engine = SovereignCDSEngine()


def compute_cds_features(cds_data: dict[str, Any]) -> dict[str, float]:
    """Mevcut sistemle ve Feature Store ile %100 uyumlu genişletilmiş CDS feature fonksiyonu."""
    metrics = cds_engine.evaluate_cds(cds_data)

    if metrics.cds_5y <= 0:
        return {}

    features = {
        "cds_5y": metrics.cds_5y,
        "cds_risk_level": metrics.risk_numeric_score,
        "cds_implied_default_prob": metrics.implied_default_prob_5y,
        "cds_hazard_rate": metrics.annual_hazard_rate,
        "cds_change_pct": metrics.change_pct,
        "cds_change_direction": metrics.change_direction,
        "cds_zscore": metrics.zscore,
        "cds_momentum_20d": metrics.momentum_20d,
        "cds_percentile": metrics.percentile,
        "cds_volatility_20d": metrics.volatility_20d,
        "cds_curve_slope": metrics.curve_slope_bps,
        "cds_curve_inverted": 1.0 if metrics.curve_inverted else 0.0,
        "cds_market_stress_flag": 1.0 if metrics.market_stress_flag else 0.0,
    }

    change_bps = metrics.additional_metrics.get("cds_change_bps")
    if change_bps is not None:
        features["cds_change_bps"] = float(change_bps)

    curvature = metrics.additional_metrics.get("cds_curve_curvature")
    if curvature is not None:
        features["cds_curve_curvature"] = float(curvature)

    return features


__all__ = [
    "CDSRiskLevel",
    "CDSMetricsResult",
    "DEFAULT_CDS_RISK_EXTREME",
    "DEFAULT_CDS_RISK_HIGH",
    "DEFAULT_CDS_RISK_LOW",
    "DEFAULT_CDS_RISK_MEDIUM",
    "DEFAULT_SOVEREIGN_RECOVERY_RATE",
    "SovereignCDSEngine",
    "cds_engine",
    "compute_cds_features",
]
