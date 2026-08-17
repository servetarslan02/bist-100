"""ALPHA BIST — Satellite Data Features."""
from typing import Dict, Any
import structlog
logger = structlog.get_logger()

def compute_satellite_features(sat_data: Dict[str, Any], ticker: str) -> Dict[str, float]:
    """Uydu verisi feature'ları."""
    features = {}
    features["factory_traffic_change"] = sat_data.get("factory_traffic", 0)
    features["store_traffic_change"] = sat_data.get("store_traffic", 0)
    features["parking_lot_occupancy"] = sat_data.get("parking_occupancy", 0)
    return features
