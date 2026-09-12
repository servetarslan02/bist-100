"""
ALPHA BIST — Credit Features v2.0

Kredi büyüme feature'ları:
- credit_growth_yoy: Kredi yıllık büyüme
- credit_gdp_ratio: Kredi/GSYH oranı
- credit_trend: Kredi trendi
- credit_momentum: Kredi momentum
"""

from typing import Any

import structlog

logger = structlog.get_logger()

# Kredi büyüme rejimi eşik sabitleri (%)
DEFAULT_CREDIT_REGIME_VERY_HIGH: float = 20.0
DEFAULT_CREDIT_REGIME_HIGH: float = 10.0
DEFAULT_CREDIT_REGIME_POSITIVE: float = 0.0
DEFAULT_CREDIT_REGIME_STAGNANT: float = -5.0
DEFAULT_CREDIT_TREND_THRESHOLD: float = 0.5


def compute_credit_features(credit_data: dict[str, Any]) -> dict[str, float]:
    """Kredi büyüme ve rejim göstergelerini hesaplar.

    Args:
        credit_data: Yıllık büyüme, kredi/GSYH oranı ve önceki büyüme verilerini içeren sözlük.

    Returns:
        dict[str, float]: Hesaplanmış kredi büyüme feature sözlüğü.

    Raises:
        ValueError: Sayısal dönüştürme hatası oluştuğunda (yakalanıp loglanır).
    """
    features: dict[str, float] = {}

    try:
        credit_growth = credit_data.get("credit_growth_yoy")
        if credit_growth is not None:
            features["credit_growth_yoy"] = round(float(credit_growth), 2)

            # Kredi rejimi
            growth = float(credit_growth)
            if growth > DEFAULT_CREDIT_REGIME_VERY_HIGH:
                features["credit_regime"] = 3.0  # ÇOK HIZLI
            elif growth > DEFAULT_CREDIT_REGIME_HIGH:
                features["credit_regime"] = 2.0  # HIZLI
            elif growth > DEFAULT_CREDIT_REGIME_POSITIVE:
                features["credit_regime"] = 1.0  # POZİTİF
            elif growth > DEFAULT_CREDIT_REGIME_STAGNANT:
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
            features["credit_trend_direction"] = (
                1.0 if trend > DEFAULT_CREDIT_TREND_THRESHOLD
                else (-1.0 if trend < -DEFAULT_CREDIT_TREND_THRESHOLD else 0.0)
            )

    except Exception as e:
        logger.error("Kredi feature hesaplaması başarısız oldu", error=str(e))

    return features


__all__ = [
    "DEFAULT_CREDIT_REGIME_VERY_HIGH",
    "DEFAULT_CREDIT_REGIME_HIGH",
    "DEFAULT_CREDIT_REGIME_POSITIVE",
    "DEFAULT_CREDIT_REGIME_STAGNANT",
    "DEFAULT_CREDIT_TREND_THRESHOLD",
    "compute_credit_features",
]

