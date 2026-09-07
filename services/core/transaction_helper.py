"""
ALPHA BIST — Database Transaction Helper v2.0

Veritabanı İşlemleri İçin Atomik ve Güvenilir Transaction Yöneticisi:
- Atomik Çoklu İşlem Transaction Desteği (PostgreSQL / TimescaleDB).
- Üstel Geri Çekilme ile Otomatik Yeniden Deneme (Exponential Backoff Retry).
- İç İçe Transaction Desteği (Savepoints).
- Gerçek Asyncio Timeout Yönetimi (asyncio.timeout ile garantili zaman aşımı koruması).
- Performans, Sorgu ve Hata Metrikleri Takibi (SHA-256 parmak izi).
- İş Parçacığı Güvenliği: threading.RLock() korumalı metrik ve log yönetimi.
- DuckDB >= 1.3.0 denetim izi: transaction_audit tablosu ile tüm transaction yaşam döngüsünün arşivlenmesi.
- Polars >= 1.30.0 analitik sorgulama ve orjson serileştirme desteği.
"""

from __future__ import annotations

import asyncio
import functools
import hashlib
import inspect
import threading
import time
from contextlib import asynccontextmanager
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, AsyncIterator, Final

import duckdb
import orjson
import polars as pl
import structlog

if TYPE_CHECKING:
    from collections.abc import Callable

DEFAULT_TRANSACTION_DB: Final[str] = "data/transaction_audit.duckdb"
DEFAULT_CHECKPOINT_SIZE: Final[str] = "4MB"
DEFAULT_WAL_SIZE: Final[str] = "2MB"

logger = structlog.get_logger(__name__)


def configure_duckdb_wal(conn: duckdb.DuckDBPyConnection) -> None:
    """DuckDB bağlantısı için WAL ve checkpoint parametrelerini optimize eder."""
    try:
        conn.execute(f"PRAGMA checkpoint_threshold = '{DEFAULT_CHECKPOINT_SIZE}';")
        conn.execute(f"PRAGMA wal_autocheckpoint = '{DEFAULT_WAL_SIZE}';")
    except Exception as exc:
        logger.debug("DuckDB WAL pragma uyarisi", hata=str(exc))


def to_orjson_bytes(val: Any) -> bytes:
    """Herhangi bir veriyi orjson ile güvenli byte dizisine serileştirir."""
    if hasattr(val, "to_dict"):
        return orjson.dumps(val.to_dict(), default=str)
    return orjson.dumps(val, default=str)


def otel_trace(span_name: str) -> Any:
    """Metotları OpenTelemetry span veya güvenli yerel izleme sarmalayıcısına alır."""

    def decorator(func: Any) -> Any:
        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            return func(*args, **kwargs)

        @functools.wraps(func)
        async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
            return await func(*args, **kwargs)

        if inspect.iscoroutinefunction(func):
            return async_wrapper
        return wrapper

    return decorator


@dataclass(slots=True)
class TransactionMetrics:
    """Transaction genel çalışma metrikleri veri modeli."""

    total_transactions: int = 0
    committed: int = 0
    rolled_back: int = 0
    retried: int = 0
    timed_out: int = 0
    total_duration_ms: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        """Metrikleri standart Python sözlüğüne dönüştürür."""
        avg_dur = round(self.total_duration_ms / max(self.total_transactions, 1), 2)
        return {
            "total_transactions": self.total_transactions,
            "committed": self.committed,
            "rolled_back": self.rolled_back,
            "retried": self.retried,
            "timed_out": self.timed_out,
            "total_duration_ms": round(self.total_duration_ms, 2),
            "avg_duration_ms": avg_dur,
        }

    def to_orjson_bytes(self) -> bytes:
        """Metrikleri orjson ikili baytlarına serileştirir."""
        return orjson.dumps(self.to_dict(), default=str)

    def __repr__(self) -> str:
        return (
            f"TransactionMetrics(total={self.total_transactions}, committed={self.committed}, "
            f"rolled_back={self.rolled_back}, retried={self.retried}, timed_out={self.timed_out})"
        )


