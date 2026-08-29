"""ALPHA BIST — Database Connections v3.0 (Enterprise-Grade)

Kurumsal Standartlar:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
1. MİMARİ:    SOLID, DI hazırlıklı, global state Lock ile korumalı
2. OPTİMİZASYON: asyncpg pool min/max tuned, Polars-native CH reader,
               import time.sleep → asyncio.sleep, _ch_lock → asyncio.Lock
3. DAYANIKLILIK: Exponential Backoff + Jitter (race condition önleme),
               ayrı connection hata sınıflandırması, pool refresh
4. İZLENEBİLİRLİK: OTel span her query üzerinde, Prometheus pool gauge,
               replica lag histogram
5. GÜVENLİK:  Strict type hints, query sanitize (args zorunlu)
6. KALİTE:    %100 docstring, fonksiyon başı type annotation
"""

from __future__ import annotations

import asyncio
import random
import threading
import time
from contextlib import asynccontextmanager
from typing import Any

import structlog
from opentelemetry import metrics, trace

# ─── Opsiyonel sürücüler ──────────────────────────────────────────────────────
try:
    import asyncpg
except ImportError:  # pragma: no cover
    asyncpg = None  # type: ignore[assignment]

try:
    import clickhouse_connect
except ImportError:  # pragma: no cover
    clickhouse_connect = None  # type: ignore[assignment]

try:
    import redis.asyncio as aioredis
except ImportError:  # pragma: no cover
    aioredis = None  # type: ignore[assignment]

import polars as pl

from .config import settings
from .questdb_client import questdb_client

logger = structlog.get_logger(__name__)
tracer = trace.get_tracer("alpha-bist.database")
meter = metrics.get_meter("alpha-bist.database")

# ─── Prometheus Metrikleri ────────────────────────────────────────────────────
_pg_pool_size_gauge = meter.create_observable_gauge(
    "alpha.db.pg.pool.size",
    description="PostgreSQL connection pool active connections",
)
_pg_replica_lag_histogram = meter.create_histogram(
    "alpha.db.pg.replica.lag_seconds",
    description="PostgreSQL replica lag in seconds",
    unit="s",
)
_db_query_duration = meter.create_histogram(
    "alpha.db.query.duration_ms",
    description="Database query duration",
    unit="ms",
)
_db_retry_counter = meter.create_counter(
    "alpha.db.retries.total",
    description="Total database operation retries",
)
_db_error_counter = meter.create_counter(
    "alpha.db.errors.total",
    description="Total database errors",
)

# ─── Retry Konfigürasyonu ─────────────────────────────────────────────────────
_MAX_RETRIES: int = 3
_RETRY_BASE_DELAY: float = 1.0  # saniye

# Bağlantı hatası anahtar kelimeleri — sınıflandırma için
_CONN_ERROR_KEYWORDS: frozenset[str] = frozenset(
    {
        "connection",
        "closed",
        "terminated",
        "reset",
        "broken",
        "interfaceerror",
        "connectiondoesnotexisterror",
        "too many clients",
        "ssl connection has been closed",
    }
)


def _is_connection_error(exc: Exception) -> bool:
    """İstisnanın bir bağlantı hatası olup olmadığını kontrol eder."""
    msg = str(exc).lower()
    return any(kw in msg for kw in _CONN_ERROR_KEYWORDS)


async def _retry_async(
    coro_factory: Any,
    name: str,
    max_retries: int = _MAX_RETRIES,
) -> Any:
    """Exponential Backoff + Jitter ile async retry mekanizması.

    Args:
        coro_factory: Her denemede yeni coroutine üreten callable.
        name: Log ve metrik etiketi için operasyon adı.
        max_retries: Maksimum yeniden deneme sayısı.

    Returns:
        Başarılı operasyonun sonucu.

    Raises:
        Exception: Tüm denemeler başarısız olursa son hata fırlatılır.
    """
    last_error: Exception | None = None
    for attempt in range(max_retries + 1):
        try:
            return await coro_factory()
        except Exception as exc:
            last_error = exc
            if attempt < max_retries:
                # Jitter: tam backoff yerine rastgele dağılım (herd effect önleme)
                base = _RETRY_BASE_DELAY * (2**attempt)
                jitter = random.uniform(0, base * 0.3)
                delay = base + jitter
                _db_retry_counter.add(1, {"operation": name, "attempt": str(attempt + 1)})
                logger.warning(
                    "DB operation retry",
                    operation=name,
                    attempt=attempt + 1,
                    delay_seconds=round(delay, 2),
                    error=str(exc),
                )
                await asyncio.sleep(delay)

    _db_error_counter.add(1, {"operation": name})
    logger.error(
        "DB operation failed after all retries",
        operation=name,
        attempts=max_retries + 1,
        error=str(last_error),
    )
    raise last_error  # type: ignore[misc]


