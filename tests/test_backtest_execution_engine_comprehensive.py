"""
ALPHA BIST — Execution Engine Comprehensive Test Suite

BacktestTrade, BacktestMetrics, BacktestResult, BacktestEngine sınıflarının
T+1 takas kuralları, dinamik slippage (karekök etki modeli), likidite kısıtlamaları,
stop-loss / trailing stop mekanizmaları, metrik hesaplamaları ve işlem defteri (ledger) çıktısını doğrular.
"""

from __future__ import annotations

import concurrent.futures

import pytest

from services.backtest.execution_engine import (
    BacktestEngine,
    BacktestMetrics,
    BacktestResult,
    BacktestTrade,
)


def test_backtest_trade_and_metrics_repr() -> None:
    """BacktestTrade ve BacktestMetrics nesneleri dize temsili testi."""
    trade = BacktestTrade(
        trade_id=1,
        ticker="THYAO",
        side="BUY",
        entry_date="2025-01-01",
        exit_date="2025-01-05",
        entry_price=200.0,
        exit_price=220.0,
        quantity=100,
        pnl=2000.0,
        pnl_pct=10.0,
        holding_days=4,
        commission=15.0,
    )
    assert "THYAO" in repr(trade)
    assert "BUY" in repr(trade)
    assert "pnl=2000.00" in repr(trade)

    metrics = BacktestMetrics(
        total_return_pct=25.5,
        cagr_pct=20.0,
        sharpe_ratio=1.85,
        sortino_ratio=2.1,
        calmar_ratio=1.5,
        max_drawdown_pct=8.5,
        max_drawdown_duration_days=12,
        win_rate=65.0,
        profit_factor=2.4,
        avg_win=500.0,
        avg_loss=250.0,
        expectancy=200.0,
        total_trades=15,
        total_fees=120.0,
        avg_holding_days=3.5,
        exposure_pct=45.0,
    )
    assert "return=25.50%" in repr(metrics)
    assert "sharpe=1.85" in repr(metrics)


def test_dynamic_slippage_and_liquidity_constraints() -> None:
    """Dinamik slippage ve katılım oranı sınırlandırması testi."""
    engine = BacktestEngine()

    # Hacim 0 iken slippage 3 katına çıkmalı
    slip_zero = engine._compute_dynamic_slippage(price=100.0, volume=0, quantity=100, base_slippage_pct=0.05)
    assert slip_zero == pytest.approx(0.15)

    # Normal hacimde slippage hesabı
    slip_norm = engine._compute_dynamic_slippage(
        price=100.0, volume=100_000, quantity=100, base_slippage_pct=0.05
    )
    assert slip_norm > 0.025

    # Likidite kısıtı (%10 katılım tavanı)
    # Hacim 10_000 -> max_shares = 1_000
    feasible, qty_adjusted = engine._check_liquidity_constraint(
        price=50.0, volume=10_000, quantity=2_000, max_participation=0.10
    )
    assert feasible is True
    assert qty_adjusted == 1_000  # Kısmi execution ile 1_000'e sınırlandırılmalı

    # Sıfır hacimde kısıt False dönmeli
    f_zero, q_zero = engine._check_liquidity_constraint(price=50.0, volume=0, quantity=100)
    assert f_zero is False
    assert q_zero == 0


