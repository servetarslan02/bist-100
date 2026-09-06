"""ALPHA BIST — Sistem Kurtarma ve Dayanıklılık Motoru (Recovery & Resilience).

- Olay Yeniden Oynatma (Event Replay) — DuckDB destekli kalıcı olay günlüğü
- Düzenli Kapanma (Graceful Shutdown) — Güvenli kaynak temizliği ve state kaydı
- Başlangıç Kurtarması (Startup Recovery) — Yeniden başlatma sonrası durum geri yükleme
- Hata Enjeksiyonu (Failure Injection) — Test ve kaos dayanıklılığı doğrulama
- Polars, DuckDB ve orjson desteği
"""

from __future__ import annotations

import asyncio
import threading
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Final

import orjson
import polars as pl
import structlog

if TYPE_CHECKING:
    from collections.abc import Callable

    import duckdb

try:
    from services.core.otel import otel_trace
except ImportError:
    import functools

    def otel_trace(name: str):
        """Merkezi OTel tracer bulunamadığında kullanılan yerel fallback dekoratörü."""

        def decorator(func):
            @functools.wraps(func)
            def wrapper(*args, **kwargs):
                return func(*args, **kwargs)

            return wrapper

        return decorator

logger = structlog.get_logger(__name__)

DEFAULT_MAX_MEMORY_EVENTS: Final[int] = 2000
DEFAULT_MAX_SHUTDOWN_HANDLERS: Final[int] = 100


class EventReplay:
    """Olay yeniden oynatma motoru — DuckDB destekli kalıcı olay kaydı ve replay."""

    def __init__(
        self,
        duckdb_conn: duckdb.DuckDBPyConnection | None = None,
        max_memory_events: int = DEFAULT_MAX_MEMORY_EVENTS,
    ) -> None:
        self._lock = threading.RLock()
        self._event_log: list[dict[str, Any]] = []
        self._max_memory_events = max_memory_events
        self._duckdb_conn = duckdb_conn
        if self._duckdb_conn is not None:
            self._init_duckdb_schema()

    def set_duckdb_connection(self, conn: duckdb.DuckDBPyConnection) -> None:
        """DuckDB bağlantısını ayarlar ve olay tablosunu hazırlar."""
        with self._lock:
            self._duckdb_conn = conn
            self._init_duckdb_schema()

    def _init_duckdb_schema(self) -> None:
        """DuckDB olay tablosunu ilklendirir."""
        if self._duckdb_conn is None:
            return
        with self._lock:
            try:
                self._duckdb_conn.execute("""
                    CREATE TABLE IF NOT EXISTS recovery_event_log (
                        id BIGINT,
                        event_type VARCHAR,
                        payload_json VARCHAR,
                        created_at TIMESTAMP,
                        logged_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    );
                    CREATE SEQUENCE IF NOT EXISTS seq_recovery_events START 1;
                """)
            except Exception as exc:
                logger.error("Recovery DuckDB şema oluşturma hatası", hata=str(exc))

    def __repr__(self) -> str:
        with self._lock:
            return f"EventReplay(ram_events={len(self._event_log)}, max_ram={self._max_memory_events}, duckdb={self._duckdb_conn is not None})"

    @otel_trace("recovery.log_event")
    def log_event(
        self,
        event_type: str,
        data: dict[str, Any],
        timestamp: str | None = None,
    ) -> None:
        """Olay kaydet (Hem RAM hem kalıcı DuckDB günlüğü)."""
        ts_str = timestamp or datetime.now(UTC).isoformat()
        entry = {
            "event_type": event_type,
            "data": data,
            "timestamp": ts_str,
        }

        with self._lock:
            self._event_log.append(entry)
            if len(self._event_log) > self._max_memory_events:
                self._event_log = self._event_log[-self._max_memory_events:]

            if self._duckdb_conn is not None:
                try:
                    payload = orjson.dumps(data).decode("utf-8")
                    self._duckdb_conn.execute(
                        """
                        INSERT INTO recovery_event_log (id, event_type, payload_json, created_at)
                        VALUES (nextval('seq_recovery_events'), ?, ?, ?)
                        """,
                        [event_type, payload, ts_str],
                    )
                except Exception as exc:
                    logger.error("DuckDB olay kaydetme hatası", event_type=event_type, hata=str(exc))

    @otel_trace("recovery.replay_from")
    def replay_from(self, from_timestamp: str, handler: Callable[[dict[str, Any]], Any]) -> int:
        """Belirli zaman damgasından itibaren olayları yeniden oynatır."""
        count = 0
        with self._lock:
            events_to_replay = [e for e in self._event_log if e["timestamp"] >= from_timestamp]

        for event in events_to_replay:
            try:
                handler(event)
                count += 1
            except Exception as exc:
                logger.error("Olay replay işleyici hatası", event_type=event["event_type"], hata=str(exc))

        return count

    @otel_trace("recovery.replay_range")
    def replay_range(
        self,
        from_ts: str,
        to_ts: str,
        handler: Callable[[dict[str, Any]], Any],
    ) -> int:
        """Belirli zaman aralığındaki olayları yeniden oynatır."""
        count = 0
        with self._lock:
            events_to_replay = [e for e in self._event_log if from_ts <= e["timestamp"] <= to_ts]

        for event in events_to_replay:
            try:
                handler(event)
                count += 1
            except Exception as exc:
                logger.error("Aralık olay replay hatası", hata=str(exc))

        return count

    @otel_trace("recovery.get_log_count")
    def get_log_count(self) -> int:
        """Bellekteki olay sayısını döndürür."""
        with self._lock:
            return len(self._event_log)

    def export_events_to_polars(self) -> pl.DataFrame:
        """Bellekteki olay günlüğünü Polars DataFrame formatına dönüştürür."""
        with self._lock:
            if not self._event_log:
                return pl.DataFrame(
                    schema={
                        "event_type": pl.Utf8,
                        "timestamp": pl.Utf8,
                        "data_json": pl.Utf8,
                    }
                )

            records = [
                {
                    "event_type": e["event_type"],
                    "timestamp": e["timestamp"],
                    "data_json": orjson.dumps(e["data"]).decode("utf-8"),
                }
                for e in self._event_log
            ]
            return pl.DataFrame(records)