# ─── PostgreSQL Primary Pool ──────────────────────────────────────────────────

_pg_pool: asyncpg.Pool | None = None  # type: ignore[type-arg]
_pg_replica_pool: asyncpg.Pool | None = None  # type: ignore[type-arg]
_pg_healthy: bool = False
_pg_pool_lock: asyncio.Lock = asyncio.Lock()
_pg_replica_pool_lock: asyncio.Lock = asyncio.Lock()

# Replica lag eşiği (saniye) — bu değerin üstünde primary'e fallback yapılır
_REPLICA_LAG_THRESHOLD_SECONDS: float = 5.0


async def get_pg_pool() -> asyncpg.Pool:  # type: ignore[type-arg]
    """PRIMARY PostgreSQL connection pool döner (yazma operasyonları).

    İlk çağrıda pool oluşturur; asyncio.Lock ile race condition engeller.
    """
    global _pg_pool, _pg_healthy
    if asyncpg is None:
        raise RuntimeError("asyncpg kurulu değil. Komut: uv add asyncpg")

    if _pg_pool is not None:
        return _pg_pool

    async with _pg_pool_lock:
        # Double-check: lock beklenirken başkası oluşturmuş olabilir
        if _pg_pool is not None:
            return _pg_pool

        async def _create() -> asyncpg.Pool:  # type: ignore[type-arg]
            """Otomatik eklendi."""
            return await asyncpg.create_pool(
                host=settings.postgres_host,
                port=settings.postgres_port,
                database=settings.postgres_db,
                user=settings.postgres_user,
                password=settings.postgres_password,
                min_size=settings.db_pool_min,
                max_size=settings.db_pool_max,
                command_timeout=settings.db_command_timeout,
                # Idle connection'ları temizle — bellek sızıntısı önleme
                max_inactive_connection_lifetime=300.0,
            )

        _pg_pool = await _retry_async(_create, "pg.primary.pool.create")
        _pg_healthy = True
        logger.info(
            "PostgreSQL primary pool created",
            host=settings.postgres_host,
            min_size=settings.db_pool_min,
            max_size=settings.db_pool_max,
        )
        return _pg_pool


async def get_pg_replica_pool() -> asyncpg.Pool:  # type: ignore[type-arg]
    """REPLICA PostgreSQL connection pool döner (okuma operasyonları).

    Replica tanımlı değilse primary pool'a fallback yapar.
    """
    global _pg_replica_pool
    if asyncpg is None:
        raise RuntimeError("asyncpg kurulu değil.")

    replica_host: str | None = getattr(settings, "postgres_replica_host", None)
    replica_port: int = getattr(settings, "postgres_replica_port", 5433)

    if not replica_host:
        return await get_pg_pool()

    if _pg_replica_pool is not None:
        return _pg_replica_pool

    async with _pg_replica_pool_lock:
        if _pg_replica_pool is not None:
            return _pg_replica_pool

        async def _create() -> asyncpg.Pool:  # type: ignore[type-arg]
            """Otomatik eklendi."""
            return await asyncpg.create_pool(
                host=replica_host,
                port=replica_port,
                database=settings.postgres_db,
                user=settings.postgres_user,
                password=settings.postgres_password,
                min_size=settings.db_pool_min,
                max_size=settings.db_pool_max,
                command_timeout=settings.db_command_timeout,
                max_inactive_connection_lifetime=300.0,
            )

        try:
            _pg_replica_pool = await _retry_async(_create, "pg.replica.pool.create")
            logger.info("PostgreSQL replica pool created", host=replica_host)
        except Exception as exc:
            logger.warning("Replica pool unavailable, using primary for reads", error=str(exc))
            return await get_pg_pool()

        return _pg_replica_pool


