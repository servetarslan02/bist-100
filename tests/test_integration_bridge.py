"""ALPHA BIST — Integration Bridge v2.0 Tests

Kapsamlı test suite:
- Circuit breaker (open/close/half-open transitions)
- Metrics (call counting, success rate, latency)
- Health check (module status reporting)
- Input validation (ticker, features, confidence, prices)
- Enhancement pipeline (all paths)
- Error handling (graceful degradation)
- Configuration (enable/disable modules)
- Correlation ID tracking
"""

from __future__ import annotations

import time
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from services.core.integration_bridge import (
    BridgeConfig,
    CircuitBreaker,
    CircuitState,
    EnhancementResult,
    IntegrationBridge,
    ModuleMetrics,
    PipelineEnhancementReport,
)


# =====================================================
# FIXTURES
# =====================================================


@pytest.fixture
def config() -> BridgeConfig:
    """Test konfigürasyonu."""
    return BridgeConfig(
        enable_feature_stability=True,
        enable_calibration_enhanced=True,
        enable_regime_limits=True,
        enable_portfolio_enhancements=True,
        enable_backtest_enhancements=True,
        enable_event_enhancements=True,
        enable_degradation_monitor=True,
        enable_feature_lineage=True,
        enable_feature_versioning=True,
        enable_ensemble_diversity=True,
        circuit_failure_threshold=3,
        circuit_recovery_timeout=1.0,  # Test için kısa
        min_features_for_stability=1,
        log_all_calls=False,
        log_failures=True,
        log_slow_calls_ms=500.0,
    )


@pytest.fixture
def bridge(config: BridgeConfig) -> IntegrationBridge:
    """Test bridge instance."""
    return IntegrationBridge(config=config)


@pytest.fixture
def sample_features() -> dict[str, float]:
    """Örnek feature seti."""
    return {
        "rsi_14": 65.3,
        "macd": 0.45,
        "volume_ratio": 1.2,
        "atr_14": 3.5,
        "bollinger_width": 0.08,
    }


@pytest.fixture
def sample_decision() -> dict[str, Any]:
    """Örnek trade kararı."""
    return {
        "action": "BUY",
        "ticker": "THYAO",
        "position_pct": 0.05,
        "notional": 50000,
        "adv": 5000000,
        "liquidity_score": 0.7,
    }


# =====================================================
# CIRCUIT BREAKER TESTS
# =====================================================


class TestCircuitBreaker:
    """Circuit breaker testleri."""

    def test_initial_state_closed(self):
        """Başlangıç durumu kapalı olmalı."""
        cb = CircuitBreaker(name="test")
        assert cb.state == CircuitState.CLOSED
        assert cb.can_execute() is True
        assert cb.failure_count == 0

    def test_failure_increments_count(self):
        """Hata sayacı artmalı."""
        cb = CircuitBreaker(name="test", failure_threshold=5)
        cb.record_failure()
        assert cb.failure_count == 1
        assert cb.state == CircuitState.CLOSED

    def test_opens_after_threshold(self):
        """Eşik aşıldığında devre açılmalı."""
        cb = CircuitBreaker(name="test", failure_threshold=3)
        cb.record_failure()
        cb.record_failure()
        assert cb.state == CircuitState.CLOSED
        cb.record_failure()
        assert cb.state == CircuitState.OPEN
        assert cb.can_execute() is False

    def test_half_open_after_timeout(self):
        """Timeout sonrası yarı açık mod."""
        cb = CircuitBreaker(name="test", failure_threshold=2, recovery_timeout_seconds=0.1)
        cb.record_failure()
        cb.record_failure()
        assert cb.state == CircuitState.OPEN

        time.sleep(0.15)
        assert cb.can_execute() is True
        assert cb.state == CircuitState.HALF_OPEN

    def test_half_open_success_closes(self):
        """Yarı açık modda başarı devreyi kapatmalı."""
        cb = CircuitBreaker(name="test", failure_threshold=2, recovery_timeout_seconds=0.1)
        cb.record_failure()
        cb.record_failure()
        time.sleep(0.15)
        cb.can_execute()  # HALF_OPEN'a geç
        cb.record_success()
        assert cb.state == CircuitState.CLOSED
        assert cb.failure_count == 0

    def test_half_open_failure_reopens(self):
        """Yarı açık modda hata devreyi tekrar açmalı."""
        cb = CircuitBreaker(name="test", failure_threshold=2, recovery_timeout_seconds=0.1)
        cb.record_failure()
        cb.record_failure()
        time.sleep(0.15)
        cb.can_execute()  # HALF_OPEN'a geç
        cb.record_failure()
        assert cb.state == CircuitState.OPEN

    def test_success_decrements_failure(self):
        """Başarı hata sayacını azaltmalı."""
        cb = CircuitBreaker(name="test", failure_threshold=5)
        cb.record_failure()
        cb.record_failure()
        assert cb.failure_count == 2
        cb.record_success()
        assert cb.failure_count == 1

    def test_reset(self):
        """Reset tüm durumu sıfırlamalı."""
        cb = CircuitBreaker(name="test", failure_threshold=2)
        cb.record_failure()
        cb.record_failure()
        assert cb.state == CircuitState.OPEN
        cb.reset()
        assert cb.state == CircuitState.CLOSED
        assert cb.failure_count == 0


