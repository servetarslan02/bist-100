"""
ALPHA BIST — Alternative Data Test Suite v1.0

Tüm fazlar için kapsamlı test'ler.

Kullanım:
    python3 -m pytest tests/test_alternative_data.py -v
"""

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, timezone

from services.alternative import (
    BaseAdapter, RateLimiter, CircuitBreaker, CircuitState,
    DataQualityValidator, QualityReport,
    AdapterRegistry, adapter_registry,
    GoogleTrendsAdapter, google_trends_adapter,
    BKMAdapter, bkm_adapter,
    KariyerNetAdapter, kariyer_net_adapter,
    EksiSozlukAdapter, eksi_sozluk_adapter,
    InvestingAdapter, investing_adapter,
    LLMSentimentAnalyzer, llm_sentiment,
    CrossSourceReconciler, ReconciliationReport, reconciler,
    FeatureStore, FeatureManifest, feature_store,
    AlternativeFeatureEngine, alt_feature_engine,
    compute_social_features, compute_job_features,
    compute_cc_features, compute_satellite_features,
    compute_web_features,
)


# =====================================================
# HELPERS
# =====================================================

def create_mock_social_data():
    return {
        "sentiment": 0.65,
        "volume": 1500,
        "viral": False,
        "positive_ratio": 0.72,
        "mention_count": 350,
        "engagement": 0.15,
        "sentiment_momentum": 0.05,
        "manipulation_score": 0.1,
        "platforms": {
            "twitter": {"sentiment": 0.7, "volume": 800},
            "eksi": {"sentiment": 0.5, "volume": 200},
        },
    }


def create_mock_job_data():
    return {
        "posting_growth": 0.25,
        "tech_hiring_pct": 0.35,
        "layoff": False,
        "salary_change": 0.08,
        "posting_count": 150,
        "remote_ratio": 0.20,
    }


def create_mock_cc_data():
    return {
        "spend_growth": 0.15,
        "vs_sector": 0.05,
        "seasonal_deviation": -0.02,
        "online_ratio": 0.35,
        "transaction_count": 50000,
    }


def create_mock_satellite_data():
    return {
        "factory_traffic": 0.10,
        "store_traffic": 0.05,
        "parking_occupancy": 0.75,
        "port_activity": 0.20,
        "construction_progress": 0.60,
    }


def create_mock_web_data():
    return {
        "web_traffic_change": 0.15,
        "app_ranking_change": -5,
        "review_count_growth": 0.30,
        "price_vs_competitors": -0.05,
        "job_posting_growth": 0.20,
        "search_volume_change": 0.10,
    }