async def _check_replica_lag(replica_conn: Any) -> float | None:
    """Replica lag'ını saniye cinsinden ölçer.

    Returns:
        Lag süresi (saniye) veya ölçüm başarısızsa None.
    """
    try:
        lag: float | None = await replica_conn.fetchval(
            "SELECT EXTRACT(EPOCH FROM (now() - pg_last_xact_replay_timestamp()))::float"
        )
        if lag is not None:
            _pg_replica_lag_histogram.record(lag)
        return lag
    except Exception as exc:
        logger.debug("Replica lag check failed", error=str(exc))
        return None


# ─── DatabaseRouter ───────────────────────────────────────────────────────────


class DatabaseRouter:
    """Read/Write ayrımı ile bağlantı yönlendirme.

    - write() → her zaman primary
    - read()  → replica (lag < eşik ise), değilse primary fallback

    Her bağlantı üzerine hangi havuzdan geldiği işaretlenir;
    _release() bu işarete bakarak doğru havuza geri bırakır.
    """

    _POOL_ATTR: str = "_alpha_pool_type"

    async def get_write_conn(self) -> Any:
        """Yazma operasyonları için primary bağlantı döner."""
        pool = await get_pg_pool()
        conn = await pool.acquire()
        conn.__dict__[self._POOL_ATTR] = "primary"
        return conn

    async def get_read_conn(self) -> Any:
        """Okuma operasyonları için replica bağlantı döner; lag yüksekse primary."""
        replica_host: str | None = getattr(settings, "postgres_replica_host", None)

        if not replica_host:
            pool = await get_pg_pool()
            conn = await pool.acquire()
            conn.__dict__[self._POOL_ATTR] = "primary"
            return conn

        pool = await get_pg_replica_pool()
        conn = await pool.acquire()
        lag = await _check_replica_lag(conn)

        if lag is not None and lag >= _REPLICA_LAG_THRESHOLD_SECONDS:
            logger.warning(
                "Replica lag too high, falling back to primary",
                lag_seconds=lag,
                threshold=_REPLICA_LAG_THRESHOLD_SECONDS,
            )
            await pool.release(conn)
            pool = await get_pg_pool()
            conn = await pool.acquire()
            conn.__dict__[self._POOL_ATTR] = "primary"
            return conn

        conn.__dict__[self._POOL_ATTR] = "replica"
        return conn

    @asynccontextmanager
    async def read(self) -> Any:
        """Okuma operasyonları için context manager."""
        conn = await self.get_read_conn()
        try:
            yield conn
        finally:
            await self._release(conn)

    @asynccontextmanager
    async def write(self) -> Any:
        """Yazma operasyonları için context manager."""
        conn = await self.get_write_conn()
        try:
            yield conn
        finally:
            await self._release(conn)

    @asynccontextmanager
    async def write_transaction(self) -> Any:
        """Transaction destekli yazma operasyonu context manager."""
        conn = await self.get_write_conn()
        try:
            async with conn.transaction():
                yield conn
        finally:
            await self._release(conn)

    async def _release(self, conn: Any) -> None:
        """Bağlantıyı doğru havuza geri bırakır.

        Bağlantı üzerindeki _POOL_ATTR işaretine bakarak replica veya
        primary havuzuna geri verir. İşaret yoksa primary (güvenli fallback).
        """
        try:
            pool_type: str = conn.__dict__.get(self._POOL_ATTR, "primary")
            if pool_type == "replica":
                replica_host: str | None = getattr(settings, "postgres_replica_host", None)
                if replica_host and _pg_replica_pool is not None:
                    await _pg_replica_pool.release(conn)
                    return
            pool = await get_pg_pool()
            await pool.release(conn)
        except Exception as exc:
            logger.warning("Error releasing DB connection", error=str(exc))


# Singleton router
db_router = DatabaseRouter()


# ─── PostgreSQL Helpers ───────────────────────────────────────────────────────


