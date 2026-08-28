"""
ALPHA BIST â€” Database Transaction Helper

Atomic operations iÃ§in transaction yardÄ±mcÄ±sÄ±.

Ã–zellikler:
1. Atomic multi-operation transactions
2. Retry with exponential backoff
3. Nested transaction support (savepoints)
4. Query timeout
5. Performance tracking

Referanslar:
- CORE-NIHAI-SPEC.md - Section 2.2
"""

import asyncio
import hashlib
import time
from collections.abc import Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any

import structlog
import functools
from opentelemetry import trace

logger = structlog.get_logger(__name__)
tracer = trace.get_tracer("alpha-bist.transaction_helper")

def otel_trace(span_name: str):
    """Decorator to wrap a method in an OTel span."""
    def decorator(func):
        @functools.wraps(func)
        def wrapper(self, *args, **kwargs):
            with tracer.start_as_current_span(span_name):
                return func(self, *args, **kwargs)
        return wrapper
    return decorator


@dataclass
class TransactionMetrics:
    """Transaction metrikleri."""

    total_transactions: int = 0
    committed: int = 0
    rolled_back: int = 0
    retried: int = 0
    timed_out: int = 0
    total_duration_ms: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_transactions": self.total_transactions,
            "committed": self.committed,
            "rolled_back": self.rolled_back,
            "retried": self.retried,
            "timed_out": self.timed_out,
            "avg_duration_ms": round(self.total_duration_ms / max(self.total_transactions, 1), 2),
        }


@dataclass
class QueryMetrics:
    """Tek sorgu metrikleri."""

    query_hash: str
    duration_ms: float
    rows_affected: int = 0
    success: bool = True
    error: str | None = None


class TransactionHelper:
    """
    Database transaction yardÄ±mcÄ±sÄ±.

    Atomic operations, retry, timeout ve metrik takibi saÄŸlar.

    KullanÄ±m:
        helper = TransactionHelper(pg_pool)

        # Simple atomic
        async with helper.atomic() as tx:
            await tx.execute("UPDATE ...")
            await tx.execute("INSERT ...")

        # With retry
        async with helper.atomic_with_retry(max_retries=3) as tx:
            await tx.execute("UPDATE ...")
    """

    def __init__(
        self,
        pool: Any = None,
        default_timeout_seconds: float = 30.0,
        max_retries: int = 3,
        retry_base_delay: float = 1.0,
    ):
        self._pool = pool
        self._default_timeout = default_timeout_seconds
        self._max_retries = max_retries
        self._retry_base_delay = retry_base_delay
        self._metrics = TransactionMetrics()
        self._query_log: list[QueryMetrics] = []

    def set_pool(self, pool: Any):
        """Connection pool'u ayarla."""
        self._pool = pool

    @asynccontextmanager
    async def atomic(
        self,
        timeout_seconds: float | None = None,
        read_only: bool = False,
    ):
        """
        Atomic transaction context manager.

        Args:
            timeout_seconds: Zaman aÅŸÄ±mÄ±
            read_only: Salt okunur transaction

        Yields:
            Transaction connection

        Usage:
            async with helper.atomic() as tx:
                await tx.execute("UPDATE ...")
        """
        if self._pool is None:
            raise RuntimeError("Database pool not configured. Call set_pool() first.")

        timeout = timeout_seconds or self._default_timeout
        self._metrics.total_transactions += 1
        start_time = time.monotonic()

        conn = None
        tx = None
        try:
            conn = await self._pool.acquire()
            tx = conn.transaction(readonly=read_only)
            await tx.start()

            # Wrapped connection with metrics
            wrapped = TransactionConnection(conn, self._query_log)

            yield wrapped

            # Commit
            await tx.commit()
            self._metrics.committed += 1

            duration = (time.monotonic() - start_time) * 1000
            self._metrics.total_duration_ms += duration

            logger.debug("Transaction committed", duration_ms=round(duration, 2), queries=len(self._query_log))

        except TimeoutError:
            self._metrics.timed_out += 1
            if tx:
                await tx.rollback()
            logger.error("Transaction timeout", timeout_seconds=timeout)
            raise

        except Exception as e:
            self._metrics.rolled_back += 1
            if tx:
                try:
                    await tx.rollback()
                except Exception as e:
                    logger.debug("Handled exception", error=str(e), context="transaction_helper.py:160")
            logger.error("Transaction rollback", error=str(e))
            raise

        finally:
            if conn:
                try:
                    await self._pool.release(conn)
                except Exception as e:
                    logger.debug("Handled exception", error=str(e), context="transaction_helper.py:169")

    @asynccontextmanager
    async def atomic_with_retry(
        self,
        max_retries: int | None = None,
        timeout_seconds: float | None = None,
        read_only: bool = False,
    ):
        """
        Retry ile atomic transaction.

        Deadlock veya geÃ§ici hatalarda otomatik retry.

        Args:
            max_retries: Maksimum deneme sayÄ±sÄ±
            timeout_seconds: Zaman aÅŸÄ±mÄ±
            read_only: Salt okunur
        """
        retries = max_retries or self._max_retries
        last_error = None

        for attempt in range(retries + 1):
            try:
                async with self.atomic(timeout_seconds, read_only) as tx:
                    yield tx
                    return  # Success

            except Exception as e:
                last_error = e
                if attempt < retries:
                    delay = self._retry_base_delay * (2**attempt)
                    self._metrics.retried += 1
                    logger.warning(
                        "Transaction retry", attempt=attempt + 1, max_retries=retries, delay_seconds=delay, error=str(e)
                    )
                    await asyncio.sleep(delay)
                else:
                    logger.error("Transaction failed after retries", attempts=retries + 1, error=str(e))

        raise last_error

    @asynccontextmanager
    async def savepoint(self, conn: Any, name: str):
        """
        Nested transaction (savepoint).

        Inner transaction baÅŸarÄ±sÄ±z olursa sadece savepoint rollback olur.
        """
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
        operations: list[Callable],
        timeout_seconds: float | None = None,
    ) -> list[Any]:
        """
        Toplu atomic iÅŸlem.

        TÃ¼m operasyonlar tek transaction'da Ã§alÄ±ÅŸÄ±r.
        Birisi baÅŸarÄ±sÄ±zsa hepsi rollback olur.

        Args:
            operations: Callable listesi (conn parametreli)
            timeout_seconds: Zaman aÅŸÄ±mÄ±

        Returns:
            Her operasyonun dÃ¶nÃ¼ÅŸ deÄŸeri
        """
        results = []

        async with self.atomic(timeout_seconds) as tx:
            for op in operations:
                if asyncio.iscoroutinefunction(op):
                    result = await op(tx)
                else:
                    result = op(tx)
                results.append(result)

        return results

    def get_metrics(self) -> dict[str, Any]:
        """Transaction metrikleri."""
        return self._metrics.to_dict()

    def get_slow_queries(self, threshold_ms: float = 1000) -> list[dict[str, Any]]:
        """YavaÅŸ sorgularÄ± listele."""
        slow = [q for q in self._query_log if q.duration_ms > threshold_ms]
        return [
            {
                "query_hash": q.query_hash,
                "duration_ms": round(q.duration_ms, 2),
                "rows_affected": q.rows_affected,
                "success": q.success,
            }
            for q in slow[-50:]  # Son 50
        ]

    def reset_metrics(self):
        """Metrikleri sÄ±fÄ±rla."""
        self._metrics = TransactionMetrics()
        self._query_log.clear()