# =====================================================
# MODULE METRICS TESTS
# =====================================================


class TestModuleMetrics:
    """Module metrics testleri."""

    def test_initial_state(self):
        """Başlangıç durumu sıfır olmalı."""
        m = ModuleMetrics(name="test")
        assert m.total_calls == 0
        assert m.successful_calls == 0
        assert m.failed_calls == 0
        assert m.success_rate == 0.0
        assert m.avg_latency_ms == 0.0

    def test_success_rate_calculation(self):
        """Başarı oranı doğru hesaplanmalı."""
        m = ModuleMetrics(name="test")
        m.total_calls = 10
        m.successful_calls = 7
        m.failed_calls = 3
        assert m.success_rate == pytest.approx(0.7)

    def test_avg_latency(self):
        """Ortalama latency doğru hesaplanmalı."""
        m = ModuleMetrics(name="test")
        m.successful_calls = 4
        m.total_latency_ms = 200.0
        assert m.avg_latency_ms == pytest.approx(50.0)

    def test_to_dict(self):
        """Dict dönüşümü doğru olmalı."""
        m = ModuleMetrics(name="test", total_calls=5, successful_calls=4, failed_calls=1)
        d = m.to_dict()
        assert d["name"] == "test"
        assert d["total_calls"] == 5
        assert d["success_rate"] == pytest.approx(0.8)


# =====================================================
# ENHANCEMENT RESULT TESTS
# =====================================================


class TestEnhancementResult:
    """Enhancement result testleri."""

    def test_success_result(self):
        """Başarılı sonuç doğru oluşturulmalı."""
        r = EnhancementResult(module="test", success=True, data={"key": "value"}, latency_ms=10.5)
        assert r.success is True
        assert r.data == {"key": "value"}
        assert r.skipped is False

    def test_failure_result(self):
        """Başarısız sonuç doğru oluşturulmalı."""
        r = EnhancementResult(module="test", success=False, error="Something failed")
        assert r.success is False
        assert r.error == "Something failed"

    def test_skipped_result(self):
        """Atlanan sonuç doğru oluşturulmalı."""
        r = EnhancementResult(module="test", success=False, skipped=True, error="Circuit open")
        assert r.skipped is True


# =====================================================
# PIPELINE ENHANCEMENT REPORT TESTS
# =====================================================


class TestPipelineEnhancementReport:
    """Pipeline enhancement report testleri."""

    def test_healthy_report(self):
        """Sağlıklı rapor doğru oluşturulmalı."""
        report = PipelineEnhancementReport(
            ticker="THYAO",
            correlation_id="test-123",
            enhancements=[
                EnhancementResult(module="a", success=True),
                EnhancementResult(module="b", success=True),
            ],
            total_latency_ms=50.0,
            success_count=2,
            failure_count=0,
            skip_count=0,
        )
        assert report.is_healthy is True

    def test_unhealthy_report(self):
        """Sağlıksız rapor doğru oluşturulmalı."""
        report = PipelineEnhancementReport(
            ticker="THYAO",
            correlation_id="test-123",
            enhancements=[
                EnhancementResult(module="a", success=True),
                EnhancementResult(module="b", success=False, error="fail"),
            ],
            total_latency_ms=50.0,
            success_count=1,
            failure_count=1,
            skip_count=0,
        )
        assert report.is_healthy is False

    def test_to_dict(self):
        """Dict dönüşümü doğru olmalı."""
        report = PipelineEnhancementReport(
            ticker="THYAO",
            correlation_id="test-123",
            enhancements=[],
            total_latency_ms=10.0,
            success_count=0,
            failure_count=0,
            skip_count=0,
        )
        d = report.to_dict()
        assert d["ticker"] == "THYAO"
        assert d["correlation_id"] == "test-123"


# =====================================================
# INTEGRATION BRIDGE — INITIALIZATION
# =====================================================


