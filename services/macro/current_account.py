"""
ALPHA BIST — Institutional External Balance & Current Account Analytics v3.0

Türkiye ekonomisi ve Borsa İstanbul şirketleri için Cari İşlemler Dengesi analitiği:
- Dış Ticaret & Enerji Hariç Çekirdek Denge (Core Balance excluding Gold & Energy)
- Cari Denge / GSYH Dinamik Sürdürülebilirlik Eşiği (Sustainability Metric)
- Finansman Kalitesi (Doğrudan Yabancı Yatırım FDI vs Sıcak Para Portfolio vs Rezervler)
- BIST Sektörel Duyarlılık: İhracatçı (Havacılık, Otomotiv, Cam) vs İthalat Bağımlı Şirketler
- Döviz Kuru Baskısı & Ödemeler Dengesi Kriz Erken Uyarı Skoru (BOP Stress Index)
"""

from dataclasses import asdict, dataclass, field
from enum import StrEnum
from typing import Any

import numpy as np
import structlog

logger = structlog.get_logger(__name__)

# Cari açık rejimi eşik sabitleri (milyar USD yıllıklandırılmış)
DEFAULT_CA_REGIME_SURPLUS: float = 0.0
DEFAULT_CA_REGIME_SMALL_DEFICIT: float = -5.0
DEFAULT_CA_REGIME_MEDIUM_DEFICIT: float = -15.0
DEFAULT_CA_REGIME_CRITICAL_DEFICIT: float = -30.0

# GSYH Oranı Eşikleri (%)
DEFAULT_CA_GDP_WARNING_THRESHOLD: float = -4.5
DEFAULT_CA_GDP_CRITICAL_THRESHOLD: float = -6.0


class CARegimeType(StrEnum):
    """Cari denge rejimi."""
    SURPLUS = "SURPLUS"
    MILD_DEFICIT = "MILD_DEFICIT"
    MODERATE_DEFICIT = "MODERATE_DEFICIT"
    SEVERE_DEFICIT = "SEVERE_DEFICIT"
    CRITICAL_DEFICIT = "CRITICAL_DEFICIT"