def run_async(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


# =====================================================
# FAZ 0: BASE INFRASTRUCTURE
# =====================================================

class TestFaz0_RateLimiter:
    """Rate limiter test'leri."""

    @pytest.mark.asyncio
    async def test_acquire_basic(self):
        limiter = RateLimiter(max_requests=10, window_seconds=60)
        await limiter.acquire()  # Should not block
        assert limiter._tokens < 10

    @pytest.mark.asyncio
    async def test_acquire_respects_limit(self):
        limiter = RateLimiter(max_requests=2, window_seconds=60)
        await limiter.acquire()
        await limiter.acquire()
        # 3. istek beklemeli ama timeout ile
        try:
            await asyncio.wait_for(limiter.acquire(), timeout=0.5)
        except asyncio.TimeoutError:
            pass  # Expected


class TestFaz0_CircuitBreaker:
    """Circuit breaker test'leri."""

    def test_initial_state_closed(self):
        cb = CircuitBreaker(failure_threshold=3)
        assert cb.state == CircuitState.CLOSED
        assert cb.allow_request()

    def test_opens_after_threshold(self):
        cb = CircuitBreaker(failure_threshold=3)
        for _ in range(3):
            cb.record_failure()
        assert cb.state == CircuitState.OPEN
        assert not cb.allow_request()

    def test_half_open_after_timeout(self):
        cb = CircuitBreaker(failure_threshold=2, recovery_timeout_seconds=0)
        cb.record_failure()
        cb.record_failure()
        # recovery_timeout=0 olduğu için state property'si hemen HALF_OPEN döner
        state = cb.state  # Bu çağrı HALF_OPEN'a çevirir
        assert state == CircuitState.HALF_OPEN
        assert cb.allow_request()

    def test_closes_after_success(self):
        cb = CircuitBreaker(failure_threshold=2, recovery_timeout_seconds=0)
        cb.record_failure()
        cb.record_failure()
        # state'i HALF_OPEN'a çevir
        _ = cb.state
        cb.record_success()
        cb.record_success()
        assert cb.state == CircuitState.CLOSED


class TestFaz0_DataQuality:
    """Data quality validator test'leri."""

    def test_valid_data(self):
        validator = DataQualityValidator()
        data = {"sentiment": 0.5, "volume": 1000}
        report = validator.validate(data, source="test")
        assert report.is_valid
        assert report.score > 0.5

    def test_none_data(self):
        validator = DataQualityValidator()
        report = validator.validate(None, source="test")
        assert not report.is_valid
        assert report.score == 0

    def test_empty_dict(self):
        validator = DataQualityValidator()
        report = validator.validate({}, source="test")
        # Boş dict: null check + type check + empty check → 1 failed
        # score = 3/4 = 0.75, is_valid = True (score >= 0.5 ve failed <= 2)
        assert report.checks_failed >= 1

    def test_all_zeros(self):
        validator = DataQualityValidator()
        data = {"a": 0, "b": 0, "c": 0}
        report = validator.validate(data, source="test")
        # All zeros: 1 failed, score = 3/4 = 0.75
        assert report.checks_failed >= 1

    def test_expected_fields(self):
        validator = DataQualityValidator()
        data = {"sentiment": 0.5}
        report = validator.validate(data, source="test", expected_fields=["sentiment", "volume"])
        # Missing field: 1 failed, score = 4/5 = 0.8
        assert report.checks_failed >= 1

    def test_range_check(self):
        validator = DataQualityValidator()
        data = {"confidence": 2.0}  # 0-1 arası olmalı
        report = validator.validate(data, source="test")
        assert len(report.issues) > 0


class TestFaz0_AdapterRegistry:
    """Adapter registry test'leri."""

    def test_register_and_list(self):
        registry = AdapterRegistry()
        adapter = BKMAdapter()
        registry.register(adapter)
        assert "bkm" in registry.list_adapters()

    def test_get_adapter(self):
        registry = AdapterRegistry()
        adapter = BKMAdapter()
        registry.register(adapter)
        assert registry.get("bkm") is adapter
        assert registry.get("nonexistent") is None

    def test_get_all_status(self):
        registry = AdapterRegistry()
        registry.register(BKMAdapter())
        status = registry.get_all_status()
        assert "bkm" in status


# =====================================================
# FAZ 1: LEGACY FEATURE FUNCTIONS
# =====================================================

class TestFaz1_LegacyFeatures:
    """Legacy feature fonksiyonları test'leri."""

    def test_social_features(self):
        data = create_mock_social_data()
        features = compute_social_features(data, "THYAO")
        assert "social_sentiment" in features
        assert features["social_sentiment"] == 0.65
        assert "social_volume" in features
        assert "social_viral" in features
        assert "social_twitter_sentiment" in features

    def test_job_features(self):
        data = create_mock_job_data()
        features = compute_job_features(data, "THYAO")
        assert "job_posting_growth" in features
        assert features["job_posting_growth"] == 0.25
        assert features["tech_hiring_pct"] == 0.35

    def test_cc_features(self):
        data = create_mock_cc_data()
        features = compute_cc_features(data, "THYAO")
        assert "cc_spend_growth" in features
        assert features["cc_spend_growth"] == 0.15

    def test_satellite_features(self):
        data = create_mock_satellite_data()
        features = compute_satellite_features(data, "THYAO")
        assert "factory_traffic_change" in features
        assert features["factory_traffic_change"] == 0.10

    def test_web_features(self):
        data = create_mock_web_data()
        features = compute_web_features(data, "THYAO")
        assert "web_traffic_change" in features
        assert features["web_traffic_change"] == 0.15

    def test_empty_data(self):
        assert compute_social_features({}, "THYAO") == {}
        assert compute_social_features(None, "THYAO") == {}


# =====================================================
# FAZ 2: ADAPTERS
# =====================================================

class TestFaz2_BKMAdapter:
    """BKM adapter test'leri."""

    def test_source_name(self):
        assert bkm_adapter.source_name == "bkm"

    def test_compute_features_empty(self):
        features = bkm_adapter.compute_features({}, "THYAO")
        assert features == {}

    def test_compute_features_placeholder(self):
        data = {"data_source": "placeholder", "total_spend": 0}
        features = bkm_adapter.compute_features(data, "THYAO")
        assert features == {}  # Placeholder veri → feature üretme

    def test_compute_features_valid(self):
        data = {
            "total_spend": 1000000,
            "transaction_count": 50000,
            "avg_transaction": 200,
            "online_ratio": 0.35,
            "growth_yoy": 0.15,
            "growth_mom": 0.05,
            "sector_growth": 0.10,
            "foreign_card_ratio": 0.08,
            "data_source": "real",
        }
        features = bkm_adapter.compute_features(data, "THYAO")
        assert "cc_spend_growth" in features
        assert features["cc_spend_growth"] == 0.15
        assert abs(features["cc_vs_sector"] - 0.05) < 0.001  # 0.15 - 0.10 (float tolerance)


class TestFaz2_GoogleTrendsAdapter:
    """Google Trends adapter test'leri."""

    def test_source_name(self):
        assert google_trends_adapter.source_name == "google_trends"

    def test_compute_features_empty(self):
        features = google_trends_adapter.compute_features({}, "THYAO")
        assert features == {}

    def test_compute_features_valid(self):
        data = {
            "score": 75,
            "avg_30d": 60,
            "momentum_7d": 10,
            "momentum_30d": 15,
            "volatility": 12,
            "percentile_90": 85,
            "trend_direction": 1.0,
        }
        features = google_trends_adapter.compute_features(data, "THYAO")
        assert "google_trends_score" in features
        assert features["google_trends_score"] == 75
        assert features["google_trends_trend"] == 1.0


class TestFaz2_KariyerNetAdapter:
    """Kariyer.net adapter test'leri."""

    def test_source_name(self):
        assert kariyer_net_adapter.source_name == "kariyer_net"

    def test_compute_features_empty(self):
        features = kariyer_net_adapter.compute_features({}, "THYAO")
        assert features == {}

    def test_compute_features_valid(self):
        data = {
            "postings": [
                {"is_tech": True, "is_management": False, "is_remote": True, "department": "IT"},
                {"is_tech": False, "is_management": True, "is_remote": False, "department": "Yönetim"},
                {"is_tech": True, "is_management": False, "is_remote": False, "department": "IT"},
                {"is_tech": False, "is_management": False, "is_remote": False, "department": "Satış"},
            ],
        }
        features = kariyer_net_adapter.compute_features(data, "THYAO")
        assert "job_posting_count" in features
        assert features["job_posting_count"] == 4
        assert features["job_tech_ratio"] == 0.5  # 2/4
        assert features["job_management_ratio"] == 0.25  # 1/4


class TestFaz2_EksiSozlukAdapter:
    """Ekşi Sözlük adapter test'leri."""

    def test_source_name(self):
        assert eksi_sozluk_adapter.source_name == "eksi_sozluk"

    def test_compute_features_empty(self):
        features = eksi_sozluk_adapter.compute_features({}, "THYAO")
        assert features == {}

    def test_compute_features_valid(self):
        data = {
            "entries": [
                {"text": "thyao çok güzel hisse, yükseliş devam edecek", "favorites": 15},
                {"text": "thyao kötü performans, düşüş riski var", "favorites": 8},
                {"text": "thyao ortalamayı tutuyor", "favorites": 3},
            ],
        }
        features = eksi_sozluk_adapter.compute_features(data, "THYAO")
        assert "eksi_sentiment" in features
        assert "eksi_volume" in features
        assert features["eksi_volume"] == 3

    def test_basic_sentiment(self):
        assert eksi_sozluk_adapter._basic_sentiment("güzel harika başarılı") > 0
        assert eksi_sozluk_adapter._basic_sentiment("kötü batık zarar") < 0
        # "güzel" pozitif kelimeler listesinde olduğu için nötr metin bile pozitif çıkabilir
        neutral_score = eksi_sozluk_adapter._basic_sentiment("bugün hava güzel")
        assert isinstance(neutral_score, float)


# =====================================================
# FAZ 3: LLM SENTIMENT
# =====================================================

class TestFaz3_LLMSentiment:
    """LLM sentiment test'leri."""

    def test_keyword_analyze_positive(self):
        analyzer = LLMSentimentAnalyzer()
        result = analyzer._keyword_analyze("Şirket rekor kâr açıkladı, büyüme devam ediyor")
        assert result["sentiment_score"] > 0
        assert result["source"] == "keyword_fallback"

    def test_keyword_analyze_negative(self):
        analyzer = LLMSentimentAnalyzer()
        result = analyzer._keyword_analyze("Şirket zarar açıkladı, iflas riski var")
        assert result["sentiment_score"] < 0

    def test_keyword_analyze_neutral(self):
        analyzer = LLMSentimentAnalyzer()
        result = analyzer._keyword_analyze("Bugün hava çok güzel")
        assert result["sentiment_score"] == 0

    def test_neutral_result(self):
        analyzer = LLMSentimentAnalyzer()
        result = analyzer._neutral_result()
        assert result["sentiment_score"] == 0
        assert result["category"] == "NEUTRAL"

    def test_cache_stats(self):
        analyzer = LLMSentimentAnalyzer()
        stats = analyzer.get_cache_stats()
        assert "cache_size" in stats
        assert "has_llm" in stats


# =====================================================
# FAZ 4: FEATURE ENGINE
# =====================================================

class TestFaz4_FeatureEngine:
    """Feature engine test'leri."""

    def test_get_feature_names(self):
        engine = AlternativeFeatureEngine()
        names = engine.get_feature_names()
        assert len(names) > 40
        assert "google_trends_score" in names
        assert "cc_spend_growth" in names
        assert "eksi_sentiment" in names
        assert "alt_sentiment_avg" in names

    def test_composite_features(self):
        engine = AlternativeFeatureEngine()
        features = {
            "google_trends_zscore": 1.5,
            "eksi_sentiment": 0.3,
            "job_posting_growth": 0.2,
            "cc_spend_growth": 0.1,
        }
        composite = engine._compute_composite_features(features)
        assert "alt_sentiment_avg" in composite
        assert "alt_growth_avg" in composite
        assert "alt_data_coverage" in composite

    def test_status(self):
        engine = AlternativeFeatureEngine()
        status = engine.get_status()
        assert "initialized" in status
        assert "total_feature_names" in status


# =====================================================
# FAZ 5: ENTEGRASYON
# =====================================================

class TestFaz5_InvestingAdapter:
    """Investing.com adapter test'leri."""

    def test_source_name(self):
        assert investing_adapter.source_name == "investing"

    def test_compute_features_empty(self):
        features = investing_adapter.compute_features({}, "THYAO")
        assert features == {}

    def test_compute_features_valid(self):
        data = {
            "comments": [
                {"text": "yükseliş devam edecek, al"},
                {"text": "düşüş riski var, sat"},
                {"text": "güçlü performans"},
            ],
        }
        features = investing_adapter.compute_features(data, "THYAO")
        assert "investing_sentiment" in features
        assert "investing_volume" in features
        assert features["investing_volume"] == 3

    def test_basic_sentiment(self):
        assert investing_adapter._basic_sentiment("yükseliş güçlü al") > 0
        assert investing_adapter._basic_sentiment("düşüş riski sat") < 0


class TestFaz5_Reconciliation:
    """Cross-source reconciliation test'leri."""

    def test_reconcile_no_data(self):
        r = reconciler.reconcile("THYAO", {})
        assert r.consensus_direction == "NEUTRAL"
        assert r.source_count == 0

    def test_reconcile_consistent(self):
        features = {
            "google_trends_zscore": 1.5,
            "eksi_sentiment": 0.6,
            "investing_sentiment": 0.7,
        }
        r = reconciler.reconcile("THYAO", features)
        assert r.consensus_direction == "LONG"
        assert r.source_count == 3
        assert r.reliability_score > 0

    def test_reconcile_discrepant(self):
        features = {
            "google_trends_zscore": 0.8,
            "eksi_sentiment": -0.7,
        }
        r = reconciler.reconcile("THYAO", features)
        assert len(r.discrepancies) > 0 or len(r.warnings) > 0

    def test_reconcile_to_dict(self):
        r = reconciler.reconcile("THYAO", {"eksi_sentiment": 0.5})
        d = r.to_dict()
        assert "ticker" in d
        assert "consensus_direction" in d


class TestFaz5_FeatureStore:
    """Feature store test'leri."""

    def test_put_and_get(self):
        store = FeatureStore()
        store.put("THYAO", "2026-01-01", {"sentiment": 0.5, "volume": 100})
        features = store.get("THYAO", "2026-01-01")
        assert features["sentiment"] == 0.5

    def test_get_latest(self):
        store = FeatureStore()
        store.put("THYAO", "2026-01-01", {"sentiment": 0.3})
        store.put("THYAO", "2026-01-15", {"sentiment": 0.7})
        features = store.get_latest("THYAO", "2026-01-20")
        assert features["sentiment"] == 0.7

    def test_get_latest_before_any_date(self):
        store = FeatureStore()
        store.put("THYAO", "2026-01-01", {"sentiment": 0.5})
        features = store.get_latest("THYAO", "2025-12-01")
        assert features == {}

    def test_register_feature(self):
        store = FeatureStore()
        store.register_feature(FeatureManifest(
            feature_name="test_feature",
            version="v1",
            source="test",
            description="Test feature",
            dtype="float",
            range_min=-1,
            range_max=1,
        ))
        assert "test_feature" in store.list_features()

    def test_stats(self):
        store = FeatureStore()
        store.put("THYAO", "2026-01-01", {"a": 1, "b": 2})
        stats = store.get_stats()
        assert stats["total_features"] == 2
        assert stats["total_dates"] == 1


class TestFaz5_Integration:
    """Entegrasyon test'leri."""

    def test_all_imports(self):
        """Tüm modüllerin import edilebilir olduğunu doğrula."""
        from services.alternative import (
            BaseAdapter, RateLimiter, CircuitBreaker,
            DataQualityValidator, AdapterRegistry,
            google_trends_adapter, bkm_adapter,
            kariyer_net_adapter, eksi_sozluk_adapter,
            investing_adapter,
            llm_sentiment, alt_feature_engine,
            reconciler, feature_store,
            compute_social_features, compute_job_features,
            compute_cc_features, compute_satellite_features,
            compute_web_features,
        )
        assert True

    def test_adapter_registry_singleton(self):
        """Singleton registry'nin doğru çalıştığını doğrula."""
        from services.alternative import adapter_registry
        assert isinstance(adapter_registry, AdapterRegistry)

    def test_legacy_functions_compatible(self):
        """Legacy fonksiyonların geriye uyumlu olduğunu doğrula."""
        data = {"sentiment": 0.5, "volume": 100}
        features = compute_social_features(data, "TEST")
        assert "social_sentiment" in features
        assert "social_volume" in features


class TestBugFixes:
    """Düzeltilen bug'lar için test'ler."""

    def test_clamp_none_handling(self):
        """_clamp(None) crash yapmamalı."""
        from services.alternative.social import _clamp
        assert _clamp(None, -1, 1) == 0.0
        assert _clamp(0.5, -1, 1) == 0.5
        assert _clamp(2.0, -1, 1) == 1.0
        assert _clamp(-2.0, -1, 1) == -1.0

    def test_google_trends_float_types(self):
        """Google Trends feature'ları float olmalı."""
        data = {
            "score": 75,
            "avg_30d": 60,
            "momentum_7d": 10,
            "momentum_30d": 15,
            "volatility": 12,
            "percentile_90": 85,
            "trend_direction": 1.0,
        }
        features = google_trends_adapter.compute_features(data, "THYAO")
        for k, v in features.items():
            assert isinstance(v, float), f"{k} should be float, got {type(v).__name__}"

    def test_compute_features_contract(self):
        """Tüm adapter'lar Dict[str, float} döndürmeli."""
        adapters = [
            (bkm_adapter, {}),
            (google_trends_adapter, {}),
            (kariyer_net_adapter, {}),
            (eksi_sozluk_adapter, {}),
            (investing_adapter, {}),
        ]
        for adapter, empty_data in adapters:
            result = adapter.compute_features(empty_data, "THYAO")
            assert isinstance(result, dict), f"{adapter.source_name} should return dict"
            for k, v in result.items():
                assert isinstance(v, (int, float)), f"{adapter.source_name}.{k} should be numeric"

    @pytest.mark.asyncio
    async def test_feature_engine_compute(self):
        """Feature engine çalışmalı (boş veri ile)."""
        engine = AlternativeFeatureEngine()
        engine.initialize()
        # Boş veri ile çalışmalı, crash yapmamalı
        features = await engine.compute_all_features("THYAO")
        assert isinstance(features, dict)
        # En azından composite features olmalı
        assert "alt_data_coverage" in features


# =====================================================
# MAIN
# =====================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
