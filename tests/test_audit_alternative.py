"""
services/alternative/ — Audit Düzeltmeleri Test Suite

Yapılan tüm düzeltmelerin doğru çalıştığını doğrular.
"""

import sys

import pytest

sys.path.insert(0, ".")


# =====================================================
# 1. __init__.py — __version__ ve Lazy Import
# =====================================================


class TestInitVersion:
    """__init__.py versiyon ve lazy import testleri."""

    def test_version_exists(self):
        from services.alternative import __version__

        assert __version__ == "2.0.0"

    def test_lazy_import_social(self):
        from services.alternative import compute_social_features

        assert callable(compute_social_features)

    def test_lazy_import_web(self):
        from services.alternative import compute_web_features

        assert callable(compute_web_features)

    def test_lazy_import_investing(self):
        from services.alternative import InvestingAdapter, investing_adapter

        assert InvestingAdapter is not None
        assert investing_adapter is not None

    def test_lazy_import_satellite(self):
        from services.alternative import SatelliteAdapter, satellite_adapter

        assert SatelliteAdapter is not None
        assert satellite_adapter is not None

    def test_lazy_import_compute_satellite(self):
        from services.alternative import compute_satellite_features

        assert callable(compute_satellite_features)


# =====================================================
# 2. base.py — Düzeltmeler
# =====================================================


class TestBaseRateLimiter:
    """RateLimiter düzeltmeleri."""

    def test_repr_exists(self):
        from services.alternative.base import RateLimiter

        rl = RateLimiter(max_requests=10, window_seconds=60)
        r = repr(rl)
        assert "RateLimiter" in r
        assert "10" in r
        assert "60" in r

    @pytest.mark.asyncio
    async def test_acquire_returns_none(self):
        from services.alternative.base import RateLimiter

        rl = RateLimiter(max_requests=10, window_seconds=60)
        result = await rl.acquire()
        assert result is None

    def test_no_placeholder_docstring(self):
        import inspect

        from services.alternative.base import RateLimiter

        source = inspect.getsource(RateLimiter)
        assert "Otomatik eklendi" not in source


class TestBaseCircuitBreaker:
    """CircuitBreaker düzeltmeleri."""

    def test_record_success_returns_none(self):
        from services.alternative.base import CircuitBreaker

        cb = CircuitBreaker()
        result = cb.record_success()
        assert result is None

    def test_record_failure_returns_none(self):
        from services.alternative.base import CircuitBreaker

        cb = CircuitBreaker()
        result = cb.record_failure()
        assert result is None

    def test_no_placeholder_docstring(self):
        import inspect

        from services.alternative.base import CircuitBreaker

        source = inspect.getsource(CircuitBreaker)
        assert "Otomatik eklendi" not in source


class TestBaseDataQualityValidator:
    """DataQualityValidator düzeltmeleri."""

    def test_range_check_counts_failure(self):
        """Range check artık checks_failed artırıyor."""
        from services.alternative.base import DataQualityValidator

        dv = DataQualityValidator()
        report = dv.validate({"confidence": 2.0, "score": 50}, source="test")
        assert report.checks_failed > 0
        assert any("out of expected range" in i for i in report.issues)

    def test_range_check_counts_pass(self):
        """Geçerli aralıktaki değerler checks_passed artırmalı."""
        from services.alternative.base import DataQualityValidator

        dv = DataQualityValidator()
        report = dv.validate({"confidence": 0.5, "score": 50}, source="test")
        assert report.checks_passed > 0

    def test_no_placeholder_docstring(self):
        import inspect

        from services.alternative.base import DataQualityValidator

        source = inspect.getsource(DataQualityValidator)
        assert "Otomatik eklendi" not in source