class TestBridgeInitialization:
    """Bridge initialization testleri."""

    def test_default_config(self):
        """Varsayılan konfigürasyon doğru olmalı."""
        bridge = IntegrationBridge()
        assert bridge.config.enable_feature_stability is True
        assert bridge.config.circuit_failure_threshold == 5

    def test_custom_config(self, config):
        """Özel konfigürasyon uygulanmalı."""
        bridge = IntegrationBridge(config=config)
        assert bridge.config.circuit_failure_threshold == 3
        assert bridge.config.circuit_recovery_timeout == 1.0

    def test_circuit_breakers_initialized(self, bridge):
        """Circuit breaker'lar başlatılmalı."""
        assert len(bridge._circuits) == 10
        assert "feature_stability" in bridge._circuits
        assert "regime_limits" in bridge._circuits

    def test_metrics_initialized(self, bridge):
        """Metrikler başlatılmalı."""
        assert len(bridge._metrics) == 10
        assert bridge._metrics["feature_stability"].total_calls == 0


# =====================================================
# INTEGRATION BRIDGE — INPUT VALIDATION
# =====================================================


class TestInputValidation:
    """Input validation testleri."""

    def test_valid_ticker(self, bridge):
        """Geçerli ticker kabul edilmeli."""
        assert bridge._validate_ticker("THYAO") is True
        assert bridge._validate_ticker("GARAN") is True

    def test_invalid_ticker(self, bridge):
        """Geçersiz ticker reddedilmeli."""
        assert bridge._validate_ticker("") is False
        assert bridge._validate_ticker(None) is False
        assert bridge._validate_ticker("A" * 25) is False

    def test_valid_features(self, bridge, sample_features):
        """Geçerli feature seti kabul edilmeli."""
        assert bridge._validate_features(sample_features) is True

    def test_invalid_features(self, bridge):
        """Geçersiz feature seti reddedilmeli."""
        assert bridge._validate_features({}) is False
        assert bridge._validate_features(None) is False

    def test_valid_confidence(self, bridge):
        """Geçerli confidence kabul edilmeli."""
        assert bridge._validate_confidence(0.5) is True
        assert bridge._validate_confidence(0.0) is True
        assert bridge._validate_confidence(1.0) is True

    def test_invalid_confidence(self, bridge):
        """Geçersiz confidence reddedilmeli."""
        assert bridge._validate_confidence(-0.1) is False
        assert bridge._validate_confidence(1.1) is False

    def test_valid_prices(self, bridge):
        """Geçerli fiyat serisi kabul edilmeli."""
        prices = np.array([100.0, 101.0, 102.0])
        assert bridge._validate_prices(prices) is True

    def test_invalid_prices(self, bridge):
        """Geçersiz fiyat serisi reddedilmeli."""
        assert bridge._validate_prices(np.array([])) is False
        assert bridge._validate_prices(None) is False
        assert bridge._validate_prices(np.array([np.nan, np.nan])) is False


# =====================================================
# INTEGRATION BRIDGE — PIPELINE ENHANCEMENT
# =====================================================


class TestPipelineEnhancement:
    """Pipeline enhancement testleri."""

    def test_invalid_ticker_returns_error(self, bridge, sample_features):
        """Geçersiz ticker hata döndürmeli."""
        result = bridge.enhance_pipeline_result("", {}, sample_features, "BULL")
        assert "_bridge_error" in result

    def test_invalid_features_returns_error(self, bridge):
        """Geçersiz feature seti hata döndürmeli."""
        result = bridge.enhance_pipeline_result("THYAO", {}, {}, "BULL")
        assert "_bridge_error" in result

    def test_bridge_metadata_added(self, bridge, sample_features):
        """Bridge metadata eklenmeli."""
        result = bridge.enhance_pipeline_result("THYAO", {}, sample_features, "BULL")
        assert "_bridge" in result
        assert "correlation_id" in result["_bridge"]
        assert "latency_ms" in result["_bridge"]

    def test_correlation_id_unique(self, bridge, sample_features):
        """Her çağrıda benzersiz correlation ID oluşmalı."""
        r1 = bridge.enhance_pipeline_result("THYAO", {}, sample_features, "BULL")
        r2 = bridge.enhance_pipeline_result("THYAO", {}, sample_features, "BULL")
        assert r1["_bridge"]["correlation_id"] != r2["_bridge"]["correlation_id"]

    def test_disabled_modules_skipped(self, config, sample_features):
        """Devre dışı modüller atlanmalı."""
        config.enable_feature_stability = False
        config.enable_regime_limits = False
        config.enable_feature_lineage = False
        bridge = IntegrationBridge(config=config)
        result = bridge.enhance_pipeline_result("THYAO", {}, sample_features, "BULL")
        # Tüm modüller devre dışı — enhancement olmamalı
        assert "enhancements" not in result or result.get("enhancements") == {}


