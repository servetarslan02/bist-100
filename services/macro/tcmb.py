"""ALPHA BIST — TCMB Features."""
from typing import Dict, Any
import structlog
logger = structlog.get_logger()

def compute_tcmb_features(tcmb_data: Dict[str, Any]) -> Dict[str, float]:
    """TCMB faiz ve para politikası feature'ları."""
    features = {}
    features["policy_rate"] = tcmb_data.get("policy_rate", 0)
    features["real_rate"] = tcmb_data.get("policy_rate", 0) - tcmb_data.get("inflation", 0)
    features["rate_surprise"] = tcmb_data.get("actual_rate", 0) - tcmb_data.get("expected_rate", 0)
    features["policy_stance"] = 1.0 if features["real_rate"] > 0 else -1.0
    features["rate_change"] = tcmb_data.get("rate_change", 0)
    return features
