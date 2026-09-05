"""ALPHA BIST — Gross Settlement Monitor Birim Testleri."""

from __future__ import annotations

from pathlib import Path

import polars as pl

from services.core.gross_settlement import (
    GrossSettlementMonitor,
    GrossSettlementStatus,
    gross_settlement_monitor,
)


def test_basic_gross_settlement_checks() -> None:
    """Temel brüt takas ekleme, kaldırma ve sorgulama."""
    monitor = GrossSettlementMonitor()
    monitor.set_gross_tickers(["THYAO", "SASA"])

    assert monitor.is_short_sell_blocked("thyao") is True
    assert monitor.is_margin_blocked("SASA") is True
    assert monitor.is_short_sell_blocked("GARAN") is False

    status = monitor.check_gross_settlement("THYAO")
    assert isinstance(status, GrossSettlementStatus)
    assert status.is_gross is True
    assert status.is_active is True
    assert "açığa satış yasak" in status.impact

    # Ticker normalizasyonu ve kaldırma
    monitor.remove_gross_ticker("  thyao  ")
    assert monitor.is_short_sell_blocked("THYAO") is False


def test_point_in_time_date_awareness() -> None:
    """Tarih aralıklı (Point-In-Time) tedbir geçerlilik denetimi."""
    monitor = GrossSettlementMonitor()
    monitor.set_gross_ticker_detail(
        "HEKTS",
        {
            "start_date": "2026-06-01",
            "end_date": "2026-07-01",
            "reason": "VBTS Tedbiri",
            "day_trade_restricted": True,
        },
    )

    # Tedbir öncesi: Serbest
    assert monitor.is_short_sell_blocked("HEKTS", current_date="2026-05-31") is False

    # Tedbir süresince: Engelli
    assert monitor.is_short_sell_blocked("HEKTS", current_date="2026-06-15") is True
    assert monitor.is_day_trade_restricted("HEKTS", current_date="2026-06-15") is True

    # Tedbir sonrası: Süresi dolmuş, serbest
    status_after = monitor.check_gross_settlement("HEKTS", current_date="2026-07-02")
    assert status_after.is_active is False
    assert status_after.effect == "EXPIRED"
    assert monitor.is_short_sell_blocked("HEKTS", current_date="2026-07-02") is False


def test_get_all_and_filter() -> None:
    """Toplu filtreleme ve aktif hisse listesi alma."""
    monitor = GrossSettlementMonitor()
    monitor.set_gross_tickers(["ASELS", "KCHOL"])
    monitor.set_gross_ticker_detail(
        "EREGL",
        {"start_date": "2026-01-01", "end_date": "2026-02-01"},
    )

    # Tarihsiz sorgu: Hepsini döner
    all_gross = monitor.get_all_gross()
    assert "ASELS" in all_gross
    assert "EREGL" in all_gross

    # 2026-03-01 itibarıyla EREGL süresi doldu
    active_in_march = monitor.get_all_gross(current_date="2026-03-01")
    assert "EREGL" not in active_in_march
    assert "ASELS" in active_in_march

    # Liste filtreleme
    filtered = monitor.filter_gross_tickers(["ASELS", "GARAN", "EREGL"], current_date="2026-03-01")
    assert filtered == ["ASELS"]


def test_polars_vectorized_enrichment() -> None:
    """Polars DataFrame üzerinde vektörize 'is_gross_settlement' kolon ekleme."""
    monitor = GrossSettlementMonitor()
    monitor.set_gross_tickers(["THYAO", "BIMAS"])

    df = pl.DataFrame(
        {
            "ticker": ["thyao", "GARAN", "bimas", "AKBNK"],
            "date": ["2026-05-01", "2026-05-01", "2026-05-01", "2026-05-01"],
        }
    )

    # Tarihsiz hızlı kolon ekleme
    res_df = monitor.check_polars(df, ticker_col="ticker")
    assert res_df["is_gross_settlement"].to_list() == [True, False, True, False]

    # Tedbir tablosunu Polars olarak dışa aktar
    export_df = monitor.export_to_polars()
    assert len(export_df) == 2
    assert "ticker" in export_df.columns
    assert "is_gross" in export_df.columns


def test_duckdb_audit_export(tmp_path: Path) -> None:
    """DuckDB denetim izi tablosuna aktarım."""
    monitor = GrossSettlementMonitor()
    monitor.set_gross_ticker_detail(
        "SISE",
        {"start_date": "2026-01-01", "end_date": "2026-02-01", "reason": "SPK Kararı"},
    )
    monitor.add_gross_ticker("PETKM")

    db_file = str(tmp_path / "test_gross.duckdb")
    saved = monitor.export_to_duckdb(db_file)
    assert saved == 2
    assert Path(db_file).exists()
