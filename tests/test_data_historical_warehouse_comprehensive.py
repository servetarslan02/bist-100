"""ALPHA BIST — Tarihsel Veri Ambarı (DuckDB & Polars) Kapsamlı Test Paketi.

services/data/historical_warehouse.py modülünün 30 yıllık DuckDB veri ambarı motoru,
önbellek geçerlilik kontrolleri (is_cached), mock veri kaydı ve yükleme akışları (load_30y_data),
Polars benchmark ve hisse mum sorgulayıcıları ve ambar temizleme işlevlerini test eder.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import duckdb
import orjson
import pandas as pd
import polars as pl
import pytest

from services.data.historical_warehouse import (
    BENCHMARK_TICKER,
    BIST_ALL_KEY_TICKERS,
    DEFAULT_CHECKPOINT_SIZE,
    DEFAULT_WAL_SIZE,
    HistoricalDataWarehouse,
    _yf_to_polars,
    clear_warehouse_duckdb,
    configure_duckdb_wal,
    read_warehouse_benchmark_from_duckdb,
    read_warehouse_stocks_from_duckdb,
    to_orjson_bytes,
)


class TestWarehouseBasics:
    """Sabitler, serileştirme ve pandas -> Polars dönüştürücü testleri."""

    def test_constants(self) -> None:
        """Sabitlerin ve temel liste tanımlarının doğruluğunu test eder."""
        assert BENCHMARK_TICKER == "XU100.IS"
        assert DEFAULT_CHECKPOINT_SIZE == "4MB"
        assert DEFAULT_WAL_SIZE == "2MB"
        assert len(BIST_ALL_KEY_TICKERS) >= 30
        assert "THYAO.IS" in BIST_ALL_KEY_TICKERS

    def test_configure_duckdb_wal(self) -> None:
        """DuckDB bağlantısına WAL pragmalarının başarıyla uygulandığını doğrular."""
        conn = duckdb.connect(":memory:")
        configure_duckdb_wal(conn)
        conn.close()

    def test_to_orjson_bytes_helper(self) -> None:
        """to_orjson_bytes serileştirme yardımcısını test eder."""
        payload = {"status": "ok", "count": 100}
        raw = to_orjson_bytes(payload)
        assert isinstance(raw, bytes)
        assert orjson.loads(raw) == payload

    def test_yf_to_polars_conversion(self) -> None:
        """_yf_to_polars yardımcı fonksiyonunun pandas MultiIndex ve normal indeks dönüşümünü test eder."""
        # Boş girdi
        df_empty = _yf_to_polars(None)
        assert isinstance(df_empty, pl.DataFrame)
        assert df_empty.height == 0

        # Normal pandas DataFrame
        pdf = pd.DataFrame(
            {
                "Open": [10.0, 11.0],
                "Close": [10.5, 11.5],
            },
            index=pd.date_range("2025-01-01", periods=2),
        )
        pldf = _yf_to_polars(pdf)
        assert isinstance(pldf, pl.DataFrame)
        assert pldf.height == 2
        assert "Close" in pldf.columns


@pytest.fixture
def test_warehouse():
    """Geçici test ambarı veritabanı oluşturan fixture."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = str(Path(tmpdir) / "test_warehouse.db")
        wh = HistoricalDataWarehouse(db_file=db_path)

        # Test için tabloları ve sembolleri oluştur
        with duckdb.connect(db_path) as conn:
            configure_duckdb_wal(conn)
            conn.execute(
                """
                CREATE TABLE benchmark_xu100 (
                    Date TIMESTAMP,
                    Open DOUBLE,
                    High DOUBLE,
                    Low DOUBLE,
                    Close DOUBLE,
                    Volume BIGINT
                );
                """
            )
            conn.execute(
                """
                INSERT INTO benchmark_xu100 VALUES
                ('2025-01-02 00:00:00', 9500.0, 9600.0, 9450.0, 9580.0, 1000000),
                ('2025-01-03 00:00:00', 9580.0, 9700.0, 9550.0, 9650.0, 1200000);
                """
            )
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
                """
            )
            conn.execute(
                """
                INSERT INTO stock_candles VALUES
                ('2025-01-02 00:00:00', 250.0, 255.0, 248.0, 253.0, 500000, 'THYAO'),
                ('2025-01-03 00:00:00', 253.0, 260.0, 252.0, 258.0, 600000, 'THYAO'),
                ('2025-01-02 00:00:00', 80.0, 82.0, 79.0, 81.0, 300000, 'GARAN'),
                ('2025-01-03 00:00:00', 81.0, 83.0, 80.5, 82.5, 400000, 'GARAN');
                """
            )

        yield wh, db_path


class TestWarehouseOperations:
    """HistoricalDataWarehouse sınıfı DuckDB ve Polars veri işleme testleri."""

    def test_warehouse_initialization_and_metadata(self, test_warehouse) -> None:
        """Ambar başlatma, is_cached, to_dict ve to_orjson_bytes testleri."""
        wh, db_path = test_warehouse
        assert "HistoricalDataWarehouse" in repr(wh)
        assert wh.is_cached() is True

        info = wh.to_dict()
        assert info["db_file"] == db_path
        assert info["is_cached"] is True
        assert info["benchmark_ticker"] == "XU100.IS"
        assert info["total_key_tickers"] >= 30

        raw_bytes = wh.to_orjson_bytes()
        assert isinstance(raw_bytes, bytes)

    def test_load_30y_data(self, test_warehouse) -> None:
        """Ambardaki verilerin Polars sözlüğü ve endeks tablosu olarak yüklenmesi."""
        wh, _ = test_warehouse
        bm_df, stock_dict = wh.load_30y_data()

        assert isinstance(bm_df, pl.DataFrame)
        assert bm_df.height == 2
        assert "Close" in bm_df.columns

        assert "THYAO.IS" in stock_dict
        assert "GARAN.IS" in stock_dict
        assert stock_dict["THYAO.IS"].height == 2
        assert stock_dict["GARAN.IS"].height == 2
        assert "Close" in stock_dict["THYAO.IS"].columns


class TestWarehouseReadersAndClear:
    """read_warehouse_benchmark_from_duckdb, read_warehouse_stocks_from_duckdb ve clear fonksiyonları."""

    def test_readers_and_clear_warehouse(self, test_warehouse) -> None:
        """Bağımsız okuyucular ve clear fonksiyonunu test eder."""
        wh, db_path = test_warehouse

        # Benchmark Okuyucu
        df_bm = read_warehouse_benchmark_from_duckdb(db_path=db_path)
        assert df_bm.height == 2

        # Hisse Mumları Okuyucu (Tüm hisseler)
        df_all_stocks = read_warehouse_stocks_from_duckdb(db_path=db_path)
        assert df_all_stocks.height == 4

        # Filtreli Hisse Okuyucu
        df_thyao = read_warehouse_stocks_from_duckdb(db_path=db_path, symbol="THYAO", limit=1)
        assert df_thyao.height == 1
        assert df_thyao["symbol"][0] == "THYAO"

        # Temizleme Fonksiyonu
        clear_warehouse_duckdb(db_path=db_path)
        df_bm_after = read_warehouse_benchmark_from_duckdb(db_path=db_path)
        assert df_bm_after.height == 0

        df_stocks_after = read_warehouse_stocks_from_duckdb(db_path=db_path)
        assert df_stocks_after.height == 0
