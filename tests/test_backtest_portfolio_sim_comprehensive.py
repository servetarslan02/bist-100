"""
ALPHA BIST — Portfolio Simulator v3.0 Comprehensive Test Suite

PortfolioSimulatorV3, Trade, Position, EquitySnapshot, AuditEntry,
BISTCommissionModel sınıflarının alım-satım yaşam döngüsü, nakit değişmezliği (invariants),
oversell engelleme, Polars DataFrame dönüşümleri, performans metrikleri (Sharpe, Calmar, VaR)
ve thread güvenliğini doğrular.
"""

from __future__ import annotations

import concurrent.futures
from datetime import date

import polars as pl
import pytest

from services.backtest.portfolio_sim import (
    BISTCommissionModel,
    EquitySnapshot,
    PortfolioSimulatorV3,
    Position,
    Trade,
    _compute_days_between,
    _parse_date_to_str,
)


def test_date_utils() -> None:
    """Tarih dönüşüm ve gün farkı yardımcı fonksiyonları testi."""
    d = date(2025, 5, 10)
    assert _parse_date_to_str(d) == "2025-05-10"
    assert _parse_date_to_str("2025-05-10T12:00:00") == "2025-05-10"
    assert _compute_days_between("2025-05-01", "2025-05-10") == 9

    with pytest.raises(TypeError):
        _parse_date_to_str(12345)


def test_bist_commission_model() -> None:
    """BIST komisyon oranları ve asgari komisyon kuralını doğrular."""
    # Sıfır veya negatif tutar
    assert BISTCommissionModel.compute(0.0) == 0.0
    assert BISTCommissionModel.compute(-50.0) == 0.0

    # Düşük tutarda asgari 1 TL komisyon kuralı
    assert BISTCommissionModel.compute(10.0) == 1.0

    # Yüksek tutarda formül hesaplaması
    # 100_000 * (0.0003 + 0.000056) = 35.6 TL base; + %5 BSMV = 37.38 TL
    comm = BISTCommissionModel.compute(100_000.0)
    assert 37.0 <= comm <= 38.0
    assert "BISTCommissionModel" in repr(BISTCommissionModel())


def test_position_and_trade_dataclasses() -> None:
    """Position ve Trade sınıflarının property, to_dict ve repr doğrulaması."""
    pos = Position(
        ticker="THYAO",
        quantity=100,
        entry_price=200.0,
        entry_date="2025-01-01",
        cost_basis=20_100.0,
        current_price=220.0,
    )
    assert pos.market_value == 22_000.0
    assert pos.unrealized_pnl == 1_900.0
    assert pos.unrealized_pnl_pct > 0
    assert pos.to_dict()["ticker"] == "THYAO"
    assert "THYAO" in repr(pos)

    trade = Trade(
        trade_id=1,
        ticker="ASELS",
        side="BUY",
        date="2025-01-02",
        quantity=50,
        price=60.0,
        commission=2.5,
        slippage=0.5,
    )
    assert trade.to_dict()["side"] == "BUY"
    assert "ASELS" in repr(trade)