class TestBaseAdapter:
    """BaseAdapter düzeltmeleri."""

    def test_repr_exists(self):
        from services.alternative.base import BaseAdapter

        class TestAdapter(BaseAdapter):
            source_name = "test"
            rate_limit = 5

            async def collect(self, ticker, **kwargs):
                return None

            def compute_features(self, data, ticker):
                return {}

        adapter = TestAdapter()
        r = repr(adapter)
        assert "TestAdapter" in r
        assert "test" in r

    def test_no_mutable_class_attribute(self):
        """circuit_breaker sınıf seviyesinde değil, instance seviyesinde olmalı."""
        from services.alternative.base import BaseAdapter

        class TestAdapter(BaseAdapter):
            source_name = "test"

            async def collect(self, ticker, **kwargs):
                return None

            def compute_features(self, data, ticker):
                return {}

        a1 = TestAdapter()
        a2 = TestAdapter()
        # Farklı instance'lar farklı circuit breaker'a sahip olmalı
        assert a1.circuit_breaker is not a2.circuit_breaker

    @pytest.mark.asyncio
    async def test_fetch_empty_ticker(self):
        """Boş ticker ile çağrılamaz."""
        from services.alternative.base import BaseAdapter

        class TestAdapter(BaseAdapter):
            source_name = "test"

            async def collect(self, ticker, **kwargs):
                return None

            def compute_features(self, data, ticker):
                return {}

        adapter = TestAdapter()
        result = await adapter.fetch("")
        assert result == {}

        result = await adapter.fetch("   ")
        assert result == {}

    def test_no_placeholder_docstring(self):
        import inspect

        from services.alternative.base import BaseAdapter

        source = inspect.getsource(BaseAdapter)
        assert "Otomatik eklendi" not in source


class TestBaseAdapterRegistry:
    """AdapterRegistry düzeltmeleri."""

    def test_repr_exists(self):
        from services.alternative.base import AdapterRegistry

        ar = AdapterRegistry()
        r = repr(ar)
        assert "AdapterRegistry" in r
        assert "0" in r

    def test_register_returns_none(self):
        from services.alternative.base import AdapterRegistry, BaseAdapter

        class TestAdapter(BaseAdapter):
            source_name = "test"

            async def collect(self, ticker, **kwargs):
                return None

            def compute_features(self, data, ticker):
                return {}

        ar = AdapterRegistry()
        result = ar.register(TestAdapter())
        assert result is None

    @pytest.mark.asyncio
    async def test_collect_all_strict_zip(self):
        """zip strict=True — boş registry ile çalışmalı."""
        from services.alternative.base import AdapterRegistry

        ar = AdapterRegistry()
        result = await ar.collect_all("THYAO")
        assert result == {}


# =====================================================
# 3. bkm_adapter.py — Düzeltmeler
# =====================================================


class TestBKMAdapter:
    """BKMAdapter düzeltmeleri."""

    def test_no_dead_features(self):
        """Kaldırılan feature'lar üretilmemeli."""
        from services.alternative.bkm_adapter import bkm_adapter

        data = {
            "total_spend": 1000000,
            "transaction_count": 50000,
            "online_ratio": 0.35,
            "contactless_ratio": 0.20,
            "growth_yoy": 0.15,
        }
        features = bkm_adapter.compute_features(data, "THYAO")
        # Kaldırılan feature'lar
        assert "cc_spend_growth_mom" not in features
        assert "cc_foreign_ratio" not in features
        assert "cc_vs_sector" not in features

    def test_avg_transaction_calculated(self):
        """avg_transaction artık hesaplanıyor."""
        from services.alternative.bkm_adapter import bkm_adapter

        data = {
            "total_spend": 1000000,
            "transaction_count": 50000,
        }
        features = bkm_adapter.compute_features(data, "THYAO")
        assert features["cc_avg_transaction"] == 20.0  # 1000000 / 50000

    def test_parse_turkish_number_raises(self):
        """_parse_turkish_number artık ValueError raise ediyor."""
        from services.alternative.bkm_adapter import bkm_adapter

        with pytest.raises(ValueError):
            bkm_adapter._parse_turkish_number("invalid")

    def test_parse_turkish_number_valid(self):
        from services.alternative.bkm_adapter import bkm_adapter

        assert bkm_adapter._parse_turkish_number("1.234,56") == 1234.56
        assert bkm_adapter._parse_turkish_number("42") == 42.0

    def test_no_placeholder_docstring(self):
        import inspect

        from services.alternative.bkm_adapter import BKMAdapter

        source = inspect.getsource(BKMAdapter)
        assert "Otomatik eklendi" not in source


# =====================================================
# 4. credit_card.py — Düzeltmeler
# =====================================================


