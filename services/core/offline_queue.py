"""
ALPHA BIST — Offline Queue v1.0

İnternet yokken üretilen sinyalleri kuyruğa alır.
İnternet gelince otomatik gönderir.

Kişisel PC senaryosu:
- İnternet kesildiğinde üretilen alım/satım sinyalleri kaybolmaz
- İnternet geldiğinde kuyruktaki tüm event'ler gönderilir
- SQLite tabanlı — restart sonrası kaybolmaz
- FIFO sırası korunur
- TTL ile eski event'ler expire olur

Kullanım:
    from services.core.offline_queue import offline_queue

    # İnternet yokken
    await offline_queue.enqueue(event_type, payload)

    # İnternet geldiğinde (otomatik tetiklenir)
    flushed = await offline_queue.flush()
"""

import asyncio
import functools
import hashlib
import time
from collections.abc import Callable
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import duckdb
import orjson
import structlog
from opentelemetry import trace

logger = structlog.get_logger(__name__)
tracer = trace.get_tracer("alpha-bist.offline_queue")


def otel_trace(span_name: str) -> Any:
    """Decorator to wrap a method in an OTel span."""

    def decorator(func) -> Any:
        """Otomatik eklendi."""
        @functools.wraps(func)
        def wrapper(self, *args, **kwargs) -> Any:
            """Otomatik eklendi."""
            with tracer.start_as_current_span(span_name):
                return func(self, *args, **kwargs)

        return wrapper

    return decorator


