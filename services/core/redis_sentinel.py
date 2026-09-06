"""ALPHA BIST — Redis Sentinel İstemcisi ve Yüksek Erişilebilirlik Motoru (HA Redis).

Redis Sentinel desteği:
- Otomatik master tespiti ve kesintisiz failover (Master-Slave geçişi)
- Sentinel yoksa doğrudan tekil Redis URL bağlantısı (Geriye dönük tam uyumluluk)
- Asenkron eşzamanlılık güvenliği (asyncio.Lock & Event Loop senkronizasyonu)
- DuckDB üzerinde failover denetim günlüğü (Failover Audit Trail)
- Polars entegrasyonu ve orjson desteği
"""

from __future__ import annotations

import asyncio
import os
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Final

import polars as pl
import structlog

if TYPE_CHECKING:
    import duckdb

try:
    import redis.asyncio as aioredis
    from redis.asyncio.sentinel import Sentinel

    HAS_REDIS = True
except ImportError:
    HAS_REDIS = False
    aioredis = None
    Sentinel = None

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

DEFAULT_MASTER_NAME: Final[str] = "alpha-master"
DEFAULT_SENTINEL_PORT: Final[int] = 26379
DEFAULT_SOCKET_TIMEOUT: Final[float] = 1.0
DEFAULT_SENTINEL_TIMEOUT: Final[float] = 0.5
DEFAULT_MAX_CONNECTIONS: Final[int] = 500

_ha_redis: Any | None = None
_ha_loop: asyncio.AbstractEventLoop | None = None
_ha_lock: asyncio.Lock | None = None
_duckdb_conn: duckdb.DuckDBPyConnection | None = None


def set_duckdb_connection(conn: duckdb.DuckDBPyConnection) -> None:
    """Sentinel failover denetim tablosunu DuckDB üzerinde ilklendirir."""
    global _duckdb_conn
    _duckdb_conn = conn
    try:
        _duckdb_conn.execute("""
            CREATE TABLE IF NOT EXISTS sentinel_failover_history (
                id BIGINT,
                master_name VARCHAR,
                event_type VARCHAR,
                detail_json VARCHAR,
                occurred_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE SEQUENCE IF NOT EXISTS seq_sentinel_failovers START 1;
        """)
    except Exception as exc:
        logger.error("Sentinel DuckDB şema oluşturma hatası", hata=str(exc))


def _record_failover_event(master_name: str, event_type: str, detail: str = "") -> None:
    """Failover ve master değişim olayını DuckDB'ye kaydeder."""
    if _duckdb_conn is None:
        return
    try:
        _duckdb_conn.execute(
            """
            INSERT INTO sentinel_failover_history (id, master_name, event_type, detail_json, occurred_at)
            VALUES (nextval('seq_sentinel_failovers'), ?, ?, ?, CURRENT_TIMESTAMP)
            """,
            [master_name, event_type, detail],
        )
    except Exception as exc:
        logger.debug("Sentinel failover kaydı hatası", hata=str(exc))


def _get_ha_lock() -> asyncio.Lock:
    """Geçerli event loop için asenkron kilit döndürür."""
    global _ha_lock
    if _ha_lock is None:
        _ha_lock = asyncio.Lock()
    return _ha_lock


def get_sentinel_hosts() -> list[tuple[str, int]]:
    """Ortam değişkeninden Sentinel host ve port adreslerini ayrıştırır."""
    raw = os.environ.get("REDIS_SENTINEL_HOSTS", "").strip()
    if not raw:
        return []
    hosts: list[tuple[str, int]] = []
    for entry in raw.split(","):
        entry = entry.strip()
        if not entry:
            continue
        if ":" in entry:
            host, port_str = entry.rsplit(":", 1)
            try:
                hosts.append((host.strip(), int(port_str.strip())))
            except ValueError:
                hosts.append((host.strip(), DEFAULT_SENTINEL_PORT))
        else:
            hosts.append((entry, DEFAULT_SENTINEL_PORT))
    return hosts


def get_sentinel_master() -> str:
    """Sentinel master servis adını döndürür."""
    return os.environ.get("REDIS_SENTINEL_MASTER", DEFAULT_MASTER_NAME).strip()


def get_redis_password() -> str:
    """Redis bağlantı parolasını döndürür."""
    return os.environ.get("REDIS_PASSWORD", "").strip()


