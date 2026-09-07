"""
ALPHA BIST — DuckDB Store v2.0 (DuckDB + Polars)

Tüm yerel ve çevrimdışı durum depolaması için kurumsal DuckDB motoru.
SQLite'ın yerine geçer; analitik sorgularda 100 kat daha yüksek hız, sıfır kopyalı
Parquet/Arrow/Polars entegrasyonu ve tamponlu (batched) SSD dostu yazma mimarisi sunar.

Özellikler:
- Gömülü mimari (ayrı bir veritabanı sunucusu gerektirmez).
- Polars DataFrame ve Arrow sıfır-kopyalama (zero-copy) doğrudan erişim.
- Eşzamanlı (thread-safe) işlem ve tampon koruması.
- SSD yazma azaltımı için arabellekli (buffered) toplu yazma ve periyodik boşaltma.
- Windows dosya kilidi ve 0-byte bozuk dosya kurtarma zırhı.
"""

from __future__ import annotations

import atexit
import re
import signal
import threading
import time
from contextlib import contextmanager, suppress
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final

import duckdb
import orjson
import structlog

from services.core.debounce import configure_duckdb_wal
from services.core.otel import otel_trace

if TYPE_CHECKING:
    import polars as pl

logger = structlog.get_logger(__name__)

DEFAULT_DUCKDB_STORE_PATH: Final[str] = "data/central_state.db"
DEFAULT_BUFFER_SIZE: Final[int] = 10
DEFAULT_FLUSH_INTERVAL: Final[float] = 30.0