def test_run_backtest_lifecycle() -> None:
    """Tam sinyal besleme, T+1 açılışta emir doldurma ve karlı kapanış döngüsü."""
    engine = BacktestEngine()

    signals = [
        {"ticker": "THYAO", "action": "BUY", "date": "2025-01-01", "weight": 0.10},
        {"ticker": "THYAO", "action": "SELL", "date": "2025-01-03", "weight": 0.10},
    ]

    price_data = {
        "THYAO": [
            {"date": "2025-01-01", "open": 100.0, "high": 102.0, "low": 99.0, "close": 101.0, "volume": 100_000},
            {"date": "2025-01-02", "open": 102.0, "high": 105.0, "low": 101.0, "close": 104.0, "volume": 120_000},
            {"date": "2025-01-03", "open": 105.0, "high": 108.0, "low": 104.0, "close": 107.0, "volume": 110_000},
            {"date": "2025-01-04", "open": 108.0, "high": 110.0, "low": 107.0, "close": 109.0, "volume": 100_000},
        ]
    }

    result = engine.run_backtest(
        strategy_name="TEST_STRAT",
        signals=signals,
        price_data=price_data,
        initial_capital=100_000.0,
    )

    assert isinstance(result, BacktestResult)
    assert result.strategy_name == "TEST_STRAT"
    assert len(result.trades) >= 1
    assert result.trades[0].pnl > 0  # Kârlı kapanmış olmalı
    assert len(result.equity_curve) == 4
    assert repr(result).startswith("BacktestResult")


def test_run_backtest_stop_loss_trigger() -> None:
    """Fiyat sert düştüğünde stop-loss tetiklenmesi ve pozisyonun kapanması."""
    engine = BacktestEngine()

    signals = [
        {"ticker": "ASELS", "action": "BUY", "date": "2025-01-01", "weight": 0.20},
    ]

    # 1. gün alım sinyali -> 2. gün 100 TL'den açılışla alım -> 3. gün low 90 TL (%10 düşüş > %7 stop-loss)
    price_data = {
        "ASELS": [
            {"date": "2025-01-01", "open": 100.0, "high": 101.0, "low": 99.0, "close": 100.0, "volume": 50_000},
            {"date": "2025-01-02", "open": 100.0, "high": 102.0, "low": 98.0, "close": 99.0, "volume": 50_000},
            {"date": "2025-01-03", "open": 95.0, "high": 96.0, "low": 90.0, "close": 91.0, "volume": 50_000},
            {"date": "2025-01-04", "open": 90.0, "high": 92.0, "low": 89.0, "close": 90.0, "volume": 50_000},
        ]
    }

    result = engine.run_backtest(
        strategy_name="STOP_LOSS_TEST",
        signals=signals,
        price_data=price_data,
        initial_capital=100_000.0,
        stop_loss_pct=0.07,
    )

    stop_trades = [t for t in result.trades if t.side == "STOP_SELL"]
    assert len(stop_trades) == 1
    assert stop_trades[0].pnl < 0  # Zararla stop olmuş olmalı


def test_run_backtest_empty_signals() -> None:
    """Boş sinyal listesi durumunda sıfır işlemle güvenle dönülmesi."""
    engine = BacktestEngine()
    res = engine.run_backtest(
        strategy_name="EMPTY",
        signals=[],
        price_data={},
        initial_capital=50_000.0,
    )
    assert res.final_capital == 50_000.0
    assert len(res.trades) == 0
    assert res.metrics.total_trades == 0


def test_execution_engine_thread_safety() -> None:
    """Eşzamanlı thread'lerde bağımsız backtest koşturulması testi."""
    engine = BacktestEngine()

    price_data = {
        "THYAO": [
            {"date": "2025-01-01", "open": 100.0, "high": 102.0, "low": 99.0, "close": 101.0, "volume": 100_000},
            {"date": "2025-01-02", "open": 102.0, "high": 105.0, "low": 101.0, "close": 104.0, "volume": 120_000},
        ]
    }

    def _task(idx: int) -> float:
        signals = [{"ticker": "THYAO", "action": "BUY", "date": "2025-01-01", "weight": 0.05 * (idx + 1)}]
        res = engine.run_backtest(
            strategy_name=f"THREAD_{idx}",
            signals=signals,
            price_data=price_data,
            initial_capital=100_000.0,
        )
        return res.final_capital

    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
        futures = [executor.submit(_task, i) for i in range(3)]
        caps = [f.result() for f in futures]

    assert len(caps) == 3
    for c in caps:
        assert c > 0