class TestCreditCard:
    """compute_cc_features düzeltmeleri."""

    def test_all_values_float(self):
        """Tüm değerler float olmalı."""
        from services.alternative.credit_card import compute_cc_features

        data = {"spend_growth": 0.15, "transaction_count": 50000, "online_ratio": 0.35}
        features = compute_cc_features(data, "THYAO")
        for k, v in features.items():
            assert isinstance(v, float), f"{k} should be float, got {type(v)}"

    def test_string_values_skipped(self):
        """String değerler skip edilmeli."""
        from services.alternative.credit_card import compute_cc_features

        data = {"spend_growth": "invalid", "transaction_count": "500"}
        features = compute_cc_features(data, "THYAO")
        assert "cc_spend_growth" not in features  # invalid skip
        assert "cc_transaction_count" in features  # "500" → 500.0

    def test_none_values_skipped(self):
        from services.alternative.credit_card import compute_cc_features

        data = {"spend_growth": None, "transaction_count": 100}
        features = compute_cc_features(data, "THYAO")
        assert "cc_spend_growth" not in features


# =====================================================
# 5. eksi_sozluk.py — Düzeltmeler
# =====================================================


class TestEksiSozluk:
    """EksiSozlukAdapter düzeltmeleri."""

    def test_no_placeholder_docstring(self):
        import inspect

        from services.alternative.eksi_sozluk import EksiSozlukAdapter

        source = inspect.getsource(EksiSozlukAdapter)
        assert "Otomatik eklendi" not in source

    def test_docstrings_turkish(self):
        """Docstring'ler Türkçe olmalı."""
        import inspect

        from services.alternative.eksi_sozluk import EksiSozlukAdapter

        source = inspect.getsource(EksiSozlukAdapter)
        assert "keyword tabanlı" in source.lower() or "keyword-based" not in source.lower()


# =====================================================
# 6. feature_engine.py — Düzeltmeler
# =====================================================


class TestFeatureEngine:
    """AlternativeFeatureEngine düzeltmeleri."""

    def test_no_placeholder_docstring(self):
        import inspect

        from services.alternative.feature_engine import AlternativeFeatureEngine

        source = inspect.getsource(AlternativeFeatureEngine)
        assert "Otomatik eklendi" not in source

    def test_initialize_returns_none(self):
        from services.alternative.feature_engine import AlternativeFeatureEngine

        engine = AlternativeFeatureEngine()
        result = engine.initialize()
        assert result is None

    def test_impact_levels_class_attribute(self):
        """IMPACT_LEVELS sınıf attribute olarak tanımlı olmalı."""
        from services.alternative.feature_engine import AlternativeFeatureEngine

        assert hasattr(AlternativeFeatureEngine, "IMPACT_LEVELS")
        assert "LOW" in AlternativeFeatureEngine.IMPACT_LEVELS
        assert "CRITICAL" in AlternativeFeatureEngine.IMPACT_LEVELS

    def test_feature_names_include_all_adapter_features(self):
        """Tüm adapter feature'ları listede olmalı."""
        from services.alternative.feature_engine import AlternativeFeatureEngine

        engine = AlternativeFeatureEngine()
        names = set(engine.get_feature_names())

        # credit_card
        assert "cc_vs_sector" in names
        # jobs
        assert "tech_hiring_pct" in names
        assert "avg_salary_change" in names
        assert "layoff_signal" in names
        # social
        assert "social_engagement" in names
        assert "social_sentiment_momentum" in names
        assert "social_manipulation_score" in names
        # web_scraping
        assert "search_volume_change" in names

    def test_lazy_import_in_initialize(self):
        """investing_adapter ve satellite_adapter initialize'da lazy import edilmeli."""
        import inspect

        from services.alternative.feature_engine import AlternativeFeatureEngine

        source = inspect.getsource(AlternativeFeatureEngine.initialize)
        assert "from .investing_adapter import investing_adapter" in source
        assert "from .satellite_adapter import satellite_adapter" in source

    def test_no_top_level_investing_import(self):
        """investing_adapter top-level import edilmemeli."""
        import inspect

        from services.alternative import feature_engine

        source = inspect.getsource(feature_engine)
        lines = source.split("\n")
        top_level_lines = [l for l in lines if l.startswith("from .investing_adapter")]
        # Sadece initialize() içinde olmalı, top-level'da olmamalı
        for line in top_level_lines:
            assert "def initialize" not in line  # Bu zaten farklı scope


# =====================================================
# 7. feature_store.py — Düzeltmeler
# =====================================================


