"""ALPHA BIST — Credit Card Spending Features."""
from typing import Dict, Any
import structlog
logger = structlog.get_logger()

def compute_cc_features(cc_data: Dict[str, Any], ticker: str) -> Dict[str, float]:
    """Kredi kartı harcama feature'ları."""
    features = {}
    features["cc_spend_growth"] = cc_data.get("spend_growth", 0)
    features["cc_vs_sector"] = cc_data.get("vs_sector", 0)
    features["cc_seasonal_deviation"] = cc_data.get("seasonal_deviation", 0)
    return features
