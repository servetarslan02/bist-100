"""
ALPHA BIST — Job Posting Features v2.0

İş ilanı feature'ları.

Features:
- job_posting_growth: İlan büyüme oranı
- tech_hiring_pct: Teknik pozisyon oranı
- layoff_signal: İşten çıkarma sinyali
- avg_salary_change: Maaş değişim oranı
- job_posting_count: İlan sayısı
- job_remote_ratio: Uzaktan çalışma oranı
"""

from typing import Any

import structlog

logger = structlog.get_logger()


def compute_job_features(job_data: dict[str, Any], ticker: str) -> dict[str, float]:
    """İş ilanı feature'larını hesapla.

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
    }
    for key, feature_name in key_feature_map.items():
        value = job_data.get(key)
        if value is not None:
            try:
                features[feature_name] = float(value)
            except (TypeError, ValueError):
                logger.debug("Skipping non-numeric value", feature=feature_name, value=value)

    features["layoff_signal"] = 1.0 if job_data.get("layoff", False) else 0.0

    return features
