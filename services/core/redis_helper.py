"""ALPHA BIST — Redis Yardımcı ve Çok Katmanlı Önbellek Motoru (Redis Helper & Cache).

- Redis L1 Yüksek Hızlı Dağıtık Önbellek
- In-Memory & DuckDB L2 Kalıcı Güvenli Fallback Önbellek
- Self-Healing Otomatik Yeniden Bağlanma (Zero-Touch Reconnection)
- Thread-Safe (RLock) ve Polars/orjson Desteği
"""

from __future__ import annotations

import os
import threading
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Final

import duckdb
import orjson
import polars as pl
import structlog

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

DEFAULT_TTL_SEC: Final[int] = 300
DEFAULT_SOCKET_TIMEOUT_SEC: Final[float] = 0.5
RECONNECT_INTERVAL_SEC: Final[float] = 30.0
DEFAULT_MAX_MEM_CACHE_SIZE: Final[int] = 5000
DEFAULT_REDIS_DUCKDB_PATH: Final[str] = "data/redis_l2_cache.duckdb"
DEFAULT_CHECKPOINT_SIZE: Final[str] = "4MB"
DEFAULT_WAL_SIZE: Final[str] = "2MB"

_lock = threading.RLock()
_redis_client: Any | None = None
_redis_available: bool = False
_last_connect_attempt: float = 0.0

# In-Memory L1 Fallback Cache: key -> (expire_mono: float, json_str: str)
_mem_cache: dict[str, tuple[float, str]] = {}
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
        logger.warning("redis_duckdb_wal_yapilandirma_uyarisi", hata=str(e))


def set_duckdb_connection(conn: duckdb.DuckDBPyConnection) -> None:
    """L2 kalıcı önbellek için DuckDB bağlantısını tanımlar ve şemayı kurar."""
    global _duckdb_conn
    with _lock:
        _duckdb_conn = conn
        configure_duckdb_wal(_duckdb_conn)
        try:
            _duckdb_conn.execute("""
                CREATE TABLE IF NOT EXISTS redis_l2_cache (
                    cache_key VARCHAR PRIMARY KEY,
                    payload_json VARCHAR,
                    expires_at TIMESTAMP,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """)
        except Exception as exc:
            logger.error("Redis L2 DuckDB şema oluşturma hatası", hata=str(exc))


