"""
ALPHA BIST — Macro Surprise Model v1.0

Beklenti vs gerçek sürpriz hesaplama:
- TCMB faiz sürprizi
- Enflasyon sürprizi
- GSYH sürprizi
- Beklenti kaynakları: anket, swap pricing, consensus, trend extrapolation
- Surprise magnitude ve direction
- Sector-specific surprise etkisi
- Decay modeli (half-life)

KURAL: Beklenti verisi yoksa surprise = 0 kabul et (belirsizlik = etki yok).
"""

import numpy as np
from typing import Dict, List, Any
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
import structlog

from services.macro.config.macro_config import macro_config

logger = structlog.get_logger()


@dataclass
class SurpriseResult:
    """Surprise sonucu."""
    indicator: str
    actual: float
    expected: float
    surprise: float
    surprise_pct: float
    magnitude: str  # NONE, SMALL, MEDIUM, LARGE
    direction: str  # IN_LINE, HIGHER, LOWER, HAWKISH, DOVISH
    confidence: float  # Beklenti güvenilirliği (0-1)
    source: str  # Beklenti kaynağı
    timestamp: str


@dataclass
class SurpriseImpact:
    """Surprise etki sonucu."""
    indicator: str
    surprise_pct: float
    sector_impacts: Dict[str, float]  # sector → impact
    company_impacts: Dict[str, float]  # ticker → impact
    decay_days: int
    remaining_impact: float  # Decay sonrası kalan etki


