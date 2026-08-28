"""ALPHA BIST — Integration Bridge v2.0 (Production-Hardened)

Tüm yeni modülleri asıl motorlara bağlayan entegrasyon katmanı.
Bu dosya, orchestrator ve learning pipeline tarafından çağrılır.

v2.0 Eklemeleri:
- Circuit breaker pattern (modül sürekli hata verirse otomatik devre dışı)
- Health check (tüm modüllerin bağlantı durumu)
- Metrics (çağrı sayısı, başarı/hata oranı, latency)
- Konfigürasyon (modül enable/disable, eşikler)
- Structured error aggregation (raporlanabilir hata yönetimi)
- Input validation (modüllere veri geçmeden önce doğrulama)
- Correlation ID (tüm modüller arası izleme)
- Graceful degradation (kısmi hatalarda bile çalış)

Kullanım:
    from services.core.integration_bridge import integration_bridge

    # Pipeline her hisse için çağrılır
    result = integration_bridge.enhance_pipeline_result(ticker, result, features, regime)

    # Learning cycle'da çağrılır
    learning_result = integration_bridge.enhance_learning_cycle(learning_result)

    # Trade plan'da çağrılır
    plan = integration_bridge.enhance_trade_plan(ticker, decision, prices, regime)

    # Sağlık kontrolü
    health = integration_bridge.health_check()

    # Metrikler
    metrics = integration_bridge.get_metrics()
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

import functools
import numpy as np
import structlog
from opentelemetry import trace

logger = structlog.get_logger(__name__)
tracer = trace.get_tracer("alpha-bist.integration_bridge")

def otel_trace(span_name: str):
    """Decorator to wrap a method in an OTel span."""
    def decorator(func):
        @functools.wraps(func)
        def wrapper(self, *args, **kwargs):
            with tracer.start_as_current_span(span_name):
                return func(self, *args, **kwargs)
        return wrapper
    return decorator


# =====================================================
# CIRCUIT BREAKER
# =====================================================


class CircuitState(Enum):
    """Circuit breaker durumu."""

    CLOSED = "closed"  # Normal çalışıyor
    OPEN = "open"  # Devre açık — çağrılar reddediliyor
    HALF_OPEN = "half_open"  # Test modu — tek çağrıya izin ver


@dataclass
class CircuitBreaker:
    """Circuit breaker — modül hatalarını izler ve otomatik devre dışı bırakır.

    Kapalı (normal) → Açık (devre dışı) → Yarı açık (test) → Kapalı (normale döndü)
    """

    name: str
    failure_threshold: int = 5  # Kaç hata sonrası devre açılsın
    recovery_timeout_seconds: float = 300.0  # Ne kadar süre açık kalsın (5 dk)
    half_open_max_calls: int = 1  # Yarı açık modda kaç test çağrısı

    _state: CircuitState = field(default=CircuitState.CLOSED, repr=False)
    _failure_count: int = field(default=0, repr=False)
    _success_count: int = field(default=0, repr=False)
    _last_failure_time: float = field(default=0.0, repr=False)
    _half_open_calls: int = field(default=0, repr=False)

    def can_execute(self) -> bool:
        """Çağrı yapılabilir mi?"""
        if self._state == CircuitState.CLOSED:
            return True

        if self._state == CircuitState.OPEN:
            # Recovery timeout doldu mu?
            if time.time() - self._last_failure_time >= self.recovery_timeout_seconds:
                self._state = CircuitState.HALF_OPEN
                self._half_open_calls = 0
                logger.info("circuit_breaker_half_open", name=self.name)
                return True
            return False

        if self._state == CircuitState.HALF_OPEN:
            return self._half_open_calls < self.half_open_max_calls

        return False

    def record_success(self) -> None:
        """Başarılı çağrı kaydet."""
        if self._state == CircuitState.HALF_OPEN:
            self._success_count += 1
            # Yarı açık modda başarılı → kapat
            self._state = CircuitState.CLOSED
            self._failure_count = 0
            self._success_count = 0
            logger.info("circuit_breaker_closed", name=self.name)
        elif self._state == CircuitState.CLOSED:
            self._failure_count = max(0, self._failure_count - 1)  # Başarı hatayı azaltır

    def record_failure(self) -> None:
        """Başarısız çağrı kaydet."""
        self._failure_count += 1
        self._last_failure_time = time.time()

        if self._state == CircuitState.HALF_OPEN:
            # Yarı açık modda hata → tekrar aç
            self._state = CircuitState.OPEN
            logger.warning("circuit_breaker_reopened", name=self.name)
        elif self._state == CircuitState.CLOSED:
            if self._failure_count >= self.failure_threshold:
                self._state = CircuitState.OPEN
                logger.warning(
                    "circuit_breaker_opened",
                    name=self.name,
                    failures=self._failure_count,
                    threshold=self.failure_threshold,
                )

    @property
    def state(self) -> CircuitState:
        return self._state

    @property
    def failure_count(self) -> int:
        return self._failure_count

    def reset(self) -> None:
        """Circuit breaker'ı sıfırla."""
        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._success_count = 0
        self._last_failure_time = 0.0
        self._half_open_calls = 0


