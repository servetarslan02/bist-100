"""ALPHA BIST — Veritabanı Sharding ve Yönlendirme Motoru (Application-Level Sharding).

Ticker tabanlı dinamik PostgreSQL sharding mimarisi:
- Shard 0: A-F hisseleri (AEFES, AGHOL, AKBNK, ...)
- Shard 1: G-M hisseleri (GARAN, HALKB, ISCTR, ...)
- Shard 2: N-Z hisseleri (PETKM, SAHOL, THYAO, ...)

Uygulama seviyesinde bağlantı havuzu yönetimi, cross-shard sorgular,
DuckDB denetim günlüğü ve Polars analitik entegrasyonu sunar.
"""

from __future__ import annotations

import asyncio
import functools
import threading
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Final

import duckdb
import orjson
import polars as pl
import structlog

try:
    import asyncpg
except ImportError:
    asyncpg = None

try:
    from .otel import get_tracer

    tracer = get_tracer("alpha-bist.sharding")
except ImportError:
    from opentelemetry import trace

    tracer = trace.get_tracer("alpha-bist.sharding")

from .config import settings

logger = structlog.get_logger(__name__)

DEFAULT_SHARDING_AUDIT_DB: Final[str] = "data/sharding_audit.duckdb"
DEFAULT_CHECKPOINT_SIZE: Final[str] = "4MB"
DEFAULT_WAL_SIZE: Final[str] = "2MB"


def configure_duckdb_wal(conn: duckdb.DuckDBPyConnection) -> None:
    """DuckDB bağlantısı için WAL ve checkpoint yapılandırmasını uygular."""
    try:
        conn.execute(f"PRAGMA checkpoint_threshold = '{DEFAULT_CHECKPOINT_SIZE}';")
        conn.execute(f"PRAGMA wal_autocheckpoint = '{DEFAULT_WAL_SIZE}';")
    except Exception as exc:
        logger.debug("Sharding DuckDB WAL pragma yapılandırma uyarısı", hata=str(exc))


def to_orjson_bytes(data: Any) -> bytes:
    """Herhangi bir Python nesnesini güvenli ve hızlı şekilde orjson bayt dizisine serileştirir."""
    return orjson.dumps(data, default=str)


def otel_trace(span_name: str) -> Any:
    """Metotları OpenTelemetry span içine alan performans izleme dekoratörü."""

    def decorator(func: Any) -> Any:
        @functools.wraps(func)
        def sync_wrapper(self: Any, *args: Any, **kwargs: Any) -> Any:
            with tracer.start_as_current_span(span_name):
                return func(self, *args, **kwargs)

        @functools.wraps(func)
        async def async_wrapper(self: Any, *args: Any, **kwargs: Any) -> Any:
            with tracer.start_as_current_span(span_name):
                return await func(self, *args, **kwargs)

        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        return sync_wrapper

    return decorator


@dataclass(frozen=True)
class ShardInfo:
    """Tekil bir veritabanı shard'ının yapılandırma ve yönlendirme bilgisi.

    Args:
        shard_id: Shard sayısal kimliği (0, 1, 2, ...).
        name: Shard mantıksal adı (örn. shard_af).
        database: Shard hedef PostgreSQL veritabanı adı.
        range_label: Shard harf aralığı etiketi (örn. 'A-F').
        active: Bağlantı havuzunun aktif olup olmadığı.
    """

    shard_id: int
    name: str
    database: str
    range_label: str
    active: bool = False

    def to_dict(self) -> dict[str, Any]:
        """Modeli sözlük yapısına dönüştürür."""
        return asdict(self)

    def to_orjson_bytes(self) -> bytes:
        """Modeli optimize edilmiş orjson bayt dizisine serileştirir."""
        return orjson.dumps(self.to_dict(), default=str)

    def __repr__(self) -> str:
        return (
            f"ShardInfo(id={self.shard_id}, name='{self.name}', "
            f"db='{self.database}', range='{self.range_label}', active={self.active})"
        )


@dataclass(frozen=True)
class ShardStats:
    """Shard bazlı hisse ve havuz metrikleri."""

    shard_id: int
    name: str
    range_label: str
    ticker_count: int
    sample_tickers: list[str]
    pool_active: bool

    def to_dict(self) -> dict[str, Any]:
        """Modeli sözlük yapısına dönüştürür."""
        return asdict(self)

    def to_orjson_bytes(self) -> bytes:
        """Modeli orjson bayt dizisine dönüştürür."""
        return orjson.dumps(self.to_dict(), default=str)

    def __repr__(self) -> str:
        return (
            f"ShardStats(id={self.shard_id}, name='{self.name}', "
            f"tickers={self.ticker_count}, pool_active={self.pool_active})"
        )


