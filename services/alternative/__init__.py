"""
ALPHA BIST — Alternative Data Package v2.0

Tüm alternative data modülleri.

Modüller:
- base: Temel altyapı (BaseAdapter, RateLimiter, CircuitBreaker, DataQuality, DuckDB export)
- google_trends: Google Trends adapter
- bkm_adapter: BKM kredi kartı adapter
- kariyer_net: Kariyer.net iş ilanı adapter
- eksi_sozluk: Ekşi Sözlük sentiment adapter
- llm_sentiment: LLM Türkçe sentiment analizi
- feature_engine: Feature hesaplama motoru (60+ feature)
- social: Sosyal medya feature'ları ve adapter
- jobs: İş ilanı feature'ları ve adapter
- credit_card: Kredi kartı feature'ları ve adapter
- satellite: Uydu verisi feature'ları ve adapter
- web_scraping: Web scraping feature'ları ve adapter
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
    export_alternative_features_to_duckdb,
)
from .bkm_adapter import BKMAdapter, bkm_adapter
from .credit_card import CreditCardAdapter, compute_cc_features, credit_card_adapter
from .eksi_sozluk import EksiSozlukAdapter, eksi_sozluk_adapter

# === Feature Engine ===
from .feature_engine import AlternativeFeatureEngine, alt_feature_engine

# === Feature Store ===
from .feature_store import FeatureManifest, FeatureStore, feature_store

# === Real-Time News & Central Bank ===
from .fomc_scraper import (
    CBEvent,
    CBEventType,
    CBTextAnalyzer,
    CentralBank,
    CentralBankScraperService,
    cb_service,
)

# === Adapters ===
from .google_trends import GoogleTrendsAdapter, google_trends_adapter
from .investing_adapter import InvestingAdapter, investing_adapter
from .jobs import JobPostingAdapter, compute_job_features, jobs_adapter
from .kariyer_net import KariyerNetAdapter, kariyer_net_adapter

# === LLM Sentiment ===
from .llm_sentiment import LLMSentimentAnalyzer, llm_sentiment
from .news_realtime import (
    KeywordSentimentScorer,
    NewsItem,
    NewsSource,
    RealTimeNewsFeed,
    TickerExtractor,
    news_feed,
)

# === Reconciliation ===
from .reconciliation import CrossSourceReconciler, ReconciliationReport, reconciler
from .satellite_adapter import SatelliteAdapter, compute_satellite_features, satellite_adapter
from .social import SocialMediaAdapter, compute_social_features, social_adapter
from .web_scraping import WebScrapingAdapter, compute_web_features, web_scraping_adapter

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
    "export_alternative_features_to_duckdb",
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
    "CreditCardAdapter",
    "credit_card_adapter",
    "JobPostingAdapter",
    "jobs_adapter",
    "SocialMediaAdapter",
    "social_adapter",
    "WebScrapingAdapter",
    "web_scraping_adapter",
    # LLM
    "LLMSentimentAnalyzer",
    "llm_sentiment",
    # Real-Time News & Central Bank
    "RealTimeNewsFeed",
    "NewsItem",
    "NewsSource",
    "KeywordSentimentScorer",
    "TickerExtractor",
    "news_feed",
    "CentralBankScraperService",
    "CBEvent",
    "CBEventType",
    "CentralBank",
    "CBTextAnalyzer",
    "cb_service",
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
    # Functions
    "compute_social_features",
    "compute_job_features",
    "compute_cc_features",
    "compute_satellite_features",
    "compute_web_features",
]
