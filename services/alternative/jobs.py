"""
ALPHA BIST — Job Posting Features & Adapter v2.0

İş ilanı ve istihdam talebi feature'ları ve kurumsal adapter altyapısı.
Kariyer portalları, LinkedIn, şirket kariyer sayfaları ve sektör istihdam trendlerini işler.

Features:
- job_posting_growth: İlan büyüme oranı
- tech_hiring_pct: Teknik pozisyon oranı
- layoff_signal: İşten çıkarma sinyali
- avg_salary_change: Maaş değişim oranı
- job_posting_count: İlan sayısı
- job_remote_ratio: Uzaktan çalışma oranı
- job_retention_score: Tahmini çalışan elde tutma skoru
"""

from __future__ import annotations

from typing import Any

import structlog

from .base import BaseAdapter

logger = structlog.get_logger(__name__)

__all__ = [
    "JobPostingAdapter",
    "compute_job_features",
    "jobs_adapter",
]


def compute_job_features(job_data: dict[str, Any], ticker: str) -> dict[str, float]:
    """İş ilanı feature'larını hesapla.

    Geriye dönük uyumluluk ve hızlı hesaplama fonksiyonu.

    Args:
        job_data: İş ilanı ham verisi (Kariyer.net veya diğer kaynaklardan).
        ticker: Hisse sembolü.

    Returns:
        Feature sözlüğü. Her değer float tipindedir.
    """
    features: dict[str, float] = {}

    if not job_data:
        return features

    key_feature_map = {
        "posting_growth": "job_posting_growth",
        "tech_hiring_pct": "tech_hiring_pct",
        "salary_change": "avg_salary_change",
        "posting_count": "job_posting_count",
        "remote_ratio": "job_remote_ratio",
        "retention_score": "job_retention_score",
    }
    for key, feature_name in key_feature_map.items():
        value = job_data.get(key)
        if value is not None:
            try:
                features[feature_name] = float(value)
            except (TypeError, ValueError):
                logger.debug("Skipping non-numeric value", feature=feature_name, value=value)

    # İşten çıkarma sinyali
    layoff_val = job_data.get("layoff")
    if layoff_val is not None:
        features["layoff_signal"] = 1.0 if layoff_val is True or layoff_val == 1 else 0.0
    elif "layoff_signal" in job_data:
        try:
            features["layoff_signal"] = float(job_data["layoff_signal"])
        except (TypeError, ValueError):
            features["layoff_signal"] = 0.0

    return features


class JobPostingAdapter(BaseAdapter):
    """Kurumsal İş İlanı ve İstihdam Dinamikleri Adapter'ı.

    BaseAdapter altyapısını miras alarak rate limiting, circuit breaking,
    kalite kontrolleri ve cache desteği sunar.
    """

    source_name: str = "jobs"
    rate_limit: int = 30

    def __init__(self, data_provider: Any = None):
        """JobPostingAdapter başlat.

        Args:
            data_provider: Harici iş ilanı veri sağlayıcısı (opsiyonel).
        """
        super().__init__()
        self._data_provider = data_provider

    async def collect(self, ticker: str, **kwargs) -> dict[str, Any] | None:
        """İş ilanı verisi topla.

        Args:
            ticker: Hisse sembolü.
            **kwargs: Ek arama parametreleri (departman, tarih vb.).

        Returns:
            Ham iş ilanı verisi sözlüğü veya veri yoksa None.
        """
        if self._data_provider and hasattr(self._data_provider, "get_job_postings"):
            try:
                data = await self._data_provider.get_job_postings(ticker=ticker, **kwargs)
                if isinstance(data, dict):
                    return data
            except Exception as e:
                logger.warning("Custom job data provider error", ticker=ticker, error=str(e))
                return None

        # Harici sağlayıcı yoksa sahte veri üretme, None dön
        return None

    def compute_features(self, data: dict[str, Any], ticker: str) -> dict[str, float]:
        """Ham iş verisinden feature'ları hesapla.

        Args:
            data: Ham iş verisi.
            ticker: Hisse sembolü.

        Returns:
            Hesaplanan feature sözlüğü.
        """
        return compute_job_features(data, ticker)

    def __repr__(self) -> str:
        return f"JobPostingAdapter(source={self.source_name!r}, rate_limit={self.rate_limit})"


# Singleton instance
jobs_adapter = JobPostingAdapter()
