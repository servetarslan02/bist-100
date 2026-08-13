"""ALPHA BIST - Database Connections (PostgreSQL, ClickHouse, Redis)"""

import asyncio
from contextlib import asynccontextmanager
from typing import AsyncGenerator, Optional, Any, List, Dict
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

logger = structlog.get_logger()

# =====================================================
# PostgreSQL (Async)
# =====================================================

_pg_pool: Optional[asyncpg.Pool] = None


async def get_pg_pool():
    """Get or create PostgreSQL connection pool."""
    global _pg_pool
    if asyncpg is None:
        raise RuntimeError("asyncpg not installed. Run: pip install asyncpg")
    if _pg_pool is None:
        _pg_pool = await asyncpg.create_pool(
            host=settings.postgres_host,
            port=settings.postgres_port,
            database=settings.postgres_db,
            user=settings.postgres_user,
            password=settings.postgres_password,
            min_size=5,
            max_size=20,
            command_timeout=30,
        )
        logger.info("PostgreSQL pool created", host=settings.postgres_host)
    return _pg_pool


async def close_pg_pool():
    """Close PostgreSQL connection pool."""
    global _pg_pool
    if _pg_pool:
        await _pg_pool.close()
        _pg_pool = None
        logger.info("PostgreSQL pool closed")


@asynccontextmanager
async def get_pg_connection() -> AsyncGenerator[asyncpg.Connection, None]:
    """Get a PostgreSQL connection from the pool."""
    pool = await get_pg_pool()
    async with pool.acquire() as conn:
        yield conn


async def pg_execute(query: str, *args) -> str:
    """Execute a PostgreSQL query."""
    async with get_pg_connection() as conn:
        return await conn.execute(query, *args)


async def pg_fetch(query: str, *args) -> List[asyncpg.Record]:
    """Fetch rows from PostgreSQL."""
    async with get_pg_connection() as conn:
        return await conn.fetch(query, *args)


async def pg_fetchrow(query: str, *args) -> Optional[asyncpg.Record]:
    """Fetch a single row from PostgreSQL."""
    async with get_pg_connection() as conn:
        return await conn.fetchrow(query, *args)


async def pg_fetchval(query: str, *args) -> Any:
    """Fetch a single value from PostgreSQL."""
    async with get_pg_connection() as conn:
        return await conn.fetchval(query, *args)


# =====================================================
# ClickHouse
# =====================================================

_ch_client: Optional[clickhouse_connect.driver.Client] = None


def get_ch_client():
    """Get or create ClickHouse client."""
    global _ch_client
    if clickhouse_connect is None:
        raise RuntimeError("clickhouse-connect not installed. Run: pip install clickhouse-connect")
    if _ch_client is None:
        _ch_client = clickhouse_connect.get_client(
            host=settings.clickhouse_host,
            port=settings.clickhouse_http_port,
            username=settings.clickhouse_user,
            password=settings.clickhouse_password,
            database=settings.clickhouse_db,
        )
        logger.info("ClickHouse client created", host=settings.clickhouse_host)
    return _ch_client


def close_ch_client():
    """Close ClickHouse client."""
    global _ch_client
    if _ch_client:
        _ch_client.close()
        _ch_client = None
        logger.info("ClickHouse client closed")


def ch_execute(query: str, parameters: Optional[Dict] = None) -> Any:
    """Execute a ClickHouse query."""
    client = get_ch_client()
    return client.query(query, parameters=parameters)


def ch_insert(table: str, data: List[List[Any]], column_names: Optional[List[str]] = None):
    """Insert data into ClickHouse."""
    client = get_ch_client()
    client.insert(table, data, column_names=column_names)


def ch_query_df(query: str, parameters: Optional[Dict] = None):
    """Execute a ClickHouse query and return as Polars DataFrame."""
    import polars as pl
    client = get_ch_client()
    result = client.query_df(query, parameters=parameters)
    return pl.from_pandas(result)


# =====================================================
# Redis
# =====================================================

_redis: Optional[aioredis.Redis] = None


async def get_redis():
    """Get or create Redis connection."""
    global _redis
    if aioredis is None:
        raise RuntimeError("redis not installed. Run: pip install redis")
    if _redis is None:
        _redis = aioredis.from_url(
            settings.redis_url,
            decode_responses=True,
            max_connections=20,
        )
        logger.info("Redis connection created", host=settings.redis_host)
    return _redis


async def close_redis():
    """Close Redis connection."""
    global _redis
    if _redis:
        await _redis.close()
        _redis = None
        logger.info("Redis connection closed")


async def redis_get(key: str) -> Optional[str]:
    """Get a value from Redis."""
    r = await get_redis()
    return await r.get(key)


async def redis_set(key: str, value: str, ex: Optional[int] = None):
    """Set a value in Redis."""
    r = await get_redis()
    await r.set(key, value, ex=ex)


async def redis_delete(key: str):
    """Delete a key from Redis."""
    r = await get_redis()
    await r.delete(key)


async def redis_hgetall(key: str) -> Dict[str, str]:
    """Get all fields of a hash from Redis."""
    r = await get_redis()
    return await r.hgetall(key)


async def redis_hset(key: str, mapping: Dict[str, str]):
    """Set fields of a hash in Redis."""
    r = await get_redis()
    await r.hset(key, mapping=mapping)


async def redis_publish(channel: str, message: str):
    """Publish a message to a Redis channel."""
    r = await get_redis()
    await r.publish(channel, message)


# =====================================================
# Lifecycle
# =====================================================

async def init_databases():
    """Initialize all database connections."""
    await get_pg_pool()
    get_ch_client()
    await get_redis()
    logger.info("All database connections initialized")


async def close_databases():
    """Close all database connections."""
    await close_pg_pool()
    close_ch_client()
    await close_redis()
    logger.info("All database connections closed")