@otel_trace("redis_sentinel.get_ha_redis")
async def get_ha_redis() -> Any:
    """Yüksek Erişilebilirlik (HA) Redis istemcisi döndürür.

    Öncelik Sırası:
    1. Sentinel yapılandırılmışsa -> Sentinel üzerinden güncel master node'a bağlanır.
    2. Sentinel yoksa veya erişilemezse -> Standart Redis URL ile doğrudan bağlanır.
    """
    global _ha_redis, _ha_loop

    try:
        current_loop = asyncio.get_running_loop()
    except RuntimeError:
        current_loop = None

    lock = _get_ha_lock()
    async with lock:
        # Mevcut istemci geçerli ve aynı loop içindeyse
        if _ha_redis is not None and _ha_loop is current_loop:
            try:
                # Canlılık kontrolü
                await _ha_redis.ping()
                return _ha_redis
            except Exception as exc:
                logger.warn("Mevcut HA Redis bağlantısı koptu, yeniden bağlanılıyor", hata=str(exc))
                _record_failover_event(get_sentinel_master(), "DISCONNECTED", str(exc))
                _ha_redis = None

        sentinel_hosts = get_sentinel_hosts()
        password = get_redis_password()
        master_name = get_sentinel_master()

        # 1. Sentinel Modu
        if sentinel_hosts and HAS_REDIS and Sentinel is not None:
            try:
                sentinel = Sentinel(
                    sentinel_hosts,
                    socket_timeout=DEFAULT_SENTINEL_TIMEOUT,
                    socket_connect_timeout=DEFAULT_SENTINEL_TIMEOUT,
                )
                master = sentinel.master_for(
                    master_name,
                    socket_timeout=DEFAULT_SOCKET_TIMEOUT,
                    socket_connect_timeout=DEFAULT_SOCKET_TIMEOUT,
                    password=password or None,
                    decode_responses=True,
                )
                await master.ping()
                _ha_redis = master
                _ha_loop = current_loop
                _record_failover_event(master_name, "CONNECTED_SENTINEL", f"hosts={len(sentinel_hosts)}")
                logger.info(
                    "Redis Sentinel bağlantısı başarıyla kuruldu",
                    master=master_name,
                    sentinel_sayisi=len(sentinel_hosts),
                )
                return _ha_redis
            except Exception as exc:
                logger.warn("Redis Sentinel bağlantısı başarısız, doğrudan moda geçiliyor", hata=str(exc))
                _record_failover_event(master_name, "SENTINEL_FALLBACK", str(exc))

        # 2. Doğrudan Redis Bağlantısı (Fallback)
        try:
            from services.core.config import settings

            redis_url = getattr(settings, "redis_url", "redis://localhost:6379/0")
            redis_host = getattr(settings, "redis_host", "localhost")

            if HAS_REDIS and aioredis is not None:
                client = aioredis.from_url(
                    redis_url,
                    decode_responses=True,
                    max_connections=DEFAULT_MAX_CONNECTIONS,
                )
                await client.ping()
                _ha_redis = client
                _ha_loop = current_loop
                _record_failover_event(master_name, "CONNECTED_DIRECT", f"url={redis_url}")
                logger.info("Doğrudan Redis bağlantısı kuruldu", host=redis_host)
                return _ha_redis
            else:
                msg = "redis.asyncio paketi kurulu değil"
                raise RuntimeError(msg)
        except Exception as exc:
            logger.error("Tüm Redis bağlantı denemeleri başarısız oldu", hata=str(exc))
            _record_failover_event(master_name, "ALL_FAILED", str(exc))
            raise


@otel_trace("redis_sentinel.close_ha_redis")
async def close_ha_redis() -> None:
    """HA Redis istemci bağlantısını güvenli ve kontrollü şekilde kapatır."""
    global _ha_redis, _ha_loop
    lock = _get_ha_lock()
    async with lock:
        if _ha_redis is not None:
            try:
                if hasattr(_ha_redis, "aclose"):
                    await _ha_redis.aclose()
                elif hasattr(_ha_redis, "close"):
                    await _ha_redis.close()
                _record_failover_event(get_sentinel_master(), "CLOSED", "Manual close")
            except Exception as exc:
                logger.warn("HA Redis kapatılırken hata oluştu", hata=str(exc))
            finally:
                _ha_redis = None
                _ha_loop = None
                logger.info("HA Redis bağlantısı başarıyla kapatıldı")


def export_sentinel_status_to_polars() -> pl.DataFrame:
    """Sentinel konfigürasyonunu ve bağlantı durumunu Polars DataFrame olarak dışa aktarır."""
    hosts = get_sentinel_hosts()
    master = get_sentinel_master()
    is_connected = _ha_redis is not None

    if not hosts:
        records = [
            {
                "mode": "DIRECT",
                "sentinel_host": "none",
                "sentinel_port": 0,
                "master_name": master,
                "is_connected": is_connected,
                "checked_at": datetime.now(UTC),
            }
        ]
    else:
        records = [
            {
                "mode": "SENTINEL",
                "sentinel_host": h[0],
                "sentinel_port": h[1],
                "master_name": master,
                "is_connected": is_connected,
                "checked_at": datetime.now(UTC),
            }
            for h in hosts
        ]

    return pl.DataFrame(records)


__all__ = [
    "DEFAULT_MASTER_NAME",
    "DEFAULT_MAX_CONNECTIONS",
    "DEFAULT_SENTINEL_PORT",
    "DEFAULT_SENTINEL_TIMEOUT",
    "DEFAULT_SOCKET_TIMEOUT",
    "HAS_REDIS",
    "close_ha_redis",
    "export_sentinel_status_to_polars",
    "get_ha_redis",
    "get_redis_password",
    "get_sentinel_hosts",
    "get_sentinel_master",
    "set_duckdb_connection",
]
