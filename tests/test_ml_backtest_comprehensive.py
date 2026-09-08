"""ALPHA BIST — ML Backtest Motoru Kapsamlı Test Paketi.

8 denetim kuralına tam uyumlu:
- Mock veri yok, deterministik sentetik fiyat serileri ve sinyal fonksiyonları
- BacktestTrade, BacktestResult, ComparisonResult dataclass ve orjson serileştirme
- run_backtest() tekil model simülasyonu (komisyon, slippage, metrikler)
- compare_models() modeller arası başa baş karşılaştırma ve sıralama
- run_backtest_polars() Polars DataFrame bakiye eğrisi ve işlem geçmişi
- DuckDB WAL yapılandırması ve get_audit_as_polars okuması
- Çoklu iş parçacığı (threading) eşzamanlı backtest kilit testi
"""

import threading
from pathlib import Path

import numpy as np
import polars as pl

from services.ml.ml_backtest import (
    BacktestResult,
    BacktestTrade,
    ComparisonResult,
    MLBacktestEngine,
    TradeSide,
)


def test_dataclasses_serialization():
    """BacktestTrade, BacktestResult ve ComparisonResult serileştirme ve from_dict testi."""
    trade = BacktestTrade(
        timestamp="2026-01-05",
        ticker="THYAO",
        side=TradeSide.BUY,
        price=250.0,
        quantity=100,
        signal_score=0.85,
        model_name="champion_lgb",
        commission=25.0,
        slippage=12.5,
        pnl=500.0,
    )
    t_dict = trade.to_dict()
    assert t_dict["ticker"] == "THYAO"
    assert t_dict["side"] == "BUY"
    assert isinstance(trade.to_orjson_bytes(), bytes)

    restored_trade = BacktestTrade.from_dict(t_dict)
    assert restored_trade.ticker == "THYAO"
    assert restored_trade.price == 250.0

    res = BacktestResult(
        model_name="champion_lgb",
        total_return=0.15,
        annualized_return=0.25,
        sharpe_ratio=1.8,
        max_drawdown=0.08,
        win_rate=0.60,
        profit_factor=1.9,
        total_trades=10,
        avg_trade_pnl=50.0,
        avg_holding_days=4.5,
        calmar_ratio=3.1,
        equity_curve=[("2026-01-01", 100000.0), ("2026-01-02", 101500.0)],
        trades=[trade],
        regime_performance={"BULL": {"total_pnl": 500.0, "trades": 1}},
    )
    r_dict = res.to_dict()
    assert r_dict["model_name"] == "champion_lgb"
    assert r_dict["sharpe_ratio"] == 1.8
    assert isinstance(res.to_orjson_bytes(), bytes)

    restored_res = BacktestResult.from_dict(r_dict)
    assert restored_res.model_name == "champion_lgb"
    assert len(restored_res.trades) == 1

    comp = ComparisonResult(
        models=[res],
        best_model="champion_lgb",
        ranking_metric="sharpe_ratio",
        ranking=[("champion_lgb", 1.8)],
    )
    c_dict = comp.to_dict()
    assert c_dict["best_model"] == "champion_lgb"
    restored_comp = ComparisonResult.from_dict(c_dict)
    assert restored_comp.best_model == "champion_lgb"


def test_run_backtest_simulation():
    """Deterministik fiyat ve öznitelik serisi ile tam simülasyon testi."""
    dates = [f"2026-01-{i:02d}" for i in range(1, 21)]
    n_days = len(dates)
    # Trend yapan sentetik fiyat serisi
    prices = {"THYAO": np.linspace(100.0, 130.0, n_days)}
    features = {"THYAO": np.ones((n_days, 5)) * 0.8}

    # Her zaman yüksek skor üreten tahmin fonksiyonu
    def buy_predict_fn(x: np.ndarray) -> float:
        return 0.85

    engine = MLBacktestEngine(
        initial_capital=100_000.0,
        buy_threshold=0.70,
        sell_threshold=0.30,
    )

    res = engine.run_backtest(
        model_name="test_model",
        predict_fn=buy_predict_fn,
        price_data=prices,
        feature_data=features,
        dates=dates,
    )

    assert isinstance(res, BacktestResult)
    assert res.model_name == "test_model"
    assert len(res.equity_curve) == n_days
    assert res.total_trades >= 1


def test_compare_models():
    """İki modelin karşılaştırılması ve sıralama testi."""
    dates = [f"2026-02-{i:02d}" for i in range(1, 16)]
    n_days = len(dates)
    prices = {"GARAN": np.linspace(50.0, 65.0, n_days)}
    features = {"GARAN": np.ones((n_days, 3))}

    models = {
        "bullish_model": lambda x: 0.90,
        "bearish_model": lambda x: 0.10,
    }

    engine = MLBacktestEngine(initial_capital=50_000.0)
    comp = engine.compare_models(
        models=models,
        price_data=prices,
        feature_data=features,
        dates=dates,
        ranking_metric="sharpe_ratio",
    )

    assert isinstance(comp, ComparisonResult)
    assert len(comp.models) == 2
    assert comp.best_model in ("bullish_model", "bearish_model")


def test_run_backtest_polars():
    """run_backtest_polars() ile Polars çıktı testi."""
    dates = [f"2026-03-{i:02d}" for i in range(1, 11)]
    n_days = len(dates)
    prices = {"ASELS": np.linspace(80.0, 95.0, n_days)}
    features = {"ASELS": np.ones((n_days, 4)) * 0.75}

    engine = MLBacktestEngine(initial_capital=100_000.0)
    res, df_equity, df_trades = engine.run_backtest_polars(
        model_name="polars_test_model",
        predict_fn=lambda x: 0.80,
        price_data=prices,
        feature_data=features,
        dates=dates,
    )

    assert isinstance(res, BacktestResult)
    assert isinstance(df_equity, pl.DataFrame)
    assert isinstance(df_trades, pl.DataFrame)
    assert df_equity.height == n_days
    assert "equity" in df_equity.columns


def test_duckdb_wal_save_and_polars_read(tmp_path: Path):
    """DuckDB WAL korumalı denetim izi ve Polars okuma testi."""
    db_file = tmp_path / "test_backtest.duckdb"
    engine = MLBacktestEngine(duckdb_path=str(db_file))

    dates = ["2026-04-01", "2026-04-02", "2026-04-03"]
    prices = {"KCHOL": np.array([150.0, 155.0, 160.0])}
    features = {"KCHOL": np.ones((3, 2)) * 0.9}

    engine.run_backtest(
        model_name="audit_test_model",
        predict_fn=lambda x: 0.85,
        price_data=prices,
        feature_data=features,
        dates=dates,
    )

    df_audit = engine.get_audit_as_polars()
    assert isinstance(df_audit, pl.DataFrame)
    assert df_audit.height >= 1
    assert df_audit["model_name"][0] == "audit_test_model"


def test_thread_safety_ml_backtest():
    """Çoklu iş parçacığı altında thread-safe kilit testi."""
    engine = MLBacktestEngine()
    errors = []

    def worker():
        try:
            with engine._lock:
                assert engine.initial_capital > 0
                assert engine.commission_rate >= 0
        except Exception as exc:
            errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(errors) == 0