class OfflineQueue:
    """SQLite tabanlı offline event kuyruğu.

    İnternet yokken üretilen event'leri saklar,
    internet gelince otomatik gönderir.
    """

    def __init__(
        self,
        db_path: str = "data/offline_queue.db",
        max_entries: int = 10000,
        default_ttl_hours: int = 48,
    ):
        """Otomatik eklendi."""
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._max_entries = max_entries
        self._default_ttl_hours = default_ttl_hours
        self._publish_handlers: dict[str, Callable] = {}
        self._flushing = False
        self._init_db()

        # Stats
        self._total_enqueued = 0
        self._total_flushed = 0
        self._total_expired = 0

        logger.info("OfflineQueue initialized", db_path=str(self.db_path))

    def _init_db(self) -> Any:
        """SQLite tablolarını oluştur."""
        with self._connect() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS offline_queue (
                    entry_id TEXT PRIMARY KEY,
                    event_type TEXT NOT NULL,
                    subject TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    priority INTEGER DEFAULT 5,
                    created_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    attempts INTEGER DEFAULT 0,
                    last_error TEXT
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_oq_created ON offline_queue(created_at)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_oq_expires ON offline_queue(expires_at)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_oq_type ON offline_queue(event_type)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_oq_priority ON offline_queue(priority)")
            conn.commit()

    @contextmanager
    def _connect(self) -> Any:
        """Otomatik eklendi."""
        conn = duckdb.connect(str(self.db_path))
        # SSD write reduction: DuckDB WAL ayarları
        try:
            from services.core.debounce import configure_duckdb_wal
            configure_duckdb_wal(conn)
        except Exception:
            logger.debug("Silent exception caught", exc_info=True)
        try:
            yield conn
        finally:
            conn.close()

    @otel_trace("offline_queue.register_publish_handler")
    def register_publish_handler(self, event_type: str, handler: Callable) -> Any:
        """Event type için publish handler kaydet."""
        self._publish_handlers[event_type] = handler

    @otel_trace("offline_queue.enqueue")
    async def enqueue(
        self,
        event_type: str,
        payload: dict[str, Any],
        subject: str = "alpha.offline",
        priority: int = 5,
        ttl_hours: int | None = None,
    ) -> str:
        """Event'i kuyruğa ekle."""
        entry_id = hashlib.md5(f"oq_{event_type}_{time.time()}_{id(payload)}".encode()).hexdigest()[:16]

        ttl = ttl_hours or self._default_ttl_hours
        expires_at = datetime.now(UTC) + timedelta(hours=ttl)

        payload_json = orjson.dumps(payload, default=str).decode()

        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO offline_queue
                (entry_id, event_type, subject, payload, priority, created_at, expires_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
                (
                    entry_id,
                    event_type,
                    subject,
                    payload_json,
                    priority,
                    datetime.now(UTC).isoformat(),
                    expires_at.isoformat(),
                ),
            )
            # SSD write reduction: enqueue'da commit yok, flush'ta toplu commit
            # conn.commit()

        self._total_enqueued += 1
        logger.info("Event queued for offline delivery", entry_id=entry_id, event_type=event_type, priority=priority)
        return entry_id

    @otel_trace("offline_queue.flush")
    async def flush(self) -> int:
        """Kuyruktaki tüm event'leri gönder.

        İnternet geldiğinde otomatik tetiklenir.
        FIFO + priority sırasıyla gönderir.
        """
        if self._flushing:
            return 0

        self._flushing = True
        flushed = 0

        try:
            # Önce expire olmuş kayıtları temizle
            self._cleanup_expired()

            with self._connect() as conn:
                rows = conn.execute("""
                    SELECT * FROM offline_queue
                    ORDER BY priority ASC, created_at ASC
                """).fetchall()

                for row in rows:
                    entry = dict(row)
                    handler = self._publish_handlers.get(entry["event_type"])

                    if handler:
                        try:
                            payload = orjson.loads(entry["payload"])

                            if asyncio.iscoroutinefunction(handler):
                                await handler(entry["subject"], payload)
                            else:
                                handler(entry["subject"], payload)

                            # Başarılı — kuyruktan çıkar
                            conn.execute("DELETE FROM offline_queue WHERE entry_id = ?", (entry["entry_id"],))
                            flushed += 1
                            self._total_flushed += 1

                        except Exception as e:
                            # Başarısız — attempt sayısını artır
                            conn.execute(
                                """
                                UPDATE offline_queue
                                SET attempts = attempts + 1, last_error = ?
                                WHERE entry_id = ?
                            """,
                                (str(e)[:200], entry["entry_id"]),
                            )

                            # 5 denemeden fazla başarısızsa çıkar
                            if entry["attempts"] >= 5:
                                conn.execute("DELETE FROM offline_queue WHERE entry_id = ?", (entry["entry_id"],))
                                logger.warning("Offline queue entry exhausted", entry_id=entry["entry_id"])

                    else:
                        # Handler yok — çıkar
                        conn.execute("DELETE FROM offline_queue WHERE entry_id = ?", (entry["entry_id"],))

                conn.commit()

            if flushed > 0:
                logger.info("Offline queue flushed", count=flushed)

        except Exception as e:
            logger.error("Offline queue flush error", error=str(e))
        finally:
            self._flushing = False

        return flushed

    def _cleanup_expired(self) -> Any:
        """Süresi dolmuş kayıtları temizle."""
        now = datetime.now(UTC).isoformat()
        with self._connect() as conn:
            cursor = conn.execute("DELETE FROM offline_queue WHERE expires_at <= ?", (now,))
            expired = cursor.rowcount
            conn.commit()
            if expired > 0:
                self._total_expired += expired
                logger.debug("Expired offline entries cleaned", count=expired)

    @otel_trace("offline_queue.get_stats")
    async def get_stats(self) -> dict[str, Any]:
        """Kuyruk istatistikleri."""
        with self._connect() as conn:
            total = conn.execute("SELECT COUNT(*) as cnt FROM offline_queue").fetchone()["cnt"]

            by_type = {}
            rows = conn.execute("""
                SELECT event_type, COUNT(*) as cnt FROM offline_queue GROUP BY event_type
            """).fetchall()
            for row in rows:
                by_type[row["event_type"]] = row["cnt"]

        return {
            "pending_entries": total,
            "by_event_type": by_type,
            "lifetime": {
                "total_enqueued": self._total_enqueued,
                "total_flushed": self._total_flushed,
                "total_expired": self._total_expired,
            },
            "db_path": str(self.db_path),
            "flushing": self._flushing,
        }

    @otel_trace("offline_queue.get_entries")
    async def get_entries(self, limit: int = 50) -> list[dict[str, Any]]:
        """Kuyruktaki kayıtları listele."""
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM offline_queue
                ORDER BY priority ASC, created_at ASC
                LIMIT ?
            """,
                (limit,),
            ).fetchall()
            return [dict(r) for r in rows]

    @otel_trace("offline_queue.clear")
    async def clear(self) -> int:
        """Tüm kuyruğu temizle."""
        with self._connect() as conn:
            count = conn.execute("SELECT COUNT(*) as cnt FROM offline_queue").fetchone()["cnt"]
            conn.execute("DELETE FROM offline_queue")
            conn.commit()
        return count


# Singleton
offline_queue = OfflineQueue()
