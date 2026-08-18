"""
ALPHA BIST — Social Media Features v2.0

Sosyal medya feature'ları.
BaseAdapter.extend ile uyumlu.

Features:
- social_sentiment: Sentiment skoru (-1 ile +1)
- social_volume: Sosyal medya hacmi
- social_viral: Viral sinyal (0 veya 1)
- social_positive_ratio: Pozitif oran
- social_mention_count: Bahsedilme sayısı
- social_engagement: Engagement oranı
- social_sentiment_momentum: Sentiment değişim hızı
- social_platform_breakdown: Platform bazlı dağılım
- social_manipulation_score: Manipülasyon skoru
"""

from typing import Dict, Any
import structlog

logger = structlog.get_logger()


def compute_social_features(social_data: Dict[str, Any], ticker: str) -> Dict[str, float]:
    """Sosyal medya feature'ları.

    Args:
        social_data: Sosyal medya verisi
        ticker: Hisse kodu

    Returns:
        Feature dict
    """
    features = {}

    if not social_data:
        return features

    # Temel feature'lar
    features["social_sentiment"] = _clamp(social_data.get("sentiment", 0), -1, 1)
    features["social_volume"] = float(social_data.get("volume", 0))
    features["social_viral"] = 1.0 if social_data.get("viral", False) else 0.0
    features["social_positive_ratio"] = _clamp(social_data.get("positive_ratio", 0.5), 0, 1)
    features["social_mention_count"] = float(social_data.get("mention_count", 0))

    # Gelişmiş feature'lar
    features["social_engagement"] = _clamp(social_data.get("engagement", 0), 0, 1)
    features["social_sentiment_momentum"] = social_data.get("sentiment_momentum", 0)
    features["social_manipulation_score"] = _clamp(social_data.get("manipulation_score", 0), 0, 1)

    # Platform bazlı
    platforms = social_data.get("platforms", {})
    for platform in ["twitter", "reddit", "eksi", "investing"]:
        if platform in platforms:
            plat_data = platforms[platform]
            features[f"social_{platform}_sentiment"] = _clamp(plat_data.get("sentiment", 0), -1, 1)
            features[f"social_{platform}_volume"] = float(plat_data.get("volume", 0))

    return features


def _clamp(value: float, min_val: float, max_val: float) -> float:
    """Değeri sınırla."""
    return max(min_val, min(max_val, float(value)))
