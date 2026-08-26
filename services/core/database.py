"""ALPHA BIST — Database Connections v2.0 (Production-Hardened)

FAZ 5.1:
- Connection retry with exponential backoff
- Health check on startup
- Graceful failure handling (no uncontrolled crash)
- Transaction support
- Connection pool tuning
"""

import asyncio
from contextlib import asynccontextmanager
from typing import Optional, Any, List, Dict
import structlog

try:
    import asyncpg
except ImportError:
    asyncpg = None

try:
    import clickhouse_connect
except ImportError:
    clickhouse_connect = None

try:
    import redis.asyncio as aioredis
except ImportError:
    aioredis = None

from .config import settings
from .questdb_client import questdb_client

logger = structlog.get_logger()

# =====================================================
# RETRY CONFIG
# =====================================================
_MAX_RETRIES = 3
_RETRY_BASE_DELAY = 1.0  # seconds


async def _retry_async(coro_factory, name: str, max_retries: int = _MAX_RETRIES):
    """Retry async operation with exponential backoff."""
    last_error = None
    for attempt in range(max_retries + 1):
        try:
            return await coro_factory()
        except Exception as e:
            last_error = e
            if attempt < max_retries:
                delay = _RETRY_BASE_DELAY * (2 ** attempt)
                logger.warning(f"{name} attempt {attempt + 1} failed, retrying in {delay}s",
                             error=str(e))
                await asyncio.sleep(delay)
    logger.error(f"{name} failed after {max_retries + 1} attempts", error=str(last_error))
    raise last_error


# =====================================================
# PostgreSQL (Async) — Primary + Replica
# =====================================================

_pg_pool = None           # Primary (yazma)
_pg_replica_pool = None   # Replica (okuma)
_pg_healthy = False


async def get_pg_pool():
    """Get or create PRIMARY PostgreSQL connection pool (writes)."""
    global _pg_pool, _pg_healthy
    if asyncpg is None:
        raise RuntimeError("asyncpg not installed. Run: pip install asyncpg")
    if _pg_pool is None:
        async def _create():
            return await asyncpg.create_pool(
                host=settings.postgres_host,
                port=settings.postgres_port,
                database=settings.postgres_db,
                user=settings.postgres_user,
                password=settings.postgres_password,
                min_size=settings.db_pool_min,
                max_size=settings.db_pool_max,
                command_timeout=settings.db_command_timeout,
            )
        _pg_pool = await _retry_async(_create, "PostgreSQL primary pool")
        _pg_healthy = True
        logger.info("PostgreSQL primary pool created", host=settings.postgres_host)
    return _pg_pool


async def get_pg_replica_pool():
    """Get or create REPLICA PostgreSQL connection pool (reads)."""
    global _pg_replica_pool
    if asyncpg is None:
        raise RuntimeError("asyncpg not installed")

    replica_host = getattr(settings, 'postgres_replica_host', None)
    replica_port = getattr(settings, 'postgres_replica_port', 5433)

    if not replica_host:
        return await get_pg_pool()

    if _pg_replica_pool is None:
        async def _create():
            return await asyncpg.create_pool(
                host=replica_host,
                port=replica_port,
                database=settings.postgres_db,
                user=settings.postgres_user,
                password=settings.postgres_password,
                min_size=settings.db_pool_min,
                max_size=settings.db_pool_max,
                command_timeout=settings.db_command_timeout,
            )
        try:
            _pg_replica_pool = await _retry_async(_create, "PostgreSQL replica pool")
            logger.info("PostgreSQL replica pool created", host=replica_host)
        except Exception as e:
            logger.warning("Replica unavailable, using primary for reads", error=str(e))
            return await get_pg_pool()
    return _pg_replica_pool


async def close_pg_pool():
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
async def get_pg_connection():
    """Get a PRIMARY PostgreSQL connection (writes)."""
    pool = await get_pg_pool()
    async with pool.acquire() as conn:
        yield conn


@asynccontextmanager
async def get_pg_replica_connection():
    """Get a REPLICA PostgreSQL connection (reads)."""
    pool = await get_pg_replica_pool()
    async with pool.acquire() as conn:
        yield conn


@asynccontextmanager
async def get_pg_transaction():
    """Get a PRIMARY PostgreSQL connection with transaction."""
    pool = await get_pg_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            yield conn


async def pg_execute(query: str, *args) -> str:
    """Execute write query on PRIMARY — pool reconnect ile."""
    global _pg_pool
    max_retries = 2
    for attempt in range(max_retries + 1):
        try:
            async with get_pg_connection() as conn:
                return await conn.execute(query, *args)
        except Exception as e:
            error_str = str(e).lower()
            is_connection_error = any(kw in error_str for kw in [
                'connection', 'closed', 'terminated', 'reset', 'broken',
                'interfaceerror', 'connectiondoesnotexisterror'
            ])
            if attempt < max_retries and is_connection_error:
                logger.warning(f"pg_execute connection error, refreshing pool (attempt {attempt + 1})", error=str(e))
                await close_pg_pool()
                _pg_pool = None
                await asyncio.sleep(1)
                continue
            logger.error("pg_execute failed", query=query[:100], error=str(e))
            raise


