"""
ALPHA BIST — Credit Card Spending Features v2.0

Kredi kartı harcama feature'ları.

Features:
- cc_spend_growth: Harcama büyüme oranı
- cc_vs_sector: Sektöre göre karşılaştırma
- cc_seasonal_deviation: Mevsimsel sapma
- cc_online_ratio: Online harcama oranı
- cc_transaction_count: İşlem sayısı
"""

from typing import Any

import structlog

logger = structlog.get_logger()


def compute_cc_features(cc_data: dict[str, Any], ticker: str) -> dict[str, float]:
    """Kredi kartı harcama feature'larını hesapla.

    Args:
        cc_data: Kredi kartı ham verisi (BKM veya diğer kaynaklardan).
        ticker: Hisse sembolü.

    Returns:
        Feature sözlüğü. Her değer float tipindedir.
    """
    features: dict[str, float] = {}

    if not cc_data:
        return features

    key_feature_map = {
        "spend_growth": "cc_spend_growth",
        "vs_sector": "cc_vs_sector",
        "seasonal_deviation": "cc_seasonal_deviation",
        "online_ratio": "cc_online_ratio",
        "transaction_count": "cc_transaction_count",
    }
    for key, feature_name in key_feature_map.items():
        value = cc_data.get(key)
        if value is not None:
            try:
                features[feature_name] = float(value)
            except (TypeError, ValueError):
                logger.debug("Skipping non-numeric value", feature=feature_name, value=value)

    return features