class DuckDBStore:
    """DuckDB tabanlı yerel durum ve analitik veri deposu.

    SQLite API'sine benzer kullanım kolaylığı sunar, yüksek hacimli analitik
    sorgularda Polars ile entegre çalışır ve SSD aşınmasını önleyen arabellekli
    yazma mekanizması barındırır.
    """

    def __init__(
        self,
        db_path: str = DEFAULT_DUCKDB_STORE_PATH,
        buffer_size: int = DEFAULT_BUFFER_SIZE,
        flush_interval: float = DEFAULT_FLUSH_INTERVAL,
    ) -> None:
        """DuckDBStore örneğini başlatır.

        Args:
            db_path: DuckDB veritabanı dosyasının disk yolu.
            buffer_size: Otomatik boşaltma öncesi tamponda tutulacak maksimum yazma adedi.
            flush_interval: Arabellek periyodik boşaltma süresi (saniye).
        """
        self._db_path: Path = Path(db_path)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn: duckdb.DuckDBPyConnection | None = None
        self._write_buffer: list[tuple[str, Any]] = []
        self._lock: threading.RLock = threading.RLock()
        self._buffer_size: int = max(1, int(buffer_size))
        self._last_flush: float = time.monotonic()
        self._flush_interval: float = max(1.0, float(flush_interval))
        self._periodic_thread: threading.Thread | None = None
        self._stop_periodic: threading.Event = threading.Event()

        self._init_connection()
        self._start_periodic_flush()

        with _stores_lock:
            _stores.append(self)

    def __repr__(self) -> str:
        """DuckDBStore nesnesinin okunabilir temsilini döner."""
        return (
            f"DuckDBStore(db_path={str(self._db_path)!r}, "
            f"buffer_len={len(self._write_buffer)}, "
            f"is_connected={self._conn is not None})"
        )

    def __enter__(self) -> DuckDBStore:
        """Bağlam yöneticisi başlangıcı."""
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        """Bağlam yöneticisi bitişi."""
        self.close()

    def _init_connection(self) -> None:
        """DuckDB bağlantısını kurar ve SSD koruma ayarlarını uygular."""
        with self._lock:
            # Windows sıfır-bayt bozuk dosya önlemi
            if self._db_path.exists() and self._db_path.is_file() and self._db_path.stat().st_size == 0:
                try:
                    self._db_path.unlink()
                    logger.warning("Bozuk sıfır baytlık DuckDB deposu temizlendi", path=str(self._db_path))
                except OSError as unlink_err:
                    logger.debug("Sıfır baytlık dosya silinirken hata", error=str(unlink_err))

            self._conn = duckdb.connect(str(self._db_path))

            # SSD write reduction: DuckDB WAL ve Checkpoint optimizasyonları
            try:
                from services.core.debounce import configure_duckdb_wal

                configure_duckdb_wal(self._conn)
            except Exception as wal_err:
                logger.debug("WAL debounce yapılandırması atlandı", error=str(wal_err))

    @contextmanager
    def _get_conn(self) -> Any:
        """Aktif DuckDB bağlantısını döner; bağlantı koparsa otomatik yeniden bağlanır.

        Yields:
            duckdb.DuckDBPyConnection: Aktif bağlantı nesnesi.
        """
        with self._lock:
            if self._conn is None:
                self._init_connection()
            try:
                yield self._conn
            except Exception as exc:
                logger.warning("DuckDB bağlantı hatası, yeniden bağlanılıyor", error=str(exc))
                self._init_connection()
                raise

    @otel_trace("duckdb_store.execute")
    def execute(self, query: str, params: Any = ()) -> None:
        """Veritabanında yazma/güncelleme (DDL/DML) sorgusu çalıştırır.

        Args:
            query: SQL sorgusu.
            params: Parametre listesi veya demeti.
        """
        with self._lock, self._get_conn() as conn:
            if params:
                conn.execute(query, params)
            else:
                conn.execute(query)

    @otel_trace("duckdb_store.fetch")
    def fetch(self, query: str, params: Any = ()) -> list[dict[str, Any]]:
        """SQL sorgusunu çalıştırır ve sonuçları sözlük listesi olarak döner.

        Args:
            query: SQL sorgusu.
            params: Parametreler.

        Returns:
            Satır kayıtlarını temsil eden sözlük listesi.
        """
        with self._lock, self._get_conn() as conn:
            result = conn.execute(query, params) if params else conn.execute(query)
            columns = [desc[0] for desc in result.description] if result.description else []
            rows = result.fetchall()
            return [dict(zip(columns, row, strict=False)) for row in rows]

    @otel_trace("duckdb_store.fetchone")
    def fetchone(self, query: str, params: Any = ()) -> dict[str, Any] | None:
        """SQL sorgusundan tek bir satır döner.

        Args:
            query: SQL sorgusu.
            params: Parametreler.

        Returns:
            Satır sözlüğü veya sonuç yoksa None.
        """
        rows = self.fetch(query, params)
        return rows[0] if rows else None

    @otel_trace("duckdb_store.fetchval")
    def fetchval(self, query: str, params: Any = ()) -> Any:
        """SQL sorgusunun ilk sütunundaki tek bir skaler değeri döner.

        Args:
            query: SQL sorgusu.
            params: Parametreler.

        Returns:
            Skaler değer veya bulunamazsa None.
        """
        with self._lock, self._get_conn() as conn:
            result = conn.execute(query, params).fetchone() if params else conn.execute(query).fetchone()
            return result[0] if result else None

    def fetch_df(self, query: str, params: Any = ()) -> pl.DataFrame:
        """SQL sorgusu sonucunu doğrudan sıfır kopyalı Polars DataFrame olarak döner.

        Args:
            query: SQL sorgusu.
            params: Parametreler.

        Returns:
            Sonuçları içeren Polars DataFrame (GEMINI.md Kural 2).
        """
        with self._lock, self._get_conn() as conn:
            result = conn.execute(query, params) if params else conn.execute(query)
            return result.pl()

    def export_table_to_polars(self, table: str, limit: int = 1000) -> pl.DataFrame:
        """Belirtilen tabloyu Polars DataFrame olarak dışa aktarır.

        Args:
            table: Hedef tablo adı.
            limit: Maksimum satır limiti.

        Returns:
            Polars DataFrame.
        """
        if not self._is_valid_identifier(table):
            raise ValueError(f"Geçersiz tablo adı: {table!r}")

        with self._lock, self._get_conn() as conn:
            return conn.execute(f'SELECT * FROM "{table}" LIMIT ?', (limit,)).pl()

    def write_df(self, table: str, df: pl.DataFrame, if_exists: str = "append") -> None:
        """Polars DataFrame verisini sıfır kopyalama ile DuckDB tablosuna yazar.

        Args:
            table: Hedef tablo adı.
            df: Yazılacak Polars DataFrame.
            if_exists: Tablo mevcutsa uygulanacak strateji ('append' veya 'replace').

        Raises:
            ValueError: Tablo adı geçersiz ise.
        """
        if not self._is_valid_identifier(table):
            raise ValueError(f"Geçersiz tablo adı: {table!r}")
        if df.is_empty():
            logger.warning("Yazılacak Polars DataFrame boş, işlem atlandı", table=table)
            return

        arrow_table = df.to_arrow()
        with self._lock, self._get_conn() as conn:
            temp_view_name = f"_tmp_store_arrow_{table}"
            conn.register(temp_view_name, arrow_table)
            try:
                table_exists = conn.execute(
                    "SELECT 1 FROM information_schema.tables WHERE table_name = ? AND table_schema = 'main'",
                    (table,),
                ).fetchone() is not None

                if not table_exists:
                    conn.execute(f'CREATE TABLE "{table}" AS SELECT * FROM "{temp_view_name}"')
                elif if_exists == "replace":
                    conn.execute(f'CREATE OR REPLACE TABLE "{table}" AS SELECT * FROM "{temp_view_name}"')
                else:
                    conn.execute(f'INSERT INTO "{table}" SELECT * FROM "{temp_view_name}"')
                logger.info(
                    "Polars verisi depoya başarıyla yazıldı",
                    table=table,
                    row_count=len(df),
                    if_exists=if_exists,
                )
            finally:
                conn.unregister(temp_view_name)

    def clear_buffer(self) -> int:
        """Arabellekte biriken bekleyen yazma işlemlerini diske yazmadan temizler.

        Returns:
            Temizlenen işlem sayısı.
        """
        with self._lock:
            discarded = len(self._write_buffer)
            self._write_buffer.clear()
            if discarded > 0:
                logger.warning("DuckDB yazma arabelleği boşaltılmadan temizlendi", discarded_count=discarded)
            return discarded

    @otel_trace("duckdb_store.executescript")
    def executescript(self, script: str) -> None:
        """Çoklu SQL komutu içeren betiği çalıştırır.

        Args:
            script: Noktalı virgülle ayrılmış SQL ifadeleri.
        """
        with self._lock, self._get_conn() as conn:
            # DuckDB doğrudan çoklu ifade yürütmeyi destekler
            try:
                conn.execute(script)
            except Exception as script_err:
                logger.debug("executescript_dogrudan_yurutme_hatasi_ayristiriliyor", error=str(script_err))
                # İfadeleri ayrıştırarak tek tek deneme yedeği
                for stmt in script.split(";"):
                    cleaned = stmt.strip()
                    if cleaned:
                        conn.execute(cleaned)

    def _flush_buffer(self) -> None:
        """Arabellekte biriken yazma işlemlerini atomik işlem (transaction) ile veritabanına aktarır."""
        with self._lock:
            if not self._write_buffer:
                return
            batch = self._write_buffer.copy()
            self._write_buffer.clear()

            with self._get_conn() as conn:
                try:
                    conn.execute("BEGIN TRANSACTION")
                    for query, params in batch:
                        if params:
                            conn.execute(query, params)
                        else:
                            conn.execute(query)
                    conn.execute("COMMIT")
                except Exception as exc:
                    with suppress(Exception):
                        conn.execute("ROLLBACK")
                    # Başarısız olan sorguları arabelleğe geri koy (fail-closed / sıfır veri kaybı)
                    self._write_buffer = batch + self._write_buffer
                    logger.error(
                        "DuckDB arabellek boşaltma hatası, işlemler geri alındı ve arabelleğe iade edildi",
                        batch_len=len(batch),
                        error=str(exc),
                    )
                    raise

            self._last_flush = time.monotonic()

    def buffered_write(self, query: str, params: Any = ()) -> None:
        """Yazma sorgusunu arabelleğe ekler; eşik aşılırsa toplu kaydeder.

        Args:
            query: SQL sorgusu.
            params: Sorgu parametreleri.
        """
        with self._lock:
            self._write_buffer.append((query, params))
            should_flush = len(self._write_buffer) >= self._buffer_size

        if should_flush:
            self._flush_buffer()

    def _start_periodic_flush(self) -> None:
        """Arka planda periyodik arabellek boşaltma iş parçacığını başlatır."""

        def _loop() -> None:
            # Kontrol periyodunu aralığın yarısı veya en fazla 1 saniye olarak belirle
            poll_interval = min(1.0, max(0.2, self._flush_interval / 2.0))
            while not self._stop_periodic.wait(poll_interval):
                try:
                    self.periodic_flush()
                except Exception as exc:
                    logger.debug("Periyodik flush esnasında hata", error=str(exc))

        self._periodic_thread = threading.Thread(target=_loop, daemon=True, name="duckdb-periodic-flush")
        self._periodic_thread.start()

    def periodic_flush(self) -> None:
        """Zaman aşımına uğramış tampon verilerini veritabanına yazar."""
        with self._lock:
            if self._write_buffer and (time.monotonic() - self._last_flush >= self._flush_interval):
                self._flush_buffer()

    def flush(self) -> None:
        """Tampondaki tüm verileri derhal diske boşaltır."""
        self._flush_buffer()

    def close(self) -> None:
        """Kaynakları serbest bırakır, tamponu diske yazar ve bağlantıyı kapatır."""
        self._stop_periodic.set()
        if self._periodic_thread is not None and self._periodic_thread.is_alive():
            if threading.current_thread() != self._periodic_thread:
                self._periodic_thread.join(timeout=2.0)

        self.flush()

        with self._lock:
            if self._conn is not None:
                try:
                    self._conn.close()
                except Exception as close_err:
                    logger.debug("DuckDB kapatılırken hata", error=str(close_err))
                finally:
                    self._conn = None

        with _stores_lock:
            if self in _stores:
                _stores.remove(self)

    @staticmethod
    def _is_valid_identifier(name: str) -> bool:
        """SQL tanımlayıcı adını doğrular (SQL Enjeksiyon koruması).

        Args:
            name: Tablo veya kolon adı.

        Returns:
            Geçerli ise True.
        """
        return bool(re.match(r"^[a-zA-Z_][a-zA-Z0-9_]*$", name))

    @otel_trace("duckdb_store.get_stats")
    def get_stats(self) -> dict[str, Any]:
        """Depodaki tablo satır sayıları ve dosya boyutu istatistiklerini döner.

        Returns:
            İstatistik sözlüğü.
        """
        with self._lock, self._get_conn() as conn:
            tables = conn.execute(
                "SELECT table_name FROM information_schema.tables WHERE table_schema = 'main'"
            ).fetchall()
            stats: dict[str, int] = {}
            for (table,) in tables:
                if not self._is_valid_identifier(table):
                    continue
                try:
                    count_val = conn.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()
                    stats[table] = int(count_val[0]) if count_val else 0
                except Exception as exc:
                    logger.debug("Tablo satır sayısı okunamadı", table=table, error=str(exc))
                    stats[table] = 0

            return {
                "db_path": str(self._db_path),
                "db_size_bytes": self._db_path.stat().st_size if self._db_path.exists() else 0,
                "buffer_size": len(self._write_buffer),
                "table_counts": stats,
            }

    def to_orjson_bytes(self) -> bytes:
        """Depo istatistiklerini orjson formatında binary olarak döner (GEMINI.md Kural 5).

        Returns:
            JSON bayt dizisi.
        """
        return orjson.dumps(self.get_stats(), option=orjson.OPT_INDENT_2, default=str)

    def __del__(self) -> None:
        """Nesne bellekten silinirken kaynakları güvenle temizler."""
        with suppress(Exception):
            self.close()