async def pg_fetch(query: str, *args):
    """Fetch from REPLICA (read-only) — pool reconnect ile."""
    global _pg_pool, _pg_replica_pool
    max_retries = 2
    for attempt in range(max_retries + 1):
        try:
            async with get_pg_replica_connection() as conn:
                return await conn.fetch(query, *args)
        except Exception as e:
            error_str = str(e).lower()
            is_connection_error = any(kw in error_str for kw in [
                'connection', 'closed', 'terminated', 'reset', 'broken',
                'interfaceerror', 'connectiondoesnotexisterror'
            ])
            if attempt < max_retries and is_connection_error:
                logger.warning(f"pg_fetch connection error, refreshing pool (attempt {attempt + 1})", error=str(e))
                await close_pg_pool()
                _pg_pool = None
                _pg_replica_pool = None
                await asyncio.sleep(1)
                continue
            logger.error("pg_fetch failed", query=query[:100], error=str(e))
            raise


async def pg_fetchrow(query: str, *args):
    """Fetch single row from REPLICA — pool reconnect ile."""
    global _pg_pool, _pg_replica_pool
    max_retries = 2
    for attempt in range(max_retries + 1):
        try:
            async with get_pg_replica_connection() as conn:
                return await conn.fetchrow(query, *args)
        except Exception as e:
            error_str = str(e).lower()
            is_connection_error = any(kw in error_str for kw in [
                'connection', 'closed', 'terminated', 'reset', 'broken',
                'interfaceerror', 'connectiondoesnotexisterror'
            ])
            if attempt < max_retries and is_connection_error:
                logger.warning(f"pg_fetchrow connection error, refreshing pool (attempt {attempt + 1})", error=str(e))
                await close_pg_pool()
                _pg_pool = None
                _pg_replica_pool = None
                await asyncio.sleep(1)
                continue
            logger.error("pg_fetchrow failed", query=query[:100], error=str(e))
            raise


async def pg_fetchval(query: str, *args) -> Any:
    """Fetch single value from REPLICA — pool reconnect ile."""
    global _pg_pool, _pg_replica_pool
    max_retries = 2
    for attempt in range(max_retries + 1):
        try:
            async with get_pg_replica_connection() as conn:
                return await conn.fetchval(query, *args)
        except Exception as e:
            error_str = str(e).lower()
            is_connection_error = any(kw in error_str for kw in [
                'connection', 'closed', 'terminated', 'reset', 'broken',
                'interfaceerror', 'connectiondoesnotexisterror'
            ])
            if attempt < max_retries and is_connection_error:
                logger.warning(f"pg_fetchval connection error, refreshing pool (attempt {attempt + 1})", error=str(e))
                await close_pg_pool()
                _pg_pool = None
                _pg_replica_pool = None
                await asyncio.sleep(1)
                continue
            logger.error("pg_fetchval failed", query=query[:100], error=str(e))
            raise


# =====================================================
# ClickHouse
# =====================================================

import threading

_ch_client = None
_ch_healthy = False
# NOT: clickhouse-connect client'i tek bir HTTP session uzerinden calisiyor ve
# ayni client'a birden fazla thread'den es zamanli sorgu gonderilirse
# "Attempt to execute concurrent queries within the same session" hatasi verir.
# system.py'deki endpoint'ler artik run_in_executor ile thread pool'da paralel
# calisabildiginden (event loop'u bloke etmemek icin), bu lock ile ClickHouse
# cagrilarini seri hale getiriyoruz — event loop yine serbest kalir, sadece
# executor thread'leri birbirini kisa sure bekler.
_ch_lock = threading.Lock()


def get_ch_client():
    global _ch_client, _ch_healthy
    if clickhouse_connect is None:
        raise RuntimeError("clickhouse-connect not installed")
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


def close_ch_client():
    global _ch_client, _ch_healthy
    if _ch_client:
        _ch_client.close()
        _ch_client = None
        _ch_healthy = False
        logger.info("ClickHouse client closed")


def ch_execute(query: str, parameters: Optional[Dict] = None) -> Any:
    """ClickHouse sorgusu — reconnect mekanizması ile."""
    global _ch_client, _ch_healthy
    max_retries = 2
    for attempt in range(max_retries + 1):
        try:
            with _ch_lock:
                client = get_ch_client()
                return client.query(query, parameters=parameters)
        except Exception as e:
            if attempt < max_retries:
                logger.warning(f"ClickHouse query failed, reconnecting (attempt {attempt + 1})", error=str(e))
                _ch_client = None
                _ch_healthy = False
                import time
                time.sleep(1 * (attempt + 1))
                continue
            logger.error("ClickHouse query failed after retries", error=str(e))
            raise