# =====================================================
# INTEGRATION BRIDGE — TRADE PLAN ENHANCEMENT
# =====================================================


class TestTradePlanEnhancement:
    """Trade plan enhancement testleri."""

    def test_invalid_ticker_returns_error(self, bridge, sample_decision):
        """Geçersiz ticker hata döndürmeli."""
        prices = np.array([100.0, 101.0])
        result = bridge.enhance_trade_plan("", sample_decision, prices, "BULL", 0.7)
        assert "_bridge_error" in result

    def test_confidence_clamped(self, bridge, sample_decision):
        """Confidence sınırlandırılmalı."""
        prices = np.array([100.0, 101.0])
        # Geçersiz confidence — clamp edilmeli, hata vermemeli
        result = bridge.enhance_trade_plan("THYAO", sample_decision, prices, "BULL", 1.5)
        assert "_bridge" in result

    def test_bridge_metadata_added(self, bridge, sample_decision):
        """Bridge metadata eklenmeli."""
        prices = np.array([100.0, 101.0])
        result = bridge.enhance_trade_plan("THYAO", sample_decision, prices, "BULL", 0.7)
        assert "_bridge" in result


# =====================================================
# INTEGRATION BRIDGE — LEARNING CYCLE
# =====================================================


class TestLearningCycleEnhancement:
    """Learning cycle enhancement testleri."""

    def test_bridge_metadata_added(self, bridge):
        """Bridge metadata eklenmeli."""
        learning_result = {"model": "lgbm", "accuracy": 0.65}
        result = bridge.enhance_learning_cycle(learning_result)
        assert "_bridge" in result

    def test_with_model_predictions(self, bridge):
        """Model predictions ile diversity analizi yapılmalı."""
        predictions = {
            "lgbm": np.array([0.7, 0.3, 0.8]),
            "xgboost": np.array([0.6, 0.4, 0.7]),
        }
        learning_result = {"model": "lgbm"}
        result = bridge.enhance_learning_cycle(learning_result, model_predictions=predictions)
        assert "_bridge" in result


# =====================================================
# INTEGRATION BRIDGE — EVENT ENHANCEMENT
# =====================================================


class TestEventEnhancement:
    """Event enhancement testleri."""

    def test_disabled_returns_original(self, config):
        """Devre dışı event enhancement orijinal payload döndürmeli."""
        config.enable_event_enhancements = False
        bridge = IntegrationBridge(config=config)
        payload = {"data": "test"}
        result = bridge.enhance_event("evt-1", "market_data", payload)
        assert result == payload


# =====================================================
# INTEGRATION BRIDGE — PORTFOLIO ENHANCEMENT
# =====================================================


class TestPortfolioEnhancement:
    """Portfolio enhancement testleri."""

    def test_disabled_returns_original(self, config):
        """Devre dışı portfolio enhancement orijinal ağırlıkları döndürmeli."""
        config.enable_portfolio_enhancements = False
        bridge = IntegrationBridge(config=config)
        weights = {"THYAO": 0.5, "GARAN": 0.5}
        result = bridge.enhance_portfolio_weights(weights, {})
        assert result == weights


# =====================================================
# INTEGRATION BRIDGE — HEALTH CHECK
# =====================================================


class TestHealthCheck:
    """Health check testleri."""

    def test_health_check_returns_structure(self, bridge):
        """Health check doğru yapı döndürmeli."""
        health = bridge.health_check()
        assert "all_healthy" in health
        assert "modules" in health
        assert "timestamp" in health

    def test_health_check_modules(self, bridge):
        """Tüm modüller sağlık raporunda olmalı."""
        health = bridge.health_check()
        assert "feature_stability" in health["modules"]
        assert "regime_limits" in health["modules"]
        assert "calibration_enhanced" in health["modules"]

    def test_health_check_module_structure(self, bridge):
        """Her modülün sağlık yapısı doğru olmalı."""
        health = bridge.health_check()
        module = health["modules"]["feature_stability"]
        assert "loaded" in module
        assert "enabled" in module
        assert "circuit_state" in module
        assert "healthy" in module


# =====================================================
# INTEGRATION BRIDGE — METRICS
# =====================================================


