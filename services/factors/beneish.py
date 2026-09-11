"""ALPHA BIST — Beneish M-Score (Nihai).

Finansal manipülasyon tespiti — 8 değişken, orijinal Beneish (1999) katsayıları.
Gerçek veriden hesaplama + raw index input desteği.
"""

from __future__ import annotations

import math
from types import MappingProxyType
from typing import Any

import structlog

logger = structlog.get_logger(__name__)

__all__ = ["calculate_m_score", "calculate_m_score_simple"]

# Orijinal Beneish katsayıları (1999) — immutable
COEFFICIENTS: MappingProxyType[str, float] = MappingProxyType({
    "constant": -4.84,
    "dsri": 0.920,
    "gmi": 0.528,
    "aqi": 0.404,
    "sgi": 0.892,
    "depi": 0.115,
    "sgai": -0.172,
    "tata": 4.679,
    "lvgi": -0.327,
})

# Eşik değerleri — immutable
THRESHOLDS: MappingProxyType[str, float] = MappingProxyType({
    "high_risk": -1.78,  # M-Score > -1.78 → manipülasyon olası
    "moderate_risk": -2.22,  # M-Score > -2.22 → şüpheli
})

# Bölünme hatası koruması için minimum değer
_MIN_DENOMINATOR: float = 1e-3


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
        logger.warning("beneish_none_value", field=name, default=default)
        return default
    try:
        result = float(value)
        if math.isnan(result) or math.isinf(result):
            logger.warning("beneish_nan_or_inf", field=name, value=value, default=default)
            return default
        return result
    except (ValueError, TypeError) as exc:
        logger.warning("beneish_type_conversion_failed", field=name, value=value, error=str(exc), default=default)
        return default


def _safe_divide(numerator: float, denominator: float, name: str = "unknown") -> float:
    """Güvenli bölme — sıfıra veya çok küçük bölenlere karşı korumalı.

    Args:
        numerator: Pay.
        denominator: Payda.
        name: Loglama için alan adı.

    Returns:
        Bölme sonucu veya 0.0.
    """
    if abs(denominator) < _MIN_DENOMINATOR:
        logger.warning("beneish_division_near_zero", field=name, denominator=denominator)
        return 0.0
    return numerator / denominator