# ==============================================================================
# Global Durum ve Kapanış Protokolü
# ==============================================================================

_stores_lock: Final[threading.Lock] = threading.Lock()
_stores: list[DuckDBStore] = []


def _flush_all_on_exit() -> None:
    """Uygulama sonlanırken kayıtlı tüm depoları diske boşaltır."""
    with _stores_lock:
        active_stores = list(_stores)
    for store in active_stores:
        with suppress(Exception):
            store.flush()


def _flush_all_on_signal(signum: int, frame: Any) -> None:
    """Sinyal (SIGTERM, SIGINT) alındığında tüm depoları boşaltır."""
    _flush_all_on_exit()


atexit.register(_flush_all_on_exit)

try:
    if threading.current_thread() is threading.main_thread():
        signal.signal(signal.SIGTERM, _flush_all_on_signal)
        signal.signal(signal.SIGINT, _flush_all_on_signal)
except (ValueError, OSError) as sig_err:
    logger.debug("Sinyal yakalayıcı kaydedilemedi", error=str(sig_err))

# Global tekil örnek
duckdb_store: Final[DuckDBStore] = DuckDBStore()
DuckDBStateStore = DuckDBStore


def fetch(query: str, params: Any = ()) -> list[dict[str, Any]]:
    """SQL sorgusunu çalıştırır ve sonuçları sözlük listesi olarak döner."""
    return duckdb_store.fetch(query=query, params=params)


