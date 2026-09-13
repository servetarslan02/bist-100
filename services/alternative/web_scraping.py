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


def _safe_float(val: Any) -> float | None:
    """Değeri güvenli float'a çevirir, geçersiz string veya NaN/Inf durumunda None döndürür."""
    if val is None:
        return None
    try:
        f = float(val)
        import math
        return None if (math.isnan(f) or math.isinf(f)) else f
    except (ValueError, TypeError):
        return None


def compute_web_features(scraped_data: dict[str, Any], ticker: str) -> dict[str, float]:
    """Web scraping ham verisinden kurumsal düzeyde dijital ayak izi feature'larını hesapla.

    Hesaplanan Metrikler:
    - web_traffic_change: Web trafiği aylık değişim oranı (%)
    - web_traffic_velocity: Trafik büyüme ivmesi (ikinci türev)
    - search_volume_change: Organik arama hacmi değişimi (%)
    - digital_traffic_momentum: Arama ve web trafiği bileşik momentumu
    - web_bounce_rate_change: Hemen çıkma oranı değişimi (%)
    - web_avg_duration_change: Ortalama oturum süresi değişimi (%)
    - web_engagement_quality_index: Kalite endeksi (süre artışı - hemen çıkma artışı)
    - app_ranking_change: Mobil uygulama mağaza sıralama kazanımı
    - review_count_growth: Müşteri değerlendirme büyüme hızı (%)
    - app_virality_score: Mobil mağaza sıralama ve yorum ivmesi bileşik skoru
    - price_vs_competitors: Rakiplere göre fiyat endeksi (100 baz)
    - job_posting_growth: Dijital ilan büyüme oranı (%)
    - digital_footprint_composite_score: 0-100 arası normalize edilmiş dijital sağlık skoru

    Args:
        scraped_data: Web scraping ham verisi.
        ticker: Hisse sembolü.

    Returns:
        Feature sözlüğü. Her değer float tipindedir.
    """
    features: dict[str, float] = {}

    if not scraped_data:
        return features

    try:
        # 1. Web Trafiği ve İvmesi
        traffic_change = _safe_float(scraped_data.get("web_traffic_change") or scraped_data.get("traffic_growth"))
        if traffic_change is not None:
            features["web_traffic_change"] = round(traffic_change, 2)
            prev_traffic = _safe_float(scraped_data.get("prev_web_traffic_change"))
            if prev_traffic is not None:
                features["web_traffic_velocity"] = round(traffic_change - prev_traffic, 2)

        # 2. Arama Motoru İlgisi ve Bileşik Trafik Momentumu
        search_change = _safe_float(scraped_data.get("search_volume_change") or scraped_data.get("search_growth"))
        if search_change is not None:
            features["search_volume_change"] = round(search_change, 2)
            if traffic_change is not None:
                # %60 fiili web trafiği, %40 arama niyeti momentumu
                momentum = 0.60 * traffic_change + 0.40 * search_change
                features["digital_traffic_momentum"] = round(momentum, 2)

        # 3. Kullanıcı Etkileşimi ve Kalite Endeksi
        bounce_change = _safe_float(scraped_data.get("web_bounce_rate_change") or scraped_data.get("bounce_change"))
        if bounce_change is not None:
            features["web_bounce_rate_change"] = round(bounce_change, 2)

        duration_change = _safe_float(scraped_data.get("web_avg_duration_change") or scraped_data.get("duration_change"))
        if duration_change is not None:
            features["web_avg_duration_change"] = round(duration_change, 2)

        if duration_change is not None and bounce_change is not None:
            # Süre uzaması pozitif (+), hemen çıkma artışı negatif (-) etki
            quality_idx = duration_change - bounce_change
            features["web_engagement_quality_index"] = round(quality_idx, 2)

        # 4. Mobil Uygulama ve Virallik
        app_rank = _safe_float(scraped_data.get("app_ranking_change") or scraped_data.get("app_rank_delta"))
        if app_rank is not None:
            features["app_ranking_change"] = round(app_rank, 2)

        review_growth = _safe_float(scraped_data.get("review_count_growth") or scraped_data.get("review_growth"))
        if review_growth is not None:
            features["review_count_growth"] = round(review_growth, 2)

        if app_rank is not None and review_growth is not None:
            virality = (app_rank * 2.0) + review_growth
            features["app_virality_score"] = round(virality, 2)

        # 5. Fiyat Rekabet Gücü ve İlanlar
        price_idx = _safe_float(scraped_data.get("price_vs_competitors") or scraped_data.get("price_index"))
        if price_idx is not None:
            features["price_vs_competitors"] = round(price_idx, 2)

        job_growth = _safe_float(scraped_data.get("job_posting_growth") or scraped_data.get("job_growth"))
        if job_growth is not None:
            features["job_posting_growth"] = round(job_growth, 2)

        # 6. Dijital Ayak İzi Bileşik Sağlık Skoru (0 - 100 bazında)
        score_components = []
        if "digital_traffic_momentum" in features:
            # -20 ile +20 arasını 0-100'e normalize et
            score_components.append(max(0.0, min(100.0, 50.0 + features["digital_traffic_momentum"] * 2.5)))
        elif "web_traffic_change" in features:
            score_components.append(max(0.0, min(100.0, 50.0 + features["web_traffic_change"] * 2.5)))

        if "web_engagement_quality_index" in features:
            score_components.append(max(0.0, min(100.0, 50.0 + features["web_engagement_quality_index"] * 2.5)))

        if "app_virality_score" in features:
            score_components.append(max(0.0, min(100.0, 50.0 + features["app_virality_score"] * 1.5)))

        if score_components:
            features["digital_footprint_composite_score"] = round(sum(score_components) / len(score_components), 2)

    except Exception as e:
        logger.warning("Error calculating web features", ticker=ticker, error=str(e))

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
