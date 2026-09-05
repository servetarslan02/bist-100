"""ALPHA BIST — Halt Monitor Birim Testleri."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import polars as pl

from services.core.halt_monitor import (
    ACTION_CANCEL_ORDERS,
    ACTION_WAIT,
    HALT_TYPE_CIRCUIT_BREAKER,
    HALT_TYPE_KAP,
    HaltMonitor,
    HaltStatus,
    halt_monitor,
)


def test_basic_add_check_remove() -> None:
    """Temel durdurma ekleme, sorgulama ve kaldırma."""
    monitor = HaltMonitor()
    # THYAO durdurma ekle
    status = monitor.add_halt(
        ticker="thyao",
        reason="KAP Özel Durum Açıklaması",
        halt_type=HALT_TYPE_KAP,
        action=ACTION_CANCEL_ORDERS,
    )
    assert isinstance(status, HaltStatus)
    assert status.ticker == "THYAO"
    assert status.halted is True
    assert status.action == ACTION_CANCEL_ORDERS

    # Sorgulama
    assert monitor.is_halted("THYAO") is True
    assert monitor.is_halted("  thyao  ") is True
    assert monitor.is_halted("GARAN") is False

    # Kaldırma
    removed = monitor.remove_halt("thyao")
    assert removed is True
    assert monitor.is_halted("THYAO") is False


def test_point_in_time_auto_expiration() -> None:
    """Beklenen yeniden başlama zamanı (Point-In-Time) aşımı kontrolü."""
    monitor = HaltMonitor()
    resume_time = datetime(2026, 6, 15, 14, 0, 0, tzinfo=UTC)

    monitor.add_halt(
        ticker="EREGL",
        reason="Devre Kesici Tetiklendi",
        halt_type=HALT_TYPE_CIRCUIT_BREAKER,
        expected_resume=resume_time,
        action=ACTION_WAIT,
    )

    # 13:55 (Süre dolmadı -> kilitli)
    before_time = datetime(2026, 6, 15, 13, 55, 0, tzinfo=UTC)
    assert monitor.is_halted("EREGL", current_time=before_time) is True
    st_before = monitor.check_halt("EREGL", current_time=before_time)
    assert st_before.halted is True
    assert st_before.is_active is True

    # 14:05 (Süre doldu -> otomatik serbest)
    after_time = datetime(2026, 6, 15, 14, 5, 0, tzinfo=UTC)
    assert monitor.is_halted("EREGL", current_time=after_time) is False
    st_after = monitor.check_halt("EREGL", current_time=after_time)
    assert st_after.halted is False
    assert st_after.is_active is False
    assert "süresi doldu" in st_after.reason


def test_get_and_filter_halted_tickers() -> None:
    """Durdurulan hisseleri listeleme ve toplu filtreleme."""
    monitor = HaltMonitor()
    monitor.add_halt("SASA", "KAP", halt_type=HALT_TYPE_KAP)
    monitor.add_halt("HEKTS", "KAP", halt_type=HALT_TYPE_KAP)

    halted_list = monitor.get_halted_tickers()
    assert "HEKTS" in halted_list
    assert "SASA" in halted_list

    filtered = monitor.filter_halted_tickers(["SASA", "GARAN", "THYAO", "HEKTS"])
    assert filtered == ["SASA", "HEKTS"]


def test_polars_enrichment_and_export() -> None:
    """Polars DataFrame üzerinde vektörize tarama ve dışa aktarım."""
    monitor = HaltMonitor()
    monitor.add_halt("BIMAS", "Olağanüstü Genel Kurul")

    df = pl.DataFrame(
        {
            "ticker": ["bimas", "akbnk", "SISE"],
        }
    )

    res_df = monitor.check_polars(df, ticker_col="ticker")
    assert res_df["is_halted"].to_list() == [True, False, False]

    export_df = monitor.export_to_polars()
    assert len(export_df) >= 1
    assert "BIMAS" in export_df["ticker"].to_list()


def test_duckdb_audit_export(tmp_path: Path) -> None:
    """DuckDB denetim izi tablosuna aktarım."""
    monitor = HaltMonitor()
    monitor.add_halt("TUPRS", "Genel Kurul Kararı", action=ACTION_WAIT)

    db_path = str(tmp_path / "test_halt.duckdb")
    saved = monitor.export_to_duckdb(db_path)
    assert saved >= 1
    assert Path(db_path).exists()


def test_orjson_bytes_serialization() -> None:
    """HaltStatus ikili serileştirme testi."""
    st = HaltStatus(
        halted=True,
        ticker="FROTO",
        reason="KAP Açıklaması",
        action=ACTION_CANCEL_ORDERS,
    )
    raw = st.to_orjson_bytes()
    assert isinstance(raw, bytes)
    assert b"FROTO" in raw
    assert b"CANCEL_ORDERS" in raw