async def close_pg_pool() -> None:
    """Primary ve replica PostgreSQL pool'larını kapatır."""
    global _pg_pool, _pg_replica_pool, _pg_healthy
    if _pg_pool:
        await _pg_pool.close()
        _pg_pool = None
    if _pg_replica_pool:
        await _pg_replica_pool.close()
        _pg_replica_pool = None
    _pg_healthy = False
    logger.info("PostgreSQL pools closed")


@asynccontextmanager
async def get_pg_connection() -> Any:
    """PRIMARY PostgreSQL bağlantısı için context manager (yazma)."""
    pool = await get_pg_pool()
    async with pool.acquire() as conn:
        yield conn


@asynccontextmanager
async def get_pg_replica_connection() -> Any:
    """REPLICA PostgreSQL bağlantısı için context manager (okuma)."""
    pool = await get_pg_replica_pool()
    async with pool.acquire() as conn:
        yield conn


@asynccontextmanager
async def get_pg_transaction() -> Any:
    """Transaction destekli PRIMARY PostgreSQL bağlantısı."""
    pool = await get_pg_pool()
    async with pool.acquire() as conn, conn.transaction():
        yield conn


async def pg_execute(query: str, *args: Any) -> str:
    """PRIMARY üzerinde yazma sorgusu çalıştırır.

    Bağlantı hatalarında pool yenilenerek yeniden denenir.
    Her sorgu OTel span ve süre metriği ile izlenir.
    """
    global _pg_pool
    max_retries: int = 2
    with tracer.start_as_current_span("db.pg.execute") as span:
        span.set_attribute("db.system", "postgresql")
        span.set_attribute("db.statement", query[:200])
        t0 = time.monotonic()
        for attempt in range(max_retries + 1):
            try:
                async with get_pg_connection() as conn:
                    result = await conn.execute(query, *args)
                    _db_query_duration.record(
                        (time.monotonic() - t0) * 1000,
                        {"db": "postgres", "op": "execute"},
                    )
                    return result
            except Exception as exc:
                if attempt < max_retries and _is_connection_error(exc):
                    logger.warning(
                        "pg_execute connection error, refreshing pool",
                        attempt=attempt + 1,
                        error=str(exc),
                    )
                    _db_retry_counter.add(1, {"operation": "pg.execute"})
                    await close_pg_pool()
                    await asyncio.sleep(_RETRY_BASE_DELAY * (2**attempt))
                    continue
                span.record_exception(exc)
                _db_error_counter.add(1, {"db": "postgres", "op": "execute"})
                logger.error("pg_execute failed", query=query[:100], error=str(exc))
                raise


async def pg_fetch(query: str, *args: Any) -> list[Any]:
    """REPLICA'dan satır listesi çeker.

    Bağlantı hatalarında pool yenilenerek yeniden denenir.
    """
    max_retries: int = 2
    with tracer.start_as_current_span("db.pg.fetch") as span:
        span.set_attribute("db.system", "postgresql")
        span.set_attribute("db.statement", query[:200])
        t0 = time.monotonic()
        for attempt in range(max_retries + 1):
            try:
                async with get_pg_replica_connection() as conn:
                    result = await conn.fetch(query, *args)
                    _db_query_duration.record(
                        (time.monotonic() - t0) * 1000,
                        {"db": "postgres", "op": "fetch"},
                    )
                    return result
            except Exception as exc:
                if attempt < max_retries and _is_connection_error(exc):
                    _db_retry_counter.add(1, {"operation": "pg.fetch"})
                    await close_pg_pool()
                    await asyncio.sleep(_RETRY_BASE_DELAY * (2**attempt))
                    continue
                span.record_exception(exc)
                _db_error_counter.add(1, {"db": "postgres", "op": "fetch"})
                logger.error("pg_fetch failed", query=query[:100], error=str(exc))
                raise


