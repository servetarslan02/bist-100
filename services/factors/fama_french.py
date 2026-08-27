"""ALPHA BIST — Fama-French Factor Scores (Nihai).

Value, Momentum, Quality, Size, Low Vol, Dividend, Leverage, BIST-specific.
Cross-sectional z-score normalization.
"""
from typing import Any

import numpy as np
import structlog

logger = structlog.get_logger()

# Faktör tanımları
FACTOR_DEFINITIONS = {
    "value": {
        "metrics": ["pb_ratio", "pe_ratio", "ev_ebitda", "fcf_yield"],
        "direction": {"pb_ratio": -1, "pe_ratio": -1, "ev_ebitda": -1, "fcf_yield": 1},
        "weight": 0.15,
    },
    "momentum": {
        "metrics": ["mom_1m", "mom_3m", "mom_6m", "mom_12m"],
        "direction": {"mom_1m": 1, "mom_3m": 1, "mom_6m": 1, "mom_12m": 1},
        "weight": 0.20,
    },
    "quality": {
        "metrics": ["roe", "roic", "gross_margin", "operating_margin"],
        "direction": {"roe": 1, "roic": 1, "gross_margin": 1, "operating_margin": 1},
        "weight": 0.20,
    },
    "size": {
        "metrics": ["market_cap"],
        "direction": {"market_cap": -1},  # Küçük = yüksek skor
        "weight": 0.10,
    },
    "low_vol": {
        "metrics": ["volatility", "beta"],
        "direction": {"volatility": -1, "beta": -1},
        "weight": 0.10,
    },
    "dividend": {
        "metrics": ["dividend_yield", "payout_ratio"],
        "direction": {"dividend_yield": 1, "payout_ratio": -1},
        "weight": 0.10,
    },
    "leverage": {
        "metrics": ["debt_equity", "net_debt_ebitda"],
        "direction": {"debt_equity": -1, "net_debt_ebitda": -1},
        "weight": 0.10,
    },
    "bist_specific": {
        "metrics": ["fx_sensitivity", "inflation_beta", "foreign_ownership"],
        "direction": {"fx_sensitivity": -1, "inflation_beta": -1, "foreign_ownership": 1},
        "weight": 0.05,
    },
}


def calculate_factor_scores(
    stock: dict[str, Any],
    universe_stats: dict[str, Any],
) -> dict[str, float]:
    """Fama-French faktör skorları — cross-sectional percentile.

    Args:
        stock: Hisse verileri
        universe_stats: Evren istatistikleri (median, std, percentiles)

    Returns:
        Dict with factor scores (0-1 arası)
    """
    scores = {}

    for factor_name, factor_def in FACTOR_DEFINITIONS.items():
        metric_scores = []

        for metric in factor_def["metrics"]:
            value = stock.get(metric, 0)
            direction = factor_def["direction"].get(metric, 1)

            # Universe istatistikleri
            median = universe_stats.get(f"{metric}_median", universe_stats.get(f"{metric}_mean", 0))
            std = universe_stats.get(f"{metric}_std", 1)
            universe_stats.get(f"{metric}_p25", median - std)
            universe_stats.get(f"{metric}_p75", median + std)

            # Percentile skor
            if std > 0:
                z = (value - median) / std
                # Percentile'a çevir (0-1)
                try:
                    from scipy.stats import norm
                    percentile = float(norm.cdf(z))
                except (ImportError, Exception):
                    import math
                    percentile = 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))
            else:
                percentile = 0.5

            # Yön düzeltmesi
            if direction < 0:
                percentile = 1 - percentile

            metric_scores.append(percentile)

        # Faktör skoru = metriklerin ortalaması
        scores[factor_name] = round(float(np.mean(metric_scores)), 4) if metric_scores else 0.5

    return scores


def calculate_factor_scores_batch(
    universe: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Tüm evren için toplu faktör skoru hesaplama.

    Args:
        universe: [{ticker, ...factor metrics...}]

    Returns:
        Her hisse için faktör skorları eklenmiş liste
    """
    if not universe:
        return []

    # Tüm metrikler için evren istatistikleri hesapla
    all_metrics = set()
    for factor_def in FACTOR_DEFINITIONS.values():
        all_metrics.update(factor_def["metrics"])

    universe_stats = {}
    for metric in all_metrics:
        values = [s.get(metric, 0) for s in universe if metric in s]
        if values:
            arr = np.array(values, dtype=float)
            universe_stats[f"{metric}_mean"] = float(np.mean(arr))
            universe_stats[f"{metric}_median"] = float(np.median(arr))
            universe_stats[f"{metric}_std"] = float(np.std(arr)) if len(arr) > 1 else 1.0
            universe_stats[f"{metric}_p25"] = float(np.percentile(arr, 25))
            universe_stats[f"{metric}_p75"] = float(np.percentile(arr, 75))

    # Her hisse için skor hesapla
    for stock in universe:
        stock["factor_scores"] = calculate_factor_scores(stock, universe_stats)

    return universe


def get_factor_weights(regime: str = "NORMAL") -> dict[str, float]:
    """Rejime göre faktör ağırlıkları döndür."""
    base = {k: v["weight"] for k, v in FACTOR_DEFINITIONS.items()}

    regime_adjustments = {
        "BULL": {"momentum": 0.30, "quality": 0.15, "value": 0.10, "low_vol": 0.05},
        "BEAR": {"quality": 0.30, "low_vol": 0.20, "dividend": 0.15, "momentum": 0.05},
        "SIDEWAYS": {"value": 0.25, "dividend": 0.20, "quality": 0.20, "momentum": 0.10},
        "HIGH_VOL": {"low_vol": 0.25, "quality": 0.25, "dividend": 0.15, "momentum": 0.05},
    }

    if regime in regime_adjustments:
        base.update(regime_adjustments[regime])

    return base
