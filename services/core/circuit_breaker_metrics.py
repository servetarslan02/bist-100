"""ALPHA BIST — Kurumsal Circuit Breaker Metrik Toplayıcı ve Prometheus/JSON Dışa Aktarıcısı.

Bu modül, mikroservis ve dış veri sağlayıcı devre kesicilerinin (Circuit Breaker)
sağlık, durum ve güvenilirlik metriklerini merkezi olarak toplar, Prometheus, Polars,
DuckDB ve orjson formatlarında dışa aktarır (Monitoring / Dashboarding / Observability).

Özellikler:
- Thread-Safe: RLock ile eşzamanlı kayıt, metrik dışa aktarımı ve durum takibi.
- O(1) Durum Değişiklik Geçmişi: collections.deque(maxlen=...) ile sabit bellek garantisi.
- Çoklu Sağlayıcı Uyumluluğu: Hem ham CircuitBreaker hem de ProtectedProvider nesnelerinden metrik çekme.
- Prometheus Standartları: Güvenli label escaping ve geçerli gauge/counter çıktıları.
- Polars & DuckDB Entegrasyonu: Devre kesici snapshot ve geçiş tarihçesinin yüksek hızlı analitiği.
- orjson Entegrasyonu: Yüksek performanslı JSON serileştirme.
"""

from __future__ import annotations

import asyncio
import math
import threading
from collections import deque
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

import duckdb
import orjson
import polars as pl
import structlog

from services.core.otel import otel_trace

logger = structlog.get_logger(__name__)

# Varsayılan Yapılandırma Sabitleri
DEFAULT_MAX_HISTORY: Final[int] = 1000
DEFAULT_HISTORY_LIMIT: Final[int] = 50
DEFAULT_METRICS_HISTORY_DB_PATH: Final[str] = "data/circuit_breaker_history.duckdb"


@dataclass(slots=True)
class CircuitBreakerSnapshot:
    """Belirli bir devre kesicinin anlık durum ve sayaç fotoğrafı.

    Attributes:
        name: Devre kesicinin tekil adı.
        state: Anlık devre durumu ("CLOSED", "OPEN", "HALF_OPEN").
        failure_count: Ardışık başarısızlık sayısı.
        success_count: Ardışık veya toplam başarı sayısı.
        failure_threshold: Devreyi OPEN yapan eşik değer.
        recovery_timeout_seconds: Devrenin HALF_OPEN'a geçmesi için bekleme süresi.
        last_failure_time: Son başarısızlık zaman damgası (ISO 8601).
        last_success_time: Son başarı zaman damgası (ISO 8601).
        total_requests: İşlenen toplam istek sayısı.
        total_failures: Toplam başarısız istek sayısı.
        total_successes: Toplam başarılı istek sayısı.
        uptime_percentage: Çalışabilirlik / başarı yüzdesi (%0.0 - %100.0).
    """

    name: str
    state: str
    failure_count: int
    success_count: int
    failure_threshold: int
    recovery_timeout_seconds: int
    last_failure_time: str | None
    last_success_time: str | None
    total_requests: int
    total_failures: int
    total_successes: int
    uptime_percentage: float

    def to_dict(self) -> dict[str, Any]:
        """Snapshot verilerini serileştirilebilir bir sözlüğe dönüştürür.

        Returns:
            dict[str, Any]: JSON uyumlu durum verileri.
        """
        safe_uptime = self.uptime_percentage
        if math.isnan(safe_uptime) or math.isinf(safe_uptime):
            safe_uptime = 100.0

        return {
            "name": self.name,
            "state": self.state,
            "failure_count": self.failure_count,
            "success_count": self.success_count,
            "failure_threshold": self.failure_threshold,
            "recovery_timeout_seconds": self.recovery_timeout_seconds,
            "last_failure": self.last_failure_time,
            "last_success": self.last_success_time,
            "total_requests": self.total_requests,
            "total_failures": self.total_failures,
            "total_successes": self.total_successes,
            "uptime_pct": round(min(100.0, max(0.0, safe_uptime)), 2),
        }

    def __repr__(self) -> str:
        """Snapshot için bilgilendirici metin temsili."""
        return (
            f"CircuitBreakerSnapshot(name='{self.name}', state='{self.state}', "
            f"failures={self.failure_count}/{self.failure_threshold}, "
            f"uptime={round(self.uptime_percentage, 1)}%)"
        )