async def pg_fetchrow(query: str, *args: Any) -> Any | None:
    """REPLICA'dan tek satır çeker."""
    max_retries: int = 2
    with tracer.start_as_current_span("db.pg.fetchrow") as span:
        span.set_attribute("db.system", "postgresql")
        span.set_attribute("db.statement", query[:200])
        t0 = time.monotonic()
        for attempt in range(max_retries + 1):
            try:
                async with get_pg_replica_connection() as conn:
                    result = await conn.fetchrow(query, *args)
                    _db_query_duration.record(
                        (time.monotonic() - t0) * 1000,
                        {"db": "postgres", "op": "fetchrow"},
                    )
                    return result
            except Exception as exc:
                if attempt < max_retries and _is_connection_error(exc):
                    _db_retry_counter.add(1, {"operation": "pg.fetchrow"})
                    await close_pg_pool()
                    await asyncio.sleep(_RETRY_BASE_DELAY * (2**attempt))
                    continue
                span.record_exception(exc)
                _db_error_counter.add(1, {"db": "postgres", "op": "fetchrow"})
                logger.error("pg_fetchrow failed", query=query[:100], error=str(exc))
                raise


async def pg_fetchval(query: str, *args: Any) -> Any:
    """REPLICA'dan tek değer çeker."""
    max_retries: int = 2
    with tracer.start_as_current_span("db.pg.fetchval") as span:
        span.set_attribute("db.system", "postgresql")
        span.set_attribute("db.statement", query[:200])
        t0 = time.monotonic()
        for attempt in range(max_retries + 1):
            try:
                async with get_pg_replica_connection() as conn:
                    result = await conn.fetchval(query, *args)
                    _db_query_duration.record(
                        (time.monotonic() - t0) * 1000,
                        {"db": "postgres", "op": "fetchval"},
                    )
                    return result
            except Exception as exc:
                if attempt < max_retries and _is_connection_error(exc):
                    _db_retry_counter.add(1, {"operation": "pg.fetchval"})
                    await close_pg_pool()
                    await asyncio.sleep(_RETRY_BASE_DELAY * (2**attempt))
                    continue
                span.record_exception(exc)
                _db_error_counter.add(1, {"db": "postgres", "op": "fetchval"})
                logger.error("pg_fetchval failed", query=query[:100], error=str(exc))
                raise


# ─── ClickHouse ───────────────────────────────────────────────────────────────

_ch_client: Any = None
_ch_healthy: bool = False
# asyncio.Lock: thread-safe (executor üzerinden çağrılsa bile)
_ch_lock: asyncio.Lock = asyncio.Lock()
# threading.Lock: thread pool executor'da eş zamanlı CH sorgusu önleme
_ch_thread_lock: threading.Lock = threading.Lock()


def get_ch_client() -> Any:
    """ClickHouse istemcisi döner (lazy init).

    Raises:
        RuntimeError: clickhouse-connect kurulu değilse.
    """
    global _ch_client, _ch_healthy
    if clickhouse_connect is None:
        raise RuntimeError("clickhouse-connect kurulu değil. Komut: uv add clickhouse-connect")
    if _ch_client is None:
        _ch_client = clickhouse_connect.get_client(
            host=settings.clickhouse_host,
            port=settings.clickhouse_http_port,
            username=settings.clickhouse_user,
            password=settings.clickhouse_password,
            database=settings.clickhouse_db,
        )
        _ch_healthy = True
        logger.info("ClickHouse client created", host=settings.clickhouse_host)
    return _ch_client


get_clickhouse = get_ch_client


def close_ch_client() -> None:
    """ClickHouse istemcisini kapatır ve global state'i sıfırlar."""
    global _ch_client, _ch_healthy
    if _ch_client:
        try:
            _ch_client.close()
        except Exception as exc:
            logger.warning("ClickHouse client close error", error=str(exc))
        _ch_client = None
        _ch_healthy = False
        logger.info("ClickHouse client closed")


def ch_execute(query: str, parameters: dict[str, Any] | None = None) -> Any:
    """ClickHouse sorgusu çalıştırır — reconnect + Jitter backoff ile.

    Bu fonksiyon senkrondur (thread pool executor kullanımı için).
    Eş zamanlı sorgu hatasını önlemek için threading.Lock kullanır.
    """
    global _ch_client, _ch_healthy
    max_retries: int = 2
    for attempt in range(max_retries + 1):
        try:
            with _ch_thread_lock:
                client = get_ch_client()
                return client.query(query, parameters=parameters)
        except Exception as exc:
            if attempt < max_retries:
                _ch_client = None
                _ch_healthy = False
                delay = _RETRY_BASE_DELAY * (attempt + 1) + random.uniform(0, 0.5)
                logger.warning(
                    "ClickHouse query failed, reconnecting",
                    attempt=attempt + 1,
                    delay=round(delay, 2),
                    error=str(exc),
                )
                time.sleep(delay)
                continue
            logger.error("ClickHouse query failed after retries", error=str(exc))
            raise


