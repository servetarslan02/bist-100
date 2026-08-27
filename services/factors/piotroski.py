"""ALPHA BIST — Piotroski F-Score (Nihai).

9 kriter, ağırlıklı, detaylı analiz.
Her kriter için değer, eşik ve sonuç döndürür.
"""

from typing import Any

import structlog

logger = structlog.get_logger()

# Kriter ağırlıkları (araştırma bazlı — İşler Dergisi 2025)
DEFAULT_WEIGHTS = {
    "net_income_positive": 1.0,
    "operating_cf_positive": 1.0,
    "roa_increasing": 1.0,
    "cf_gt_ni": 1.0,
    "leverage_decreasing": 1.0,
    "current_ratio_increasing": 1.0,
    "no_dilution": 1.0,
    "gross_margin_increasing": 1.0,
    "asset_turnover_increasing": 1.0,
}


def calculate_f_score(
    financials: dict[str, Any],
    financials_prev: dict[str, Any] | None = None,
    weights: dict[str, float] | None = None,
) -> dict[str, Any]:
    """Piotroski F-Score — detaylı, ağırlıklı.

    Args:
        financials: Güncel finansal veriler
        financials_prev: Önceki dönem finansal veriler (opsiyonel)
        weights: Kriter ağırlıkları (opsiyonel)

    Returns:
        Dict with f_score, max_score, category, details, signal
    """
    w = weights or DEFAULT_WEIGHTS
    prev = financials_prev or {}
    score = 0.0
    max_score = sum(w.values())
    details = {}

    # 1. Net income > 0 (Kârlılık)
    ni = financials.get("net_income", 0)
    passed = ni > 0
    score += passed * w["net_income_positive"]
    details["net_income_positive"] = {"value": ni, "passed": passed, "weight": w["net_income_positive"]}

    # 2. Operating cash flow > 0 (Nakit akışı)
    ocf = financials.get("operating_cf", 0)
    passed = ocf > 0
    score += passed * w["operating_cf_positive"]
    details["operating_cf_positive"] = {"value": ocf, "passed": passed, "weight": w["operating_cf_positive"]}

    # 3. ROA increasing (Kârlılık trendi)
    roa_curr = financials.get("roa", financials.get("roa_current", 0))
    roa_prev = prev.get("roa", financials.get("roa_prev", 0))
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
    lev_curr = financials.get("leverage", financials.get("leverage_current", 0))
    lev_prev = prev.get("leverage", financials.get("leverage_prev", 0))
    passed = lev_curr < lev_prev
    score += passed * w["leverage_decreasing"]
    details["leverage_decreasing"] = {
        "current": lev_curr,
        "previous": lev_prev,
        "passed": passed,
        "weight": w["leverage_decreasing"],
    }

    # 6. Current ratio increasing (Likidite artışı)
    cr_curr = financials.get("current_ratio", 0)
    cr_prev = prev.get("current_ratio", financials.get("current_ratio_prev", 0))
    passed = cr_curr > cr_prev
    score += passed * w["current_ratio_increasing"]
    details["current_ratio_increasing"] = {
        "current": cr_curr,
        "previous": cr_prev,
        "passed": passed,
        "weight": w["current_ratio_increasing"],
    }

    # 7. No dilution (Seyreltme yok)
    shares_curr = financials.get("shares_outstanding", financials.get("shares_current", 0))
    shares_prev = prev.get("shares_outstanding", financials.get("shares_prev", 0))
    passed = shares_curr <= shares_prev and shares_curr > 0
    score += passed * w["no_dilution"]
    details["no_dilution"] = {
        "current": shares_curr,
        "previous": shares_prev,
        "passed": passed,
        "weight": w["no_dilution"],
    }

    # 8. Gross margin increasing (Marj artışı)
    gm_curr = financials.get("gross_margin", 0)
    gm_prev = prev.get("gross_margin", financials.get("gross_margin_prev", 0))
    passed = gm_curr > gm_prev
    score += passed * w["gross_margin_increasing"]
    details["gross_margin_increasing"] = {
        "current": gm_curr,
        "previous": gm_prev,
        "passed": passed,
        "weight": w["gross_margin_increasing"],
    }

    # 9. Asset turnover increasing (Verimlilik artışı)
    at_curr = financials.get("asset_turnover", 0)
    at_prev = prev.get("asset_turnover", financials.get("asset_turnover_prev", 0))
    passed = at_curr > at_prev
    score += passed * w["asset_turnover_increasing"]
    details["asset_turnover_increasing"] = {
        "current": at_curr,
        "previous": at_prev,
        "passed": passed,
        "weight": w["asset_turnover_increasing"],
    }

    # Normalize score to 0-9 range
    normalized_score = int(score * 9 / max_score + 0.5) if max_score > 0 else 0

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

    result = {
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


def calculate_f_score_simple(financials: dict[str, Any]) -> int:
    """Basitleştirilmiş F-Score (backward compatibility)."""
    result = calculate_f_score(financials)
    return result["f_score"]
