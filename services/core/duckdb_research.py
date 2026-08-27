"""ALPHA BIST — DuckDB Research Engine v1.0

Araştırma ve backtest için DuckDB tabanlı OLAP motoru.
Production DB'ye ağır sorgular bindirmeden offline analiz sağlar.

Veri Akışı:
    TimescaleDB → Parquet → DuckDB (embedded OLAP) → Polars → Research/Backtest

Özellikler:
- Parquet dosyalarını doğrudan sorgula (zero-copy)
- Polars DataFrame entegrasyonu
- Production DB'den bağımsız offline analiz
- Bellek verimli (streaming, lazy loading)

Kullanım:
    from services.core.duckdb_research import research_engine

    # Parquet'ten sorgula
    df = await research_engine.query_parquet("data/market_ticks.parquet", "SELECT * WHERE ticker = 'THYAO'")

    # TimescaleDB'den export et
    await research_engine.export_timescaledb_to_parquet("model_predictions", "data/model_predictions.parquet")

    # Research DB'den sorgula
    df = await research_engine.query_research("SELECT * FROM model_predictions WHERE confidence > 0.8")
"""

import asyncio
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import structlog

try:
    import duckdb
except ImportError:
    duckdb = None

try:
    import polars as pl
except ImportError:
    pl = None

logger = structlog.get_logger()


