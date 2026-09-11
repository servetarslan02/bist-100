"""ALPHA BIST — Multi-Factor Ranking (Nihai).

Risk-adjusted, sector-neutral, regime-based ranking.
"""

from __future__ import annotations

import math
from types import MappingProxyType
from typing import Any

import numpy as np
import structlog

logger = structlog.get_logger(__name__)

__all__ = ["DEFAULT_WEIGHTS", "REGIME_WEIGHTS", "get_bottom_n", "get_top_n", "rank_stocks"]

# Risk cezası gücü (0=ceza yok, 1=tam ceza)
_RISK_AVERSION: float = 0.5

# Varsayılan faktör ağırlıkları — immutable
DEFAULT_WEIGHTS: MappingProxyType[str, float] = MappingProxyType({
    "value": 0.15,
    "momentum": 0.20,
    "quality": 0.20,
    "size": 0.10,
    "low_vol": 0.10,
    "dividend": 0.10,
    "leverage": 0.10,
    "bist_specific": 0.05,
})

# Rejime göre ağırlık ayarlamaları — immutable
REGIME_WEIGHTS: MappingProxyType[str, MappingProxyType[str, float]] = MappingProxyType({
    "BULL": MappingProxyType({"momentum": 0.30, "quality": 0.15, "value": 0.10, "low_vol": 0.05}),
    "BEAR": MappingProxyType({"quality": 0.30, "low_vol": 0.20, "dividend": 0.15, "momentum": 0.05}),
    "SIDEWAYS": MappingProxyType({"value": 0.25, "dividend": 0.20, "quality": 0.20}),
    "HIGH_VOL": MappingProxyType({"low_vol": 0.25, "quality": 0.25, "dividend": 0.15}),
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
        logger.warning("ranking_none_value", field=name, default=default)
        return default
    try:
        result = float(value)
        if math.isnan(result) or math.isinf(result):
            logger.warning("ranking_nan_or_inf", field=name, value=value, default=default)
            return default
        return result
    except (ValueError, TypeError) as exc:
        logger.warning("ranking_type_conversion_failed", field=name, value=value, error=str(exc), default=default)
        return default


def rank_stocks(
    universe: list[dict[str, Any]],
    factor_weights: dict[str, float] | None = None,
    regime: str = "NORMAL",
    sector_neutral: bool = False,
    risk_adjust: bool = True,
) -> list[dict[str, Any]]:
    """Çok faktörlü hisse sıralaması — risk-adjusted.

    Args:
        universe: Hisse listesi. Her hisse sözlüğü:
            - ticker: Hisse kodu
            - factors: {factor_name: score} faktör skorları
            - risk_score: Risk skoru (0-100, yüksek = riskli)
            - sector: Sektör adı (opsiyonel)
        factor_weights: Faktör ağırlıkları (opsiyonel). None ise DEFAULT_WEIGHTS.
        regime: Piyasa rejimi (BULL, BEAR, SIDEWAYS, HIGH_VOL, NORMAL).
        sector_neutral: Sektör-nötr sıralama uygula.
        risk_adjust: Risk ayarlaması uygula.

    Returns:
        Sıralanmış hisse listesi. Her hisseye eklenen alanlar:
        factor_score, risk_adjusted_score, factor_contributions, regime, rank, top_pct.
        Girdi listesi doğrudan değiştirilir (in-place).

    Raises:
        TypeError: universe None veya list değilse.
    """
    if universe is None:
        raise TypeError("universe parametresi None olamaz")
    if not isinstance(universe, list):
        raise TypeError(f"universe list olmalı, alınan tip: {type(universe).__name__}")
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
    sector_means: dict[str, dict[str, float]] = {}
    if sector_neutral:
        sector_factors: dict[str, list[dict[str, Any]]] = {}
        for stock in universe:
            sector = stock.get("sector", "OTHER")
            if sector not in sector_factors:
                sector_factors[sector] = []
            sector_factors[sector].append(stock.get("factors", {}))
        for sector, factors_list in sector_factors.items():
            all_keys: set[str] = set()
            for f in factors_list:
                all_keys.update(f.keys())
            sector_means[sector] = {
                k: float(np.mean([_safe_float(f.get(k), name=f"sector.{k}") for f in factors_list]))
                for k in all_keys
            }

    # Her hisse için skor hesapla
    for stock in universe:
        factors = stock.get("factors", {})
        sector = stock.get("sector", "OTHER")

        # Sektör-nötr düzeltme
        if sector_neutral and sector in sector_means:
            adjusted_factors = {
                k: _safe_float(factors.get(k), name=f"stock.{k}") - sector_means[sector].get(k, 0)
                for k in factors
            }
        else:
            adjusted_factors = factors

        # Ağırlıklı skor
        total_score = 0.0
        factor_contributions: dict[str, dict[str, float]] = {}
        for factor, weight in weights.items():
            factor_score = _safe_float(adjusted_factors.get(factor), name=f"factor.{factor}")
            contribution = factor_score * weight
            total_score += contribution
            factor_contributions[factor] = {
                "score": round(factor_score, 4),
                "weight": round(weight, 4),
                "contribution": round(contribution, 4),
            }

        # Risk adjustment
        risk_score = _safe_float(stock.get("risk_score"), default=50.0, name="risk_score")
        if risk_adjust and risk_score > 0:
            risk_penalty = (risk_score / 100) * _RISK_AVERSION
            risk_adjusted_score = total_score * (1 - risk_penalty)
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


def get_top_n(ranked: list[dict[str, Any]], n: int = 10) -> list[dict[str, Any]]:
    """İlk N hisseyi döndür.

    Args:
        ranked: Sıralanmış hisse listesi.
        n: Döndürülecek hisse sayısı.

    Returns:
        İlk N hisse.
    """
    return ranked[:n]


def get_bottom_n(ranked: list[dict[str, Any]], n: int = 10) -> list[dict[str, Any]]:
    """Son N hisseyi döndür.

    Args:
        ranked: Sıralanmış hisse listesi.
        n: Döndürülecek hisse sayısı.

    Returns:
        Son N hisse.
    """
    return ranked[-n:]