class ShardRouter:
    """Hisse senedi (ticker) bazlı uygulama seviyesinde veritabanı shard yönlendiricisi.

    Birden çok PostgreSQL veritabanı arasında yatay ölçekleme, dinamik havuz yönetimi,
    cross-shard analitik sorgulama, DuckDB denetim kaydı ve Polars veri ihracı sağlar.
    """

    # Shard varsayılan tanımları
    SHARDS: dict[int, dict[str, str]] = {
        0: {"name": "shard_af", "db": "alpha_bist_af", "range": "A-F"},
        1: {"name": "shard_gm", "db": "alpha_bist_gm", "range": "G-M"},
        2: {"name": "shard_nz", "db": "alpha_bist_nz", "range": "N-Z"},
    }

    def __init__(self, duckdb_path: str = DEFAULT_SHARDING_AUDIT_DB) -> None:
        """Shard yönlendiriciyi başlatır ve eşzamanlı erişim kilitlerini tanımlar.

        Args:
            duckdb_path: Sharding denetim günlükleri için DuckDB dosya yolu veya hafıza veritabanı.
        """
        self._lock = threading.RLock()
        self._pools: dict[int, Any] = {}
        self._enabled: bool = False
        self._duckdb_path = duckdb_path
        if self._duckdb_path != ":memory:":
            Path(self._duckdb_path).parent.mkdir(parents=True, exist_ok=True)
        self._duckdb_con = duckdb.connect(self._duckdb_path)
        configure_duckdb_wal(self._duckdb_con)
        self._init_duckdb()

    def _init_duckdb(self) -> None:
        """DuckDB üzerinde sharding sorgu ve rota denetim tablosunu hazırlar."""
        with self._lock:
            try:
                self._duckdb_con.execute(
                    """
                    CREATE TABLE IF NOT EXISTS sharding_query_audit (
                        id BIGINT PRIMARY KEY,
                        ticker VARCHAR,
                        shard_id INTEGER,
                        query_type VARCHAR,
                        elapsed_ms DOUBLE,
                        recorded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                    """
                )
                self._duckdb_con.execute("CREATE SEQUENCE IF NOT EXISTS seq_sharding_audit_id START 1")
            except Exception as e:
                logger.error("DuckDB sharding denetim tablosu olusturulamadi", hata=str(e))

    def _record_audit(self, ticker: str, shard_id: int, query_type: str, elapsed_ms: float) -> None:
        """Sorgu yönlendirme operasyonunu DuckDB denetim günlüğüne yazar."""
        with self._lock:
            try:
                self._duckdb_con.execute(
                    """
                    INSERT INTO sharding_query_audit (id, ticker, shard_id, query_type, elapsed_ms)
                    VALUES (nextval('seq_sharding_audit_id'), ?, ?, ?, ?)
                    """,
                    [ticker, shard_id, query_type, elapsed_ms],
                )
            except Exception as e:
                logger.warning("Sharding denetim kaydi DuckDB'ye yazilamadi", hata=str(e))

    @property
    def enabled(self) -> bool:
        """Sharding mekanizmasının devrede olup olmadığını döndürür."""
        with self._lock:
            return self._enabled

    def _get_shard_id(self, ticker: str) -> int:
        """Hisse sembolünün baş harfine göre deterministik shard ID belirler.

        Args:
            ticker: BIST hisse sembolü (örn. 'THYAO').

        Returns:
            int: 0 (A-F), 1 (G-M) veya 2 (N-Z).
        """
        if not ticker or not isinstance(ticker, str):
            return 0

        clean_ticker = ticker.strip().upper()
        if not clean_ticker:
            return 0

        # Türkçe karakter duyarlılığı normalizasyonu
        first_char = clean_ticker[0]
        if first_char in ("Ç",):
            first_char = "C"
        elif first_char in ("Ğ",):
            first_char = "G"
        elif first_char in ("İ", "I"):
            first_char = "I"
        elif first_char in ("Ö",):
            first_char = "O"
        elif first_char in ("Ş",):
            first_char = "S"
        elif first_char in ("Ü",):
            first_char = "U"

        if first_char <= "F":
            return 0
        if first_char <= "M":
            return 1
        return 2

    def get_shard(self, ticker: str) -> int:
        """Hisse sembolü için hedef shard ID değerini döndürür."""
        return self._get_shard_id(ticker)

    def get_shard_info(self, ticker: str) -> ShardInfo:
        """Hisse sembolü için detaylı shard yapılandırma modelini döndürür."""
        shard_id = self._get_shard_id(ticker)
        raw_shard = self.SHARDS.get(shard_id, self.SHARDS[0])
        with self._lock:
            is_active = shard_id in self._pools

        return ShardInfo(
            shard_id=shard_id,
            name=raw_shard["name"],
            database=raw_shard["db"],
            range_label=raw_shard["range"],
            active=is_active,
        )

    def register_mock_pool(self, shard_id: int, pool: Any) -> None:
        """Testler ve harici enjeksiyon için mock bağlantı havuzu kaydeder."""
        with self._lock:
            self._pools[shard_id] = pool
            self._enabled = True

    async def init(self) -> None:
        """Shard bağlantı havuzlarını başlatır. Sharding kapalıysa birincil veritabanına düşer."""
        if not getattr(settings, "sharding_enabled", False):
            logger.info("Sharding devre disi, birincil tekil veritabani kullanilacak")
            return

        if asyncpg is None:
            logger.warning("asyncpg kurulu degil, veritabani sharding baslatilamadi")
            return

        created_pools: dict[int, Any] = {}
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
                created_pools[shard_id] = pool
                logger.info("Shard baglanti havuzu olusturuldu", shard_id=shard_id, db=shard_info["db"])
            except Exception as e:
                logger.warning("Shard havuzu olusturulamadi", shard_id=shard_id, hata=str(e))

        with self._lock:
            self._pools.update(created_pools)
            if self._pools:
                self._enabled = True
                logger.info("Veritabani sharding aktiflestirildi", aktif_shard_sayisi=len(self._pools))

    async def close(self) -> None:
        """Açık olan tüm shard veritabanı bağlantı havuzlarını güvenle kapatır."""
        with self._lock:
            pools_to_close = list(self._pools.items())
            self._pools.clear()
            self._enabled = False

        for shard_id, pool in pools_to_close:
            try:
                if hasattr(pool, "close"):
                    if asyncio.iscoroutinefunction(pool.close):
                        await pool.close()
                    else:
                        pool.close()
            except Exception as e:
                logger.warning("Shard havuzu kapatilirken hata olustu", shard_id=shard_id, hata=str(e))

        logger.info("Tum shard baglanti havuzlari kapatildi")

    async def get_pool(self, ticker: str) -> Any:
        """Belirtilen hisse senedi için ilgili shard bağlantı havuzunu döndürür.

        Sharding devre dışıysa veya ilgili shard bulunamazsa sistemin ana PG havuzuna yönlendirir.
        """
        with self._lock:
            if not self._enabled:
                from .database import get_pg_pool

                return await get_pg_pool()

            shard_id = self._get_shard_id(ticker)
            pool = self._pools.get(shard_id)
            if pool is not None:
                return pool

        from .database import get_pg_pool

        return await get_pg_pool()

    @otel_trace("sharding.execute")
    async def execute(self, ticker: str, query: str, *args: Any) -> str:
        """Hissenin ait olduğu shard üzerinde yazma/güncelleme (DML) sorgusu çalıştırır."""
        t0 = time.perf_counter()
        shard_id = self._get_shard_id(ticker)
        pool = await self.get_pool(ticker)
        async with pool.acquire() as conn:
            result = await conn.execute(query, *args)
            elapsed = (time.perf_counter() - t0) * 1000.0
            self._record_audit(ticker, shard_id, "EXECUTE", elapsed)
            return str(result)

    @otel_trace("sharding.fetch")
    async def fetch(self, ticker: str, query: str, *args: Any) -> list[Any]:
        """Hissenin ait olduğu shard'dan birden fazla satır okuma sorgusu çalıştırır."""
        t0 = time.perf_counter()
        shard_id = self._get_shard_id(ticker)
        pool = await self.get_pool(ticker)
        async with pool.acquire() as conn:
            rows = await conn.fetch(query, *args)
            elapsed = (time.perf_counter() - t0) * 1000.0
            self._record_audit(ticker, shard_id, "FETCH", elapsed)
            return list(rows)

    @otel_trace("sharding.fetchrow")
    async def fetchrow(self, ticker: str, query: str, *args: Any) -> Any:
        """Hissenin ait olduğu shard'dan tek bir kayıt çeker."""
        t0 = time.perf_counter()
        shard_id = self._get_shard_id(ticker)
        pool = await self.get_pool(ticker)
        async with pool.acquire() as conn:
            row = await conn.fetchrow(query, *args)
            elapsed = (time.perf_counter() - t0) * 1000.0
            self._record_audit(ticker, shard_id, "FETCHROW", elapsed)
            return row

    @otel_trace("sharding.fetchval")
    async def fetchval(self, ticker: str, query: str, *args: Any) -> Any:
        """Hissenin ait olduğu shard'dan tek bir skaler değer çeker."""
        t0 = time.perf_counter()
        shard_id = self._get_shard_id(ticker)
        pool = await self.get_pool(ticker)
        async with pool.acquire() as conn:
            val = await conn.fetchval(query, *args)
            elapsed = (time.perf_counter() - t0) * 1000.0
            self._record_audit(ticker, shard_id, "FETCHVAL", elapsed)
            return val

    @otel_trace("sharding.query_all")
    async def query_all(self, query: str, *args: Any) -> dict[int, list[Any]]:
        """Tüm aktif shard'larda paralel/sıralı sorgu çalıştırır ve shard ID bazlı satırları döndürür."""
        t0 = time.perf_counter()
        with self._lock:
            active_pools = list(self._pools.items())

        results: dict[int, list[Any]] = {}
        for shard_id, pool in active_pools:
            try:
                async with pool.acquire() as conn:
                    rows = await conn.fetch(query, *args)
                    results[shard_id] = list(rows)
            except Exception as e:
                logger.error("Shard sorgusu basarisiz oldu", shard_id=shard_id, hata=str(e))
                results[shard_id] = []

        elapsed = (time.perf_counter() - t0) * 1000.0
        self._record_audit("ALL", -1, "QUERY_ALL", elapsed)
        return results

    @otel_trace("sharding.aggregate")
    async def aggregate(self, query: str, *args: Any) -> Any:
        """Tüm shard'larda toplulaştırma (SUM, COUNT vb.) sorgusu çalıştırır ve sonuçları birleştirir."""
        all_results = await self.query_all(query, *args)
        combined: list[Any] = []
        for _shard_id, rows in all_results.items():
            combined.extend(rows)

        if not combined:
            return None

        if len(combined) == 1:
            return combined[0]

        return combined

    def get_all_tickers_for_shard(self, shard_id: int) -> list[str]:
        """Belirtilen shard'a düşen tüm evren sembollerini filtreler."""
        try:
            from ..ingestion.bist_universe import get_bist_universe

            universe = get_bist_universe()
        except ImportError:
            universe = ["AEFES", "AKBNK", "GARAN", "HALKB", "ISCTR", "PETKM", "SAHOL", "THYAO"]

        return [t for t in universe if self._get_shard_id(t) == shard_id]

    def get_shard_stats(self) -> dict[str, ShardStats]:
        """Tüm shard'ların doluluk ve durum istatistiklerini hesaplar."""
        try:
            from ..ingestion.bist_universe import get_bist_universe

            universe = get_bist_universe()
        except ImportError:
            universe = ["AEFES", "AKBNK", "GARAN", "HALKB", "ISCTR", "PETKM", "SAHOL", "THYAO"]

        stats: dict[str, ShardStats] = {}
        with self._lock:
            for shard_id, info in self.SHARDS.items():
                tickers = [t for t in universe if self._get_shard_id(t) == shard_id]
                stats[info["name"]] = ShardStats(
                    shard_id=shard_id,
                    name=info["name"],
                    range_label=info["range"],
                    ticker_count=len(tickers),
                    sample_tickers=tickers[:10],
                    pool_active=shard_id in self._pools,
                )
        return stats

    def export_shards_to_polars(self) -> pl.DataFrame:
        """Shard yapılandırması ve durumunu Polars DataFrame olarak dışa aktarır."""
        stats = self.get_shard_stats()
        rows = [
            {
                "shard_id": s.shard_id,
                "name": s.name,
                "range_label": s.range_label,
                "ticker_count": s.ticker_count,
                "pool_active": s.pool_active,
            }
            for s in stats.values()
        ]
        if not rows:
            return pl.DataFrame(
                schema={
                    "shard_id": pl.Int64,
                    "name": pl.Utf8,
                    "range_label": pl.Utf8,
                    "ticker_count": pl.Int64,
                    "pool_active": pl.Boolean,
                }
            )
        return pl.DataFrame(rows)

    def export_sharding_audit_to_polars(self, limit: int = 1000) -> pl.DataFrame:
        """DuckDB üzerindeki sorgu yönlendirme denetim kayıtlarını Polars DataFrame olarak döndürür."""
        with self._lock:
            try:
                df = self._duckdb_con.execute(
                    "SELECT id, ticker, shard_id, query_type, elapsed_ms, recorded_at "
                    "FROM sharding_query_audit ORDER BY id DESC LIMIT ?",
                    [limit],
                ).pl()
                return df
            except Exception as e:
                logger.error("DuckDB denetim kayitlari Polars'a aktarilamadi", hata=str(e))
                return pl.DataFrame(
                    schema={
                        "id": pl.Int64,
                        "ticker": pl.Utf8,
                        "shard_id": pl.Int64,
                        "query_type": pl.Utf8,
                        "elapsed_ms": pl.Float64,
                        "recorded_at": pl.Datetime,
                    }
                )

    def clear_audit_duckdb(self) -> None:
        """DuckDB üzerindeki sorgu yönlendirme denetim tablosunu temizler."""
        with self._lock:
            try:
                self._duckdb_con.execute("DELETE FROM sharding_query_audit;")
            except Exception as e:
                logger.error("DuckDB sharding denetim kayitlari temizlenemedi", hata=str(e))

    def __repr__(self) -> str:
        with self._lock:
            active_count = len(self._pools)
            enabled = self._enabled
        return f"ShardRouter(enabled={enabled}, active_pools={active_count}, shards={len(self.SHARDS)})"