class MacroSurpriseModel:
    """Makro sürpriz hesaplama motoru."""

    # Beklenti kaynakları ve güvenilirlikleri
    EXPECTATION_SOURCES = {
        "TCMB_RATE": {
            "primary": "tcmb_survey",       # TCMB Piyasa Katılımcıları Anketi
            "fallback": "swap_pricing",      # TCMB faiz swapları
            "confidence": {"tcmb_survey": 0.9, "swap_pricing": 0.7, "trend": 0.4},
        },
        "CPI": {
            "primary": "consensus_forecast",  # Reuters/Bloomberg consensus
            "fallback": "trend_extrapolation",
            "confidence": {"consensus_forecast": 0.8, "trend_extrapolation": 0.3},
        },
        "GDP": {
            "primary": "consensus_forecast",
            "fallback": "trend_extrapolation",
            "confidence": {"consensus_forecast": 0.7, "trend_extrapolation": 0.3},
        },
        "POLICY_RATE": {
            "primary": "tcmb_survey",
            "fallback": "swap_pricing",
            "confidence": {"tcmb_survey": 0.9, "swap_pricing": 0.7, "trend": 0.4},
        },
    }

    # Sektör-Macro Surprise hassasiyet matrisi
    SECTOR_SURPRISE_SENSITIVITY = {
        "BANK": {"TCMB_RATE": 0.9, "CPI": -0.5, "GDP": 0.4},
        "AVIATION": {"TCMB_RATE": -0.6, "CPI": -0.7, "GDP": 0.5},
        "ENERGY": {"TCMB_RATE": -0.3, "CPI": 0.3, "GDP": 0.6},
        "TECH": {"TCMB_RATE": -0.7, "CPI": -0.3, "GDP": 0.7},
        "RETAIL": {"TCMB_RATE": -0.5, "CPI": -0.8, "GDP": 0.5},
        "METAL": {"TCMB_RATE": -0.3, "CPI": 0.2, "GDP": 0.6},
        "CONSTR": {"TCMB_RATE": -0.8, "CPI": -0.6, "GDP": 0.4},
        "FOOD": {"TCMB_RATE": -0.4, "CPI": -0.5, "GDP": 0.3},
        "HOLDING": {"TCMB_RATE": -0.5, "CPI": -0.4, "GDP": 0.5},
        "OTHER": {"TCMB_RATE": -0.4, "CPI": -0.4, "GDP": 0.4},
    }

    def __init__(self):
        self._expectations: Dict[str, Dict] = {}  # indicator → {value, source, timestamp}
        self._surprise_history: List[SurpriseResult] = []
        self._active_surprises: Dict[str, SurpriseResult] = {}

    def set_expectation(
        self,
        indicator: str,
        expected: float,
        source: str = "manual",
        confidence: float = 0.5,
    ):
        """Beklenti değerini kaydet."""
        self._expectations[indicator] = {
            "value": expected,
            "source": source,
            "confidence": confidence,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        logger.info("Expectation set", indicator=indicator,
                   expected=expected, source=source)

    def calculate_surprise(
        self,
        indicator: str,
        actual: float,
        expected: float = None,
    ) -> SurpriseResult:
        """Sürpriz hesapla.

        Args:
            indicator: Gösterge adı (TCMB_RATE, CPI, GDP)
            actual: Gerçek değer
            expected: Beklenti değeri (None ise kayıtlı beklenti kullan)

        Returns:
            SurpriseResult
        """
        cfg = macro_config.surprise

        # Beklenti bul
        if expected is None:
            exp_data = self._expectations.get(indicator)
            if exp_data:
                expected = exp_data["value"]
                source = exp_data["source"]
                confidence = exp_data["confidence"]
            else:
                # Beklenti yok → surprise hesaplanamaz
                return SurpriseResult(
                    indicator=indicator,
                    actual=actual,
                    expected=actual,  # Beklenti = gerçek → surprise 0
                    surprise=0.0,
                    surprise_pct=0.0,
                    magnitude="NONE",
                    direction="IN_LINE",
                    confidence=0.0,
                    source="no_expectation",
                    timestamp=datetime.now(timezone.utc).isoformat(),
                )
        else:
            source = "manual"
            confidence = 0.5

        # Surprise hesapla
        surprise = actual - expected
        surprise_pct = surprise / abs(expected) if expected != 0 else 0.0

        # Magnitude
        abs_pct = abs(surprise_pct)
        if abs_pct > cfg.large_threshold:
            magnitude = "LARGE"
        elif abs_pct > cfg.medium_threshold:
            magnitude = "MEDIUM"
        elif abs_pct > cfg.small_threshold:
            magnitude = "SMALL"
        else:
            magnitude = "NONE"

        # Direction
        if indicator in ("TCMB_RATE", "POLICY_RATE"):
            direction = "HAWKISH" if surprise > 0 else ("DOVISH" if surprise < 0 else "IN_LINE")
        else:
            direction = "HIGHER" if surprise > 0 else ("LOWER" if surprise < 0 else "IN_LINE")

        result = SurpriseResult(
            indicator=indicator,
            actual=actual,
            expected=expected,
            surprise=round(surprise, 4),
            surprise_pct=round(surprise_pct, 4),
            magnitude=magnitude,
            direction=direction,
            confidence=round(confidence, 4),
            source=source,
            timestamp=datetime.now(timezone.utc).isoformat(),
        )

        self._surprise_history.append(result)
        if len(self._surprise_history) > 1000:
            self._surprise_history = self._surprise_history[-1000:]
        self._active_surprises[indicator] = result

        if magnitude != "NONE":
            logger.warning("Macro surprise detected",
                         indicator=indicator, magnitude=magnitude,
                         direction=direction, surprise_pct=round(surprise_pct, 4))

        return result

    def compute_surprise_features(
        self,
        actuals: Dict[str, float],
    ) -> Dict[str, float]:
        """Surprise feature'ları üret.

        Args:
            actuals: {indicator: actual_value}

        Returns:
            Feature dictionary
        """
        features = {}

        for indicator, actual in actuals.items():
            surprise = self.calculate_surprise(indicator, actual)

            prefix = indicator.lower()
            features[f"{prefix}_surprise"] = surprise.surprise
            features[f"{prefix}_surprise_pct"] = surprise.surprise_pct
            features[f"{prefix}_surprise_magnitude"] = {
                "NONE": 0.0, "SMALL": 1.0, "MEDIUM": 2.0, "LARGE": 3.0
            }.get(surprise.magnitude, 0.0)

            # Direction encoding
            if indicator in ("TCMB_RATE", "POLICY_RATE"):
                features[f"{prefix}_surprise_direction"] = {
                    "IN_LINE": 0.0, "HAWKISH": 1.0, "DOVISH": -1.0
                }.get(surprise.direction, 0.0)
            else:
                features[f"{prefix}_surprise_direction"] = {
                    "IN_LINE": 0.0, "HIGHER": 1.0, "LOWER": -1.0
                }.get(surprise.direction, 0.0)

        # Birikimli surprise (son 3 ay)
        cumulative = self._compute_cumulative_surprise()
        features.update(cumulative)

        return features

    def compute_sector_surprise_impact(
        self,
        sector: str,
        surprises: Dict[str, SurpriseResult],
    ) -> Dict[str, float]:
        """Sektör bazlı surprise etkisi."""
        sensitivity = self.SECTOR_SURPRISE_SENSITIVITY.get(
            sector, self.SECTOR_SURPRISE_SENSITIVITY["OTHER"]
        )

        impacts = {}
        total_impact = 0.0

        for indicator, surprise in surprises.items():
            sens = sensitivity.get(indicator, 0)
            impact = surprise.surprise_pct * sens
            impacts[f"{indicator.lower()}_surprise_impact"] = round(impact, 4)
            total_impact += impact

        impacts["total_surprise_impact"] = round(total_impact, 4)
        return impacts

    def get_decay_impact(
        self,
        indicator: str,
        days_elapsed: int,
    ) -> float:
        """Surprise etkisinin decay sonrası kalan oranı."""
        cfg = macro_config.decay
        half_life = cfg.half_life_by_shock_type.get(
            indicator.lower(), cfg.default_half_life_days
        )
        return round(0.5 ** (days_elapsed / half_life), 4)

    def get_surprise_report(self) -> Dict[str, Any]:
        """Surprise raporu."""
        return {
            "active_surprises": {
                k: {
                    "surprise_pct": v.surprise_pct,
                    "magnitude": v.magnitude,
                    "direction": v.direction,
                    "source": v.source,
                }
                for k, v in self._active_surprises.items()
            },
            "total_surprises": len(self._surprise_history),
            "expectations": {
                k: {"value": v["value"], "source": v["source"]}
                for k, v in self._expectations.items()
            },
        }

    def _compute_cumulative_surprise(self) -> Dict[str, float]:
        """Son 3 ayın birikimli surprise'ını hesapla."""
        features = {}
        cutoff = (datetime.now(timezone.utc) - timedelta(days=90)).isoformat()

        # Indicator bazlı grupla
        indicator_surprises: Dict[str, List[float]] = {}
        for s in self._surprise_history:
            if s.timestamp > cutoff and s.magnitude != "NONE":
                if s.indicator not in indicator_surprises:
                    indicator_surprises[s.indicator] = []
                indicator_surprises[s.indicator].append(s.surprise_pct)

        for indicator, surprises in indicator_surprises.items():
            prefix = indicator.lower()
            features[f"{prefix}_cumulative_surprise_90d"] = round(sum(surprises), 4)
            features[f"{prefix}_surprise_count_90d"] = float(len(surprises))
            features[f"{prefix}_avg_surprise_90d"] = round(np.mean(surprises), 4)

        return features


# Singleton
macro_surprise_model = MacroSurpriseModel()
