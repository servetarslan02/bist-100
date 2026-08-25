"""
ALPHA BIST — Inflation Features v2.0

Enflasyon feature'ları:
- cpi_yoy: Tüketici fiyatları yıllık değişim
- ppi_yoy: Üretici fiyatları yıllık değişim
- core_cpi: Çekirdek enflasyon
- cpi_ppi_spread: CPI-PPI spread (maliyet geçişkenliği)
- inflation_trend: Enflasyon trendi
- inflation_surprise: Enflasyon sürprizi
- inflation_regime: Enflasyon rejimi (düşük/orta/yüksek/çok yüksek)
"""

from typing import Dict, Any
import structlog

logger = structlog.get_logger()


def compute_inflation_features(inflation_data: Dict[str, Any]) -> Dict[str, float]:
    """Enflasyon feature'ları.

    Args:
        inflation_data: {
            "cpi_yoy": float,           # CPI yıllık değişim (%)
            "ppi_yoy": float,           # PPI yıllık değişim (%)
            "core_cpi": float,          # Çekirdek enflasyon (%)
            "cpi_monthly": float,       # CPI aylık değişim (%)
            "ppi_monthly": float,       # PPI aylık değişim (%)
            "cpi_expected": float,      # CPI beklenti
            "cpi_previous": float,      # Önceki CPI
        }

    Returns:
        Feature dictionary
    """
    features = {}

    try:
        # CPI seviyesi
        cpi_yoy = inflation_data.get("cpi_yoy")
        if cpi_yoy is not None:
            features["inf_cpi_level"] = round(float(cpi_yoy), 2)

            # Enflasyon rejimi
            if float(cpi_yoy) > 50:
                features["inf_regime"] = 4.0  # ÇOK YÜKSEK
            elif float(cpi_yoy) > 25:
                features["inf_regime"] = 3.0  # YÜKSEK
            elif float(cpi_yoy) > 10:
                features["inf_regime"] = 2.0  # ORTA-YÜKSEK
            elif float(cpi_yoy) > 5:
                features["inf_regime"] = 1.0  # ORTA
            else:
                features["inf_regime"] = 0.0  # DÜŞÜK

        # PPI seviyesi
        ppi_yoy = inflation_data.get("ppi_yoy")
        if ppi_yoy is not None:
            features["inf_ppi_level"] = round(float(ppi_yoy), 2)

        # CPI-PPI spread (maliyet geçişkenliği)
        if cpi_yoy is not None and ppi_yoy is not None:
            features["inf_cpi_ppi_spread"] = round(float(cpi_yoy) - float(ppi_yoy), 2)

        # Çekirdek enflasyon
        core_cpi = inflation_data.get("core_cpi")
        if core_cpi is not None:
            features["inf_core_cpi"] = round(float(core_cpi), 2)
            if cpi_yoy is not None:
                features["inf_core_headline_spread"] = round(float(core_cpi) - float(cpi_yoy), 2)

        # Aylık değişim
        cpi_monthly = inflation_data.get("cpi_monthly")
        if cpi_monthly is not None:
            features["inf_cpi_monthly"] = round(float(cpi_monthly), 2)
            # Yıllıklandırılmış aylık
            # Bileşik formül: (1 + aylık_oran)^12 - 1
            monthly_rate = float(cpi_monthly) / 100
            features["inf_cpi_annualized"] = round(((1 + monthly_rate) ** 12 - 1) * 100, 2)

        # Enflasyon sürprizi
        cpi_expected = inflation_data.get("cpi_expected")
        if cpi_yoy is not None and cpi_expected is not None:
            surprise = float(cpi_yoy) - float(cpi_expected)
            features["inf_surprise"] = round(surprise, 4)
            features["inf_surprise_pct"] = round(surprise / max(abs(float(cpi_expected)), 0.01), 4)
            features["inf_surprise_direction"] = (
                1.0 if surprise > 0.5 else (-1.0 if surprise < -0.5 else 0.0)
            )

        # Enflasyon trendi
        cpi_previous = inflation_data.get("cpi_previous")
        if cpi_yoy is not None and cpi_previous is not None:
            trend = float(cpi_yoy) - float(cpi_previous)
            features["inf_trend"] = round(trend, 4)
            features["inf_trend_direction"] = (
                1.0 if trend > 0.5 else (-1.0 if trend < -0.5 else 0.0)
            )

    except Exception as e:
        logger.error("Inflation feature computation failed", error=str(e))

    return features
