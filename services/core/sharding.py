"""ALPHA BIST — Database Sharding (Application-Level)

Ticker-based sharding: hisse adına göre veriyi birden fazla PostgreSQL
database'e dağıtır. Büyük veri setlerinde okuma performansını artırır.

Strateji:
- Shard 0: A-F tickers (AEFES, AGHOL, AKBNK, ...)
- Shard 1: G-M tickers (GARAN, HALKB, ISCTR, ...)
- Shard 2: N-Z tickers (PETKM, SAHOL, THYAO, ...)

Her shard bağımsız PostgreSQL database'i.
Uygulama seviyesinde routing — proxy gerektirmez.

Kullanım:
    from services.core.sharding import shard_router

    # Doğru shard'ı bul
    shard = shard_router.get_shard("THYAO")  # → shard 2

    # Shard'a göre connection al
    pool = await shard_router.get_pool("THYAO")

    # Tüm shard'larda sorgu
    results = await shard_router.query_all("SELECT * FROM prices WHERE ...")

    # Cross-shard aggregation
    total = await shard_router.aggregate("SELECT SUM(volume) FROM prices")
"""

from typing import Any

import structlog

try:
    import asyncpg
except ImportError:
    asyncpg = None

from .config import settings

import structlog
import functools
from opentelemetry import trace

logger = structlog.get_logger(__name__)
tracer = trace.get_tracer("alpha-bist.sharding")

def otel_trace(span_name: str):
    """Decorator to wrap a method in an OTel span."""
    def decorator(func):
        @functools.wraps(func)
        def wrapper(self, *args, **kwargs):
            with tracer.start_as_current_span(span_name):
                return func(self, *args, **kwargs)
        return wrapper
    return decorator


