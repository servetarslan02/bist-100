"""ALPHA BIST — Credit Features."""
from typing import Dict, Any
import structlog
logger = structlog.get_logger()

def compute_credit_features(credit_data: Dict[str, Any]) -> Dict[str, float]:
    """Kredi büyüme feature'ları."""
    features = {}
    features["credit_growth_yoy"] = credit_data.get("growth_yoy", 0)
    features["credit_gdp_ratio"] = credit_data.get("gdp_ratio", 0)
    features["credit_trend"] = credit_data.get("trend", 0)
    return features
