"""ALPHA BIST — Inflation Features."""
from typing import Dict, Any
import structlog
logger = structlog.get_logger()

def compute_inflation_features(inflation_data: Dict[str, Any]) -> Dict[str, float]:
    """Enflasyon feature'ları."""
    features = {}
    features["cpi_yoy"] = inflation_data.get("cpi_yoy", 0)
    features["ppi_yoy"] = inflation_data.get("ppi_yoy", 0)
    features["core_cpi"] = inflation_data.get("core_cpi", 0)
    features["ppi_cpi_spread"] = features["ppi_yoy"] - features["cpi_yoy"]
    features["inflation_trend"] = inflation_data.get("trend", 0)
    return features
