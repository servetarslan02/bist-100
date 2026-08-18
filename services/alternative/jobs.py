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

from typing import Dict, Any
import structlog

logger = structlog.get_logger()


def compute_job_features(job_data: Dict[str, Any], ticker: str) -> Dict[str, float]:
    """İş ilanı feature'ları."""
    features = {}

    if not job_data:
        return features

    features["job_posting_growth"] = job_data.get("posting_growth", 0)
    features["tech_hiring_pct"] = job_data.get("tech_hiring_pct", 0)
    features["layoff_signal"] = 1.0 if job_data.get("layoff", False) else 0.0
    features["avg_salary_change"] = job_data.get("salary_change", 0)
    features["job_posting_count"] = float(job_data.get("posting_count", 0))
    features["job_remote_ratio"] = job_data.get("remote_ratio", 0)

    return features
