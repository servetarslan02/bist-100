"""
ALPHA BIST — DuckDB Research Engine v2.0 (DuckDB + Polars)

Araştırma, kantitatif modelleme ve backtest için DuckDB ve Polars tabanlı OLAP motoru.
Production veritabanına ağır analitik yükler bindirmeden yerel, gömülü ve yüksek hızlı
offline analiz kabiliyeti sunar.

Veri Akışı:
    TimescaleDB → Parquet → DuckDB (embedded OLAP) → Polars → Research / Backtest

Özellikler:
- Parquet dosyalarını doğrudan diskten sıfır kopyalama (zero-copy) ile sorgulama.
- Yüksek hacimli projeksiyon ve koşul filtreleme (Projection & Predicate Pushdown).
- Polars DataFrame ve LazyFrame entegrasyonu (GEMINI.md Kural 2).
- Eşzamanlı (thread-safe) kilit ve kaynak yönetimi.
- Windows dosya kilidi ve 0-byte bozuk veritabanı kurtarma mekanizması.
- Kişisel PC donanım sınırlarına duyarlı bellek ve iş parçacığı optimizasyonu.
"""

from __future__ import annotations

import asyncio
import functools
import re
import tempfile
import threading
from pathlib import Path
from typing import Any, Callable, Final

import duckdb
import polars as pl
import structlog
from opentelemetry import trace

logger = structlog.get_logger(__name__)
tracer = trace.get_tracer("alpha-bist.duckdb_research")

DEFAULT_RESEARCH_DB_PATH: Final[str] = "data/research.duckdb"
DEFAULT_PARQUET_OUTPUT_DIR: Final[str] = "data/parquet"
DEFAULT_BATCH_SIZE: Final[int] = 10000

DEFAULT_EXPORT_TABLES: Final[list[str]] = [
    "model_predictions",
    "daily_performance",
    "equity_curve",
    "daily_pnl",
    "equity_snapshots",
    "scan_results",
    "alerts",
    "audit_logs",
    "system_events",
    "paper_trades",
    "backtest_runs",
]


