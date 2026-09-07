"""ALPHA BIST — İnternet Bağlantı ve Ağ Sağlığı İzleyici v3.0 (Enterprise Connectivity Monitor)

Bu modül, dış veri kaynaklarına (BIST, KAP, TCMB, Yahoo Finance, Cloudflare)
olan internet bağlantısının sürekliliğini, gecikmesini ve kesinti durumlarını
asenkron olarak izler. Bağlantı kesintilerinde exponential backoff ve olay
günlüğü (incident logging) mekanizmalarını işletir.

Özellikler:
- Çoklu ve yedekli endpoint kontrolü (tek nokta arızasını önleme).
- Durum makinesi: `ONLINE`, `DEGRADED`, `OFFLINE`.
- Asenkron olay dinleyicileri (Callbacks): `on_offline`, `on_online`, `on_degraded`.
- Thread-safe durum yönetimi (`threading.RLock`) ve asenkron oturum kilidi (`asyncio.Lock`).
- OpenTelemetry metrik ve span entegrasyonu (`alpha.connectivity.offline.*`).
- Polars ve DuckDB ile kesinti geçmişi ve analitik raporlama.
"""

from __future__ import annotations

import asyncio
import contextlib
import threading
import time
from collections import deque
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

import aiohttp
import duckdb
import orjson
import polars as pl
import structlog
from opentelemetry import metrics, trace

logger = structlog.get_logger(__name__)
tracer = trace.get_tracer("alpha-bist.connectivity")
meter = metrics.get_meter("alpha-bist.connectivity")

# OpenTelemetry Metrikleri
_offline_counter = meter.create_counter(
    "alpha.connectivity.offline.total",
    description="Toplam bağlantı kesintisi sayısı",
)
_offline_duration_histogram = meter.create_histogram(
    "alpha.connectivity.offline.duration_seconds",
    description="Kesinti süreleri dağılımı",
    unit="s",
)

# Yapılandırma Sabitleri
DEFAULT_CHECK_INTERVAL_SECONDS: float = 60.0  # SSD koruma periyodu: 60 saniye
DEFAULT_TIMEOUT_SECONDS: float = 5.0
DEFAULT_FAILURE_THRESHOLD: int = 3
DEFAULT_RECOVERY_THRESHOLD: int = 1
DEFAULT_MAX_EVENT_LOG: int = 500
DEFAULT_DUCKDB_PATH: Path = Path("data/connectivity.duckdb")

# Yüksek erişilebilirlikli izleme endpoint'leri
DEFAULT_CHECK_ENDPOINTS: list[str] = [
    "https://www.google.com",
    "https://1.1.1.1",
    "https://finance.yahoo.com",
    "https://query1.finance.yahoo.com",
    "https://www.tcmb.gov.tr",
]


class ConnectivityState(StrEnum):
    """Bağlantı durum kodları.

    Hem büyük hem küçük harf uyumluluğu için StrEnum kullanılır.
    """

    ONLINE = "ONLINE"
    DEGRADED = "DEGRADED"  # Bazı endpoint'ler erişilemez, kısmi bağlantı
    OFFLINE = "OFFLINE"

    def __repr__(self) -> str:
        return f"<ConnectivityState.{self.name}: '{self.value}'>"


