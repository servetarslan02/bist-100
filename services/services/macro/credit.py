"""
ALPHA BIST — Credit Features v2.0

Kredi büyüme feature'ları:
- credit_growth_yoy: Kredi yıllık büyüme
- credit_gdp_ratio: Kredi/GSYH oranı
- credit_trend: Kredi trendi
- credit_momentum: Kredi momentum
"""

from typing import Dict, Any
import structlog

logger = structlog.get_logger()


def compute_credit_features(credit_data: Dict[str, Any]) -> Dict[str, float]:
    """Kredi büyüme feature'ları.

    Args:
        credit_data: {
            "credit_growth_yoy": float,  # Yıllık büyüme (%)
            "credit_gdp_ratio": float,    # Kredi/GSYH (%)
            "credit_previous": float,     # Önceki büyüme
            "credit_total": float,        # Toplam kredi hacmi
        }

    Returns:
        Feature dictionary
    """
    features = {}

    try:
        credit_growth = credit_data.get("credit_growth_yoy")
        if credit_growth is not None:
            features["credit_growth_yoy"] = round(float(credit_growth), 2)

            # Kredi rejimi
            growth = float(credit_growth)
            if growth > 20:
                features["credit_regime"] = 3.0  # ÇOK HIZLI
            elif growth > 10:
                features["credit_regime"] = 2.0  # HIZLI
            elif growth > 0:
                features["credit_regime"] = 1.0  # POZİTİF
            elif growth > -5:
                features["credit_regime"] = 0.0  # STAGNANT
            else:
                features["credit_regime"] = -1.0  # DARALMA

        # Kredi/GSYH oranı
        credit_gdp = credit_data.get("credit_gdp_ratio")
        if credit_gdp is not None:
            features["credit_gdp_ratio"] = round(float(credit_gdp), 2)

        # Kredi trendi
        credit_previous = credit_data.get("credit_previous")
        if credit_growth is not None and credit_previous is not None:
            trend = float(credit_growth) - float(credit_previous)
            features["credit_trend"] = round(trend, 4)
            features["credit_trend_direction"] = 1.0 if trend > 0.5 else (-1.0 if trend < -0.5 else 0.0)

    except Exception as e:
        logger.error("Credit feature computation failed", error=str(e))

    return features
