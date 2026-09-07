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
from pathlib import Path
from typing import Any, Final

import duckdb
import orjson
import polars as pl
import structlog

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
DEFAULT_SENTINEL_DUCKDB_PATH: Final[str] = "data/sentinel_failovers.duckdb"
DEFAULT_CHECKPOINT_SIZE: Final[str] = "4MB"
DEFAULT_WAL_SIZE: Final[str] = "2MB"

_ha_redis: Any | None = None
_ha_loop: asyncio.AbstractEventLoop | None = None
_ha_lock: asyncio.Lock | None = None
_duckdb_conn: duckdb.DuckDBPyConnection | None = None


def configure_duckdb_wal(
    conn: duckdb.DuckDBPyConnection,
    checkpoint_threshold: str = DEFAULT_CHECKPOINT_SIZE,
    wal_autocheckpoint: str = DEFAULT_WAL_SIZE,
) -> None:
    """DuckDB WAL parametrelerini optimize eder."""
    try:
        conn.execute(f"SET checkpoint_threshold = '{checkpoint_threshold}';")
        conn.execute(f"SET wal_autocheckpoint = '{wal_autocheckpoint}';")
    except Exception as e:
        logger.warning("sentinel_duckdb_wal_yapilandirma_uyarisi", hata=str(e))


def set_duckdb_connection(conn: duckdb.DuckDBPyConnection) -> None:
    """Sentinel failover denetim tablosunu DuckDB üzerinde ilklendirir."""
    global _duckdb_conn
    _duckdb_conn = conn
    configure_duckdb_wal(_duckdb_conn)
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