# =====================================================
# MODULE METRICS
# =====================================================


@dataclass
class ModuleMetrics:
    """Tek modül için metrikler."""

    name: str
    total_calls: int = 0
    successful_calls: int = 0
    failed_calls: int = 0
    skipped_calls: int = 0  # Circuit breaker açıkken atlanan
    total_latency_ms: float = 0.0
    last_call_time: float = 0.0
    last_error: str = ""

    @property
    def success_rate(self) -> float:
        if self.total_calls == 0:
            return 0.0
        return self.successful_calls / self.total_calls

    @property
    def avg_latency_ms(self) -> float:
        if self.successful_calls == 0:
            return 0.0
        return self.total_latency_ms / self.successful_calls

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "total_calls": self.total_calls,
            "successful_calls": self.successful_calls,
            "failed_calls": self.failed_calls,
            "skipped_calls": self.skipped_calls,
            "success_rate": round(self.success_rate, 4),
            "avg_latency_ms": round(self.avg_latency_ms, 2),
            "last_error": self.last_error[:200] if self.last_error else "",
        }


# =====================================================
# ENHANCEMENT RESULT
# =====================================================


@dataclass
class EnhancementResult:
    """Tek enhancement sonucu."""

    module: str
    success: bool
    data: dict[str, Any] | None = None
    error: str | None = None
    latency_ms: float = 0.0
    skipped: bool = False


@dataclass
class PipelineEnhancementReport:
    """Pipeline enhancement raporu — tüm modüllerin sonuçları."""

    ticker: str
    correlation_id: str
    enhancements: list[EnhancementResult]
    total_latency_ms: float
    success_count: int
    failure_count: int
    skip_count: int

    @property
    def is_healthy(self) -> bool:
        return self.failure_count == 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "ticker": self.ticker,
            "correlation_id": self.correlation_id,
            "total_latency_ms": round(self.total_latency_ms, 2),
            "success_count": self.success_count,
            "failure_count": self.failure_count,
            "skip_count": self.skip_count,
            "is_healthy": self.is_healthy,
            "modules": [
                {
                    "module": e.module,
                    "success": e.success,
                    "skipped": e.skipped,
                    "latency_ms": round(e.latency_ms, 2),
                    "error": e.error[:200] if e.error else None,
                }
                for e in self.enhancements
            ],
        }


# =====================================================
# BRIDGE CONFIGURATION
# =====================================================


@dataclass
class BridgeConfig:
    """Integration Bridge konfigürasyonu."""

    # Modül enable/disable
    enable_feature_stability: bool = True
    enable_calibration_enhanced: bool = True
    enable_regime_limits: bool = True
    enable_portfolio_enhancements: bool = True
    enable_backtest_enhancements: bool = True
    enable_event_enhancements: bool = True
    enable_degradation_monitor: bool = True
    enable_feature_lineage: bool = True
    enable_feature_versioning: bool = True
    enable_ensemble_diversity: bool = True

    # Circuit breaker ayarları
    circuit_failure_threshold: int = 5
    circuit_recovery_timeout: float = 300.0

    # Validation
    min_features_for_stability: int = 1
    min_confidence: float = 0.0
    max_confidence: float = 1.0

    # Logging
    log_all_calls: bool = False
    log_failures: bool = True
    log_slow_calls_ms: float = 1000.0  # 1 saniyeden yavaş çağrıları logla


# =====================================================
# INTEGRATION BRIDGE v2.0
# =====================================================


