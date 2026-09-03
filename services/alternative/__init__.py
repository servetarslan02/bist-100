"""
ALPHA BIST — Alternative Data Package v2.0

Tüm alternative data modülleri.

Modüller:
- base: Temel altyapı (BaseAdapter, RateLimiter, CircuitBreaker, DataQuality)
- google_trends: Google Trends adapter
- bkm_adapter: BKM kredi kartı adapter
- kariyer_net: Kariyer.net iş ilanı adapter
- eksi_sozluk: Ekşi Sözlük sentiment adapter
- llm_sentiment: LLM Türkçe sentiment analizi
- feature_engine: Feature hesaplama motoru (60+ feature)
- social: Sosyal medya feature'ları (mevcut)
- jobs: İş ilanı feature'ları (mevcut)
- credit_card: Kredi kartı feature'ları (mevcut)
- satellite: Uydu verisi feature'ları (mevcut)
- web_scraping: Web scraping feature'ları (mevcut)
"""

__version__ = "2.0.0"

# === Base Infrastructure ===
from .base import (
    AdapterRegistry,
    BaseAdapter,
    CircuitBreaker,
    CircuitState,
    DataQualityValidator,
    QualityReport,
    RateLimiter,
    adapter_registry,
)
from .bkm_adapter import BKMAdapter, bkm_adapter
from .credit_card import compute_cc_features
from .eksi_sozluk import EksiSozlukAdapter, eksi_sozluk_adapter

# === Feature Engine ===
from .feature_engine import AlternativeFeatureEngine, alt_feature_engine

# === Feature Store ===
from .feature_store import FeatureManifest, FeatureStore, feature_store

# === Adapters ===
from .google_trends import GoogleTrendsAdapter, google_trends_adapter
from .jobs import compute_job_features
from .kariyer_net import KariyerNetAdapter, kariyer_net_adapter

# === LLM Sentiment ===
from .llm_sentiment import LLMSentimentAnalyzer, llm_sentiment

# === Reconciliation ===
from .reconciliation import CrossSourceReconciler, ReconciliationReport, reconciler

# === Legacy Feature Functions (backward compatibility) ===
# Lazy import: nadiren kullanılan modüller __getattr__ ile yüklenir
_LAZY_IMPORTS = {
    "compute_social_features": (".social", "compute_social_features"),
    "compute_web_features": (".web_scraping", "compute_web_features"),
    "InvestingAdapter": (".investing_adapter", "InvestingAdapter"),
    "investing_adapter": (".investing_adapter", "investing_adapter"),
    "SatelliteAdapter": (".satellite_adapter", "SatelliteAdapter"),
    "satellite_adapter": (".satellite_adapter", "satellite_adapter"),
    "compute_satellite_features": (".satellite_adapter", "compute_satellite_features"),
}


def __getattr__(name: str):
    """Nadiren kullanılan adapter'lar için lazy import."""
    if name in _LAZY_IMPORTS:
        module_path, attr_name = _LAZY_IMPORTS[name]
        import importlib
        module = importlib.import_module(module_path, __package__)
        return getattr(module, attr_name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    # Base
    "BaseAdapter",
    "RateLimiter",
    "CircuitBreaker",
    "CircuitState",
    "DataQualityValidator",
    "QualityReport",
    "AdapterRegistry",
    "adapter_registry",
    # Adapters
    "GoogleTrendsAdapter",
    "google_trends_adapter",
    "BKMAdapter",
    "bkm_adapter",
    "KariyerNetAdapter",
    "kariyer_net_adapter",
    "EksiSozlukAdapter",
    "eksi_sozluk_adapter",
    "InvestingAdapter",
    "investing_adapter",
    "SatelliteAdapter",
    "satellite_adapter",
    # LLM
    "LLMSentimentAnalyzer",
    "llm_sentiment",
    # Reconciliation
    "CrossSourceReconciler",
    "ReconciliationReport",
    "reconciler",
    # Feature Store
    "FeatureStore",
    "FeatureManifest",
    "feature_store",
    # Feature Engine
    "AlternativeFeatureEngine",
    "alt_feature_engine",
    # Legacy
    "compute_social_features",
    "compute_job_features",
    "compute_cc_features",
    "compute_satellite_features",
    "compute_web_features",
]
