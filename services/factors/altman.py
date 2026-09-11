"""ALPHA BIST — Altman Z-Score (Nihai).

Orijinal Altman (1968) + Türkiye'ye özgü düzeltme (enflasyon, kur, sektör).
"""

from __future__ import annotations

import math
from types import MappingProxyType
from typing import Any

import structlog

logger = structlog.get_logger(__name__)

__all__ = ["calculate_z_score", "calculate_z_score_simple"]

# Orijinal Altman katsayıları (1968) — immutable
COEFFICIENTS: MappingProxyType[str, float] = MappingProxyType({
    "wc_ta": 1.2,
    "re_ta": 1.4,
    "ebit_ta": 3.3,
    "equity_debt": 0.6,
    "sales_ta": 1.0,
})

# Türkiye düzeltmeleri — enflasyon, kur, sektör bazlı çarpanlar (immutable)
TURKEY_ADJUSTMENTS: MappingProxyType[str, Any] = MappingProxyType({
    "inflation": 0.85,
    "fx": 0.90,
    "sector": MappingProxyType({
        "BANKA": 1.10,
        "SANAYI": 0.95,
        "TEKNOLOJI": 1.05,
        "ENERJI": 0.90,
        "GIDA": 0.95,
        "ULASIM": 0.92,
        "INSAAT": 0.88,
        "METAL": 0.93,
        "TEKSTIL": 0.90,
        "TELEKOM": 1.00,
    }),
})

# Bölge eşikleri — Altman orijinal sınıflandırma (immutable)
ZONES: MappingProxyType[str, float] = MappingProxyType({"safe": 2.99, "grey": 1.81})

# Bölünme hatası koruması için minimum değer
_MIN_DENOMINATOR: float = 1e-6


def _safe_float(value: Any, default: float = 0.0, name: str = "unknown") -> float:
    """Değeri güvenli float'a çevirir; None, NaN veya Inf için varsayılan döndürür.

    Args:
        value: Dönüştürülecek değer.
        default: Hata durumunda dönecek varsayılan değer.
        name: Loglama için alan adı.

    Returns:
        Güvenli float değeri.

    Raises:
        Hiçbir zaman — her durumda varsayılan döner.
    """
    if value is None:
        logger.warning("altman_none_value", field=name, default=default)
        return default
    try:
        result = float(value)
        if math.isnan(result) or math.isinf(result):
            logger.warning("altman_nan_or_inf", field=name, value=value, default=default)
            return default
        return result
    except (ValueError, TypeError) as exc:
        logger.warning("altman_type_conversion_failed", field=name, value=value, error=str(exc), default=default)
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
        logger.warning("altman_division_near_zero", field=name, denominator=denominator)
        return 0.0
    return numerator / denominator