class TransactionConnection:
    """
    Transaction connection wrapper.

    Sorgu metriklerini otomatik toplar.
    """

    def __init__(self, conn: Any, query_log: list[QueryMetrics]):
        self._conn = conn
        self._query_log = query_log

    @otel_trace("transaction_connection.execute")
    async def execute(self, query: str, *args) -> Any:
        """Sorgu Ã§alÄ±ÅŸtÄ±r (metrics ile)."""
        start = time.monotonic()
        query_hash = hashlib.md5(query.encode()).hexdigest()[:8]

        try:
            result = await self._conn.execute(query, *args)
            duration = (time.monotonic() - start) * 1000

            self._query_log.append(
                QueryMetrics(
                    query_hash=query_hash,
                    duration_ms=duration,
                    success=True,
                )
            )

            return result

        except Exception as e:
            duration = (time.monotonic() - start) * 1000
            self._query_log.append(
                QueryMetrics(
                    query_hash=query_hash,
                    duration_ms=duration,
                    success=False,
                    error=str(e),
                )
            )
            raise

    @otel_trace("transaction_connection.fetch")
    async def fetch(self, query: str, *args) -> list[Any]:
        """Fetch sorgusu."""
        start = time.monotonic()
        query_hash = hashlib.md5(query.encode()).hexdigest()[:8]

        try:
            result = await self._conn.fetch(query, *args)
            duration = (time.monotonic() - start) * 1000

            self._query_log.append(
                QueryMetrics(
                    query_hash=query_hash,
                    duration_ms=duration,
                    rows_affected=len(result),
                    success=True,
                )
            )

            return result

        except Exception as e:
            duration = (time.monotonic() - start) * 1000
            self._query_log.append(
                QueryMetrics(
                    query_hash=query_hash,
                    duration_ms=duration,
                    success=False,
                    error=str(e),
                )
            )
            raise

    @otel_trace("transaction_connection.fetchval")
    async def fetchval(self, query: str, *args) -> Any:
        """Tek deÄŸer fetch."""
        start = time.monotonic()
        query_hash = hashlib.md5(query.encode()).hexdigest()[:8]

        try:
            result = await self._conn.fetchval(query, *args)
            duration = (time.monotonic() - start) * 1000

            self._query_log.append(
                QueryMetrics(
                    query_hash=query_hash,
                    duration_ms=duration,
                    success=True,
                )
            )

            return result

        except Exception as e:
            duration = (time.monotonic() - start) * 1000
            self._query_log.append(
                QueryMetrics(
                    query_hash=query_hash,
                    duration_ms=duration,
                    success=False,
                    error=str(e),
                )
            )
            raise


# Singleton
transaction_helper = TransactionHelper()