@dataclass(slots=True)
class ConnectivityEvent:
    """Bağlantı durumu değişiklik olayı veri modeli.

    Attributes:
        timestamp: Olay zaman damgası (Unix zamanı).
        event_type: Olay tipi ('connected', 'disconnected', 'degraded').
        duration_seconds: Kesinti veya durum süresi (saniye).
        details: Olay hakkında ek açıklama.
    """

    timestamp: float
    event_type: str
    duration_seconds: float = 0.0
    details: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Olayı sözlük formatına dönüştürür."""
        return {
            "timestamp": self.timestamp,
            "timestamp_iso": datetime.fromtimestamp(self.timestamp, tz=UTC).isoformat(),
            "event_type": self.event_type,
            "duration_seconds": round(self.duration_seconds, 2),
            "details": self.details,
        }

    def to_orjson_bytes(self) -> bytes:
        """Olayı orjson bayt dizisine serileştirir."""
        return orjson.dumps(self.to_dict(), default=str)

    def to_json(self) -> str:
        """Olayı JSON metnine dönüştürür."""
        return self.to_orjson_bytes().decode("utf-8")

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ConnectivityEvent:
        """Sözlükten ConnectivityEvent nesnesi oluşturur."""
        return cls(
            timestamp=float(data.get("timestamp", time.time())),
            event_type=str(data.get("event_type", "unknown")),
            duration_seconds=float(data.get("duration_seconds", 0.0)),
            details=str(data.get("details", "")),
        )

    def __repr__(self) -> str:
        return (
            f"<ConnectivityEvent type='{self.event_type}' "
            f"duration={self.duration_seconds:.1f}s ts={self.timestamp:.0f}>"
        )


class ConnectivityMonitor:
    """İnternet bağlantısını periyodik olarak kontrol eden kurumsal izleme servisi."""

    def __init__(
        self,
        check_interval_seconds: float = DEFAULT_CHECK_INTERVAL_SECONDS,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        failure_threshold: int = DEFAULT_FAILURE_THRESHOLD,
        recovery_threshold: int = DEFAULT_RECOVERY_THRESHOLD,
        endpoints: list[str] | None = None,
    ) -> None:
        """ConnectivityMonitor örneğini başlatır.

        Args:
            check_interval_seconds: Kontrol döngü periyodu (saniye).
            timeout_seconds: HTTP istek zaman aşımı (saniye).
            failure_threshold: Kesinti (OFFLINE) ilan edilmesi için gereken ardışık hata sayısı.
            recovery_threshold: Çevrimiçi (ONLINE) sayılması için başarılı endpoint eşiği.
            endpoints: Yoklanacak HTTP URL listesi.
        """
        self._check_interval: float = max(5.0, float(check_interval_seconds))
        self._timeout: float = max(1.0, float(timeout_seconds))
        self._failure_threshold: int = max(1, int(failure_threshold))
        self._recovery_threshold: int = max(1, int(recovery_threshold))
        self.CHECK_ENDPOINTS: list[str] = endpoints or list(DEFAULT_CHECK_ENDPOINTS)

        self._state: ConnectivityState = ConnectivityState.ONLINE
        self._consecutive_failures: int = 0
        self._consecutive_successes: int = 0
        self._last_check_time: float = 0.0
        self._last_online_time: float = time.time()
        self._offline_since: float | None = None
        self._total_offline_seconds: float = 0.0

        self._event_log: deque[ConnectivityEvent] = deque(maxlen=DEFAULT_MAX_EVENT_LOG)
        self._max_event_log: int = DEFAULT_MAX_EVENT_LOG

        # Geri Çağırma (Callback) Listeleri
        self._on_offline: list[Callable[[], Awaitable[None]]] = []
        self._on_online: list[Callable[[float], Awaitable[None]]] = []
        self._on_degraded: list[Callable[[], Awaitable[None]]] = []

        # Oturum ve Eşzamanlılık Kilitleri
        self._session: aiohttp.ClientSession | None = None
        self._session_lock: asyncio.Lock = asyncio.Lock()
        self._state_lock: threading.RLock = threading.RLock()

        self._monitor_task: asyncio.Task[None] | None = None
        self._running: bool = False

    @property
    def is_online(self) -> bool:
        """Sistemin çevrimiçi (ONLINE) olup olmadığını döndürür."""
        with self._state_lock:
            return self._state == ConnectivityState.ONLINE

    @property
    def is_offline(self) -> bool:
        """Sistemin çevrimdışı (OFFLINE) olup olmadığını döndürür."""
        with self._state_lock:
            return self._state == ConnectivityState.OFFLINE

    @property
    def is_degraded(self) -> bool:
        """Sistemin kısmi kesinti (DEGRADED) durumunda olup olmadığını döndürür."""
        with self._state_lock:
            return self._state == ConnectivityState.DEGRADED

    @property
    def state(self) -> ConnectivityState:
        """Mevcut bağlantı durumunu döndürür."""
        with self._state_lock:
            return self._state

    @property
    def offline_since(self) -> float | None:
        """Kesintinin başladığı Unix zaman damgasını döndürür (çevrimiçi ise None)."""
        with self._state_lock:
            return self._offline_since

    @property
    def offline_duration_seconds(self) -> float:
        """Aktif kesinti süresini saniye cinsinden döndürür."""
        with self._state_lock:
            if self._offline_since is not None:
                return max(0.0, time.time() - self._offline_since)
            return 0.0

    @property
    def total_offline_seconds(self) -> float:
        """Platform başlangıcından bu yana toplam kesinti süresini döndürür."""
        with self._state_lock:
            total = self._total_offline_seconds
            if self._offline_since is not None:
                total += max(0.0, time.time() - self._offline_since)
            return total

    def on_offline(self, callback: Callable[[], Awaitable[None]]) -> None:
        """Bağlantı koptuğunda (OFFLINE) tetiklenecek asenkron callback kaydeder."""
        with self._state_lock:
            self._on_offline.append(callback)

    def on_online(self, callback: Callable[[float], Awaitable[None]]) -> None:
        """Bağlantı geri geldiğinde (ONLINE) kesinti süresi argümanıyla çağrılacak callback kaydeder."""
        with self._state_lock:
            self._on_online.append(callback)

    def on_degraded(self, callback: Callable[[], Awaitable[None]]) -> None:
        """Kısmi kesinti (DEGRADED) oluştuğunda çağrılacak callback kaydeder."""
        with self._state_lock:
            self._on_degraded.append(callback)

    async def start(self) -> None:
        """Arka plan bağlantı izleyicisini başlatır."""
        with self._state_lock:
            if self._running:
                return
            self._running = True

        loop = asyncio.get_running_loop()
        self._monitor_task = loop.create_task(self._monitor_loop())
        logger.info(
            "Connectivity monitor başlatıldı",
            check_interval=self._check_interval,
            failure_threshold=self._failure_threshold,
        )

    async def stop(self) -> None:
        """Arka plan izleyiciyi durdurur ve HTTP oturumunu kapatır."""
        with self._state_lock:
            self._running = False

        if self._monitor_task and not self._monitor_task.done():
            self._monitor_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._monitor_task
            self._monitor_task = None

        # aiohttp oturumunu temizle
        async with self._session_lock:
            if self._session and not self._session.closed:
                await self._session.close()
                self._session = None

        logger.info(
            "Connectivity monitor durduruldu",
            total_offline_seconds=round(self.total_offline_seconds, 1),
        )

    async def check_now(self) -> ConnectivityState:
        """Anlık bağlantı kontrolü yapar ve güncel durumu döner."""
        return await self._do_check()

    async def wait_for_online(self, timeout: float = 300.0, poll_interval: float = 5.0) -> bool:
        """Bağlantı tekrar kurulana (ONLINE) kadar asenkron bekler.

        Args:
            timeout: Maksimum bekleme süresi (saniye).
            poll_interval: Denetleme sıklığı (saniye).

        Returns:
            Süre dolmadan bağlantı kurulduysa True, zaman aşımına uğradıysa False.
        """
        start = time.time()
        while (time.time() - start) < timeout:
            if self.is_online:
                return True
            await asyncio.sleep(poll_interval)
        return False

    async def _monitor_loop(self) -> None:
        """Arka plan periyodik kontrol döngüsü."""
        while True:
            with self._state_lock:
                if not self._running:
                    break

            try:
                state = await self._do_check()

                # Duruma göre optimize edilmiş bekleme aralığı
                if state == ConnectivityState.OFFLINE:
                    wait = min(self._check_interval * 0.5, 30.0)  # Kesintide daha hızlı toparlanma kontrolü
                elif state == ConnectivityState.DEGRADED:
                    wait = min(self._check_interval * 0.5, 30.0)
                else:
                    wait = self._check_interval

                await asyncio.sleep(wait)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("connectivity_monitor_dongu_hatasi", error=str(e))
                await asyncio.sleep(self._check_interval)

    async def _do_check(self) -> ConnectivityState:
        """Paralel endpoint kontrolü gerçekleştirir ve durumu günceller."""
        now_time = time.time()
        total_endpoints = len(self.CHECK_ENDPOINTS)

        # Singleton aiohttp oturumu
        async with self._session_lock:
            if self._session is None or self._session.closed:
                timeout = aiohttp.ClientTimeout(total=self._timeout)
                self._session = aiohttp.ClientSession(timeout=timeout)

        # Paralel istekler
        try:
            tasks = [self._check_endpoint(self._session, url) for url in self.CHECK_ENDPOINTS]
            results = await asyncio.gather(*tasks, return_exceptions=True)
            successful = sum(1 for r in results if r is True)
        except Exception:
            successful = 0

        # Kilit altında durum güncellemesi
        callbacks_to_run: list[tuple[Callable[..., Awaitable[None]], tuple[Any, ...]]] = []
        with self._state_lock:
            self._last_check_time = now_time
            old_state = self._state

            if successful >= self._recovery_threshold:
                new_state = (
                    ConnectivityState.ONLINE
                    if successful == total_endpoints
                    else ConnectivityState.DEGRADED
                )
                self._consecutive_successes += 1
                self._consecutive_failures = 0

                if old_state == ConnectivityState.OFFLINE:
                    offline_duration = (
                        max(0.0, now_time - self._offline_since)
                        if self._offline_since is not None
                        else 0.0
                    )
                    self._total_offline_seconds += offline_duration
                    self._offline_since = None
                    self._last_online_time = now_time

                    _offline_duration_histogram.record(offline_duration)
                    self._log_event("connected", offline_duration, f"Başarılı endpoint: {successful}/{total_endpoints}")

                    with tracer.start_as_current_span("connectivity.online") as span:
                        span.set_attribute("offline_seconds", round(offline_duration, 1))
                        span.set_attribute("successful_endpoints", successful)

                    logger.info(
                        "Bağlantı geri geldi",
                        offline_seconds=round(offline_duration, 1),
                        successful_endpoints=successful,
                    )

                    for cb in self._on_online:
                        callbacks_to_run.append((cb, (offline_duration,)))

                elif new_state == ConnectivityState.DEGRADED and old_state != ConnectivityState.DEGRADED:
                    self._log_event("degraded", 0.0, f"Başarılı endpoint: {successful}/{total_endpoints}")
                    for cb in self._on_degraded:
                        callbacks_to_run.append((cb, ()))

                self._state = new_state

            else:
                self._consecutive_failures += 1
                self._consecutive_successes = 0

                if self._consecutive_failures >= self._failure_threshold:
                    if old_state != ConnectivityState.OFFLINE:
                        self._offline_since = now_time
                        self._state = ConnectivityState.OFFLINE
                        self._log_event("disconnected", 0.0, f"Ardışık hata: {self._consecutive_failures}")
                        _offline_counter.add(1)

                        with tracer.start_as_current_span("connectivity.offline") as span:
                            span.set_attribute("consecutive_failures", self._consecutive_failures)

                        logger.warning(
                            "Bağlantı kesildi",
                            consecutive_failures=self._consecutive_failures,
                        )

                        for cb in self._on_offline:
                            callbacks_to_run.append((cb, ()))

            current_state = self._state

        # Callback'leri kilit dışından asenkron çalıştır
        for cb, args in callbacks_to_run:
            try:
                await cb(*args)
            except Exception as exc:
                logger.error("connectivity_callback_hatasi", error=str(exc))

        return current_state

    async def _check_endpoint(self, session: aiohttp.ClientSession, url: str) -> bool:
        """Tek bir HTTP/HTTPS endpoint'ini yoklar."""
        try:
            async with session.get(url, allow_redirects=True) as resp:
                return resp.status < 500
        except Exception:
            return False

    def _log_event(self, event_type: str, duration: float = 0.0, details: str = "") -> None:
        """İç olay günlüğüne yeni bir kayıt yazar."""
        event = ConnectivityEvent(
            timestamp=time.time(),
            event_type=event_type,
            duration_seconds=duration,
            details=details,
        )
        self._event_log.append(event)

    def clear_event_log(self) -> None:
        """Olay günlüğünü thread-safe olarak temizler."""
        with self._state_lock:
            self._event_log.clear()

    def get_status(self) -> dict[str, Any]:
        """Mevcut bağlantı durumunu ve metriklerini sözlük olarak döndürür."""
        with self._state_lock:
            recent = [e.to_dict() for e in list(self._event_log)[-10:]]
            off_iso = (
                datetime.fromtimestamp(self._offline_since, tz=UTC).isoformat()
                if self._offline_since is not None
                else None
            )
            chk_iso = (
                datetime.fromtimestamp(self._last_check_time, tz=UTC).isoformat()
                if self._last_check_time > 0.0
                else None
            )

            return {
                "state": self._state.value,
                "is_online": self.is_online,
                "is_offline": self.is_offline,
                "is_degraded": self.is_degraded,
                "offline_since": off_iso,
                "offline_duration_seconds": round(self.offline_duration_seconds, 1),
                "total_offline_seconds": round(self.total_offline_seconds, 1),
                "consecutive_failures": self._consecutive_failures,
                "consecutive_successes": self._consecutive_successes,
                "last_check": chk_iso,
                "recent_events": recent,
            }

    def get_offline_report(self) -> dict[str, Any]:
        """Toplam kesinti sürelerini özetleyen analitik raporu döndürür."""
        with self._state_lock:
            total_sec = self.total_offline_seconds
            disconn_count = sum(1 for e in self._event_log if e.event_type == "disconnected")
            return {
                "total_offline_seconds": round(total_sec, 1),
                "total_offline_minutes": round(total_sec / 60.0, 1),
                "total_offline_hours": round(total_sec / 3600.0, 2),
                "current_offline": self.is_offline,
                "current_offline_seconds": round(self.offline_duration_seconds, 1),
                "disconnect_incident_count": disconn_count,
            }

    def export_events_to_polars(self) -> pl.DataFrame:
        """Olay günlüğünü Polars DataFrame olarak dışa aktarır."""
        with self._state_lock:
            items = [e.to_dict() for e in self._event_log]

        schema = {
            "timestamp": pl.Float64,
            "timestamp_iso": pl.Utf8,
            "event_type": pl.Utf8,
            "duration_seconds": pl.Float64,
            "details": pl.Utf8,
        }
        if not items:
            return pl.DataFrame(schema=schema)

        return pl.DataFrame(items, schema=schema)

    def export_events_to_duckdb(
        self,
        db_path: str | Path = DEFAULT_DUCKDB_PATH,
        table_name: str = "bist_connectivity_events",
    ) -> int:
        """Olay günlüğünü DuckDB tablosuna kaydeder.

        Args:
            db_path: DuckDB veritabanı dosya yolu.
            table_name: Hedef tablo adı.

        Returns:
            Kaydedilen olay sayısı.
        """
        df = self.export_events_to_polars()
        if df.is_empty():
            return 0

        path_obj = Path(db_path)
        path_obj.parent.mkdir(parents=True, exist_ok=True)
        if path_obj.exists() and path_obj.stat().st_size == 0:
            with contextlib.suppress(OSError):
                path_obj.unlink()

        try:
            with duckdb.connect(str(path_obj)) as conn:
                try:
                    from services.core.debounce import configure_duckdb_wal

                    configure_duckdb_wal(conn)
                except Exception:
                    with contextlib.suppress(Exception):
                        conn.execute("PRAGMA wal_autocheckpoint='10MB';")

                conn.register("df_conn_events", df.to_arrow())
                conn.execute(
                    f"CREATE TABLE IF NOT EXISTS {table_name} AS SELECT * FROM df_conn_events WHERE 1=0"
                )
                conn.execute(f"INSERT INTO {table_name} SELECT * FROM df_conn_events")
                with contextlib.suppress(Exception):
                    conn.execute(f"CREATE INDEX IF NOT EXISTS idx_{table_name}_ts ON {table_name} (timestamp)")
            return len(df)
        except Exception as e:
            logger.error("export_connectivity_to_duckdb_failed", error=str(e))
            return 0

    def query_events_duckdb(
        self,
        db_path: str | Path = DEFAULT_DUCKDB_PATH,
        table_name: str = "bist_connectivity_events",
        limit: int = 100,
    ) -> pl.DataFrame:
        """DuckDB üzerinden geçmiş bağlantı olaylarını sorgular.

        Args:
            db_path: DuckDB dosya yolu.
            table_name: Tablo adı.
            limit: Maksimum satır sayısı.

        Returns:
            Polars DataFrame.
        """
        schema = {
            "timestamp": pl.Float64,
            "timestamp_iso": pl.Utf8,
            "event_type": pl.Utf8,
            "duration_seconds": pl.Float64,
            "details": pl.Utf8,
        }
        empty_df = pl.DataFrame(schema=schema)
        path_obj = Path(db_path)
        if not path_obj.exists() or path_obj.stat().st_size == 0:
            return empty_df

        try:
            with duckdb.connect(str(path_obj), read_only=True) as conn:
                tables = conn.execute(
                    "SELECT table_name FROM information_schema.tables WHERE table_name = ?",
                    [table_name],
                ).fetchall()
                if not tables:
                    return empty_df

                query = f"SELECT * FROM {table_name} ORDER BY timestamp DESC LIMIT ?"
                arrow_res = conn.execute(query, [limit]).arrow()
                return pl.from_arrow(arrow_res)
        except Exception as e:
            logger.error("query_connectivity_duckdb_failed", error=str(e))
            return empty_df

    def __repr__(self) -> str:
        with self._state_lock:
            return (
                f"<ConnectivityMonitor state='{self._state.value}' "
                f"failures={self._consecutive_failures} events={len(self._event_log)}>"
            )