def calculate_m_score(
    current: dict[str, Any] | None,
    previous: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Beneish M-Score — detaylı.

    Args:
        current: Güncel finansal veriler sözlüğü.
            previous None ise raw index olarak okunur:
            dsri, gmi, aqi, sgi, depi, sgai, lvgi, tata
            previous verisi varsa beklenen anahtarlar:
            receivables, revenue, gross_margin, current_assets, ppe,
            total_assets, depreciation, sga, total_debt, net_income, operating_cf
        previous: Önceki dönem finansal veriler (opsiyonel).
            Eğer None ise, current'dan raw index olarak okunur (backward compat).

    Returns:
        Dict with m_score, threshold, manipulation_likely, category, signal,
        risk_score, components, coefficients.

    Raises:
        TypeError: current None veya dict değilse.
    """
    if current is None:
        raise TypeError("current parametresi None olamaz")
    if not isinstance(current, dict):
        raise TypeError(f"current dict olmalı, alınan tip: {type(current).__name__}")

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

    result: dict[str, Any] = {
        "m_score": round(m_score, 4),
        "threshold": THRESHOLDS["high_risk"],
        "manipulation_likely": m_score > THRESHOLDS["high_risk"],
        "category": category,
        "signal": signal,
        "risk_score": round(risk_score, 1),
        "components": {k: round(v, 4) for k, v in components.items()},
        "coefficients": dict(COEFFICIENTS),
    }

    logger.info("beneish_calculated", m_score=round(m_score, 4), category=category)
    return result


def _calculate_components(current: dict[str, Any], previous: dict[str, Any]) -> dict[str, float]:
    """Ham finansal veriden 8 Beneish index'ini hesaplar.

    Args:
        current: Güncel finansal veriler.
        previous: Önceki dönem finansal veriler.

    Returns:
        8 index sözlüğü: dsri, gmi, aqi, sgi, depi, sgai, lvgi, tata.
    """
    # 1. DSRI (Days Sales in Receivables Index)
    rec_curr = _safe_float(current.get("receivables"), default=0.0, name="receivables_curr")
    rev_curr = max(_safe_float(current.get("revenue"), default=1.0, name="revenue_curr"), _MIN_DENOMINATOR)
    rec_prev = _safe_float(previous.get("receivables"), default=0.0, name="receivables_prev")
    rev_prev = max(_safe_float(previous.get("revenue"), default=1.0, name="revenue_prev"), _MIN_DENOMINATOR)
    dsri_curr = _safe_divide(rec_curr, rev_curr, name="dsri_curr")
    dsri_prev = _safe_divide(rec_prev, rev_prev, name="dsri_prev")
    dsri = _safe_divide(dsri_curr, dsri_prev, name="dsri")

    # 2. GMI (Gross Margin Index)
    gm_prev = _safe_float(previous.get("gross_margin"), default=0.0, name="gross_margin_prev")
    gm_curr = _safe_float(current.get("gross_margin"), default=0.0, name="gross_margin_curr")
    gmi = _safe_divide(gm_prev, gm_curr, name="gmi") if abs(gm_curr) > _MIN_DENOMINATOR else 1.0

    # 3. AQI (Asset Quality Index)
    ca_curr = _safe_float(current.get("current_assets"), default=0.0, name="current_assets_curr")
    ppe_curr = _safe_float(current.get("ppe"), default=0.0, name="ppe_curr")
    ta_curr = max(_safe_float(current.get("total_assets"), default=1.0, name="total_assets_curr"), _MIN_DENOMINATOR)
    ca_prev = _safe_float(previous.get("current_assets"), default=0.0, name="current_assets_prev")
    ppe_prev = _safe_float(previous.get("ppe"), default=0.0, name="ppe_prev")
    ta_prev = max(_safe_float(previous.get("total_assets"), default=1.0, name="total_assets_prev"), _MIN_DENOMINATOR)
    aqi_curr = max(0.0, 1.0 - _safe_divide(ca_curr + ppe_curr, ta_curr, name="aqi_curr_calc"))
    aqi_prev = max(0.0, 1.0 - _safe_divide(ca_prev + ppe_prev, ta_prev, name="aqi_prev_calc"))
    aqi = _safe_divide(aqi_curr, aqi_prev, name="aqi")

    # 4. SGI (Sales Growth Index)
    sgi = _safe_divide(
        _safe_float(current.get("revenue"), default=0.0, name="sgi_rev_curr"),
        max(_safe_float(previous.get("revenue"), default=1.0, name="sgi_rev_prev"), _MIN_DENOMINATOR),
        name="sgi",
    )

    # 5. DEPI (Depreciation Index)
    dep_curr = _safe_float(current.get("depreciation"), default=0.0, name="depreciation_curr")
    dep_prev = _safe_float(previous.get("depreciation"), default=0.0, name="depreciation_prev")
    depi_prev = _safe_divide(dep_prev, dep_prev + ppe_prev, name="depi_prev_calc")
    depi_curr = _safe_divide(dep_curr, dep_curr + ppe_curr, name="depi_curr_calc")
    depi = _safe_divide(depi_prev, depi_curr, name="depi")

    # 6. SGAI (SGA Expense Index)
    sga_curr = _safe_float(current.get("sga"), default=0.0, name="sga_curr")
    sga_prev = _safe_float(previous.get("sga"), default=0.0, name="sga_prev")
    sgai_prev = _safe_divide(sga_prev, rev_prev, name="sgai_prev_calc")
    sgai_curr = _safe_divide(sga_curr, rev_curr, name="sgai_curr_calc")
    sgai = _safe_divide(sgai_curr, sgai_prev, name="sgai")

    # 7. LVGI (Leverage Index)
    debt_curr = _safe_float(current.get("total_debt"), default=0.0, name="total_debt_curr")
    debt_prev = _safe_float(previous.get("total_debt"), default=0.0, name="total_debt_prev")
    lvgi_curr = _safe_divide(debt_curr, ta_curr, name="lvgi_curr_calc")
    lvgi_prev = _safe_divide(debt_prev, ta_prev, name="lvgi_prev_calc")
    lvgi = _safe_divide(lvgi_curr, lvgi_prev, name="lvgi")

    # 8. TATA (Total Accruals to Total Assets)
    ni = _safe_float(current.get("net_income"), default=0.0, name="net_income")
    ocf = _safe_float(current.get("operating_cf"), default=0.0, name="operating_cf")
    tata = _safe_divide(ni - ocf, ta_curr, name="tata")

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


def _read_raw_indices(financials: dict[str, Any]) -> dict[str, float]:
    """Raw index'leri doğrudan oku (backward compatibility).

    Args:
        financials: Raw index değerleri sözlüğü.

    Returns:
        8 index sözlüğü.
    """
    return {
        "dsri": _safe_float(financials.get("dsri"), default=1.0, name="dsri"),
        "gmi": _safe_float(financials.get("gmi"), default=1.0, name="gmi"),
        "aqi": _safe_float(financials.get("aqi"), default=1.0, name="aqi"),
        "sgi": _safe_float(financials.get("sgi"), default=1.0, name="sgi"),
        "depi": _safe_float(financials.get("depi"), default=1.0, name="depi"),
        "sgai": _safe_float(financials.get("sgai"), default=1.0, name="sgai"),
        "lvgi": _safe_float(financials.get("lvgi"), default=1.0, name="lvgi"),
        "tata": _safe_float(financials.get("tata"), default=0.0, name="tata"),
    }


def calculate_m_score_simple(financials: dict[str, Any] | None) -> float:
    """Basitleştirilmiş M-Score (backward compatibility).

    Args:
        financials: Finansal veriler sözlüğü.

    Returns:
        M-Score değeri (float).

    Raises:
        TypeError: financials None veya dict değilse.
    """
    result = calculate_m_score(financials)
    return result["m_score"]
