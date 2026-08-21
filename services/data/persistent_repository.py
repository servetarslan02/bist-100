"""
ALPHA BIST — Persistent Historical Repository

SQLite tabanlı historical veri deposu.

Mevcut proje altyapısındaki persistence yapısını kullanır.
Incremental ingestion, deduplication, PIT-safe sorgulama destekler.
"""

import sqlite3
import json
import hashlib
from typing import Dict, List, Optional, Any
from datetime import datetime, timezone
from pathlib import Path
import structlog

from .historical_contracts import (
    HistoricalDataRepository, FundamentalSnapshot,
    EventSnapshot, CatalystSnapshot,
)

logger = structlog.get_logger()


class PersistentHistoricalRepository(HistoricalDataRepository):
    """SQLite tabanlı historical repository."""

    def __init__(self, db_path: str = "historical_data.db"):
        self._db_path = db_path
        self._conn = None
        self._init_db()

    def _get_conn(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = sqlite3.connect(self._db_path)
            self._conn.row_factory = sqlite3.Row
            self._conn.execute("PRAGMA journal_mode=WAL")
        return self._conn

    def _init_db(self):
        """Tabloları oluştur."""
        conn = self._get_conn()
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS fundamental_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ticker TEXT NOT NULL,
                period_end TEXT NOT NULL,
                available_at TEXT NOT NULL,
                values_json TEXT NOT NULL,
                source TEXT DEFAULT 'unknown',
                status TEXT DEFAULT 'FRESH',
                fetched_at TEXT NOT NULL,
                checksum TEXT,
                UNIQUE(ticker, period_end, available_at)
            );

            CREATE TABLE IF NOT EXISTS event_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_id TEXT NOT NULL,
                ticker TEXT NOT NULL,
                published_at TEXT NOT NULL,
                event_type TEXT NOT NULL,
                title TEXT DEFAULT '',
                sentiment REAL DEFAULT 0.0,
                importance REAL DEFAULT 0.5,
                source TEXT DEFAULT 'unknown',
                content TEXT DEFAULT '',
                fetched_at TEXT NOT NULL,
                checksum TEXT,
                UNIQUE(event_id)
            );

            CREATE TABLE IF NOT EXISTS catalyst_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_id TEXT NOT NULL,
                ticker TEXT NOT NULL,
                announcement_date TEXT NOT NULL,
                event_date TEXT NOT NULL,
                catalyst_type TEXT NOT NULL,
                importance REAL DEFAULT 0.5,
                source TEXT DEFAULT 'unknown',
                fetched_at TEXT NOT NULL,
                checksum TEXT,
                UNIQUE(event_id)
            );

            CREATE TABLE IF NOT EXISTS ingestion_state (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_fund_ticker_date
                ON fundamental_snapshots(ticker, available_at);
            CREATE INDEX IF NOT EXISTS idx_event_ticker_date
                ON event_snapshots(ticker, published_at);
            CREATE INDEX IF NOT EXISTS idx_catalyst_ticker_date
                ON catalyst_snapshots(ticker, announcement_date);
        """)
        conn.commit()

    # === QUERY METHODS ===

    def get_fundamental_snapshots(
        self, ticker: str, as_of_date: str,
    ) -> List[FundamentalSnapshot]:
        conn = self._get_conn()
        rows = conn.execute(
            """SELECT * FROM fundamental_snapshots
               WHERE ticker = ? AND available_at <= ?
               ORDER BY available_at DESC""",
            (ticker, as_of_date)
        ).fetchall()

        return [FundamentalSnapshot(
            ticker=row['ticker'],
            period_end=row['period_end'],
            available_at=row['available_at'],
            values=json.loads(row['values_json']),
            source=row['source'],
            status=row['status'],
        ) for row in rows]

    def get_event_snapshots(
        self, ticker: str, as_of_date: str,
        event_types: Optional[List[str]] = None,
    ) -> List[EventSnapshot]:
        conn = self._get_conn()
        if event_types:
            placeholders = ','.join('?' * len(event_types))
            rows = conn.execute(
                f"""SELECT * FROM event_snapshots
                    WHERE ticker = ? AND published_at <= ?
                    AND event_type IN ({placeholders})
                    ORDER BY published_at DESC""",
                [ticker, as_of_date] + list(event_types)
            ).fetchall()
        else:
            rows = conn.execute(
                """SELECT * FROM event_snapshots
                   WHERE ticker = ? AND published_at <= ?
                   ORDER BY published_at DESC""",
                (ticker, as_of_date)
            ).fetchall()

        return [EventSnapshot(
            event_id=row['event_id'],
            ticker=row['ticker'],
            published_at=row['published_at'],
            event_type=row['event_type'],
            title=row['title'],
            sentiment=row['sentiment'],
            importance=row['importance'],
            source=row['source'],
            content=row['content'],
        ) for row in rows]

    def get_catalyst_snapshots(
        self, ticker: str, as_of_date: str,
    ) -> List[CatalystSnapshot]:
        conn = self._get_conn()
        rows = conn.execute(
            """SELECT * FROM catalyst_snapshots
               WHERE ticker = ? AND announcement_date <= ?
               ORDER BY announcement_date DESC""",
            (ticker, as_of_date)
        ).fetchall()

        return [CatalystSnapshot(
            event_id=row['event_id'],
            ticker=row['ticker'],
            announcement_date=row['announcement_date'],
            event_date=row['event_date'],
            catalyst_type=row['catalyst_type'],
            importance=row['importance'],
            source=row['source'],
        ) for row in rows]

    # === INGESTION METHODS ===

    def add_fundamental_snapshot(self, snapshot: FundamentalSnapshot) -> bool:
        """Fundamental snapshot ekle (duplicate kontrolü ile)."""
        conn = self._get_conn()
        now = datetime.now(timezone.utc).isoformat()
        values_json = json.dumps(snapshot.values, sort_keys=True)
        checksum = hashlib.md5(values_json.encode()).hexdigest()

        try:
            conn.execute(
                """INSERT OR REPLACE INTO fundamental_snapshots
                   (ticker, period_end, available_at, values_json, source, status, fetched_at, checksum)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (snapshot.ticker, snapshot.period_end, snapshot.available_at,
                 values_json, snapshot.source, snapshot.status, now, checksum)
            )
            conn.commit()
            return True
        except Exception as e:
            logger.error("Failed to add fundamental snapshot",
                        ticker=snapshot.ticker, error=str(e))
            return False

    def add_event_snapshot(self, snapshot: EventSnapshot) -> bool:
        """Event snapshot ekle (duplicate kontrolü ile)."""
        conn = self._get_conn()
        now = datetime.now(timezone.utc).isoformat()
        checksum = hashlib.md5(
            f"{snapshot.event_id}:{snapshot.title}".encode()
        ).hexdigest()

        try:
            conn.execute(
                """INSERT OR IGNORE INTO event_snapshots
                   (event_id, ticker, published_at, event_type, title,
                    sentiment, importance, source, content, fetched_at, checksum)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (snapshot.event_id, snapshot.ticker, snapshot.published_at,
                 snapshot.event_type, snapshot.title, snapshot.sentiment,
                 snapshot.importance, snapshot.source, snapshot.content,
                 now, checksum)
            )
            conn.commit()
            return True
        except Exception as e:
            logger.error("Failed to add event snapshot",
                        event_id=snapshot.event_id, error=str(e))
            return False

    def add_catalyst_snapshot(self, snapshot: CatalystSnapshot) -> bool:
        """Catalyst snapshot ekle (duplicate kontrolü ile)."""
        conn = self._get_conn()
        now = datetime.now(timezone.utc).isoformat()
        checksum = hashlib.md5(
            f"{snapshot.event_id}:{snapshot.catalyst_type}".encode()
        ).hexdigest()

        try:
            conn.execute(
                """INSERT OR IGNORE INTO catalyst_snapshots
                   (event_id, ticker, announcement_date, event_date,
                    catalyst_type, importance, source, fetched_at, checksum)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (snapshot.event_id, snapshot.ticker, snapshot.announcement_date,
                 snapshot.event_date, snapshot.catalyst_type, snapshot.importance,
                 snapshot.source, now, checksum)
            )
            conn.commit()
            return True
        except Exception as e:
            logger.error("Failed to add catalyst snapshot",
                        event_id=snapshot.event_id, error=str(e))
            return False

    # === INGESTION STATE ===

    def get_last_ingestion_time(self, key: str) -> Optional[str]:
        """Son ingestion timestamp'ini getir."""
        conn = self._get_conn()
        row = conn.execute(
            "SELECT value FROM ingestion_state WHERE key = ?",
            (key,)
        ).fetchone()
        return row['value'] if row else None

    def set_last_ingestion_time(self, key: str, timestamp: str):
        """Son ingestion timestamp'ini kaydet."""
        conn = self._get_conn()
        now = datetime.now(timezone.utc).isoformat()
        conn.execute(
            """INSERT OR REPLACE INTO ingestion_state (key, value, updated_at)
               VALUES (?, ?, ?)""",
            (key, timestamp, now)
        )
        conn.commit()

    # === STATISTICS ===

    def get_stats(self) -> Dict[str, Any]:
        """Repository istatistikleri."""
        conn = self._get_conn()
        fund_count = conn.execute("SELECT COUNT(*) FROM fundamental_snapshots").fetchone()[0]
        event_count = conn.execute("SELECT COUNT(*) FROM event_snapshots").fetchone()[0]
        catalyst_count = conn.execute("SELECT COUNT(*) FROM catalyst_snapshots").fetchone()[0]

        fund_tickers = conn.execute(
            "SELECT COUNT(DISTINCT ticker) FROM fundamental_snapshots"
        ).fetchone()[0]
        event_tickers = conn.execute(
            "SELECT COUNT(DISTINCT ticker) FROM event_snapshots"
        ).fetchone()[0]

        return {
            "fundamental_snapshots": fund_count,
            "event_snapshots": event_count,
            "catalyst_snapshots": catalyst_count,
            "fundamental_tickers": fund_tickers,
            "event_tickers": event_tickers,
        }

    def close(self):
        if self._conn:
            self._conn.close()
            self._conn = None


# Singleton Instance
persistent_repository = PersistentHistoricalRepository()
