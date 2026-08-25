"""
ALPHA BIST — Persistent Dead Letter Queue v1.0

SQLite tabanlı DLQ — restart sonrası kaybolmaz.
In-memory DLQ'nun dayanıklı versiyonu.

Özellikler:
- SQLite WAL mode (crash-safe)
- Atomic write
- Retry with exponential backoff
- Max retry limiti
- Cleanup (eski kayıtları temizle)
- In-memory DLQ ile uyumlu API

Kullanım:
    from services.core.persistent_dlq import persistent_dlq

    await persistent_dlq.push(event_id, event_type, payload, error)
    retried = await persistent_dlq.retry_failed()
    stats = await persistent_dlq.get_stats()
"""

import asyncio
import hashlib
import os
import sqlite3
import time
from contextlib import contextmanager
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Any, Callable
from dataclasses import dataclass
from enum import Enum
import structlog

import orjson

logger = structlog.get_logger()


class DLQStatus(str, Enum):
    PENDING = "PENDING"
    RETRYING = "RETRYING"
    RESOLVED = "RESOLVED"
    EXHAUSTED = "EXHAUSTED"


class PersistentDeadLetterQueue:
    """SQLite tabanlı kalıcı Dead Letter Queue.

    Restart sonrası veri kaybolmaz.
    """

    def __init__(self, db_path: str = "data/dlq.db", max_entries: int = 50000):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._max_entries = max_entries
        self._retry_handlers: Dict[str, Callable] = {}
        self._init_db()

        # Stats
        self._total_pushed = 0
        self._total_retried = 0
        self._total_resolved = 0
        self._total_exhausted = 0

        logger.info("PersistentDLQ initialized", db_path=str(self.db_path))

    def _init_db(self):
        """SQLite tablolarını oluştur."""
        with self._connect() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS dlq_entries (
                    entry_id TEXT PRIMARY KEY,
                    event_id TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    error TEXT NOT NULL,
                    retry_count INTEGER DEFAULT 0,
                    max_retries INTEGER DEFAULT 3,
                    status TEXT DEFAULT 'PENDING',
                    created_at TEXT NOT NULL,
                    last_retry_at TEXT,
                    next_retry_at TEXT,
                    resolved_at TEXT
                );

                CREATE INDEX IF NOT EXISTS idx_dlq_status ON dlq_entries(status);
                CREATE INDEX IF NOT EXISTS idx_dlq_type ON dlq_entries(event_type);
                CREATE INDEX IF NOT EXISTS idx_dlq_created ON dlq_entries(created_at);
                CREATE INDEX IF NOT EXISTS idx_dlq_next_retry ON dlq_entries(next_retry_at);

                CREATE TABLE IF NOT EXISTS dlq_stats (
                    key TEXT PRIMARY KEY,
                    value INTEGER DEFAULT 0
                );
            """)
            conn.commit()

    @contextmanager
    def _connect(self):
        conn = sqlite3.connect(str(self.db_path), timeout=30.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        try:
            yield conn
        finally:
            conn.close()

    def register_retry_handler(self, event_type: str, handler: Callable):
        """Event type için retry handler kaydet."""
        self._retry_handlers[event_type] = handler

    async def push(
        self,
        event_id: str,
        event_type: str,
        payload: str,
        error: str,
        retry_count: int = 0,
        max_retries: int = 3,
    ) -> str:
        """Başarısız event'i DLQ'ya kaydet."""
        entry_id = hashlib.md5(
            f"dlq_{event_id}_{time.time()}".encode()
        ).hexdigest()[:16]

        backoff_seconds = 5 * (2 ** retry_count)
        next_retry = datetime.now(timezone.utc) + timedelta(seconds=backoff_seconds)

        with self._connect() as conn:
            conn.execute("""
                INSERT OR REPLACE INTO dlq_entries
                (entry_id, event_id, event_type, payload, error, retry_count,
                 max_retries, status, created_at, next_retry_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, 'PENDING', ?, ?)
            """, (
                entry_id, event_id, event_type, payload, error,
                retry_count, max_retries,
                datetime.now(timezone.utc).isoformat(),
                next_retry.isoformat(),
            ))
            conn.commit()

        self._total_pushed += 1
        logger.warning("Event pushed to persistent DLQ",
                      entry_id=entry_id, event_type=event_type,
                      retry_count=retry_count)
        return entry_id

    async def retry_failed(self, batch_size: int = 100) -> int:
        """DLQ'daki retry edilebilir event'leri tekrar dene."""
        retried = 0
        now = datetime.now(timezone.utc).isoformat()

        with self._connect() as conn:
            rows = conn.execute("""
                SELECT * FROM dlq_entries
                WHERE status = 'PENDING'
                AND (next_retry_at IS NULL OR next_retry_at <= ?)
                AND retry_count < max_retries
                ORDER BY created_at ASC
                LIMIT ?
            """, (now, batch_size)).fetchall()

            for row in rows:
                entry = dict(row)
                handler = self._retry_handlers.get(entry["event_type"])

                if handler:
                    try:
                        conn.execute(
                            "UPDATE dlq_entries SET status = 'RETRYING' WHERE entry_id = ?",
                            (entry["entry_id"],)
                        )
                        conn.commit()

                        if asyncio.iscoroutinefunction(handler):
                            await handler(entry["payload"])
                        else:
                            handler(entry["payload"])

                        # Başarılı
                        conn.execute("""
                            UPDATE dlq_entries SET status = 'RESOLVED', resolved_at = ?
                            WHERE entry_id = ?
                        """, (datetime.now(timezone.utc).isoformat(), entry["entry_id"]))
                        conn.commit()

                        self._total_resolved += 1
                        self._total_retried += 1
                        retried += 1

                    except Exception as e:
                        # Retry başarısız
                        new_count = entry["retry_count"] + 1
                        if new_count >= entry["max_retries"]:
                            conn.execute("""
                                UPDATE dlq_entries SET status = 'EXHAUSTED',
                                retry_count = ?, error = ?
                                WHERE entry_id = ?
                            """, (new_count, str(e), entry["entry_id"]))
                            self._total_exhausted += 1
                        else:
                            backoff = 5 * (2 ** new_count)
                            next_retry = (datetime.now(timezone.utc) +
                                        timedelta(seconds=backoff)).isoformat()
                            conn.execute("""
                                UPDATE dlq_entries SET status = 'PENDING',
                                retry_count = ?, error = ?, next_retry_at = ?
                                WHERE entry_id = ?
                            """, (new_count, str(e), next_retry, entry["entry_id"]))
                        conn.commit()
                else:
                    # Handler yok
                    conn.execute("""
                        UPDATE dlq_entries SET status = 'EXHAUSTED' WHERE entry_id = ?
                    """, (entry["entry_id"],))
                    conn.commit()
                    self._total_exhausted += 1

        # Eski resolved kayıtları temizle
        self._cleanup_resolved()

        return retried

    async def get_stats(self) -> Dict[str, Any]:
        """DLQ istatistikleri."""
        with self._connect() as conn:
            by_status = {}
            rows = conn.execute("""
                SELECT status, COUNT(*) as cnt FROM dlq_entries GROUP BY status
            """).fetchall()
            for row in rows:
                by_status[row["status"]] = row["cnt"]

            by_type = {}
            rows = conn.execute("""
                SELECT event_type, COUNT(*) as cnt FROM dlq_entries GROUP BY event_type
            """).fetchall()
            for row in rows:
                by_type[row["event_type"]] = row["cnt"]

            total = conn.execute("SELECT COUNT(*) as cnt FROM dlq_entries").fetchone()["cnt"]

        return {
            "total_entries": total,
            "by_status": by_status,
            "by_event_type": by_type,
            "lifetime": {
                "total_pushed": self._total_pushed,
                "total_retried": self._total_retried,
                "total_resolved": self._total_resolved,
                "total_exhausted": self._total_exhausted,
            },
            "db_path": str(self.db_path),
            "persistent": True,
        }

    async def get_entries(
        self,
        status: Optional[str] = None,
        event_type: Optional[str] = None,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        """DLQ kayıtlarını listele."""
        with self._connect() as conn:
            query = "SELECT * FROM dlq_entries WHERE 1=1"
            params = []

            if status:
                query += " AND status = ?"
                params.append(status)
            if event_type:
                query += " AND event_type = ?"
                params.append(event_type)

            query += " ORDER BY created_at DESC LIMIT ?"
            params.append(limit)

            rows = conn.execute(query, params).fetchall()
            return [dict(r) for r in rows]

    async def clear(self) -> int:
        """Tüm DLQ'yı temizle."""
        with self._connect() as conn:
            count = conn.execute("SELECT COUNT(*) as cnt FROM dlq_entries").fetchone()["cnt"]
            conn.execute("DELETE FROM dlq_entries")
            conn.commit()
        return count

    def _cleanup_resolved(self):
        """Çözülmüş kayıtları temizle (son 24 saat tut)."""
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
        with self._connect() as conn:
            conn.execute("""
                DELETE FROM dlq_entries
                WHERE status = 'RESOLVED' AND resolved_at < ?
            """, (cutoff,))
            conn.commit()

    def _evict_oldest(self):
        """Max entries aşıldığında en eski kayıtları çıkar."""
        with self._connect() as conn:
            count = conn.execute("SELECT COUNT(*) as cnt FROM dlq_entries").fetchone()["cnt"]
            if count > self._max_entries:
                excess = count - self._max_entries
                conn.execute("""
                    DELETE FROM dlq_entries WHERE entry_id IN (
                        SELECT entry_id FROM dlq_entries
                        WHERE status IN ('RESOLVED', 'EXHAUSTED')
                        ORDER BY created_at ASC LIMIT ?
                    )
                """, (excess,))
                conn.commit()


# Singleton
persistent_dlq = PersistentDeadLetterQueue()