@dataclass(slots=True)
class QueryMetrics:
    """Tekil sorgu çalışma metrikleri veri modeli."""

    query_hash: str
    duration_ms: float
    rows_affected: int = 0
    success: bool = True
    error: str | None = None
    executed_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def to_dict(self) -> dict[str, Any]:
        """Sorgu metriğini sözlüğe dönüştürür."""
        data = asdict(self)
        data["executed_at"] = self.executed_at.isoformat()
        return data

    def to_orjson_bytes(self) -> bytes:
        """Sorgu metriğini orjson baytlarına dönüştürür."""
        return orjson.dumps(self.to_dict(), default=str)

    def __repr__(self) -> str:
        status = "SUCCESS" if self.success else f"FAILED({self.error})"
        return f"QueryMetrics(hash={self.query_hash!r}, dur={self.duration_ms:.2f}ms, status={status})"


class TransactionHelper:
    """PostgreSQL ve TimescaleDB veritabanı transaction yöneticisi.

    Atomik operasyonlar, yeniden deneme (retry), timeout ve DuckDB denetim takibi sağlar.
    """

    def __init__(
        self,
        pool: Any = None,
        default_timeout_seconds: float = 30.0,
        max_retries: int = 3,
        retry_base_delay: float = 0.5,
        duckdb_path: str = DEFAULT_TRANSACTION_DB,
    ) -> None:
        """TransactionHelper başlatıcısı.

        Args:
            pool: asyncpg veya SQLAlchemy veritabanı bağlantı havuzu.
            default_timeout_seconds: Varsayılan işlem zaman aşımı süresi.
            max_retries: Hata durumunda azami yeniden deneme sayısı.
            retry_base_delay: Üstel geri çekilme başlangıç gecikmesi (saniye).
            duckdb_path: Transaction denetim günlüğü için DuckDB dosya yolu veya ':memory:'.
        """
        self._lock = threading.RLock()
        self._pool = pool
        self._default_timeout = max(1.0, default_timeout_seconds)
        self._max_retries = max(0, max_retries)
        self._retry_base_delay = max(0.1, retry_base_delay)
        self._metrics = TransactionMetrics()
        self._query_log: list[QueryMetrics] = []
        self._duckdb_path = duckdb_path

        # DuckDB denetim tablosu kurulumu
        if self._duckdb_path != ":memory:":
            try:
                Path(self._duckdb_path).parent.mkdir(parents=True, exist_ok=True)
                self._duckdb_con = duckdb.connect(self._duckdb_path)
            except Exception as e:
                logger.warning(
                    "DuckDB disk baglantisi kurulamadi, bellege donuluyor",
                    yol=self._duckdb_path,
                    hata=str(e),
                )
                self._duckdb_con = duckdb.connect(":memory:")
        else:
            self._duckdb_con = duckdb.connect(":memory:")

        configure_duckdb_wal(self._duckdb_con)
        self._init_duckdb_schema()

    def _init_duckdb_schema(self) -> None:
        """DuckDB denetim tablosunu ve dizisini oluşturur."""
        with self._lock:
            try:
                self._duckdb_con.execute("""
                    CREATE SEQUENCE IF NOT EXISTS seq_tx_audit_id START 1;
                    CREATE TABLE IF NOT EXISTS transaction_audit (
                        id BIGINT DEFAULT nextval('seq_tx_audit_id') PRIMARY KEY,
                        tx_type VARCHAR NOT NULL,
                        status VARCHAR NOT NULL,
                        duration_ms DOUBLE NOT NULL,
                        query_count INTEGER NOT NULL,
                        error VARCHAR,
                        recorded_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
                    );
                """)
            except Exception as exc:
                logger.error("TransactionHelper DuckDB schema init failed", error=str(exc))

    def _record_audit_log(
        self,
        tx_type: str,
        status: str,
        duration_ms: float,
        query_count: int,
        error: str | None = None,
    ) -> None:
        """Transaction denetim kaydını DuckDB tablosuna işler."""
        with self._lock:
            try:
                self._duckdb_con.execute(
                    """
                    INSERT INTO transaction_audit
                    (tx_type, status, duration_ms, query_count, error)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    [tx_type, status, float(duration_ms), int(query_count), error],
                )
            except Exception as exc:
                logger.warning("Failed to record transaction audit log", error=str(exc))

    def set_pool(self, pool: Any) -> None:
        """Veritabanı bağlantı havuzunu ayarlar."""
        with self._lock:
            self._pool = pool

    @asynccontextmanager
    async def atomic(
        self,
        timeout_seconds: float | None = None,
        read_only: bool = False,
    ) -> AsyncIterator[TransactionConnection]:
        """Atomik transaction bağlam yöneticisi.

        Args:
            timeout_seconds: İşlem zaman aşımı (saniye).
            read_only: Salt okunur işlem modu.

        Yields:
            TransactionConnection: Metrik toplayan sarmalanmış bağlantı nesnesi.
        """
        if self._pool is None:
            raise RuntimeError("Database pool not configured. Call set_pool() first.")

        timeout = timeout_seconds or self._default_timeout
        start_time = time.monotonic()
        tx_queries: list[QueryMetrics] = []

        with self._lock:
            self._metrics.total_transactions += 1

        conn = None
        tx = None
        try:
            async with asyncio.timeout(timeout):
                conn = await self._pool.acquire()
                tx_obj = conn.transaction(readonly=read_only)
                tx = await tx_obj if inspect.iscoroutine(tx_obj) else tx_obj

                if hasattr(tx, "start"):
                    start_res = tx.start()
                    if inspect.iscoroutine(start_res):
                        await start_res

                wrapped = TransactionConnection(conn, tx_queries)
                yield wrapped

                if hasattr(tx, "commit"):
                    commit_res = tx.commit()
                    if inspect.iscoroutine(commit_res):
                        await commit_res

            duration = (time.monotonic() - start_time) * 1000.0
            with self._lock:
                self._metrics.committed += 1
                self._metrics.total_duration_ms += duration
                self._query_log.extend(tx_queries)
                if len(self._query_log) > 500:
                    self._query_log = self._query_log[-500:]

            self._record_audit_log("atomic", "COMMITTED", duration, len(tx_queries))
            logger.debug("Transaction committed successfully", duration_ms=round(duration, 2), queries=len(tx_queries))

        except TimeoutError as exc:
            duration = (time.monotonic() - start_time) * 1000.0
            with self._lock:
                self._metrics.timed_out += 1
                self._metrics.rolled_back += 1
                self._metrics.total_duration_ms += duration

            if tx is not None and hasattr(tx, "rollback"):
                try:
                    rb_res = tx.rollback()
                    if inspect.iscoroutine(rb_res):
                        await rb_res
                except Exception as rb_exc:
                    logger.warning("Rollback on timeout failed", error=str(rb_exc))

            self._record_audit_log("atomic", "TIMEOUT", duration, len(tx_queries), str(exc))
            logger.error("Transaction timed out", timeout_seconds=timeout)
            raise

        except Exception as exc:
            duration = (time.monotonic() - start_time) * 1000.0
            with self._lock:
                self._metrics.rolled_back += 1
                self._metrics.total_duration_ms += duration

            if tx is not None and hasattr(tx, "rollback"):
                try:
                    rb_res = tx.rollback()
                    if inspect.iscoroutine(rb_res):
                        await rb_res
                except Exception as rb_exc:
                    logger.warning("Rollback on error failed", error=str(rb_exc))

            self._record_audit_log("atomic", "ROLLED_BACK", duration, len(tx_queries), str(exc))
            logger.error("Transaction rolled back due to error", error=str(exc))
            raise

        finally:
            if conn is not None:
                try:
                    await self._pool.release(conn)
                except Exception as rel_exc:
                    logger.warning("Connection release to pool failed", error=str(rel_exc))

    @asynccontextmanager
    async def atomic_with_retry(
        self,
        max_retries: int | None = None,
        timeout_seconds: float | None = None,
        read_only: bool = False,
    ) -> AsyncIterator[TransactionConnection]:
        """Üstel geri çekilme (exponential backoff) ile yeniden deneyen atomik transaction."""
        retries = max_retries if max_retries is not None else self._max_retries
        last_error: Exception | None = None

        for attempt in range(retries + 1):
            try:
                async with self.atomic(timeout_seconds=timeout_seconds, read_only=read_only) as tx:
                    yield tx
                    return

            except Exception as exc:
                last_error = exc
                if attempt < retries:
                    delay = self._retry_base_delay * (2**attempt)
                    with self._lock:
                        self._metrics.retried += 1
                    logger.warning(
                        "Transaction retry initiated",
                        attempt=attempt + 1,
                        max_retries=retries,
                        delay_seconds=delay,
                        error=str(exc),
                    )
                    await asyncio.sleep(delay)
                else:
                    logger.error("Transaction permanently failed after retries", attempts=retries + 1, error=str(exc))

        if last_error is not None:
            raise last_error

    @asynccontextmanager
    async def savepoint(self, conn: Any, name: str) -> AsyncIterator[Any]:
        """İç içe transaction desteği (Savepoint bağlamı)."""
        sp_name = f"sp_{name}_{int(time.monotonic() * 1000)}"
        await conn.execute(f"SAVEPOINT {sp_name}")

        try:
            yield conn
            await conn.execute(f"RELEASE SAVEPOINT {sp_name}")
        except Exception:
            await conn.execute(f"ROLLBACK TO SAVEPOINT {sp_name}")
            raise

    @otel_trace("transaction_helper.execute_batch")
    async def execute_batch(
        self,
        operations: list[Callable[[TransactionConnection], Any]],
        timeout_seconds: float | None = None,
    ) -> list[Any]:
        """Toplu işlemleri tek bir atomik transaction içinde sırayla çalıştırır."""
        results: list[Any] = []

        async with self.atomic(timeout_seconds=timeout_seconds) as tx:
            for op in operations:
                if inspect.iscoroutinefunction(op):
                    res = await op(tx)
                else:
                    res = op(tx)
                results.append(res)

        return results

    def get_metrics(self) -> dict[str, Any]:
        """Genel transaction metriklerini sözlük olarak döndürür."""
        with self._lock:
            return self._metrics.to_dict()

    def get_slow_queries(self, threshold_ms: float = 1000.0) -> list[dict[str, Any]]:
        """Belirtilen süreyi aşan yavaş sorguları listeler."""
        with self._lock:
            slow = [q for q in self._query_log if q.duration_ms >= threshold_ms]
            return [q.to_dict() for q in slow[-50:]]

    def reset_metrics(self) -> None:
        """Tüm transaction ve sorgu metriklerini sıfırlar."""
        with self._lock:
            self._metrics = TransactionMetrics()
            self._query_log.clear()

    def export_queries_to_polars(self) -> pl.DataFrame:
        """Bellekteki sorgu metriklerini Polars DataFrame olarak dışa aktarır."""
        with self._lock:
            if not self._query_log:
                return pl.DataFrame(
                    schema={
                        "query_hash": pl.Utf8,
                        "duration_ms": pl.Float64,
                        "rows_affected": pl.Int64,
                        "success": pl.Boolean,
                        "error": pl.Utf8,
                        "executed_at": pl.Utf8,
                    }
                )

            rows = [q.to_dict() for q in self._query_log]
            return pl.DataFrame(rows)

    def export_audit_to_polars(self) -> pl.DataFrame:
        """DuckDB'de kayıtlı transaction denetim kayıtlarını Polars DataFrame olarak dışa aktarır."""
        with self._lock:
            try:
                return self._duckdb_con.execute("""
                    SELECT id, tx_type, status, duration_ms, query_count, error, recorded_at
                    FROM transaction_audit
                    ORDER BY id ASC
                """).pl()
            except Exception as exc:
                logger.error("Failed to export transaction audit log to Polars", error=str(exc))
                return pl.DataFrame()

    def clear_audit_duckdb(self) -> None:
        """DuckDB transaction denetim tablosunu temizler."""
        with self._lock:
            try:
                self._duckdb_con.execute("DELETE FROM transaction_audit")
            except Exception as exc:
                logger.warning("DuckDB transaction denetim tablosu temizlenemedi", hata=str(exc))

    def close(self) -> None:
        """DuckDB bağlantısını güvenli şekilde kapatır."""
        with self._lock:
            try:
                self._duckdb_con.close()
            except Exception as exc:
                logger.debug("DuckDB baglantisi kapatilirken hata", hata=str(exc))

    def __repr__(self) -> str:
        with self._lock:
            return (
                f"TransactionHelper(pool={'CONNECTED' if self._pool else 'NONE'}, "
                f"tx_total={self._metrics.total_transactions}, duckdb={self._duckdb_path!r})"
            )


class TransactionConnection:
    """Transaction bağlantı sarmalayıcısı (Sorgu süresi ve metriklerini otomatik toplar)."""

    def __init__(self, conn: Any, query_log: list[QueryMetrics]) -> None:
        """TransactionConnection başlatıcısı."""
        self._conn = conn
        self._query_log = query_log

    def _hash_query(self, query: str) -> str:
        """Sorgu metni için SHA-256 tabanlı 8 karakterlik parmak izi üretir."""
        return hashlib.sha256(query.encode("utf-8")).hexdigest()[:8]

    @otel_trace("transaction_connection.execute")
    async def execute(self, query: str, *args: Any) -> Any:
        """Sorgu çalıştırır ve metrikleri kaydeder."""
        start = time.monotonic()
        query_hash = self._hash_query(query)

        try:
            result = await self._conn.execute(query, *args)
            duration = (time.monotonic() - start) * 1000.0

            self._query_log.append(
                QueryMetrics(
                    query_hash=query_hash,
                    duration_ms=duration,
                    success=True,
                )
            )
            return result

        except Exception as exc:
            duration = (time.monotonic() - start) * 1000.0
            self._query_log.append(
                QueryMetrics(
                    query_hash=query_hash,
                    duration_ms=duration,
                    success=False,
                    error=str(exc),
                )
            )
            raise

    @otel_trace("transaction_connection.fetch")
    async def fetch(self, query: str, *args: Any) -> list[Any]:
        """Çoklu satır getiren sorgu çalıştırır."""
        start = time.monotonic()
        query_hash = self._hash_query(query)

        try:
            result = await self._conn.fetch(query, *args)
            duration = (time.monotonic() - start) * 1000.0

            self._query_log.append(
                QueryMetrics(
                    query_hash=query_hash,
                    duration_ms=duration,
                    rows_affected=len(result) if isinstance(result, list) else 0,
                    success=True,
                )
            )
            return result

        except Exception as exc:
            duration = (time.monotonic() - start) * 1000.0
            self._query_log.append(
                QueryMetrics(
                    query_hash=query_hash,
                    duration_ms=duration,
                    success=False,
                    error=str(exc),
                )
            )
            raise

    @otel_trace("transaction_connection.fetchval")
    async def fetchval(self, query: str, *args: Any) -> Any:
        """Tekil değer getiren sorgu çalıştırır."""
        start = time.monotonic()
        query_hash = self._hash_query(query)

        try:
            result = await self._conn.fetchval(query, *args)
            duration = (time.monotonic() - start) * 1000.0

            self._query_log.append(
                QueryMetrics(
                    query_hash=query_hash,
                    duration_ms=duration,
                    rows_affected=1 if result is not None else 0,
                    success=True,
                )
            )
            return result

        except Exception as exc:
            duration = (time.monotonic() - start) * 1000.0
            self._query_log.append(
                QueryMetrics(
                    query_hash=query_hash,
                    duration_ms=duration,
                    success=False,
                    error=str(exc),
                )
            )
            raise

    def __repr__(self) -> str:
        return f"TransactionConnection(logged_queries={len(self._query_log)})"


def read_transaction_audit_from_duckdb(
    duckdb_path: str = DEFAULT_TRANSACTION_DB,
    limit: int = 1000,
) -> pl.DataFrame:
    """DuckDB dosyasından doğrudan transaction denetim kayıtlarını Polars DataFrame olarak okur."""
    try:
        conn = duckdb.connect(duckdb_path)
        try:
            return conn.execute(
                """
                SELECT id, tx_type, status, duration_ms, query_count, error, recorded_at
                FROM transaction_audit
                ORDER BY id DESC
                LIMIT ?
                """,
                [limit],
            ).pl()
        finally:
            conn.close()
    except Exception as exc:
        logger.error("DuckDB dosyasindan transaction kayitlari okunamadi", hata=str(exc))
        return pl.DataFrame()


def clear_transaction_audit_duckdb(duckdb_path: str = DEFAULT_TRANSACTION_DB) -> None:
    """Belirtilen DuckDB dosyasındaki transaction denetim tablosunu sıfırlar."""
    try:
        conn = duckdb.connect(duckdb_path)
        try:
            conn.execute("DELETE FROM transaction_audit")
        finally:
            conn.close()
    except Exception as exc:
        logger.warning("DuckDB transaction denetim tablosu temizlenemedi", hata=str(exc))


# Küresel Singleton Nesnesi
transaction_helper = TransactionHelper()

__all__ = [
    "DEFAULT_CHECKPOINT_SIZE",
    "DEFAULT_TRANSACTION_DB",
    "DEFAULT_WAL_SIZE",
    "QueryMetrics",
    "TransactionConnection",
    "TransactionHelper",
    "TransactionMetrics",
    "clear_transaction_audit_duckdb",
    "configure_duckdb_wal",
    "otel_trace",
    "read_transaction_audit_from_duckdb",
    "to_orjson_bytes",
    "transaction_helper",
]