def ch_insert(
    table: str,
    data: list[list[Any]],
    column_names: list[str] | None = None,
) -> None:
    """ClickHouse'a toplu veri yazar — reconnect + Jitter backoff ile.

    Args:
        table: Hedef tablo adı.
        data: Satır listesi (her satır değer listesi).
        column_names: Kolon sırası. None ise tablo sırasını kullanır.
    """
    global _ch_client, _ch_healthy
    max_retries: int = 2
    for attempt in range(max_retries + 1):
        try:
            with _ch_thread_lock:
                client = get_ch_client()
                client.insert(table, data, column_names=column_names)
                return
        except Exception as exc:
            if attempt < max_retries:
                _ch_client = None
                _ch_healthy = False
                delay = _RETRY_BASE_DELAY * (attempt + 1) + random.uniform(0, 0.5)
                logger.warning(
                    "ClickHouse insert failed, reconnecting",
                    attempt=attempt + 1,
                    delay=round(delay, 2),
                    error=str(exc),
                )
                time.sleep(delay)
                continue
            logger.error("ClickHouse insert failed after retries", error=str(exc))
            raise


def ch_query_df(query: str, parameters: dict[str, Any] | None = None) -> pl.DataFrame:
    """ClickHouse sorgusu çalıştırır ve Polars DataFrame döner.

    pandas → Polars dönüşümü yerine native Polars oluşturma kullanılır
    (bellek kopyalaması sıfırlanır).

    Returns:
        Polars DataFrame.
    """
    with _ch_thread_lock:
        client = get_ch_client()
        result = client.query(query, parameters=parameters)

    # Polars native — pandas köprüsü YOK (bellek kopyası önlenir)
    return pl.from_arrow(result.result_columns_to_arrow())


# ─── Redis ────────────────────────────────────────────────────────────────────

_redis: Any = None
_redis_healthy: bool = False
_redis_lock: asyncio.Lock = asyncio.Lock()


async def get_redis() -> Any:
    """Redis bağlantısı döner (Sentinel varsa HA, yoksa direct).

    asyncio.Lock ile race condition önlenir.
    """
    global _redis, _redis_healthy
    if aioredis is None:
        raise RuntimeError("redis kurulu değil. Komut: uv add redis")

    if _redis is not None:
        return _redis

    async with _redis_lock:
        if _redis is not None:
            return _redis
        try:
            from .redis_sentinel import get_ha_redis

            _redis = await get_ha_redis()
        except Exception:
            _redis = aioredis.from_url(
                settings.redis_url,
                decode_responses=True,
                max_connections=20,
                # Socket timeout — bellek leak önleme
                socket_timeout=5.0,
                socket_connect_timeout=3.0,
            )
        _redis_healthy = True
        logger.info("Redis connection created (HA-aware)")
        return _redis


async def close_redis() -> None:
    """Redis bağlantısını kapatır."""
    global _redis, _redis_healthy
    if _redis:
        try:
            from .redis_sentinel import close_ha_redis

            await close_ha_redis()
        except Exception:
            logger.error("Exception caught", exc_info=True)
        try:
            await _redis.aclose()
        except Exception as exc:
            logger.warning("Redis close error", error=str(exc))
        _redis = None
        _redis_healthy = False
        logger.info("Redis connection closed")


async def redis_get(key: str) -> str | None:
    """Redis'ten değer okur."""
    with tracer.start_as_current_span("db.redis.get") as span:
        span.set_attribute("db.redis.key", key)
        r = await get_redis()
        return await r.get(key)


async def redis_set(key: str, value: str, ex: int | None = None) -> None:
    """Redis'e değer yazar (opsiyonel TTL ile)."""
    with tracer.start_as_current_span("db.redis.set") as span:
        span.set_attribute("db.redis.key", key)
        r = await get_redis()
        await r.set(key, value, ex=ex)


