"""ALPHA BIST — Piotroski F-Score (Nihai).

9 kriter, ağırlıklı, detaylı analiz.
Her kriter için değer, eşik ve sonuç döndürür.
"""

from __future__ import annotations

import math
from types import MappingProxyType
from typing import Any

import structlog

logger = structlog.get_logger(__name__)

__all__ = ["calculate_f_score", "calculate_f_score_simple"]

# Kriter ağırlıkları (araştırma bazlı — İşler Dergisi 2025) — immutable
DEFAULT_WEIGHTS: MappingProxyType[str, float] = MappingProxyType({
    "net_income_positive": 1.0,
    "operating_cf_positive": 1.0,
    "roa_increasing": 1.0,
    "cf_gt_ni": 1.0,
    "leverage_decreasing": 1.0,
    "current_ratio_increasing": 1.0,
    "no_dilution": 1.0,
    "gross_margin_increasing": 1.0,
    "asset_turnover_increasing": 1.0,
})

# Beklenen kriter anahtarları
_REQUIRED_CRITERIA: frozenset[str] = frozenset({
    "net_income_positive",
    "operating_cf_positive",
    "roa_increasing",
    "cf_gt_ni",
    "leverage_decreasing",
    "current_ratio_increasing",
    "no_dilution",
    "gross_margin_increasing",
    "asset_turnover_increasing",
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
        logger.warning("piotroski_none_value", field=name, default=default)
        return default
    try:
        result = float(value)
        if math.isnan(result) or math.isinf(result):
            logger.warning("piotroski_nan_or_inf", field=name, value=value, default=default)
            return default
        return result
    except (ValueError, TypeError) as exc:
        logger.warning("piotroski_type_conversion_failed", field=name, value=value, error=str(exc), default=default)
        return default


def calculate_f_score(
    financials: dict[str, Any] | None,
    financials_prev: dict[str, Any] | None = None,
    weights: dict[str, float] | None = None,
) -> dict[str, Any]:
    """Piotroski F-Score — detaylı, ağırlıklı.

    9 kriterin her birini değerlendirir, ağırlıklı puan hesaplar ve
    0-9 aralığına normalize eder. Kriter grupları (kârlılık, borç/likidite,
    verimlilik) alt skorları ayrıca raporlanır.

    Args:
        financials: Güncel finansal veriler sözlüğü. Beklenen anahtarlar:
            net_income, operating_cf, roa/roa_current, leverage/leverage_current,
            current_ratio, shares_outstanding/shares_current, gross_margin,
            asset_turnover
        financials_prev: Önceki dönem finansal veriler (opsiyonel).
            None ise financials içinden *_prev anahtarları okunur.
        weights: Kriter ağırlıkları (opsiyonel). 9 anahtar içermeli.

    Returns:
        Dict with f_score (0-9), raw_score, max_score, category (STRONG/
        MODERATE/WEAK), signal (BUY/HOLD/SELL), details, sub_scores.

    Raises:
        TypeError: financials None veya dict değilse.
        ValueError: weights eksik kriter içeriyorsa.
    """
    if financials is None:
        raise TypeError("financials parametresi None olamaz")
    if not isinstance(financials, dict):
        raise TypeError(f"financials dict olmalı, alınan tip: {type(financials).__name__}")

    # Ağırlıkları doğrula
    if weights is not None:
        missing = _REQUIRED_CRITERIA - set(weights.keys())
        if missing:
            raise ValueError(f"weights eksik kriterler: {sorted(missing)}")
        w = dict(weights)
    else:
        w = dict(DEFAULT_WEIGHTS)

    prev = financials_prev or {}
    score = 0.0
    max_score = sum(w.values())
    details: dict[str, dict[str, Any]] = {}

    # 1. Net income > 0 (Kârlılık)
    ni = _safe_float(financials.get("net_income"), default=0.0, name="net_income")
    passed = ni > 0
    score += passed * w["net_income_positive"]
    details["net_income_positive"] = {"value": ni, "passed": passed, "weight": w["net_income_positive"]}

    # 2. Operating cash flow > 0 (Nakit akışı)
    ocf = _safe_float(financials.get("operating_cf"), default=0.0, name="operating_cf")
    passed = ocf > 0
    score += passed * w["operating_cf_positive"]
    details["operating_cf_positive"] = {"value": ocf, "passed": passed, "weight": w["operating_cf_positive"]}

    # 3. ROA increasing (Kârlılık trendi)
    roa_curr = _safe_float(
        financials.get("roa", financials.get("roa_current")),
        default=0.0,
        name="roa_curr",
    )
    roa_prev = _safe_float(
        prev.get("roa", financials.get("roa_prev")),
        default=0.0,
        name="roa_prev",
    )
    passed = roa_curr > roa_prev
    score += passed * w["roa_increasing"]
    details["roa_increasing"] = {
        "current": roa_curr,
        "previous": roa_prev,
        "passed": passed,
        "weight": w["roa_increasing"],
    }

    # 4. Cash flow > Net income (Kazanç kalitesi — düşük tahakkuk)
    # Orijinal Piotroski: CFO > NI. Negatif değerlerde anlamsız → sadece pozitif NI'da uygula
    passed = ocf > ni and ni > 0
    score += passed * w["cf_gt_ni"]
    details["cf_gt_ni"] = {"cf": ocf, "ni": ni, "passed": passed, "weight": w["cf_gt_ni"]}

    # 5. Leverage decreasing (Borç azalması)
    lev_curr = _safe_float(
        financials.get("leverage", financials.get("leverage_current")),
        default=0.0,
        name="leverage_curr",
    )
    lev_prev = _safe_float(
        prev.get("leverage", financials.get("leverage_prev")),
        default=0.0,
        name="leverage_prev",
    )
    passed = lev_curr < lev_prev
    score += passed * w["leverage_decreasing"]
    details["leverage_decreasing"] = {
        "current": lev_curr,
        "previous": lev_prev,
        "passed": passed,
        "weight": w["leverage_decreasing"],
    }

    # 6. Current ratio increasing (Likidite artışı)
    cr_curr = _safe_float(financials.get("current_ratio"), default=0.0, name="current_ratio_curr")
    cr_prev = _safe_float(
        prev.get("current_ratio", financials.get("current_ratio_prev")),
        default=0.0,
        name="current_ratio_prev",
    )
    passed = cr_curr > cr_prev
    score += passed * w["current_ratio_increasing"]
    details["current_ratio_increasing"] = {
        "current": cr_curr,
        "previous": cr_prev,
        "passed": passed,
        "weight": w["current_ratio_increasing"],
    }

    # 7. No dilution (Seyreltme yok)
    shares_curr = _safe_float(
        financials.get("shares_outstanding", financials.get("shares_current")),
        default=0.0,
        name="shares_curr",
    )
    shares_prev = _safe_float(
        prev.get("shares_outstanding", financials.get("shares_prev")),
        default=0.0,
        name="shares_prev",
    )
    passed = shares_curr <= shares_prev and shares_curr > 0
    score += passed * w["no_dilution"]
    details["no_dilution"] = {
        "current": shares_curr,
        "previous": shares_prev,
        "passed": passed,
        "weight": w["no_dilution"],
    }

    # 8. Gross margin increasing (Marj artışı)
    gm_curr = _safe_float(financials.get("gross_margin"), default=0.0, name="gross_margin_curr")
    gm_prev = _safe_float(
        prev.get("gross_margin", financials.get("gross_margin_prev")),
        default=0.0,
        name="gross_margin_prev",
    )
    passed = gm_curr > gm_prev
    score += passed * w["gross_margin_increasing"]
    details["gross_margin_increasing"] = {
        "current": gm_curr,
        "previous": gm_prev,
        "passed": passed,
        "weight": w["gross_margin_increasing"],
    }

    # 9. Asset turnover increasing (Verimlilik artışı)
    at_curr = _safe_float(financials.get("asset_turnover"), default=0.0, name="asset_turnover_curr")
    at_prev = _safe_float(
        prev.get("asset_turnover", financials.get("asset_turnover_prev")),
        default=0.0,
        name="asset_turnover_prev",
    )
    passed = at_curr > at_prev
    score += passed * w["asset_turnover_increasing"]
    details["asset_turnover_increasing"] = {
        "current": at_curr,
        "previous": at_prev,
        "passed": passed,
        "weight": w["asset_turnover_increasing"],
    }

    # Normalize score to 0-9 range
    if max_score > 0:
        normalized_score = int(score * 9 / max_score + 0.5)
    else:
        logger.warning("piotroski_zero_max_score", max_score=max_score)
        normalized_score = 0

    # Category
    if normalized_score >= 7:
        category = "STRONG"
        signal = "BUY"
    elif normalized_score >= 4:
        category = "MODERATE"
        signal = "HOLD"
    else:
        category = "WEAK"
        signal = "SELL"

    # Kriter grupları
    profitability = sum(
        1
        for k in ["net_income_positive", "operating_cf_positive", "roa_increasing", "cf_gt_ni"]
        if details[k]["passed"]
    )
    leverage_liquidity = sum(
        1 for k in ["leverage_decreasing", "current_ratio_increasing", "no_dilution"] if details[k]["passed"]
    )
    efficiency = sum(1 for k in ["gross_margin_increasing", "asset_turnover_increasing"] if details[k]["passed"])

    result: dict[str, Any] = {
        "f_score": normalized_score,
        "raw_score": round(score, 2),
        "max_score": 9,
        "category": category,
        "signal": signal,
        "details": details,
        "sub_scores": {
            "profitability": {"score": profitability, "max": 4, "pct": round(profitability / 4 * 100, 1)},
            "leverage_liquidity": {
                "score": leverage_liquidity,
                "max": 3,
                "pct": round(leverage_liquidity / 3 * 100, 1),
            },
            "efficiency": {"score": efficiency, "max": 2, "pct": round(efficiency / 2 * 100, 1)},
        },
    }

    logger.info("piotroski_calculated", f_score=normalized_score, category=category)
    return result


def calculate_f_score_simple(financials: dict[str, Any] | None) -> int:
    """Basitleştirilmiş F-Score (backward compatibility).

    Args:
        financials: Finansal veriler sözlüğü.

    Returns:
        Normalize edilmiş F-Score (0-9).

    Raises:
        TypeError: financials None veya dict değilse.
    """
    result = calculate_f_score(financials)
    return result["f_score"]
