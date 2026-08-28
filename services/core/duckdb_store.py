"""
ALPHA BIST — DuckDB Store v1.0 (SQLite Replacement)

Tüm local/offline depolama için DuckDB tabanlı store.
SQLite yerine geçer: 100x+ hızlı analitik sorgular, Parquet native.

Özellikler:
- Embedded (sunucu gerektirmez)
- Parquet/Arrow native desteği
- ACID garantili
- SQLite API'sine benzer kolay kullanım
- Batched writes (SSD dostu)

Kullanım:
    from services.core.duckdb_store import DuckDBStore

    store = DuckDBStore("data/central_state.db")
    store.execute("INSERT INTO ...", params)
    rows = store.fetch("SELECT * FROM ...", params)
"""

import atexit
import signal
import time
from contextlib import contextmanager, suppress
from pathlib import Path
from typing import Any

import duckdb
import structlog

try:
    import orjson  # noqa: F401
except ImportError:
    raise ImportError("orjson is required") from None

logger = structlog.get_logger()


class DuckDBStore:
    """DuckDB tabanlı local store — SQLite drop-in replacement."""

    def __init__(self, db_path: str = "data/central_state.db"):
        self._db_path = Path(db_path)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn: duckdb.DuckDBPyConnection | None = None
        self._write_buffer: list[tuple[str, tuple]] = []
        self._buffer_size = 10
        self._last_flush = time.time()
        self._flush_interval = 30.0
        self._init_connection()

    def _init_connection(self):
        """DuckDB bağlantısını başlat."""
        self._conn = duckdb.connect(str(self._db_path))
        # WAL mode + performans ayarları
        self._conn.execute("SET wal_autocheckpoint = '10MB'")
        self._conn.execute("SET checkpoint_threshold = '16MB'")

    @contextmanager
    def _get_conn(self):
        """Bağlantı al (reconnect destekli)."""
        if self._conn is None:
            self._init_connection()
        try:
            yield self._conn
        except Exception as e:
            logger.warning("DuckDB connection error, reconnecting", error=str(e))
            self._init_connection()
            raise

    def execute(self, query: str, params: tuple = ()) -> None:
        """Sorgu çalıştır (write)."""
        with self._get_conn() as conn:
            conn.execute(query, params)

    def fetch(self, query: str, params: tuple = ()) -> list[dict[str, Any]]:
        """Sorgu çalıştır ve sonuçları dict listesi olarak döndür."""
        with self._get_conn() as conn:
            result = conn.execute(query, params)
            columns = [desc[0] for desc in result.description]
            rows = result.fetchall()
            return [dict(zip(columns, row, strict=False)) for row in rows]

    def fetchone(self, query: str, params: tuple = ()) -> dict[str, Any] | None:
        """Tek satır döndür."""
        rows = self.fetch(query, params)
        return rows[0] if rows else None

    def fetchval(self, query: str, params: tuple = ()) -> Any:
        """Tek değer döndür."""
        with self._get_conn() as conn:
            result = conn.execute(query, params).fetchone()
            return result[0] if result else None

    def executescript(self, script: str) -> None:
        """Birden fazla SQL çalıştır.

        UYARI: Noktalı virgülle (;) ayırır — string literal içinde ; varsa
        bu yöntem çalışmaz. Böyle durumlarda ayrı execute() kullanın.
        """
        with self._get_conn() as conn:
            for stmt in script.split(";"):
                stmt = stmt.strip()
                if stmt:
                    conn.execute(stmt)

    def _flush_buffer(self):
        """Write buffer'ı flush et."""
        if not self._write_buffer:
            return
        with self._get_conn() as conn:
            for query, params in self._write_buffer:
                conn.execute(query, params)
        self._write_buffer.clear()
        self._last_flush = time.time()

    def buffered_write(self, query: str, params: tuple):
        """Buffered write — toplu yaz."""
        self._write_buffer.append((query, params))
        if len(self._write_buffer) >= self._buffer_size:
            self._flush_buffer()

    def periodic_flush(self):
        """Periyodik flush."""
        if time.time() - self._last_flush > self._flush_interval:
            self._flush_buffer()

    def flush(self):
        """Manuel flush."""
        self._flush_buffer()

    def close(self):
        """Bağlantıyı kapat."""
        self._flush_buffer()
        if self._conn:
            self._conn.close()
            self._conn = None

    @staticmethod
    def _is_valid_identifier(name: str) -> bool:
        """SQL identifier whitelist kontrolü — injection önleme."""
        import re

        return bool(re.match(r"^[a-zA-Z_][a-zA-Z0-9_]*$", name))

    def get_stats(self) -> dict[str, Any]:
        """İstatistikler."""
        with self._get_conn() as conn:
            tables = conn.execute(
                "SELECT table_name FROM information_schema.tables WHERE table_schema = 'main'"
            ).fetchall()
            stats = {}
            for (table,) in tables:
                if not self._is_valid_identifier(table):
                    logger.warning("Skipping invalid table name", table=table)
                    stats[table] = 0
                    continue
                try:
                    count = conn.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
                    stats[table] = count
                except Exception as e:
                    logger.debug("Table count failed", table=table, error=str(e))
                    stats[table] = 0
        return {
            "db_path": str(self._db_path),
            "db_size_bytes": self._db_path.stat().st_size if self._db_path.exists() else 0,
            "buffer_size": len(self._write_buffer),
            "table_counts": stats,
        }

    def __del__(self):
        with suppress(Exception):
            self.close()


# Graceful shutdown
_stores: list[DuckDBStore] = []


def _flush_all_on_exit():
    for store in _stores:
        with suppress(Exception):
            store.flush()


def _flush_all_on_signal(signum, frame):
    for store in _stores:
        with suppress(Exception):
            store.flush()


atexit.register(_flush_all_on_exit)
try:
    signal.signal(signal.SIGTERM, _flush_all_on_signal)
    signal.signal(signal.SIGINT, _flush_all_on_signal)
except (ValueError, OSError):
    pass
