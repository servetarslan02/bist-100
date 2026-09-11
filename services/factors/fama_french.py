"""ALPHA BIST — Fama-French Factor Scores (Nihai).

Value, Momentum, Quality, Size, Low Vol, Dividend, Leverage, BIST-specific.
Cross-sectional z-score normalization.
"""

from __future__ import annotations

import math
from types import MappingProxyType
from typing import Any

import numpy as np
import structlog

logger = structlog.get_logger(__name__)

__all__ = [
    "FACTOR_DEFINITIONS",
    "calculate_factor_scores",
    "calculate_factor_scores_batch",
    "get_factor_weights",
]

# Faktör tanımları — immutable (iç içe MappingProxyType)
FACTOR_DEFINITIONS: MappingProxyType[str, MappingProxyType[str, Any]] = MappingProxyType({
    "value": MappingProxyType({
        "metrics": ("pb_ratio", "pe_ratio", "ev_ebitda", "fcf_yield"),
        "direction": MappingProxyType({"pb_ratio": -1, "pe_ratio": -1, "ev_ebitda": -1, "fcf_yield": 1}),
        "weight": 0.15,
    }),
    "momentum": MappingProxyType({
        "metrics": ("mom_1m", "mom_3m", "mom_6m", "mom_12m"),
        "direction": MappingProxyType({"mom_1m": 1, "mom_3m": 1, "mom_6m": 1, "mom_12m": 1}),
        "weight": 0.20,
    }),
    "quality": MappingProxyType({
        "metrics": ("roe", "roic", "gross_margin", "operating_margin"),
        "direction": MappingProxyType({"roe": 1, "roic": 1, "gross_margin": 1, "operating_margin": 1}),
        "weight": 0.20,
    }),
    "size": MappingProxyType({
        "metrics": ("market_cap",),
        "direction": MappingProxyType({"market_cap": -1}),
        "weight": 0.10,
    }),
    "low_vol": MappingProxyType({
        "metrics": ("volatility", "beta"),
        "direction": MappingProxyType({"volatility": -1, "beta": -1}),
        "weight": 0.10,
    }),
    "dividend": MappingProxyType({
        "metrics": ("dividend_yield", "payout_ratio"),
        "direction": MappingProxyType({"dividend_yield": 1, "payout_ratio": -1}),
        "weight": 0.10,
    }),
    "leverage": MappingProxyType({
        "metrics": ("debt_equity", "net_debt_ebitda"),
        "direction": MappingProxyType({"debt_equity": -1, "net_debt_ebitda": -1}),
        "weight": 0.10,
    }),
    "bist_specific": MappingProxyType({
        "metrics": ("fx_sensitivity", "inflation_beta", "foreign_ownership"),
        "direction": MappingProxyType({"fx_sensitivity": -1, "inflation_beta": -1, "foreign_ownership": 1}),
        "weight": 0.05,
    }),
})


def _safe_float(value: Any, default: float = 0.0, name: str = "unknown") -> float:
    """Değeri güvenli float'a çevirir; None, NaN veya Inf için varsayılan döndürür.

    Args:
        value: Dönüştürülecek değer.
        default: Hata durumunda dönecek varsayılan değer.
        name: Loglama için alan adı.

    Returns:
        Güvenli float değeri.
    """
    if value is None:
        logger.warning("fama_french_none_value", field=name, default=default)
        return default
    try:
        result = float(value)
        if math.isnan(result) or math.isinf(result):
            logger.warning("fama_french_nan_or_inf", field=name, value=value, default=default)
            return default
        return result
    except (ValueError, TypeError) as exc:
        logger.warning("fama_french_type_conversion_failed", field=name, value=value, error=str(exc), default=default)
        return default


def _percentile_from_z(z: float) -> float:
    """Z-score'dan percentile hesaplar (0-1). scipy yoksa math.erf kullanır.

    Args:
        z: Z-score değeri.

    Returns:
        Percentile (0-1 arası).
    """
    try:
        from scipy.stats import norm

        return float(norm.cdf(z))
    except ImportError:
        return 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))