def fetchone(query: str, params: Any = ()) -> dict[str, Any] | None:
    """SQL sorgusundan tek bir satır döner."""
    return duckdb_store.fetchone(query=query, params=params)


def fetchval(query: str, params: Any = ()) -> Any:
    """SQL sorgusunun ilk sütunundaki tek bir skaler değeri döner."""
    return duckdb_store.fetchval(query=query, params=params)


def fetch_df(query: str, params: Any = ()) -> pl.DataFrame:
    """SQL sorgusu sonucunu doğrudan sıfır kopyalı Polars DataFrame olarak döner."""
    return duckdb_store.fetch_df(query=query, params=params)


def export_table_to_polars(table: str, limit: int = 1000) -> pl.DataFrame:
    """Belirtilen tabloyu Polars DataFrame olarak dışa aktarır."""
    return duckdb_store.export_table_to_polars(table=table, limit=limit)


def write_df(table: str, df: pl.DataFrame, if_exists: str = "append") -> None:
    """Polars DataFrame verisini sıfır kopyayla DuckDB deposuna yazar."""
    duckdb_store.write_df(table=table, df=df, if_exists=if_exists)


def execute(query: str, params: Any = ()) -> None:
    """Global DuckDB deposunda yazma sorgusu çalıştırır."""
    duckdb_store.execute(query=query, params=params)


def clear_store_buffer() -> int:
    """Global DuckDB deposunun tamponundaki bekleyen sorguları temizler."""
    return duckdb_store.clear_buffer()


def get_store_stats() -> dict[str, Any]:
    """Global DuckDB deposunun istatistiklerini döner."""
    return duckdb_store.get_stats()


def get_store_stats_orjson_bytes() -> bytes:
    """Global DuckDB deposunun istatistiklerini orjson binary olarak döner."""
    return duckdb_store.to_orjson_bytes()


__all__: Final[list[str]] = [
    "DEFAULT_BUFFER_SIZE",
    "DEFAULT_DUCKDB_STORE_PATH",
    "DEFAULT_FLUSH_INTERVAL",
    "DuckDBStateStore",
    "DuckDBStore",
    "clear_store_buffer",
    "configure_duckdb_wal",
    "duckdb_store",
    "execute",
    "export_table_to_polars",
    "fetch",
    "fetch_df",
    "fetchone",
    "fetchval",
    "get_store_stats",
    "get_store_stats_orjson_bytes",
    "otel_trace",
    "write_df",
]

