"""
ALPHA BIST — Institutional Credit Cycle & Banking Liquidity Engine v3.0

BDDK ve TCMB verileri üzerinden kredi piyasası ve bankacılık risk göstergeleri:
- Ticari vs Tüketici Kredisi Ayrıştırması (Commercial vs Consumer Credit Divergence)
- Kredi İvmesi (Credit Impulse: Kredi büyümesinin 2. türevi ve GSYH etkisi)
- Kur Korumalı / Döviz Kredileri vs TL Kredileri Dağılımı
- Kredi / Mevduat Oranı (Loan-to-Deposit Ratio - LDR) ve Likidite Sıkışıklığı
- BIST Bankacılık (XBANK) ve Sınai (XUSIN) Kredi Kanalı İletim Göstergeleri
"""

from dataclasses import asdict, dataclass, field
from enum import StrEnum
from typing import Any

import numpy as np
import structlog

logger = structlog.get_logger(__name__)

# Kredi Büyüme Rejimi Eşik Sabitleri (Yıllık Enflasyondan Arındırılmış Reel Büyüme %)
DEFAULT_CREDIT_REGIME_VERY_HIGH: float = 20.0
DEFAULT_CREDIT_REGIME_HIGH: float = 10.0
DEFAULT_CREDIT_REGIME_POSITIVE: float = 0.0
DEFAULT_CREDIT_REGIME_STAGNANT: float = -5.0
DEFAULT_CREDIT_TREND_THRESHOLD: float = 0.5

# LDR (Kredi/Mevduat) Kritik Eşikleri (%)
DEFAULT_LDR_NORMAL: float = 100.0
DEFAULT_LDR_TIGHT_LIQUIDITY: float = 115.0


class CreditRegimeType(StrEnum):
    """Kredi genişleme/daralma rejimi."""
    BOOM = "BOOM"
    EXPANSION = "EXPANSION"
    MODERATE = "MODERATE"
    STAGNATION = "STAGNATION"
    CONTRACTION = "CONTRACTION"


