"""
ALPHA BIST — Integration Bridge v2.0 (Production-Hardened)

Tüm yeni modülleri asıl motorlara bağlayan merkezi entegrasyon katmanı.
Bu modül, `orchestrator` ve `learning_pipeline` tarafından çağrılır.

v2.0 Özellikleri:
1. Circuit Breaker Deseni: Modül sürekli hata verirse otomatik devre dışı bırakma (CLOSED -> OPEN -> HALF_OPEN).
2. Sağlık Kontrolü (Health Check): Tüm modüllerin ve alt sistemlerin canlı bağlantı durumu.
3. Metrik Toplama: Çağrı sayısı, başarı/hata oranı, gecikme (latency) ve son hata kayıtları.
4. Thread-Safe Durum Yönetimi: `threading.RLock()` ile reentrant eşzamanlı erişim koruması.
5. Girdi Doğrulama (Input Validation): Ticker, feature, güven skoru ve fiyat serisi kontrolleri.
6. Korelasyon Takibi (Correlation ID): Modüller arası dağıtık işlem takibi.
7. Esnek Bozulma Toleransı (Graceful Degradation): Kısmi bileşen hatalarında ana akışın kesilmemesi.
8. DuckDB ve Polars Desteği: Metrik ve entegrasyon raporlarının analitik dışa aktarımı.
"""

from __future__ import annotations

import importlib
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any, Final

import duckdb
import numpy as np
import orjson
import polars as pl
import structlog

from services.core.otel import otel_trace

logger = structlog.get_logger(__name__)

# =====================================================
# SABİTLER (CONSTANTS)
# =====================================================

DEFAULT_CIRCUIT_FAILURE_THRESHOLD: Final[int] = 5
DEFAULT_CIRCUIT_RECOVERY_TIMEOUT_SECONDS: Final[float] = 300.0
DEFAULT_HALF_OPEN_MAX_CALLS: Final[int] = 1
DEFAULT_LOG_SLOW_CALLS_MS: Final[float] = 1000.0
DEFAULT_MAX_TICKER_LEN: Final[int] = 20
DEFAULT_MIN_CONFIDENCE: Final[float] = 0.0
DEFAULT_MAX_CONFIDENCE: Final[float] = 1.0
DEFAULT_BASE_POSITION_PCT: Final[float] = 0.05
DEFAULT_MAX_REPORT_HISTORY: Final[int] = 1000
DEFAULT_BRIDGE_AUDIT_DB_PATH: Final[Path] = Path("data/duckdb/alpha_bist_audit.duckdb")


# =====================================================
# CIRCUIT BREAKER & VERİ MODELLERİ
# =====================================================


class CircuitState(StrEnum):
    """Circuit breaker çalışma durumları."""

    CLOSED = "closed"  # Normal çalışma — tüm çağrılara izin verilir
    OPEN = "open"  # Devre açık — çağrılar otomatik reddedilir
    HALF_OPEN = "half_open"  # Test modu — sınırlı sayıda deneme çağrısına izin verilir


@dataclass(slots=True)
class CircuitBreaker:
    """Devre kesici (Circuit Breaker) — bileşen hatalarını izler ve sistemi korur.

    Durum Geçişleri:
    CLOSED (normal) → OPEN (hata eşiği aşıldı) → HALF_OPEN (iyileşme zamanı doldu) → CLOSED
    """

    name: str
    failure_threshold: int = DEFAULT_CIRCUIT_FAILURE_THRESHOLD
    recovery_timeout_seconds: float = DEFAULT_CIRCUIT_RECOVERY_TIMEOUT_SECONDS
    half_open_max_calls: int = DEFAULT_HALF_OPEN_MAX_CALLS

    _state: CircuitState = field(default=CircuitState.CLOSED, repr=False)
    _failure_count: int = field(default=0, repr=False)
    _success_count: int = field(default=0, repr=False)
    _last_failure_time: float = field(default=0.0, repr=False)
    _half_open_calls: int = field(default=0, repr=False)
    _lock: threading.RLock = field(default_factory=threading.RLock, repr=False)

    def can_execute(self) -> bool:
        """Çağrının icra edilip edilemeyeceğini denetler.

        Returns:
            bool: İcraya izin veriliyorsa True, aksi halde False.
        """
        with self._lock:
            if self._state == CircuitState.CLOSED:
                return True

            if self._state == CircuitState.OPEN:
                now = time.time()
                if now - self._last_failure_time >= self.recovery_timeout_seconds:
                    self._state = CircuitState.HALF_OPEN
                    self._half_open_calls = 0
                    logger.info("circuit_breaker_half_open", name=self.name)
                    return True
                return False

            if self._state == CircuitState.HALF_OPEN:
                return self._half_open_calls < self.half_open_max_calls

            return False

    def record_success(self) -> None:
        """Başarılı bir çağrıyı kaydeder ve durumu günceller."""
        with self._lock:
            if self._state == CircuitState.HALF_OPEN:
                self._success_count += 1
                self._state = CircuitState.CLOSED
                self._failure_count = 0
                self._success_count = 0
                self._half_open_calls = 0
                logger.info("circuit_breaker_closed", name=self.name)
            elif self._state == CircuitState.CLOSED:
                self._failure_count = max(0, self._failure_count - 1)

    def record_failure(self) -> None:
        """Başarısız bir çağrıyı kaydeder; eşik aşılırsa devreyi açar."""
        with self._lock:
            self._failure_count += 1
            self._last_failure_time = time.time()

            if self._state == CircuitState.HALF_OPEN:
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
        """Mevcut devre kesici durumunu döndürür."""
        with self._lock:
            return self._state

    @property
    def failure_count(self) -> int:
        """Mevcut arıza sayısını döndürür."""
        with self._lock:
            return self._failure_count

    def reset(self) -> None:
        """Devre kesiciyi başlangıç durumuna sıfırlar."""
        with self._lock:
            self._state = CircuitState.CLOSED
            self._failure_count = 0
            self._success_count = 0
            self._last_failure_time = 0.0
            self._half_open_calls = 0

    def to_dict(self) -> dict[str, Any]:
        """Devre kesici durumunu sözlük olarak döndürür."""
        with self._lock:
            return {
                "name": self.name,
                "state": self._state.value,
                "failure_count": self._failure_count,
                "threshold": self.failure_threshold,
                "recovery_timeout_seconds": self.recovery_timeout_seconds,
            }

    def to_orjson_bytes(self) -> bytes:
        """Devre kesici durumunu JSON bayt dizisine dönüştürür."""
        return orjson.dumps(self.to_dict())

    def to_json(self) -> str:
        """Devre kesici durumunu UTF-8 JSON metnine dönüştürür."""
        return orjson.dumps(self.to_dict()).decode("utf-8")

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CircuitBreaker:
        """Sözlükten CircuitBreaker nesnesi üretir.

        Args:
            data: Devre kesici alanlarını içeren sözlük.

        Returns:
            CircuitBreaker: Oluşturulan devre kesici nesnesi.
        """
        cb = cls(
            name=str(data["name"]),
            failure_threshold=int(data.get("threshold", DEFAULT_CIRCUIT_FAILURE_THRESHOLD)),
            recovery_timeout_seconds=float(data.get("recovery_timeout_seconds", DEFAULT_CIRCUIT_RECOVERY_TIMEOUT_SECONDS)),
        )
        cb._state = CircuitState(data.get("state", CircuitState.CLOSED.value))
        cb._failure_count = int(data.get("failure_count", 0))
        return cb

    @classmethod
    def from_json(cls, json_str_or_bytes: str | bytes) -> CircuitBreaker:
        """JSON metni veya bayt dizisinden CircuitBreaker üretir.

        Args:
            json_str_or_bytes: JSON verisi.

        Returns:
            CircuitBreaker: Üretilen nesne.
        """
        data = orjson.loads(json_str_or_bytes)
        return cls.from_dict(data)

    def __repr__(self) -> str:
        """Devre kesici metin gösterimi."""
        with self._lock:
            return f"CircuitBreaker(name={self.name!r}, state={self._state.value!r}, failures={self._failure_count})"


