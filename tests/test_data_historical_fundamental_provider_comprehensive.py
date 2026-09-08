"""ALPHA BIST — Tarihsel Temel Analiz Sağlayıcı Motoru Kapsamlı Test Paketi.

services/data/historical_fundamental_provider.py modülünün önbellekleme,
metrik haritalama, yayın tarihi kestirimi (PIT), Polars DataFrame aktarımı,
DuckDB denetim kayıtları ve temizleme fonksiyonlarını test eder.
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

from services.data.historical_contracts import FundamentalSnapshot
from services.data.historical_fundamental_provider import (
    DEFAULT_CACHE_TTL_SECONDS,
    DEFAULT_FALLBACK_DAYS_OFFSET,
    DEFAULT_MAX_PERIODS,
    HistoricalFundamentalProvider,
    clear_fundamental_audit_duckdb,
    configure_duckdb_wal,
    export_fundamental_to_duckdb,
    export_snapshots_to_polars,
    read_fundamental_audit_from_duckdb,
    to_orjson_bytes,
)


class TestFundamentalProviderBasics:
    """Sabitler, serileştirme ve DuckDB WAL testleri."""

    def test_constants(self) -> None:
        """Sabitlerin doğruluğunu kontrol eder."""
        assert DEFAULT_CACHE_TTL_SECONDS == 3600
        assert DEFAULT_FALLBACK_DAYS_OFFSET == 60
        assert DEFAULT_MAX_PERIODS == 8

    def test_configure_duckdb_wal(self) -> None:
        """DuckDB WAL pragma çalıştırmasını test eder."""
        conn = duckdb.connect(":memory:")
        configure_duckdb_wal(conn)
        conn.close()

    def test_to_orjson_bytes_helper(self) -> None:
        """to_orjson_bytes serileştirme doğrulaması."""
        snap = FundamentalSnapshot(
            ticker="THYAO",
            period_end="2025-06-30",
            available_at="2025-08-15",
            values={"fk": 5.2},
        )
        res = to_orjson_bytes(snap)
        assert isinstance(res, bytes)
        decoded = orjson.loads(res)
        assert decoded["ticker"] == "THYAO"


class TestFundamentalProviderLogic:
    """HistoricalFundamentalProvider sınıfı metot ve mantık testleri."""

    def test_provider_initialization_and_repr(self) -> None:
        """Başlatma ve durum metotları testi."""
        provider = HistoricalFundamentalProvider(cache_ttl_seconds=1800)
        assert "HistoricalFundamentalProvider" in repr(provider)

        status_dict = provider.to_dict()
        assert status_dict["cache_ttl_seconds"] == 1800
        assert status_dict["cached_count"] == 0

        raw_bytes = provider.to_orjson_bytes()
        assert isinstance(raw_bytes, bytes)

    def test_map_metrics(self) -> None:
        """yfinance ham bilanço anahtarlarının standart alanlara ve marjlara dönüştürülmesi."""
        provider = HistoricalFundamentalProvider()
        raw_values = {
            "Total Revenue": 1000000.0,
            "Net Income": 200000.0,
            "Operating Income": 250000.0,
            "Gross Profit": 400000.0,
            "Free Cash Flow": 150000.0,
            "EBITDA": 300000.0,
            "Basic Average Shares": 50000.0,
            "Diluted EPS": 4.0,
        }
        mapped = provider._map_metrics(raw_values, "THYAO")

        assert mapped["revenue"] == 1000000.0
        assert mapped["net_income"] == 200000.0
        assert mapped["operating_income"] == 250000.0
        assert mapped["gross_profit"] == 400000.0
        assert mapped["free_cash_flow"] == 150000.0
        assert mapped["ebitda"] == 300000.0
        assert mapped["eps"] == 4.0
        # Türetilmiş marjlar
        assert pytest.approx(mapped["profit_margin"], 0.001) == 0.20
        assert pytest.approx(mapped["gross_margin"], 0.001) == 0.40
        assert pytest.approx(mapped["operating_margin"], 0.001) == 0.25
        assert pytest.approx(mapped["fcf_margin"], 0.001) == 0.15

    def test_find_publication_date(self) -> None:
        """Kamuya açıklanma tarihi bulucu ve 60 günlük fallback öteleme testi."""
        provider = HistoricalFundamentalProvider()
        earnings_dates = {
            "2024-11-10": "2024-11-10",
            "2025-05-15": "2025-05-15",
        }

        # Mevcut aday varsa en yakın olanı seçmeli
        res = provider._find_publication_date("2024-09-30", earnings_dates)
        assert res == "2024-11-10"

        # Aday yoksa 60 gün ileri ötelemeli (2025-06-30 + 60 gün -> 2025-08-29)
        res_fallback = provider._find_publication_date("2025-06-30", earnings_dates)
        assert res_fallback == "2025-08-29"

    def test_get_historical_snapshots_with_mocked_yfinance(self) -> None:
        """yfinance API çağrısının taklit edilerek snapshot listesi üretilmesi ve önbellek testi."""
        provider = HistoricalFundamentalProvider(cache_ttl_seconds=3600)

        mock_qf = pd.DataFrame(
            {
                "2025-03-31": [500000.0, 100000.0],
                "2024-12-31": [400000.0, 80000.0],
            },
            index=["Total Revenue", "Net Income"],
        )
        mock_bs = pd.DataFrame(
            {
                "2025-03-31": [2000000.0],
                "2024-12-31": [1800000.0],
            },
            index=["Total Assets"],
        )

        with patch("yfinance.Ticker") as mock_ticker_cls:
            mock_inst = MagicMock()
            mock_inst.quarterly_financials = mock_qf
            mock_inst.quarterly_balance_sheet = mock_bs
            mock_inst.earnings_dates = None
            mock_ticker_cls.return_value = mock_inst

            snapshots = provider.fetch_historical_fundamentals("GARAN", max_periods=2)
            assert len(snapshots) == 2
            assert snapshots[0].ticker == "GARAN"
            assert snapshots[0].period_end == "2025-03-31"
            assert snapshots[0].values["revenue"] == 500000.0

            # İkinci çağrıda önbellekten gelmeli
            snapshots_cached = provider.fetch_historical_fundamentals("GARAN")
            assert len(snapshots_cached) == 2

            # Temizleme
            provider.clear_cache()
            assert provider.to_dict()["cached_count"] == 0


class TestFundamentalExportAndDuckDB:
    """Polars ve DuckDB denetim fonksiyonları testleri."""

    def test_export_snapshots_to_polars(self) -> None:
        """Temel analiz snapshot'larının Polars DataFrame'e aktarılması."""
        snapshots = [
            FundamentalSnapshot(
                ticker="EREGL",
                period_end="2025-03-31",
                available_at="2025-05-10",
                values={"revenue": 50000.0, "net_income": 10000.0},
            ),
            FundamentalSnapshot(
                ticker="EREGL",
                period_end="2024-12-31",
                available_at="2025-03-01",
                values={"revenue": 45000.0, "net_income": 8000.0},
            ),
        ]
        df = export_snapshots_to_polars(snapshots)
        assert isinstance(df, pl.DataFrame)
        assert df.height == 2
        assert "val_revenue" in df.columns
        assert df["val_revenue"][0] == 50000.0

        # Boş liste kontrolü
        df_empty = export_snapshots_to_polars([])
        assert df_empty.height == 0

    def test_export_and_read_fundamental_audit(self) -> None:
        """DuckDB fundamental audit tablosuna yazma, okuma ve temizleme akışı."""
        with tempfile.TemporaryDirectory() as tmpdir:
            test_db = str(Path(tmpdir) / "test_fund_audit.duckdb")

            snap = FundamentalSnapshot(
                ticker="AKBNK",
                period_end="2025-03-31",
                available_at="2025-05-02",
                values={"revenue": 120000.0},
            )

            res = export_fundamental_to_duckdb(snap, db_path=test_db)
            assert res == 1

            df = read_fundamental_audit_from_duckdb(db_path=test_db, ticker="AKBNK")
            assert isinstance(df, pl.DataFrame)
            assert df.height == 1
            assert df["ticker"][0] == "AKBNK"
            assert df["period_end"][0] == "2025-03-31"

            clear_fundamental_audit_duckdb(db_path=test_db)
            df_after = read_fundamental_audit_from_duckdb(db_path=test_db)
            assert df_after.height == 0
