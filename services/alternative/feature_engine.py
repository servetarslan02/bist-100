"""
ALPHA BIST — Alternative Data Feature Engine v1.0

Tüm alternative data kaynaklarından feature hesaplama.
60+ feature üretir.

Kaynaklar:
1. Google Trends (9 feature)
2. BKM Credit Card (8 feature)
3. Kariyer.net Jobs (5+ feature)
4. Ekşi Sözlük (8 feature)
5. Investing.com (5+ feature)
6. LLM Sentiment (5+ feature)
7. Social Media (10+ feature)
8. Web Scraping (5+ feature)
"""

import asyncio
import time
from typing import Dict, Any, Optional, List
from datetime import datetime, timezone
import structlog

from .base import adapter_registry, BaseAdapter
from .google_trends import google_trends_adapter
from .bkm_adapter import bkm_adapter
from .kariyer_net import kariyer_net_adapter
from .eksi_sozluk import eksi_sozluk_adapter
from .investing_adapter import investing_adapter
from .llm_sentiment import llm_sentiment
from .reconciliation import reconciler
from .feature_store import feature_store

logger = structlog.get_logger()


class AlternativeFeatureEngine:
    """Alternative data feature engine.

    Tüm kaynakları orkestre eder, feature'ları birleştirir.
    """

    def __init__(self, llm_client=None):
        self._initialized = False
        self._feature_cache: Dict[str, Dict[str, float]] = {}

        # LLM client'ı sentiment analyzer'a bağla
        if llm_client:
            llm_sentiment.set_llm_client(llm_client)

    def initialize(self):
        """Adapter'ları kaydet."""
        if self._initialized:
            return

        adapter_registry.register(google_trends_adapter)
        adapter_registry.register(bkm_adapter)
        adapter_registry.register(kariyer_net_adapter)
        adapter_registry.register(eksi_sozluk_adapter)
        adapter_registry.register(investing_adapter)

        self._initialized = True
        logger.info(
            "Alternative Feature Engine initialized",
            adapters=adapter_registry.list_adapters(),
        )

    async def compute_all_features(
        self,
        ticker: str,
        sources: Optional[List[str]] = None,
        sector: Optional[str] = None,
        extra_data: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, float]:
        """Tüm alternative data kaynaklarından feature hesapla.

        Args:
            ticker: Hisse kodu
            sources: Kullanılacak kaynaklar (None = tümü)
            sector: Sektör adı
            extra_data: Ek veri (KAP, haber vb.)

        Returns:
            Birleştirilmiş feature dict (60+ feature)
        """
        if not self._initialized:
            self.initialize()

        start = time.monotonic()

        # Cache kontrolü
        cache_key = f"{ticker}:{','.join(sorted(sources or []))}"
        if cache_key in self._feature_cache:
            return self._feature_cache[cache_key]

        # Paralel veri toplama
        all_features: Dict[str, float] = {}

        # 1. Adapter'lardan veri topla
        adapter_results = await adapter_registry.collect_all(ticker, sources)

        # 2. Her kaynaktan feature hesapla
        for source_name, raw_data in adapter_results.items():
            adapter = adapter_registry.get(source_name)
            if adapter and raw_data:
                features = adapter.compute_features(raw_data, ticker)
                all_features.update(features)

        # 3. LLM sentiment (eğer KAP/haber verisi varsa)
        if extra_data:
            llm_features = await self._compute_llm_features(ticker, extra_data)
            all_features.update(llm_features)

        # 4. Cross-source reconciliation
        reconciliation = reconciler.reconcile(ticker, all_features)
        all_features["alt_reliability_score"] = reconciliation.reliability_score
        all_features["alt_consensus_score"] = reconciliation.consensus_score
        all_features["alt_source_count"] = float(reconciliation.source_count)

        # 5. Cross-source composite features
        composite = self._compute_composite_features(all_features)
        all_features.update(composite)

        # 6. Feature store'a yaz
        feature_store.put(ticker, datetime.now(timezone.utc).strftime("%Y-%m-%d"), all_features)

        duration = (time.monotonic() - start) * 1000

        logger.info(
            "Alternative features computed",
            ticker=ticker,
            total_features=len(all_features),
            duration_ms=round(duration, 2),
            non_zero=sum(1 for v in all_features.values() if v != 0),
        )

        # Cache
        self._feature_cache[cache_key] = all_features

        return all_features

    async def _compute_llm_features(
        self,
        ticker: str,
        extra_data: Dict[str, Any],
    ) -> Dict[str, float]:
        """LLM sentiment feature'ları hesapla."""
        features = {}

        # KAP açıklamaları
        kap_texts = extra_data.get("kap_announcements", [])
        if kap_texts:
            for ann in kap_texts[:3]:  # Son 3 açıklama
                result = await llm_sentiment.analyze(
                    text=ann.get("text", ""),
                    ticker=ticker,
                    source="kap",
                )
                if result.get("sentiment_score") is not None:
                    features["llm_kap_sentiment"] = result["sentiment_score"]
                    features["llm_kap_confidence"] = result["confidence"]
                    features["llm_kap_impact"] = {
                        "LOW": 0, "MEDIUM": 1, "HIGH": 2, "CRITICAL": 3
                    }.get(result.get("impact_level", "LOW"), 0)
                    break

        # Haber metinleri
        news_texts = extra_data.get("news", [])
        if news_texts:
            sentiments = []
            for news in news_texts[:5]:  # Son 5 haber
                result = await llm_sentiment.analyze(
                    text=news.get("text", news.get("title", "")),
                    ticker=ticker,
                    source="news",
                )
                if result.get("sentiment_score") is not None:
                    sentiments.append(result["sentiment_score"])

            if sentiments:
                import numpy as np
                features["llm_news_sentiment"] = float(np.mean(sentiments))
                features["llm_news_sentiment_std"] = float(np.std(sentiments))
                features["llm_news_count"] = len(sentiments)

        return features

    def _compute_composite_features(self, features: Dict[str, float]) -> Dict[str, float]:
        """Cross-source bileşik feature'lar."""
        composite = {}

        # 1. Genel alternative data skoru
        sentiment_scores = []
        for key in ["google_trends_zscore", "eksi_sentiment", "llm_kap_sentiment", "llm_news_sentiment"]:
            if key in features and features[key] != 0:
                sentiment_scores.append(features[key])

        if sentiment_scores:
            import numpy as np
            composite["alt_sentiment_avg"] = float(np.mean(sentiment_scores))
            composite["alt_sentiment_consensus"] = float(
                sum(1 for s in sentiment_scores if s > 0) / len(sentiment_scores)
            )

        # 2. Büyüme sinyali
        growth_signals = []
        for key in ["job_posting_growth", "cc_spend_growth", "google_trends_momentum_30d"]:
            if key in features and features[key] != 0:
                growth_signals.append(features[key])

        if growth_signals:
            import numpy as np
            composite["alt_growth_avg"] = float(np.mean(growth_signals))
            composite["alt_growth_consensus"] = float(
                sum(1 for s in growth_signals if s > 0) / len(growth_signals)
            )

        # 3. Alternatif veri güvenilirlik skoru
        non_zero_sources = sum(1 for v in features.values() if v != 0)
        total_possible = 50  # Max feature sayısı
        composite["alt_data_coverage"] = min(1.0, non_zero_sources / total_possible)

        return composite

    def get_feature_names(self) -> List[str]:
        """Tüm mümkün feature adları."""
        return [
            # Google Trends
            "google_trends_score", "google_trends_avg_30d",
            "google_trends_momentum_7d", "google_trends_momentum_30d",
            "google_trends_volatility", "google_trends_percentile",
            "google_trends_relative", "google_trends_trend", "google_trends_zscore",
            # BKM Credit Card
            "cc_spend_growth", "cc_spend_growth_mom", "cc_transaction_count",
            "cc_avg_transaction", "cc_online_ratio", "cc_vs_sector",
            "cc_seasonal_deviation", "cc_foreign_ratio",
            # Kariyer.net Jobs
            "job_posting_count", "job_posting_growth", "job_tech_ratio",
            "job_management_ratio", "job_remote_ratio", "job_diversity",
            # Ekşi Sözlük
            "eksi_sentiment", "eksi_volume", "eksi_positive_ratio",
            "eksi_negative_ratio", "eksi_avg_favorites", "eksi_max_favorites",
            "eksi_sentiment_std", "eksi_controversial",
            # LLM Sentiment
            "llm_kap_sentiment", "llm_kap_confidence", "llm_kap_impact",
            "llm_news_sentiment", "llm_news_sentiment_std", "llm_news_count",
            # Investing.com
            "investing_sentiment", "investing_volume", "investing_positive_ratio",
            "investing_negative_ratio", "investing_sentiment_std", "investing_technical_rating",
            # Reconciliation
            "alt_reliability_score", "alt_consensus_score", "alt_source_count",
            # Composite
            "alt_sentiment_avg", "alt_sentiment_consensus",
            "alt_growth_avg", "alt_growth_consensus", "alt_data_coverage",
            # Social (mevcut)
            "social_sentiment", "social_volume", "social_viral",
            "social_positive_ratio", "social_mention_count",
            # Web Scraping (mevcut)
            "web_traffic_change", "app_ranking_change", "review_count_growth",
            "price_vs_competitors",
        ]

    def get_status(self) -> Dict[str, Any]:
        """Engine durumu."""
        return {
            "initialized": self._initialized,
            "adapters": adapter_registry.get_all_status(),
            "llm_sentiment": llm_sentiment.get_cache_stats(),
            "feature_cache_size": len(self._feature_cache),
            "total_feature_names": len(self.get_feature_names()),
        }


# Singleton
alt_feature_engine = AlternativeFeatureEngine()