# Singleton instance
shard_router = ShardRouter()


async def init_sharding() -> None:
    """Veritabanı sharding bağlantı havuzlarını başlatır."""
    await shard_router.init()


async def close_sharding() -> None:
    """Veritabanı sharding bağlantı havuzlarını güvenle sonlandırır."""
    await shard_router.close()


def read_sharding_audit_from_duckdb(
    duckdb_path: str = DEFAULT_SHARDING_AUDIT_DB,
    limit: int = 1000,
) -> pl.DataFrame:
    """Doğrudan DuckDB dosyasından sharding denetim kayıtlarını okur."""
    empty_df = pl.DataFrame(
        schema={
            "id": pl.Int64,
            "ticker": pl.Utf8,
            "shard_id": pl.Int64,
            "query_type": pl.Utf8,
            "elapsed_ms": pl.Float64,
            "recorded_at": pl.Datetime,
        }
    )
    p = Path(duckdb_path)
    if not p.exists():
        return empty_df
    try:
        conn = duckdb.connect(str(p), read_only=True)
        try:
            query = f"SELECT id, ticker, shard_id, query_type, elapsed_ms, recorded_at FROM sharding_query_audit ORDER BY id DESC LIMIT {int(limit)}"
            return conn.execute(query).pl()
        finally:
            conn.close()
    except Exception as e:
        logger.error("DuckDB dogrudan sharding denetim okuma hatasi", yol=duckdb_path, hata=str(e))
        return empty_df


def clear_sharding_audit_duckdb(
    duckdb_path: str = DEFAULT_SHARDING_AUDIT_DB,
) -> None:
    """Doğrudan DuckDB dosyasındaki sharding denetim tablosunu temizler."""
    p = Path(duckdb_path)
    if not p.exists():
        return
    try:
        conn = duckdb.connect(str(p), read_only=False)
        configure_duckdb_wal(conn)
        try:
            conn.execute("DELETE FROM sharding_query_audit;")
        finally:
            conn.close()
    except Exception as e:
        logger.error("DuckDB dogrudan sharding denetim temizleme hatasi", yol=duckdb_path, hata=str(e))


__all__ = [
    "DEFAULT_CHECKPOINT_SIZE",
    "DEFAULT_SHARDING_AUDIT_DB",
    "DEFAULT_WAL_SIZE",
    "ShardInfo",
    "ShardRouter",
    "ShardStats",
    "clear_sharding_audit_duckdb",
    "close_sharding",
    "configure_duckdb_wal",
    "init_sharding",
    "otel_trace",
    "read_sharding_audit_from_duckdb",
    "shard_router",
    "to_orjson_bytes",
]
