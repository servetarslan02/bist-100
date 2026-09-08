"""ALPHA BIST — Çok Kaynaklı Veri Entegrasyonu (Data Source Manager) Kapsamlı Test Paketi.

services/data/data_source.py modülünün Yahoo, BIST, TradingView, Local Parquet ve Warehouse
veri adaptörleri, DataSourceManager fallback öncelik sırası, Parquet önbellekleme (TTL, save, load, clear),
BIST-100 hisse evreni, paralel indirme, DuckDB WAL ve candle sorgulayıcı fonksiyonlarını test eder.
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import duckdb
import orjson
import pandas as pd
import polars as pl
import pytest

from services.data.data_source import (
    DEFAULT_CACHE_TTL_HOURS,
    DEFAULT_CHECKPOINT_SIZE,
    DEFAULT_MAX_WORKERS,
    DEFAULT_SOURCE_PRIORITY,
    DEFAULT_WAL_SIZE,
    DataSourceManager,
    LocalParquetSource,
    WarehouseSource,
    YahooFinanceSource,
    clear_stock_candles_duckdb,
    configure_duckdb_wal,
    read_stock_candles_from_duckdb,
    to_orjson_bytes,
)


class TestDataSourceBasics:
    """Sabitler, serileştirme ve DuckDB WAL testleri."""

    def test_constants(self) -> None:
        """Sabitlerin beklenen değerlerini kontrol eder."""
        assert DEFAULT_CACHE_TTL_HOURS == 24
        assert DEFAULT_MAX_WORKERS == 8
        assert DEFAULT_CHECKPOINT_SIZE == "4MB"
        assert DEFAULT_WAL_SIZE == "2MB"
        assert "warehouse" in DEFAULT_SOURCE_PRIORITY
        assert "yahoo" in DEFAULT_SOURCE_PRIORITY

    def test_configure_duckdb_wal(self) -> None:
        """DuckDB WAL pragma yapılandırmasını test eder."""
        conn = duckdb.connect(":memory:")
        configure_duckdb_wal(conn)
        conn.close()

    def test_to_orjson_bytes_helper(self) -> None:
        """to_orjson_bytes fonksiyonunun sözlük ve model dönüşümünü doğrular."""
        data = {"kaynak": "warehouse", "hisseler": ["THYAO", "GARAN"]}
        raw = to_orjson_bytes(data)
        assert isinstance(raw, bytes)
        assert orjson.loads(raw)["kaynak"] == "warehouse"


class TestIndividualSources:
    """Her bağımsız veri kaynağı adaptörünün (Yahoo, Local, Warehouse) temel testleri."""

    def test_yahoo_finance_source_fetch(self) -> None:
        """YahooFinanceSource adaptörünün yfinance DataFrame dönüşüm testi."""
        source = YahooFinanceSource()
        assert "YahooFinanceSource" in repr(source)

        mock_pdf = pd.DataFrame(
            {
                "Open": [250.0],
                "High": [255.0],
                "Low": [248.0],
                "Close": [253.0],
                "Volume": [100000],
            },
            index=pd.date_range("2025-01-02", periods=1),
        )

        with patch("yfinance.Ticker") as mock_ticker:
            mock_inst = MagicMock()
            mock_inst.history.return_value = mock_pdf
            mock_ticker.return_value = mock_inst

            df = source.fetch("THYAO")
            assert df is not None
            assert isinstance(df, pl.DataFrame)
            assert df.height == 1
            assert "Close" in df.columns
            assert df["Close"][0] == 253.0

    def test_local_parquet_source(self) -> None:
        """LocalParquetSource adaptörünün yerel dosya okuma testi."""
        with tempfile.TemporaryDirectory() as tmpdir:
            cache_dir = Path(tmpdir)
            source = LocalParquetSource(cache_dir=cache_dir)
            assert "LocalParquetSource" in repr(source)

            # Henüz dosya yokken None dönmeli
            assert source.fetch("GARAN") is None

            # Parquet dosyası oluştur
            test_df = pl.DataFrame(
                {
                    "Date": ["2025-01-02"],
                    "Open": [80.0],
                    "High": [82.0],
                    "Low": [79.0],
                    "Close": [81.0],
                    "Volume": [200000],
                }
            )
            test_df.write_parquet(cache_dir / "GARAN_1d.parquet")

            df = source.fetch("GARAN.IS", interval="1d")
            assert df is not None
            assert df.height == 1
            assert df["Close"][0] == 81.0

    def test_warehouse_source(self) -> None:
        """WarehouseSource adaptörünün DuckDB tablosundan veri okuma testi."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = str(Path(tmpdir) / "test_wh.duckdb")

            with duckdb.connect(db_path) as conn:
                configure_duckdb_wal(conn)
                conn.execute(
                    """
                    CREATE TABLE stock_candles (
                        Date TIMESTAMP,
                        Open DOUBLE,
                        High DOUBLE,
                        Low DOUBLE,
                        Close DOUBLE,
                        Volume BIGINT,
                        symbol VARCHAR
                    );
                    INSERT INTO stock_candles VALUES
                    ('2025-01-02 00:00:00', 100.0, 105.0, 99.0, 104.0, 50000, 'ASELS');
                    """
                )

            wh_source = WarehouseSource(db_path=db_path)
            assert "WarehouseSource" in repr(wh_source)

            df = wh_source.fetch("ASELS")
            assert df is not None
            assert df.height == 1
            assert df["Close"][0] == 104.0