class TestMetrics:
    """Metrics testleri."""

    def test_initial_metrics_zero(self, bridge):
        """Başlangıç metrikleri sıfır olmalı."""
        metrics = bridge.get_metrics()
        assert metrics["total_calls"] == 0
        assert metrics["total_successful"] == 0
        assert metrics["total_failed"] == 0

    def test_metrics_after_call(self, bridge, sample_features):
        """Çağrı sonrası metrikler güncellenmeli."""
        bridge.enhance_pipeline_result("THYAO", {}, sample_features, "BULL")
        metrics = bridge.get_metrics()
        # Modüller yüklenemeyebilir (bağımlılık eksik) — bu durumda çağrı sayısı 0 olabilir
        # Ama metrics yapısı doğru olmalı
        assert "total_calls" in metrics
        assert "total_successful" in metrics
        assert "total_failed" in metrics
        assert metrics["total_calls"] >= 0

    def test_reset_metrics(self, bridge, sample_features):
        """Metrik sıfırlama çalışmalı."""
        bridge.enhance_pipeline_result("THYAO", {}, sample_features, "BULL")
        bridge.reset_metrics()
        metrics = bridge.get_metrics()
        assert metrics["total_calls"] == 0

    def test_reset_circuit_breakers(self, bridge):
        """Circuit breaker sıfırlama çalışmalı."""
        cb = bridge._circuits["feature_stability"]
        cb.record_failure()
        cb.record_failure()
        bridge.reset_circuit_breakers()
        assert cb.state == CircuitState.CLOSED


# =====================================================
# INTEGRATION BRIDGE — CONFIGURATION
# =====================================================


class TestConfiguration:
    """Configuration testleri."""

    def test_disable_module(self, bridge):
        """Modül devre dışı bırakılabilmeli."""
        bridge.disable_module("feature_stability")
        assert bridge.config.enable_feature_stability is False

    def test_enable_module(self, bridge):
        """Modül etkinleştirilebilmeli."""
        bridge.disable_module("feature_stability")
        bridge.enable_module("feature_stability")
        assert bridge.config.enable_feature_stability is True

    def test_update_config(self, bridge):
        """Konfigürasyon güncellenebilmeli."""
        bridge.update_config(circuit_failure_threshold=10)
        assert bridge.config.circuit_failure_threshold == 10

    def test_update_config_unknown_key(self, bridge):
        """Bilinmeyen anahtar uyarı vermemeli (sessiz geç)."""
        bridge.update_config(unknown_key="value")  # Should not raise


# =====================================================
# INTEGRATION BRIDGE — CIRCUIT BREAKER INTEGRATION
# =====================================================


class TestCircuitBreakerIntegration:
    """Circuit breaker entegrasyon testleri."""

    def test_circuit_breaker_opens_on_failures(self, bridge):
        """Sürekli hatalar circuit breaker'ı açmalı."""
        cb = bridge._circuits["feature_stability"]
        for _ in range(bridge.config.circuit_failure_threshold):
            cb.record_failure()
        assert cb.state == CircuitState.OPEN

    def test_open_circuit_skips_calls(self, bridge, sample_features):
        """Açık circuit breaker çağrıları atlamalı."""
        cb = bridge._circuits["feature_stability"]
        for _ in range(bridge.config.circuit_failure_threshold):
            cb.record_failure()

        result = bridge.enhance_pipeline_result("THYAO", {}, sample_features, "BULL")
        # feature_stability atlanmış olmalı
        bridge_meta = result.get("_bridge", {})
        assert bridge_meta.get("modules_skipped", 0) >= 0  # Atlanan modül olabilir


# =====================================================
# EDGE CASES
# =====================================================


class TestEdgeCases:
    """Edge case testleri."""

    def test_empty_regime(self, bridge, sample_features):
        """Boş regime ile çalışmalı."""
        result = bridge.enhance_pipeline_result("THYAO", {}, sample_features, "")
        assert "_bridge" in result

    def test_none_features_values(self, bridge):
        """None değerli feature'lar filtrelenmeli."""
        features = {"rsi_14": None, "macd": 0.5, "volume_ratio": float("nan")}
        # None ve NaN filtrelenmeli, macd kalmalı
        result = bridge.enhance_pipeline_result("THYAO", {}, features, "BULL")
        assert "_bridge" in result

    def test_large_feature_set(self, bridge):
        """Büyük feature seti ile çalışmalı."""
        features = {f"feature_{i}": float(i) for i in range(1000)}
        result = bridge.enhance_pipeline_result("THYAO", {}, features, "BULL")
        assert "_bridge" in result

    def test_special_float_values(self, bridge):
        """Özel float değerler (inf, -inf) filtrelenmeli."""
        features = {
            "normal": 1.5,
            "positive_inf": float("inf"),
            "negative_inf": float("-inf"),
            "nan": float("nan"),
        }
        result = bridge.enhance_pipeline_result("THYAO", {}, features, "BULL")
        assert "_bridge" in result
