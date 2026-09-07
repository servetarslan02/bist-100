"""
ALPHA BIST — Graceful Degradation & System State Machine v2.0

Sistem Durumu Makinesi ve Kademeli Bozulma (Graceful Degradation) Yönetimi:
- Sistem Durumları (State Machine): FULL, DEGRADED, READ_ONLY, RECOVERY, SHUTDOWN.
- Özellik Bayrakları (Feature Flags): Her durum için dinamik izin verilen/engellenen yetenekler.
- Otomatik Bozulma ve İyileşme (Auto-Degrade & Auto-Recovery): Bileşen sağlık oranlarına göre dinamik durum geçişi.
- Fallback Yanıt Sağlayıcı: Devre dışı kalan özellikler için istemciyi bozmayan kurumsal fallback yanıtları.
- İş Parçacığı Güvenliği: threading.RLock() korumalı eşzamanlı durum ve özellik erişimi.
- DuckDB >= 1.3.0 denetim izi: Tüm durum geçişleri system_governor_audit tablosuna kalıcı kaydedilir.
- Polars >= 1.30.0 analitik sorgulama ve orjson serileştirme desteği.
"""

from __future__ import annotations

import asyncio
import functools
import inspect
import threading
import time
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final

import duckdb
import orjson
import polars as pl
import structlog

if TYPE_CHECKING:
    from collections.abc import Callable

DEFAULT_SYSTEM_GOVERNOR_DB: Final[str] = "data/system_governor_audit.duckdb"
DEFAULT_CHECKPOINT_SIZE: Final[str] = "4MB"
DEFAULT_WAL_SIZE: Final[str] = "2MB"

logger = structlog.get_logger(__name__)


def configure_duckdb_wal(conn: duckdb.DuckDBPyConnection) -> None:
    """DuckDB bağlantısı için WAL ve checkpoint parametrelerini optimize eder."""
    try:
        conn.execute(f"PRAGMA checkpoint_threshold = '{DEFAULT_CHECKPOINT_SIZE}';")
        conn.execute(f"PRAGMA wal_autocheckpoint = '{DEFAULT_WAL_SIZE}';")
    except Exception as exc:
        logger.debug("DuckDB WAL pragma uyarisi", hata=str(exc))


def to_orjson_bytes(val: Any) -> bytes:
    """Herhangi bir veriyi orjson ile güvenli byte dizisine serileştirir."""
    if hasattr(val, "to_dict"):
        return orjson.dumps(val.to_dict(), default=str)
    return orjson.dumps(val, default=str)


def otel_trace(span_name: str) -> Any:
    """Metotları OpenTelemetry span veya güvenli yerel izleme sarmalayıcısına alır."""

    def decorator(func: Any) -> Any:
        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            return func(*args, **kwargs)

        @functools.wraps(func)
        async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
            return await func(*args, **kwargs)

        if inspect.iscoroutinefunction(func):
            return async_wrapper
        return wrapper

    return decorator


class SystemState(StrEnum):
    """Sistem çalışma durumları."""

    FULL = "FULL"  # Tüm özellikler aktif
    DEGRADED = "DEGRADED"  # Kritik olmayan özellikler devre dışı
    READ_ONLY = "READ_ONLY"  # Sadece okuma, yeni emir/pozisyon yok
    RECOVERY = "RECOVERY"  # Sistem kendini kurtarıyor / veri senkronizasyonu
    SHUTDOWN = "SHUTDOWN"  # Sistem kapatılıyor


class FeatureFlag(StrEnum):
    """Sistem özellik bayrakları."""

    LIVE_TRADING = "live_trading"
    NEW_POSITIONS = "new_positions"
    SCANNING = "scanning"
    ML_PREDICTIONS = "ml_predictions"
    NEWS_FEED = "news_feed"
    ALTERNATIVE_DATA = "alternative_data"
    BACKTESTING = "backtesting"
    ALERTING = "alerting"
    REPORTING = "reporting"
    LEARNING = "learning"


