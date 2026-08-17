"""ALPHA BIST — Social Media Features."""
from typing import Dict, Any
import structlog
logger = structlog.get_logger()

def compute_social_features(social_data: Dict[str, Any], ticker: str) -> Dict[str, float]:
    """Sosyal medya feature'ları."""
    features = {}
    features["social_sentiment"] = social_data.get("sentiment", 0)
    features["social_volume"] = social_data.get("volume", 0)
    features["social_viral"] = 1.0 if social_data.get("viral", False) else 0.0
    features["social_positive_ratio"] = social_data.get("positive_ratio", 0.5)
    features["social_mention_count"] = social_data.get("mention_count", 0)
    return features
