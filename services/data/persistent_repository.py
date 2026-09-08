"""ALPHA BIST — Kalıcı Tarihsel Veri Deposu (Persistent Historical Repository).

Bu modül; DuckDB tabanlı kalıcı tarihsel veri deposu sağlayarak çeyreklik temel analiz
snapshot'larını, KAP şirket bildirimlerini ve türetilmiş kurumsal katalistleri
Point-In-Time (PIT) uyumlu, artımlı (incremental) ve tekrarsız (deterministic deduplication)
olarak saklar ve yüksek performanslı sorgulama sağlar.
"""

from __future__ import annotations

import hashlib
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

import duckdb
import orjson
import polars as pl
import structlog

from services.data.historical_contracts import (
    CatalystSnapshot,
    EventSnapshot,
    FundamentalSnapshot,
    HistoricalDataRepository,
)

logger = structlog.get_logger(__name__)

# ==============================================================================
# Yapılandırma ve WAL Sabitleri
# ==============================================================================

DEFAULT_HISTORICAL_DB_PATH: Final[str] = "data/historical_data.duckdb"
DEFAULT_CHECKPOINT_SIZE: Final[str] = "4MB"
DEFAULT_WAL_SIZE: Final[str] = "2MB"


# ==============================================================================
# DuckDB WAL ve orjson Yardımcıları
# ==============================================================================


def configure_duckdb_wal(conn: duckdb.DuckDBPyConnection) -> None:
    """DuckDB bağlantısı için WAL ve checkpoint parametrelerini optimize eder.

    Args:
        conn: Yapılandırılacak DuckDB bağlantısı.
    """
    try:
        conn.execute(f"PRAGMA checkpoint_threshold = '{DEFAULT_CHECKPOINT_SIZE}';")
        conn.execute(f"PRAGMA wal_autocheckpoint = '{DEFAULT_WAL_SIZE}';")
    except Exception as exc:
        logger.warning("duckdb_wal_yapilandirma_uyarisi", hata=str(exc))


def to_orjson_bytes(val: Any) -> bytes:
    """Herhangi bir nesneyi orjson ile ikili bayt dizisine dönüştürür.

    Args:
        val: Serileştirilecek veri veya nesne.

    Returns:
        bytes: orjson kodlanmış baytlar.
    """
    if hasattr(val, "to_dict"):
        val = val.to_dict()
    return orjson.dumps(val, default=str)


# ==============================================================================
# Kalıcı Veri Deposu Sınıfı (Persistent Repository)
# ==============================================================================