def calculate_z_score(
    financials: dict[str, Any] | None,
    sector: str = "OTHER",
    turkey_adjusted: bool = True,
) -> dict[str, Any]:
    """Altman Z-Score — detaylı, Türkiye düzeltmeli.

    Args:
        financials: Finansal veriler sözlüğü. Beklenen anahtarlar:
            - total_assets: Toplam varlıklar
            - working_capital: İşletme sermayesi
            - retained_earnings: Dağıtılmamış kârlar
            - ebit: Faiz ve vergi öncesi kâr
            - market_cap veya equity: Piyasa değeri veya özkaynak
            - total_debt: Toplam borç
            - revenue: Satış gelirleri
        sector: Sektör adı (BANKA, SANAYI, TEKNOLOJI vb.)
        turkey_adjusted: Türkiye düzeltmesi uygulanacak mı?

    Returns:
        Dict with z_score, z_score_original, zone, signal, thresholds,
        adjustments, components.

    Raises:
        TypeError: financials None veya dict değilse.
        ValueError: sector None veya boş string ise.
    """
    if financials is None:
        raise TypeError("financials parametresi None olamaz")
    if not isinstance(financials, dict):
        raise TypeError(f"financials dict olmalı, alınan tip: {type(financials).__name__}")
    if not sector or not isinstance(sector, str):
        raise ValueError(f"sector geçerli bir string olmalı, alınan: {sector!r}")

    # Toplam varlıklar — bölünme hatası koruması
    ta = max(_safe_float(financials.get("total_assets"), default=1.0, name="total_assets"), _MIN_DENOMINATOR)

    # Bileşenler — her biri None/NaN/Inf korumalı
    wc = _safe_float(financials.get("working_capital"), default=0.0, name="working_capital")
    re_ = _safe_float(financials.get("retained_earnings"), default=0.0, name="retained_earnings")
    ebit = _safe_float(financials.get("ebit"), default=0.0, name="ebit")
    market_cap = _safe_float(
        financials.get("market_cap", financials.get("equity")),
        default=0.0,
        name="market_cap/equity",
    )
    td = max(
        _safe_float(financials.get("total_debt"), default=1.0, name="total_debt"),
        _MIN_DENOMINATOR,
    )
    revenue = _safe_float(financials.get("revenue"), default=0.0, name="revenue")

    wc_ta = _safe_divide(wc, ta, name="wc/ta")
    re_ta = _safe_divide(re_, ta, name="re/ta")
    ebit_ta = _safe_divide(ebit, ta, name="ebit/ta")
    equity_debt = _safe_divide(market_cap, td, name="equity/debt")
    sales_ta = _safe_divide(revenue, ta, name="sales/ta")

    # Orijinal Z-Score
    z_original = (
        COEFFICIENTS["wc_ta"] * wc_ta
        + COEFFICIENTS["re_ta"] * re_ta
        + COEFFICIENTS["ebit_ta"] * ebit_ta
        + COEFFICIENTS["equity_debt"] * equity_debt
        + COEFFICIENTS["sales_ta"] * sales_ta
    )

    # Türkiye düzeltmesi
    if turkey_adjusted:
        inf_adj = TURKEY_ADJUSTMENTS["inflation"]
        fx_adj = TURKEY_ADJUSTMENTS["fx"]
        sec_adj = TURKEY_ADJUSTMENTS["sector"].get(sector.upper(), 1.0)
        z_adjusted = z_original * inf_adj * fx_adj * sec_adj
    else:
        inf_adj = fx_adj = sec_adj = 1.0
        z_adjusted = z_original

    # Bölge tespiti
    if z_adjusted > ZONES["safe"]:
        zone = "SAFE"
        signal = "BUY"
    elif z_adjusted > ZONES["grey"]:
        zone = "GREY"
        signal = "HOLD"
    else:
        zone = "DISTRESS"
        signal = "SELL"

    result: dict[str, Any] = {
        "z_score": round(z_adjusted, 4),
        "z_score_original": round(z_original, 4),
        "zone": zone,
        "signal": signal,
        "thresholds": dict(ZONES),
        "adjustments": {"inflation": inf_adj, "fx": fx_adj, "sector": sec_adj},
        "components": {
            "wc_ta": round(wc_ta, 4),
            "re_ta": round(re_ta, 4),
            "ebit_ta": round(ebit_ta, 4),
            "equity_debt": round(equity_debt, 4),
            "sales_ta": round(sales_ta, 4),
        },
    }

    logger.info("altman_calculated", z_score=round(z_adjusted, 4), zone=zone, sector=sector)
    return result


def calculate_z_score_simple(financials: dict[str, Any] | None) -> float:
    """Basitleştirilmiş Z-Score (backward compatibility).

    Args:
        financials: Finansal veriler sözlüğü.

    Returns:
        Düzeltilmemiş Z-Score değeri.

    Raises:
        TypeError: financials None veya dict değilse.
    """
    result = calculate_z_score(financials, turkey_adjusted=False)
    return result["z_score"]