def ch_insert(table: str, data: List[List[Any]], column_names: Optional[List[str]] = None):
    """ClickHouse insert — reconnect mekanizması ile."""
    global _ch_client, _ch_healthy
    max_retries = 2
    for attempt in range(max_retries + 1):
        try:
            with _ch_lock:
                client = get_ch_client()
                client.insert(table, data, column_names=column_names)
                return
        except Exception as e:
            if attempt < max_retries:
                logger.warning(f"ClickHouse insert failed, reconnecting (attempt {attempt + 1})", error=str(e))
                _ch_client = None
                _ch_healthy = False
                import time
                time.sleep(1 * (attempt + 1))
                continue
            logger.error("ClickHouse insert failed after retries", error=str(e))
            raise


def ch_query_df(query: str, parameters: Optional[Dict] = None):
    import polars as pl
    with _ch_lock:
        client = get_ch_client()
        result = client.query_df(query, parameters=parameters)
    return pl.from_pandas(result)


# =====================================================
# Redis (Sentinel-aware HA)
# =====================================================

_redis = None
_redis_healthy = False


async def get_redis():
    """Redis bağlantısı — Sentinel varsa HA, yoksa direct."""
    global _redis, _redis_healthy
    if aioredis is None:
        raise RuntimeError("redis not installed")
    if _redis is None:
        try:
            from .redis_sentinel import get_ha_redis
            _redis = await get_ha_redis()
        except Exception:
            # Fallback: direct connection
            _redis = aioredis.from_url(
                settings.redis_url,
                decode_responses=True,
                max_connections=20,
            )
        _redis_healthy = True
        logger.info("Redis connection created (HA-aware)")
    return _redis


async def close_redis():
    global _redis, _redis_healthy
    if _redis:
        try:
            from .redis_sentinel import close_ha_redis
            await close_ha_redis()
        except Exception:
            logger.warning("Caught Exception in close_redis", exc_info=True)
        try:
            await _redis.close()
        except Exception:
            logger.warning("Caught Exception in close_redis", exc_info=True)
        _redis = None
        _redis_healthy = False
        logger.info("Redis connection closed")


async def redis_get(key: str) -> Optional[str]:
    r = await get_redis()
    return await r.get(key)


async def redis_set(key: str, value: str, ex: Optional[int] = None):
    r = await get_redis()
    await r.set(key, value, ex=ex)


async def redis_delete(key: str):
    r = await get_redis()
    await r.delete(key)


async def redis_hgetall(key: str) -> Dict[str, str]:
    r = await get_redis()
    return await r.hgetall(key)


async def redis_hset(key: str, mapping: Dict[str, str]):
    r = await get_redis()
    await r.hset(key, mapping=mapping)


async def redis_publish(channel: str, message: str):
    r = await get_redis()
    await r.publish(channel, message)


# =====================================================
# Health Check
# =====================================================

async def check_db_health() -> Dict[str, Any]:
    """Check health of all database connections."""
    health = {"postgres": "unavailable", "clickhouse": "unavailable", "redis": "unavailable", "questdb": "unavailable"}

    # PostgreSQL
    try:
        pool = await get_pg_pool()
        async with pool.acquire() as conn:
            result = await conn.fetchval("SELECT 1")
            if result == 1:
                health["postgres"] = "healthy"
    except Exception as e:
        health["postgres"] = f"error: {str(e)[:100]}"

    # ClickHouse
    try:
        client = get_ch_client()
        result = client.query("SELECT 1")
        if result.result_rows and result.result_rows[0][0] == 1:
            health["clickhouse"] = "healthy"
    except Exception as e:
        health["clickhouse"] = f"error: {str(e)[:100]}"

    # Redis
    try:
        r = await get_redis()
        if await r.ping():
            health["redis"] = "healthy"
    except Exception as e:
        health["redis"] = f"error: {str(e)[:100]}"

    # QuestDB
    try:
        if questdb_client._connected:
            health["questdb"] = "healthy"
        else:
            health["questdb"] = "disconnected"
    except Exception as e:
        health["questdb"] = f"error: {str(e)[:100]}"

    return health


# =====================================================
# Lifecycle
# =====================================================

async def init_databases():
    """Initialize all database connections. Graceful on failure."""
    global _pg_healthy, _ch_healthy, _redis_healthy

    try:
        await get_pg_pool()
    except Exception as e:
        _pg_healthy = False
        logger.warning(f"PostgreSQL not available: {e}")

    try:
        get_ch_client()
    except Exception as e:
        _ch_healthy = False
        logger.warning(f"ClickHouse not available: {e}")

    try:
        await get_redis()
    except Exception as e:
        _redis_healthy = False
        logger.warning(f"Redis not available: {e}")

    # QuestDB
    try:
        await questdb_client.connect()
        await questdb_client.ensure_tables()
    except Exception as e:
        logger.warning(f"QuestDB not available: {e}")

    health = await check_db_health()
    for svc, status in health.items():
        if status == "healthy":
            logger.info(f"DB health: {svc} = OK")
        else:
            logger.warning(f"DB health: {svc} = {status}")

    logger.info("Database initialization completed")


async def close_databases():
    await close_pg_pool()
    close_ch_client()
    await close_redis()
    questdb_client.close()
    logger.info("All database connections closed")
