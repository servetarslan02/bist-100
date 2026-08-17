"""ALPHA BIST — Web Scraping Features."""
from typing import Dict, Any
import structlog
logger = structlog.get_logger()

def compute_web_features(scraped_data: Dict[str, Any], ticker: str) -> Dict[str, float]:
    """Web scraping feature'ları."""
    features = {}
    features["job_posting_growth"] = scraped_data.get("job_posting_growth", 0)
    features["review_count_growth"] = scraped_data.get("review_count_growth", 0)
    features["price_vs_competitors"] = scraped_data.get("price_vs_competitors", 0)
    features["web_traffic_change"] = scraped_data.get("web_traffic_change", 0)
    features["app_ranking_change"] = scraped_data.get("app_ranking_change", 0)
    return features
