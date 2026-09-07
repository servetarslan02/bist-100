"""ALPHA BIST — Kurumsal Veritabanı ve Bağlantı Havuzu Yöneticisi v3.0 (Enterprise-Grade)

Sistem Veritabanı Mimarisi (GEMINI.md Standartları):
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
1. PostgreSQL + TimescaleDB:
   - Port: 5432 (Primary / Yazma) & 5433 (Replica / Okuma)
   - Sürücü: asyncpg, Read/Write ayrımı ve DatabaseRouter
2. ClickHouse:
   - Port: 8123 (HTTP) & 9002 (Native)
   - Sürücü: clickhouse-connect, thread-local client, sıfır kopyalı Arrow -> Polars dönüşümü
3. DuckDB:
   - Yerel gömülü (in-process) OLAP ve durum depolama motoru (duckdb>=1.3.0)
   - Sıfır kopyalı Polars entegrasyonu, 0-byte bozuk dosya guard'ı, thread-safe bağlantı yönetimi
4. Redis 8 + Sentinel:
   - Port: 6379 (Redis) & 26379 (Sentinel)
   - Sürücü: redis.asyncio, High Availability (HA) Sentinel desteği
5. QuestDB:
   - ILP / HTTP tick ve orderbook istemcisi
6. Dayanıklılık ve İzlenebilirlik:
   - Exponential Backoff + Jitter retry mimarisi
   - OpenTelemetry (OTel) span ve metrik enstrümantasyonu
   - Kesintisiz Türkçe loglama (structlog) ve fail-closed hata yönetimi
"""

from __future__ import annotations

import asyncio
import contextlib
import random
import threading
import time
from contextlib import asynccontextmanager, contextmanager
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator, Generator

import duckdb
import polars as pl
import structlog
from opentelemetry import metrics, trace

# ─── Opsiyonel Sürücüler ──────────────────────────────────────────────────────
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

from .config import settings
from .questdb_client import questdb_client

logger = structlog.get_logger(__name__)
tracer = trace.get_tracer("alpha-bist.database")
meter = metrics.get_meter("alpha-bist.database")

# ─── Sabitler ─────────────────────────────────────────────────────────────────
DEFAULT_MAX_RETRIES: int = 3
DEFAULT_RETRY_BASE_DELAY: float = 1.0  # saniye
DEFAULT_REPLICA_LAG_THRESHOLD_SECONDS: float = 5.0
DEFAULT_DUCKDB_PATH: str = "data/local_state.duckdb"

# ─── OpenTelemetry Metrikleri ─────────────────────────────────────────────────
_pg_pool: asyncpg.Pool | None = None  # type: ignore[type-arg]
_pg_replica_pool: asyncpg.Pool | None = None  # type: ignore[type-arg]
_pg_healthy: bool = False
_pg_pool_lock: asyncio.Lock = asyncio.Lock()
_pg_replica_pool_lock: asyncio.Lock = asyncio.Lock()


def _observe_pg_pool_size(options: Any = None) -> list[metrics.Observation]:
    """OpenTelemetry için PostgreSQL bağlantı havuzu boyutunu gözlemler."""
    if _pg_pool is not None:
        try:
            return [metrics.Observation(_pg_pool.get_size(), {"pool": "primary"})]
        except Exception:
            return []
    return []


