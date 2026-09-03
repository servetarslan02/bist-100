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

from typing import Any

import structlog

logger = structlog.get_logger()


def compute_web_features(scraped_data: dict[str, Any], ticker: str) -> dict[str, float]:
    """Web scraping feature'larını hesapla.

    Args:
        scraped_data: Web scraping ham verisi.
        ticker: Hisse sembolü.

    Returns:
        Feature sözlüğü. Her değer float tipindedir.
    """
    features: dict[str, float] = {}

    if not scraped_data:
        return features

    feature_keys = [
        "web_traffic_change",
        "app_ranking_change",
        "review_count_growth",
        "price_vs_competitors",
        "job_posting_growth",
        "search_volume_change",
    ]
    for key in feature_keys:
        value = scraped_data.get(key)
        if value is not None:
            try:
                features[key] = float(value)
            except (TypeError, ValueError):
                logger.debug("Skipping non-numeric value", feature=key, value=value)

    return features