@dataclass
class CurrentAccountMetricsResult:
    """Detaylı cari denge ve ödemeler dengesi analiz çıktısı."""
    ca_balance_billion_usd: float
    ca_regime: str
    ca_regime_score: float
    ca_gdp_ratio: float
    ca_core_balance: float
    ca_12m_cumulative: float
    ca_monthly_run_rate: float
    trend_momentum: float
    is_improving: bool
    financing_quality_score: float
    fx_pressure_index: float
    export_sector_tailwind: float
    bop_stress_flag: bool
    raw_details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Sözlük formatına dönüştürür."""
        return asdict(self)


class CurrentAccountEngine:
    """Kurumsal Cari Denge ve Ödemeler Dengesi Analiz Motoru."""

    def __init__(
        self,
        gdp_warning_threshold: float = DEFAULT_CA_GDP_WARNING_THRESHOLD,
        gdp_critical_threshold: float = DEFAULT_CA_GDP_CRITICAL_THRESHOLD,
    ) -> None:
        """Motor ilklendirici."""
        self.gdp_warning_threshold = gdp_warning_threshold
        self.gdp_critical_threshold = gdp_critical_threshold

    def __repr__(self) -> str:
        return f"CurrentAccountEngine(warn={self.gdp_warning_threshold}%, crit={self.gdp_critical_threshold}%)"

    def evaluate_current_account(self, ca_data: dict[str, Any]) -> CurrentAccountMetricsResult:
        """Cari denge göstergelerini hesaplar ve yapılandırılmış sonuç döndürür.

        Args:
            ca_data: Cari denge, GSYH oranı, çekirdek denge, doğrudan yatırımlar ve rezerv değişimleri.

        Returns:
            CurrentAccountMetricsResult: Kurumsal analiz çıktısı.
        """
        ca_bal_raw = ca_data.get("ca_balance")
        ca_balance = float(ca_bal_raw) if ca_bal_raw is not None else 0.0

        # GSYH Oranı
        gdp_ratio_raw = ca_data.get("ca_gdp_ratio")
        gdp_ratio = float(gdp_ratio_raw) if gdp_ratio_raw is not None else 0.0

        # Çekirdek Denge (Altın ve Enerji Hariç)
        core_raw = ca_data.get("ca_core_balance")
        core_balance = float(core_raw) if core_raw is not None else (ca_balance + float(ca_data.get("energy_deficit", 0.0)))

        # 12 Aylık Kümülatif & Trend
        ca_12m_raw = ca_data.get("ca_12m_avg", ca_data.get("ca_12m_cumulative"))
        ca_12m = float(ca_12m_raw) if ca_12m_raw is not None else ca_balance

        ca_prev_raw = ca_data.get("ca_previous")
        trend = 0.0
        if ca_prev_raw is not None:
            trend = ca_balance - float(ca_prev_raw)
        is_improving = trend > 0.0

        # Rejim Sınıflandırması
        if ca_balance > DEFAULT_CA_REGIME_SURPLUS:
            regime = CARegimeType.SURPLUS
            regime_score = 2.0
        elif ca_balance > DEFAULT_CA_REGIME_SMALL_DEFICIT:
            regime = CARegimeType.MILD_DEFICIT
            regime_score = 1.0
        elif ca_balance > DEFAULT_CA_REGIME_MEDIUM_DEFICIT:
            regime = CARegimeType.MODERATE_DEFICIT
            regime_score = 0.0
        elif ca_balance > DEFAULT_CA_REGIME_CRITICAL_DEFICIT:
            regime = CARegimeType.SEVERE_DEFICIT
            regime_score = -1.0
        else:
            regime = CARegimeType.CRITICAL_DEFICIT
            regime_score = -2.0

        # Finansman Kalitesi Skoru (FDI / Toplam Açık)
        fdi = float(ca_data.get("fdi_inflow", 0.0))
        portfolio_flows = float(ca_data.get("portfolio_inflow", 0.0))
        reserves_change = float(ca_data.get("reserves_change", 0.0))

        # Kalite: Uzun vadeli FDI yüksekse pozitif, rezerv erimesi varsa negatif
        financing_score = 0.0
        if abs(ca_balance) > 0.1:
            fdi_ratio = np.clip(fdi / abs(ca_balance), 0.0, 1.5)
            financing_score = float((fdi_ratio * 2.0) - (1.0 if reserves_change < 0 else 0.0))

        # Ödemeler Dengesi Baskı Endeksi (BOP Stress: Açık büyük + GSYH eşiği aşılmış + Rezerv kaybı)
        fx_pressure = 0.0
        if gdp_ratio < self.gdp_warning_threshold:
            fx_pressure += abs(gdp_ratio - self.gdp_warning_threshold) * 1.5
        if reserves_change < 0:
            fx_pressure += abs(reserves_change) * 0.5
        fx_pressure_clamped = float(np.clip(fx_pressure, 0.0, 10.0))

        # İhracatçı Sektör Rüzgarı (Döviz baskısı ve cari açık varken ihracatçı şirketler avantajlıdır)
        export_tailwind = float(np.clip(fx_pressure_clamped * 10.0, 10.0, 100.0))

        bop_stress = gdp_ratio <= self.gdp_critical_threshold or fx_pressure_clamped > 5.0

        return CurrentAccountMetricsResult(
            ca_balance_billion_usd=round(ca_balance, 2),
            ca_regime=regime.value,
            ca_regime_score=regime_score,
            ca_gdp_ratio=round(gdp_ratio, 2),
            ca_core_balance=round(core_balance, 2),
            ca_12m_cumulative=round(ca_12m, 2),
            ca_monthly_run_rate=round(ca_balance / 12.0, 2),
            trend_momentum=round(trend, 4),
            is_improving=is_improving,
            financing_quality_score=round(financing_score, 2),
            fx_pressure_index=round(fx_pressure_clamped, 2),
            export_sector_tailwind=round(export_tailwind, 2),
            bop_stress_flag=bop_stress,
            raw_details={
                "fdi": fdi,
                "portfolio_flows": portfolio_flows,
                "reserves_change": reserves_change,
            },
        )


ca_engine = CurrentAccountEngine()


def compute_ca_features(ca_data: dict[str, Any]) -> dict[str, float]:
    """Sistem genelinde Feature Store ile tam uyumlu çalışan cari denge feature fonksiyonu."""
    if not ca_data:
        return {}
    metrics = ca_engine.evaluate_current_account(ca_data)

    return {
        "ca_balance": metrics.ca_balance_billion_usd,
        "ca_regime": metrics.ca_regime_score,
        "ca_gdp_ratio": metrics.ca_gdp_ratio,
        "ca_core_balance": metrics.ca_core_balance,
        "ca_trend": metrics.trend_momentum,
        "ca_improving": 1.0 if metrics.is_improving else 0.0,
        "ca_12m_avg": metrics.ca_12m_cumulative,
        "ca_financing_quality": metrics.financing_quality_score,
        "ca_fx_pressure_index": metrics.fx_pressure_index,
        "ca_export_tailwind": metrics.export_sector_tailwind,
        "ca_bop_stress_flag": 1.0 if metrics.bop_stress_flag else 0.0,
    }


__all__ = [
    "CARegimeType",
    "CurrentAccountEngine",
    "CurrentAccountMetricsResult",
    "DEFAULT_CA_GDP_CRITICAL_THRESHOLD",
    "DEFAULT_CA_GDP_WARNING_THRESHOLD",
    "DEFAULT_CA_REGIME_CRITICAL_DEFICIT",
    "DEFAULT_CA_REGIME_MEDIUM_DEFICIT",
    "DEFAULT_CA_REGIME_SMALL_DEFICIT",
    "DEFAULT_CA_REGIME_SURPLUS",
    "ca_engine",
    "compute_ca_features",
]
