"""ALPHA BIST — CDS Features."""
from typing import Dict, Any
import structlog
logger = structlog.get_logger()

def compute_cds_features(cds_data: Dict[str, Any]) -> Dict[str, float]:
    """CDS spread feature'ları."""
    features = {}
    features["cds_5y"] = cds_data.get("cds_5y", 0)
    features["cds_change"] = cds_data.get("cds_change", 0)
    features["risk_level"] = 1.0 if features["cds_5y"] > 400 else (0.5 if features["cds_5y"] > 200 else 0.0)
    return features
