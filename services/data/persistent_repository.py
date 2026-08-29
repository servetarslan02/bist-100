"""
ALPHA BIST — Persistent Historical Repository

DuckDB tabanlı historical veri deposu.

Mevcut proje altyapısındaki persistence yapısını kullanır.
Incremental ingestion, deduplication, PIT-safe sorgulama destekler.
"""

import hashlib
from datetime import UTC, datetime
from typing import Any

import duckdb
import orjson
import structlog

from .historical_contracts import (
    CatalystSnapshot,
    EventSnapshot,
    FundamentalSnapshot,
    HistoricalDataRepository,
)

logger = structlog.get_logger()


class PersistentHistoricalRepository(HistoricalDataRepository):
    """SQLite tabanlı historical repository."""

    def __init__(self, db_path: str = "historical_data.db"):
        self._db_path = db_path
        self._conn = None
        self._init_db()

    def _get_conn(self) -> duckdb.DuckDBPyConnection:
        if self._conn is None:
            self._conn = duckdb.connect(self._db_path)
            self._conn.execute("SET enable_progress_bar = false")
        return self._conn

    def _fetchall_dicts(self, conn, query: str, params: tuple = ()) -> list[dict]:
        """DuckDB'den dict listesi olarak sonuç çek."""
        result = conn.execute(query, params)
        columns = [desc[0] for desc in result.description]
        return [dict(zip(columns, row)) for row in result.fetchall()]

    def _init_db(self):
        """Tabloları oluştur."""
        conn = self._get_conn()
        conn.execute("CREATE SEQUENCE IF NOT EXISTS fundamental_snapshots_seq START 1")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS fundamental_snapshots (
                id BIGINT PRIMARY KEY DEFAULT nextval('fundamental_snapshots_seq'),
                ticker TEXT NOT NULL,
                period_end TEXT NOT NULL,
                available_at TEXT NOT NULL,
                values_json TEXT NOT NULL,
                source TEXT DEFAULT 'unknown',
                status TEXT DEFAULT 'FRESH',
                fetched_at TEXT NOT NULL,
                checksum TEXT,
                UNIQUE(ticker, period_end, available_at)
            )
        """)
        conn.execute("CREATE SEQUENCE IF NOT EXISTS event_snapshots_seq START 1")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS event_snapshots (
                id BIGINT PRIMARY KEY DEFAULT nextval('event_snapshots_seq'),
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
            )
        """)
        conn.execute("CREATE SEQUENCE IF NOT EXISTS catalyst_snapshots_seq START 1")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS catalyst_snapshots (
                id BIGINT PRIMARY KEY DEFAULT nextval('catalyst_snapshots_seq'),
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
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS ingestion_state (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_fund_ticker_date ON fundamental_snapshots(ticker, available_at)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_event_ticker_date ON event_snapshots(ticker, published_at)")
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_catalyst_ticker_date ON catalyst_snapshots(ticker, announcement_date)"
        )
        conn.commit()

    # === QUERY METHODS ===

    def get_fundamental_snapshots(
        self,
        ticker: str,
        as_of_date: str,
    ) -> list[FundamentalSnapshot]:
        conn = self._get_conn()
        rows = self._fetchall_dicts(
            conn,
            """SELECT * FROM fundamental_snapshots
               WHERE ticker = ? AND available_at <= ?
               ORDER BY available_at DESC""",
            (ticker, as_of_date),
        )

        return [
            FundamentalSnapshot(
                ticker=row["ticker"],
                period_end=row["period_end"],
                available_at=row["available_at"],
                values=orjson.loads(row["values_json"]),
                source=row["source"],
                status=row["status"],
            )
            for row in rows
        ]

    def get_event_snapshots(
        self,
        ticker: str,
        as_of_date: str,
        event_types: list[str] | None = None,
    ) -> list[EventSnapshot]:
        conn = self._get_conn()
        if event_types:
            placeholders = ",".join("?" * len(event_types))
            rows = self._fetchall_dicts(
                conn,
                f"""SELECT * FROM event_snapshots
                    WHERE ticker = ? AND published_at <= ?
                    AND event_type IN ({placeholders})
                    ORDER BY published_at DESC""",
                [ticker, as_of_date] + list(event_types),
            )
        else:
            rows = self._fetchall_dicts(
                conn,
                """SELECT * FROM event_snapshots
                   WHERE ticker = ? AND published_at <= ?
                   ORDER BY published_at DESC""",
                (ticker, as_of_date),
            )

        return [
            EventSnapshot(
                event_id=row["event_id"],
                ticker=row["ticker"],
                published_at=row["published_at"],
                event_type=row["event_type"],
                title=row["title"],
                sentiment=row["sentiment"],
                importance=row["importance"],
                source=row["source"],
                content=row["content"],
            )
            for row in rows
        ]

    def get_catalyst_snapshots(
        self,
        ticker: str,
        as_of_date: str,
    ) -> list[CatalystSnapshot]:
        conn = self._get_conn()
        rows = self._fetchall_dicts(
            conn,
            """SELECT * FROM catalyst_snapshots
               WHERE ticker = ? AND announcement_date <= ?
               ORDER BY announcement_date DESC""",
            (ticker, as_of_date),
        )

        return [
            CatalystSnapshot(
                event_id=row["event_id"],
                ticker=row["ticker"],
                announcement_date=row["announcement_date"],
                event_date=row["event_date"],
                catalyst_type=row["catalyst_type"],
                importance=row["importance"],
                source=row["source"],
            )
            for row in rows
        ]

    # === INGESTION METHODS ===

    def add_fundamental_snapshot(self, snapshot: FundamentalSnapshot) -> bool:
        """Fundamental snapshot ekle (duplicate kontrolü ile)."""
        conn = self._get_conn()
        now = datetime.now(UTC).isoformat()
        values_json = orjson.dumps(snapshot.values, option=orjson.OPT_SORT_KEYS).decode()
        checksum = hashlib.md5(values_json.encode()).hexdigest()

        try:
            conn.execute(
                """INSERT INTO fundamental_snapshots
                   (ticker, period_end, available_at, values_json, source, status, fetched_at, checksum)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(ticker, period_end, available_at)
                   DO UPDATE SET
                       values_json = excluded.values_json,
                       source = excluded.source,
                       status = excluded.status,
                       fetched_at = excluded.fetched_at,
                       checksum = excluded.checksum""",
                (
                    snapshot.ticker,
                    snapshot.period_end,
                    snapshot.available_at,
                    values_json,
                    snapshot.source,
                    snapshot.status,
                    now,
                    checksum,
                ),
            )
            conn.commit()
            return True
        except Exception as e:
            logger.error("Failed to add fundamental snapshot", ticker=snapshot.ticker, error=str(e))
            return False

    def add_event_snapshot(self, snapshot: EventSnapshot) -> bool:
        """Event snapshot ekle (duplicate kontrolü ile)."""
        conn = self._get_conn()
        now = datetime.now(UTC).isoformat()
        checksum = hashlib.md5(f"{snapshot.event_id}:{snapshot.title}".encode()).hexdigest()

        try:
            conn.execute(
                """INSERT INTO event_snapshots
                   (event_id, ticker, published_at, event_type, title,
                    sentiment, importance, source, content, fetched_at, checksum)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(event_id) DO NOTHING""",
                (
                    snapshot.event_id,
                    snapshot.ticker,
                    snapshot.published_at,
                    snapshot.event_type,
                    snapshot.title,
                    snapshot.sentiment,
                    snapshot.importance,
                    snapshot.source,
                    snapshot.content,
                    now,
                    checksum,
                ),
            )
            conn.commit()
            return True
        except Exception as e:
            logger.error("Failed to add event snapshot", event_id=snapshot.event_id, error=str(e))
            return False

    def add_catalyst_snapshot(self, snapshot: CatalystSnapshot) -> bool:
        """Catalyst snapshot ekle (duplicate kontrolü ile)."""
        conn = self._get_conn()
        now = datetime.now(UTC).isoformat()
        checksum = hashlib.md5(f"{snapshot.event_id}:{snapshot.catalyst_type}".encode()).hexdigest()

        try:
            conn.execute(
                """INSERT INTO catalyst_snapshots
                   (event_id, ticker, announcement_date, event_date,
                    catalyst_type, importance, source, fetched_at, checksum)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(event_id) DO NOTHING""",
                (
                    snapshot.event_id,
                    snapshot.ticker,
                    snapshot.announcement_date,
                    snapshot.event_date,
                    snapshot.catalyst_type,
                    snapshot.importance,
                    snapshot.source,
                    now,
                    checksum,
                ),
            )
            conn.commit()
            return True
        except Exception as e:
            logger.error("Failed to add catalyst snapshot", event_id=snapshot.event_id, error=str(e))
            return False

    # === INGESTION STATE ===

    def get_last_ingestion_time(self, key: str) -> str | None:
        """Son ingestion timestamp'ini getir."""
        conn = self._get_conn()
        rows = self._fetchall_dicts(conn, "SELECT value FROM ingestion_state WHERE key = ?", (key,))
        return rows[0]["value"] if rows else None

    def set_last_ingestion_time(self, key: str, timestamp: str):
        """Son ingestion timestamp'ini kaydet."""
        conn = self._get_conn()
        now = datetime.now(UTC).isoformat()
        conn.execute(
            """INSERT OR REPLACE INTO ingestion_state (key, value, updated_at)
               VALUES (?, ?, ?)""",
            (key, timestamp, now),
        )
        conn.commit()

    # === STATISTICS ===

    def get_stats(self) -> dict[str, Any]:
        """Repository istatistikleri."""
        conn = self._get_conn()
        fund_count = conn.execute("SELECT COUNT(*) FROM fundamental_snapshots").fetchone()[0]
        event_count = conn.execute("SELECT COUNT(*) FROM event_snapshots").fetchone()[0]
        catalyst_count = conn.execute("SELECT COUNT(*) FROM catalyst_snapshots").fetchone()[0]

        fund_tickers = conn.execute("SELECT COUNT(DISTINCT ticker) FROM fundamental_snapshots").fetchone()[0]
        event_tickers = conn.execute("SELECT COUNT(DISTINCT ticker) FROM event_snapshots").fetchone()[0]

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