class ShardRouter:
    """Ticker-based database shard router."""

    # Shard tanımları
    SHARDS = {
        0: {"name": "shard_af", "db": "alpha_bist_af", "range": "A-F"},
        1: {"name": "shard_gm", "db": "alpha_bist_gm", "range": "G-M"},
        2: {"name": "shard_nz", "db": "alpha_bist_nz", "range": "N-Z"},
    }

    def __init__(self):
        self._pools: dict[int, Any] = {}
        self._enabled = False

    @property
    def enabled(self) -> bool:
        """Sharding aktif mi?"""
        return self._enabled

    def _get_shard_id(self, ticker: str) -> int:
        """Ticker'dan shard ID hesapla."""
        if not ticker:
            return 0
        first = ticker[0].upper()
        if first <= "F":
            return 0
        elif first <= "M":
            return 1
        else:
            return 2

    def get_shard(self, ticker: str) -> int:
        """Ticker için shard ID döndür."""
        return self._get_shard_id(ticker)

    def get_shard_info(self, ticker: str) -> dict[str, Any]:
        """Ticker için shard bilgisi döndür."""
        shard_id = self._get_shard_id(ticker)
        return {
            "shard_id": shard_id,
            "ticker": ticker,
            "database": self.SHARDS[shard_id]["db"],
            "range": self.SHARDS[shard_id]["range"],
        }

    async def init(self):
        """Shard pool'larını başlat. Sharding devre dışıysa primary'ye düş."""
        if not getattr(settings, "sharding_enabled", False):
            logger.info("Sharding disabled, using single database")
            return

        if asyncpg is None:
            logger.warning("asyncpg not installed, sharding disabled")
            return

        for shard_id, shard_info in self.SHARDS.items():
            try:
                pool = await asyncpg.create_pool(
                    host=settings.postgres_host,
                    port=settings.postgres_port,
                    database=shard_info["db"],
                    user=settings.postgres_user,
                    password=settings.postgres_password,
                    min_size=2,
                    max_size=10,
                )
                self._pools[shard_id] = pool
                logger.info("Shard pool created", shard_id=shard_id, db=shard_info["db"])
            except Exception as e:
                logger.warning("Shard pool creation failed", shard_id=shard_id, error=str(e))

        if self._pools:
            self._enabled = True
            logger.info("Sharding enabled", shards=len(self._pools))

    async def close(self):
        """Tüm shard pool'larını kapat."""
        for _shard_id, pool in self._pools.items():
            try:
                await pool.close()
            except Exception:
                logger.warning("Caught Exception in close", exc_info=True)
        self._pools.clear()
        self._enabled = False
        logger.info("Shard pools closed")

    async def get_pool(self, ticker: str):
        """Ticker için doğru pool'u döndür."""
        if not self._enabled:
            from .database import get_pg_pool

            return await get_pg_pool()

        shard_id = self._get_shard_id(ticker)
        pool = self._pools.get(shard_id)
        if not pool:
            from .database import get_pg_pool

            return await get_pg_pool()
        return pool

    @otel_trace("sharding.execute")
    async def execute(self, ticker: str, query: str, *args) -> str:
        """Ticker'ın shard'ında write query çalıştır."""
        pool = await self.get_pool(ticker)
        async with pool.acquire() as conn:
            return await conn.execute(query, *args)

    @otel_trace("sharding.fetch")
    async def fetch(self, ticker: str, query: str, *args) -> list:
        """Ticker'ın shard'ından read query çalıştır."""
        pool = await self.get_pool(ticker)
        async with pool.acquire() as conn:
            return await conn.fetch(query, *args)

    @otel_trace("sharding.fetchrow")
    async def fetchrow(self, ticker: str, query: str, *args):
        """Ticker'ın shard'ından tek satır çek."""
        pool = await self.get_pool(ticker)
        async with pool.acquire() as conn:
            return await conn.fetchrow(query, *args)

    @otel_trace("sharding.fetchval")
    async def fetchval(self, ticker: str, query: str, *args) -> Any:
        """Ticker'ın shard'ından tek değer çek."""
        pool = await self.get_pool(ticker)
        async with pool.acquire() as conn:
            return await conn.fetchval(query, *args)

    @otel_trace("sharding.query_all")
    async def query_all(self, query: str, *args) -> dict[int, list]:
        """Tüm shard'larda sorgu çalıştır. {shard_id: rows} döndür."""
        results = {}
        for shard_id, pool in self._pools.items():
            try:
                async with pool.acquire() as conn:
                    rows = await conn.fetch(query, *args)
                    results[shard_id] = rows
            except Exception as e:
                logger.error("Shard query failed", shard_id=shard_id, error=str(e))
                results[shard_id] = []
        return results

    @otel_trace("sharding.aggregate")
    async def aggregate(self, query: str, *args) -> Any:
        """Tüm shard'larda aggregation çalıştır ve sonuçları birleştir."""
        all_results = await self.query_all(query, *args)

        # Sonuçları birleştir (SUM, COUNT, AVG için)
        combined = []
        for _shard_id, rows in all_results.items():
            combined.extend(rows)

        if not combined:
            return None

        # Tek satır aggregation sonucu
        if len(combined) == 1:
            return combined[0]

        return combined

    def get_all_tickers_for_shard(self, shard_id: int) -> list[str]:
        """Shard'daki tüm ticker'ları döndür."""
        from ..ingestion.bist_universe import get_bist_universe

        universe = get_bist_universe()
        return [t for t in universe if self._get_shard_id(t) == shard_id]

    def get_shard_stats(self) -> dict[str, Any]:
        """Shard istatistikleri."""
        from ..ingestion.bist_universe import get_bist_universe

        universe = get_bist_universe()

        stats = {}
        for shard_id, info in self.SHARDS.items():
            tickers = [t for t in universe if self._get_shard_id(t) == shard_id]
            stats[info["name"]] = {
                "shard_id": shard_id,
                "range": info["range"],
                "ticker_count": len(tickers),
                "tickers": tickers[:10],  # İlk 10
                "pool_active": shard_id in self._pools,
            }
        return stats


# Singleton
shard_router = ShardRouter()


async def init_sharding():
    """Sharding'i başlat."""
    await shard_router.init()


async def close_sharding():
    """Sharding'i kapat."""
    await shard_router.close()
