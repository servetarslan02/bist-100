from typing import Any

"""ALPHA BIST — DuckDB Research Engine Tests

Gerçek fonksiyonel testler:
- Parquet okuma/yazma
- Research tablo işlemleri
- Polars DataFrame entegrasyonu
- Export fonksiyonları

Kullanım:
    python -m pytest tests/test_duckdb_research.py -v
"""

import tempfile
from pathlib import Path

import polars as pl
import pytest

from services.core.duckdb_research import DuckDBResearchEngine

# =====================================================
# FIXTURES
# =====================================================


@pytest.fixture
def research_engine() -> Any:
    """Test için DuckDB research engine."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = str(Path(tmpdir) / "test_research.duckdb")
        engine = DuckDBResearchEngine(db_path)
        yield engine
        engine.close()


@pytest.fixture
def sample_parquet(tmp_path) -> Any:
    """Test Parquet dosyası oluştur."""
    df = pl.DataFrame(
        {
            "ticker": ["THYAO", "GARAN", "AKBNK", "THYAO", "GARAN"],
            "price": [100.0, 50.0, 30.0, 101.0, 51.0],
            "volume": [1000, 500, 300, 1200, 600],
            "date": ["2025-01-01", "2025-01-01", "2025-01-01", "2025-01-02", "2025-01-02"],
        }
    )
    path = str(tmp_path / "test_data.parquet")
    df.write_parquet(path)
    return path


# =====================================================
# PARQUET OPERATIONS TESTS
# =====================================================


class TestParquetOperations:
    """Parquet okuma/yazma testleri."""

    def test_query_parquet_returns_polars(self, research_engine, sample_parquet) -> Any:
        """Parquet sorgusu Polars DataFrame döndürmeli."""
        result = research_engine.query_parquet(sample_parquet)
        assert isinstance(result, pl.DataFrame)
        assert len(result) == 5

    def test_query_parquet_with_filter(self, research_engine, sample_parquet) -> Any:
        """Parquet sorgusu filtre çalışmalı."""
        result = research_engine.query_parquet(
            sample_parquet,
            f"SELECT * FROM read_parquet('{sample_parquet}') WHERE ticker = 'THYAO'",
        )
        assert len(result) == 2
        assert all(result["ticker"] == "THYAO")

    def test_query_parquet_with_aggregation(self, research_engine, sample_parquet) -> Any:
        """Parquet sorgusu aggregation çalışmalı."""
        result = research_engine.query_parquet(
            sample_parquet,
            f"SELECT ticker, AVG(price) as avg_price FROM read_parquet('{sample_parquet}') GROUP BY ticker",
        )
        assert len(result) == 3  # THYAO, GARAN, AKBNK
        assert "avg_price" in result.columns

    def test_register_parquet_view(self, research_engine, sample_parquet) -> Any:
        """Parquet view olarak kaydedilmeli."""
        research_engine.register_parquet("market_data", sample_parquet)
        assert "market_data" in research_engine.list_parquet_views()

    def test_query_registered_view(self, research_engine, sample_parquet) -> Any:
        """Kayıtlı view sorgulanabilmeli."""
        research_engine.register_parquet("market_data", sample_parquet)
        result = research_engine.query_research("SELECT * FROM market_data")
        assert len(result) == 5

    def test_parquet_write_and_read(self, research_engine, tmp_path) -> Any:
        """Parquet yazma ve okuma döngüsü çalışmalı."""
        # Parquet yaz
        df = pl.DataFrame({"a": [1, 2, 3], "b": [4, 5, 6]})
        parquet_path = str(tmp_path / "write_test.parquet")
        df.write_parquet(parquet_path)

        # Parquet oku
        result = research_engine.query_parquet(parquet_path)
        assert len(result) == 3
        assert result["a"].to_list() == [1, 2, 3]
        assert result["b"].to_list() == [4, 5, 6]


# =====================================================
# RESEARCH DB TESTS
# =====================================================


class TestResearchDB:
    """Research DB işlemleri testleri."""

    def test_create_table(self, research_engine) -> Any:
        """Research tablosu oluşturulabilmeli."""
        research_engine.create_research_table(
            "test_table",
            {"id": "INTEGER", "name": "VARCHAR", "value": "DOUBLE"},
        )

        # Tablo oluşturuldu mu kontrol et
        stats = research_engine.get_stats()
        assert "test_table" in stats["tables"]

    def test_insert_and_query(self, research_engine) -> Any:
        """Veri yazma ve okuma çalışmalı."""
        research_engine.create_research_table(
            "test_data",
            {"ticker": "VARCHAR", "price": "DOUBLE"},
        )

        research_engine.execute_research("INSERT INTO test_data VALUES ('THYAO', 100.0), ('GARAN', 50.0)")

        result = research_engine.query_research("SELECT * FROM test_data ORDER BY ticker")
        assert len(result) == 2
        assert result["ticker"].to_list() == ["GARAN", "THYAO"]

    def test_insert_from_parquet(self, research_engine, sample_parquet) -> Any:
        """Parquet'ten research tablosuna veri aktarılabilmeli."""
        research_engine.create_research_table(
            "market_data",
            {"ticker": "VARCHAR", "price": "DOUBLE", "volume": "BIGINT", "date": "VARCHAR"},
        )

        research_engine.insert_from_parquet("market_data", sample_parquet)

        result = research_engine.query_research("SELECT COUNT(*) as cnt FROM market_data")
        assert result["cnt"].to_list()[0] == 5

    def test_get_stats(self, research_engine) -> Any:
        """İstatistikler doğru döndürülmeli."""
        research_engine.create_research_table("t1", {"id": "INTEGER"})
        research_engine.create_research_table("t2", {"id": "INTEGER"})

        stats = research_engine.get_stats()
        assert "db_path" in stats
        assert "db_size_bytes" in stats
        assert "tables" in stats
        assert "t1" in stats["tables"]
        assert "t2" in stats["tables"]