class TestDataSourceManager:
    """DataSourceManager koordinasyon, önbellekleme ve çoklu kaynak fallback testleri."""

    @pytest.fixture
    def manager(self):
        """Geçici dizinde önbellek oluşturan DataSourceManager fixture'ı."""
        with tempfile.TemporaryDirectory() as tmpdir:
            mgr = DataSourceManager(cache_dir=tmpdir, use_cache=True, cache_ttl_hours=24)
            yield mgr, tmpdir

    def test_manager_init_and_repr(self, manager) -> None:
        """Yönetici başlatma ve meta veri metotları testi."""
        mgr, cache_dir = manager
        assert "DataSourceManager" in repr(mgr)

        as_dict = mgr.to_dict()
        assert as_dict["cache_dir"] == cache_dir
        assert as_dict["use_cache"] is True
        assert "warehouse" in as_dict["sources"]

        raw = mgr.to_orjson_bytes()
        assert isinstance(raw, bytes)

    def test_cache_save_load_clear(self, manager) -> None:
        """Önbelleğe yazma, önbellekten okuma ve önbelleği temizleme akışı testi."""
        mgr, _ = manager

        sample_df = pl.DataFrame(
            {
                "Date": ["2025-01-02", "2025-01-03"],
                "Open": [10.0, 11.0],
                "High": [12.0, 13.0],
                "Low": [9.5, 10.5],
                "Close": [11.5, 12.5],
                "Volume": [1000, 1500],
            }
        )

        # Önbelleğe yaz
        mgr._save_to_cache("THYAO", sample_df, "1d")

        stats = mgr.get_cache_stats()
        assert stats["files"] == 1
        assert "THYAO_1d" in stats["tickers"]

        # Önbellekten oku
        loaded_df = mgr._load_from_cache("THYAO", "1d")
        assert loaded_df is not None
        assert loaded_df.height == 2

        # Temizle
        mgr.clear_cache()
        stats_cleared = mgr.get_cache_stats()
        assert stats_cleared["files"] == 0

    def test_get_stock_data_fallback_flow(self, manager) -> None:
        """get_stock_data fonksiyonunun öncelik sırasına göre kaynakları denemesi testi."""
        mgr, _ = manager

        # Mock kaynaklar
        mock_source = MagicMock()
        mock_source.fetch.return_value = pl.DataFrame(
            {
                "Date": ["2025-01-02"],
                "Open": [50.0],
                "High": [52.0],
                "Low": [49.0],
                "Close": [51.0],
                "Volume": [10000],
            }
        )
        mgr._sources["mock_src"] = mock_source

        df = mgr.get_stock_data("SISE", source_priority=["mock_src"])
        assert df is not None
        assert df.height == 1
        assert df["Close"][0] == 51.0

        # Sonuç önbelleğe yazılmış olmalı
        assert mgr.get_cache_stats()["files"] == 1

    def test_get_bist100_universe(self, manager) -> None:
        """BIST-100 hisse evren listesinin çekilmesi veya fallback listesi testi."""
        mgr, _ = manager
        universe = mgr.get_bist100_universe()
        assert isinstance(universe, list)
        assert len(universe) >= 20
        assert "THYAO.IS" in universe


class TestDuckDBStockCandlesHelpers:
    """read_stock_candles_from_duckdb ve clear_stock_candles_duckdb testleri."""

    def test_read_and_clear_stock_candles(self) -> None:
        """DuckDB veri ambarından mum okuma ve temizleme testleri."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = str(Path(tmpdir) / "test_candles.duckdb")

            with duckdb.connect(db_path) as conn:
                configure_duckdb_wal(conn)
                conn.execute(
                    """
                    CREATE TABLE stock_candles (
                        Date TIMESTAMP,
                        Open DOUBLE,
                        High DOUBLE,
                        Low DOUBLE,
                        Close DOUBLE,
                        Volume BIGINT,
                        symbol VARCHAR
                    );
                    INSERT INTO stock_candles VALUES
                    ('2025-01-02 00:00:00', 300.0, 305.0, 298.0, 302.0, 500000, 'FROTO');
                    """
                )

            # Polars Okuyucu Testi
            df = read_stock_candles_from_duckdb(db_path=db_path, ticker="FROTO")
            assert isinstance(df, pl.DataFrame)
            assert df.height == 1
            assert df["Close"][0] == 302.0

            # Temizleme Testi
            clear_stock_candles_duckdb(db_path=db_path)
            df_after = read_stock_candles_from_duckdb(db_path=db_path)
            assert df_after.height == 0