# Modül seviyesi tekil servis örneği
connectivity_monitor: ConnectivityMonitor = ConnectivityMonitor()


def is_online() -> bool:
    """Sistemin çevrimiçi olup olmadığını bildirir."""
    return connectivity_monitor.is_online


def is_offline() -> bool:
    """Sistemin çevrimdışı olup olmadığını bildirir."""
    return connectivity_monitor.is_offline


def export_connectivity_events_to_polars() -> pl.DataFrame:
    """Bağlantı olaylarını Polars DataFrame olarak döndürür."""
    return connectivity_monitor.export_events_to_polars()


def export_connectivity_events_to_duckdb(
    db_path: str | Path = DEFAULT_DUCKDB_PATH,
    table_name: str = "bist_connectivity_events",
) -> int:
    """Bağlantı olaylarını DuckDB tablosuna kaydeder."""
    return connectivity_monitor.export_events_to_duckdb(db_path=db_path, table_name=table_name)


def query_connectivity_events_duckdb(
    db_path: str | Path = DEFAULT_DUCKDB_PATH,
    table_name: str = "bist_connectivity_events",
    limit: int = 100,
) -> pl.DataFrame:
    """DuckDB üzerinden geçmiş bağlantı olaylarını sorgular."""
    return connectivity_monitor.query_events_duckdb(db_path=db_path, table_name=table_name, limit=limit)


__all__ = [
    "DEFAULT_CHECK_INTERVAL_SECONDS",
    "DEFAULT_TIMEOUT_SECONDS",
    "DEFAULT_FAILURE_THRESHOLD",
    "DEFAULT_RECOVERY_THRESHOLD",
    "DEFAULT_MAX_EVENT_LOG",
    "DEFAULT_DUCKDB_PATH",
    "DEFAULT_CHECK_ENDPOINTS",
    "ConnectivityState",
    "ConnectivityEvent",
    "ConnectivityMonitor",
    "connectivity_monitor",
    "is_online",
    "is_offline",
    "export_connectivity_events_to_polars",
    "export_connectivity_events_to_duckdb",
    "query_connectivity_events_duckdb",
]
