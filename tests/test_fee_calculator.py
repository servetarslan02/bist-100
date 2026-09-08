"""ALPHA BIST — Fee Calculator ve Başa Baş (Break-Even) Analizi Testleri."""

from __future__ import annotations

from pathlib import Path

import polars as pl
import pytest

from services.core.fee_calculator import (
    BreakEvenAnalysis,
    FeeCalculator,
    fee_calculator,
)


def test_standard_equity_calculation() -> None:
    """BIST Pay Piyasası standart komisyon ve masraf hesaplaması."""
    calc = FeeCalculator(
        broker_rate=0.0003,
        bist_fee_rate=0.000056,
        mkk_fee_rate=0.0000109,
        bsmv_rate=0.05,
        min_commission=1.0,
    )
    breakdown = calc.calculate(100_000.0, side="BUY")

    assert breakdown.amount == 100_000.0
    assert breakdown.broker_fee == 30.0
    assert breakdown.bist_fee == 5.60
    assert breakdown.mkk_fee == 1.09
    assert breakdown.bsmv == 1.50
    assert breakdown.total == 38.19
    assert breakdown.effective_rate == round((38.19 / 100_000.0) * 100.0, 6)
    assert breakdown.side == "BUY"
    assert breakdown.net_amount == 100_038.19

    # orjson bayt serileştirmesi
    raw_bytes = breakdown.to_orjson_bytes()
    assert isinstance(raw_bytes, bytes)
    assert b"100038.19" in raw_bytes


def test_sell_net_cash_flow() -> None:
    """Satış işleminde masrafların düşülmesiyle net tahsilat hesabı."""
    breakdown = fee_calculator.calculate(50_000.0, side="SELL")
    assert breakdown.side == "SELL"
    assert breakdown.net_amount == round(breakdown.amount - breakdown.total, 4)
    assert breakdown.net_amount < breakdown.amount


def test_viop_calculation() -> None:
    """VİOP sözleşmelerinde MKK payı sıfır ve VİOP borsa payı kontrolü."""
    breakdown = fee_calculator.calculate(100_000.0, side="BUY", instrument_type="viop")
    assert breakdown.instrument_type == "viop"
    assert breakdown.mkk_fee == 0.0
    assert breakdown.bist_fee == 4.0  # 100_000 * 0.00004
    assert breakdown.broker_fee == 30.0
    assert breakdown.bsmv == 1.50
    assert breakdown.total == 35.50


def test_min_commission_guard() -> None:
    """Küçük tutarlı işlemlerde taban komisyon (1.00 TL) koruması."""
    breakdown = fee_calculator.calculate(100.0)
    # 100 * 0.0003 = 0.03 TL -> min_commission = 1.00 TL devreye girmeli
    assert breakdown.broker_fee == 1.0
    assert breakdown.bsmv == 0.05  # 1.0 * 0.05


def test_edge_cases_and_fail_closed() -> None:
    """Sıfır, negatif ve NaN/Inf girdilerde güvenli fail-closed davranışı."""
    for bad_input in [0.0, -500.0, float("nan"), float("inf"), float("-inf")]:
        fb = fee_calculator.calculate(bad_input)
        assert fb.amount == 0.0
        assert fb.total == 0.0
        assert fb.net_amount == 0.0


def test_break_even_analysis() -> None:
    """Alış sonrası kâr/zararsız başa baş fiyat ve BIST tick boyutu uyumu."""
    entry_price = 100.0
    quantity = 500.0
    analysis = fee_calculator.calculate_break_even(
        entry_price=entry_price,
        quantity=quantity,
        instrument_type="equity",
        round_to_tick=True,
    )

    assert isinstance(analysis, BreakEvenAnalysis)
    assert analysis.entry_price == entry_price
    assert analysis.quantity == quantity
    assert analysis.break_even_price > entry_price
    # Kademe uyumlu satış fiyatı teorik fiyattan küçük olamaz (zarara düşmemek için)
    assert analysis.tick_aligned_price >= analysis.break_even_price
    assert analysis.break_even_return_pct > 0.0

    # Geçersiz girdi kontrolü
    with pytest.raises(ValueError):
        fee_calculator.calculate_break_even(entry_price=-10.0, quantity=100.0)
    with pytest.raises(ValueError):
        fee_calculator.calculate_break_even(entry_price=10.0, quantity=0.0)


def test_tiered_commission_rates() -> None:
    """Hacim baremlerine göre dinamik komisyon oranları."""
    calc = FeeCalculator(
        broker_rate=0.0003,
        tiered_rates=[(100_000.0, 0.0003), (500_000.0, 0.00025), (float("inf"), 0.0002)],
    )
    # 50.000 TL -> %0.03
    fb1 = calc.calculate(50_000.0)
    assert fb1.broker_fee == 15.0

    # 300.000 TL -> %0.025
    fb2 = calc.calculate(300_000.0)
    assert fb2.broker_fee == 75.0

    # 1.000.000 TL -> %0.02
    fb3 = calc.calculate(1_000_000.0)
    assert fb3.broker_fee == 200.0


def test_polars_vectorized_calculation() -> None:
    """Polars DataFrame üzerinde sıfır kopyalı toplu hesaplama."""
    df = pl.DataFrame(
        {
            "amount": [100.0, 50_000.0, 200_000.0],
            "side": ["BUY", "SELL", "BUY"],
        }
    )
    result_df = fee_calculator.calculate_polars(df, amount_col="amount", side_col="side")

    assert len(result_df) == 3
    assert "broker_fee" in result_df.columns
    assert "bist_fee" in result_df.columns
    assert "mkk_fee" in result_df.columns
    assert "bsmv" in result_df.columns
    assert "total_fee" in result_df.columns
    assert "net_amount" in result_df.columns

    # İlk satır min komisyon olmalı
    assert result_df["broker_fee"][0] == 1.0
    # İkinci satır satış olduğundan net_amount < amount
    assert result_df["net_amount"][1] < result_df["amount"][1]
    # Üçüncü satır alış olduğundan net_amount > amount
    assert result_df["net_amount"][2] > result_df["amount"][2]


def test_duckdb_audit_export(tmp_path: Path) -> None:
    """DuckDB denetim izi tablosuna toplu kayıt ve doğrulama."""
    db_file = str(tmp_path / "test_fee_audit.duckdb")
    fb1 = fee_calculator.calculate(25_000.0, side="BUY")
    fb2 = fee_calculator.calculate(75_000.0, side="SELL")

    saved_count = fee_calculator.export_to_duckdb([fb1, fb2], db_path=db_file)
    assert saved_count == 2
    assert Path(db_file).exists()
