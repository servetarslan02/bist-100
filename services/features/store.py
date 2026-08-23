"""
ALPHA BIST — Real Feature Store
Redis ve bellek üzerinden anlık canlı öznitelikleri depolar ve sorgular.
"""

from typing import Dict, Any, Optional
import structlog
from services.core.redis_helper import get_cached, set_cached

logger = structlog.get_logger()

class FeatureStore:
    """Canlı Feature Store erişim katmanı."""
    
    def get_all(self, ticker: str) -> Dict[str, float]:
        """Hisseye ait tüm güncel öznitelikleri getir."""
        cached = get_cached(f"features:{ticker}")
        if cached and isinstance(cached, dict):
            return {k: float(v) for k, v in cached.items() if isinstance(v, (int, float, str))}
        return {}

    def set_features(self, ticker: str, features: Dict[str, float], ttl: int = 3600):
        """Öznitelikleri kaydet."""
        if features:
            set_cached(f"features:{ticker}", features, ttl=ttl)

feature_store = FeatureStore()