# =====================================================
# POLARS INTEGRATION TESTS
# =====================================================


class TestPolarsIntegration:
    """Polars DataFrame entegrasyonu testleri."""

    def test_query_returns_polars(self, research_engine, sample_parquet) -> Any:
        """Sorgular Polars DataFrame döndürmeli."""
        research_engine.register_parquet("data", sample_parquet)
        result = research_engine.query_research("SELECT * FROM data")
        assert isinstance(result, pl.DataFrame)

    def test_polars_operations(self, research_engine, sample_parquet) -> Any:
        """Polars işlemleri çalışmalı."""
        research_engine.register_parquet("data", sample_parquet)
        df = research_engine.query_research("SELECT * FROM data")

        # Polars aggregation
        grouped = df.group_by("ticker").agg(pl.col("price").mean())
        assert len(grouped) == 3

        # Polars filter
        thyao = df.filter(pl.col("ticker") == "THYAO")
        assert len(thyao) == 2

    def test_lazy_query(self, research_engine, sample_parquet) -> Any:
        """Lazy sorgu çalışmalı."""
        research_engine.register_parquet("data", sample_parquet)
        df = research_engine.query_research("SELECT * FROM data")

        # Polars lazy operations
        result = df.lazy().filter(pl.col("price") > 50).select(["ticker", "price"]).collect()
        assert len(result) == 3  # THYAO x2, GARAN x1


# =====================================================
# ERROR HANDLING TESTS
# =====================================================


class TestErrorHandling:
    """Hata yönetimi testleri."""

    def test_invalid_parquet_path(self, research_engine) -> Any:
        """Geçersiz Parquet yolu hata vermeli."""
        with pytest.raises((RuntimeError, ValueError, Exception)):
            research_engine.query_parquet("/nonexistent/path.parquet")

    def test_invalid_sql(self, research_engine, sample_parquet) -> Any:
        """Geçersiz SQL hata vermeli."""
        research_engine.register_parquet("data", sample_parquet)
        with pytest.raises((RuntimeError, ValueError, Exception)):
            research_engine.query_research("INVALID SQL QUERY")

    def test_close_and_reopen(self, sample_parquet) -> Any:
        """Kapatıp yeniden açma çalışmalı."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = str(Path(tmpdir) / "test.duckdb")

            # İlk oturum
            engine1 = DuckDBResearchEngine(db_path)
            engine1.create_research_table("test", {"id": "INTEGER"})
            engine1.close()

            # İkinci oturum
            engine2 = DuckDBResearchEngine(db_path)
            stats = engine2.get_stats()
            assert "test" in stats["tables"]
            engine2.close()