class IntegrationBridge:
    """Tüm yeni modülleri asıl motorlara bağlayan entegrasyon katmanı v2.0.

    Modüller:
    - FeatureStabilityAnalyzer → feature drift tespiti
    - CalibrationEnhanced → confidence kalibrasyon
    - RegimeLimitsManager → rejime göre risk limitleri
    - PortfolioEnhancements → turnover/hysteresis/constraints
    - BacktestEnhancements → T+1/market impact/delisted
    - EventEnhancements → idempotency/retry/correlation
    - WalkForwardEnsemble → WF ensemble eğitimi
    - ModelDegradationMonitor → model degradation
    - FeatureSelector → feature selection
    - FeatureLineageTracker → feature lineage
    - FeatureVersionManager → feature versioning

    v2.0 Eklemeleri:
    - Circuit breaker pattern
    - Health check
    - Metrics
    - Configuration
    - Input validation
    - Correlation ID tracking
    """

    def __init__(self, config: BridgeConfig | None = None):
        self.config = config or BridgeConfig()
        self._initialized = False

        # Module references
        self._feature_stability = None
        self._calibration_enhanced = None
        self._regime_limits = None
        self._portfolio_enhancements = None
        self._backtest_enhancements = None
        self._event_enhancements = None
        self._degradation_monitor = None
        self._feature_lineage = None
        self._feature_version_manager = None

        # Circuit breakers — her modül için ayrı
        self._circuits: dict[str, CircuitBreaker] = {}
        self._init_circuit_breakers()

        # Metrics
        self._metrics: dict[str, ModuleMetrics] = {}
        self._init_metrics()

        # Correlation ID counter
        self._call_counter = 0

    def _init_circuit_breakers(self) -> None:
        """Her modül için circuit breaker oluştur."""
        module_names = [
            "feature_stability",
            "calibration_enhanced",
            "regime_limits",
            "portfolio_enhancements",
            "backtest_enhancements",
            "event_enhancements",
            "degradation_monitor",
            "feature_lineage",
            "feature_versioning",
            "ensemble_diversity",
        ]
        for name in module_names:
            self._circuits[name] = CircuitBreaker(
                name=name,
                failure_threshold=self.config.circuit_failure_threshold,
                recovery_timeout_seconds=self.config.circuit_recovery_timeout,
            )

    def _init_metrics(self) -> None:
        """Her modül için metrik oluştur."""
        module_names = [
            "feature_stability",
            "calibration_enhanced",
            "regime_limits",
            "portfolio_enhancements",
            "backtest_enhancements",
            "event_enhancements",
            "degradation_monitor",
            "feature_lineage",
            "feature_versioning",
            "ensemble_diversity",
        ]
        for name in module_names:
            self._metrics[name] = ModuleMetrics(name=name)

    def _ensure_initialized(self) -> None:
        """Lazy initialization — sadece gerektiğinde import et."""
        if self._initialized:
            return

        self._load_module("feature_stability", "services.ml.feature_stability", "feature_stability")
        self._load_module("calibration_enhanced", "services.ml.calibration_enhanced", "calibration_enhanced")
        self._load_module("regime_limits", "services.risk.regime_limits", "regime_limits")
        self._load_module(
            "portfolio_enhancements", "services.portfolio.portfolio_enhancements", "portfolio_enhancements"
        )
        self._load_module("backtest_enhancements", "services.backtest.backtest_enhancements", "backtest_enhancements")
        self._load_module("event_enhancements", "services.core.event_enhancements", "event_enhancements")
        self._load_module("degradation_monitor", "services.learning.model_degradation_monitor", "degradation_monitor")
        self._load_module("feature_lineage", "services.features.lineage", "feature_lineage")
        self._load_module("feature_versioning", "services.features.versioning", "feature_version_manager")

        self._initialized = True

    def _load_module(self, attr_name: str, module_path: str, singleton_name: str) -> None:
        """Modülü güvenli şekilde yükle."""
        try:
            import importlib

            mod = importlib.import_module(module_path)
            instance = getattr(mod, singleton_name)
            setattr(self, f"_{attr_name}", instance)
            logger.debug("module_loaded", module=attr_name)
        except Exception as e:
            logger.warning("module_load_failed", module=attr_name, error=str(e))
            setattr(self, f"_{attr_name}", None)

    def _generate_correlation_id(self) -> str:
        """Correlation ID üret."""
        self._call_counter += 1
        return f"bridge-{uuid.uuid4().hex[:12]}-{self._call_counter:06d}"

    def _execute_with_circuit_breaker(
        self,
        module_name: str,
        func: Any,
        *args: Any,
        **kwargs: Any,
    ) -> EnhancementResult:
        """Circuit breaker ile modül çağrısı yap.

        Args:
            module_name: Modül adı
            func: Çağrılacak fonksiyon
            *args, **kwargs: Fonksiyon argümanları

        Returns:
            EnhancementResult
        """
        circuit = self._circuits.get(module_name)
        metrics = self._metrics.get(module_name)

        # Circuit breaker kontrolü
        if circuit and not circuit.can_execute():
            if metrics:
                metrics.skipped_calls += 1
                metrics.total_calls += 1
            if self.config.log_failures:
                logger.debug("circuit_breaker_skipped", module=module_name)
            return EnhancementResult(
                module=module_name,
                success=False,
                error=f"Circuit breaker OPEN — {circuit.failure_count} failures",
                skipped=True,
            )

        # Çağrı yap
        start_time = time.time()
        try:
            result_data = func(*args, **kwargs)
            latency_ms = (time.time() - start_time) * 1000

            # Başarı kaydet
            if circuit:
                circuit.record_success()
            if metrics:
                metrics.total_calls += 1
                metrics.successful_calls += 1
                metrics.total_latency_ms += latency_ms
                metrics.last_call_time = time.time()

            # Yavaş çağrı uyarısı
            if latency_ms > self.config.log_slow_calls_ms:
                logger.warning("slow_module_call", module=module_name, latency_ms=round(latency_ms, 2))

            if self.config.log_all_calls:
                logger.debug("module_call_success", module=module_name, latency_ms=round(latency_ms, 2))

            return EnhancementResult(
                module=module_name,
                success=True,
                data=result_data,
                latency_ms=latency_ms,
            )

        except Exception as e:
            latency_ms = (time.time() - start_time) * 1000
            error_msg = str(e)

            # Hata kaydet
            if circuit:
                circuit.record_failure()
            if metrics:
                metrics.total_calls += 1
                metrics.failed_calls += 1
                metrics.last_error = error_msg
                metrics.last_call_time = time.time()

            if self.config.log_failures:
                logger.warning(
                    "module_call_failed",
                    module=module_name,
                    error=error_msg[:200],
                    latency_ms=round(latency_ms, 2),
                )

            return EnhancementResult(
                module=module_name,
                success=False,
                error=error_msg,
                latency_ms=latency_ms,
            )

    # =====================================================
    # INPUT VALIDATION
    # =====================================================

    def _validate_ticker(self, ticker: str) -> bool:
        """Ticker doğrulama."""
        if not ticker or not isinstance(ticker, str):
            return False
        if len(ticker) > 20:  # BIST ticker'ları kısa
            return False
        return True

    def _validate_features(self, features: dict[str, float]) -> bool:
        """Feature dict doğrulama."""
        if not isinstance(features, dict):
            return False
        if len(features) < self.config.min_features_for_stability:
            return False
        return True

    def _validate_confidence(self, confidence: float) -> bool:
        """Confidence doğrulama."""
        return self.config.min_confidence <= confidence <= self.config.max_confidence

    def _validate_prices(self, prices: np.ndarray) -> bool:
        """Fiyat serisi doğrulama."""
        if prices is None or len(prices) == 0:
            return False
        if np.all(np.isnan(prices)):
            return False
        return True

    # =====================================================
    # PIPELINE ENHANCEMENT
    # =====================================================

    @otel_trace("integration_bridge.enhance_pipeline_result")
    def enhance_pipeline_result(
        self,
        ticker: str,
        result: dict[str, Any],
        features: dict[str, float],
        regime: str,
    ) -> dict[str, Any]:
        """Pipeline sonucunu yeni modüllerle zenginleştir.

        Args:
            ticker: Hisse kodu
            result: Mevcut pipeline sonucu
            features: Hesaplanan feature'lar
            regime: Tespit edilen rejim

        Returns:
            Zenginleştirilmiş result
        """
        self._ensure_initialized()
        correlation_id = self._generate_correlation_id()
        start_time = time.time()
        enhancement_results: list[EnhancementResult] = []

        # Input validation
        if not self._validate_ticker(ticker):
            logger.warning("invalid_ticker", ticker=ticker)
            result["_bridge_error"] = "Invalid ticker"
            return result

        if not self._validate_features(features):
            logger.warning("invalid_features", ticker=ticker, n_features=len(features) if features else 0)
            result["_bridge_error"] = "Invalid features"
            return result

        enhancements: dict[str, Any] = {}

        # 1. Feature stability kontrolü
        if self.config.enable_feature_stability and self._feature_stability:
            er = self._execute_with_circuit_breaker(
                "feature_stability",
                self._check_feature_stability,
                ticker,
                features,
            )
            enhancement_results.append(er)
            if er.success and er.data:
                enhancements["feature_stability"] = er.data

        # 2. Regime limits
        if self.config.enable_regime_limits and self._regime_limits:
            er = self._execute_with_circuit_breaker(
                "regime_limits",
                self._get_regime_limits,
                regime,
            )
            enhancement_results.append(er)
            if er.success and er.data:
                enhancements["regime_limits"] = er.data

        # 3. Feature lineage
        if self.config.enable_feature_lineage and self._feature_lineage:
            er = self._execute_with_circuit_breaker(
                "feature_lineage",
                self._record_feature_lineage,
                features,
            )
            enhancement_results.append(er)

        total_latency = (time.time() - start_time) * 1000

        # Rapor oluştur
        report = PipelineEnhancementReport(
            ticker=ticker,
            correlation_id=correlation_id,
            enhancements=enhancement_results,
            total_latency_ms=total_latency,
            success_count=sum(1 for e in enhancement_results if e.success),
            failure_count=sum(1 for e in enhancement_results if not e.success and not e.skipped),
            skip_count=sum(1 for e in enhancement_results if e.skipped),
        )

        if enhancements:
            result["enhancements"] = enhancements

        # Bridge metadata
        result["_bridge"] = {
            "correlation_id": correlation_id,
            "latency_ms": round(total_latency, 2),
            "modules_called": len(enhancement_results),
            "modules_succeeded": report.success_count,
            "modules_failed": report.failure_count,
            "modules_skipped": report.skip_count,
        }

        return result

    def _check_feature_stability(self, ticker: str, features: dict[str, float]) -> dict[str, Any]:
        """Feature stability kontrolü (circuit breaker tarafından çağrılır)."""
        feature_data = {k: np.array([v]) for k, v in features.items() if isinstance(v, (int, float)) and np.isfinite(v)}
        if not feature_data:
            return {"score": 1.0, "unstable": [], "note": "No numeric features"}

        self._feature_stability.record_distribution(feature_data)
        stability_summary = self._feature_stability.check_stability()
        return {
            "score": stability_summary.overall_stability_score,
            "unstable": stability_summary.unstable_features,
            "total_features": stability_summary.total_features,
            "stable_features": stability_summary.stable_features,
            "warning_features": stability_summary.warning_features,
            "alert_features": stability_summary.alert_features,
            "critical_features": stability_summary.critical_features,
        }

    def _get_regime_limits(self, regime: str) -> dict[str, Any]:
        """Regime limits bilgisi (circuit breaker tarafından çağrılır)."""
        limits = self._regime_limits.get_limits(regime)
        return {
            "max_position_pct": limits.max_position_pct,
            "max_total_exposure": limits.max_total_exposure,
            "max_sector_concentration": limits.max_sector_concentration,
            "stop_loss_pct": limits.stop_loss_pct,
            "confidence_multiplier": limits.confidence_multiplier,
            "min_liquidity_score": limits.min_liquidity_score,
            "max_leverage": limits.max_leverage,
            "description": limits.description,
        }

    def _record_feature_lineage(self, features: dict[str, float]) -> None:
        """Feature lineage kaydı (circuit breaker tarafından çağrılır)."""
        for fname in features:
            if not self._feature_lineage.get_lineage(fname):
                self._feature_lineage.record(
                    feature_name=fname,
                    raw_sources=["market_data"],
                    transformations=["computed"],
                    computed_by="orchestrator",
                )

    # =====================================================
    # TRADE PLAN ENHANCEMENT
    # =====================================================

    @otel_trace("integration_bridge.enhance_trade_plan")
    def enhance_trade_plan(
        self,
        ticker: str,
        decision: dict[str, Any],
        prices: np.ndarray,
        regime: str,
        confidence: float = 0.5,
    ) -> dict[str, Any]:
        """Trade planını yeni modüllerle zenginleştir.

        Args:
            ticker: Hisse kodu
            decision: Karar sonucu
            prices: Fiyat serisi
            regime: Rejim
            confidence: Model confidence

        Returns:
            Zenginleştirilmiş trade planı
        """
        self._ensure_initialized()
        correlation_id = self._generate_correlation_id()
        start_time = time.time()
        enhancement_results: list[EnhancementResult] = []

        # Input validation
        if not self._validate_ticker(ticker):
            decision["_bridge_error"] = "Invalid ticker"
            return decision

        if not self._validate_confidence(confidence):
            logger.warning("invalid_confidence", ticker=ticker, confidence=confidence)
            confidence = max(0.0, min(1.0, confidence))  # Clamp

        enhancements: dict[str, Any] = {}

        # 1. Regime-aware position sizing
        if self.config.enable_regime_limits and self._regime_limits:
            er = self._execute_with_circuit_breaker(
                "regime_limits",
                self._adjust_position_for_confidence,
                decision,
                confidence,
                regime,
            )
            enhancement_results.append(er)
            if er.success and er.data:
                enhancements["regime_adjusted_size"] = er.data

        # 2. T+1 execution check
        if self.config.enable_backtest_enhancements and self._backtest_enhancements:
            er = self._execute_with_circuit_breaker(
                "backtest_enhancements",
                self._check_t_plus_1,
                ticker,
            )
            enhancement_results.append(er)
            if er.success and er.data:
                enhancements["t_plus_1"] = er.data

        # 3. Market impact estimate
        if self.config.enable_backtest_enhancements and self._backtest_enhancements:
            er = self._execute_with_circuit_breaker(
                "backtest_enhancements",
                self._estimate_market_impact,
                ticker,
                decision,
            )
            enhancement_results.append(er)
            if er.success and er.data:
                enhancements["market_impact"] = er.data

        # 4. Liquidity check
        if self.config.enable_regime_limits and self._regime_limits:
            er = self._execute_with_circuit_breaker(
                "regime_limits",
                self._check_liquidity,
                ticker,
                decision,
                regime,
            )
            enhancement_results.append(er)
            if er.success and er.data:
                enhancements["liquidity_check"] = er.data

        total_latency = (time.time() - start_time) * 1000

        if enhancements:
            decision["enhancements"] = enhancements

        decision["_bridge"] = {
            "correlation_id": correlation_id,
            "latency_ms": round(total_latency, 2),
            "modules_called": len(enhancement_results),
            "modules_succeeded": sum(1 for e in enhancement_results if e.success),
            "modules_failed": sum(1 for e in enhancement_results if not e.success and not e.skipped),
            "modules_skipped": sum(1 for e in enhancement_results if e.skipped),
        }

        return decision

    def _adjust_position_for_confidence(self, decision: dict[str, Any], confidence: float, regime: str) -> float:
        """Confidence'a göre pozisyon boyutu ayarla."""
        base_size = decision.get("position_pct", 0.05)
        return self._regime_limits.adjust_for_confidence(base_size, confidence, regime)

    def _check_t_plus_1(self, ticker: str) -> dict[str, Any]:
        """T+1 execution kontrolü."""
        from datetime import UTC, datetime

        today = datetime.now(UTC).strftime("%Y-%m-%d")
        t1_result = self._backtest_enhancements.check_t_plus_1(ticker, today)
        return {
            "can_execute": t1_result.can_execute,
            "execution_date": t1_result.execution_date,
            "delay_days": t1_result.delay_days,
            "reason": t1_result.reason,
        }

    def _estimate_market_impact(self, ticker: str, decision: dict[str, Any]) -> dict[str, Any] | None:
        """Market impact tahmini."""
        trade_size = decision.get("notional", 0)
        adv = decision.get("adv", 0)
        if trade_size <= 0 or adv <= 0:
            return None

        impact = self._backtest_enhancements.estimate_market_impact(ticker, trade_size, adv)
        return {
            "total_impact_pct": impact.total_impact_pct,
            "is_feasible": impact.is_feasible,
            "participation_rate": impact.participation_rate,
            "temporary_impact_pct": impact.temporary_impact_pct,
            "permanent_impact_pct": impact.permanent_impact_pct,
        }

    def _check_liquidity(self, ticker: str, decision: dict[str, Any], regime: str) -> dict[str, Any]:
        """Likidite kontrolü."""
        liquidity_score = decision.get("liquidity_score", 0.5)
        is_sufficient = self._regime_limits.check_liquidity(ticker, liquidity_score, regime)
        return {
            "is_sufficient": is_sufficient,
            "liquidity_score": liquidity_score,
            "min_required": self._regime_limits.get_limits(regime).min_liquidity_score,
        }

    # =====================================================
    # LEARNING CYCLE ENHANCEMENT
    # =====================================================

    @otel_trace("integration_bridge.enhance_learning_cycle")
    def enhance_learning_cycle(
        self,
        learning_result: dict[str, Any],
        model_predictions: dict[str, np.ndarray] | None = None,
    ) -> dict[str, Any]:
        """Learning cycle sonucunu zenginleştir.

        Args:
            learning_result: Mevcut learning sonucu
            model_predictions: Model tahminleri (diversity analizi için)

        Returns:
            Zenginleştirilmiş learning sonucu
        """
        self._ensure_initialized()
        correlation_id = self._generate_correlation_id()
        start_time = time.time()
        enhancement_results: list[EnhancementResult] = []

        enhancements: dict[str, Any] = {}

        # 1. Model degradation kontrolü
        if self.config.enable_degradation_monitor and self._degradation_monitor:
            er = self._execute_with_circuit_breaker(
                "degradation_monitor",
                self._check_degradation,
            )
            enhancement_results.append(er)
            if er.success and er.data:
                enhancements["degradation_status"] = er.data

        # 2. Calibration drift
        if self.config.enable_calibration_enhanced and self._calibration_enhanced:
            er = self._execute_with_circuit_breaker(
                "calibration_enhanced",
                self._check_calibration_drift,
            )
            enhancement_results.append(er)
            if er.success and er.data:
                enhancements["calibration_drift"] = er.data

        # 3. Ensemble diversity (eğer model predictions varsa)
        if self.config.enable_ensemble_diversity and model_predictions and len(model_predictions) >= 2:
            er = self._execute_with_circuit_breaker(
                "ensemble_diversity",
                self._check_ensemble_diversity,
                model_predictions,
            )
            enhancement_results.append(er)
            if er.success and er.data:
                enhancements["ensemble_diversity"] = er.data

        total_latency = (time.time() - start_time) * 1000

        if enhancements:
            learning_result["enhancements"] = enhancements

        learning_result["_bridge"] = {
            "correlation_id": correlation_id,
            "latency_ms": round(total_latency, 2),
            "modules_called": len(enhancement_results),
            "modules_succeeded": sum(1 for e in enhancement_results if e.success),
            "modules_failed": sum(1 for e in enhancement_results if not e.success and not e.skipped),
            "modules_skipped": sum(1 for e in enhancement_results if e.skipped),
        }

        return learning_result

    def _check_degradation(self) -> dict[str, Any]:
        """Model degradation kontrolü."""
        summary = self._degradation_monitor.get_model_summary()
        result: dict[str, Any] = {"models": summary}

        alerts = self._degradation_monitor.check_all_models()
        if alerts:
            result["alerts"] = [{"model": a.model_id, "severity": a.severity, "message": a.message} for a in alerts]

        return result

    def _check_calibration_drift(self) -> dict[str, Any]:
        """Calibration drift kontrolü."""
        drift = self._calibration_enhanced.check_calibration_drift()
        retrain = self._calibration_enhanced.should_retrain_calibration()
        return {
            "drift_detected": drift.drift_detected,
            "severity": drift.severity,
            "brier_change": drift.brier_change,
            "ece_change": drift.ece_change,
            "recommendation": drift.recommendation,
            "should_retrain": retrain.should_retrain,
            "retrain_reason": retrain.reason,
        }

    def _check_ensemble_diversity(self, model_predictions: dict[str, np.ndarray]) -> dict[str, Any]:
        """Ensemble diversity analizi."""
        from services.ml.ensemble import EnsembleModel

        ens = EnsembleModel()
        diversity = ens.analyze_diversity(model_predictions)
        return {
            "score": diversity.diversity_score,
            "redundant": diversity.redundant_models,
            "recommendation": diversity.recommendation,
        }

    # =====================================================
    # EVENT ENHANCEMENT
    # =====================================================

    @otel_trace("integration_bridge.enhance_event")
    def enhance_event(
        self,
        event_id: str,
        event_type: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        """Event'i zenginleştir (idempotency + correlation).

        Args:
            event_id: Event ID
            event_type: Event tipi
            payload: Event payload

        Returns:
            Zenginleştirilmiş payload
        """
        self._ensure_initialized()

        if not self.config.enable_event_enhancements or not self._event_enhancements:
            return payload

        er = self._execute_with_circuit_breaker(
            "event_enhancements",
            self._enhance_event_internal,
            event_id,
            event_type,
            payload,
        )

        if er.success and er.data:
            return er.data

        # Hata durumunda orijinal payload'ı döndür (graceful degradation)
        return payload

    def _enhance_event_internal(self, event_id: str, event_type: str, payload: dict[str, Any]) -> dict[str, Any]:
        """Event enhancement iç mantığı."""
        # Idempotency kontrolü
        if self._event_enhancements.is_duplicate(event_id):
            return {"_skipped": True, "_reason": "duplicate"}

        # Correlation ID ekle
        if "_correlation_id" not in payload:
            payload["_correlation_id"] = self._event_enhancements.generate_correlation_id()

        # Timestamp ekle
        from datetime import UTC, datetime

        payload["_timestamp"] = datetime.now(UTC).isoformat()

        # Sequence number
        payload["_sequence"] = self._event_enhancements.get_next_sequence(event_type)

        # İşlenmiş olarak işaretle
        self._event_enhancements.mark_processed(event_id)

        return payload

    # =====================================================
    # PORTFOLIO ENHANCEMENT
    # =====================================================

    @otel_trace("integration_bridge.enhance_portfolio_weights")
    def enhance_portfolio_weights(
        self,
        target_weights: dict[str, float],
        current_weights: dict[str, float],
        sector_map: dict[str, str] | None = None,
        liquidity_scores: dict[str, float] | None = None,
        regime: str = "UNKNOWN",
    ) -> dict[str, float]:
        """Portföy ağırlıklarını zenginleştir.

        Args:
            target_weights: Hedef ağırlıklar
            current_weights: Mevcut ağırlıklar
            sector_map: Sektör haritası
            liquidity_scores: Likidite skorları
            regime: Mevcut rejim

        Returns:
            Düzeltilmiş ağırlıklar
        """
        self._ensure_initialized()

        if not self.config.enable_portfolio_enhancements or not self._portfolio_enhancements:
            return target_weights

        er = self._execute_with_circuit_breaker(
            "portfolio_enhancements",
            self._enhance_portfolio_internal,
            target_weights,
            current_weights,
            sector_map,
            liquidity_scores,
            regime,
        )

        if er.success and er.data:
            return er.data

        # Hata durumunda orijinal ağırlıkları döndür (graceful degradation)
        return target_weights

    def _enhance_portfolio_internal(
        self,
        target_weights: dict[str, float],
        current_weights: dict[str, float],
        sector_map: dict[str, str] | None,
        liquidity_scores: dict[str, float] | None,
        regime: str,
    ) -> dict[str, float]:
        """Portfolio enhancement iç mantığı."""
        # 1. Hysteresis (küçük değişimleri filtrele)
        adjusted = self._portfolio_enhancements.apply_hysteresis(target_weights, current_weights)

        # 2. Sector constraints
        if sector_map:
            adjusted = self._portfolio_enhancements.apply_sector_constraints(adjusted, sector_map)

        # 3. Liquidity constraints
        if liquidity_scores:
            adjusted = self._portfolio_enhancements.apply_liquidity_constraints(adjusted, liquidity_scores)

        # 4. Min position filter
        adjusted = self._portfolio_enhancements.apply_min_position(adjusted)

        # 5. Position limits
        if self._regime_limits:
            limits = self._regime_limits.get_limits(regime)
            adjusted = self._portfolio_enhancements.apply_position_limits(adjusted, limits.max_position_pct)

        return adjusted

    # =====================================================
    # RECORD OUTCOME
    # =====================================================

    @otel_trace("integration_bridge.record_model_outcome")
    def record_model_outcome(
        self,
        model_id: str,
        predicted: float,
        actual: float,
        return_pct: float = 0.0,
    ) -> None:
        """Model sonucunu degradation monitor'a kaydet.

        Args:
            model_id: Model adı
            predicted: Tahmin
            actual: Gerçek
            return_pct: Getiri %
        """
        self._ensure_initialized()

        if not self.config.enable_degradation_monitor or not self._degradation_monitor:
            return

        self._execute_with_circuit_breaker(
            "degradation_monitor",
            self._degradation_monitor.record_outcome,
            model_id,
            predicted,
            actual,
            return_pct,
        )

    @otel_trace("integration_bridge.record_calibration_data")
    def record_calibration_data(
        self,
        brier_score: float,
        ece: float,
    ) -> None:
        """Calibration verisini kaydet.

        Args:
            brier_score: Brier skoru
            ece: Expected Calibration Error
        """
        self._ensure_initialized()

        if not self.config.enable_calibration_enhanced or not self._calibration_enhanced:
            return

        self._execute_with_circuit_breaker(
            "calibration_enhanced",
            self._calibration_enhanced.record_calibration_metrics,
            brier_score,
            ece,
        )

    # =====================================================
    # HEALTH CHECK
    # =====================================================

    @otel_trace("integration_bridge.health_check")
    def health_check(self) -> dict[str, Any]:
        """Tüm modüllerin sağlık durumunu kontrol et.

        Returns:
            Sağlık raporu
        """
        self._ensure_initialized()

        modules: dict[str, dict[str, Any]] = {}
        all_healthy = True

        module_map = {
            "feature_stability": self._feature_stability,
            "calibration_enhanced": self._calibration_enhanced,
            "regime_limits": self._regime_limits,
            "portfolio_enhancements": self._portfolio_enhancements,
            "backtest_enhancements": self._backtest_enhancements,
            "event_enhancements": self._event_enhancements,
            "degradation_monitor": self._degradation_monitor,
            "feature_lineage": self._feature_lineage,
            "feature_versioning": self._feature_version_manager,
        }

        for name, instance in module_map.items():
            circuit = self._circuits.get(name)
            metrics = self._metrics.get(name)

            is_loaded = instance is not None
            circuit_state = circuit.state.value if circuit else "unknown"
            is_enabled = getattr(self.config, f"enable_{name}", True)

            module_healthy = is_loaded and circuit_state != "open"
            if not module_healthy:
                all_healthy = False

            modules[name] = {
                "loaded": is_loaded,
                "enabled": is_enabled,
                "circuit_state": circuit_state,
                "circuit_failures": circuit.failure_count if circuit else 0,
                "total_calls": metrics.total_calls if metrics else 0,
                "success_rate": round(metrics.success_rate, 4) if metrics else 0.0,
                "healthy": module_healthy,
            }

        return {
            "all_healthy": all_healthy,
            "modules": modules,
            "timestamp": time.time(),
        }

    # =====================================================
    # METRICS
    # =====================================================

    @otel_trace("integration_bridge.get_metrics")
    def get_metrics(self) -> dict[str, Any]:
        """Tüm modüllerin metriklerini döndür.

        Returns:
            Metrik raporu
        """
        module_metrics = {}
        total_calls = 0
        total_success = 0
        total_fail = 0
        total_skip = 0

        for name, metrics in self._metrics.items():
            module_metrics[name] = metrics.to_dict()
            total_calls += metrics.total_calls
            total_success += metrics.successful_calls
            total_fail += metrics.failed_calls
            total_skip += metrics.skipped_calls

        return {
            "total_calls": total_calls,
            "total_successful": total_success,
            "total_failed": total_fail,
            "total_skipped": total_skip,
            "overall_success_rate": round(total_success / max(total_calls, 1), 4),
            "modules": module_metrics,
            "circuit_breakers": {
                name: {
                    "state": cb.state.value,
                    "failures": cb.failure_count,
                }
                for name, cb in self._circuits.items()
            },
        }

    @otel_trace("integration_bridge.reset_metrics")
    def reset_metrics(self) -> None:
        """Tüm metrikleri sıfırla."""
        for metrics in self._metrics.values():
            metrics.total_calls = 0
            metrics.successful_calls = 0
            metrics.failed_calls = 0
            metrics.skipped_calls = 0
            metrics.total_latency_ms = 0.0
            metrics.last_error = ""

    @otel_trace("integration_bridge.reset_circuit_breakers")
    def reset_circuit_breakers(self) -> None:
        """Tüm circuit breaker'ları sıfırla."""
        for cb in self._circuits.values():
            cb.reset()

    # =====================================================
    # CONFIGURATION
    # =====================================================

    @otel_trace("integration_bridge.update_config")
    def update_config(self, **kwargs: Any) -> None:
        """Konfigürasyonu güncelle.

        Args:
            **kwargs: Güncellenecek alanlar
        """
        for key, value in kwargs.items():
            if hasattr(self.config, key):
                setattr(self.config, key, value)
                logger.info("bridge_config_updated", key=key, value=value)
            else:
                logger.warning("bridge_config_unknown_key", key=key)

    @otel_trace("integration_bridge.disable_module")
    def disable_module(self, module_name: str) -> None:
        """Modülü devre dışı bırak."""
        attr_name = f"enable_{module_name}"
        if hasattr(self.config, attr_name):
            setattr(self.config, attr_name, False)
            logger.info("bridge_module_disabled", module=module_name)

    @otel_trace("integration_bridge.enable_module")
    def enable_module(self, module_name: str) -> None:
        """Modülü etkinleştir."""
        attr_name = f"enable_{module_name}"
        if hasattr(self.config, attr_name):
            setattr(self.config, attr_name, True)
            logger.info("bridge_module_enabled", module=module_name)


# Singleton
integration_bridge = IntegrationBridge()