def calculate_factor_scores(
    stock: dict[str, Any] | None,
    universe_stats: dict[str, Any] | None = None,
) -> dict[str, float]:
    """Fama-French faktör skorları — cross-sectional percentile.

    Her faktör için metriklerin z-score'u hesaplanır, percentile'a dönüştürülür
    ve yön düzeltmesi uygulanır. Faktör skoru = metriklerin ortalaması.

    Args:
        stock: Hisse verileri sözlüğü. Her metrik key'i float değer içermeli.
        universe_stats: Evren istatistikleri sözlüğü. Her metrik için:
            {metric}_mean, {metric}_median, {metric}_std, {metric}_p25, {metric}_p75

    Returns:
        8 faktör skoru sözlüğü (0-1 arası): value, momentum, quality, size,
        low_vol, dividend, leverage, bist_specific.

    Raises:
        TypeError: stock None veya dict değilse.
    """
    if stock is None:
        raise TypeError("stock parametresi None olamaz")
    if not isinstance(stock, dict):
        raise TypeError(f"stock dict olmalı, alınan tip: {type(stock).__name__}")

    stats = universe_stats or {}
    scores: dict[str, float] = {}

    for factor_name, factor_def in FACTOR_DEFINITIONS.items():
        metric_scores: list[float] = []

        for metric in factor_def["metrics"]:
            value = _safe_float(stock.get(metric), default=0.0, name=f"stock.{metric}")
            direction = factor_def["direction"].get(metric, 1)

            # Universe istatistikleri
            median = _safe_float(
                stats.get(f"{metric}_median", stats.get(f"{metric}_mean")),
                default=0.0,
                name=f"stats.{metric}_median",
            )
            std = _safe_float(stats.get(f"{metric}_std"), default=1.0, name=f"stats.{metric}_std")

            # Percentile skor
            if std > 1e-10:
                z = (value - median) / std
                percentile = _percentile_from_z(z)
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
    universe: list[dict[str, Any]] | None,
) -> list[dict[str, Any]]:
    """Tüm evren için toplu faktör skoru hesaplama.

    Args:
        universe: [{ticker, ...factor metrics...}] listesi.

    Returns:
        Her hisse için 'factor_scores' anahtarı eklenmiş liste.
        Orijinal liste değiştirilmez (kopya üzerinde çalışır).

    Raises:
        TypeError: universe None veya list değilse.
    """
    if universe is None:
        raise TypeError("universe parametresi None olamaz")
    if not isinstance(universe, list):
        raise TypeError(f"universe list olmalı, alınan tip: {type(universe).__name__}")
    if not universe:
        return []

    # Kopya üzerinde çalış (input'u mutate etme)
    universe = [dict(s) for s in universe]

    # Tüm metrikler için evren istatistikleri hesapla
    all_metrics: set[str] = set()
    for factor_def in FACTOR_DEFINITIONS.values():
        all_metrics.update(factor_def["metrics"])

    universe_stats: dict[str, Any] = {}
    for metric in all_metrics:
        values = [_safe_float(s.get(metric), name=f"batch.{metric}") for s in universe if metric in s]
        if values:
            arr = np.array(values, dtype=float)
            # NaN/Inf temizle
            arr = arr[np.isfinite(arr)]
            if len(arr) > 0:
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
    """Rejime göre faktör ağırlıkları döndür.

    Args:
        regime: Piyasa rejimi (BULL, BEAR, SIDEWAYS, HIGH_VOL, NORMAL).

    Returns:
        Faktör ağırlıkları sözlüğü. NORMAL rejimde FACTOR_DEFINITIONS
        ağırlıkları döner; diğer rejimlerde override uygulanır.
    """
    base = {k: v["weight"] for k, v in FACTOR_DEFINITIONS.items()}

    regime_adjustments: dict[str, dict[str, float]] = {
        "BULL": {"momentum": 0.30, "quality": 0.15, "value": 0.10, "low_vol": 0.05},
        "BEAR": {"quality": 0.30, "low_vol": 0.20, "dividend": 0.15, "momentum": 0.05},
        "SIDEWAYS": {"value": 0.25, "dividend": 0.20, "quality": 0.20, "momentum": 0.10},
        "HIGH_VOL": {"low_vol": 0.25, "quality": 0.25, "dividend": 0.15, "momentum": 0.05},
    }

    if regime in regime_adjustments:
        base.update(regime_adjustments[regime])
    else:
        logger.warning("fama_french_unknown_regime", regime=regime, action="using_default_weights")

    # Ağırlıkları normalize et (toplam = 1.0)
    total = sum(base.values())
    if total > 0:
        base = {k: v / total for k, v in base.items()}

    return base
