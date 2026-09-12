"""
ALPHA BIST — Web Scraping Features & Adapter v2.0

Web trafiği, mobil uygulama metrikleri, müşteri yorumları ve fiyat rekabeti adapter altyapısı.
E-ticaret, web analytics ve dijital ayak izi verilerini işler.

Features:
- web_traffic_change: Web trafiği değişim oranı
- app_ranking_change: Uygulama mağaza sıralaması değişimi
- review_count_growth: Müşteri yorum sayısı büyüme hızı
- price_vs_competitors: Rakiplere göre fiyat endeksi
- job_posting_growth: İlan büyüme oranı
- search_volume_change: Arama motoru hacim değişimi
- web_bounce_rate_change: Hemen çıkma oranı değişimi
- web_avg_duration_change: Ortalama oturum süresi değişimi
"""

from __future__ import annotations

from typing import Any

import structlog

from .base import BaseAdapter

logger = structlog.get_logger(__name__)

__all__ = [
    "WebScrapingAdapter",
    "compute_web_features",
    "web_scraping_adapter",
]


def compute_web_features(scraped_data: dict[str, Any], ticker: str) -> dict[str, float]:
    """Web scraping ham verisinden feature'ları hesapla.

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
        "web_bounce_rate_change",
        "web_avg_duration_change",
    ]
    for key in feature_keys:
        value = scraped_data.get(key)
        if value is not None:
            try:
                features[key] = float(value)
            except (TypeError, ValueError):
                logger.debug("Skipping non-numeric value", feature=key, value=value)

    return features


class WebScrapingAdapter(BaseAdapter):
    """Kurumsal Web Scraping ve Dijital Ayak İzi Adapter'ı.

    BaseAdapter ile rate limit, circuit breaker ve veri kalite kontrolü sağlar.
    """

    source_name: str = "web_scraping"
    rate_limit: int = 20

    def __init__(self, data_provider: Any = None):
        """WebScrapingAdapter başlat.

        Args:
            data_provider: Harici web veri sağlayıcısı (opsiyonel).
        """
        super().__init__()
        self._data_provider = data_provider

    async def collect(self, ticker: str, **kwargs) -> dict[str, Any] | None:
        """Web scraping ve dijital ayak izi verisi topla.

        Args:
            ticker: Hisse sembolü.
            **kwargs: Ek scraping parametreleri.

        Returns:
            Ham veri sözlüğü veya veri yoksa None.
        """
        if self._data_provider and hasattr(self._data_provider, "get_web_metrics"):
            try:
                data = await self._data_provider.get_web_metrics(ticker=ticker, **kwargs)
                if isinstance(data, dict):
                    return data
            except Exception as e:
                logger.warning("Custom web metrics provider error", ticker=ticker, error=str(e))
                return None

        # Mock / sahte veri kesinlikle üretilmez
        return None

    def compute_features(self, data: dict[str, Any], ticker: str) -> dict[str, float]:
        """Ham web verisinden feature hesapla.

        Args:
            data: Ham scraping verisi.
            ticker: Hisse sembolü.

        Returns:
            Hesaplanan feature sözlüğü.
        """
        return compute_web_features(data, ticker)

    def __repr__(self) -> str:
        return f"WebScrapingAdapter(source={self.source_name!r}, rate_limit={self.rate_limit})"


# Singleton instance
web_scraping_adapter = WebScrapingAdapter()
