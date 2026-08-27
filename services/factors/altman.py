"""ALPHA BIST — Altman Z-Score (Nihai).

Orijinal Altman (1968) + Türkiye'ye özgü düzeltme (enflasyon, kur, sektör).
"""
from typing import Any

import structlog

logger = structlog.get_logger()

# Orijinal Altman katsayıları
COEFFICIENTS = {"wc_ta": 1.2, "re_ta": 1.4, "ebit_ta": 3.3, "equity_debt": 0.6, "sales_ta": 1.0}

# Türkiye düzeltmeleri
TURKEY_ADJUSTMENTS = {
    "inflation": 0.85,
    "fx": 0.90,
    "sector": {
        "BANKA": 1.10, "SANAYI": 0.95, "TEKNOLOJI": 1.05, "ENERJI": 0.90,
        "GIDA": 0.95, "ULASIM": 0.92, "INSAAT": 0.88, "METAL": 0.93,
        "TEKSTIL": 0.90, "TELEKOM": 1.00,
    },
}

# Bölge eşikleri
ZONES = {"safe": 2.99, "grey": 1.81}


def calculate_z_score(
    financials: dict[str, Any],
    sector: str = "OTHER",
    turkey_adjusted: bool = True,
) -> dict[str, Any]:
    """Altman Z-Score — detaylı, Türkiye düzeltmeli.

    Args:
        financials: Finansal veriler
        sector: Sektör adı
        turkey_adjusted: Türkiye düzeltmesi uygula mı?

    Returns:
        Dict with z_score, zone, components, adjustments
    """
    ta = max(financials.get("total_assets", 1), 1)

    # Bileşenler
    wc_ta = financials.get("working_capital", 0) / ta
    re_ta = financials.get("retained_earnings", 0) / ta
    ebit_ta = financials.get("ebit", 0) / ta
    td = max(financials.get("total_debt", 1), 1)
    equity_debt = financials.get("market_cap", financials.get("equity", 0)) / td
    sales_ta = financials.get("revenue", 0) / ta

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

    # Bölge
    if z_adjusted > ZONES["safe"]:
        zone = "SAFE"
        signal = "BUY"
    elif z_adjusted > ZONES["grey"]:
        zone = "GREY"
        signal = "HOLD"
    else:
        zone = "DISTRESS"
        signal = "SELL"

    result = {
        "z_score": round(z_adjusted, 4),
        "z_score_original": round(z_original, 4),
        "zone": zone,
        "signal": signal,
        "thresholds": ZONES,
        "adjustments": {"inflation": inf_adj, "fx": fx_adj, "sector": sec_adj},
        "components": {
            "wc_ta": round(wc_ta, 4),
            "re_ta": round(_reta := re_ta, 4),
            "ebit_ta": round(ebit_ta, 4),
            "equity_debt": round(equity_debt, 4),
            "sales_ta": round(sales_ta, 4),
        },
    }

    logger.info("altman_calculated", z_score=z_adjusted, zone=zone)
    return result


def calculate_z_score_simple(financials: dict[str, Any]) -> float:
    """Basitleştirilmiş Z-Score (backward compatibility)."""
    result = calculate_z_score(financials, turkey_adjusted=False)
    return result["z_score"]
