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
    """İş ilanı ve istihdam talebi ham verisinden kurumsal büyüme göstergelerini hesaplar.

    Hesaplanan Göstergeler:
    - job_posting_growth: İlan adedi büyüme hızı (%)
    - job_hiring_velocity: İstihdam ivmesi (aylık ilan artış hızındaki ivmelenme)
    - tech_hiring_pct: Mühendislik, Ar-Ge ve teknoloji pozisyon oranı (%)
    - avg_salary_change: Teklif edilen maaş değişim/enflasyon oranı (%)
    - layoff_signal: İşten çıkarma / tensikat riski sinyali (0 veya 1)
    - job_posting_count: Toplam aktif açık pozisyon sayısı
    - job_remote_ratio: Uzaktan / hibrit çalışma esnekliği oranı
    - job_expansion_ratio: Yeni pozisyon / büyüme odaklı işe alım oranı
    - job_retention_score: Tahmini çalışan bağlılığı / elde tutma skoru (0-1)
    - job_headcount_regime: 0 (Küçülme/Tensikat), 1 (Dondurma), 2 (Normal), 3 (Agresif Büyüme)

    Args:
        job_data: Kariyer portalları veya şirket istihdam verilerini içeren sözlük.
        ticker: İlgili BIST hisse sembolü.

    Returns:
        dict[str, float]: Hesaplanmış kurumsal istihdam göstergeleri sözlüğü.
    """
    features: dict[str, float] = {}

    if not job_data:
        return features

    try:
        # 1. İlan Sayısı ve Büyüme Hızı
        count_val = job_data.get("posting_count") or job_data.get("job_posting_count")
        if count_val is not None:
            features["job_posting_count"] = round(float(count_val), 0)

        growth_val = job_data.get("posting_growth") or job_data.get("job_posting_growth")
        if growth_val is not None:
            features["job_posting_growth"] = round(float(growth_val), 2)

        # 2. İşe Alım İvmesi (Hiring Velocity)
        prev_growth = job_data.get("prev_posting_growth")
        if growth_val is not None and prev_growth is not None:
            features["job_hiring_velocity"] = round(float(growth_val) - float(prev_growth), 2)

        # 3. Teknoloji ve Ar-Ge Pozisyon Yoğunluğu
        tech_val = job_data.get("tech_hiring_pct")
        if tech_val is not None:
            features["tech_hiring_pct"] = round(float(tech_val), 4)

        # 4. Maaş Değişimi ve Maliyet Baskısı
        salary_val = job_data.get("salary_change") or job_data.get("avg_salary_change")
        if salary_val is not None:
            features["avg_salary_change"] = round(float(salary_val), 2)

        # 5. Uzaktan Çalışma Oranı
        remote_val = job_data.get("remote_ratio") or job_data.get("job_remote_ratio")
        if remote_val is not None:
            features["job_remote_ratio"] = round(float(remote_val), 4)

        # 6. Büyüme vs Ayrılanın Yerini Doldurma Oranı (Expansion vs Replacement)
        expansion_val = job_data.get("expansion_ratio") or job_data.get("job_expansion_ratio")
        if expansion_val is not None:
            features["job_expansion_ratio"] = round(float(expansion_val), 4)

        # 7. Çalışan Elde Tutma Skoru
        retention_val = job_data.get("retention_score") or job_data.get("job_retention_score")
        if retention_val is not None:
            features["job_retention_score"] = round(max(0.0, min(1.0, float(retention_val))), 4)

        # 8. İşten Çıkarma / Tensikat Sinyali
        layoff_val = job_data.get("layoff") or job_data.get("layoff_signal")
        if layoff_val is not None:
            is_layoff = 1.0 if layoff_val is True or layoff_val in (1, "1", "true", "TRUE") else 0.0
            features["layoff_signal"] = is_layoff

        # 9. İstihdam Rejimi
        is_layoff_flag = features.get("layoff_signal", 0.0) == 1.0
        growth = features.get("job_posting_growth", 0.0)

        if is_layoff_flag or growth < -25.0:
            regime = 0.0  # TENSİKAT / KÜÇÜLME REJİMİ
        elif growth < -5.0:
            regime = 1.0  # İSTİHDAM DONDURMA / DOĞAL ERİME
        elif growth < 20.0:
            regime = 2.0  # DENGELİ / RUTİN İSTİHDAM
        else:
            regime = 3.0  # AGRESİF KAPASİTE ARTIŞI / BÜYÜME

        features["job_headcount_regime"] = regime

    except Exception as e:
        logger.error("İş ilanı gösterge hesaplaması başarısız oldu", ticker=ticker, error=str(e))

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
                logger.warning("Özel iş ilanı sağlayıcısı hatası", ticker=ticker, error=str(e))
                return None

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


jobs_adapter = JobPostingAdapter()