@dataclass(slots=True)
class ModuleMetrics:
    """Tek bir entegre alt modül için performans ve güvenilirlik metrikleri."""

    name: str
    total_calls: int = 0
    successful_calls: int = 0
    failed_calls: int = 0
    skipped_calls: int = 0
    total_latency_ms: float = 0.0
    last_call_time: float = 0.0
    last_error: str = ""
    _lock: threading.RLock = field(default_factory=threading.RLock, repr=False)

    @property
    def success_rate(self) -> float:
        """Başarı oranını [0.0, 1.0] aralığında hesaplar."""
        with self._lock:
            if self.total_calls == 0:
                return 0.0
            return self.successful_calls / self.total_calls

    @property
    def avg_latency_ms(self) -> float:
        """Ortalama çağrı süresini (milisaniye) hesaplar."""
        with self._lock:
            if self.successful_calls == 0:
                return 0.0
            return self.total_latency_ms / self.successful_calls

    def to_dict(self) -> dict[str, Any]:
        """Metrikleri serileştirilebilir sözlüğe dönüştürür."""
        with self._lock:
            return {
                "name": self.name,
                "total_calls": self.total_calls,
                "successful_calls": self.successful_calls,
                "failed_calls": self.failed_calls,
                "skipped_calls": self.skipped_calls,
                "success_rate": round(self.success_rate, 4),
                "avg_latency_ms": round(self.avg_latency_ms, 2),
                "last_call_time": self.last_call_time,
                "last_error": self.last_error[:200] if self.last_error else "",
            }

    def to_orjson_bytes(self) -> bytes:
        """Metrikleri JSON bayt dizisine dönüştürür."""
        return orjson.dumps(self.to_dict())

    def to_json(self) -> str:
        """Metrikleri UTF-8 JSON metnine dönüştürür."""
        return orjson.dumps(self.to_dict()).decode("utf-8")

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ModuleMetrics:
        """Sözlükten ModuleMetrics nesnesi üretir."""
        m = cls(
            name=str(data["name"]),
            total_calls=int(data.get("total_calls", 0)),
            successful_calls=int(data.get("successful_calls", 0)),
            failed_calls=int(data.get("failed_calls", 0)),
            skipped_calls=int(data.get("skipped_calls", 0)),
            total_latency_ms=float(data.get("avg_latency_ms", 0.0)) * int(data.get("successful_calls", 1)),
            last_call_time=float(data.get("last_call_time", 0.0)),
            last_error=str(data.get("last_error", "")),
        )
        return m

    @classmethod
    def from_json(cls, json_str_or_bytes: str | bytes) -> ModuleMetrics:
        """JSON metni veya bayt dizisinden ModuleMetrics üretir."""
        data = orjson.loads(json_str_or_bytes)
        return cls.from_dict(data)

    def __repr__(self) -> str:
        """Metrik metin gösterimi."""
        with self._lock:
            return (
                f"ModuleMetrics(name={self.name!r}, toplam={self.total_calls}, "
                f"basarili={self.successful_calls}, hatali={self.failed_calls}, "
                f"ort_sure_ms={self.avg_latency_ms:.2f})"
            )


@dataclass(slots=True)
class EnhancementResult:
    """Tek bir zenginleştirme (enhancement) adımı sonucu."""

    module: str
    success: bool
    data: dict[str, Any] | None = None
    error: str | None = None
    latency_ms: float = 0.0
    skipped: bool = False

    def to_dict(self) -> dict[str, Any]:
        """Sonucu sözlük yapısına dönüştürür."""
        return {
            "module": self.module,
            "success": self.success,
            "data": self.data,
            "error": self.error[:200] if self.error else None,
            "latency_ms": round(self.latency_ms, 2),
            "skipped": self.skipped,
        }

    def to_orjson_bytes(self) -> bytes:
        """Sonucu JSON bayt dizisine dönüştürür."""
        return orjson.dumps(self.to_dict())

    def to_json(self) -> str:
        """Sonucu UTF-8 JSON metnine dönüştürür."""
        return orjson.dumps(self.to_dict()).decode("utf-8")

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> EnhancementResult:
        """Sözlükten EnhancementResult nesnesi üretir."""
        return cls(
            module=str(data["module"]),
            success=bool(data["success"]),
            data=data.get("data"),
            error=data.get("error"),
            latency_ms=float(data.get("latency_ms", 0.0)),
            skipped=bool(data.get("skipped", False)),
        )

    @classmethod
    def from_json(cls, json_str_or_bytes: str | bytes) -> EnhancementResult:
        """JSON metni veya bayt dizisinden EnhancementResult üretir."""
        data = orjson.loads(json_str_or_bytes)
        return cls.from_dict(data)

    def __repr__(self) -> str:
        """Zenginleştirme sonucu metin gösterimi."""
        durum = "ATLANDI" if self.skipped else ("BAŞARILI" if self.success else "HATALI")
        return f"EnhancementResult(modul={self.module!r}, durum={durum}, sure_ms={self.latency_ms:.2f})"


