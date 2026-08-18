"""
ALPHA BIST — Web Scraping Features v2.0

Web scraping feature'ları.

Features:
- web_traffic_change: Web trafiği değişim
- app_ranking_change: Uygulama sıralaması değişim
- review_count_growth: Yorum sayısı büyüme
- price_vs_competitors: Rakiplere göre fiyat
- job_posting_growth: İlan büyüme (web scraping)
- search_volume_change: Arama hacmi değişim
"""

from typing import Dict, Any
import structlog

logger = structlog.get_logger()


def compute_web_features(scraped_data: Dict[str, Any], ticker: str) -> Dict[str, float]:
    """Web scraping feature'ları."""
    features = {}

    if not scraped_data:
        return features

    features["web_traffic_change"] = scraped_data.get("web_traffic_change", 0)
    features["app_ranking_change"] = scraped_data.get("app_ranking_change", 0)
    features["review_count_growth"] = scraped_data.get("review_count_growth", 0)
    features["price_vs_competitors"] = scraped_data.get("price_vs_competitors", 0)
    features["job_posting_growth"] = scraped_data.get("job_posting_growth", 0)
    features["search_volume_change"] = scraped_data.get("search_volume_change", 0)

    return features