class CircuitBreakerMetricsCollector:
    """Merkezi devre kesici metrik toplayıcı ve export yöneticisi.

    Tüm kayıtlı devre kesicilerin durumunu eşzamanlı güvenli (thread-safe)
    olarak takip eder, durum geçişlerinin tarihçesini tutar ve Prometheus / JSON / Polars
    formatlarında sunar.
    """

    def __init__(self, max_history: int = DEFAULT_MAX_HISTORY) -> None:
        """Metrik toplayıcıyı başlatır.

        Args:
            max_history: Bellekte saklanacak maksimum durum değişikliği sayısı.
        """
        self._tracked_breakers: dict[str, Any] = {}
        self._max_history: int = max(1, max_history)
        self._history: deque[dict[str, Any]] = deque(maxlen=self._max_history)
        self._lock: threading.RLock = threading.RLock()

    @otel_trace("circuit_breaker_metrics.track")
    def track(self, breaker: Any) -> None:
        """Bir devre kesici veya korumalı sağlayıcıyı merkezi izlemeye alır.

        Args:
            breaker: İzlenecek CircuitBreaker veya ProtectedProvider nesnesi.
        """
        if not hasattr(breaker, "name"):
            logger.warning("gecersiz_breaker_izleme_reddedildi", breaker=str(breaker))
            return

        with self._lock:
            self._tracked_breakers[breaker.name] = breaker

        logger.debug("circuit_breaker_izlemeye_alindi", name=breaker.name)

    def untrack(self, name: str) -> None:
        """Devre kesiciyi merkezi izlemeden çıkarır.

        Args:
            name: İzlemeden çıkarılacak devre kesici adı.
        """
        with self._lock:
            removed = self._tracked_breakers.pop(name, None)

        if removed is not None:
            logger.debug("circuit_breaker_izlemeden_cikarildi", name=name)

    def get_snapshot(self, name: str) -> CircuitBreakerSnapshot | None:
        """Belirtilen devre kesicinin anlık sağlık ve metrik görüntüsünü çıkarır.

        Args:
            name: Devre kesici adı.

        Returns:
            CircuitBreakerSnapshot | None: Varsa snapshot, yoksa None.
        """
        with self._lock:
            breaker = self._tracked_breakers.get(name)

        if not breaker:
            return None

        # Farklı nesne modellerinden (CircuitBreaker veya ProtectedProvider) esnek metrik çekme
        target = getattr(breaker, "circuit", breaker)

        # Durum tespiti
        raw_state = getattr(target, "state", "CLOSED")
        state_str = raw_state.value if hasattr(raw_state, "value") else str(raw_state)

        failure_count = int(getattr(target, "failure_count", 0))
        failure_threshold = int(getattr(target, "failure_threshold", 5))
        recovery_timeout = int(getattr(target, "recovery_timeout_seconds", 30))

        last_fail_raw = getattr(target, "last_failure_time", None)
        last_failure_time = (
            last_fail_raw.isoformat()
            if isinstance(last_fail_raw, datetime)
            else (str(last_fail_raw) if last_fail_raw else None)
        )

        last_succ_raw = getattr(target, "last_success_time", None)
        last_success_time = (
            last_succ_raw.isoformat()
            if isinstance(last_succ_raw, datetime)
            else (str(last_succ_raw) if last_succ_raw else None)
        )

        # İstek sayaçları (doğrudan veya reliability katmanından)
        reliability = getattr(breaker, "reliability", None)
        if reliability is not None and hasattr(reliability, "get_stats"):
            stats = reliability.get_stats()
            total_req = int(stats.get("total_calls", 0))
            total_fail = int(stats.get("total_failures", 0))
            total_succ = max(0, total_req - total_fail)
            success_count = total_succ
        else:
            total_req = int(getattr(breaker, "_total_requests", getattr(target, "_total_requests", 0)))
            total_fail = int(getattr(breaker, "_total_failures", getattr(target, "_total_failures", failure_count)))
            total_succ = int(getattr(breaker, "_total_successes", getattr(target, "_total_successes", 0)))
            success_count = int(getattr(breaker, "success_count", getattr(target, "half_open_calls", total_succ)))

        if total_req > 0:
            safe_succ = min(total_req, max(0, total_succ))
            uptime = (safe_succ / total_req) * 100.0
        else:
            uptime = 100.0 if failure_count == 0 else 0.0

        if math.isnan(uptime) or math.isinf(uptime):
            uptime = 100.0

        return CircuitBreakerSnapshot(
            name=breaker.name,
            state=state_str,
            failure_count=failure_count,
            success_count=success_count,
            failure_threshold=failure_threshold,
            recovery_timeout_seconds=recovery_timeout,
            last_failure_time=last_failure_time,
            last_success_time=last_success_time,
            total_requests=total_req,
            total_failures=total_fail,
            total_successes=total_succ,
            uptime_percentage=round(min(100.0, max(0.0, uptime)), 2),
        )

    def get_all_snapshots(self) -> list[CircuitBreakerSnapshot]:
        """Tüm kayıtlı devre kesicilerin snapshot listesini döner.

        Returns:
            list[CircuitBreakerSnapshot]: Tüm izlenen devre kesicilerin durumları.
        """
        with self._lock:
            names = list(self._tracked_breakers.keys())

        snapshots: list[CircuitBreakerSnapshot] = []
        for name in names:
            snap = self.get_snapshot(name)
            if snap is not None:
                snapshots.append(snap)
        return snapshots

    @otel_trace("circuit_breaker_metrics.export_prometheus")
    def export_prometheus(self) -> str:
        """Prometheus metin formatında tüm devre kesici metriklerini dışa aktarır.

        Returns:
            str: Prometheus uyumlu metrik çıktısı.
        """
        snapshots = self.get_all_snapshots()
        lines: list[str] = [
            "# HELP circuit_breaker_state Circuit breaker durumu (0=CLOSED, 1=HALF_OPEN, 2=OPEN)",
            "# TYPE circuit_breaker_state gauge",
            "# HELP circuit_breaker_failures Mevcut ardışık hata sayısı",
            "# TYPE circuit_breaker_failures gauge",
            "# HELP circuit_breaker_requests Toplam işlenen istek adedi",
            "# TYPE circuit_breaker_requests counter",
            "# HELP circuit_breaker_total_failures Toplam başarısız istek adedi",
            "# TYPE circuit_breaker_total_failures counter",
            "# HELP circuit_breaker_uptime_pct Başarı ve çalışabilirlik yüzdesi",
            "# TYPE circuit_breaker_uptime_pct gauge",
        ]

        state_map = {"CLOSED": 0, "HALF_OPEN": 1, "OPEN": 2}

        for snap in snapshots:
            safe_name = snap.name.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "")
            labels = f'name="{safe_name}"'
            state_val = state_map.get(snap.state, -1)

            lines.append(f"circuit_breaker_state{{{labels}}} {state_val}")
            lines.append(f"circuit_breaker_failures{{{labels}}} {snap.failure_count}")
            lines.append(f"circuit_breaker_requests{{{labels}}} {snap.total_requests}")
            lines.append(f"circuit_breaker_total_failures{{{labels}}} {snap.total_failures}")
            lines.append(f"circuit_breaker_uptime_pct{{{labels}}} {snap.uptime_percentage:.2f}")

        return "\n".join(lines) + "\n"

    def export_json(self) -> dict[str, Any]:
        """Tüm metrikleri ve sistem özetini sözlük yapısında döner.

        Returns:
            dict[str, Any]: JSON uyumlu metrik raporu.
        """
        snapshots = self.get_all_snapshots()

        total_count = len(snapshots)
        closed_count = sum(1 for s in snapshots if s.state == "CLOSED")
        open_count = sum(1 for s in snapshots if s.state == "OPEN")
        half_open_count = sum(1 for s in snapshots if s.state == "HALF_OPEN")

        return {
            "timestamp": datetime.now(UTC).isoformat(),
            "circuit_breakers": {s.name: s.to_dict() for s in snapshots},
            "summary": {
                "total": total_count,
                "closed": closed_count,
                "open": open_count,
                "half_open": half_open_count,
                "healthy_ratio": round(closed_count / total_count, 3) if total_count > 0 else 1.0,
            },
        }

    def export_orjson_bytes(self) -> bytes:
        """Tüm metrikleri orjson ile yüksek hızlı ikili JSON bayt dizisi olarak üretir.

        Returns:
            bytes: UTF-8 kodlanmış JSON verisi.
        """
        return orjson.dumps(self.export_json())

    def export_snapshots_to_polars(self) -> pl.DataFrame:
        """Tüm devre kesici anlık durumlarını Polars DataFrame olarak döndürür.

        Returns:
            pl.DataFrame: Devre kesici metrik tablosu.
        """
        snapshots = self.get_all_snapshots()
        if not snapshots:
            return pl.DataFrame(
                schema={
                    "name": pl.Utf8,
                    "state": pl.Utf8,
                    "failure_count": pl.Int64,
                    "success_count": pl.Int64,
                    "failure_threshold": pl.Int64,
                    "recovery_timeout_seconds": pl.Int64,
                    "last_failure": pl.Utf8,
                    "last_success": pl.Utf8,
                    "total_requests": pl.Int64,
                    "total_failures": pl.Int64,
                    "total_successes": pl.Int64,
                    "uptime_pct": pl.Float64,
                }
            )
        return pl.DataFrame([s.to_dict() for s in snapshots])

    @otel_trace("circuit_breaker_metrics.record_state_change")
    def record_state_change(self, name: str, old_state: str, new_state: str) -> None:
        """Devre kesicide meydana gelen bir durum geçişini tarihçeye kaydeder.

        Args:
            name: Devre kesici adı.
            old_state: Önceki durum ("CLOSED", "OPEN", "HALF_OPEN").
            new_state: Yeni durum.
        """
        entry: dict[str, Any] = {
            "timestamp": datetime.now(UTC).isoformat(),
            "name": name,
            "old_state": str(old_state),
            "new_state": str(new_state),
        }

        with self._lock:
            self._history.append(entry)

        logger.info(
            "circuit_breaker_durumu_degisti",
            name=name,
            eski_durum=old_state,
            yeni_durum=new_state,
        )

    def get_history(self, limit: int = DEFAULT_HISTORY_LIMIT) -> list[dict[str, Any]]:
        """Son durum geçişi kayıtlarını döner.

        Args:
            limit: Döndürülecek maksimum kayıt sayısı.

        Returns:
            list[dict[str, Any]]: Kronolojik durum değişikliği listesi.
        """
        safe_limit = max(1, min(limit, self._max_history))
        with self._lock:
            history_list = list(self._history)

        return history_list[-safe_limit:]

    def export_history_to_polars(self) -> pl.DataFrame:
        """Durum geçişi tarihçesini Polars DataFrame olarak döndürür.

        Returns:
            pl.DataFrame: Geçiş geçmişi tablosu.
        """
        with self._lock:
            records = list(self._history)

        if not records:
            return pl.DataFrame(
                schema={
                    "timestamp": pl.Utf8,
                    "name": pl.Utf8,
                    "old_state": pl.Utf8,
                    "new_state": pl.Utf8,
                }
            )
        return pl.DataFrame(records)

    def export_history_to_duckdb(self, db_path: str = DEFAULT_METRICS_HISTORY_DB_PATH) -> int:
        """Durum geçişi tarihçesini kalıcı DuckDB tablosuna kaydeder.

        Args:
            db_path: Hedef DuckDB dosya yolu.

        Returns:
            int: Kaydedilen olay adedi.
        """
        df = self.export_history_to_polars()
        if df.is_empty():
            return 0

        path_obj = Path(db_path)
        path_obj.parent.mkdir(parents=True, exist_ok=True)

        with duckdb.connect(str(path_obj)) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS circuit_breaker_history (
                    timestamp VARCHAR,
                    name VARCHAR,
                    old_state VARCHAR,
                    new_state VARCHAR
                )
                """
            )
            conn.register("tmp_cb_hist_df", df)
            conn.execute("INSERT INTO circuit_breaker_history SELECT * FROM tmp_cb_hist_df")
            total = len(df)

        logger.info("cb_history_duckdb_guncellendi", db_path=str(path_obj), adet=total)
        return total

    def auto_track_global_registry(self) -> int:
        """services.core.circuit_breaker registry'sindeki tüm sağlayıcıları otomatik izlemeye alır.

        Returns:
            int: Yeni izlemeye alınan sağlayıcı sayısı.
        """
        try:
            from services.core.circuit_breaker import _providers, _registry_lock

            with _registry_lock:
                providers_copy = list(_providers.values())

            added = 0
            for prov in providers_copy:
                if prov.name not in self._tracked_breakers:
                    self.track(prov)
                    added += 1
            return added
        except Exception as exc:
            logger.debug("auto_track_global_registry_atlandi", error=str(exc))
            return 0

    async def export_prometheus_async(self) -> str:
        """Prometheus metriklerini event loop'u bloke etmeden asenkron üretir."""
        return await asyncio.to_thread(self.export_prometheus)

    async def export_json_async(self) -> dict[str, Any]:
        """JSON metriklerini event loop'u bloke etmeden asenkron üretir."""
        return await asyncio.to_thread(self.export_json)

    def persist_history_to_duckdb(self) -> int:
        """Bellekteki durum değişikliği geçmişini DuckDB state_store bileşenine kaydeder.

        Returns:
            int: Kaydedilen olay sayısı.
        """
        try:
            from services.core.state_store import state_store

            with self._lock:
                events = list(self._history)

            if not events:
                return 0

            for ev in events:
                state_store.save_circuit_state(
                    name=ev["name"],
                    state=ev["new_state"],
                    failure_count=0,
                    last_failure=ev.get("timestamp"),
                )
            return len(events)
        except Exception as exc:
            logger.debug("persist_history_to_duckdb_atlandi", error=str(exc))
            return 0

    def clear(self) -> None:
        """Kayıtlı devre kesicileri ve durum tarihçesini temizler (Testler ve sıfırlama için)."""
        with self._lock:
            self._tracked_breakers.clear()
            self._history.clear()

    def __repr__(self) -> str:
        """Toplayıcının okunabilir dize temsilini döner."""
        with self._lock:
            count = len(self._tracked_breakers)
            history_len = len(self._history)
        return (
            f"CircuitBreakerMetricsCollector(tracked_breakers={count}, "
            f"history_events={history_len}/{self._max_history})"
        )