def _get_active_duckdb(writable: bool = False) -> tuple[duckdb.DuckDBPyConnection | None, bool]:
    """Aktif DuckDB bağlantısını ve bağlantının kapatılması gerekip gerekmediğini döndürür."""
    if _duckdb_conn is not None:
        return _duckdb_conn, False

    p = Path(DEFAULT_SENTINEL_DUCKDB_PATH)
    if not writable and not p.exists():
        return None, False

    try:
        if writable:
            p.parent.mkdir(parents=True, exist_ok=True)
            conn = duckdb.connect(str(p))
            configure_duckdb_wal(conn)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS sentinel_failover_history (
                    id BIGINT,
                    master_name VARCHAR,
                    event_type VARCHAR,
                    detail_json VARCHAR,
                    occurred_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
                CREATE SEQUENCE IF NOT EXISTS seq_sentinel_failovers START 1;
            """)
            return conn, True
        else:
            conn = duckdb.connect(str(p), read_only=True)
            tables = [r[0] for r in conn.execute("SHOW TABLES").fetchall()]
            if "sentinel_failover_history" not in tables:
                conn.close()
                return None, False
            return conn, True
    except Exception as exc:
        logger.debug("sentinel_duckdb_baglanti_hatasi", hata=str(exc))
        return None, False


def _record_failover_event(master_name: str, event_type: str, detail: str = "") -> None:
    """Failover ve master değişim olayını DuckDB'ye kaydeder."""
    conn, should_close = _get_active_duckdb(writable=True)
    if conn is None:
        return
    try:
        conn.execute(
            """
            INSERT INTO sentinel_failover_history (id, master_name, event_type, detail_json, occurred_at)
            VALUES (nextval('seq_sentinel_failovers'), ?, ?, ?, CURRENT_TIMESTAMP)
            """,
            [master_name, event_type, detail],
        )
    except Exception as exc:
        logger.debug("Sentinel failover kaydı hatası", hata=str(exc))
    finally:
        if should_close:
            conn.close()


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
                logger.warning("Mevcut HA Redis bağlantısı koptu, yeniden bağlanılıyor", hata=str(exc))
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
                logger.warning("Redis Sentinel bağlantısı başarısız, doğrudan moda geçiliyor", hata=str(exc))
                _record_failover_event(master_name, "SENTINEL_FALLBACK", str(exc))

        # 2. Doğrudan Redis Bağlantısı (Fallback)
        try:
            from services.core.config import settings

            redis_url = getattr(settings, "redis_url", "redis://127.0.0.1:6379/0")
            redis_host = getattr(settings, "redis_host", "127.0.0.1")

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
                logger.warning("HA Redis kapatılırken hata oluştu", hata=str(exc))
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


def read_sentinel_failovers_from_duckdb(
    db_path: str = DEFAULT_SENTINEL_DUCKDB_PATH,
    limit: int = 100,
) -> pl.DataFrame:
    """DuckDB üzerindeki failover denetim geçmişini Polars DataFrame olarak okur."""
    empty_schema = {
        "id": pl.Int64,
        "master_name": pl.String,
        "event_type": pl.String,
        "detail_json": pl.String,
        "occurred_at": pl.Datetime,
    }
    if _duckdb_conn is not None:
        try:
            return _duckdb_conn.execute(
                "SELECT * FROM sentinel_failover_history ORDER BY id DESC LIMIT ?",
                [limit],
            ).pl()
        except Exception as e:
            logger.error("read_sentinel_failovers_conn_hatasi", hata=str(e))
            return pl.DataFrame(schema=empty_schema)

    p = Path(db_path)
    if not p.exists():
        return pl.DataFrame(schema=empty_schema)

    try:
        conn = duckdb.connect(str(p), read_only=True)
        tables = [r[0] for r in conn.execute("SHOW TABLES").fetchall()]
        if "sentinel_failover_history" not in tables:
            conn.close()
            return pl.DataFrame(schema=empty_schema)
        df = conn.execute(
            "SELECT * FROM sentinel_failover_history ORDER BY id DESC LIMIT ?",
            [limit],
        ).pl()
        conn.close()
        return df
    except Exception as e:
        logger.error("read_sentinel_failovers_file_hatasi", hata=str(e))
        return pl.DataFrame(schema=empty_schema)


def clear_sentinel_failovers_duckdb(db_path: str = DEFAULT_SENTINEL_DUCKDB_PATH) -> bool:
    """DuckDB üzerindeki failover geçmiş tablosunu temizler."""
    if _duckdb_conn is not None:
        try:
            _duckdb_conn.execute("DELETE FROM sentinel_failover_history")
            return True
        except Exception as e:
            logger.error("clear_sentinel_failovers_conn_hatasi", hata=str(e))
            return False

    p = Path(db_path)
    if not p.exists():
        return True
    try:
        conn = duckdb.connect(str(p))
        tables = [r[0] for r in conn.execute("SHOW TABLES").fetchall()]
        if "sentinel_failover_history" in tables:
            conn.execute("DELETE FROM sentinel_failover_history")
        conn.close()
        return True
    except Exception as e:
        logger.error("clear_sentinel_failovers_file_hatasi", hata=str(e))
        return False


def to_orjson_bytes(data: Any) -> bytes:
    """Veriyi orjson ile güvenli bayt dizisine serileştirir."""
    return orjson.dumps(data, default=str)


def get_sentinel_status_dict() -> dict[str, Any]:
    """Sentinel konfigürasyonunu ve bağlantı metriklerini sözlük olarak döndürür."""
    hosts = get_sentinel_hosts()
    master = get_sentinel_master()
    return {
        "master_name": master,
        "sentinel_hosts_count": len(hosts),
        "sentinel_hosts": hosts,
        "is_connected": _ha_redis is not None,
        "has_redis_pkg": HAS_REDIS,
    }


__all__ = [
    "DEFAULT_CHECKPOINT_SIZE",
    "DEFAULT_MASTER_NAME",
    "DEFAULT_MAX_CONNECTIONS",
    "DEFAULT_SENTINEL_DUCKDB_PATH",
    "DEFAULT_SENTINEL_PORT",
    "DEFAULT_SENTINEL_TIMEOUT",
    "DEFAULT_SOCKET_TIMEOUT",
    "DEFAULT_WAL_SIZE",
    "HAS_REDIS",
    "clear_sentinel_failovers_duckdb",
    "close_ha_redis",
    "configure_duckdb_wal",
    "export_sentinel_status_to_polars",
    "get_ha_redis",
    "get_redis_password",
    "get_sentinel_hosts",
    "get_sentinel_master",
    "get_sentinel_status_dict",
    "read_sentinel_failovers_from_duckdb",
    "set_duckdb_connection",
    "to_orjson_bytes",
]
