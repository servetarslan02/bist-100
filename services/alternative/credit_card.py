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

from typing import Dict, Any
import structlog

logger = structlog.get_logger()


def compute_cc_features(cc_data: Dict[str, Any], ticker: str) -> Dict[str, float]:
    """Kredi kartı harcama feature'ları."""
    features = {}

    if not cc_data:
        return features

    features["cc_spend_growth"] = cc_data.get("spend_growth", 0)
    features["cc_vs_sector"] = cc_data.get("vs_sector", 0)
    features["cc_seasonal_deviation"] = cc_data.get("seasonal_deviation", 0)
    features["cc_online_ratio"] = cc_data.get("online_ratio", 0)
    features["cc_transaction_count"] = float(cc_data.get("transaction_count", 0))

    return features