# Global Singleton Örneği
circuit_breaker_metrics: Final[CircuitBreakerMetricsCollector] = CircuitBreakerMetricsCollector()


# Modül Seviyesinde Kolaylık Fonksiyonları (Convenience APIs)
def get_circuit_breaker_snapshots() -> list[CircuitBreakerSnapshot]:
    """Tüm devre kesici snapshot'larını döner."""
    return circuit_breaker_metrics.get_all_snapshots()


def export_circuit_breaker_prometheus() -> str:
    """Prometheus metriklerini döner."""
    return circuit_breaker_metrics.export_prometheus()


def export_circuit_breaker_json() -> dict[str, Any]:
    """JSON metrik özetini döner."""
    return circuit_breaker_metrics.export_json()


def export_circuit_breaker_snapshots_to_polars() -> pl.DataFrame:
    """Tüm devre kesici metriklerini Polars DataFrame olarak döner."""
    return circuit_breaker_metrics.export_snapshots_to_polars()


def export_circuit_breaker_history_to_polars() -> pl.DataFrame:
    """Durum geçiş geçmişini Polars DataFrame olarak döner."""
    return circuit_breaker_metrics.export_history_to_polars()


def export_circuit_breaker_history_to_duckdb(
    db_path: str = DEFAULT_METRICS_HISTORY_DB_PATH,
) -> int:
    """Durum geçiş geçmişini DuckDB tablosuna kaydeder."""
    return circuit_breaker_metrics.export_history_to_duckdb(db_path)


def track_circuit_breaker(breaker: Any) -> None:
    """Bir devre kesiciyi izlemeye alır."""
    circuit_breaker_metrics.track(breaker)


def untrack_circuit_breaker(name: str) -> None:
    """Devre kesiciyi izlemeden çıkarır."""
    circuit_breaker_metrics.untrack(name)


def record_circuit_breaker_state_change(name: str, old_state: str, new_state: str) -> None:
    """Durum geçişi kaydeder."""
    circuit_breaker_metrics.record_state_change(name, old_state, new_state)


__all__ = [
    "DEFAULT_HISTORY_LIMIT",
    "DEFAULT_MAX_HISTORY",
    "DEFAULT_METRICS_HISTORY_DB_PATH",
    "CircuitBreakerMetricsCollector",
    "CircuitBreakerSnapshot",
    "circuit_breaker_metrics",
    "export_circuit_breaker_history_to_duckdb",
    "export_circuit_breaker_history_to_polars",
    "export_circuit_breaker_json",
    "export_circuit_breaker_prometheus",
    "export_circuit_breaker_snapshots_to_polars",
    "get_circuit_breaker_snapshots",
    "record_circuit_breaker_state_change",
    "track_circuit_breaker",
    "untrack_circuit_breaker",
]