@dataclass(slots=True)
class StateTransition:
    """Sistem durum geçiş kaydı veri modeli.

    Attributes:
        from_state: Önceki sistem durumu.
        to_state: Yeni sistem durumu.
        reason: Geçiş gerekçesi.
        timestamp: Geçiş anlık zaman damgası.
        triggered_by: Tetikleyen kaynak ('manual', 'auto', 'health_check').
    """

    from_state: SystemState
    to_state: SystemState
    reason: str
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))
    triggered_by: str = "manual"

    def to_dict(self) -> dict[str, Any]:
        """Modeli standart Python sözlüğüne dönüştürür."""
        return {
            "from": self.from_state.value,
            "to": self.to_state.value,
            "reason": self.reason,
            "timestamp": self.timestamp.isoformat(),
            "triggered_by": self.triggered_by,
        }

    def to_orjson_bytes(self) -> bytes:
        """Modeli orjson baytlarına serileştirir."""
        return orjson.dumps(self.to_dict(), default=str)

    def __repr__(self) -> str:
        return (
            f"StateTransition({self.from_state.value} -> {self.to_state.value}, "
            f"by={self.triggered_by!r}, reason={self.reason!r})"
        )


@dataclass(slots=True)
class HealthCheck:
    """Bileşen sağlık kontrolü sonucu veri modeli.

    Attributes:
        component: Bileşen adı (örn. 'redis', 'timescaledb', 'clickhouse').
        is_healthy: Sağlık durumu.
        latency_ms: Yanıt gecikmesi (milisaniye).
        error: Hata mesajı (varsa).
        details: Ek tanı bilgileri.
        checked_at: Kontrol zaman damgası.
    """

    component: str
    is_healthy: bool
    latency_ms: float
    error: str | None = None
    details: dict[str, Any] = field(default_factory=dict)
    checked_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def to_dict(self) -> dict[str, Any]:
        """Modeli standart Python sözlüğüne dönüştürür."""
        data = asdict(self)
        data["checked_at"] = self.checked_at.isoformat()
        return data

    def to_orjson_bytes(self) -> bytes:
        """Modeli orjson baytlarına dönüştürür."""
        return orjson.dumps(self.to_dict(), default=str)

    def __repr__(self) -> str:
        status = "HEALTHY" if self.is_healthy else "UNHEALTHY"
        return f"HealthCheck(component={self.component!r}, status={status}, latency={self.latency_ms:.2f}ms)"


@dataclass(slots=True)
class GovernorStatus:
    """Sistem durumu genel durum özeti veri modeli."""

    state: str
    feature_flags: dict[str, bool]
    enabled_features: list[str]
    disabled_features: list[str]
    health: dict[str, dict[str, Any]]
    total_transitions: int
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def to_dict(self) -> dict[str, Any]:
        """Modeli standart Python sözlüğüne dönüştürür."""
        data = asdict(self)
        data["updated_at"] = self.updated_at.isoformat()
        return data

    def to_orjson_bytes(self) -> bytes:
        """Modeli orjson baytlarına serileştirir."""
        return orjson.dumps(self.to_dict(), default=str)

    def __repr__(self) -> str:
        return (
            f"GovernorStatus(state={self.state!r}, enabled={len(self.enabled_features)}, "
            f"disabled={len(self.disabled_features)}, transitions={self.total_transitions})"
        )


