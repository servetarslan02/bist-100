"""ALPHA BIST — Job Posting Features."""
from typing import Dict, Any
import structlog
logger = structlog.get_logger()

def compute_job_features(job_data: Dict[str, Any], ticker: str) -> Dict[str, float]:
    """İş ilanı feature'ları."""
    features = {}
    features["job_posting_growth"] = job_data.get("posting_growth", 0)
    features["tech_hiring_pct"] = job_data.get("tech_hiring_pct", 0)
    features["layoff_signal"] = 1.0 if job_data.get("layoff", False) else 0.0
    features["avg_salary_change"] = job_data.get("salary_change", 0)
    return features