@dataclass(slots=True)
class PipelineEnhancementReport:
    """Pipeline zenginleştirme raporu — tüm modüllerin kümülatif sonuçları."""

    ticker: str
    correlation_id: str
    enhancements: list[EnhancementResult]
    total_latency_ms: float
    success_count: int
    failure_count: int
    skip_count: int
    created_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    @property
    def is_healthy(self) -> bool:
        """Raporun hatasız tamamlanıp tamamlanmadığını denetler."""
        return self.failure_count == 0

    def to_dict(self) -> dict[str, Any]:
        """Raporu serileştirilebilir sözlüğe dönüştürür."""
        return {
            "ticker": self.ticker,
            "correlation_id": self.correlation_id,
            "total_latency_ms": round(self.total_latency_ms, 2),
            "success_count": self.success_count,
            "failure_count": self.failure_count,
            "skip_count": self.skip_count,
            "is_healthy": self.is_healthy,
            "created_at": self.created_at,
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

    def to_orjson_bytes(self) -> bytes:
        """Raporu JSON bayt dizisine dönüştürür."""
        return orjson.dumps(self.to_dict())

    def to_json(self) -> str:
        """Raporu UTF-8 JSON metnine dönüştürür."""
        return orjson.dumps(self.to_dict()).decode("utf-8")

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PipelineEnhancementReport:
        """Sözlükten PipelineEnhancementReport nesnesi üretir."""
        enhancements = [
            EnhancementResult.from_dict(e) if isinstance(e, dict) else e
            for e in data.get("modules", [])
        ]
        return cls(
            ticker=str(data["ticker"]).upper(),
            correlation_id=str(data["correlation_id"]),
            enhancements=enhancements,
            total_latency_ms=float(data.get("total_latency_ms", 0.0)),
            success_count=int(data.get("success_count", 0)),
            failure_count=int(data.get("failure_count", 0)),
            skip_count=int(data.get("skip_count", 0)),
            created_at=str(data.get("created_at", datetime.now(UTC).isoformat())),
        )

    @classmethod
    def from_json(cls, json_str_or_bytes: str | bytes) -> PipelineEnhancementReport:
        """JSON metni veya bayt dizisinden PipelineEnhancementReport üretir."""
        data = orjson.loads(json_str_or_bytes)
        return cls.from_dict(data)

    def __repr__(self) -> str:
        """Rapor metin gösterimi."""
        return (
            f"PipelineEnhancementReport(ticker={self.ticker!r}, correlation_id={self.correlation_id!r}, "
            f"basarili={self.success_count}, hatali={self.failure_count}, sure_ms={self.total_latency_ms:.2f})"
        )


@dataclass(slots=True)
class BridgeConfig:
    """Integration Bridge yapılandırma parametreleri."""

    # Modül aktif/pasif bayrakları
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

    # Devre kesici eşikleri
    circuit_failure_threshold: int = DEFAULT_CIRCUIT_FAILURE_THRESHOLD
    circuit_recovery_timeout: float = DEFAULT_CIRCUIT_RECOVERY_TIMEOUT_SECONDS

    # Girdi doğrulama eşikleri
    min_features_for_stability: int = 1
    min_confidence: float = DEFAULT_MIN_CONFIDENCE
    max_confidence: float = DEFAULT_MAX_CONFIDENCE

    # Loglama ve telemetri
    log_all_calls: bool = False
    log_failures: bool = True
    log_slow_calls_ms: float = DEFAULT_LOG_SLOW_CALLS_MS

    def to_dict(self) -> dict[str, Any]:
        """Konfigürasyonu sözlük yapısına dönüştürür."""
        return {
            "enable_feature_stability": self.enable_feature_stability,
            "enable_calibration_enhanced": self.enable_calibration_enhanced,
            "enable_regime_limits": self.enable_regime_limits,
            "enable_portfolio_enhancements": self.enable_portfolio_enhancements,
            "enable_backtest_enhancements": self.enable_backtest_enhancements,
            "enable_event_enhancements": self.enable_event_enhancements,
            "enable_degradation_monitor": self.enable_degradation_monitor,
            "enable_feature_lineage": self.enable_feature_lineage,
            "enable_feature_versioning": self.enable_feature_versioning,
            "enable_ensemble_diversity": self.enable_ensemble_diversity,
            "circuit_failure_threshold": self.circuit_failure_threshold,
            "circuit_recovery_timeout": self.circuit_recovery_timeout,
            "log_slow_calls_ms": self.log_slow_calls_ms,
        }

    def to_orjson_bytes(self) -> bytes:
        """Konfigürasyonu JSON bayt dizisine dönüştürür."""
        return orjson.dumps(self.to_dict())

    def to_json(self) -> str:
        """Konfigürasyonu UTF-8 JSON metnine dönüştürür."""
        return orjson.dumps(self.to_dict()).decode("utf-8")

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> BridgeConfig:
        """Sözlükten BridgeConfig nesnesi üretir."""
        return cls(
            enable_feature_stability=bool(data.get("enable_feature_stability", True)),
            enable_calibration_enhanced=bool(data.get("enable_calibration_enhanced", True)),
            enable_regime_limits=bool(data.get("enable_regime_limits", True)),
            enable_portfolio_enhancements=bool(data.get("enable_portfolio_enhancements", True)),
            enable_backtest_enhancements=bool(data.get("enable_backtest_enhancements", True)),
            enable_event_enhancements=bool(data.get("enable_event_enhancements", True)),
            enable_degradation_monitor=bool(data.get("enable_degradation_monitor", True)),
            enable_feature_lineage=bool(data.get("enable_feature_lineage", True)),
            enable_feature_versioning=bool(data.get("enable_feature_versioning", True)),
            enable_ensemble_diversity=bool(data.get("enable_ensemble_diversity", True)),
            circuit_failure_threshold=int(data.get("circuit_failure_threshold", DEFAULT_CIRCUIT_FAILURE_THRESHOLD)),
            circuit_recovery_timeout=float(data.get("circuit_recovery_timeout", DEFAULT_CIRCUIT_RECOVERY_TIMEOUT_SECONDS)),
            log_slow_calls_ms=float(data.get("log_slow_calls_ms", DEFAULT_LOG_SLOW_CALLS_MS)),
        )

    @classmethod
    def from_json(cls, json_str_or_bytes: str | bytes) -> BridgeConfig:
        """JSON metni veya bayt dizisinden BridgeConfig üretir."""
        data = orjson.loads(json_str_or_bytes)
        return cls.from_dict(data)

    def __repr__(self) -> str:
        """Konfigürasyon metin gösterimi."""
        return (
            f"BridgeConfig(devre_esigi={self.circuit_failure_threshold}, "
            f"kurtarma_sn={self.circuit_recovery_timeout}, yavas_esik_ms={self.log_slow_calls_ms})"
        )


# =====================================================
# INTEGRATION BRIDGE v2.0 ÇEKİRDEK SERVİSİ
# =====================================================


class IntegrationBridge:
    """Tüm yeni alt sistemleri ana motorlara bağlayan entegrasyon katmanı.

    Yönetilen Alt Sistemler:
    - FeatureStabilityAnalyzer: Feature drift ve istatistiksel kayma analizi
    - CalibrationEnhanced: Model güven skoru kalibrasyonu ve Brier/ECE takibi
    - RegimeLimitsManager: Piyasa rejimine göre dinamik risk limitleri
    - PortfolioEnhancements: Histerezis, sektör ve likidite kısıtları
    - BacktestEnhancements: T+1 takas kuralı, piyasa etkisi (market impact) simülasyonu
    - EventEnhancements: Tekilleştirme (idempotency) ve korelasyon takibi
    - ModelDegradationMonitor: Model bozulma ve drift tespiti
    - FeatureLineageTracker: Feature soy ağacı ve veri kaynağı kaydı
    - FeatureVersionManager: Feature sürüm ve şema yönetimi
    - EnsembleModel: Model çeşitliliği ve korelasyon analizi
    """

    def __init__(self, config: BridgeConfig | None = None) -> None:
        """Integration Bridge örneğini başlatır.

        Args:
            config: Opsiyonel yapılandırma nesnesi.
        """
        self.config: BridgeConfig = config or BridgeConfig()
        self._initialized: bool = False
        self._lock: threading.RLock = threading.RLock()

        # Alt modül örnekleri (Lazy Loaded)
        self._feature_stability: Any = None
        self._calibration_enhanced: Any = None
        self._regime_limits: Any = None
        self._portfolio_enhancements: Any = None
        self._backtest_enhancements: Any = None
        self._event_enhancements: Any = None
        self._degradation_monitor: Any = None
        self._feature_lineage: Any = None
        self._feature_version_manager: Any = None

        # Devre kesiciler
        self._circuits: dict[str, CircuitBreaker] = {}
        self._init_circuit_breakers()

        # Metrik toplayıcılar
        self._metrics: dict[str, ModuleMetrics] = {}
        self._init_metrics()

        # Rapor geçmişi ve sayaçlar
        self._call_counter: int = 0
        self._report_history: list[PipelineEnhancementReport] = []

    def _init_circuit_breakers(self) -> None:
        """Her modül için bağımsız devre kesici oluşturur."""
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
        """Her modül için bağımsız metrik toplayıcı oluşturur."""
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
        """Gerektiğinde alt modülleri güvenli ve dinamik olarak içe aktarır."""
        if self._initialized:
            return

        with self._lock:
            if self._initialized:
                return

            self._load_module("feature_stability", "services.ml.feature_stability", "feature_stability")
            self._load_module("calibration_enhanced", "services.ml.calibration_enhanced", "calibration_enhanced")
            self._load_module("regime_limits", "services.risk.regime_limits", "regime_limits")
            self._load_module(
                "portfolio_enhancements",
                "services.portfolio.portfolio_enhancements",
                "portfolio_enhancements",
            )
            self._load_module(
                "backtest_enhancements",
                "services.backtest.backtest_enhancements",
                "backtest_enhancements",
            )
            self._load_module("event_enhancements", "services.core.event_enhancements", "event_enhancements")
            self._load_module("degradation_monitor", "services.learning.model_degradation_monitor", "degradation_monitor")
            self._load_module("feature_lineage", "services.features.lineage", "feature_lineage")
            self._load_module("feature_versioning", "services.features.versioning", "feature_version_manager")

            self._initialized = True

    def _load_module(self, attr_name: str, module_path: str, singleton_name: str) -> None:
        """Modülü hata korumalı olarak içe aktarır."""
        try:
            mod = importlib.import_module(module_path)
            instance = getattr(mod, singleton_name, None)
            setattr(self, f"_{attr_name}", instance)
            logger.debug("module_loaded", module=attr_name)
        except Exception as e:
            logger.warning("module_load_failed", module=attr_name, error=str(e))
            setattr(self, f"_{attr_name}", None)

    def _generate_correlation_id(self) -> str:
        """Tekil korelasyon takip kimliği üretir."""
        with self._lock:
            self._call_counter += 1
            counter_val = self._call_counter
        return f"bridge-{uuid.uuid4().hex[:12]}-{counter_val:06d}"

    def _execute_with_circuit_breaker(
        self,
        module_name: str,
        func: Any,
        *args: Any,
        **kwargs: Any,
    ) -> EnhancementResult:
        """Circuit breaker ve metrik koruması altında fonksiyon çalıştırır.

        Args:
            module_name: İlgili modülün adı.
            func: Çalıştırılacak fonksiyon veya metot.
            *args: Fonksiyon konumsal parametreleri.
            **kwargs: Fonksiyon anahtar kelime parametreleri.

        Returns:
            EnhancementResult: İcra veya devre kesici atlama sonucu.
        """
        circuit = self._circuits.get(module_name)
        metrics = self._metrics.get(module_name)

        if circuit and not circuit.can_execute():
            if metrics:
                with metrics._lock:
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

        start_time = time.time()
        try:
            result_data = func(*args, **kwargs)
            latency_ms = (time.time() - start_time) * 1000.0

            if circuit:
                circuit.record_success()

            if metrics:
                with metrics._lock:
                    metrics.total_calls += 1
                    metrics.successful_calls += 1
                    metrics.total_latency_ms += latency_ms
                    metrics.last_call_time = time.time()

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
            latency_ms = (time.time() - start_time) * 1000.0
            error_msg = str(e)

            if circuit:
                circuit.record_failure()

            if metrics:
                with metrics._lock:
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
    # GİRDİ DOĞRULAMA (INPUT VALIDATION)
    # =====================================================

    def _validate_ticker(self, ticker: str) -> bool:
        """Hisse kodu geçerliliğini denetler."""
        if not ticker or not isinstance(ticker, str):
            return False
        clean = ticker.strip()
        return 0 < len(clean) <= DEFAULT_MAX_TICKER_LEN

    def _validate_features(self, features: dict[str, float]) -> bool:
        """Öznitelik sözlüğü geçerliliğini denetler."""
        if not isinstance(features, dict):
            return False
        if len(features) < self.config.min_features_for_stability:
            return False
        valid_nums = sum(1 for v in features.values() if isinstance(v, (int, float)) and np.isfinite(v))
        return valid_nums >= self.config.min_features_for_stability

    def _validate_confidence(self, confidence: float) -> bool:
        """Model güven skorunu denetler."""
        if not isinstance(confidence, (int, float)) or not np.isfinite(confidence):
            return False
        return self.config.min_confidence <= float(confidence) <= self.config.max_confidence

    def _validate_prices(self, prices: np.ndarray | list[float]) -> bool:
        """Fiyat serisi geçerliliğini denetler."""
        if prices is None:
            return False
        arr = np.asarray(prices, dtype=float)
        if len(arr) == 0:
            return False
        arr = arr[np.isfinite(arr)]
        return len(arr) > 0 and np.all(arr > 0)

    # =====================================================
    # PIPELINE ZENGİNLEŞTİRME (ENHANCE PIPELINE RESULT)
    # =====================================================

    @otel_trace("integration_bridge.enhance_pipeline_result")
    def enhance_pipeline_result(
        self,
        ticker: str,
        result: dict[str, Any],
        features: dict[str, float],
        regime: str,
    ) -> dict[str, Any]:
        """Model tahmin ve pipeline sonucunu yeni modüllerle zenginleştirir.

        Args:
            ticker: Hisse kodu (örn. THYAO).
            result: Mevcut pipeline çıktısı sözlüğü.
            features: Hesaplanan öznitelik seti.
            regime: Tespit edilen piyasa rejimi (BULL, BEAR vb.).

        Returns:
            dict[str, Any]: Zenginleştirilmiş pipeline sonucu.
        """
        self._ensure_initialized()
        clean_ticker = str(ticker).strip().upper() if ticker else ""
        correlation_id = self._generate_correlation_id()
        start_time = time.time()
        enhancement_results: list[EnhancementResult] = []

        if not self._validate_ticker(clean_ticker):
            logger.warning("invalid_ticker", ticker=ticker)
            result["_bridge_error"] = "Invalid ticker"
            return result

        if not self._validate_features(features):
            logger.warning("invalid_features", ticker=clean_ticker, n_features=len(features) if features else 0)
            result["_bridge_error"] = "Invalid features"
            return result

        enhancements: dict[str, Any] = {}

        # 1. Feature stability kontrolü
        if self.config.enable_feature_stability and self._feature_stability:
            er = self._execute_with_circuit_breaker(
                "feature_stability",
                self._check_feature_stability,
                clean_ticker,
                features,
            )
            enhancement_results.append(er)
            if er.success and er.data:
                enhancements["feature_stability"] = er.data

        # 2. Rejim risk limitleri
        if self.config.enable_regime_limits and self._regime_limits:
            er = self._execute_with_circuit_breaker(
                "regime_limits",
                self._get_regime_limits,
                regime,
            )
            enhancement_results.append(er)
            if er.success and er.data:
                enhancements["regime_limits"] = er.data

        # 3. Feature soy ağacı kaydı
        if self.config.enable_feature_lineage and self._feature_lineage:
            er = self._execute_with_circuit_breaker(
                "feature_lineage",
                self._record_feature_lineage,
                features,
            )
            enhancement_results.append(er)

        total_latency = (time.time() - start_time) * 1000.0

        report = PipelineEnhancementReport(
            ticker=clean_ticker,
            correlation_id=correlation_id,
            enhancements=enhancement_results,
            total_latency_ms=total_latency,
            success_count=sum(1 for e in enhancement_results if e.success),
            failure_count=sum(1 for e in enhancement_results if not e.success and not e.skipped),
            skip_count=sum(1 for e in enhancement_results if e.skipped),
        )

        with self._lock:
            self._report_history.append(report)
            if len(self._report_history) > DEFAULT_MAX_REPORT_HISTORY:
                self._report_history = self._report_history[-DEFAULT_MAX_REPORT_HISTORY:]

        if enhancements:
            result["enhancements"] = enhancements

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
        """Öznitelik kararlılığını test eder."""
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
        """Piyasa rejimine uygun risk ve pozisyon limitlerini sorgular."""
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
        """Öznitelik soy ağacını kaydeder."""
        for fname in features:
            if not self._feature_lineage.get_lineage(fname):
                self._feature_lineage.record(
                    feature_name=fname,
                    raw_sources=["market_data"],
                    transformations=["computed"],
                    computed_by="orchestrator",
                )

    # =====================================================
    # TRADE PLAN ZENGİNLEŞTİRME (ENHANCE TRADE PLAN)
    # =====================================================

    @otel_trace("integration_bridge.enhance_trade_plan")
    def enhance_trade_plan(
        self,
        ticker: str,
        decision: dict[str, Any],
        prices: np.ndarray | list[float],
        regime: str,
        confidence: float = 0.5,
    ) -> dict[str, Any]:
        """İşlem planını takas kuralları, piyasa etkisi ve likiditeyle zenginleştirir.

        Args:
            ticker: Hisse kodu.
            decision: Model karar sözlüğü.
            prices: Kapanış fiyat serisi.
            regime: Mevcut piyasa rejimi.
            confidence: Model tahmin güven skoru.

        Returns:
            dict[str, Any]: Zenginleştirilmiş işlem planı.
        """
        self._ensure_initialized()
        clean_ticker = str(ticker).strip().upper() if ticker else ""
        correlation_id = self._generate_correlation_id()
        start_time = time.time()
        enhancement_results: list[EnhancementResult] = []

        if not self._validate_ticker(clean_ticker):
            decision["_bridge_error"] = "Invalid ticker"
            return decision

        if prices is not None and not self._validate_prices(prices):
            logger.warning("invalid_prices_in_trade_plan", ticker=clean_ticker)
            decision["_bridge_warning"] = "Invalid prices array"

        if not self._validate_confidence(confidence):
            logger.warning("invalid_confidence", ticker=clean_ticker, confidence=confidence)
            confidence = max(DEFAULT_MIN_CONFIDENCE, min(DEFAULT_MAX_CONFIDENCE, self._safe_float(confidence, 0.5)))

        enhancements: dict[str, Any] = {}

        # 1. Rejime göre pozisyon boyutlandırma
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

        # 2. T+1 takas kuralı kontrolü
        if self.config.enable_backtest_enhancements and self._backtest_enhancements:
            er = self._execute_with_circuit_breaker(
                "backtest_enhancements",
                self._check_t_plus_1,
                clean_ticker,
            )
            enhancement_results.append(er)
            if er.success and er.data:
                enhancements["t_plus_1"] = er.data

        # 3. Piyasa etkisi (Market Impact) tahmini
        if self.config.enable_backtest_enhancements and self._backtest_enhancements:
            er = self._execute_with_circuit_breaker(
                "backtest_enhancements",
                self._estimate_market_impact,
                clean_ticker,
                decision,
            )
            enhancement_results.append(er)
            if er.success and er.data:
                enhancements["market_impact"] = er.data

        # 4. Rejim likidite yeterlilik kontrolü
        if self.config.enable_regime_limits and self._regime_limits:
            er = self._execute_with_circuit_breaker(
                "regime_limits",
                self._check_liquidity,
                clean_ticker,
                decision,
                regime,
            )
            enhancement_results.append(er)
            if er.success and er.data:
                enhancements["liquidity_check"] = er.data

        total_latency = (time.time() - start_time) * 1000.0

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

    @staticmethod
    def _safe_float(val: Any, default: float = 0.0) -> float:
        """Değeri güvenli şekilde float'a dönüştürür; None, inf ve nan durumlarını guard eder."""
        if val is None:
            return default
        try:
            num = float(val)
            return num if np.isfinite(num) else default
        except (ValueError, TypeError):
            return default

    def _adjust_position_for_confidence(self, decision: dict[str, Any], confidence: float, regime: str) -> float:
        """Güven skoruna ve rejime göre pozisyon büyüklüğünü uyarlar."""
        base_size = self._safe_float(decision.get("position_pct"), DEFAULT_BASE_POSITION_PCT)
        return float(self._regime_limits.adjust_for_confidence(base_size, confidence, regime))

    def _check_t_plus_1(self, ticker: str) -> dict[str, Any]:
        """T+1 takas kuralı icra durumunu denetler."""
        today = datetime.now(UTC).strftime("%Y-%m-%d")
        t1_result = self._backtest_enhancements.check_t_plus_1(ticker, today)
        return {
            "can_execute": t1_result.can_execute,
            "execution_date": t1_result.execution_date,
            "delay_days": t1_result.delay_days,
            "reason": t1_result.reason,
        }

    def _estimate_market_impact(self, ticker: str, decision: dict[str, Any]) -> dict[str, Any] | None:
        """Piyasa darbe (market impact) maliyetini tahmin eder."""
        trade_size = self._safe_float(decision.get("notional"), 0.0)
        adv = self._safe_float(decision.get("adv"), 0.0)
        if trade_size <= 0.0 or adv <= 0.0:
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
        """Rejim bazlı likidite yeterliliğini denetler."""
        liquidity_score = self._safe_float(decision.get("liquidity_score"), 0.5)
        is_sufficient = self._regime_limits.check_liquidity(ticker, liquidity_score, regime)
        return {
            "is_sufficient": is_sufficient,
            "liquidity_score": liquidity_score,
            "min_required": self._regime_limits.get_limits(regime).min_liquidity_score,
        }

    # =====================================================
    # ÖĞRENME DÖNGÜSÜ ZENGİNLEŞTİRME (ENHANCE LEARNING)
    # =====================================================

    @otel_trace("integration_bridge.enhance_learning_cycle")
    def enhance_learning_cycle(
        self,
        learning_result: dict[str, Any],
        model_predictions: dict[str, np.ndarray] | None = None,
    ) -> dict[str, Any]:
        """Öğrenme döngüsü çıktısını model bozulma ve kalibrasyonla zenginleştirir.

        Args:
            learning_result: Mevcut öğrenme döngüsü sonucu.
            model_predictions: Çeşitlilik analizi için model tahminleri.

        Returns:
            dict[str, Any]: Zenginleştirilmiş öğrenme çıktısı.
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

        # 2. Kalibrasyon sapması (Calibration drift)
        if self.config.enable_calibration_enhanced and self._calibration_enhanced:
            er = self._execute_with_circuit_breaker(
                "calibration_enhanced",
                self._check_calibration_drift,
            )
            enhancement_results.append(er)
            if er.success and er.data:
                enhancements["calibration_drift"] = er.data

        # 3. Topluluk model çeşitliliği (Ensemble diversity)
        if self.config.enable_ensemble_diversity and model_predictions and len(model_predictions) >= 2:
            er = self._execute_with_circuit_breaker(
                "ensemble_diversity",
                self._check_ensemble_diversity,
                model_predictions,
            )
            enhancement_results.append(er)
            if er.success and er.data:
                enhancements["ensemble_diversity"] = er.data

        total_latency = (time.time() - start_time) * 1000.0

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
        """Model bozulma durumunu özetler."""
        summary = self._degradation_monitor.get_model_summary()
        result: dict[str, Any] = {"models": summary}

        alerts = self._degradation_monitor.check_all_models()
        if alerts:
            result["alerts"] = [
                {
                    "model": getattr(a, "model_id", ""),
                    "severity": getattr(a, "severity", ""),
                    "message": getattr(a, "message", ""),
                }
                for a in alerts
            ]

        return result

    def _check_calibration_drift(self) -> dict[str, Any]:
        """Model güven skorundaki kalibrasyon kaymasını denetler."""
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
        """Topluluk modelleri arası korelasyon ve çeşitlilik analizi yapar."""
        try:
            from services.ml.ensemble import EnsembleModel

            ens = EnsembleModel()
            diversity = ens.analyze_diversity(model_predictions)
            return {
                "score": diversity.diversity_score,
                "redundant": diversity.redundant_models,
                "recommendation": diversity.recommendation,
            }
        except Exception as exc:
            logger.warning("ensemble_diversity_check_failed", error=str(exc))
            return {"score": 1.0, "redundant": [], "recommendation": "Ensemble diversity check unavailable"}

    # =====================================================
    # OLAY ZENGİNLEŞTİRME (ENHANCE EVENT)
    # =====================================================

    @otel_trace("integration_bridge.enhance_event")
    def enhance_event(
        self,
        event_id: str,
        event_type: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        """Olay yükünü tekilleştirme ve zaman damgasıyla zenginleştirir.

        Args:
            event_id: Olay tekil kimliği.
            event_type: Olay tipi.
            payload: Olay veri yükü sözlüğü.

        Returns:
            dict[str, Any]: Zenginleştirilmiş veri yükü.
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

        return payload

    def _enhance_event_internal(self, event_id: str, event_type: str, payload: dict[str, Any]) -> dict[str, Any]:
        """Olay zenginleştirme iç mantığı."""
        if self._event_enhancements.is_duplicate(event_id):
            return {"_skipped": True, "_reason": "duplicate"}

        if "_correlation_id" not in payload:
            payload["_correlation_id"] = self._event_enhancements.generate_correlation_id()

        payload["_timestamp"] = datetime.now(UTC).isoformat()
        payload["_sequence"] = self._event_enhancements.get_next_sequence(event_type)
        self._event_enhancements.mark_processed(event_id)

        return payload

    # =====================================================
    # PORTFÖY AĞIRLIKLARI ZENGİNLEŞTİRME
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
        """Portföy ağırlıklarını histerezis, sektör ve rejim kısıtlarıyla düzeltir.

        Args:
            target_weights: Model hedef ağırlıkları.
            current_weights: Mevcut portföy ağırlıkları.
            sector_map: Hisse-sektör eşleme sözlüğü.
            liquidity_scores: Hisse likidite skorları sözlüğü.
            regime: Mevcut piyasa rejimi.

        Returns:
            dict[str, float]: Düzeltilmiş ve filtrelenmiş portföy ağırlıkları.
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

        return target_weights

    def _enhance_portfolio_internal(
        self,
        target_weights: dict[str, float],
        current_weights: dict[str, float],
        sector_map: dict[str, str] | None,
        liquidity_scores: dict[str, float] | None,
        regime: str,
    ) -> dict[str, float]:
        """Portföy ağırlık kısıtlama iç mantığı."""
        # 1. Histerezis (Gereksiz işlem maliyetini önleme)
        adjusted = self._portfolio_enhancements.apply_hysteresis(target_weights, current_weights)

        # 2. Sektör konsantrasyon kısıtı
        if sector_map:
            adjusted = self._portfolio_enhancements.apply_sector_constraints(adjusted, sector_map)

        # 3. Likidite kısıtı
        if liquidity_scores:
            adjusted = self._portfolio_enhancements.apply_liquidity_constraints(adjusted, liquidity_scores)

        # 4. Minimum pozisyon eşik filtresi
        adjusted = self._portfolio_enhancements.apply_min_position(adjusted)

        # 5. Rejime bağlı maksimum pozisyon tavanı
        if self._regime_limits:
            limits = self._regime_limits.get_limits(regime)
            adjusted = self._portfolio_enhancements.apply_position_limits(adjusted, limits.max_position_pct)

        return adjusted

    # =====================================================
    # MODEL VE KALİBRASYON GERİBİLDİRİMİ KAYIT
    # =====================================================

    @otel_trace("integration_bridge.record_model_outcome")
    def record_model_outcome(
        self,
        model_id: str,
        predicted: float,
        actual: float,
        return_pct: float = 0.0,
    ) -> None:
        """Model tahmin ve gerçekleşen getiri sonucunu kaydeder.

        Args:
            model_id: Model tanımlayıcı kimliği.
            predicted: Tahmin edilen değer/yön.
            actual: Gerçekleşen getiri veya sınıf.
            return_pct: Gerçekleşen getiri yüzdesi.
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
        """Kalibrasyon metriklerini (Brier ve ECE) kaydeder.

        Args:
            brier_score: Brier skoru.
            ece: Beklenen Kalibrasyon Hatası (Expected Calibration Error).
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
    # SAĞLIK KONTROLÜ VE METRİKLER
    # =====================================================

    @otel_trace("integration_bridge.health_check")
    def health_check(self) -> dict[str, Any]:
        """Tüm entegre alt modüllerin bağlantı ve sağlık durumunu raporlar.

        Returns:
            dict[str, Any]: Sistem genel sağlık özeti.
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

    @otel_trace("integration_bridge.get_metrics")
    def get_metrics(self) -> dict[str, Any]:
        """Tüm modüllerin kümülatif çağrı ve gecikme metriklerini döndürür.

        Returns:
            dict[str, Any]: Metrik raporu sözlüğü.
        """
        module_metrics = {}
        total_calls = 0
        total_success = 0
        total_fail = 0
        total_skip = 0

        for name, metrics in self._metrics.items():
            module_metrics[name] = metrics.to_dict()
            with metrics._lock:
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
        """Tüm modül performans metriklerini sıfırlar."""
        for metrics in self._metrics.values():
            with metrics._lock:
                metrics.total_calls = 0
                metrics.successful_calls = 0
                metrics.failed_calls = 0
                metrics.skipped_calls = 0
                metrics.total_latency_ms = 0.0
                metrics.last_error = ""

    @otel_trace("integration_bridge.reset_circuit_breakers")
    def reset_circuit_breakers(self) -> None:
        """Tüm devre kesicileri başlangıç (CLOSED) durumuna sıfırlar."""
        for cb in self._circuits.values():
            cb.reset()

    # =====================================================
    # KONFİGÜRASYON VE MODÜL YÖNETİMİ
    # =====================================================

    @otel_trace("integration_bridge.update_config")
    def update_config(self, **kwargs: Any) -> None:
        """Yapılandırma parametrelerini dinamik olarak günceller."""
        for key, value in kwargs.items():
            if hasattr(self.config, key):
                setattr(self.config, key, value)
                logger.info("bridge_config_updated", key=key, value=value)
            else:
                logger.warning("bridge_config_unknown_key", key=key)

    @otel_trace("integration_bridge.disable_module")
    def disable_module(self, module_name: str) -> None:
        """Belirtilen alt modülü devre dışı bırakır."""
        attr_name = f"enable_{module_name}"
        if hasattr(self.config, attr_name):
            setattr(self.config, attr_name, False)
            logger.info("bridge_module_disabled", module=module_name)

    @otel_trace("integration_bridge.enable_module")
    def enable_module(self, module_name: str) -> None:
        """Belirtilen alt modülü etkinleştirir."""
        attr_name = f"enable_{module_name}"
        if hasattr(self.config, attr_name):
            setattr(self.config, attr_name, True)
            logger.info("bridge_module_enabled", module=module_name)

    # =====================================================
    # POLARS VE DUCKDB DIŞA AKTARIMI
    # =====================================================

    @otel_trace("integration_bridge.export_metrics_to_polars")
    def export_metrics_to_polars(self) -> pl.DataFrame:
        """Modül performans metriklerini Polars DataFrame olarak döndürür.

        Returns:
            pl.DataFrame: Metrik tablosu.
        """
        schema = {
            "module_name": pl.Utf8,
            "total_calls": pl.Int64,
            "successful_calls": pl.Int64,
            "failed_calls": pl.Int64,
            "skipped_calls": pl.Int64,
            "success_rate": pl.Float64,
            "avg_latency_ms": pl.Float64,
            "circuit_state": pl.Utf8,
            "circuit_failures": pl.Int64,
            "last_error": pl.Utf8,
            "recorded_at": pl.Utf8,
        }
        records: list[dict[str, Any]] = []
        now_str = datetime.now(UTC).isoformat()

        for name, m in self._metrics.items():
            cb = self._circuits.get(name)
            with m._lock:
                records.append(
                    {
                        "module_name": name,
                        "total_calls": m.total_calls,
                        "successful_calls": m.successful_calls,
                        "failed_calls": m.failed_calls,
                        "skipped_calls": m.skipped_calls,
                        "success_rate": float(round(m.success_rate, 4)),
                        "avg_latency_ms": float(round(m.avg_latency_ms, 2)),
                        "circuit_state": cb.state.value if cb else "unknown",
                        "circuit_failures": cb.failure_count if cb else 0,
                        "last_error": m.last_error,
                        "recorded_at": now_str,
                    }
                )

        if not records:
            return pl.DataFrame(schema=schema)
        return pl.DataFrame(records, schema=schema)

    @otel_trace("integration_bridge.export_metrics_to_duckdb")
    def export_metrics_to_duckdb(self, db_path: str | Path | None = None) -> int:
        """Modül metriklerini DuckDB tablosuna atomik olarak yazar.

        Args:
            db_path: Opsiyonel DuckDB veritabanı dosya yolu.

        Returns:
            int: Kaydedilen metrik satırı sayısı.
        """
        target_path = Path(db_path) if db_path is not None else DEFAULT_BRIDGE_AUDIT_DB_PATH
        target_path.parent.mkdir(parents=True, exist_ok=True)
        if target_path.exists() and target_path.stat().st_size == 0:
            target_path.unlink(missing_ok=True)

        df = self.export_metrics_to_polars()
        if len(df) == 0:
            return 0

        con = duckdb.connect(str(target_path))
        try:
            con.execute(
                """
                CREATE TABLE IF NOT EXISTS bist_integration_bridge_metrics (
                    module_name VARCHAR NOT NULL,
                    total_calls BIGINT NOT NULL,
                    successful_calls BIGINT NOT NULL,
                    failed_calls BIGINT NOT NULL,
                    skipped_calls BIGINT NOT NULL,
                    success_rate DOUBLE NOT NULL,
                    avg_latency_ms DOUBLE NOT NULL,
                    circuit_state VARCHAR NOT NULL,
                    circuit_failures BIGINT NOT NULL,
                    last_error VARCHAR,
                    recorded_at VARCHAR NOT NULL,
                    PRIMARY KEY (module_name, recorded_at)
                )
                """
            )
            con.register("df_metrics_view", df.to_arrow())
            con.execute(
                """
                INSERT OR REPLACE INTO bist_integration_bridge_metrics
                SELECT * FROM df_metrics_view
                """
            )
            con.commit()
            return len(df)
        finally:
            con.close()

    def query_metrics_duckdb(
        self,
        db_path: str | Path | None = None,
        limit: int = 100,
    ) -> pl.DataFrame:
        """DuckDB `bist_integration_bridge_metrics` tablosundan modül metriklerini Polars DataFrame olarak sorgular.

        Args:
            db_path: Opsiyonel DuckDB veritabanı dosya yolu.
            limit: Maksimum satır sayısı.

        Returns:
            pl.DataFrame: Metrik tablosu sonucu.
        """
        target_path = Path(db_path) if db_path is not None else DEFAULT_BRIDGE_AUDIT_DB_PATH
        if not target_path.exists():
            return self.export_metrics_to_polars().head(0)
        if target_path.stat().st_size == 0:
            target_path.unlink(missing_ok=True)
            return self.export_metrics_to_polars().head(0)

        con = duckdb.connect(str(target_path), read_only=True)
        try:
            tbl_check = con.execute(
                "SELECT count(*) FROM information_schema.tables WHERE table_name = 'bist_integration_bridge_metrics'"
            ).fetchone()
            if not tbl_check or tbl_check[0] == 0:
                return self.export_metrics_to_polars().head(0)
            return con.execute(
                "SELECT * FROM bist_integration_bridge_metrics ORDER BY recorded_at DESC LIMIT ?",
                [limit],
            ).pl()
        finally:
            con.close()

    @otel_trace("integration_bridge.export_reports_to_polars")
    def export_reports_to_polars(self) -> pl.DataFrame:
        """Geçmiş pipeline zenginleştirme raporlarını Polars DataFrame olarak döndürür.

        Returns:
            pl.DataFrame: Rapor geçmişi tablosu.
        """
        schema = {
            "ticker": pl.Utf8,
            "correlation_id": pl.Utf8,
            "total_latency_ms": pl.Float64,
            "success_count": pl.Int64,
            "failure_count": pl.Int64,
            "skip_count": pl.Int64,
            "is_healthy": pl.Boolean,
            "created_at": pl.Utf8,
        }
        with self._lock:
            records = [
                {
                    "ticker": r.ticker,
                    "correlation_id": r.correlation_id,
                    "total_latency_ms": float(r.total_latency_ms),
                    "success_count": int(r.success_count),
                    "failure_count": int(r.failure_count),
                    "skip_count": int(r.skip_count),
                    "is_healthy": bool(r.is_healthy),
                    "created_at": r.created_at,
                }
                for r in self._report_history
            ]

        if not records:
            return pl.DataFrame(schema=schema)
        return pl.DataFrame(records, schema=schema)

    @otel_trace("integration_bridge.export_reports_to_duckdb")
    def export_reports_to_duckdb(self, db_path: str | Path | None = None) -> int:
        """Pipeline zenginleştirme raporlarını DuckDB tablosuna yazar.

        Args:
            db_path: Opsiyonel DuckDB veritabanı dosya yolu.

        Returns:
            int: Kaydedilen rapor sayısı.
        """
        target_path = Path(db_path) if db_path is not None else DEFAULT_BRIDGE_AUDIT_DB_PATH
        target_path.parent.mkdir(parents=True, exist_ok=True)
        if target_path.exists() and target_path.stat().st_size == 0:
            target_path.unlink(missing_ok=True)

        df = self.export_reports_to_polars()
        if len(df) == 0:
            return 0

        con = duckdb.connect(str(target_path))
        try:
            con.execute(
                """
                CREATE TABLE IF NOT EXISTS bist_integration_bridge_reports (
                    ticker VARCHAR NOT NULL,
                    correlation_id VARCHAR NOT NULL PRIMARY KEY,
                    total_latency_ms DOUBLE NOT NULL,
                    success_count BIGINT NOT NULL,
                    failure_count BIGINT NOT NULL,
                    skip_count BIGINT NOT NULL,
                    is_healthy BOOLEAN NOT NULL,
                    created_at VARCHAR NOT NULL
                )
                """
            )
            con.register("df_reports_view", df.to_arrow())
            con.execute(
                """
                INSERT OR REPLACE INTO bist_integration_bridge_reports
                SELECT * FROM df_reports_view
                """
            )
            con.commit()
            return len(df)
        finally:
            con.close()

    def query_reports_duckdb(
        self,
        db_path: str | Path | None = None,
        limit: int = 100,
    ) -> pl.DataFrame:
        """DuckDB `bist_integration_bridge_reports` tablosundan pipeline raporlarını Polars DataFrame olarak sorgular.

        Args:
            db_path: Opsiyonel DuckDB veritabanı dosya yolu.
            limit: Maksimum satır sayısı.

        Returns:
            pl.DataFrame: Rapor tablosu sonucu.
        """
        target_path = Path(db_path) if db_path is not None else DEFAULT_BRIDGE_AUDIT_DB_PATH
        if not target_path.exists():
            return self.export_reports_to_polars().head(0)
        if target_path.stat().st_size == 0:
            target_path.unlink(missing_ok=True)
            return self.export_reports_to_polars().head(0)

        con = duckdb.connect(str(target_path), read_only=True)
        try:
            tbl_check = con.execute(
                "SELECT count(*) FROM information_schema.tables WHERE table_name = 'bist_integration_bridge_reports'"
            ).fetchone()
            if not tbl_check or tbl_check[0] == 0:
                return self.export_reports_to_polars().head(0)
            return con.execute(
                "SELECT * FROM bist_integration_bridge_reports ORDER BY created_at DESC LIMIT ?",
                [limit],
            ).pl()
        finally:
            con.close()

    def get_report_history(self, limit: int = 100) -> list[dict[str, Any]]:
        """Son üretilen entegrasyon raporlarını döndürür."""
        with self._lock:
            return [r.to_dict() for r in self._report_history[-limit:]]

    def __repr__(self) -> str:
        """IntegrationBridge metin gösterimi."""
        with self._lock:
            return (
                f"IntegrationBridge(baslatildi={self._initialized}, "
                f"toplam_cagri={self._call_counter}, gecmis_rapor={len(self._report_history)})"
            )


# =====================================================
# MODÜL DÜZEYİNDE KOLAYLIK (CONVENIENCE) FONKSİYONLARI
# =====================================================


def enhance_pipeline_result(
    ticker: str,
    result: dict[str, Any],
    features: dict[str, float],
    regime: str,
    bridge: IntegrationBridge | None = None,
) -> dict[str, Any]:
    """Pipeline sonucunu zenginleştirir."""
    inst = bridge if bridge is not None else integration_bridge
    return inst.enhance_pipeline_result(ticker=ticker, result=result, features=features, regime=regime)


def enhance_trade_plan(
    ticker: str,
    decision: dict[str, Any],
    prices: np.ndarray | list[float],
    regime: str,
    confidence: float = 0.5,
    bridge: IntegrationBridge | None = None,
) -> dict[str, Any]:
    """İşlem planını takas ve etki modelleriyle zenginleştirir."""
    inst = bridge if bridge is not None else integration_bridge
    return inst.enhance_trade_plan(
        ticker=ticker,
        decision=decision,
        prices=prices,
        regime=regime,
        confidence=confidence,
    )


def enhance_learning_cycle(
    learning_result: dict[str, Any],
    model_predictions: dict[str, np.ndarray] | None = None,
    bridge: IntegrationBridge | None = None,
) -> dict[str, Any]:
    """Öğrenme döngüsü çıktısını model bozulma ve drift ile zenginleştirir."""
    inst = bridge if bridge is not None else integration_bridge
    return inst.enhance_learning_cycle(learning_result=learning_result, model_predictions=model_predictions)


def enhance_event(
    event_id: str,
    event_type: str,
    payload: dict[str, Any],
    bridge: IntegrationBridge | None = None,
) -> dict[str, Any]:
    """Olay yükünü tekilleştirme ve zaman damgasıyla zenginleştirir."""
    inst = bridge if bridge is not None else integration_bridge
    return inst.enhance_event(event_id=event_id, event_type=event_type, payload=payload)


def enhance_portfolio_weights(
    target_weights: dict[str, float],
    current_weights: dict[str, float],
    sector_map: dict[str, str] | None = None,
    liquidity_scores: dict[str, float] | None = None,
    regime: str = "UNKNOWN",
    bridge: IntegrationBridge | None = None,
) -> dict[str, float]:
    """Portföy ağırlıklarını kısıt ve rejim modelleriyle zenginleştirir."""
    inst = bridge if bridge is not None else integration_bridge
    return inst.enhance_portfolio_weights(
        target_weights=target_weights,
        current_weights=current_weights,
        sector_map=sector_map,
        liquidity_scores=liquidity_scores,
        regime=regime,
    )


def record_model_outcome(
    model_id: str,
    predicted: float,
    actual: float,
    return_pct: float = 0.0,
    bridge: IntegrationBridge | None = None,
) -> None:
    """Model tahmin sonucunu kaydeder."""
    inst = bridge if bridge is not None else integration_bridge
    inst.record_model_outcome(model_id=model_id, predicted=predicted, actual=actual, return_pct=return_pct)


def record_calibration_data(
    brier_score: float,
    ece: float,
    bridge: IntegrationBridge | None = None,
) -> None:
    """Kalibrasyon metriklerini kaydeder."""
    inst = bridge if bridge is not None else integration_bridge
    inst.record_calibration_data(brier_score=brier_score, ece=ece)


def get_bridge_health(bridge: IntegrationBridge | None = None) -> dict[str, Any]:
    """Entegrasyon köprüsünün sağlık durumunu döndürür."""
    inst = bridge if bridge is not None else integration_bridge
    return inst.health_check()


def get_bridge_metrics(bridge: IntegrationBridge | None = None) -> dict[str, Any]:
    """Tüm alt modüllerin performans metriklerini döndürür."""
    inst = bridge if bridge is not None else integration_bridge
    return inst.get_metrics()


def get_integration_bridge() -> IntegrationBridge:
    """Tekil entegrasyon köprüsü örneğini döndürür."""
    return integration_bridge


def export_bridge_metrics_to_polars(bridge: IntegrationBridge | None = None) -> pl.DataFrame:
    """Köprü metriklerini Polars DataFrame olarak dışa aktarır."""
    inst = bridge if bridge is not None else integration_bridge
    return inst.export_metrics_to_polars()


def export_bridge_metrics_to_duckdb(
    db_path: str | Path | None = None,
    bridge: IntegrationBridge | None = None,
) -> int:
    """Köprü metriklerini DuckDB tablosuna yazar."""
    inst = bridge if bridge is not None else integration_bridge
    return inst.export_metrics_to_duckdb(db_path=db_path)


def export_bridge_reports_to_polars(bridge: IntegrationBridge | None = None) -> pl.DataFrame:
    """Köprü rapor geçmişini Polars DataFrame olarak dışa aktarır."""
    inst = bridge if bridge is not None else integration_bridge
    return inst.export_reports_to_polars()


def export_bridge_reports_to_duckdb(
    db_path: str | Path | None = None,
    bridge: IntegrationBridge | None = None,
) -> int:
    """Köprü rapor geçmişini DuckDB tablosuna yazar."""
    inst = bridge if bridge is not None else integration_bridge
    return inst.export_reports_to_duckdb(db_path=db_path)


def query_bridge_metrics_duckdb(
    db_path: str | Path | None = None,
    limit: int = 100,
    bridge: IntegrationBridge | None = None,
) -> pl.DataFrame:
    """DuckDB tablosundan modül metriklerini Polars DataFrame olarak sorgular."""
    inst = bridge if bridge is not None else integration_bridge
    return inst.query_metrics_duckdb(db_path=db_path, limit=limit)


def query_bridge_reports_duckdb(
    db_path: str | Path | None = None,
    limit: int = 100,
    bridge: IntegrationBridge | None = None,
) -> pl.DataFrame:
    """DuckDB tablosundan pipeline rapor geçmişini Polars DataFrame olarak sorgular."""
    inst = bridge if bridge is not None else integration_bridge
    return inst.query_reports_duckdb(db_path=db_path, limit=limit)


def get_bridge_report_history(limit: int = 100, bridge: IntegrationBridge | None = None) -> list[dict[str, Any]]:
    """Son üretilen entegrasyon raporlarını döndürür."""
    inst = bridge if bridge is not None else integration_bridge
    return inst.get_report_history(limit=limit)


# Singleton Örneği
integration_bridge: Final[IntegrationBridge] = IntegrationBridge()

__all__: list[str] = [
    "DEFAULT_BASE_POSITION_PCT",
    "DEFAULT_BRIDGE_AUDIT_DB_PATH",
    "DEFAULT_CIRCUIT_FAILURE_THRESHOLD",
    "DEFAULT_CIRCUIT_RECOVERY_TIMEOUT_SECONDS",
    "DEFAULT_HALF_OPEN_MAX_CALLS",
    "DEFAULT_LOG_SLOW_CALLS_MS",
    "DEFAULT_MAX_CONFIDENCE",
    "DEFAULT_MAX_REPORT_HISTORY",
    "DEFAULT_MAX_TICKER_LEN",
    "DEFAULT_MIN_CONFIDENCE",
    "BridgeConfig",
    "CircuitBreaker",
    "CircuitState",
    "EnhancementResult",
    "IntegrationBridge",
    "ModuleMetrics",
    "PipelineEnhancementReport",
    "enhance_event",
    "enhance_learning_cycle",
    "enhance_pipeline_result",
    "enhance_portfolio_weights",
    "enhance_trade_plan",
    "export_bridge_metrics_to_duckdb",
    "export_bridge_metrics_to_polars",
    "export_bridge_reports_to_duckdb",
    "export_bridge_reports_to_polars",
    "get_bridge_health",
    "get_bridge_metrics",
    "get_bridge_report_history",
    "get_integration_bridge",
    "integration_bridge",
    "query_bridge_metrics_duckdb",
    "query_bridge_reports_duckdb",
    "record_calibration_data",
    "record_model_outcome",
]