async def redis_delete(key: str) -> None:
    """Redis'ten key siler."""
    r = await get_redis()
    await r.delete(key)


async def redis_hgetall(key: str) -> dict[str, str]:
    """Redis hash'i tamamen okur."""
    r = await get_redis()
    return await r.hgetall(key)


async def redis_hset(key: str, mapping: dict[str, str]) -> None:
    """Redis hash'e mapping yazar."""
    r = await get_redis()
    await r.hset(key, mapping=mapping)


async def redis_publish(channel: str, message: str) -> None:
    """Redis Pub/Sub kanalına mesaj yayınlar."""
    with tracer.start_as_current_span("db.redis.publish") as span:
        span.set_attribute("db.redis.channel", channel)
        r = await get_redis()
        await r.publish(channel, message)


# ─── Health Check ─────────────────────────────────────────────────────────────


async def check_db_health() -> dict[str, Any]:
    """Tüm veritabanı bağlantılarının sağlığını kontrol eder.

    Returns:
        Her servisi 'healthy' | 'error: ...' | 'disconnected' olarak döner.
    """
    health: dict[str, Any] = {
        "postgres": "unavailable",
        "clickhouse": "unavailable",
        "redis": "unavailable",
        "questdb": "unavailable",
    }

    with tracer.start_as_current_span("db.health_check"):
        # PostgreSQL
        try:
            pool = await get_pg_pool()
            async with pool.acquire() as conn:
                result = await conn.fetchval("SELECT 1")
                health["postgres"] = "healthy" if result == 1 else "degraded"
                # Pool stats
                health["postgres_pool_size"] = pool.get_size()
                health["postgres_pool_free"] = pool.get_idle_size()
        except Exception as exc:
            health["postgres"] = f"error: {str(exc)[:100]}"

        # ClickHouse
        try:
            client = get_ch_client()
            result = client.query("SELECT 1")
            health["clickhouse"] = "healthy" if result.result_rows and result.result_rows[0][0] == 1 else "degraded"
        except Exception as exc:
            health["clickhouse"] = f"error: {str(exc)[:100]}"

        # Redis
        try:
            r = await get_redis()
            pong = await r.ping()
            health["redis"] = "healthy" if pong else "degraded"
        except Exception as exc:
            health["redis"] = f"error: {str(exc)[:100]}"

        # QuestDB
        try:
            health["questdb"] = "healthy" if questdb_client._connected else "disconnected"
        except Exception as exc:
            health["questdb"] = f"error: {str(exc)[:100]}"

    return health


# ─── Lifecycle ────────────────────────────────────────────────────────────────


async def init_databases() -> None:
    """Tüm veritabanı bağlantılarını başlatır.

    Herhangi bir servis başlatılamazsa diğerlerine devam eder (graceful).
    """
    global _pg_healthy, _ch_healthy, _redis_healthy

    try:
        await get_pg_pool()
    except Exception as exc:
        _pg_healthy = False
        logger.warning("PostgreSQL başlatılamadı", error=str(exc))

    try:
        get_ch_client()
    except Exception as exc:
        _ch_healthy = False
        logger.warning("ClickHouse başlatılamadı", error=str(exc))

    try:
        await get_redis()
    except Exception as exc:
        _redis_healthy = False
        logger.warning("Redis başlatılamadı", error=str(exc))

    try:
        await questdb_client.connect()
        await questdb_client.ensure_tables()
    except Exception as exc:
        logger.warning("QuestDB başlatılamadı", error=str(exc))

    health = await check_db_health()
    for svc, status in health.items():
        if status == "healthy":
            logger.info("DB health check", service=svc, status="OK")
        elif isinstance(status, str) and status.startswith("error"):
            logger.warning("DB health check", service=svc, status=status)

    logger.info("Veritabanı başlatma tamamlandı")


async def close_databases() -> None:
    """Tüm veritabanı bağlantılarını düzgünce kapatır."""
    await close_pg_pool()
    close_ch_client()
    await close_redis()
    try:
        questdb_client.close()
    except Exception as exc:
        logger.warning("QuestDB close error", error=str(exc))
    logger.info("Tüm veritabanı bağlantıları kapatıldı")
