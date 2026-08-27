"""
ALPHA BIST — Macro Impact Analyzer v1.0

Makro şok etki analizi + decay modeli:
- Şok etkisi = magnitude × sensitivity
- Decay modeli: half-life ile etki zamanla azalır
- Birikimli etki: birden fazla şokun toplam etkisi
- Sector ve company bazlı etki

KURAL: Etki zamanla azalır — half-life modeli.
"""

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import structlog

from services.macro.config.macro_config import macro_config

logger = structlog.get_logger()


@dataclass
class ShockEvent:
    """Şok olayı kaydı."""

    shock_type: str
    magnitude: float
    timestamp: str
    indicator: str
    half_life_days: int


@dataclass
class ImpactResult:
    """Etki sonucu."""

    ticker: str
    sector: str
    shock_type: str
    raw_impact: float
    decay_factor: float
    remaining_impact: float
    days_elapsed: int
    cumulative_impact: float


class MacroImpactAnalyzer:
    """Makro şok etki analizi motoru."""

    # Sektör hassasiyet matrisi (MacroSensitivityEngine ile uyumlu)
    SECTOR_SENSITIVITY = {
        "BANK": {"usdtry": -0.3, "interest_rate": 0.9, "oil": -0.1, "inflation": -0.7, "global": 0.5, "vix": -0.4},
        "AVIATION": {"usdtry": -0.8, "interest_rate": -0.5, "oil": -0.9, "inflation": -0.4, "global": 0.6, "vix": -0.5},
        "ENERGY": {"usdtry": 0.5, "interest_rate": -0.4, "oil": 0.9, "inflation": 0.3, "global": 0.7, "vix": -0.3},
        "TECH": {"usdtry": 0.4, "interest_rate": -0.6, "oil": -0.1, "inflation": -0.3, "global": 0.8, "vix": -0.6},
        "RETAIL": {"usdtry": -0.6, "interest_rate": -0.5, "oil": -0.3, "inflation": -0.8, "global": 0.3, "vix": -0.3},
        "METAL": {"usdtry": 0.4, "interest_rate": -0.3, "oil": -0.5, "inflation": 0.3, "global": 0.8, "vix": -0.4},
        "CONSTR": {"usdtry": -0.6, "interest_rate": -0.8, "oil": -0.4, "inflation": -0.7, "global": 0.3, "vix": -0.4},
        "FOOD": {"usdtry": -0.5, "interest_rate": -0.4, "oil": -0.3, "inflation": -0.6, "global": 0.3, "vix": -0.3},
        "HOLDING": {"usdtry": -0.4, "interest_rate": -0.5, "oil": -0.2, "inflation": -0.4, "global": 0.5, "vix": -0.4},
        "OTHER": {"usdtry": -0.4, "interest_rate": -0.4, "oil": -0.2, "inflation": -0.4, "global": 0.4, "vix": -0.3},
    }

    def __init__(self):
        self._shock_history: list[ShockEvent] = []

    def record_shock(
        self,
        shock_type: str,
        magnitude: float,
        indicator: str,
    ):
        """Şok olayı kaydet."""
        cfg = macro_config.decay
        half_life = cfg.half_life_by_shock_type.get(shock_type, cfg.default_half_life_days)

        event = ShockEvent(
            shock_type=shock_type,
            magnitude=magnitude,
            timestamp=datetime.now(UTC).isoformat(),
            indicator=indicator,
            half_life_days=half_life,
        )
        self._shock_history.append(event)
        if len(self._shock_history) > 1000:
            self._shock_history = self._shock_history[-1000:]

        logger.warning(
            "Macro shock recorded", shock_type=shock_type, magnitude=magnitude, indicator=indicator, half_life=half_life
        )

    def compute_impact(
        self,
        ticker: str,
        sector: str,
        shock_type: str,
        magnitude: float,
        days_elapsed: int = 0,
    ) -> ImpactResult:
        """Tek şok etkisini hesapla (decay dahil)."""
        cfg = macro_config.decay

        # Sensitivity
        sensitivity = self.SECTOR_SENSITIVITY.get(sector, self.SECTOR_SENSITIVITY["OTHER"])
        sens_value = sensitivity.get(shock_type, 0)

        # Raw impact
        raw_impact = magnitude * sens_value

        # Decay
        half_life = cfg.half_life_by_shock_type.get(shock_type, cfg.default_half_life_days)
        decay_factor = 0.5 ** (days_elapsed / half_life)
        remaining_impact = raw_impact * decay_factor

        return ImpactResult(
            ticker=ticker,
            sector=sector,
            shock_type=shock_type,
            raw_impact=round(raw_impact, 4),
            decay_factor=round(decay_factor, 4),
            remaining_impact=round(remaining_impact, 4),
            days_elapsed=days_elapsed,
            cumulative_impact=round(remaining_impact, 4),
        )

    def compute_cumulative_impact(
        self,
        ticker: str,
        sector: str,
    ) -> dict[str, float]:
        """Tüm aktif şokların birikimli etkisini hesapla."""
        now = datetime.now(UTC)
        total_impact = 0.0
        shock_impacts = {}

        for shock in self._shock_history:
            shock_time = datetime.fromisoformat(shock.timestamp)
            days_elapsed = (now - shock_time).days

            # Decay sonrası etki artık ihmal edilebilir mi?
            if days_elapsed > shock.half_life_days * 5:
                continue

            impact = self.compute_impact(
                ticker=ticker,
                sector=sector,
                shock_type=shock.shock_type,
                magnitude=shock.magnitude,
                days_elapsed=days_elapsed,
            )

            shock_impacts[shock.shock_type] = {
                "raw_impact": impact.raw_impact,
                "decay_factor": impact.decay_factor,
                "remaining_impact": impact.remaining_impact,
                "days_elapsed": days_elapsed,
            }
            total_impact += impact.remaining_impact

        return {
            "ticker": ticker,
            "sector": sector,
            "cumulative_impact": round(total_impact, 4),
            "active_shocks": len(shock_impacts),
            "shock_details": shock_impacts,
        }

    def compute_decay_curve(
        self,
        shock_type: str,
        magnitude: float,
        max_days: int = 30,
    ) -> list[dict[str, float]]:
        """Decay eğrisi hesapla (görselleştirme için)."""
        cfg = macro_config.decay
        half_life = cfg.half_life_by_shock_type.get(shock_type, cfg.default_half_life_days)

        curve = []
        for day in range(max_days + 1):
            decay = 0.5 ** (day / half_life)
            remaining = magnitude * decay
            curve.append(
                {
                    "day": day,
                    "decay_factor": round(decay, 4),
                    "remaining_impact": round(remaining, 4),
                }
            )

        return curve

    def get_shock_report(self) -> dict[str, Any]:
        """Şok raporu."""
        return {
            "total_shocks": len(self._shock_history),
            "recent_shocks": [
                {
                    "type": s.shock_type,
                    "magnitude": s.magnitude,
                    "indicator": s.indicator,
                    "timestamp": s.timestamp,
                    "half_life": s.half_life_days,
                }
                for s in self._shock_history[-10:]
            ],
        }


# Singleton
macro_impact_analyzer = MacroImpactAnalyzer()