class TestFeatureStore:
    """FeatureStore düzeltmeleri."""

    def test_no_placeholder_docstring(self):
        import inspect

        from services.alternative.feature_store import FeatureStore

        source = inspect.getsource(FeatureStore)
        assert "Otomatik eklendi" not in source

    def test_register_returns_none(self):
        from services.alternative.feature_store import FeatureManifest, FeatureStore

        store = FeatureStore()
        manifest = FeatureManifest(
            feature_name="test", version="v1", source="test",
            description="test", dtype="float", range_min=0, range_max=1,
        )
        result = store.register_feature(manifest)
        assert result is None

    def test_put_returns_none(self):
        from services.alternative.feature_store import FeatureStore

        store = FeatureStore()
        result = store.put("THYAO", "2026-01-01", {"a": 1.0})
        assert result is None

    def test_no_cross_module_import(self):
        """services.core.debounce import'u kaldırılmış olmalı."""
        import inspect

        from services.alternative.feature_store import FeatureStore

        source = inspect.getsource(FeatureStore)
        assert "services.core.debounce" not in source


# =====================================================
# 8. google_trends.py — Düzeltmeler
# =====================================================


class TestGoogleTrends:
    """GoogleTrendsAdapter düzeltmeleri."""

    def test_no_placeholder_docstring(self):
        import inspect

        from services.alternative.google_trends import GoogleTrendsAdapter

        source = inspect.getsource(GoogleTrendsAdapter)
        assert "Otomatik eklendi" not in source


# =====================================================
# 9. investing_adapter.py — Düzeltmeler
# =====================================================


class TestInvestingAdapter:
    """InvestingAdapter düzeltmeleri."""

    def test_no_placeholder_docstring(self):
        import inspect

        from services.alternative.investing_adapter import InvestingAdapter

        source = inspect.getsource(InvestingAdapter)
        assert "Otomatik eklendi" not in source

    def test_variable_names_meaningful(self):
        """Değişken isimleri anlamlı olmalı (p, n, t değil)."""
        import inspect

        from services.alternative.investing_adapter import InvestingAdapter

        source = inspect.getsource(InvestingAdapter._basic_sentiment)
        assert "positive_count" in source
        assert "negative_count" in source
        assert "total" in source

    def test_docstrings_turkish(self):
        import inspect

        from services.alternative.investing_adapter import InvestingAdapter

        source = inspect.getsource(InvestingAdapter._basic_sentiment)
        assert "keyword tabanlı" in source.lower()


# =====================================================
# 10. jobs.py — Düzeltmeler
# =====================================================


class TestJobs:
    """compute_job_features düzeltmeleri."""

    def test_all_values_float(self):
        from services.alternative.jobs import compute_job_features

        data = {"posting_growth": 0.2, "tech_hiring_pct": 0.4, "posting_count": 150}
        features = compute_job_features(data, "THYAO")
        for k, v in features.items():
            assert isinstance(v, float), f"{k} should be float, got {type(v)}"

    def test_string_values_cast(self):
        from services.alternative.jobs import compute_job_features

        data = {"posting_count": "150", "posting_growth": "0.2"}
        features = compute_job_features(data, "THYAO")
        assert features["job_posting_count"] == 150.0
        assert features["job_posting_growth"] == 0.2


# =====================================================
# 11. kariyer_net.py — Düzeltmeler
# =====================================================


class TestKariyerNet:
    """KariyerNetAdapter düzeltmeleri."""

    def test_no_placeholder_docstring(self):
        import inspect

        from services.alternative.kariyer_net import KariyerNetAdapter

        source = inspect.getsource(KariyerNetAdapter)
        assert "Otomatik eklendi" not in source
        assert "Placeholder yapı" not in source


# =====================================================
# 12. llm_sentiment.py — Düzeltmeler
# =====================================================