def test_portfolio_simulator_lifecycle_and_invariants() -> None:
    """Tam alım, satım, kâr realizasyonu ve değişmezlik (invariant) kontrolü."""
    sim = PortfolioSimulatorV3(initial_capital=100_000.0, max_position_pct=0.20)

    # 1. Alım işlemi
    t_buy = sim.execute_buy(ticker="THYAO", price=200.0, date="2025-01-01", quantity=50)
    assert t_buy is not None
    assert t_buy.side == "BUY"
    assert sim.has_position("THYAO") is True
    assert sim.get_position_count() == 1

    # 2. Güncelleme
    snap = sim.update_equity(prices={"THYAO": 220.0}, date="2025-01-02", benchmark_price=10_000.0)
    assert isinstance(snap, EquitySnapshot)
    assert snap.equity > 100_000.0
    assert "pozisyonlar=1/20" in repr(sim)

    # 3. Satış işlemi (Kârla kapanış)
    t_sell = sim.execute_sell(ticker="THYAO", price=220.0, date="2025-01-03")
    assert t_sell is not None
    assert t_sell.side == "SELL"
    assert t_sell.pnl > 0
    assert sim.has_position("THYAO") is False

    # Satış sonrası equity snapshot güncellemesi (muhasebe eşlemesi için)
    sim.update_equity(prices={}, date="2025-01-03")

    # 4. Değişmezlik kontrolü
    is_valid, errors = sim.check_invariants()
    assert is_valid is True
    assert len(errors) == 0

    # 5. Metrik hesaplama
    metrics = sim.compute_metrics()
    assert metrics["total_trades"] == 2
    assert metrics["sell_trades"] == 1
    assert metrics["win_rate_pct"] == 100.0
    assert metrics["final_equity"] > 100_000.0


def test_portfolio_simulator_oversell_and_limits() -> None:
    """Elde olmayan hissenin satılamaması ve yetersiz nakit kontrolleri."""
    sim = PortfolioSimulatorV3(initial_capital=1_000.0, max_positions=1)

    # Elde olmayan hisseyi satma
    assert sim.execute_sell("ASELS", price=50.0, date="2025-01-01") is None

    # Sermayeyi aşan alım denemesi
    t_buy = sim.execute_buy("THYAO", price=500.0, date="2025-01-01", quantity=100)
    # 500 * 100 = 50,000 TL > 1,000 TL nakit -> Nakde göre küçültülür veya reddedilir
    if t_buy is not None:
        assert t_buy.quantity < 10

    # Zaten portföyde olan hisseyi tekrar almayı reddetme
    sim.execute_buy("GARAN", price=10.0, date="2025-01-02", quantity=10)
    assert sim.execute_buy("GARAN", price=10.0, date="2025-01-03", quantity=10) is None


def test_portfolio_simulator_polars_dataframes() -> None:
    """get_trades_df ve get_equity_curve_df Polars çıktılarını doğrular."""
    sim = PortfolioSimulatorV3(initial_capital=50_000.0)
    sim.execute_buy("BIMAS", price=100.0, date="2025-01-01", quantity=10)
    sim.update_equity({"BIMAS": 105.0}, date="2025-01-02")

    trades_df = sim.get_trades_df()
    assert isinstance(trades_df, pl.DataFrame)
    assert trades_df.height == 1
    assert "ticker" in trades_df.columns

    equity_df = sim.get_equity_curve_df()
    assert isinstance(equity_df, pl.DataFrame)
    assert equity_df.height == 1
    assert "equity" in equity_df.columns


def test_portfolio_simulator_reset() -> None:
    """reset metodunun simülatörü fabrika ayarlarına döndürdüğünü doğrular."""
    sim = PortfolioSimulatorV3(initial_capital=20_000.0)
    sim.execute_buy("THYAO", price=100.0, date="2025-01-01", quantity=5)
    sim.reset()

    assert sim.get_position_count() == 0
    assert len(sim.get_trades()) == 0
    assert sim.get_total_value() == 20_000.0


def test_portfolio_simulator_thread_safety() -> None:
    """Eşzamanlı thread'lerde alım, satım ve bakiye güncellemelerinin güvenliği."""
    sim = PortfolioSimulatorV3(initial_capital=500_000.0, max_positions=10)

    def _task(i: int) -> None:
        ticker = f"SYM_{i}"
        sim.execute_buy(ticker, price=50.0, date="2025-01-01", quantity=10)
        sim.execute_sell(ticker, price=55.0, date="2025-01-03")

    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
        futures = [executor.submit(_task, i) for i in range(5)]
        for f in futures:
            f.result()

    sim.update_equity(prices={}, date="2025-01-03")
    is_valid, errors = sim.check_invariants()
    assert is_valid is True
    assert len(errors) == 0