def _get_active_duckdb(writable: bool = False) -> tuple[duckdb.DuckDBPyConnection | None, bool]:
    """Aktif DuckDB bağlantısını ve bağlantının kapatılması gerekip gerekmediğini döndürür."""
    with _lock:
        if _duckdb_conn is not None:
            return _duckdb_conn, False

    p = Path(DEFAULT_REDIS_DUCKDB_PATH)
    if not writable and not p.exists():
        return None, False

    try:
        if writable:
            p.parent.mkdir(parents=True, exist_ok=True)
            conn = duckdb.connect(str(p))
            configure_duckdb_wal(conn)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS redis_l2_cache (
                    cache_key VARCHAR PRIMARY KEY,
                    payload_json VARCHAR,
                    expires_at TIMESTAMP,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """)
            return conn, True
        else:
            conn = duckdb.connect(str(p), read_only=True)
            tables = [r[0] for r in conn.execute("SHOW TABLES").fetchall()]
            if "redis_l2_cache" not in tables:
                conn.close()
                return None, False
            return conn, True
    except Exception as exc:
        logger.debug("redis_duckdb_aktif_baglanti_hatasi", hata=str(exc))
        return None, False


def _get_l2_duckdb_cache(key: str) -> Any | None:
    """DuckDB L2 önbelleğinden geçerli kaydı okur."""
    conn, should_close = _get_active_duckdb(writable=False)
    if conn is None:
        return None
    try:
        now_dt = datetime.now(UTC)
        row = conn.execute(
            """
            SELECT payload_json FROM redis_l2_cache
            WHERE cache_key = ? AND expires_at > ?
            LIMIT 1
            """,
            [key, now_dt],
        ).fetchone()
        if row:
            return orjson.loads(row[0])
    except Exception as exc:
        logger.debug("Redis L2 DuckDB önbellek okuma hatası", key=key, hata=str(exc))
    finally:
        if should_close:
            conn.close()
    return None


def _set_l2_duckdb_cache(key: str, data: Any, ttl_sec: int) -> None:
    """DuckDB L2 önbelleğine kayıt yazar."""
    conn, should_close = _get_active_duckdb(writable=True)
    if conn is None:
        return
    try:
        payload = orjson.dumps(data, default=str).decode("utf-8")
        exp_dt = datetime.now(UTC) + timedelta(seconds=ttl_sec)
        conn.execute(
            """
            INSERT OR REPLACE INTO redis_l2_cache (cache_key, payload_json, expires_at)
            VALUES (?, ?, ?)
            """,
            [key, payload, exp_dt],
        )
    except Exception as exc:
        logger.debug("Redis L2 DuckDB önbellek yazma hatası", key=key, hata=str(exc))
    finally:
        if should_close:
            conn.close()


def get_client() -> Any | None:
    """Thread-safe ve Self-Healing Redis istemcisi döndürür.

    Redis daha önce çökmüş olsa bile RECONNECT_INTERVAL_SEC sonrasında otomatik tekrar dener.
    """
    global _redis_client, _redis_available, _last_connect_attempt
    with _lock:
        now_mono = time.monotonic()

        # Halihazırda bağlı ve istemci varsa
        if _redis_client is not None and _redis_available:
            return _redis_client

        # Reconnect throttling: Son denemenin üzerinden yeterli süre geçmediyse bekle
        if (now_mono - _last_connect_attempt) < RECONNECT_INTERVAL_SEC:
            return None

        _last_connect_attempt = now_mono

        try:
            import redis as redis_lib

            host = os.environ.get("REDIS_HOST", "127.0.0.1" if os.name == "nt" else "redis")
            port = int(os.environ.get("REDIS_PORT", "6379"))
            db = int(os.environ.get("REDIS_DB", "0"))
            password = os.environ.get("REDIS_PASSWORD", "") or None

            client = redis_lib.Redis(
                host=host,
                port=port,
                db=db,
                password=password,
                socket_timeout=DEFAULT_SOCKET_TIMEOUT_SEC,
                socket_connect_timeout=DEFAULT_SOCKET_TIMEOUT_SEC,
                decode_responses=False,
            )
            client.ping()
            _redis_client = client
            _redis_available = True
            logger.info("Redis bağlantısı başarıyla kuruldu (Self-Healing)", host=host, port=port, db=db)
            return _redis_client
        except Exception as exc:
            _redis_available = False
            _redis_client = None
            _last_connect_attempt = time.monotonic()
            logger.warning("Redis bağlantısı kurulamadı, L1/L2 önbelleğe düşülüyor", hata=str(exc))
            return None


@otel_trace("redis_helper.get_cached")
def get_cached(key: str) -> Any | None:
    """Önbellekten değer okur (Redis -> Memory L1 -> DuckDB L2 Fallback)."""
    r = get_client()
    if r is not None:
        try:
            data = r.get(key)
            if data:
                return orjson.loads(data)
        except Exception as exc:
            logger.warning("Redis okuma hatası, yerel önbelleğe düşülüyor", key=key, hata=str(exc))
            with _lock:
                _redis_available = False

    # In-Memory L1 Kontrolü
    now_mono = time.monotonic()
    with _lock:
        if key in _mem_cache:
            exp, val = _mem_cache[key]
            if exp > now_mono:
                try:
                    return orjson.loads(val)
                except Exception:
                    pass
            _mem_cache.pop(key, None)

    # DuckDB L2 Kontrolü
    return _get_l2_duckdb_cache(key)


@otel_trace("redis_helper.set_cached")
def set_cached(key: str, data: Any, ttl: int = DEFAULT_TTL_SEC) -> bool:
    """Önbelleğe değer yazar (Redis + Memory L1 + DuckDB L2)."""
    payload_str = orjson.dumps(data, default=str).decode("utf-8")
    now_mono = time.monotonic()

    # Bellek önbelleğine daima yaz (L1)
    with _lock:
        _mem_cache[key] = (now_mono + ttl, payload_str)
        if len(_mem_cache) > DEFAULT_MAX_MEM_CACHE_SIZE:
            # En eski veya süresi dolanları temizle
            _cleanup_mem_cache()

    # DuckDB L2 önbelleğe yaz
    _set_l2_duckdb_cache(key, data, ttl)

    # Redis'e yaz
    r = get_client()
    if r is not None:
        try:
            r.setex(key, ttl, payload_str)
            return True
        except Exception as exc:
            logger.warning("Redis yazma hatası, yerel önbellek korundu", key=key, hata=str(exc))
            with _lock:
                _redis_available = False

    return True


@otel_trace("redis_helper.delete_cached")
def delete_cached(key: str) -> bool:
    """Önbellekten anahtarı tüm katmanlardan siler."""
    with _lock:
        _mem_cache.pop(key, None)

    conn, should_close = _get_active_duckdb(writable=True)
    if conn is not None:
        try:
            conn.execute("DELETE FROM redis_l2_cache WHERE cache_key = ?", [key])
        except Exception as exc:
            logger.debug("DuckDB L2 silme hatası", key=key, hata=str(exc))
        finally:
            if should_close:
                conn.close()

    r = get_client()
    if r is not None:
        try:
            r.delete(key)
            return True
        except Exception as exc:
            logger.warning("Redis silme hatası", key=key, hata=str(exc))
            with _lock:
                _redis_available = False

    return True


@otel_trace("redis_helper.mget_cached")
def mget_cached(keys: list[str]) -> dict[str, Any]:
    """Çoklu anahtarı toplu olarak çeker (Pipeline & Yerel birleştirme)."""
    if not keys:
        return {}

    results: dict[str, Any] = {}
    missing_keys: list[str] = list(keys)

    r = get_client()
    if r is not None:
        try:
            pipe = r.pipeline(transaction=False)
            for k in keys:
                pipe.get(k)
            pipe_results = pipe.execute()
            for k, val in zip(keys, pipe_results, strict=False):
                if val is not None:
                    try:
                        results[k] = orjson.loads(val)
                        missing_keys.remove(k)
                    except Exception:
                        pass
        except Exception as exc:
            logger.warning("Redis mget pipeline hatası", hata=str(exc))
            with _lock:
                _redis_available = False

    # Eksik kalan anahtarları Memory L1 ve DuckDB L2'den tamamla
    if missing_keys:
        now_mono = time.monotonic()
        with _lock:
            for k in list(missing_keys):
                if k in _mem_cache:
                    exp, val = _mem_cache[k]
                    if exp > now_mono:
                        try:
                            results[k] = orjson.loads(val)
                            missing_keys.remove(k)
                        except Exception:
                            pass
                    else:
                        _mem_cache.pop(k, None)

        for k in list(missing_keys):
            val_l2 = _get_l2_duckdb_cache(k)
            if val_l2 is not None:
                results[k] = val_l2
                missing_keys.remove(k)

    return results


@otel_trace("redis_helper.mset_cached")
def mset_cached(mapping: dict[str, Any], ttl: int = DEFAULT_TTL_SEC) -> bool:
    """Çoklu anahtarı toplu yazar (Pipeline & L1/L2 senkronizasyonu)."""
    if not mapping:
        return True

    now_mono = time.monotonic()
    with _lock:
        for k, v in mapping.items():
            payload = orjson.dumps(v, default=str).decode("utf-8")
            _mem_cache[k] = (now_mono + ttl, payload)
            _set_l2_duckdb_cache(k, v, ttl)

    r = get_client()
    if r is not None:
        try:
            pipe = r.pipeline(transaction=False)
            for k, v in mapping.items():
                payload = orjson.dumps(v, default=str).decode("utf-8")
                pipe.setex(k, ttl, payload)
            pipe.execute()
            return True
        except Exception as exc:
            logger.warning("Redis mset pipeline hatası", hata=str(exc))
            with _lock:
                _redis_available = False

    return True


def _cleanup_mem_cache() -> None:
    """Süresi dolan bellek önbellek kayıtlarını temizler."""
    now_mono = time.monotonic()
    keys_to_del = [k for k, (exp, _) in _mem_cache.items() if exp <= now_mono]
    for k in keys_to_del:
        _mem_cache.pop(k, None)


def is_available() -> bool:
    """Redis bağlantısının aktif olup olmadığını belirtir."""
    return get_client() is not None


def export_cache_metrics_to_polars() -> pl.DataFrame:
    """Önbellek metriklerini ve bellek durumunu Polars DataFrame olarak dışa aktarır."""
    now_mono = time.monotonic()
    with _lock:
        records = [
            {
                "cache_key": k,
                "remaining_ttl_sec": max(0.0, exp - now_mono),
                "payload_size_bytes": len(val),
                "is_expired": exp <= now_mono,
            }
            for k, (exp, val) in _mem_cache.items()
        ]

    if not records:
        return pl.DataFrame(
            schema={
                "cache_key": pl.Utf8,
                "remaining_ttl_sec": pl.Float64,
                "payload_size_bytes": pl.Int64,
                "is_expired": pl.Boolean,
            }
        )

    return pl.DataFrame(records)


def reset_memory_cache() -> None:
    """Bellek önbelleğini sıfırlar (Test ve acil durumlar için)."""
    with _lock:
        _mem_cache.clear()


def read_l2_cache_from_duckdb(
    db_path: str = DEFAULT_REDIS_DUCKDB_PATH,
    include_expired: bool = False,
) -> pl.DataFrame:
    """DuckDB L2 önbelleğindeki kayıtları Polars DataFrame olarak okur."""
    p = Path(db_path)
    empty_schema = {
        "cache_key": pl.String,
        "payload_json": pl.String,
        "expires_at": pl.Datetime,
        "created_at": pl.Datetime,
    }
    with _lock:
        if _duckdb_conn is not None:
            try:
                if include_expired:
                    return _duckdb_conn.execute("SELECT * FROM redis_l2_cache").pl()
                return _duckdb_conn.execute(
                    "SELECT * FROM redis_l2_cache WHERE expires_at > ?",
                    [datetime.now(UTC)],
                ).pl()
            except Exception as e:
                logger.error("read_l2_cache_duckdb_hatasi", hata=str(e))
                return pl.DataFrame(schema=empty_schema)

    if not p.exists():
        return pl.DataFrame(schema=empty_schema)

    try:
        conn = duckdb.connect(str(p), read_only=True)
        tables = [r[0] for r in conn.execute("SHOW TABLES").fetchall()]
        if "redis_l2_cache" not in tables:
            conn.close()
            return pl.DataFrame(schema=empty_schema)
        if include_expired:
            df = conn.execute("SELECT * FROM redis_l2_cache").pl()
        else:
            df = conn.execute(
                "SELECT * FROM redis_l2_cache WHERE expires_at > ?",
                [datetime.now(UTC)],
            ).pl()
        conn.close()
        return df
    except Exception as e:
        logger.error("read_l2_cache_file_hatasi", hata=str(e))
        return pl.DataFrame(schema=empty_schema)


def clear_l2_cache_duckdb(db_path: str = DEFAULT_REDIS_DUCKDB_PATH) -> bool:
    """DuckDB L2 tablosundaki tüm kayıtları temizler."""
    with _lock:
        if _duckdb_conn is not None:
            try:
                _duckdb_conn.execute("DELETE FROM redis_l2_cache")
                return True
            except Exception as e:
                logger.error("clear_l2_cache_duckdb_hatasi", hata=str(e))
                return False

    p = Path(db_path)
    if not p.exists():
        return True
    try:
        conn = duckdb.connect(str(p))
        tables = [r[0] for r in conn.execute("SHOW TABLES").fetchall()]
        if "redis_l2_cache" in tables:
            conn.execute("DELETE FROM redis_l2_cache")
        conn.close()
        return True
    except Exception as e:
        logger.error("clear_l2_cache_file_hatasi", hata=str(e))
        return False


def to_orjson_bytes(data: Any) -> bytes:
    """Veriyi orjson ile güvenli bayt dizisine serileştirir."""
    return orjson.dumps(data, default=str)


def get_cache_stats() -> dict[str, Any]:
    """Önbellek katmanlarının genel sağlık ve kapasite durumunu döndürür."""
    with _lock:
        mem_count = len(_mem_cache)
        r_active = _redis_available and _redis_client is not None

    l2_count = 0
    try:
        df = read_l2_cache_from_duckdb(include_expired=False)
        l2_count = df.height
    except Exception:
        pass

    return {
        "redis_available": r_active,
        "mem_cache_count": mem_count,
        "duckdb_l2_count": l2_count,
        "max_mem_cache_size": DEFAULT_MAX_MEM_CACHE_SIZE,
    }


__all__ = [
    "DEFAULT_CHECKPOINT_SIZE",
    "DEFAULT_MAX_MEM_CACHE_SIZE",
    "DEFAULT_REDIS_DUCKDB_PATH",
    "DEFAULT_SOCKET_TIMEOUT_SEC",
    "DEFAULT_TTL_SEC",
    "DEFAULT_WAL_SIZE",
    "RECONNECT_INTERVAL_SEC",
    "clear_l2_cache_duckdb",
    "configure_duckdb_wal",
    "delete_cached",
    "export_cache_metrics_to_polars",
    "get_cache_stats",
    "get_cached",
    "get_client",
    "is_available",
    "mget_cached",
    "mset_cached",
    "read_l2_cache_from_duckdb",
    "reset_memory_cache",
    "set_cached",
    "set_duckdb_connection",
    "to_orjson_bytes",
]
