"""
ALPHA BIST — Database Transaction Helper

Atomic operations için transaction yardımcısı.

Özellikler:
1. Atomic multi-operation transactions
2. Retry with exponential backoff
3. Nested transaction support (savepoints)
4. Query timeout
5. Performance tracking

Referanslar:
- CORE-NIHAI-SPEC.md - Section 2.2
"""

import asyncio
import time
from typing import Dict, List, Optional, Any, Callable
from dataclasses import dataclass
from contextlib import asynccontextmanager
import structlog

logger = structlog.get_logger()


@dataclass
class TransactionMetrics:
    """Transaction metrikleri."""
    total_transactions: int = 0
    committed: int = 0
    rolled_back: int = 0
    retried: int = 0
    timed_out: int = 0
    total_duration_ms: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "total_transactions": self.total_transactions,
            "committed": self.committed,
            "rolled_back": self.rolled_back,
            "retried": self.retried,
            "timed_out": self.timed_out,
            "avg_duration_ms": round(
                self.total_duration_ms / max(self.total_transactions, 1), 2
            ),
        }


@dataclass
class QueryMetrics:
    """Tek sorgu metrikleri."""
    query_hash: str
    duration_ms: float
    rows_affected: int = 0
    success: bool = True
    error: Optional[str] = None


class TransactionHelper:
    """
    Database transaction yardımcısı.

    Atomic operations, retry, timeout ve metrik takibi sağlar.

    Kullanım:
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
        self._query_log: List[QueryMetrics] = []

    def set_pool(self, pool: Any):
        """Connection pool'u ayarla."""
        self._pool = pool

    @asynccontextmanager
    async def atomic(
        self,
        timeout_seconds: Optional[float] = None,
        read_only: bool = False,
    ):
        """
        Atomic transaction context manager.

        Args:
            timeout_seconds: Zaman aşımı
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

            logger.debug("Transaction committed",
                        duration_ms=round(duration, 2),
                        queries=len(self._query_log))

        except asyncio.TimeoutError:
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
        max_retries: Optional[int] = None,
        timeout_seconds: Optional[float] = None,
        read_only: bool = False,
    ):
        """
        Retry ile atomic transaction.

        Deadlock veya geçici hatalarda otomatik retry.

        Args:
            max_retries: Maksimum deneme sayısı
            timeout_seconds: Zaman aşımı
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
                    delay = self._retry_base_delay * (2 ** attempt)
                    self._metrics.retried += 1
                    logger.warning("Transaction retry",
                                 attempt=attempt + 1,
                                 max_retries=retries,
                                 delay_seconds=delay,
                                 error=str(e))
                    await asyncio.sleep(delay)
                else:
                    logger.error("Transaction failed after retries",
                                attempts=retries + 1,
                                error=str(e))

        raise last_error

    @asynccontextmanager
    async def savepoint(self, conn: Any, name: str):
        """
        Nested transaction (savepoint).

        Inner transaction başarısız olursa sadece savepoint rollback olur.
        """
        sp_name = f"sp_{name}_{int(time.monotonic() * 1000)}"
        await conn.execute(f"SAVEPOINT {sp_name}")

        try:
            yield conn
            await conn.execute(f"RELEASE SAVEPOINT {sp_name}")
        except Exception:
            await conn.execute(f"ROLLBACK TO SAVEPOINT {sp_name}")
            raise

    async def execute_batch(
        self,
        operations: List[Callable],
        timeout_seconds: Optional[float] = None,
    ) -> List[Any]:
        """
        Toplu atomic işlem.

        Tüm operasyonlar tek transaction'da çalışır.
        Birisi başarısızsa hepsi rollback olur.

        Args:
            operations: Callable listesi (conn parametreli)
            timeout_seconds: Zaman aşımı

        Returns:
            Her operasyonun dönüş değeri
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

    def get_metrics(self) -> Dict[str, Any]:
        """Transaction metrikleri."""
        return self._metrics.to_dict()

    def get_slow_queries(self, threshold_ms: float = 1000) -> List[Dict[str, Any]]:
        """Yavaş sorguları listele."""
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
        """Metrikleri sıfırla."""
        self._metrics = TransactionMetrics()
        self._query_log.clear()


class TransactionConnection:
    """
    Transaction connection wrapper.

    Sorgu metriklerini otomatik toplar.
    """

    def __init__(self, conn: Any, query_log: List[QueryMetrics]):
        self._conn = conn
        self._query_log = query_log

    async def execute(self, query: str, *args) -> Any:
        """Sorgu çalıştır (metrics ile)."""
        start = time.monotonic()
        query_hash = hashlib.md5(query.encode()).hexdigest()[:8]

        try:
            result = await self._conn.execute(query, *args)
            duration = (time.monotonic() - start) * 1000

            self._query_log.append(QueryMetrics(
                query_hash=query_hash,
                duration_ms=duration,
                success=True,
            ))

            return result

        except Exception as e:
            duration = (time.monotonic() - start) * 1000
            self._query_log.append(QueryMetrics(
                query_hash=query_hash,
                duration_ms=duration,
                success=False,
                error=str(e),
            ))
            raise

    async def fetch(self, query: str, *args) -> List[Any]:
        """Fetch sorgusu."""
        start = time.monotonic()
        query_hash = hashlib.md5(query.encode()).hexdigest()[:8]

        try:
            result = await self._conn.fetch(query, *args)
            duration = (time.monotonic() - start) * 1000

            self._query_log.append(QueryMetrics(
                query_hash=query_hash,
                duration_ms=duration,
                rows_affected=len(result),
                success=True,
            ))

            return result

        except Exception as e:
            duration = (time.monotonic() - start) * 1000
            self._query_log.append(QueryMetrics(
                query_hash=query_hash,
                duration_ms=duration,
                success=False,
                error=str(e),
            ))
            raise

    async def fetchval(self, query: str, *args) -> Any:
        """Tek değer fetch."""
        start = time.monotonic()
        query_hash = hashlib.md5(query.encode()).hexdigest()[:8]

        try:
            result = await self._conn.fetchval(query, *args)
            duration = (time.monotonic() - start) * 1000

            self._query_log.append(QueryMetrics(
                query_hash=query_hash,
                duration_ms=duration,
                success=True,
            ))

            return result

        except Exception as e:
            duration = (time.monotonic() - start) * 1000
            self._query_log.append(QueryMetrics(
                query_hash=query_hash,
                duration_ms=duration,
                success=False,
                error=str(e),
            ))
            raise


# Singleton
transaction_helper = TransactionHelper()