def otel_trace(span_name: str) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Metot çağrılarını OpenTelemetry span'i ile sarmalayan dekoratör.

    Senkron ve asenkron metotları otomatik tespit ederek uygun sarmalayıcıyı uygular.

    Args:
        span_name: OTel span adı.

    Returns:
        Sarmalayıcı dekoratör fonksiyonu.
    """

    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        """Fonksiyonu OTel span bağlamında çalıştırır."""

        @functools.wraps(func)
        async def async_wrapper(self: Any, *args: Any, **kwargs: Any) -> Any:
            """Asenkron fonksiyon için span oluşturur ve yürütür."""
            with tracer.start_as_current_span(span_name):
                return await func(self, *args, **kwargs)

        @functools.wraps(func)
        def sync_wrapper(self: Any, *args: Any, **kwargs: Any) -> Any:
            """Senkron fonksiyon için span oluşturur ve yürütür."""
            with tracer.start_as_current_span(span_name):
                return func(self, *args, **kwargs)

        return async_wrapper if asyncio.iscoroutinefunction(func) else sync_wrapper

    return decorator


class DuckDBResearchEngine:
    """DuckDB ve Polars tabanlı analitik araştırma motoru (OLAP).

    Özellikler:
    - Parquet dosyalarını sıfır kopyalama ile sorgulama ve Polars DataFrame üretme.
    - Sanal Parquet görünümleri (view) kaydederek SQL sorgularında kullanabilme.
    - TimescaleDB üretim verilerini parça parça Parquet formatına aktarma.
    - Donanım profil yöneticisi ile uyumlu bellek ve iş parçacığı yapılandırması.
    - Eşzamanlı okuma/yazma emniyeti sağlayan reentrant kilit (RLock) mekanizması.
    """

    def __init__(self, research_db_path: str = DEFAULT_RESEARCH_DB_PATH) -> None:
        """DuckDBResearchEngine nesnesini başlatır.

        Args:
            research_db_path: DuckDB veritabanı dosyasının disk konumu.
        """
        self._db_path: Path = Path(research_db_path)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn: duckdb.DuckDBPyConnection | None = None
        self._parquet_cache: dict[str, str] = {}
        self._lock: threading.RLock = threading.RLock()

    def __repr__(self) -> str:
        """DuckDBResearchEngine nesnesinin okunabilir temsilini döner."""
        return (
            f"DuckDBResearchEngine(db_path={str(self._db_path)!r}, "
            f"registered_views={len(self._parquet_cache)}, "
            f"is_connected={self._conn is not None})"
        )

    def __enter__(self) -> DuckDBResearchEngine:
        """Bağlam yöneticisi başlangıcı."""
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        """Bağlam yöneticisi bitişi; kaynakları serbest bırakır."""
        self.close()

    def _get_conn(self) -> duckdb.DuckDBPyConnection:
        """Aktif DuckDB bağlantısını döner veya güvenli şekilde başlatır (lazy init).

        Returns:
            DuckDB bağlantı nesnesi.

        Raises:
            duckdb.Error: Bağlantı kurulamazsa.
        """
        with self._lock:
            if self._conn is None:
                # Windows sıfır-bayt bozuk dosya önlemi
                if self._db_path.exists() and self._db_path.is_file() and self._db_path.stat().st_size == 0:
                    try:
                        self._db_path.unlink()
                        logger.warning(
                            "Bozuk sıfır baytlık DuckDB araştırma dosyası temizlendi",
                            path=str(self._db_path),
                        )
                    except OSError as unlink_err:
                        logger.debug("Sıfır baytlık dosya silinirken hata", error=str(unlink_err))

                try:
                    self._conn = duckdb.connect(str(self._db_path))
                    # SSD yazma azaltımı: WAL yapılandırması
                    try:
                        from services.core.duckdb_store import configure_duckdb_wal

                        configure_duckdb_wal(self._conn)
                    except Exception as wal_err:
                        logger.debug("DuckDB WAL yapılandırması atlandı", error=str(wal_err))
                except Exception as lock_err:
                    logger.debug(
                        "DuckDB yazma bağlantısı kilitli, salt-okunur mod deneniyor",
                        error=str(lock_err),
                    )
                    self._conn = duckdb.connect(str(self._db_path), read_only=True)

                # Kişisel PC Adaptif Performans ve Bellek Sınırları
                try:
                    from services.core.hardware_profile import hardware_manager

                    max_mem = f"{hardware_manager.limits.max_duckdb_memory_mb}MB"
                    max_threads = hardware_manager.limits.max_cpu_threads
                except Exception:
                    max_mem = "1GB"
                    max_threads = 2

                self._conn.execute(f"SET memory_limit = '{max_mem}'")
                self._conn.execute(f"SET threads = {max_threads}")
                logger.info(
                    "DuckDB araştırma motoru bağlandı",
                    path=str(self._db_path),
                    memory_limit=max_mem,
                    threads=max_threads,
                )

            return self._conn

    def close(self) -> None:
        """DuckDB bağlantısını güvenle kapatır ve kaynakları temizler."""
        with self._lock:
            if self._conn is not None:
                try:
                    self._conn.close()
                except Exception as close_err:
                    logger.debug("DuckDB kapatılırken hata oluştu", error=str(close_err))
                finally:
                    self._conn = None

    @staticmethod
    def _escape_path(path: str | Path) -> str:
        """SQL sorgularında dosya yollarının tek tırnak enjeksiyonunu engeller.

        Args:
            path: Temizlenecek dosya yolu.

        Returns:
            Kaçış karakterleri eklenmiş güvenli dosya yolu.
        """
        return str(path).replace("'", "''")

    @staticmethod
    def _is_valid_identifier(name: str) -> bool:
        """SQL tanımlayıcı adını doğrular (SQL Injection koruması).

        Args:
            name: Denetlenecek tanımlayıcı adı (tablo, view, kolon).

        Returns:
            Geçerli ise True, aksi halde False.
        """
        return bool(re.match(r"^[a-zA-Z_][a-zA-Z0-9_]*$", name))

    # =====================================================
    # PARQUET OPERASYONLARI
    # =====================================================

    @otel_trace("duckdb_research.query_parquet")
    def query_parquet(
        self,
        parquet_path: str | Path,
        sql: str | None = None,
        params: dict[str, Any] | list[Any] | None = None,
    ) -> pl.DataFrame:
        """Parquet dosyasını doğrudan sorgular ve Polars DataFrame döner.

        Args:
            parquet_path: Kaynak Parquet dosyasının yolu.
            sql: Çalıştırılacak SQL sorgusu. None ise 'SELECT * FROM ...' varsayılır.
                 Sorguda 'FROM' ifadesi yoksa otomatik olarak dosya eklenir.
            params: Sorguya bağlanacak parametreler (opsiyonel).

        Returns:
            Sorgu sonucunu içeren Polars DataFrame.

        Raises:
            Exception: Sorgu yürütme hatası durumunda.
        """
        safe_path = self._escape_path(parquet_path)

        if sql is None:
            query = f"SELECT * FROM read_parquet('{safe_path}')"
        else:
            stripped = sql.strip()
            if not re.search(r"\bFROM\b", stripped, re.IGNORECASE):
                # WHERE, GROUP BY, ORDER BY, LIMIT, HAVING tespit edilirse FROM araya eklenir
                clause_match = re.search(
                    r"\b(WHERE|GROUP\s+BY|ORDER\s+BY|LIMIT|HAVING)\b",
                    stripped,
                    re.IGNORECASE,
                )
                if clause_match:
                    idx = clause_match.start()
                    prefix = stripped[:idx].strip()
                    suffix = stripped[idx:].strip()
                    if not prefix:
                        prefix = "SELECT *"
                    elif not prefix.upper().startswith("SELECT"):
                        prefix = f"SELECT {prefix}"
                    query = f"{prefix} FROM read_parquet('{safe_path}') {suffix}"
                else:
                    if not stripped.upper().startswith("SELECT"):
                        query = f"SELECT {stripped} FROM read_parquet('{safe_path}')"
                    else:
                        query = f"{stripped} FROM read_parquet('{safe_path}')"
            else:
                query = stripped

        with self._lock:
            conn = self._get_conn()
            try:
                result = conn.execute(query, params) if params is not None else conn.execute(query)
                return result.pl()
            except Exception as exc:
                logger.error(
                    "Parquet sorgusu başarısız oldu",
                    path=str(parquet_path),
                    query=query[:200],
                    error=str(exc),
                )
                raise

    @otel_trace("duckdb_research.query_parquet_columns")
    def query_parquet_columns(
        self,
        parquet_path: str | Path,
        columns: list[str],
        where_clause: str | None = None,
        params: dict[str, Any] | list[Any] | None = None,
    ) -> pl.DataFrame:
        """Projection ve Predicate pushdown ile yalnızca istenen kolonları bellek dostu çeker.

        Args:
            parquet_path: Parquet dosya yolu.
            columns: Çekilecek sütun adları listesi.
            where_clause: İsteğe bağlı filtreleme koşulu (örn: 'volume > 1000').
            params: Sorgu parametreleri.

        Returns:
            Filtrelenmiş Polars DataFrame.
        """
        safe_path = self._escape_path(parquet_path)

        if not columns:
            cols_str = "*"
        else:
            clean_cols = []
            for col in columns:
                clean = col.strip('"')
                if not self._is_valid_identifier(clean):
                    raise ValueError(f"Geçersiz sütun adı: {col!r}")
                clean_cols.append(clean)
            cols_str = ", ".join(f'"{c}"' for c in clean_cols)

        query = f"SELECT {cols_str} FROM read_parquet('{safe_path}')"
        if where_clause:
            query += f" WHERE {where_clause}"

        with self._lock:
            conn = self._get_conn()
            try:
                result = conn.execute(query, params) if params is not None else conn.execute(query)
                return result.pl()
            except Exception as exc:
                logger.error(
                    "Sütun filtreli Parquet sorgusu başarısız oldu",
                    path=str(parquet_path),
                    error=str(exc),
                )
                raise

    def scan_parquet(self, parquet_path: str | Path) -> pl.LazyFrame:
        """Parquet dosyasını sıfır bellek tüketimi ile sorgulamak üzere Polars LazyFrame döner.

        Args:
            parquet_path: Parquet dosya yolu.

        Returns:
            Polars LazyFrame nesnesi.
        """
        return pl.scan_parquet(str(parquet_path))

    @otel_trace("duckdb_research.register_parquet")
    def register_parquet(self, name: str, parquet_path: str | Path) -> None:
        """Parquet dosyasını DuckDB içinde sanal bir görünüm (VIEW) olarak kaydeder.

        Args:
            name: Sanal tablo adı (geçerli SQL identifier olmalıdır).
            parquet_path: Hedef Parquet dosyasının yolu.

        Raises:
            ValueError: Tablo adı geçersiz ise.
        """
        if not self._is_valid_identifier(name):
            raise ValueError(f"Geçersiz sanal görünüm adı: {name!r}")

        safe_path = self._escape_path(parquet_path)
        with self._lock:
            conn = self._get_conn()
            conn.execute(f"CREATE OR REPLACE VIEW \"{name}\" AS SELECT * FROM read_parquet('{safe_path}')")
            self._parquet_cache[name] = str(parquet_path)
            logger.info("Parquet sanal tablo olarak kaydedildi", name=name, path=str(parquet_path))

    def list_parquet_views(self) -> list[str]:
        """Sisteme kayıtlı sanal Parquet görünümlerinin isimlerini döner.

        Returns:
            Kayıtlı görünüm adları listesi.
        """
        with self._lock:
            return list(self._parquet_cache.keys())

    # =====================================================
    # RESEARCH VERİTABANI OPERASYONLARI
    # =====================================================

    @otel_trace("duckdb_research.query_research")
    def query_research(
        self,
        sql: str,
        params: dict[str, Any] | list[Any] | None = None,
    ) -> pl.DataFrame:
        """Research veritabanında salt-okunur analitik sorgu çalıştırır ve Polars DataFrame döner.

        Args:
            sql: Çalıştırılacak SQL sorgusu.
            params: Sorgu parametreleri.

        Returns:
            Sonuç kümesini içeren Polars DataFrame.
        """
        with self._lock:
            conn = self._get_conn()
            try:
                result = conn.execute(sql, params) if params is not None else conn.execute(sql)
                return result.pl()
            except Exception as exc:
                logger.error("Araştırma sorgusu başarısız oldu", sql=sql[:200], error=str(exc))
                raise

    @otel_trace("duckdb_research.execute_research")
    def execute_research(
        self,
        sql: str,
        params: dict[str, Any] | list[Any] | None = None,
    ) -> None:
        """Research veritabanında DDL veya DML (yazma/oluşturma) sorgusu çalıştırır.

        Args:
            sql: Çalıştırılacak SQL sorgusu.
            params: Sorgu parametreleri.
        """
        with self._lock:
            conn = self._get_conn()
            try:
                if params is not None:
                    conn.execute(sql, params)
                else:
                    conn.execute(sql)
            except Exception as exc:
                logger.error("Araştırma yürütme hatası", sql=sql[:200], error=str(exc))
                raise

    def export_research_to_polars(self, table: str, limit: int = 1000) -> pl.DataFrame:
        """Araştırma veritabanındaki bir tabloyu Polars DataFrame olarak dışa aktarır.

        Args:
            table: Hedef tablo adı.
            limit: Maksimum satır sayısı.

        Returns:
            Polars DataFrame.
        """
        if not self._is_valid_identifier(table):
            raise ValueError(f"Geçersiz tablo adı: {table!r}")

        with self._lock:
            conn = self._get_conn()
            try:
                return conn.execute(f'SELECT * FROM "{table}" LIMIT ?', (limit,)).pl()
            except Exception as exc:
                logger.error("Tablo Polars formatına aktarılamadı", table=table, error=str(exc))
                raise

    def create_research_table(self, name: str, schema: dict[str, str]) -> None:
        """Research veritabanında yeni bir analitik tablo oluşturur.

        Args:
            name: Tablo adı.
            schema: Sütun adı → Veri tipi eşlemesi (örn: {'ticker': 'TEXT', 'score': 'DOUBLE'}).

        Raises:
            ValueError: Tablo veya sütun adı güvenlik kurallarını ihlal ediyorsa.
        """
        if not self._is_valid_identifier(name):
            raise ValueError(f"Geçersiz tablo adı: {name!r}")
        for col in schema:
            if not self._is_valid_identifier(col):
                raise ValueError(f"Geçersiz sütun adı: {col!r}")

        columns_sql = ", ".join(f'"{col}" {dtype}' for col, dtype in schema.items())
        with self._lock:
            conn = self._get_conn()
            conn.execute(f'CREATE TABLE IF NOT EXISTS "{name}" ({columns_sql})')
            logger.info("Araştırma tablosu oluşturuldu", name=name)

    def insert_from_parquet(self, table: str, parquet_path: str | Path) -> None:
        """Parquet dosyasındaki tüm verileri araştırma tablosuna kopyalar.

        Args:
            table: Hedef tablo adı.
            parquet_path: Kaynak Parquet dosyasının yolu.

        Raises:
            ValueError: Tablo adı geçersiz ise.
        """
        if not self._is_valid_identifier(table):
            raise ValueError(f"Geçersiz tablo adı: {table!r}")

        safe_path = self._escape_path(parquet_path)
        with self._lock:
            conn = self._get_conn()
            conn.execute(f'INSERT INTO "{table}" SELECT * FROM read_parquet(\'{safe_path}\')')
            logger.info("Parquet verisi araştırma tablosuna aktarıldı", table=table, path=str(parquet_path))

    # =====================================================
    # TIMESCALEDB → PARQUET AKTARIMI
    # =====================================================

    @otel_trace("duckdb_research.export_timescaledb_to_parquet")
    async def export_timescaledb_to_parquet(
        self,
        table: str,
        parquet_path: str | Path,
        where: str = "",
        batch_size: int = DEFAULT_BATCH_SIZE,
    ) -> dict[str, Any]:
        """TimescaleDB tablosundaki verileri parça parça çekip optimize Parquet formatına aktarır.

        Args:
            table: TimescaleDB kaynak tablosu.
            parquet_path: Hedef Parquet dosya konumu.
            where: İsteğe bağlı filtre koşulu.
            batch_size: Tek seferde hafızaya alınacak satır adedi.

        Returns:
            İşlem özet istatistikleri.
        """
        if not self._is_valid_identifier(table):
            raise ValueError(f"Geçersiz tablo adı: {table!r}")

        from .database import pg_fetch

        output_path = Path(parquet_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        count_query = f'SELECT COUNT(*) FROM "{table}"'
        if where:
            count_query += f" WHERE {where}"

        total_rows = await pg_fetch(count_query)
        total = total_rows[0]["count"] if total_rows else 0

        if total == 0:
            logger.warning("Aktarılacak veri bulunamadı", table=table)
            return {
                "table": table,
                "rows_exported": 0,
                "parquet_path": str(parquet_path),
                "file_size_bytes": 0,
            }

        offset = 0
        rows_exported = 0
        batch_files: list[str] = []

        with tempfile.TemporaryDirectory() as tmpdir:
            while offset < total:
                query = f'SELECT * FROM "{table}"'
                if where:
                    query += f" WHERE {where}"
                query += f" ORDER BY 1 LIMIT {batch_size} OFFSET {offset}"

                rows = await pg_fetch(query)
                if not rows:
                    break

                df = pl.from_dicts([dict(r) for r in rows])
                batch_path = f"{tmpdir}/batch_{len(batch_files):04d}.parquet"
                df.write_parquet(batch_path)
                batch_files.append(batch_path)

                rows_exported += len(rows)
                offset += batch_size

                logger.debug(
                    "Parquet aktarım ilerlemesi",
                    table=table,
                    exported=rows_exported,
                    total=total,
                )

            if batch_files:
                if len(batch_files) == 1:
                    import shutil

                    shutil.move(batch_files[0], str(output_path))
                else:
                    combined = pl.concat([pl.read_parquet(f) for f in batch_files])
                    combined.write_parquet(str(output_path))

        logger.info(
            "TimescaleDB → Parquet aktarımı tamamlandı",
            table=table,
            rows_exported=rows_exported,
            parquet_path=str(parquet_path),
        )

        return {
            "table": table,
            "rows_exported": rows_exported,
            "parquet_path": str(parquet_path),
            "file_size_bytes": output_path.stat().st_size if output_path.exists() else 0,
        }

    @otel_trace("duckdb_research.export_all_timescaledb")
    async def export_all_timescaledb(
        self,
        output_dir: str | Path = DEFAULT_PARQUET_OUTPUT_DIR,
    ) -> list[dict[str, Any]]:
        """Sistemde tanımlı tüm kritik TimescaleDB tablolarını Parquet formatında dışa aktarır.

        Args:
            output_dir: Parquet dosyalarının kaydedileceği hedef dizin.

        Returns:
            Her tablonun aktarım durumunu belirten sözlük listesi.
        """
        results: list[dict[str, Any]] = []
        out_dir = Path(output_dir)
        out_dir.mkdir(parents=True, exist_ok=True)

        for table in DEFAULT_EXPORT_TABLES:
            try:
                result = await self.export_timescaledb_to_parquet(
                    table=table,
                    parquet_path=out_dir / f"{table}.parquet",
                )
                results.append(result)
            except Exception as exc:
                logger.error("Tablo aktarımı başarısız oldu", table=table, error=str(exc))
                results.append({"table": table, "error": str(exc)})

        return results

    # =====================================================
    # DURUM VE İSTATİSTİKLER
    # =====================================================

    def get_stats(self) -> dict[str, Any]:
        """Research veritabanı boyut, tablo ve sanal görünüm istatistiklerini döner.

        Returns:
            İstatistik sözlüğü.
        """
        with self._lock:
            conn = self._get_conn()
            try:
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
                    "tables": stats,
                    "parquet_views": list(self._parquet_cache.keys()),
                }
            except Exception as exc:
                return {"error": str(exc)}


# Global tekil örnek
research_engine: Final[DuckDBResearchEngine] = DuckDBResearchEngine()


def get_research_engine() -> DuckDBResearchEngine:
    """Aktif global DuckDBResearchEngine tekil örneğini döner."""
    return research_engine


def query_parquet(
    parquet_path: str | Path,
    sql: str | None = None,
    params: dict[str, Any] | list[Any] | None = None,
) -> pl.DataFrame:
    """Parquet dosyasını doğrudan sorgular ve Polars DataFrame döner."""
    return research_engine.query_parquet(parquet_path=parquet_path, sql=sql, params=params)


def get_research_stats() -> dict[str, Any]:
    """Research motoru istatistiklerini döner."""
    return research_engine.get_stats()


__all__ = [
    "DEFAULT_BATCH_SIZE",
    "DEFAULT_EXPORT_TABLES",
    "DEFAULT_PARQUET_OUTPUT_DIR",
    "DEFAULT_RESEARCH_DB_PATH",
    "DuckDBResearchEngine",
    "get_research_engine",
    "get_research_stats",
    "otel_trace",
    "query_parquet",
    "research_engine",
]
