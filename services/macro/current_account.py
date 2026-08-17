"""ALPHA BIST — Current Account Features."""
from typing import Dict, Any
import structlog
logger = structlog.get_logger()

def compute_ca_features(ca_data: Dict[str, Any]) -> Dict[str, float]:
    """Cari açık feature'ları."""
    features = {}
    features["ca_balance"] = ca_data.get("balance", 0)
    features["ca_trend"] = ca_data.get("trend", 0)
    features["ca_improving"] = 1.0 if ca_data.get("improving", False) else 0.0
    return features
