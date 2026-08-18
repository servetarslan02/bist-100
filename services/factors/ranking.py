"""ALPHA BIST — Multi-Factor Ranking (Nihai).

Risk-adjusted, sector-neutral, regime-based ranking.
"""
from typing import Dict, Any, List, Optional
import numpy as np
import structlog

logger = structlog.get_logger()

# Varsayılan faktör ağırlıkları
DEFAULT_WEIGHTS = {
    "value": 0.15, "momentum": 0.20, "quality": 0.20, "size": 0.10,
    "low_vol": 0.10, "dividend": 0.10, "leverage": 0.10, "bist_specific": 0.05,
}

# Rejime göre ağırlık ayarlamaları
REGIME_WEIGHTS = {
    "BULL": {"momentum": 0.30, "quality": 0.15, "value": 0.10, "low_vol": 0.05},
    "BEAR": {"quality": 0.30, "low_vol": 0.20, "dividend": 0.15, "momentum": 0.05},
    "SIDEWAYS": {"value": 0.25, "dividend": 0.20, "quality": 0.20},
    "HIGH_VOL": {"low_vol": 0.25, "quality": 0.25, "dividend": 0.15},
}


def rank_stocks(
    universe: List[Dict[str, Any]],
    factor_weights: Optional[Dict[str, float]] = None,
    regime: str = "NORMAL",
    sector_neutral: bool = False,
    risk_adjust: bool = True,
) -> List[Dict[str, Any]]:
    """Çok faktörlü hisse sıralaması — risk-adjusted.

    Args:
        universe: Hisse listesi [{ticker, factors: {factor_name: score}, risk_score, sector}]
        factor_weights: Faktör ağırlıkları
        regime: Piyasa rejimi (BULL, BEAR, SIDEWAYS, HIGH_VOL, NORMAL)
        sector_neutral: Sektör-nötr sıralama
        risk_adjust: Risk ayarlaması uygula

    Returns:
        Sıralanmış hisse listesi
    """
    if not universe:
        return []

    weights = dict(factor_weights or DEFAULT_WEIGHTS)

    # Rejime göre ağırlık ayarla
    if regime in REGIME_WEIGHTS:
        weights.update(REGIME_WEIGHTS[regime])

    # Ağırlıkları normalize et
    total_w = sum(weights.values())
    if total_w > 0:
        weights = {k: v / total_w for k, v in weights.items()}

    # Sektör-nötr için sektör ortalamalarını hesapla
    sector_means = {}
    if sector_neutral:
        sector_factors = {}
        for stock in universe:
            sector = stock.get("sector", "OTHER")
            if sector not in sector_factors:
                sector_factors[sector] = []
            sector_factors[sector].append(stock.get("factors", {}))
        for sector, factors_list in sector_factors.items():
            all_keys = set()
            for f in factors_list:
                all_keys.update(f.keys())
            sector_means[sector] = {
                k: np.mean([f.get(k, 0) for f in factors_list]) for k in all_keys
            }

    # Her hisse için skor hesapla
    for stock in universe:
        factors = stock.get("factors", {})
        sector = stock.get("sector", "OTHER")

        # Sektör-nötr düzeltme
        if sector_neutral and sector in sector_means:
            adjusted_factors = {
                k: factors.get(k, 0) - sector_means[sector].get(k, 0)
                for k in factors
            }
        else:
            adjusted_factors = factors

        # Ağırlıklı skor
        total_score = 0
        factor_contributions = {}
        for factor, weight in weights.items():
            factor_score = adjusted_factors.get(factor, 0)
            contribution = factor_score * weight
            total_score += contribution
            factor_contributions[factor] = {
                "score": round(factor_score, 4),
                "weight": round(weight, 4),
                "contribution": round(contribution, 4),
            }

        # Risk adjustment
        risk_score = stock.get("risk_score", 50)
        if risk_adjust and risk_score > 0:
            risk_factor = risk_score / 100
            risk_adjusted_score = total_score * risk_factor
        else:
            risk_adjusted_score = total_score

        stock["factor_score"] = round(total_score, 4)
        stock["risk_adjusted_score"] = round(risk_adjusted_score, 4)
        stock["factor_contributions"] = factor_contributions
        stock["regime"] = regime

    # Risk-adjusted skora göre sırala
    universe.sort(key=lambda s: s.get("risk_adjusted_score", 0), reverse=True)

    # Rank ekle
    for i, stock in enumerate(universe):
        stock["rank"] = i + 1
        stock["top_pct"] = round((i + 1) / len(universe) * 100, 1)

    return universe


def get_top_n(
    ranked: List[Dict[str, Any]], n: int = 10
) -> List[Dict[str, Any]]:
    """İlk N hisseyi döndür."""
    return ranked[:n]


def get_bottom_n(
    ranked: List[Dict[str, Any]], n: int = 10
) -> List[Dict[str, Any]]:
    """Son N hisseyi döndür."""
    return ranked[-n:]
