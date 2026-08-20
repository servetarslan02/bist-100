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

# === Base Infrastructure ===
from .base import (
    BaseAdapter, RateLimiter, CircuitBreaker, CircuitState,
    DataQualityValidator, QualityReport,
    AdapterRegistry, adapter_registry,
)

# === Adapters ===
from .google_trends import GoogleTrendsAdapter, google_trends_adapter
from .bkm_adapter import BKMAdapter, bkm_adapter
from .kariyer_net import KariyerNetAdapter, kariyer_net_adapter
from .eksi_sozluk import EksiSozlukAdapter, eksi_sozluk_adapter
from .investing_adapter import InvestingAdapter, investing_adapter
from .satellite_adapter import SatelliteAdapter, satellite_adapter

# === LLM Sentiment ===
from .llm_sentiment import LLMSentimentAnalyzer, llm_sentiment

# === Reconciliation ===
from .reconciliation import CrossSourceReconciler, ReconciliationReport, reconciler

# === Feature Store ===
from .feature_store import FeatureStore, FeatureManifest, feature_store

# === Feature Engine ===
from .feature_engine import AlternativeFeatureEngine, alt_feature_engine

# === Legacy Feature Functions (backward compatibility) ===
from .social import compute_social_features
from .jobs import compute_job_features
from .credit_card import compute_cc_features
from .satellite import compute_satellite_features
from .web_scraping import compute_web_features

__all__ = [
    # Base
    "BaseAdapter", "RateLimiter", "CircuitBreaker", "CircuitState",
    "DataQualityValidator", "QualityReport",
    "AdapterRegistry", "adapter_registry",
    # Adapters
    "GoogleTrendsAdapter", "google_trends_adapter",
    "BKMAdapter", "bkm_adapter",
    "KariyerNetAdapter", "kariyer_net_adapter",
    "EksiSozlukAdapter", "eksi_sozluk_adapter",
    "InvestingAdapter", "investing_adapter",
    "SatelliteAdapter", "satellite_adapter",
    # LLM
    "LLMSentimentAnalyzer", "llm_sentiment",
    # Reconciliation
    "CrossSourceReconciler", "ReconciliationReport", "reconciler",
    # Feature Store
    "FeatureStore", "FeatureManifest", "feature_store",
    # Feature Engine
    "AlternativeFeatureEngine", "alt_feature_engine",
    # Legacy
    "compute_social_features", "compute_job_features",
    "compute_cc_features", "compute_satellite_features",
    "compute_web_features",
]
