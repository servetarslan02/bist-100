"""ALPHA BIST — Beneish M-Score (Nihai).

Finansal manipülasyon tespiti — 8 değişken, orijinal Beneish (1999) katsayıları.
Gerçek veriden hesaplama + raw index input desteği.
"""
from typing import Any

import structlog

logger = structlog.get_logger()

# Orijinal Beneish katsayıları (1999)
COEFFICIENTS = {
    "constant": -4.84,
    "dsri": 0.920,
    "gmi": 0.528,
    "aqi": 0.404,
    "sgi": 0.892,
    "depi": 0.115,
    "sgai": -0.172,
    "tata": 4.679,
    "lvgi": -0.327,
}

# Eşik değerleri
THRESHOLDS = {
    "high_risk": -1.78,    # M-Score > -1.78 → manipülasyon olası
    "moderate_risk": -2.22, # M-Score > -2.22 → şüpheli
}


def calculate_m_score(
    current: dict[str, Any],
    previous: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Beneish M-Score — detaylı.

    Args:
        current: Güncel finansal veriler
        previous: Önceki dönem finansal veriler (opsiyonel)
            Eğer None ise, current'dan raw index olarak okunur (backward compat)

    Returns:
        Dict with m_score, threshold, manipulation_likely, category, components
    """
    prev = previous or {}

    # Eğer previous verisi varsa → gerçek hesaplama
    if prev:
        components = _calculate_components(current, prev)
    else:
        # Backward compat: raw index'ler doğrudan current'dan okunur
        components = _read_raw_indices(current)

    # M-Score hesapla
    m_score = (
        COEFFICIENTS["constant"]
        + COEFFICIENTS["dsri"] * components["dsri"]
        + COEFFICIENTS["gmi"] * components["gmi"]
        + COEFFICIENTS["aqi"] * components["aqi"]
        + COEFFICIENTS["sgi"] * components["sgi"]
        + COEFFICIENTS["depi"] * components["depi"]
        + COEFFICIENTS["sgai"] * components["sgai"]
        + COEFFICIENTS["tata"] * components["tata"]
        + COEFFICIENTS["lvgi"] * components["lvgi"]
    )

    # Kategori
    if m_score > THRESHOLDS["high_risk"]:
        category = "HIGH_RISK"
        signal = "SELL"
    elif m_score > THRESHOLDS["moderate_risk"]:
        category = "MODERATE_RISK"
        signal = "HOLD"
    else:
        category = "LOW_RISK"
        signal = "BUY"

    # Risk skoru (0-100, yüksek = riskli)
    risk_score = min(max((m_score + 3) / 2 * 100, 0), 100)

    result = {
        "m_score": round(m_score, 4),
        "threshold": THRESHOLDS["high_risk"],
        "manipulation_likely": m_score > THRESHOLDS["high_risk"],
        "category": category,
        "signal": signal,
        "risk_score": round(risk_score, 1),
        "components": {k: round(v, 4) for k, v in components.items()},
        "coefficients": COEFFICIENTS,
    }

    logger.info("beneish_calculated", m_score=m_score, category=category)
    return result


def _calculate_components(current: dict, previous: dict) -> dict[str, float]:
    """Ham finansal veriden index hesapla."""

    # 1. DSRI (Days Sales in Receivables Index)
    rec_curr = current.get("receivables", 0)
    rev_curr = max(current.get("revenue", 1), 1)
    rec_prev = previous.get("receivables", 0)
    rev_prev = max(previous.get("revenue", 1), 1)
    dsri_curr = rec_curr / rev_curr
    dsri_prev = rec_prev / rev_prev
    dsri = dsri_curr / max(dsri_prev, 0.001)

    # 2. GMI (Gross Margin Index)
    gm_prev = previous.get("gross_margin", 0)
    gm_curr = current.get("gross_margin", 0)
    gmi = gm_prev / max(gm_curr, 0.001) if gm_curr != 0 else 1.0

    # 3. AQI (Asset Quality Index)
    ca_curr = current.get("current_assets", 0)
    ppe_curr = current.get("ppe", 0)
    ta_curr = max(current.get("total_assets", 1), 1)
    ca_prev = previous.get("current_assets", 0)
    ppe_prev = previous.get("ppe", 0)
    ta_prev = max(previous.get("total_assets", 1), 1)
    aqi_curr = max(0.0, 1.0 - (ca_curr + ppe_curr) / ta_curr)
    aqi_prev = max(0.0, 1.0 - (ca_prev + ppe_prev) / ta_prev)
    aqi = aqi_curr / max(aqi_prev, 0.001)

    # 4. SGI (Sales Growth Index)
    sgi = current.get("revenue", 0) / max(previous.get("revenue", 1), 1)

    # 5. DEPI (Depreciation Index)
    dep_curr = current.get("depreciation", 0)
    dep_prev = previous.get("depreciation", 0)
    depi_prev = dep_prev / max(dep_prev + ppe_prev, 1)
    depi_curr = dep_curr / max(dep_curr + ppe_curr, 1)
    depi = depi_prev / max(depi_curr, 0.001)

    # 6. SGAI (SGA Expense Index)
    sga_curr = current.get("sga", 0)
    sga_prev = previous.get("sga", 0)
    sgai_prev = sga_prev / max(rev_prev, 1)
    sgai_curr = sga_curr / max(rev_curr, 1)
    sgai = sgai_curr / max(sgai_prev, 0.001)

    # 7. LVGI (Leverage Index)
    debt_curr = current.get("total_debt", 0)
    debt_prev = previous.get("total_debt", 0)
    lvgi_curr = debt_curr / max(ta_curr, 1)
    lvgi_prev = debt_prev / max(ta_prev, 1)
    lvgi = lvgi_curr / max(lvgi_prev, 0.001)

    # 8. TATA (Total Accruals to Total Assets)
    ni = current.get("net_income", 0)
    ocf = current.get("operating_cf", 0)
    tata = (ni - ocf) / max(ta_curr, 1)

    return {
        "dsri": dsri,
        "gmi": gmi,
        "aqi": aqi,
        "sgi": sgi,
        "depi": depi,
        "sgai": sgai,
        "lvgi": lvgi,
        "tata": tata,
    }


def _read_raw_indices(financials: dict) -> dict[str, float]:
    """Raw index'leri doğrudan oku (backward compatibility)."""
    return {
        "dsri": financials.get("dsri", 1.0),
        "gmi": financials.get("gmi", 1.0),
        "aqi": financials.get("aqi", 1.0),
        "sgi": financials.get("sgi", 1.0),
        "depi": financials.get("depi", 1.0),
        "sgai": financials.get("sgai", 1.0),
        "lvgi": financials.get("lvgi", 1.0),
        "tata": financials.get("tata", 0.0),
    }


def calculate_m_score_simple(financials: dict[str, Any]) -> float:
    """Basitleştirilmiş M-Score (backward compatibility)."""
    result = calculate_m_score(financials)
    return result["m_score"]
