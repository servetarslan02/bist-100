"""
ALPHA BIST — Macro Factor Decomposition v1.0

Makro faktör ayrıştırması:
- Hangi faktör ne kadar katkı yaptı?
- USDTRY katkısı, faiz katkısı, enflasyon katkısı ayrı
- Residual (açıklanamayan kısım)
- Factor-based attribution

KURAL: Toplam getiri = Σ(faktör katkısı) + residual.
"""

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import structlog

logger = structlog.get_logger()


@dataclass
class FactorContribution:
    """Faktör katkısı."""

    factor: str
    contribution: float
    contribution_pct: float
    direction: str  # POSITIVE, NEGATIVE, NEUTRAL
    significance: str  # HIGH, MEDIUM, LOW


@dataclass
class DecompositionResult:
    """Ayrıştırma sonucu."""

    ticker: str
    sector: str
    total_return: float
    factor_contributions: list[FactorContribution]
    residual: float
    residual_pct: float
    explained_pct: float
    top_factor: str
    timestamp: str


class MacroFactorDecomposition:
    """Makro faktör ayrıştırma motoru."""

    # Faktör isimleri
    FACTORS = [
        "usdtry",
        "interest_rate",
        "inflation",
        "oil",
        "gold",
        "global_market",
        "vix",
    ]

    # Sektör hassasiyet matrisi
    SECTOR_SENSITIVITY = {
        "BANK": {
            "usdtry": -0.3,
            "interest_rate": 0.9,
            "inflation": -0.7,
            "oil": -0.1,
            "gold": 0.1,
            "global_market": 0.5,
            "vix": -0.4,
        },
        "AVIATION": {
            "usdtry": -0.8,
            "interest_rate": -0.5,
            "inflation": -0.4,
            "oil": -0.9,
            "gold": 0.0,
            "global_market": 0.6,
            "vix": -0.5,
        },
        "ENERGY": {
            "usdtry": 0.5,
            "interest_rate": -0.4,
            "inflation": 0.3,
            "oil": 0.9,
            "gold": 0.1,
            "global_market": 0.7,
            "vix": -0.3,
        },
        "TECH": {
            "usdtry": 0.4,
            "interest_rate": -0.6,
            "inflation": -0.3,
            "oil": -0.1,
            "gold": 0.0,
            "global_market": 0.8,
            "vix": -0.6,
        },
        "RETAIL": {
            "usdtry": -0.6,
            "interest_rate": -0.5,
            "inflation": -0.8,
            "oil": -0.3,
            "gold": 0.0,
            "global_market": 0.3,
            "vix": -0.3,
        },
        "METAL": {
            "usdtry": 0.4,
            "interest_rate": -0.3,
            "inflation": 0.3,
            "oil": -0.5,
            "gold": 0.7,
            "global_market": 0.8,
            "vix": -0.4,
        },
        "CONSTR": {
            "usdtry": -0.6,
            "interest_rate": -0.8,
            "inflation": -0.7,
            "oil": -0.4,
            "gold": 0.1,
            "global_market": 0.3,
            "vix": -0.4,
        },
        "FOOD": {
            "usdtry": -0.5,
            "interest_rate": -0.4,
            "inflation": -0.6,
            "oil": -0.3,
            "gold": 0.0,
            "global_market": 0.3,
            "vix": -0.3,
        },
        "HOLDING": {
            "usdtry": -0.4,
            "interest_rate": -0.5,
            "inflation": -0.4,
            "oil": -0.2,
            "gold": 0.1,
            "global_market": 0.5,
            "vix": -0.4,
        },
        "OTHER": {
            "usdtry": -0.4,
            "interest_rate": -0.4,
            "inflation": -0.4,
            "oil": -0.2,
            "gold": 0.1,
            "global_market": 0.4,
            "vix": -0.3,
        },
    }

    def decompose(
        self,
        ticker: str,
        sector: str,
        total_return: float,
        macro_changes: dict[str, float],
        company_sensitivity: dict[str, float] | None = None,
    ) -> DecompositionResult:
        """Getiriyi makro faktörlere ayrıştır.

        Args:
            ticker: Hisse kodu
            sector: Sektör
            total_return: Toplam getiri (%)
            macro_changes: {factor: change} — faktör değişimleri
            company_sensitivity: Şirket-specific hassasiyet (override)

        Returns:
            DecompositionResult
        """
        # Hassasiyet al
        sensitivity = company_sensitivity or self.SECTOR_SENSITIVITY.get(sector, self.SECTOR_SENSITIVITY["OTHER"])

        # Her faktörün katkısını hesapla
        contributions = []
        total_explained = 0.0

        for factor in self.FACTORS:
            change = macro_changes.get(factor, 0)
            sens = sensitivity.get(factor, 0)

            # Katkı = değişim × hassasiyet
            contribution = change * sens

            # Yön
            if contribution > 0.001:
                direction = "POSITIVE"
            elif contribution < -0.001:
                direction = "NEGATIVE"
            else:
                direction = "NEUTRAL"

            # Önem
            abs_contrib = abs(contribution)
            if abs_contrib > 0.02:
                significance = "HIGH"
            elif abs_contrib > 0.005:
                significance = "MEDIUM"
            else:
                significance = "LOW"

            contributions.append(
                FactorContribution(
                    factor=factor,
                    contribution=round(contribution, 4),
                    contribution_pct=round(contribution * 100, 2),
                    direction=direction,
                    significance=significance,
                )
            )

            total_explained += contribution

        # Residual
        residual = total_return - total_explained
        residual_pct = residual / abs(total_return) if total_return != 0 else 0

        # En büyük faktör
        if contributions:
            top = max(contributions, key=lambda c: abs(c.contribution))
            top_factor = top.factor
        else:
            top_factor = "unknown"

        return DecompositionResult(
            ticker=ticker,
            sector=sector,
            total_return=round(total_return, 4),
            factor_contributions=contributions,
            residual=round(residual, 4),
            residual_pct=round(residual_pct * 100, 2),
            explained_pct=round((1 - abs(residual_pct)) * 100, 2),
            top_factor=top_factor,
            timestamp=datetime.now(UTC).isoformat(),
        )

    def compute_factor_features(
        self,
        ticker: str,
        sector: str,
        total_return: float,
        macro_changes: dict[str, float],
    ) -> dict[str, float]:
        """Faktör feature'ları üret."""
        result = self.decompose(ticker, sector, total_return, macro_changes)

        features = {}

        # Her faktörün katkısı
        for contrib in result.factor_contributions:
            features[f"factor_{contrib.factor}_contribution"] = contrib.contribution

        # Residual
        features["factor_residual"] = result.residual
        features["factor_residual_pct"] = result.residual_pct

        # Açıklanan oran
        features["factor_explained_pct"] = result.explained_pct

        # En büyük faktör (one-hot)
        for factor in self.FACTORS:
            features[f"factor_top_{factor}"] = 1.0 if result.top_factor == factor else 0.0

        # Pozitif/negatif faktör sayısı
        pos_count = sum(1 for c in result.factor_contributions if c.direction == "POSITIVE")
        neg_count = sum(1 for c in result.factor_contributions if c.direction == "NEGATIVE")
        features["factor_positive_count"] = float(pos_count)
        features["factor_negative_count"] = float(neg_count)
        features["factor_net_direction"] = 1.0 if pos_count > neg_count else (-1.0 if neg_count > pos_count else 0.0)

        return features

    def get_report(
        self,
        ticker: str,
        sector: str,
        total_return: float,
        macro_changes: dict[str, float],
    ) -> dict[str, Any]:
        """Faktör ayrıştırma raporu."""
        result = self.decompose(ticker, sector, total_return, macro_changes)

        return {
            "ticker": ticker,
            "sector": sector,
            "total_return": result.total_return,
            "explained_pct": result.explained_pct,
            "residual_pct": result.residual_pct,
            "top_factor": result.top_factor,
            "contributions": [
                {
                    "factor": c.factor,
                    "contribution_pct": c.contribution_pct,
                    "direction": c.direction,
                    "significance": c.significance,
                }
                for c in sorted(result.factor_contributions, key=lambda c: abs(c.contribution), reverse=True)
            ],
        }


# Singleton
macro_factor_decomposition = MacroFactorDecomposition()