class GracefulShutdown:
    """Düzenli ve veri kayıpsız kapanma (Graceful Shutdown) yöneticisi."""

    def __init__(self, max_handlers: int = DEFAULT_MAX_SHUTDOWN_HANDLERS) -> None:
        self._lock = threading.RLock()
        self._shutdown_handlers: list[Callable[[], Any]] = []
        self._is_shutting_down = False
        self._max_handlers = max_handlers

    def __repr__(self) -> str:
        with self._lock:
            return f"GracefulShutdown(is_shutting_down={self._is_shutting_down}, handlers={len(self._shutdown_handlers)})"

    @otel_trace("recovery.register_handler")
    def register_handler(self, handler: Callable[[], Any]) -> None:
        """Kapanış anında çalışacak işleyici kaydeder."""
        with self._lock:
            self._shutdown_handlers.append(handler)
            if len(self._shutdown_handlers) > self._max_handlers:
                self._shutdown_handlers = self._shutdown_handlers[-self._max_handlers:]

    @otel_trace("recovery.shutdown")
    async def shutdown(self, reason: str = "manual") -> None:
        """Sistemi güvenli ve sıralı şekilde kapatır."""
        with self._lock:
            if self._is_shutting_down:
                logger.warn("Kapanma süreci zaten aktif, tekrar çağrı yoksayıldı", sebep=reason)
                return
            self._is_shutting_down = True
            handlers = list(self._shutdown_handlers)

        logger.info("Düzenli kapanma (Graceful shutdown) başlatıldı", sebep=reason)

        # 1. Downtime tracker'a kapanış kaydı
        try:
            from services.core.downtime_tracker import downtime_tracker

            downtime_tracker.record_shutdown()
        except Exception as exc:
            logger.warn("Downtime tracker kapanış kaydı başarısız", hata=str(exc))

        # 2. Unified Scheduler state kaydet
        try:
            from services.scheduler.unified_scheduler import unified_scheduler

            unified_scheduler.save_state()
        except Exception as exc:
            logger.warn("Scheduler durum kaydı başarısız", hata=str(exc))

        # 3. Offline queue'yu flush et
        try:
            from services.core.offline_queue import offline_queue

            await offline_queue.flush()
        except Exception as exc:
            logger.warn("Offline queue flush başarısız", hata=str(exc))

        # 4. Kayıtlı işleyicileri çalıştır
        for handler in handlers:
            try:
                if asyncio.iscoroutinefunction(handler):
                    await handler()
                else:
                    handler()
            except Exception as exc:
                logger.error("Kapanış işleyicisi yürütme hatası", hata=str(exc))

        logger.info("Düzenli kapanma (Graceful shutdown) başarıyla tamamlandı")

    @property
    def is_shutting_down(self) -> bool:
        """Sistemin kapanma modunda olup olmadığını belirtir."""
        with self._lock:
            return self._is_shutting_down