class DuckDBResearchEngine:
    """DuckDB tabanlı araştırma motoru — offline OLAP analiz."""

    def __init__(self, research_db_path: str = "data/research.duckdb"):
        if duckdb is None:
            raise RuntimeError("duckdb not installed. Run: pip install duckdb")

        self._db_path = Path(research_db_path)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn: duckdb.DuckDBPyConnection | None = None
        self._parquet_cache: dict[str, Any] = {}

    def _get_conn(self) -> duckdb.DuckDBPyConnection:
        """DuckDB bağlantısı al (lazy init)."""
        if self._conn is None:
            self._conn = duckdb.connect(str(self._db_path))
            # Performans ayarları
            self._conn.execute("SET memory_limit = '2GB'")
            self._conn.execute("SET threads = 4")
            logger.info("DuckDB research engine connected", path=str(self._db_path))
        return self._conn

    def close(self):
        """Bağlantıyı kapat."""
        if self._conn:
            self._conn.close()
            self._conn = None

    # =====================================================
    # PARQUET OPERATIONS
    # =====================================================

    def query_parquet(self, parquet_path: str, sql: str | None = None, params: dict | None = None) -> "pl.DataFrame":
        """Parquet dosyasını sorgula ve Polars DataFrame döndür.

        Args:
            parquet_path: Parquet dosya yolu
            sql: SQL sorgusu. None ise SELECT * kullanılır.
                FROM clause yoksa otomatik olarak read_parquet('{parquet_path}') eklenir.
                FROM clause varsa parquet_path parametresi kullanılmaz.
            params: Sorgu parametreleri

        Returns:
            Polars DataFrame
        """
        if pl is None:
            raise RuntimeError("polars not installed")

        conn = self._get_conn()

        if sql is None:
            query = f"SELECT * FROM read_parquet('{parquet_path}')"
        else:
            # FROM clause yoksa otomatik ekle (footgun önleme)
            import re
            if not re.search(r'\bFROM\b', sql, re.IGNORECASE):
                query = f"{sql} FROM read_parquet('{parquet_path}')"
            else:
                query = sql

        try:
            result = conn.execute(query)
            df = result.pl()
            return df
        except Exception as e:
            logger.error("Parquet query failed", path=parquet_path, error=str(e))
            raise

    def register_parquet(self, name: str, parquet_path: str):
        """Parquet dosyasını sanal tablo olarak kaydet.

        Args:
            name: Sanal tablo adı
            parquet_path: Parquet dosya yolu
        """
        conn = self._get_conn()
        conn.execute(f"CREATE OR REPLACE VIEW {name} AS SELECT * FROM read_parquet('{parquet_path}')")
        self._parquet_cache[name] = parquet_path
        logger.info("Parquet registered as view", name=name, path=parquet_path)

    def list_parquet_views(self) -> list[str]:
        """Kayıtlı Parquet view'ları listele."""
        return list(self._parquet_cache.keys())

    # =====================================================
    # RESEARCH DB OPERATIONS
    # =====================================================

    def query_research(self, sql: str, params: dict | None = None) -> "pl.DataFrame":
        """Research DB'den sorgula.

        Args:
            sql: SQL sorgusu
            params: Sorgu parametreleri

        Returns:
            Polars DataFrame
        """
        if pl is None:
            raise RuntimeError("polars not installed")

        conn = self._get_conn()

        try:
            result = conn.execute(sql)
            df = result.pl()
            return df
        except Exception as e:
            logger.error("Research query failed", error=str(e))
            raise

    def execute_research(self, sql: str, params: dict | None = None) -> None:
        """Research DB'de sorgu çalıştır (write).

        Args:
            sql: SQL sorgusu
            params: Sorgu parametreleri
        """
        conn = self._get_conn()
        try:
            conn.execute(sql)
        except Exception as e:
            logger.error("Research execute failed", error=str(e))
            raise

    # =====================================================
    # TIMESCALEDB → PARQUET EXPORT
    # =====================================================

    async def export_timescaledb_to_parquet(
        self,
        table: str,
        parquet_path: str,
        where: str = "",
        batch_size: int = 10000,
    ) -> dict[str, Any]:
        """TimescaleDB tablosunu Parquet'e aktar.

        Optimizasyon: Batch'leri ayrı geçici dosyalara yazar, sonunda tek Parquet'te birleştirir.
        Eski yöntem her batch'te mevcut Parquet'i okuyup tekrar yazıyordu (O(n²) I/O).

        Args:
            table: TimescaleDB tablo adı
            parquet_path: Çıktı Parquet dosya yolu
            where: Filtre koşulu (opsiyonel)
            batch_size: Toplu okuma boyutu

        Returns:
            Export istatistikleri
        """
        if pl is None:
            raise RuntimeError("polars not installed")

        import tempfile

        from .database import pg_fetch

        output_path = Path(parquet_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        # Toplam satır sayısını al
        count_query = f"SELECT COUNT(*) FROM {table}"
        if where:
            count_query += f" WHERE {where}"

        total_rows = await pg_fetch(count_query)
        total = total_rows[0]["count"] if total_rows else 0

        if total == 0:
            logger.warning("No data to export", table=table)
            return {"table": table, "rows_exported": 0, "parquet_path": parquet_path}

        # Batch'leri geçici dosyalara yaz, sonunda birleştir
        offset = 0
        rows_exported = 0
        batch_files: list[str] = []

        with tempfile.TemporaryDirectory() as tmpdir:
            while offset < total:
                query = f"SELECT * FROM {table}"
                if where:
                    query += f" WHERE {where}"
                query += f" ORDER BY 1 LIMIT {batch_size} OFFSET {offset}"

                rows = await pg_fetch(query)
                if not rows:
                    break

                df = pl.from_dicts([dict(r) for r in rows])

                # Geçici batch dosyasına yaz
                batch_path = f"{tmpdir}/batch_{len(batch_files):04d}.parquet"
                df.write_parquet(batch_path)
                batch_files.append(batch_path)

                rows_exported += len(rows)
                offset += batch_size

                logger.debug(
                    "Export progress",
                    table=table,
                    exported=rows_exported,
                    total=total,
                )

            # Tüm batch'leri tek Parquet'te birleştir
            if batch_files:
                if len(batch_files) == 1:
                    # Tek batch — doğrudan kopyala
                    import shutil
                    shutil.move(batch_files[0], str(output_path))
                else:
                    # Çoklu batch — Polars ile birleştir (lazy, memory-efficient)
                    combined = pl.concat([pl.read_parquet(f) for f in batch_files])
                    combined.write_parquet(str(output_path))

        logger.info(
            "TimescaleDB → Parquet export completed",
            table=table,
            rows_exported=rows_exported,
            parquet_path=parquet_path,
        )

        return {
            "table": table,
            "rows_exported": rows_exported,
            "parquet_path": parquet_path,
            "file_size_bytes": output_path.stat().st_size if output_path.exists() else 0,
        }

    async def export_all_timescaledb(self, output_dir: str = "data/parquet") -> list[dict]:
        """Tüm TimescaleDB tablolarını Parquet'e aktar.

        Args:
            output_dir: Çıktı dizini

        Returns:
            Export sonuçları
        """
        tables = [
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

        results = []
        for table in tables:
            try:
                result = await self.export_timescaledb_to_parquet(
                    table=table,
                    parquet_path=f"{output_dir}/{table}.parquet",
                )
                results.append(result)
            except Exception as e:
                logger.error("Export failed", table=table, error=str(e))
                results.append({"table": table, "error": str(e)})

        return results

    # =====================================================
    # RESEARCH TABLE OPERATIONS
    # =====================================================

    def create_research_table(self, name: str, schema: dict[str, str]):
        """Research tablosu oluştur.

        Args:
            name: Tablo adı
            schema: Sütun adı → tip eşleme
        """
        conn = self._get_conn()
        columns = ", ".join(f"{col} {dtype}" for col, dtype in schema.items())
        conn.execute(f"CREATE TABLE IF NOT EXISTS {name} ({columns})")
        logger.info("Research table created", name=name)

    def insert_from_parquet(self, table: str, parquet_path: str):
        """Parquet dosyasından research tablosuna veri aktar.

        Args:
            table: Hedef tablo adı
            parquet_path: Kaynak Parquet dosya yolu
        """
        conn = self._get_conn()
        conn.execute(f"INSERT INTO {table} SELECT * FROM read_parquet('{parquet_path}')")
        logger.info("Data inserted from Parquet", table=table, path=parquet_path)

    def get_stats(self) -> dict[str, Any]:
        """Research DB istatistikleri."""
        conn = self._get_conn()

        try:
            tables = conn.execute(
                "SELECT table_name FROM information_schema.tables WHERE table_schema = 'main'"
            ).fetchall()

            stats = {}
            for (table,) in tables:
                try:
                    count = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                    stats[table] = count
                except Exception:
                    stats[table] = 0

            return {
                "db_path": str(self._db_path),
                "db_size_bytes": self._db_path.stat().st_size if self._db_path.exists() else 0,
                "tables": stats,
                "parquet_views": list(self._parquet_cache.keys()),
            }
        except Exception as e:
            return {"error": str(e)}

    # =====================================================
    # HELPERS
    # =====================================================

    def _extract_table_name(self, sql: str) -> str:
        """SQL'den tablo adını çıkar."""
        import re

        match = re.search(r"FROM\s+(\w+)", sql, re.IGNORECASE)
        return match.group(1) if match else ""


# Singleton
research_engine = DuckDBResearchEngine()