_pg_pool_size_gauge = meter.create_observable_gauge(
    "alpha.db.pg.pool.size",
    callbacks=[_observe_pg_pool_size],
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
    """İstisnanın bir veritabanı bağlantı hatası olup olmadığını kontrol eder.

    Args:
        exc: İncelenecek istisna nesnesi.

    Returns:
        bool: Bağlantı hatası ise True, aksi halde False.
    """
    msg = str(exc).lower()
    return any(kw in msg for kw in _CONN_ERROR_KEYWORDS)


async def _retry_async(
    coro_factory: Any,
    name: str,
    max_retries: int = DEFAULT_MAX_RETRIES,
) -> Any:
    """Exponential Backoff ve Jitter ile asenkron yeniden deneme mekanizması.

    Args:
        coro_factory: Her denemede yeni coroutine üreten çağrılabilir nesne.
        name: Log ve metrik etiketi için operasyon adı.
        max_retries: Maksimum yeniden deneme sayısı.

    Returns:
        Any: Başarılı operasyonun sonucu.

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
                err_msg = str(exc)
                if (
                    "getaddrinfo failed" in err_msg
                    or "NameResolutionError" in err_msg
                    or "Failed to resolve" in err_msg
                    or "Name or service not known" in err_msg
                    or "gaierror" in err_msg
                ):
                    logger.warning(
                        "db_sunucu_adresi_cozulemedi_tekrar_deneme_atlanıyor",
                        operation=name,
                        error=err_msg,
                    )
                    break

                # Jitter: rastgele zaman kaydırması ile herd effect engellenir
                base = DEFAULT_RETRY_BASE_DELAY * (2**attempt)
                jitter = random.uniform(0, base * 0.3)
                delay = base + jitter
                _db_retry_counter.add(1, {"operation": name, "attempt": str(attempt + 1)})
                logger.warning(
                    "db_operasyonu_tekrar_deneniyor",
                    operation=name,
                    attempt=attempt + 1,
                    delay_seconds=round(delay, 2),
                    error=str(exc),
                )
                await asyncio.sleep(delay)

    _db_error_counter.add(1, {"operation": name})
    logger.error(
        "db_operasyonu_tum_denemelerden_sonra_basarisiz_oldu",
        operation=name,
        attempts=max_retries + 1,
        error=str(last_error),
    )
    raise last_error  # type: ignore[misc]


# ─── PostgreSQL Primary & Replica Pool ────────────────────────────────────────


async def get_pg_pool() -> asyncpg.Pool:  # type: ignore[type-arg]
    """PRIMARY PostgreSQL bağlantı havuzunu döndürür (yazma operasyonları).

    İlk çağrıda havuzu oluşturur; asyncio.Lock ile eşzamanlı erişim yarışını engeller.

    Returns:
        asyncpg.Pool: PostgreSQL birincil bağlantı havuzu.

    Raises:
        RuntimeError: asyncpg paketi kurulu değilse.
    """
    global _pg_pool, _pg_healthy
    if asyncpg is None:
        raise RuntimeError("asyncpg kurulu değil. Kurulum komutu: uv add asyncpg")

    if _pg_pool is not None:
        return _pg_pool

    async with _pg_pool_lock:
        if _pg_pool is not None:
            return _pg_pool

        async def _create() -> asyncpg.Pool:  # type: ignore[type-arg]
            """PostgreSQL havuzunu yapılandırır ve bağlar."""
            return await asyncpg.create_pool(
                host=settings.postgres_host,
                port=settings.postgres_port,
                database=settings.postgres_db,
                user=settings.postgres_user,
                password=settings.postgres_password,
                min_size=settings.db_pool_min,
                max_size=settings.db_pool_max,
                command_timeout=settings.db_command_timeout,
                max_inactive_connection_lifetime=300.0,
            )

        _pg_pool = await _retry_async(_create, "pg.primary.pool.create")
        _pg_healthy = True
        logger.info(
            "postgresql_primary_havuzu_olusturuldu",
            host=settings.postgres_host,
            min_size=settings.db_pool_min,
            max_size=settings.db_pool_max,
        )
        return _pg_pool


# Geriye dönük uyumluluk takma adı (Backwards Compatibility Alias)
get_db_pool = get_pg_pool


async def get_pg_replica_pool() -> asyncpg.Pool:  # type: ignore[type-arg]
    """REPLICA PostgreSQL bağlantı havuzunu döndürür (okuma operasyonları).

    Replica tanımlı veya erişilebilir değilse otomatik olarak primary havuza fallback yapar.

    Returns:
        asyncpg.Pool: PostgreSQL ikincil (okuma) bağlantı havuzu.

    Raises:
        RuntimeError: asyncpg paketi kurulu değilse.
    """
    global _pg_replica_pool
    if asyncpg is None:
        raise RuntimeError("asyncpg kurulu değil. Kurulum komutu: uv add asyncpg")

    replica_host: str | None = getattr(settings, "postgres_replica_host", None)
    replica_port: int = getattr(settings, "postgres_replica_port", 5433)
    if replica_host and replica_host not in ("localhost", "127.0.0.1") and replica_port == 5433:
        replica_port = 5432

    if not replica_host:
        return await get_pg_pool()

    if _pg_replica_pool is not None:
        return _pg_replica_pool

    async with _pg_replica_pool_lock:
        if _pg_replica_pool is not None:
            return _pg_replica_pool

        async def _create() -> asyncpg.Pool:  # type: ignore[type-arg]
            """PostgreSQL ikincil kopya havuzunu oluşturur."""
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
            logger.info("postgresql_replica_havuzu_olusturuldu", host=replica_host)
        except Exception as exc:
            logger.warning("replica_havuzu_kullanilamiyor_primarye_geciliyor", error=str(exc))
            _pg_replica_pool = await get_pg_pool()
            return _pg_replica_pool

        return _pg_replica_pool


async def _check_replica_lag(replica_conn: Any) -> float | None:
    """Replica senkronizasyon gecikmesini saniye cinsinden ölçer.

    Args:
        replica_conn: Ölçüm yapılacak replica bağlantısı.

    Returns:
        float | None: Gecikme süresi (saniye) veya hata durumunda None.
    """
    try:
        lag: float | None = await replica_conn.fetchval(
            "SELECT EXTRACT(EPOCH FROM (now() - pg_last_xact_replay_timestamp()))::float"
        )
        if lag is not None:
            _pg_replica_lag_histogram.record(lag)
        return lag
    except Exception as exc:
        logger.debug("replica_gecikme_olcumu_yapilamadi", error=str(exc))
        return None


# ─── DatabaseRouter ───────────────────────────────────────────────────────────


class DatabaseRouter:
    """Read/Write ayrımı ve yük dengeleme ile bağlantı yönlendirici.

    - write() -> Daima Primary PostgreSQL havuzunu kullanır.
    - read()  -> Eşik altındaki gecikmelerde Replica, aksi takdirde Primary kullanır.
    """

    _POOL_ATTR: str = "_alpha_pool_type"

    def __init__(self, replica_lag_threshold: float = DEFAULT_REPLICA_LAG_THRESHOLD_SECONDS) -> None:
        """Başlatıcı.

        Args:
            replica_lag_threshold: Replica gecikme tolerans eşiği (saniye).
        """
        self.replica_lag_threshold = float(replica_lag_threshold)

    def __repr__(self) -> str:
        """Açıklayıcı metin temsili."""
        return f"<DatabaseRouter lag_threshold={self.replica_lag_threshold}s>"

    async def get_write_conn(self) -> Any:
        """Yazma operasyonları için primary bağlantı döner.

        Returns:
            Any: asyncpg bağlantı nesnesi.
        """
        pool = await get_pg_pool()
        conn = await pool.acquire()
        conn.__dict__[self._POOL_ATTR] = "primary"
        return conn

    async def get_read_conn(self) -> Any:
        """Okuma operasyonları için replica bağlantı döner; lag yüksekse primary'e geçer.

        Returns:
            Any: asyncpg bağlantı nesnesi.
        """
        replica_host: str | None = getattr(settings, "postgres_replica_host", None)

        if not replica_host:
            pool = await get_pg_pool()
            conn = await pool.acquire()
            conn.__dict__[self._POOL_ATTR] = "primary"
            return conn

        pool = await get_pg_replica_pool()
        conn = await pool.acquire()
        lag = await _check_replica_lag(conn)

        if lag is not None and lag >= self.replica_lag_threshold:
            logger.warning(
                "replica_gecikmesi_cok_yuksek_primarye_geciliyor",
                lag_seconds=lag,
                threshold=self.replica_lag_threshold,
            )
            await pool.release(conn)
            pool = await get_pg_pool()
            conn = await pool.acquire()
            conn.__dict__[self._POOL_ATTR] = "primary"
            return conn

        conn.__dict__[self._POOL_ATTR] = "replica"
        return conn

    @asynccontextmanager
    async def read(self) -> AsyncGenerator[Any, None]:
        """Okuma operasyonları için asenkron bağlam yöneticisi."""
        conn = await self.get_read_conn()
        try:
            yield conn
        finally:
            await self._release(conn)

    @asynccontextmanager
    async def write(self) -> AsyncGenerator[Any, None]:
        """Yazma operasyonları için asenkron bağlam yöneticisi."""
        conn = await self.get_write_conn()
        try:
            yield conn
        finally:
            await self._release(conn)

    @asynccontextmanager
    async def write_transaction(self) -> AsyncGenerator[Any, None]:
        """Transaction destekli yazma operasyonu asenkron bağlam yöneticisi."""
        conn = await self.get_write_conn()
        try:
            async with conn.transaction():
                yield conn
        finally:
            await self._release(conn)

    async def _release(self, conn: Any) -> None:
        """Bağlantıyı ait olduğu havuza güvenli şekilde geri bırakır.

        Args:
            conn: Serbest bırakılacak bağlantı nesnesi.
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
            logger.warning("db_baglantisi_serbest_birakilirken_hata", error=str(exc))


# Singleton router
db_router = DatabaseRouter()


# ─── PostgreSQL Yardımcıları ──────────────────────────────────────────────────


async def close_pg_pool() -> None:
    """Primary ve replica PostgreSQL havuzlarını güvenle kapatır."""
    global _pg_pool, _pg_replica_pool, _pg_healthy
    if _pg_pool:
        await _pg_pool.close()
        _pg_pool = None
    if _pg_replica_pool:
        await _pg_replica_pool.close()
        _pg_replica_pool = None
    _pg_healthy = False
    logger.info("postgresql_havuzlari_kapatildi")


@asynccontextmanager
async def get_pg_connection() -> AsyncGenerator[Any, None]:
    """PRIMARY PostgreSQL bağlantısı için asenkron bağlam yöneticisi."""
    pool = await get_pg_pool()
    async with pool.acquire() as conn:
        yield conn


@asynccontextmanager
async def get_pg_replica_connection() -> AsyncGenerator[Any, None]:
    """REPLICA PostgreSQL bağlantısı için asenkron bağlam yöneticisi."""
    pool = await get_pg_replica_pool()
    async with pool.acquire() as conn:
        yield conn


@asynccontextmanager
async def get_pg_transaction() -> AsyncGenerator[Any, None]:
    """Transaction destekli PRIMARY PostgreSQL bağlantı bağlamı."""
    pool = await get_pg_pool()
    async with pool.acquire() as conn, conn.transaction():
        yield conn


async def pg_execute(query: str, *args: Any) -> str:
    """PRIMARY üzerinde yazma sorgusu çalıştırır.

    Args:
        query: SQL sorgu cümlesi.
        *args: Sorgu parametreleri.

    Returns:
        str: İşlem durum sonucu (örn. 'INSERT 0 1').
    """
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
                    return str(result)
            except Exception as exc:
                if attempt < max_retries and _is_connection_error(exc):
                    logger.warning(
                        "pg_execute_baglanti_hatasi_havuz_yenileniyor",
                        attempt=attempt + 1,
                        error=str(exc),
                    )
                    _db_retry_counter.add(1, {"operation": "pg.execute"})
                    await close_pg_pool()
                    await asyncio.sleep(DEFAULT_RETRY_BASE_DELAY * (2**attempt))
                    continue
                span.record_exception(exc)
                _db_error_counter.add(1, {"db": "postgres", "op": "execute"})
                logger.error("pg_execute_basarisiz", query=query[:100], error=str(exc))
                raise


async def pg_fetch(query: str, *args: Any) -> list[Any]:
    """REPLICA havuzundan satır listesi çeker.

    Args:
        query: SQL sorgu metni.
        *args: Sorgu parametreleri.

    Returns:
        list[Any]: Kayıt listesi.
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
                    return list(result)
            except Exception as exc:
                if attempt < max_retries and _is_connection_error(exc):
                    _db_retry_counter.add(1, {"operation": "pg.fetch"})
                    await close_pg_pool()
                    await asyncio.sleep(DEFAULT_RETRY_BASE_DELAY * (2**attempt))
                    continue
                span.record_exception(exc)
                _db_error_counter.add(1, {"db": "postgres", "op": "fetch"})
                logger.error("pg_fetch_basarisiz", query=query[:100], error=str(exc))
                raise


async def pg_fetchrow(query: str, *args: Any) -> Any | None:
    """REPLICA havuzundan tek satır çeker.

    Args:
        query: SQL sorgu metni.
        *args: Sorgu parametreleri.

    Returns:
        Any | None: Bulunan tek kayıt veya None.
    """
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
                    await asyncio.sleep(DEFAULT_RETRY_BASE_DELAY * (2**attempt))
                    continue
                span.record_exception(exc)
                _db_error_counter.add(1, {"db": "postgres", "op": "fetchrow"})
                logger.error("pg_fetchrow_basarisiz", query=query[:100], error=str(exc))
                raise


async def pg_fetchval(query: str, *args: Any) -> Any:
    """REPLICA havuzundan tek skalar değer çeker.

    Args:
        query: SQL sorgu metni.
        *args: Sorgu parametreleri.

    Returns:
        Any: Skalar değer.
    """
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
                    await asyncio.sleep(DEFAULT_RETRY_BASE_DELAY * (2**attempt))
                    continue
                span.record_exception(exc)
                _db_error_counter.add(1, {"db": "postgres", "op": "fetchval"})
                logger.error("pg_fetchval_basarisiz", query=query[:100], error=str(exc))
                raise


# ─── ClickHouse ───────────────────────────────────────────────────────────────

_ch_local = threading.local()
_ch_healthy: bool = False
_ch_thread_lock: threading.Lock = threading.Lock()


def get_ch_client() -> Any:
    """Thread-local ClickHouse istemcisi döndürür (tamamen thread-safe).

    Returns:
        Any: clickhouse_connect istemcisi.

    Raises:
        RuntimeError: clickhouse-connect kurulu değilse.
    """
    global _ch_healthy
    if clickhouse_connect is None:
        raise RuntimeError("clickhouse-connect kurulu değil. Kurulum komutu: uv add clickhouse-connect")

    client = getattr(_ch_local, "client", None)
    if client is None:
        client = clickhouse_connect.get_client(
            host=settings.clickhouse_host,
            port=settings.clickhouse_http_port,
            username=settings.clickhouse_user,
            password=settings.clickhouse_password,
            database=settings.clickhouse_db,
            connect_timeout=5,
            send_receive_timeout=10,
        )
        _ch_local.client = client
        _ch_healthy = True
    return client


get_clickhouse = get_ch_client


def close_ch_client() -> None:
    """Mevcut iş parçacığındaki ClickHouse istemcisini kapatır."""
    global _ch_healthy
    client = getattr(_ch_local, "client", None)
    if client:
        try:
            client.close()
        except Exception as exc:
            logger.warning("clickhouse_istemcisi_kapatilirken_hata", error=str(exc))
        _ch_local.client = None
    _ch_healthy = False
    logger.info("clickhouse_istemcisi_kapatildi")


def ch_execute(query: str, parameters: dict[str, Any] | None = None) -> Any:
    """ClickHouse üzerinde sorgu çalıştırır.

    Args:
        query: ClickHouse SQL sorgusu.
        parameters: İsteğe bağlı parametre sözlüğü.

    Returns:
        Any: ClickHouse sorgu yanıt nesnesi.
    """
    max_retries: int = 2
    for attempt in range(max_retries + 1):
        try:
            with _ch_thread_lock:
                client = get_ch_client()
                return client.query(query, parameters=parameters)
        except Exception as exc:
            if attempt < max_retries:
                _ch_local.client = None
                delay = DEFAULT_RETRY_BASE_DELAY * (attempt + 1) + random.uniform(0, 0.5)
                logger.warning(
                    "clickhouse_sorgusu_basarisiz_yeniden_baglaniliyor",
                    attempt=attempt + 1,
                    delay=round(delay, 2),
                    error=str(exc),
                )
                time.sleep(delay)
                continue
            logger.error("clickhouse_sorgusu_tum_denemelerden_sonra_basarisiz", error=str(exc))
            raise


def ch_insert(
    table: str,
    data: list[list[Any]],
    column_names: list[str] | None = None,
) -> None:
    """ClickHouse'a toplu veri yazar — yeniden bağlanma ve Jitter ile.

    Args:
        table: Hedef tablo adı.
        data: Satır listesi.
        column_names: Kolon sırası (varsayılan: None, tablo sırası).
    """
    global _ch_healthy
    max_retries: int = 2
    for attempt in range(max_retries + 1):
        try:
            with _ch_thread_lock:
                client = get_ch_client()
                client.insert(table, data, column_names=column_names)
                return
        except Exception as exc:
            if attempt < max_retries:
                _ch_local.client = None
                _ch_healthy = False
                delay = DEFAULT_RETRY_BASE_DELAY * (attempt + 1) + random.uniform(0, 0.5)
                logger.warning(
                    "clickhouse_toplu_yazma_basarisiz_yeniden_baglaniliyor",
                    attempt=attempt + 1,
                    delay=round(delay, 2),
                    error=str(exc),
                )
                time.sleep(delay)
                continue
            logger.error("clickhouse_toplu_yazma_tum_denemelerden_sonra_basarisiz", error=str(exc))
            raise


def ch_query_df(query: str, parameters: dict[str, Any] | None = None) -> pl.DataFrame:
    """ClickHouse sorgusunu çalıştırır ve sıfır bellek kopyasıyla Polars DataFrame döner.

    Args:
        query: SQL sorgu cümlesi.
        parameters: Parametreler sözlüğü.

    Returns:
        pl.DataFrame: Polars DataFrame sonucu.
    """
    with _ch_thread_lock:
        client = get_ch_client()
        result = client.query(query, parameters=parameters)

    # Sıfır kopyalı PyArrow tablosundan Polars oluşturma (Pandas kullanılmaz)
    return pl.from_arrow(result.result_columns_to_arrow())


# ─── DuckDB (Yerel Gömülü Veritabanı) ──────────────────────────────────────────

_duckdb_lock = threading.RLock()


def get_duckdb_connection(
    db_path: str | Path = DEFAULT_DUCKDB_PATH,
    read_only: bool = False,
) -> duckdb.DuckDBPyConnection:
    """Thread-safe ve 0-byte bozulma korumalı yerel DuckDB bağlantısı oluşturur.

    Args:
        db_path: DuckDB veritabanı dosya yolu.
        read_only: Salt okunur mod aktif edilsin mi?

    Returns:
        duckdb.DuckDBPyConnection: DuckDB bağlantı nesnesi.
    """
    path_obj = Path(db_path)
    if not read_only:
        path_obj.parent.mkdir(parents=True, exist_ok=True)
        if path_obj.exists() and path_obj.stat().st_size == 0:
            with contextlib.suppress(OSError):
                path_obj.unlink()

    with _duckdb_lock:
        conn = duckdb.connect(str(path_obj), read_only=read_only)
        if not read_only:
            with contextlib.suppress(Exception):
                from .duckdb_store import configure_duckdb_wal

                configure_duckdb_wal(conn)
        return conn


@contextmanager
def get_duckdb(
    db_path: str | Path = DEFAULT_DUCKDB_PATH,
    read_only: bool = False,
) -> Generator[duckdb.DuckDBPyConnection, None, None]:
    """DuckDB bağlantısı için güvenli context manager.

    Args:
        db_path: DuckDB veritabanı dosya yolu.
        read_only: Salt okunur mod.

    Yields:
        duckdb.DuckDBPyConnection: DuckDB bağlantısı.
    """
    conn = get_duckdb_connection(db_path=db_path, read_only=read_only)
    try:
        yield conn
    finally:
        with contextlib.suppress(Exception):
            conn.close()


def duckdb_query_df(
    query: str,
    parameters: list[Any] | None = None,
    db_path: str | Path = DEFAULT_DUCKDB_PATH,
) -> pl.DataFrame:
    """DuckDB üzerinden sorgu çalıştırır ve doğrudan Polars DataFrame döndürür.

    Args:
        query: SQL sorgu metni.
        parameters: Sorgu parametreleri listesi.
        db_path: DuckDB dosya yolu.

    Returns:
        pl.DataFrame: Sorgu sonucu Polars DataFrame.
    """
    path_obj = Path(db_path)
    if not path_obj.exists() or path_obj.stat().st_size == 0:
        return pl.DataFrame()

    try:
        with get_duckdb(db_path=path_obj, read_only=True) as conn:
            cursor = conn.execute(query, parameters or [])
            arrow_table = cursor.arrow()
            return pl.from_arrow(arrow_table)
    except Exception as exc:
        logger.error("duckdb_query_df_basarisiz", query=query[:100], error=str(exc))
        return pl.DataFrame()


def duckdb_execute(
    query: str,
    parameters: list[Any] | None = None,
    db_path: str | Path = DEFAULT_DUCKDB_PATH,
) -> None:
    """DuckDB üzerinde DDL veya DML komutu (CREATE, INSERT, UPDATE, DELETE) çalıştırır.

    Args:
        query: SQL komut metni.
        parameters: Parametre listesi.
        db_path: DuckDB dosya yolu.
    """
    path_obj = Path(db_path)
    with get_duckdb(db_path=path_obj, read_only=False) as conn:
        conn.execute(query, parameters or [])


def duckdb_write_df(
    df: pl.DataFrame,
    table_name: str,
    db_path: str | Path = DEFAULT_DUCKDB_PATH,
    mode: str = "append",
) -> int:
    """Polars DataFrame verisini sıfır kopyayla (Arrow) yerel DuckDB tablosuna yazar.

    Args:
        df: Yazılacak Polars DataFrame.
        table_name: Hedef tablo adı.
        db_path: DuckDB veritabanı dosya yolu.
        mode: Yazma modu ('append' veya 'replace').

    Returns:
        int: Eklenen satır sayısı.
    """
    if df.is_empty():
        return 0

    path_obj = Path(db_path)
    with get_duckdb(db_path=path_obj, read_only=False) as conn:
        conn.register("df_source", df.to_arrow())
        if mode == "replace":
            conn.execute(f"CREATE OR REPLACE TABLE {table_name} AS SELECT * FROM df_source")
        else:
            conn.execute(f"CREATE TABLE IF NOT EXISTS {table_name} AS SELECT * FROM df_source WHERE 1=0")
            conn.execute(f"INSERT INTO {table_name} SELECT * FROM df_source")
    return len(df)


# ─── Redis ────────────────────────────────────────────────────────────────────

_redis: Any = None
_redis_healthy: bool = False
_redis_lock: asyncio.Lock = asyncio.Lock()


async def get_redis() -> Any:
    """Redis bağlantısı döndürür (Sentinel varsa HA, yoksa doğrudan bağlantı).

    Returns:
        Any: aioredis istemci nesnesi.

    Raises:
        RuntimeError: redis paketi kurulu değilse.
    """
    global _redis, _redis_healthy
    if aioredis is None:
        raise RuntimeError("redis kurulu değil. Kurulum komutu: uv add redis")

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
                max_connections=500,
                socket_timeout=5.0,
                socket_connect_timeout=3.0,
            )
        _redis_healthy = True
        logger.info("redis_baglantisi_olusturuldu_ha_uyumlu")
        return _redis


async def close_redis() -> None:
    """Redis bağlantısını güvenle kapatır."""
    global _redis, _redis_healthy
    if _redis:
        try:
            from .redis_sentinel import close_ha_redis

            await close_ha_redis()
        except Exception as exc:
            logger.warning("ha_redis_kapatilirken_hata", error=str(exc))
        try:
            await _redis.aclose()
        except Exception as exc:
            logger.warning("redis_kapatilirken_hata", error=str(exc))
        _redis = None
        _redis_healthy = False
        logger.info("redis_baglantisi_kapatildi")


async def redis_get(key: str) -> str | None:
    """Redis'ten anahtar değerini okur.

    Args:
        key: Okunacak anahtar.

    Returns:
        str | None: Değer veya None.
    """
    with tracer.start_as_current_span("db.redis.get") as span:
        span.set_attribute("db.redis.key", key)
        r = await get_redis()
        return await r.get(key)


async def redis_set(key: str, value: str, ex: int | None = None) -> None:
    """Redis'e anahtar ve değer yazar (isteğe bağlı TTL ile).

    Args:
        key: Yazılacak anahtar.
        value: Değer.
        ex: Geçerlilik süresi (saniye).
    """
    with tracer.start_as_current_span("db.redis.set") as span:
        span.set_attribute("db.redis.key", key)
        r = await get_redis()
        await r.set(key, value, ex=ex)


async def redis_delete(key: str) -> None:
    """Redis'ten anahtar siler.

    Args:
        key: Silinecek anahtar adı.
    """
    r = await get_redis()
    await r.delete(key)


async def redis_hgetall(key: str) -> dict[str, str]:
    """Redis hash yapısını tamamen okur.

    Args:
        key: Hash anahtarı.

    Returns:
        dict[str, str]: Hash haritası.
    """
    r = await get_redis()
    return await r.hgetall(key)


async def redis_hset(key: str, mapping: dict[str, str]) -> None:
    """Redis hash yapısına alan haritası yazar.

    Args:
        key: Hash anahtarı.
        mapping: Alan-değer çiftleri.
    """
    r = await get_redis()
    await r.hset(key, mapping=mapping)


async def redis_publish(channel: str, message: str) -> None:
    """Redis Pub/Sub kanalına mesaj yayınlar.

    Args:
        channel: Hedef kanal adı.
        message: Yayınlanacak metin mesajı.
    """
    with tracer.start_as_current_span("db.redis.publish") as span:
        span.set_attribute("db.redis.channel", channel)
        r = await get_redis()
        await r.publish(channel, message)


# ─── Sağlık Denetimi (Health Check) ───────────────────────────────────────────


async def check_db_health() -> dict[str, Any]:
    """Tüm kurumsal veritabanı bağlantılarının canlılık durumunu denetler.

    Returns:
        dict[str, Any]: Servis durumları ('healthy', 'degraded', 'offline', 'error: ...').
    """
    health: dict[str, Any] = {
        "postgres": "unavailable",
        "clickhouse": "unavailable",
        "redis": "unavailable",
        "questdb": "unavailable",
        "duckdb": "unavailable",
    }

    with tracer.start_as_current_span("db.health_check"):
        # 1. PostgreSQL Denetimi
        if _pg_healthy and _pg_pool is not None:
            try:

                async def _check_pg() -> tuple[Any, int, int]:
                    """PostgreSQL canlılığını test eder."""
                    pool = await get_pg_pool()
                    async with pool.acquire() as conn:
                        result = await conn.fetchval("SELECT 1")
                        return result, pool.get_size(), pool.get_idle_size()

                result, p_size, p_free = await asyncio.wait_for(_check_pg(), timeout=1.0)
                health["postgres"] = "healthy" if result == 1 else "degraded"
                health["postgres_pool_size"] = p_size
                health["postgres_pool_free"] = p_free
            except Exception as exc:
                health["postgres"] = f"error: {str(exc)[:100]}"
        else:
            health["postgres"] = "offline"

        # 2. ClickHouse Denetimi
        if _ch_healthy:
            try:

                def _check_ch() -> bool:
                    """ClickHouse canlılığını test eder."""
                    res = ch_execute("SELECT 1")
                    return bool(res.result_rows and res.result_rows[0][0] == 1)

                is_ok = await asyncio.wait_for(asyncio.to_thread(_check_ch), timeout=1.0)
                health["clickhouse"] = "healthy" if is_ok else "degraded"
            except Exception as exc:
                health["clickhouse"] = f"error: {str(exc)[:100]}"
        else:
            health["clickhouse"] = "offline"

        # 3. Redis Denetimi
        if _redis_healthy and _redis is not None:
            try:

                async def _check_redis() -> bool:
                    """Redis canlılığını test eder."""
                    r = await get_redis()
                    return bool(await r.ping())

                pong = await asyncio.wait_for(_check_redis(), timeout=1.0)
                health["redis"] = "healthy" if pong else "degraded"
            except Exception as exc:
                health["redis"] = f"error: {str(exc)[:100]}"
        else:
            health["redis"] = "offline"

        # 4. QuestDB Denetimi
        try:
            health["questdb"] = "healthy" if questdb_client._connected else "disconnected"
        except Exception as exc:
            health["questdb"] = f"error: {str(exc)[:100]}"

        # 5. DuckDB Denetimi
        try:
            with get_duckdb(read_only=False) as d_conn:
                val = d_conn.execute("SELECT 1").fetchone()
                health["duckdb"] = "healthy" if val and val[0] == 1 else "degraded"
        except Exception as exc:
            health["duckdb"] = f"error: {str(exc)[:100]}"

    return health


# ─── Yaşam Döngüsü (Lifecycle) ────────────────────────────────────────────────

_databases_initialized: bool = False


async def init_databases(force: bool = False) -> None:
    """Tüm veritabanı altyapısını başlatır ve sağlık durumunu raporlar.

    Args:
        force: Daha önce başlatılmış olsa bile zorla yeniden başlatılsın mı?
    """
    global _pg_healthy, _ch_healthy, _redis_healthy, _databases_initialized

    if _databases_initialized and not force:
        return
    _databases_initialized = True

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

    # DuckDB yerel depolama başlatması
    try:
        with get_duckdb(read_only=False) as d_conn:
            d_conn.execute("SELECT 1")
    except Exception as exc:
        logger.warning("DuckDB başlatılamadı", error=str(exc))

    health = await check_db_health()
    for svc, status in health.items():
        if status == "healthy":
            logger.info("db_saglik_kontrolu", service=svc, status="OK")
        elif isinstance(status, str) and status.startswith("error"):
            logger.warning("db_saglik_kontrolu", service=svc, status=status)

    logger.info("veritabani_baslatma_tamamlandi")


async def close_databases() -> None:
    """Tüm veritabanı bağlantı havuzlarını ve oturumlarını düzenli şekilde kapatır."""
    await close_pg_pool()
    close_ch_client()
    await close_redis()
    try:
        questdb_client.close()
    except Exception as exc:
        logger.warning("QuestDB kapatılırken hata", error=str(exc))
    logger.info("tum_veritabani_baglantilari_kapatildi")


__all__ = [
    "DEFAULT_DUCKDB_PATH",
    "DEFAULT_MAX_RETRIES",
    "DEFAULT_REPLICA_LAG_THRESHOLD_SECONDS",
    "DEFAULT_RETRY_BASE_DELAY",
    "DatabaseRouter",
    "ch_execute",
    "ch_insert",
    "ch_query_df",
    "check_db_health",
    "close_ch_client",
    "close_databases",
    "close_pg_pool",
    "close_redis",
    "db_router",
    "duckdb_execute",
    "duckdb_query_df",
    "duckdb_write_df",
    "get_ch_client",
    "get_clickhouse",
    "get_db_pool",
    "get_duckdb",
    "get_duckdb_connection",
    "get_pg_connection",
    "get_pg_pool",
    "get_pg_replica_connection",
    "get_pg_replica_pool",
    "get_pg_transaction",
    "get_redis",
    "init_databases",
    "pg_execute",
    "pg_fetch",
    "pg_fetchrow",
    "pg_fetchval",
    "redis_delete",
    "redis_get",
    "redis_hgetall",
    "redis_hset",
    "redis_publish",
    "redis_set",
]