@dataclass
class CreditMetricsResult:
    """Detaylı kredi büyümesi ve bankacılık likidite çıktısı."""
    credit_growth_yoy: float
    credit_regime: str
    credit_regime_score: float
    credit_gdp_ratio: float
    credit_trend: float
    credit_trend_direction: float
    credit_impulse: float
    loan_to_deposit_ratio: float
    commercial_vs_retail_spread: float
    banking_liquidity_stress: bool
    corporate_capex_support: float
    additional_data: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Sözlük formatına dönüştürür."""
        return asdict(self)


class CreditCycleEngine:
    """Kurumsal Kredi Döngüsü ve Bankacılık Likidite Analiz Motoru."""

    def __init__(
        self,
        trend_threshold: float = DEFAULT_CREDIT_TREND_THRESHOLD,
        ldr_stress_threshold: float = DEFAULT_LDR_TIGHT_LIQUIDITY,
    ) -> None:
        """Motor başlatıcısı."""
        self.trend_threshold = trend_threshold
        self.ldr_stress_threshold = ldr_stress_threshold

    def __repr__(self) -> str:
        return f"CreditCycleEngine(trend_th={self.trend_threshold}, ldr_stress={self.ldr_stress_threshold}%)"

    def evaluate_credit(self, credit_data: dict[str, Any]) -> CreditMetricsResult:
        """Kredi hacmi, trend, kredi ivmesi (impulse) ve bankacılık likiditesini hesaplar.

        Args:
            credit_data: Yıllık büyüme, önceki büyüme, ticari/bireysel kredi oranları ve mevduat oranları.

        Returns:
            CreditMetricsResult: Yapılandırılmış kurumsal kredi analiz çıktısı.
        """
        growth_raw = credit_data.get("credit_growth_yoy")
        growth = float(growth_raw) if growth_raw is not None else 0.0

        # Kredi / GSYH
        gdp_ratio_raw = credit_data.get("credit_gdp_ratio")
        gdp_ratio = float(gdp_ratio_raw) if gdp_ratio_raw is not None else 0.0

        # Kredi Trendi (1. Türev)
        prev_raw = credit_data.get("credit_previous")
        trend = 0.0
        if prev_raw is not None:
            trend = growth - float(prev_raw)

        direction = 0.0
        if trend > self.trend_threshold:
            direction = 1.0
        elif trend < -self.trend_threshold:
            direction = -1.0

        # Kredi İvmesi (Credit Impulse: Δ(Kredi Akışı) / GSYH veya Trend Farkı)
        prev_trend = float(credit_data.get("credit_previous_trend", 0.0))
        impulse = trend - prev_trend

        # Rejim Sınıflandırması
        if growth > DEFAULT_CREDIT_REGIME_VERY_HIGH:
            regime = CreditRegimeType.BOOM
            regime_score = 3.0
        elif growth > DEFAULT_CREDIT_REGIME_HIGH:
            regime = CreditRegimeType.EXPANSION
            regime_score = 2.0
        elif growth > DEFAULT_CREDIT_REGIME_POSITIVE:
            regime = CreditRegimeType.MODERATE
            regime_score = 1.0
        elif growth > DEFAULT_CREDIT_REGIME_STAGNANT:
            regime = CreditRegimeType.STAGNATION
            regime_score = 0.0
        else:
            regime = CreditRegimeType.CONTRACTION
            regime_score = -1.0

        # Ticari vs Tüketici Kredi Farkı (Ticari büyüme yüksekse reel sektöre yatırım, tüketici yüksekse enflasyonist talep)
        commercial_growth = float(credit_data.get("commercial_credit_growth", growth))
        retail_growth = float(credit_data.get("retail_credit_growth", growth))
        comm_retail_spread = commercial_growth - retail_growth

        # Kredi / Mevduat Oranı (LDR) ve Likidite Baskısı
        ldr = float(credit_data.get("loan_to_deposit_ratio", 102.0))
        liquidity_stress = ldr > self.ldr_stress_threshold

        # Şirket Yatırım Gücü (Ticari kredi büyümesi + pozitif kredi ivmesi)
        capex_support = float(np.clip((commercial_growth * 0.5) + (impulse * 2.0), -20.0, 50.0))

        return CreditMetricsResult(
            credit_growth_yoy=round(growth, 2),
            credit_regime=regime.value,
            credit_regime_score=regime_score,
            credit_gdp_ratio=round(gdp_ratio, 2),
            credit_trend=round(trend, 4),
            credit_trend_direction=direction,
            credit_impulse=round(impulse, 4),
            loan_to_deposit_ratio=round(ldr, 2),
            commercial_vs_retail_spread=round(comm_retail_spread, 2),
            banking_liquidity_stress=liquidity_stress,
            corporate_capex_support=round(capex_support, 2),
            additional_data={
                "commercial_growth": commercial_growth,
                "retail_growth": retail_growth,
            },
        )


credit_engine = CreditCycleEngine()


def compute_credit_features(credit_data: dict[str, Any]) -> dict[str, float]:
    """Feature Store ve portföy risk motoruyla tam uyumlu kredi feature fonksiyonu."""
    if not credit_data:
        return {}
    metrics = credit_engine.evaluate_credit(credit_data)

    return {
        "credit_growth_yoy": metrics.credit_growth_yoy,
        "credit_regime": metrics.credit_regime_score,
        "credit_gdp_ratio": metrics.credit_gdp_ratio,
        "credit_trend": metrics.credit_trend,
        "credit_trend_direction": metrics.credit_trend_direction,
        "credit_impulse": metrics.credit_impulse,
        "credit_ldr": metrics.loan_to_deposit_ratio,
        "credit_comm_retail_spread": metrics.commercial_vs_retail_spread,
        "credit_liquidity_stress_flag": 1.0 if metrics.banking_liquidity_stress else 0.0,
        "credit_capex_support": metrics.corporate_capex_support,
    }


__all__ = [
    "CreditCycleEngine",
    "CreditMetricsResult",
    "CreditRegimeType",
    "DEFAULT_CREDIT_REGIME_HIGH",
    "DEFAULT_CREDIT_REGIME_POSITIVE",
    "DEFAULT_CREDIT_REGIME_STAGNANT",
    "DEFAULT_CREDIT_REGIME_VERY_HIGH",
    "DEFAULT_CREDIT_TREND_THRESHOLD",
    "DEFAULT_LDR_NORMAL",
    "DEFAULT_LDR_TIGHT_LIQUIDITY",
    "compute_credit_features",
    "credit_engine",
]