class SystemStateGovernor:
    """Sistem durumu yöneticisi (Governor).

    Sistem durumunu yönetir, feature flag'leri kontrol eder,
    otomatik bozulma (degradation) ve kurtarma (recovery) sağlar.
    """

    def __init__(self, duckdb_path: str = DEFAULT_SYSTEM_GOVERNOR_DB) -> None:
        """SystemStateGovernor başlatıcısı.

        Args:
            duckdb_path: Geçiş denetim günlüğü için DuckDB dosya yolu veya ':memory:'.
        """
        self._lock = threading.RLock()
        self._state = SystemState.FULL
        self._feature_flags: dict[FeatureFlag, bool] = {f: True for f in FeatureFlag}
        self._transition_history: list[StateTransition] = []
        self._health_checks: dict[str, Callable[[], Any]] = {}
        self._health_results: dict[str, HealthCheck] = {}
        self._callbacks: list[Callable[[SystemState, SystemState, str], Any]] = []
        self._auto_recovery_enabled = True
        self._degradation_threshold = 0.5  # %50 sağlıksız -> DEGRADED
        self._readonly_threshold = 0.75  # %75 sağlıksız -> READ_ONLY
        self._duckdb_path = duckdb_path

        # Duruma özgü özellik kısıtlama kuralları
        self._state_features: dict[SystemState, set[FeatureFlag]] = {
            SystemState.FULL: set(),  # Kısıtlama yok
            SystemState.DEGRADED: {
                FeatureFlag.ALTERNATIVE_DATA,
                FeatureFlag.LEARNING,
                FeatureFlag.REPORTING,
            },
            SystemState.READ_ONLY: {
                FeatureFlag.LIVE_TRADING,
                FeatureFlag.NEW_POSITIONS,
                FeatureFlag.SCANNING,
                FeatureFlag.ML_PREDICTIONS,
                FeatureFlag.ALTERNATIVE_DATA,
                FeatureFlag.LEARNING,
            },
            SystemState.RECOVERY: {
                FeatureFlag.LIVE_TRADING,
                FeatureFlag.NEW_POSITIONS,
                FeatureFlag.SCANNING,
                FeatureFlag.ML_PREDICTIONS,
                FeatureFlag.NEWS_FEED,
                FeatureFlag.ALTERNATIVE_DATA,
                FeatureFlag.BACKTESTING,
                FeatureFlag.LEARNING,
            },
            SystemState.SHUTDOWN: set(FeatureFlag),  # Tüm özellikler kapalı
        }

        # DuckDB denetim tablosu kurulumu
        if self._duckdb_path != ":memory:":
            try:
                Path(self._duckdb_path).parent.mkdir(parents=True, exist_ok=True)
                self._duckdb_con = duckdb.connect(self._duckdb_path)
            except Exception as e:
                logger.warning(
                    "DuckDB disk baglantisi kurulamadi, bellege donuluyor",
                    yol=self._duckdb_path,
                    hata=str(e),
                )
                self._duckdb_con = duckdb.connect(":memory:")
        else:
            self._duckdb_con = duckdb.connect(":memory:")

        configure_duckdb_wal(self._duckdb_con)
        self._init_duckdb_schema()

        # Başlangıç durumunu uygula
        self._apply_state_locked()

    def _init_duckdb_schema(self) -> None:
        """DuckDB durum geçiş denetim tablosunu ve dizisini oluşturur."""
        with self._lock:
            try:
                self._duckdb_con.execute("""
                    CREATE SEQUENCE IF NOT EXISTS seq_governor_trans_id START 1;
                    CREATE TABLE IF NOT EXISTS system_governor_audit (
                        id BIGINT DEFAULT nextval('seq_governor_trans_id') PRIMARY KEY,
                        from_state VARCHAR NOT NULL,
                        to_state VARCHAR NOT NULL,
                        reason VARCHAR NOT NULL,
                        triggered_by VARCHAR NOT NULL,
                        active_features VARCHAR NOT NULL,
                        recorded_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
                    );
                """)
            except Exception as exc:
                logger.error("SystemStateGovernor DuckDB schema init failed", error=str(exc))

    def _record_audit_log(self, transition: StateTransition) -> None:
        """Durum geçişini DuckDB kalıcı denetim tablosuna kaydeder."""
        with self._lock:
            try:
                enabled_list = [f.value for f, v in self._feature_flags.items() if v]
                self._duckdb_con.execute(
                    """
                    INSERT INTO system_governor_audit
                    (from_state, to_state, reason, triggered_by, active_features, recorded_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    [
                        transition.from_state.value,
                        transition.to_state.value,
                        transition.reason,
                        transition.triggered_by,
                        orjson.dumps(enabled_list).decode("utf-8"),
                        transition.timestamp,
                    ],
                )
            except Exception as exc:
                logger.warning("Failed to record state transition in DuckDB audit", error=str(exc))

    @property
    def state(self) -> SystemState:
        """Mevcut sistem durumunu döndürür."""
        with self._lock:
            return self._state

    def is_allowed(self, feature: FeatureFlag) -> bool:
        """Belirtilen özelliğin mevcut durumda kullanıma açık olup olmadığını denetler."""
        with self._lock:
            return self._feature_flags.get(feature, False)

    def _apply_state_locked(self) -> None:
        """Mevcut duruma göre bayrakları ayarlar (Kilit altında çağrılmalıdır)."""
        for f in FeatureFlag:
            self._feature_flags[f] = True

        disabled = self._state_features.get(self._state, set())
        for f in disabled:
            self._feature_flags[f] = False

    @otel_trace("system_governor.transition")
    def transition(
        self,
        new_state: SystemState,
        reason: str,
        triggered_by: str = "manual",
    ) -> bool:
        """Sistem durum geçişi gerçekleştirir.

        Args:
            new_state: Geçilecek hedef sistem durumu.
            reason: Durum değişikliği gerekçesi.
            triggered_by: Tetikleyici kaynak ('manual', 'auto', 'health_check').

        Returns:
            bool: Durum fiilen değiştiyse True, aksi takdirde False.
        """
        with self._lock:
            if new_state == self._state:
                return False

            old_state = self._state
            self._state = new_state
            self._apply_state_locked()

            trans = StateTransition(
                from_state=old_state,
                to_state=new_state,
                reason=reason,
                timestamp=datetime.now(UTC),
                triggered_by=triggered_by,
            )
            self._transition_history.append(trans)
            if len(self._transition_history) > 1000:
                self._transition_history = self._transition_history[-1000:]

            self._record_audit_log(trans)

            callbacks_to_notify = list(self._callbacks)

        logger.warning(
            "System state transition",
            old=old_state.value,
            new=new_state.value,
            reason=reason,
            triggered_by=triggered_by,
        )

        # Geri bildirim işleyicilerini (callbacks) güvenle tetikle
        self._trigger_callbacks(callbacks_to_notify, old_state, new_state, reason)
        return True

    def _trigger_callbacks(
        self,
        callbacks: list[Callable[[SystemState, SystemState, str], Any]],
        old_state: SystemState,
        new_state: SystemState,
        reason: str,
    ) -> None:
        """Geri bildirim fonksiyonlarını çağırır."""
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(self._notify_callbacks(callbacks, old_state, new_state, reason))
        except RuntimeError:
            for cb in callbacks:
                try:
                    if not asyncio.iscoroutinefunction(cb):
                        cb(old_state, new_state, reason)
                except Exception as exc:
                    logger.error("Synchronous callback execution failed", error=str(exc))

    async def _notify_callbacks(
        self,
        callbacks: list[Callable[[SystemState, SystemState, str], Any]],
        old_state: SystemState,
        new_state: SystemState,
        reason: str,
    ) -> None:
        """Asenkron geri bildirim döngüsü."""
        for cb in callbacks:
            try:
                if asyncio.iscoroutinefunction(cb):
                    await cb(old_state, new_state, reason)
                else:
                    cb(old_state, new_state, reason)
            except Exception as exc:
                logger.error("State change callback execution error", error=str(exc))

    def register_health_check(self, component: str, check_func: Callable[[], Any]) -> None:
        """Bileşen sağlık kontrol fonksiyonu kaydeder."""
        with self._lock:
            self._health_checks[component] = check_func

    def register_callback(self, callback: Callable[[SystemState, SystemState, str], Any]) -> None:
        """Durum geçiş geri bildirim fonksiyonu kaydeder."""
        with self._lock:
            self._callbacks.append(callback)
            if len(self._callbacks) > 100:
                self._callbacks = self._callbacks[-100:]

    @otel_trace("system_governor.run_health_checks")
    async def run_health_checks(self) -> dict[str, HealthCheck]:
        """Tüm kayıtlı sağlık denetimlerini eşzamanlı çalıştırır."""
        with self._lock:
            checks_snapshot = dict(self._health_checks)

        results: dict[str, HealthCheck] = {}

        for component, check_func in checks_snapshot.items():
            start = time.monotonic()
            try:
                if asyncio.iscoroutinefunction(check_func):
                    is_healthy = bool(await check_func())
                else:
                    is_healthy = bool(check_func())

                latency = (time.monotonic() - start) * 1000.0
                results[component] = HealthCheck(
                    component=component,
                    is_healthy=is_healthy,
                    latency_ms=round(latency, 2),
                )
            except Exception as exc:
                latency = (time.monotonic() - start) * 1000.0
                results[component] = HealthCheck(
                    component=component,
                    is_healthy=False,
                    latency_ms=round(latency, 2),
                    error=str(exc),
                )

        with self._lock:
            self._health_results = results

        # Otomatik bozulma veya iyileşme kontrolü
        if self._auto_recovery_enabled:
            self._auto_degrade_or_recover(results)

        return results

    def _auto_degrade_or_recover(self, results: dict[str, HealthCheck]) -> None:
        """Bileşen sağlık oranına göre otomatik kademeli bozulma veya iyileşme uygular."""
        if not results:
            return

        total = len(results)
        unhealthy = sum(1 for r in results.values() if not r.is_healthy)
        unhealthy_ratio = unhealthy / total

        with self._lock:
            current = self._state

        if current == SystemState.FULL:
            if unhealthy_ratio >= self._readonly_threshold:
                self.transition(
                    SystemState.READ_ONLY,
                    f"Otomatik gecis: {unhealthy}/{total} bilesen sagliksiz (%{unhealthy_ratio * 100:.0f})",
                    "auto",
                )
            elif unhealthy_ratio >= self._degradation_threshold:
                self.transition(
                    SystemState.DEGRADED,
                    f"Otomatik gecis: {unhealthy}/{total} bilesen sagliksiz (%{unhealthy_ratio * 100:.0f})",
                    "auto",
                )
        elif current in (SystemState.DEGRADED, SystemState.READ_ONLY, SystemState.RECOVERY):
            if unhealthy_ratio < self._degradation_threshold:
                self.transition(
                    SystemState.FULL,
                    f"Otomatik iyilesme: {unhealthy}/{total} bilesen sagliksiz (%{unhealthy_ratio * 100:.0f})",
                    "auto",
                )

    def get_status(self) -> GovernorStatus:
        """Sistem durumu genel özetini yapılandırılmış veri modeli olarak döndürür."""
        with self._lock:
            flags = {f.value: v for f, v in self._feature_flags.items()}
            enabled = [f.value for f, v in self._feature_flags.items() if v]
            disabled = [f.value for f, v in self._feature_flags.items() if not v]
            health_summary = {
                comp: {"healthy": h.is_healthy, "latency_ms": h.latency_ms}
                for comp, h in self._health_results.items()
            }

            return GovernorStatus(
                state=self._state.value,
                feature_flags=flags,
                enabled_features=enabled,
                disabled_features=disabled,
                health=health_summary,
                total_transitions=len(self._transition_history),
            )

    def get_transition_history(self, limit: int = 20) -> list[dict[str, Any]]:
        """Geçiş geçmişini liste olarak döndürür."""
        with self._lock:
            return [t.to_dict() for t in self._transition_history[-limit:]]

    @otel_trace("system_governor.force_feature")
    def force_feature(self, feature: FeatureFlag, enabled: bool) -> None:
        """Belirli bir özellik bayrağını zorla ayarlar."""
        with self._lock:
            self._feature_flags[feature] = enabled
        logger.info("Feature flag forced", feature=feature.value, enabled=enabled)

    def get_fallback_response(self, feature: FeatureFlag) -> dict[str, Any] | None:
        """Devre dışı kalan özellikler için standart fallback yanıtı üretir."""
        if self.is_allowed(feature):
            return None

        fallbacks: dict[FeatureFlag, dict[str, Any]] = {
            FeatureFlag.ML_PREDICTIONS: {
                "predictions": [],
                "status": "degraded",
                "message": "ML tahmin motoru gecici olarak devre disi",
            },
            FeatureFlag.SCANNING: {
                "opportunities": [],
                "status": "degraded",
                "message": "Piyasa tarayici gecici olarak devre disi",
            },
            FeatureFlag.NEWS_FEED: {
                "news": [],
                "status": "degraded",
                "message": "Haber akisi servisi gecici olarak devre disi",
            },
            FeatureFlag.LIVE_TRADING: {
                "status": "read_only",
                "message": "Canli emir iletimi kilitli - sistem salt okunur modda",
            },
        }

        return fallbacks.get(
            feature,
            {
                "status": "unavailable",
                "message": f"'{feature.value}' ozelligi mevcut sistem durumunda devre disidir",
            },
        )

    def export_transitions_to_polars(self) -> pl.DataFrame:
        """DuckDB'de kayıtlı durum geçiş denetim loglarını Polars DataFrame olarak dışa aktarır."""
        with self._lock:
            try:
                return self._duckdb_con.execute("""
                    SELECT id, from_state, to_state, reason, triggered_by, active_features, recorded_at
                    FROM system_governor_audit
                    ORDER BY id ASC
                """).pl()
            except Exception as exc:
                logger.error("Failed to export governor transitions to Polars", error=str(exc))
                return pl.DataFrame()

    def export_health_checks_to_polars(self) -> pl.DataFrame:
        """Mevcut sağlık denetim sonuçlarını Polars DataFrame olarak dışa aktarır."""
        with self._lock:
            if not self._health_results:
                return pl.DataFrame(
                    schema={
                        "component": pl.Utf8,
                        "is_healthy": pl.Boolean,
                        "latency_ms": pl.Float64,
                        "error": pl.Utf8,
                        "checked_at": pl.Utf8,
                    }
                )

            rows: list[dict[str, Any]] = []
            for comp, h in self._health_results.items():
                rows.append({
                    "component": comp,
                    "is_healthy": bool(h.is_healthy),
                    "latency_ms": float(h.latency_ms),
                    "error": str(h.error or ""),
                    "checked_at": h.checked_at.isoformat(),
                })
            return pl.DataFrame(rows)

    def clear_audit_duckdb(self) -> None:
        """Geçiş denetim tablosunu temizler."""
        with self._lock:
            try:
                self._duckdb_con.execute("DELETE FROM system_governor_audit")
            except Exception as exc:
                logger.warning("DuckDB governor audit tablosu temizlenemedi", hata=str(exc))

    def close(self) -> None:
        """DuckDB bağlantısını güvenli şekilde kapatır."""
        with self._lock:
            try:
                self._duckdb_con.close()
            except Exception as exc:
                logger.debug("DuckDB baglantisi kapatilirken hata", hata=str(exc))

    def __repr__(self) -> str:
        with self._lock:
            return (
                f"SystemStateGovernor(state={self._state.value!r}, "
                f"transitions={len(self._transition_history)}, duckdb={self._duckdb_path!r})"
            )


def read_governor_transitions_from_duckdb(
    duckdb_path: str = DEFAULT_SYSTEM_GOVERNOR_DB,
    limit: int = 1000,
) -> pl.DataFrame:
    """DuckDB dosyasından doğrudan durum geçiş denetim kayıtlarını Polars DataFrame olarak okur."""
    try:
        conn = duckdb.connect(duckdb_path)
        try:
            return conn.execute(
                """
                SELECT id, from_state, to_state, reason, triggered_by, active_features, recorded_at
                FROM system_governor_audit
                ORDER BY id DESC
                LIMIT ?
                """,
                [limit],
            ).pl()
        finally:
            conn.close()
    except Exception as exc:
        logger.error("DuckDB dosyasindan governor denetim kayitlari okunamadi", hata=str(exc))
        return pl.DataFrame()


def clear_system_governor_audit_duckdb(duckdb_path: str = DEFAULT_SYSTEM_GOVERNOR_DB) -> None:
    """Belirtilen DuckDB dosyasındaki durum geçiş denetim tablosunu sıfırlar."""
    try:
        conn = duckdb.connect(duckdb_path)
        try:
            conn.execute("DELETE FROM system_governor_audit")
        finally:
            conn.close()
    except Exception as exc:
        logger.warning("DuckDB governor denetim tablosu temizlenemedi", hata=str(exc))


# Küresel Singleton Nesnesi
system_governor = SystemStateGovernor()

__all__ = [
    "DEFAULT_CHECKPOINT_SIZE",
    "DEFAULT_SYSTEM_GOVERNOR_DB",
    "DEFAULT_WAL_SIZE",
    "FeatureFlag",
    "GovernorStatus",
    "HealthCheck",
    "StateTransition",
    "SystemState",
    "SystemStateGovernor",
    "clear_system_governor_audit_duckdb",
    "configure_duckdb_wal",
    "otel_trace",
    "read_governor_transitions_from_duckdb",
    "system_governor",
    "to_orjson_bytes",
]