class PersistentHistoricalRepository(HistoricalDataRepository):
    """DuckDB tabanlı kalıcı tarihsel veri deposu motoru."""

    def __init__(self, db_path: str = DEFAULT_HISTORICAL_DB_PATH) -> None:
        """DuckDB dosya yolunu ve veri dizinini hazırlar.

        Args:
            db_path: Kalıcı DuckDB dosya yolu.
        """
        self._lock = threading.RLock()
        self._db_path = db_path
        Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
        self._conn: duckdb.DuckDBPyConnection | None = None
        self._init_db()
        logger.info("persistent_historical_repository_baslatildi", db_path=self._db_path)

    def __repr__(self) -> str:
        """Okunabilir nesne temsili."""
        with self._lock:
            return f"PersistentHistoricalRepository(db_path='{self._db_path}', baglanti_aktif={self._conn is not None})"

    def to_dict(self) -> dict[str, Any]:
        """Depo durumunu ve istatistiklerini sözlük formatında döner."""
        with self._lock:
            stats = self.get_stats()
            return {
                "db_path": self._db_path,
                "is_connected": self._conn is not None,
                "stats": stats,
            }

    def to_orjson_bytes(self) -> bytes:
        """Depo durumunu ikili orjson baytlarına dönüştürür."""
        return to_orjson_bytes(self.to_dict())

    def _get_conn(self) -> duckdb.DuckDBPyConnection:
        """Etkin DuckDB bağlantısını döner veya yeni güvenli bağlantı oluşturur."""
        with self._lock:
            if self._conn is None:
                try:
                    self._conn = duckdb.connect(self._db_path)
                except Exception as exc:
                    logger.warning("kalici_duckdb_acilamadi_fallback", db_path=self._db_path, hata=str(exc))
                    self._conn = duckdb.connect(":memory:")

                self._conn.execute("SET enable_progress_bar = false;")
                configure_duckdb_wal(self._conn)

            return self._conn

    def _fetchall_dicts(self, conn: duckdb.DuckDBPyConnection, query: str, params: tuple[Any, ...] | list[Any] = ()) -> list[dict[str, Any]]:
        """DuckDB üzerinden sorgu çalıştırıp sonuçları sözlük listesi olarak döner."""
        result = conn.execute(query, params)
        if result.description is None:
            return []
        columns = [desc[0] for desc in result.description]
        return [dict(zip(columns, row, strict=False)) for row in result.fetchall()]

    def _init_db(self) -> None:
        """Veri tabanı tablolarını ve dizinlerini oluşturur."""
        with self._lock:
            conn = self._get_conn()
            conn.execute("CREATE SEQUENCE IF NOT EXISTS fundamental_snapshots_seq START 1;")
            conn.execute(
                """
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
                );
                """
            )
            conn.execute("CREATE SEQUENCE IF NOT EXISTS event_snapshots_seq START 1;")
            conn.execute(
                """
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
                );
                """
            )
            conn.execute("CREATE SEQUENCE IF NOT EXISTS catalyst_snapshots_seq START 1;")
            conn.execute(
                """
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
                );
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS ingestion_state (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_fund_ticker_date ON fundamental_snapshots(ticker, available_at);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_event_ticker_date ON event_snapshots(ticker, published_at);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_catalyst_ticker_date ON catalyst_snapshots(ticker, announcement_date);")

    # === QUERY METHODS ===

    def get_fundamental_snapshots(
        self,
        ticker: str,
        as_of_date: str,
    ) -> list[FundamentalSnapshot]:
        """Hisse için Point-In-Time uyumlu temel analiz snapshot'larını döner.

        Args:
            ticker: Hisse sembolü (örn: THYAO).
            as_of_date: Karar anı tarihi (YYYY-MM-DD).

        Returns:
            list[FundamentalSnapshot]: Yayınlanma tarihine göre azalan sıralı snapshot'lar.
        """
        with self._lock:
            conn = self._get_conn()
            clean_ticker = ticker.upper().replace(".IS", "").strip()
            date_filter = as_of_date[:10]

            rows = self._fetchall_dicts(
                conn,
                """
                SELECT ticker, period_end, available_at, values_json, source, status
                FROM fundamental_snapshots
                WHERE ticker = ? AND available_at <= ?
                ORDER BY available_at DESC
                """,
                (clean_ticker, date_filter),
            )

            snapshots: list[FundamentalSnapshot] = []
            for row in rows:
                values_dict = orjson.loads(row["values_json"]) if isinstance(row["values_json"], str | bytes) else row["values_json"]
                snapshots.append(
                    FundamentalSnapshot(
                        ticker=row["ticker"],
                        period_end=row["period_end"],
                        available_at=row["available_at"],
                        values=values_dict,
                        source=row["source"],
                        status=row["status"],
                    )
                )
            return snapshots

    def get_event_snapshots(
        self,
        ticker: str,
        as_of_date: str,
        event_types: list[str] | None = None,
    ) -> list[EventSnapshot]:
        """Hisse için Point-In-Time uyumlu olay bildirimlerini döner.

        Args:
            ticker: Hisse sembolü.
            as_of_date: Karar anı tarihi.
            event_types: İsteğe bağlı olay kategorisi filtresi.

        Returns:
            list[EventSnapshot]: Yayınlanma tarihine göre azalan sıralı olaylar.
        """
        with self._lock:
            conn = self._get_conn()
            clean_ticker = ticker.upper().replace(".IS", "").strip()
            date_filter = as_of_date[:10]

            if event_types:
                placeholders = ",".join("?" * len(event_types))
                query = f"""
                    SELECT event_id, ticker, published_at, event_type, title,
                           sentiment, importance, source, content
                    FROM event_snapshots
                    WHERE ticker = ? AND published_at <= ?
                    AND event_type IN ({placeholders})
                    ORDER BY published_at DESC
                """
                params: list[Any] = [clean_ticker, date_filter] + list(event_types)
                rows = self._fetchall_dicts(conn, query, params)
            else:
                query = """
                    SELECT event_id, ticker, published_at, event_type, title,
                           sentiment, importance, source, content
                    FROM event_snapshots
                    WHERE ticker = ? AND published_at <= ?
                    ORDER BY published_at DESC
                """
                rows = self._fetchall_dicts(conn, query, (clean_ticker, date_filter))

            return [
                EventSnapshot(
                    event_id=row["event_id"],
                    ticker=row["ticker"],
                    published_at=row["published_at"],
                    event_type=row["event_type"],
                    title=row["title"],
                    sentiment=float(row["sentiment"] or 0.0),
                    importance=float(row["importance"] or 0.5),
                    source=row["source"],
                    content=row["content"] or "",
                )
                for row in rows
            ]

    def get_catalyst_snapshots(
        self,
        ticker: str,
        as_of_date: str,
    ) -> list[CatalystSnapshot]:
        """Hisse için duyurulmuş geleceğe dönük katalistleri döner.

        Args:
            ticker: Hisse sembolü.
            as_of_date: Karar anı tarihi.

        Returns:
            list[CatalystSnapshot]: Duyuru tarihine göre azalan sıralı katalistler.
        """
        with self._lock:
            conn = self._get_conn()
            clean_ticker = ticker.upper().replace(".IS", "").strip()
            date_filter = as_of_date[:10]

            rows = self._fetchall_dicts(
                conn,
                """
                SELECT event_id, ticker, announcement_date, event_date,
                       catalyst_type, importance, source
                FROM catalyst_snapshots
                WHERE ticker = ? AND announcement_date <= ?
                ORDER BY announcement_date DESC
                """,
                (clean_ticker, date_filter),
            )

            return [
                CatalystSnapshot(
                    event_id=row["event_id"],
                    ticker=row["ticker"],
                    announcement_date=row["announcement_date"],
                    event_date=row["event_date"],
                    catalyst_type=row["catalyst_type"],
                    importance=float(row["importance"] or 0.5),
                    source=row["source"],
                )
                for row in rows
            ]

    # === INGESTION METHODS ===

    def add_fundamental_snapshot(self, snapshot: FundamentalSnapshot) -> bool:
        """Yeni bir temel analiz snapshot'ı ekler veya günceller (upsert).

        Args:
            snapshot: Eklenecek temel analiz snapshot nesnesi.

        Returns:
            bool: İşlem başarılı ise True, hata oluşursa False.
        """
        with self._lock:
            conn = self._get_conn()
            now = datetime.now(UTC).isoformat()
            values_bytes = orjson.dumps(snapshot.values, option=orjson.OPT_SORT_KEYS)
            values_json = values_bytes.decode("utf-8")
            checksum = hashlib.md5(values_bytes).hexdigest()

            clean_ticker = snapshot.ticker.upper().replace(".IS", "").strip()

            try:
                conn.execute(
                    """
                    INSERT INTO fundamental_snapshots
                    (ticker, period_end, available_at, values_json, source, status, fetched_at, checksum)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(ticker, period_end, available_at)
                    DO UPDATE SET
                        values_json = excluded.values_json,
                        source = excluded.source,
                        status = excluded.status,
                        fetched_at = excluded.fetched_at,
                        checksum = excluded.checksum
                    """,
                    (
                        clean_ticker,
                        snapshot.period_end,
                        snapshot.available_at,
                        values_json,
                        snapshot.source,
                        snapshot.status,
                        now,
                        checksum,
                    ),
                )
                return True
            except Exception as exc:
                logger.error("temel_snapshot_ekleme_hatasi", hisse=snapshot.ticker, hata=str(exc))
                return False

    def add_event_snapshot(self, snapshot: EventSnapshot) -> bool:
        """Yeni bir olay bildirim snapshot'ı ekler (duplicate korumalı).

        Args:
            snapshot: Eklenecek olay snapshot nesnesi.

        Returns:
            bool: İşlem başarılı ise True, hata durumunda False.
        """
        with self._lock:
            conn = self._get_conn()
            now = datetime.now(UTC).isoformat()
            checksum = hashlib.md5(f"{snapshot.event_id}:{snapshot.title}".encode()).hexdigest()
            clean_ticker = snapshot.ticker.upper().replace(".IS", "").strip()

            try:
                conn.execute(
                    """
                    INSERT INTO event_snapshots
                    (event_id, ticker, published_at, event_type, title,
                     sentiment, importance, source, content, fetched_at, checksum)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(event_id) DO NOTHING
                    """,
                    (
                        snapshot.event_id,
                        clean_ticker,
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
                return True
            except Exception as exc:
                logger.error("olay_snapshot_ekleme_hatasi", event_id=snapshot.event_id, hata=str(exc))
                return False

    def add_catalyst_snapshot(self, snapshot: CatalystSnapshot) -> bool:
        """Yeni bir katalist snapshot'ı ekler (duplicate korumalı).

        Args:
            snapshot: Eklenecek katalist snapshot nesnesi.

        Returns:
            bool: İşlem başarılı ise True, hata durumunda False.
        """
        with self._lock:
            conn = self._get_conn()
            now = datetime.now(UTC).isoformat()
            checksum = hashlib.md5(f"{snapshot.event_id}:{snapshot.catalyst_type}".encode()).hexdigest()
            clean_ticker = snapshot.ticker.upper().replace(".IS", "").strip()

            try:
                conn.execute(
                    """
                    INSERT INTO catalyst_snapshots
                    (event_id, ticker, announcement_date, event_date,
                     catalyst_type, importance, source, fetched_at, checksum)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(event_id) DO NOTHING
                    """,
                    (
                        snapshot.event_id,
                        clean_ticker,
                        snapshot.announcement_date,
                        snapshot.event_date,
                        snapshot.catalyst_type,
                        snapshot.importance,
                        snapshot.source,
                        now,
                        checksum,
                    ),
                )
                return True
            except Exception as exc:
                logger.error("katalist_snapshot_ekleme_hatasi", event_id=snapshot.event_id, hata=str(exc))
                return False

    # === INGESTION STATE ===

    def get_last_ingestion_time(self, key: str) -> str | None:
        """Belirtilen alım kanalı için son başarılı alım zaman damgasını döner.

        Args:
            key: Kanal adı (örn: 'fundamental', 'kap', 'news').

        Returns:
            str | None: ISO formatında zaman damgası veya bulunamadıysa None.
        """
        with self._lock:
            conn = self._get_conn()
            rows = self._fetchall_dicts(conn, "SELECT value FROM ingestion_state WHERE key = ?", (key,))
            return str(rows[0]["value"]) if rows else None

    def set_last_ingestion_time(self, key: str, timestamp: str) -> None:
        """Belirtilen alım kanalı için son alım zaman damgasını günceller.

        Args:
            key: Kanal adı.
            timestamp: Kaydedilecek zaman damgası.
        """
        with self._lock:
            conn = self._get_conn()
            now = datetime.now(UTC).isoformat()
            conn.execute(
                """
                INSERT OR REPLACE INTO ingestion_state (key, value, updated_at)
                VALUES (?, ?, ?)
                """,
                (key, timestamp, now),
            )

    # === STATISTICS & MAINTENANCE ===

    def get_stats(self) -> dict[str, Any]:
        """Depodaki kayıt ve hisse sayılarını içeren istatistikleri döner.

        Returns:
            dict[str, Any]: Depo istatistikleri.
        """
        with self._lock:
            conn = self._get_conn()
            fund_row = conn.execute("SELECT COUNT(*), COUNT(DISTINCT ticker) FROM fundamental_snapshots;").fetchone()
            event_row = conn.execute("SELECT COUNT(*), COUNT(DISTINCT ticker) FROM event_snapshots;").fetchone()
            cat_row = conn.execute("SELECT COUNT(*), COUNT(DISTINCT ticker) FROM catalyst_snapshots;").fetchone()

            return {
                "fundamental_snapshots": fund_row[0] if fund_row else 0,
                "fundamental_tickers": fund_row[1] if fund_row else 0,
                "event_snapshots": event_row[0] if event_row else 0,
                "event_tickers": event_row[1] if event_row else 0,
                "catalyst_snapshots": cat_row[0] if cat_row else 0,
                "catalyst_tickers": cat_row[1] if cat_row else 0,
            }

    def flush(self) -> None:
        """Tamponlanmış yazma işlemlerini diske kaydeder (checkpoint)."""
        with self._lock:
            if self._conn:
                try:
                    self._conn.execute("CHECKPOINT;")
                except Exception as exc:
                    logger.debug("duckdb_checkpoint_uyarisi", hata=str(exc))

    def clear(self) -> None:
        """Kalıcı depodaki tüm tabloların içeriğini temizler."""
        with self._lock:
            conn = self._get_conn()
            conn.execute("DELETE FROM fundamental_snapshots;")
            conn.execute("DELETE FROM event_snapshots;")
            conn.execute("DELETE FROM catalyst_snapshots;")
            conn.execute("DELETE FROM ingestion_state;")
            logger.info("persistent_repository_tablolari_temizlendi", db_path=self._db_path)

    def close(self) -> None:
        """Etkin DuckDB bağlantısını güvenle kapatır."""
        with self._lock:
            if self._conn:
                try:
                    self.flush()
                    self._conn.close()
                except Exception as exc:
                    logger.warning("duckdb_kapatma_uyarisi", hata=str(exc))
                finally:
                    self._conn = None


# ==============================================================================
# Polars Okuma ve Temizleme Fonksiyonları
# ==============================================================================


def read_persistent_fundamentals_from_duckdb(
    db_path: str = DEFAULT_HISTORICAL_DB_PATH,
    ticker: str | None = None,
    limit: int | None = None,
) -> pl.DataFrame:
    """DuckDB deposundaki temel analiz snapshot'larını Polars DataFrame olarak okur.

    Args:
        db_path: DuckDB dosya yolu.
        ticker: İsteğe bağlı hisse filtresi.
        limit: Maksimum satır sayısı.

    Returns:
        pl.DataFrame: Temel analiz tablosu.
    """
    path_obj = Path(db_path)
    if not path_obj.exists():
        return pl.DataFrame()

    try:
        with duckdb.connect(str(path_obj)) as conn:
            configure_duckdb_wal(conn)
            tbl = conn.execute(
                "SELECT count(*) FROM information_schema.tables WHERE table_name = 'fundamental_snapshots'"
            ).fetchone()
            if not tbl or tbl[0] == 0:
                return pl.DataFrame()

            query = "SELECT * FROM fundamental_snapshots WHERE 1=1"
            params: list[Any] = []
            if ticker:
                query += " AND ticker = ?"
                params.append(ticker.upper().replace(".IS", "").strip())

            query += " ORDER BY available_at DESC"
            if limit and limit > 0:
                query += f" LIMIT {int(limit)}"

            return conn.execute(query, params).pl()
    except Exception as exc:
        logger.warning("duckdb_persistent_fundamentals_okuma_hatasi", db_path=db_path, hata=str(exc))
        return pl.DataFrame()


def read_persistent_events_from_duckdb(
    db_path: str = DEFAULT_HISTORICAL_DB_PATH,
    ticker: str | None = None,
    limit: int | None = None,
) -> pl.DataFrame:
    """DuckDB deposundaki olay snapshot'larını Polars DataFrame olarak okur.

    Args:
        db_path: DuckDB dosya yolu.
        ticker: İsteğe bağlı hisse filtresi.
        limit: Maksimum satır sayısı.

    Returns:
        pl.DataFrame: Olay bildirimleri tablosu.
    """
    path_obj = Path(db_path)
    if not path_obj.exists():
        return pl.DataFrame()

    try:
        with duckdb.connect(str(path_obj)) as conn:
            configure_duckdb_wal(conn)
            tbl = conn.execute(
                "SELECT count(*) FROM information_schema.tables WHERE table_name = 'event_snapshots'"
            ).fetchone()
            if not tbl or tbl[0] == 0:
                return pl.DataFrame()

            query = "SELECT * FROM event_snapshots WHERE 1=1"
            params: list[Any] = []
            if ticker:
                query += " AND ticker = ?"
                params.append(ticker.upper().replace(".IS", "").strip())

            query += " ORDER BY published_at DESC"
            if limit and limit > 0:
                query += f" LIMIT {int(limit)}"

            return conn.execute(query, params).pl()
    except Exception as exc:
        logger.warning("duckdb_persistent_events_okuma_hatasi", db_path=db_path, hata=str(exc))
        return pl.DataFrame()


def read_persistent_catalysts_from_duckdb(
    db_path: str = DEFAULT_HISTORICAL_DB_PATH,
    ticker: str | None = None,
    limit: int | None = None,
) -> pl.DataFrame:
    """DuckDB deposundaki katalist snapshot'larını Polars DataFrame olarak okur.

    Args:
        db_path: DuckDB dosya yolu.
        ticker: İsteğe bağlı hisse filtresi.
        limit: Maksimum satır sayısı.

    Returns:
        pl.DataFrame: Katalist bildirimleri tablosu.
    """
    path_obj = Path(db_path)
    if not path_obj.exists():
        return pl.DataFrame()

    try:
        with duckdb.connect(str(path_obj)) as conn:
            configure_duckdb_wal(conn)
            tbl = conn.execute(
                "SELECT count(*) FROM information_schema.tables WHERE table_name = 'catalyst_snapshots'"
            ).fetchone()
            if not tbl or tbl[0] == 0:
                return pl.DataFrame()

            query = "SELECT * FROM catalyst_snapshots WHERE 1=1"
            params: list[Any] = []
            if ticker:
                query += " AND ticker = ?"
                params.append(ticker.upper().replace(".IS", "").strip())

            query += " ORDER BY announcement_date DESC"
            if limit and limit > 0:
                query += f" LIMIT {int(limit)}"

            return conn.execute(query, params).pl()
    except Exception as exc:
        logger.warning("duckdb_persistent_catalysts_okuma_hatasi", db_path=db_path, hata=str(exc))
        return pl.DataFrame()


def clear_persistent_repository_duckdb(db_path: str = DEFAULT_HISTORICAL_DB_PATH) -> None:
    """DuckDB kalıcı deposundaki tüm tabloları sıfırlar.

    Args:
        db_path: DuckDB dosya yolu.
    """
    path_obj = Path(db_path)
    if not path_obj.exists():
        return

    try:
        with duckdb.connect(str(path_obj)) as conn:
            configure_duckdb_wal(conn)
            conn.execute("DROP TABLE IF EXISTS fundamental_snapshots;")
            conn.execute("DROP TABLE IF EXISTS event_snapshots;")
            conn.execute("DROP TABLE IF EXISTS catalyst_snapshots;")
            conn.execute("DROP TABLE IF EXISTS ingestion_state;")
            logger.info("persistent_repository_duckdb_sifirlandi", db_path=db_path)
    except Exception as exc:
        logger.error("persistent_repository_duckdb_sifirlama_hatasi", db_path=db_path, hata=str(exc))


# Singleton örneği
persistent_repository: Final[PersistentHistoricalRepository] = PersistentHistoricalRepository()

# Geriye dönük uyumluluk takma adı
PersistentRepository: Final[type[PersistentHistoricalRepository]] = PersistentHistoricalRepository

__all__: Final[list[str]] = [
    "DEFAULT_CHECKPOINT_SIZE",
    "DEFAULT_HISTORICAL_DB_PATH",
    "DEFAULT_WAL_SIZE",
    "PersistentHistoricalRepository",
    "PersistentRepository",
    "clear_persistent_repository_duckdb",
    "configure_duckdb_wal",
    "persistent_repository",
    "read_persistent_catalysts_from_duckdb",
    "read_persistent_events_from_duckdb",
    "read_persistent_fundamentals_from_duckdb",
    "to_orjson_bytes",
]