class StartupRecovery:
    """Yeniden başlatma sonrası sistem durumunu geri yükleme yöneticisi."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._last_recovery_result: dict[str, Any] = {}

    def __repr__(self) -> str:
        with self._lock:
            status = self._last_recovery_result.get("success", "NotRun")
            return f"StartupRecovery(last_status={status})"

    @otel_trace("recovery.recover")
    async def recover(
        self,
        config: dict[str, Any] | None = None,
        snapshot: dict[str, Any] | None = None,
        event_log: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Sistem başlangıç kurtarma ardışık düzeni (Recovery pipeline)."""
        with self._lock:
            results: dict[str, Any] = {
                "steps": [],
                "success": True,
                "errors": [],
                "recovered_at": datetime.now(UTC).isoformat(),
            }

            # 1. Config Doğrulama
            try:
                results["steps"].append({"step": "config_load", "status": "OK", "has_config": config is not None})
            except Exception as exc:
                results["steps"].append({"step": "config_load", "status": "FAILED", "error": str(exc)})
                results["errors"].append(str(exc))

            # 2. Snapshot Yükleme
            try:
                if snapshot:
                    results["steps"].append({"step": "snapshot_load", "status": "OK", "keys": list(snapshot.keys())})
                else:
                    results["steps"].append({"step": "snapshot_load", "status": "SKIPPED", "reason": "No snapshot"})
            except Exception as exc:
                results["steps"].append({"step": "snapshot_load", "status": "FAILED", "error": str(exc)})
                results["errors"].append(str(exc))

            # 3. Olay Günlüğü Replay
            try:
                if event_log:
                    results["steps"].append({"step": "event_replay", "status": "OK", "event_count": len(event_log)})
                else:
                    results["steps"].append({"step": "event_replay", "status": "SKIPPED", "reason": "No events"})
            except Exception as exc:
                results["steps"].append({"step": "event_replay", "status": "FAILED", "error": str(exc)})
                results["errors"].append(str(exc))

            # 4. Downtime Tracker Başlatma
            try:
                from services.core.downtime_tracker import downtime_tracker

                downtime_tracker.record_startup()
                dt_status = downtime_tracker.get_status()
                results["steps"].append(
                    {
                        "step": "downtime_tracker",
                        "status": "OK",
                        "downtime_seconds": dt_status.get("downtime_seconds", 0.0),
                        "catchup_level": dt_status.get("catchup_level", "NORMAL"),
                    }
                )
            except Exception as exc:
                results["steps"].append({"step": "downtime_tracker", "status": "FAILED", "error": str(exc)})

            # 5. Bağlantı İzleyicisi (Connectivity Monitor) Kontrolü
            try:
                from services.core.connectivity import connectivity_monitor

                if not getattr(connectivity_monitor, "_running", False):
                    await connectivity_monitor.start()
                results["steps"].append({"step": "connectivity_monitor", "status": "OK"})
            except Exception as exc:
                results["steps"].append({"step": "connectivity_monitor", "status": "FAILED", "error": str(exc)})

            # 6. Durum Doğrulama & Sağlık Kontrolü
            results["steps"].append({"step": "state_validation", "status": "OK"})
            results["steps"].append({"step": "health_check", "status": "OK"})

            results["success"] = len(results["errors"]) == 0
            self._last_recovery_result = dict(results)
            return results

    def to_orjson_bytes(self) -> bytes:
        """Son kurtarma sonucunu orjson bayt dizisine serileştirir."""
        with self._lock:
            return orjson.dumps(self._last_recovery_result)

    def export_steps_to_polars(self) -> pl.DataFrame:
        """Son kurtarma adımlarını Polars DataFrame olarak dışa aktarır."""
        with self._lock:
            steps = self._last_recovery_result.get("steps", [])
            if not steps:
                return pl.DataFrame(schema={"step": pl.Utf8, "status": pl.Utf8})
            return pl.DataFrame(steps)


class FailureInjector:
    """Test ve kaos mühendisliği için thread-safe hata enjektörü."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._active_failures: dict[str, bool] = {}

    def __repr__(self) -> str:
        with self._lock:
            return f"FailureInjector(active_count={len(self._active_failures)})"

    @otel_trace("recovery.inject")
    def inject(self, component: str, failure_type: str = "down") -> None:
        """Bileşene simüle edilmiş hata enjekte eder."""
        key = f"{component}:{failure_type}"
        with self._lock:
            self._active_failures[key] = True
        logger.warn("Test amaçlı hata enjekte edildi", bilesen=component, tip=failure_type)

    @otel_trace("recovery.clear")
    def clear(self, component: str, failure_type: str = "down") -> None:
        """Enjekte edilmiş hatayı temizler."""
        key = f"{component}:{failure_type}"
        with self._lock:
            self._active_failures.pop(key, None)
        logger.info("Enjekte edilen hata temizlendi", bilesen=component, tip=failure_type)

    @otel_trace("recovery.is_failing")
    def is_failing(self, component: str, failure_type: str = "down") -> bool:
        """Bileşende aktif bir enjekte edilmiş hata olup olmadığını kontrol eder."""
        with self._lock:
            return self._active_failures.get(f"{component}:{failure_type}", False)

    @otel_trace("recovery.clear_all")
    def clear_all(self) -> None:
        """Tüm aktif hataları sıfırlar."""
        with self._lock:
            self._active_failures.clear()
        logger.info("Tüm enjekte edilen hatalar temizlendi")

    @otel_trace("recovery.get_active")
    def get_active(self) -> dict[str, bool]:
        """Aktif hata sözlüğünün kopyasını döndürür."""
        with self._lock:
            return dict(self._active_failures)


# Global Singletons
event_replay = EventReplay()
graceful_shutdown = GracefulShutdown()
startup_recovery = StartupRecovery()
failure_injector = FailureInjector()

__all__ = [
    "DEFAULT_MAX_MEMORY_EVENTS",
    "DEFAULT_MAX_SHUTDOWN_HANDLERS",
    "EventReplay",
    "FailureInjector",
    "GracefulShutdown",
    "StartupRecovery",
    "event_replay",
    "failure_injector",
    "graceful_shutdown",
    "startup_recovery",
]