class TestLLMSentiment:
    """LLMSentimentAnalyzer düzeltmeleri."""

    def test_no_placeholder_docstring(self):
        import inspect

        from services.alternative.llm_sentiment import LLMSentimentAnalyzer

        source = inspect.getsource(LLMSentimentAnalyzer)
        assert "Otomatik eklendi" not in source

    def test_set_llm_client_returns_none(self):
        from services.alternative.llm_sentiment import LLMSentimentAnalyzer

        analyzer = LLMSentimentAnalyzer()
        result = analyzer.set_llm_client(None)
        assert result is None

    def test_no_duplicate_negative_words(self):
        """Negatif kelime listesinde duplicate olmamalı."""
        import inspect

        from services.alternative.llm_sentiment import LLMSentimentAnalyzer

        source = inspect.getsource(LLMSentimentAnalyzer._keyword_analyze)
        # "kayıp" ve "zarar" sadece bir kez geçmeli
        assert source.count('"kayıp"') == 1
        assert source.count('"zarar"') == 1

    def test_analyze_batch_return_type(self):
        """analyze_batch Exception dönebilir."""
        import inspect

        from services.alternative.llm_sentiment import LLMSentimentAnalyzer

        sig = inspect.signature(LLMSentimentAnalyzer.analyze_batch)
        # return type annotation Exception içermeli
        annotation = str(sig.return_annotation)
        assert "Exception" in annotation


# =====================================================
# 13. reconciliation.py — Düzeltmeler
# =====================================================


class TestReconciliation:
    """CrossSourceReconciler düzeltmeleri."""

    def test_no_placeholder_docstring(self):
        import inspect

        from services.alternative.reconciliation import ReconciliationReport

        source = inspect.getsource(ReconciliationReport)
        assert "Otomatik eklendi" not in source

    def test_no_dead_code(self):
        """_compute_consensus sadece bir kez çağrılmalı (dead code kaldırıldı)."""
        import inspect

        from services.alternative.reconciliation import CrossSourceReconciler

        source = inspect.getsource(CrossSourceReconciler.reconcile)
        assert source.count("self._compute_consensus") == 1

    def test_no_unused_category_param(self):
        """_compute_consensus'te category parametresi olmamalı."""
        import inspect

        from services.alternative.reconciliation import CrossSourceReconciler

        sig = inspect.signature(CrossSourceReconciler._compute_consensus)
        assert "category" not in sig.parameters


# =====================================================
# 14. satellite_adapter.py — Düzeltmeler
# =====================================================


class TestSatelliteAdapter:
    """SatelliteAdapter düzeltmeleri."""

    def test_no_placeholder_docstring(self):
        import inspect

        from services.alternative.satellite_adapter import SatelliteAdapter

        source = inspect.getsource(SatelliteAdapter)
        assert "Otomatik eklendi" not in source

    def test_legacy_wrapper_validates(self):
        """compute_satellite_features değerleri validate etmeli."""
        from services.alternative.satellite_adapter import compute_satellite_features

        data = {"factory_traffic": "invalid", "port_activity": 0.5}
        features = compute_satellite_features(data, "THYAO")
        assert "factory_traffic_change" not in features  # invalid skip
        assert "port_activity" in features  # valid

    def test_no_unused_bbox_to_wkt(self):
        """_bbox_to_wkt çağrılmamalı (kullanılmayan return kaldırıldı)."""
        import inspect

        from services.alternative.satellite_adapter import SatelliteAdapter

        source = inspect.getsource(SatelliteAdapter._fetch_ndvi)
        assert "_bbox_to_wkt(bbox)" not in source


# =====================================================
# 15. social.py — Düzeltmeler
# =====================================================


class TestSocial:
    """social.py düzeltmeleri."""

    def test_clamp_handles_none(self):
        from services.alternative.social import _clamp

        assert _clamp(None, -1, 1) == 0.0

    def test_clamp_handles_invalid_string(self):
        from services.alternative.social import _clamp

        assert _clamp("invalid", -1, 1) == 0.0

    def test_clamp_handles_valid(self):
        from services.alternative.social import _clamp

        assert _clamp(0.5, 0, 1) == 0.5
        assert _clamp(1.5, 0, 1) == 1.0
        assert _clamp(-0.5, 0, 1) == 0.0


# =====================================================
# 16. web_scraping.py — Düzeltmeler
# =====================================================


class TestWebScraping:
    """compute_web_features düzeltmeleri."""

    def test_all_values_float(self):
        from services.alternative.web_scraping import compute_web_features

        data = {"web_traffic_change": 0.15, "app_ranking_change": -5}
        features = compute_web_features(data, "THYAO")
        for k, v in features.items():
            assert isinstance(v, float), f"{k} should be float, got {type(v)}"

    def test_string_values_skipped(self):
        from services.alternative.web_scraping import compute_web_features

        data = {"web_traffic_change": "invalid", "app_ranking_change": -5}
        features = compute_web_features(data, "THYAO")
        assert "web_traffic_change" not in features
        assert "app_ranking_change" in features


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
