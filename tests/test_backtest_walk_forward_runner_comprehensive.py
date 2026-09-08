"""Comprehensive unit tests for services.backtest.walk_forward_runner."""

from __future__ import annotations

import datetime

import numpy as np
import polars as pl
import pytest

from services.backtest.engine_v4 import BacktestConfig
from services.backtest.walk_forward_runner import (
    DEFAULT_EMBARGO_DAYS,
    DEFAULT_PURGE_DAYS,
    DEFAULT_STEP_DAYS,
    DEFAULT_TEST_DAYS,
    DEFAULT_TRAIN_DAYS,
    FoldBacktestResult,
    WalkForwardBacktestResult,
    WalkForwardBacktestRunner,
    _filter_polars_by_date,
    _filter_polars_by_range,
    walk_forward_runner,
)


def _generate_synthetic_market_data(
    tickers: list[str],
    n_days: int = 150,
    base_price: float = 100.0,
) -> tuple[dict[str, pl.DataFrame], pl.DataFrame]:
    """Generates synthetic OHLCV data with consistent OHLC geometry."""
    start_date = datetime.date(2025, 1, 1)
    dates = [start_date + datetime.timedelta(days=i) for i in range(n_days)]

    market_data: dict[str, pl.DataFrame] = {}
    np.random.seed(42)

    for i, ticker in enumerate(tickers):
        drift = 0.0005 * (i + 1)
        returns = np.random.normal(drift, 0.015, n_days)
        prices = base_price * np.cumprod(1 + returns)
        opens = prices * (1 + np.random.normal(0, 0.003, n_days))
        highs = np.maximum(prices, opens) * (1 + np.abs(np.random.normal(0.005, 0.002, n_days)))
        lows = np.minimum(prices, opens) * (1 - np.abs(np.random.normal(0.005, 0.002, n_days)))
        volumes = np.random.uniform(500_000, 2_000_000, n_days)

        df = pl.DataFrame({
            "Date": [d.strftime("%Y-%m-%d") for d in dates],
            "Open": opens,
            "High": highs,
            "Low": lows,
            "Close": prices,
            "Volume": volumes,
        })
        market_data[ticker] = df

    # Benchmark XU100
    b_returns = np.random.normal(0.0003, 0.01, n_days)
    b_prices = 10000.0 * np.cumprod(1 + b_returns)
    b_opens = b_prices * (1 + np.random.normal(0, 0.002, n_days))
    b_highs = np.maximum(b_prices, b_opens) * 1.005
    b_lows = np.minimum(b_prices, b_opens) * 0.995
    benchmark_df = pl.DataFrame({
        "Date": [d.strftime("%Y-%m-%d") for d in dates],
        "Open": b_opens,
        "High": b_highs,
        "Low": b_lows,
        "Close": b_prices,
        "Volume": np.random.uniform(10_000_000, 50_000_000, n_days),
    })

    return market_data, benchmark_df


def test_constants():
    """Verify default constants."""
    assert DEFAULT_PURGE_DAYS == 5
    assert DEFAULT_EMBARGO_DAYS == 5
    assert DEFAULT_TRAIN_DAYS == 252
    assert DEFAULT_TEST_DAYS == 63
    assert DEFAULT_STEP_DAYS == 21


def test_dataclasses_repr_and_dict():
    """Verify FoldBacktestResult and WalkForwardBacktestResult to_dict and repr."""
    fold = FoldBacktestResult(
        fold_id=1,
        train_start="2025-01-01",
        train_end="2025-03-31",
        purge_start="2025-04-01",
        purge_end="2025-04-05",
        test_start="2025-04-06",
        test_end="2025-04-30",
        embargo_start="2025-05-01",
        embargo_end="2025-05-05",
        run_id="fold_001",
        total_return_pct=5.5,
        sharpe_ratio=1.4,
        total_trades=10,
    )
    assert "FoldBacktestResult" in repr(fold)
    assert "ret=5.50%" in repr(fold)
    f_dict = fold.to_dict()
    assert f_dict["fold_id"] == 1
    assert f_dict["total_return_pct"] == 5.5

    res = WalkForwardBacktestResult(
        run_id="wf_main_123",
        total_folds=1,
        avg_test_return_pct=5.5,
        avg_test_sharpe=1.4,
        avg_test_sortino=1.6,
        avg_test_max_drawdown_pct=2.1,
        avg_win_rate_pct=60.0,
        stability_score=0.9,
        worst_fold_return_pct=5.5,
        best_fold_return_pct=5.5,
        deflated_sharpe=1.1,
        total_trades=10,
        all_leakage_ok=True,
        folds=[fold],
    )
    assert "WalkForwardBacktestResult" in repr(res)
    assert "wf_main_123" in repr(res)
    res_dict = res.to_dict()
    assert res_dict["run_id"] == "wf_main_123"
    assert len(res_dict["folds"]) == 1


def test_polars_date_filtering_helpers():
    """Test _filter_polars_by_date and _filter_polars_by_range."""
    df = pl.DataFrame({
        "Date": ["2025-01-01", "2025-01-05", "2025-01-10", "2025-01-15"],
        "Close": [10.0, 11.0, 12.0, 13.0],
    })

    # String date column
    cut = _filter_polars_by_date(df, "2025-01-08")
    assert len(cut) == 2
    assert cut["Date"].to_list() == ["2025-01-01", "2025-01-05"]

    ranged = _filter_polars_by_range(df, "2025-01-05", "2025-01-12")
    assert len(ranged) == 2
    assert ranged["Date"].to_list() == ["2025-01-05", "2025-01-10"]

    # Native pl.Date column
    df_date = df.with_columns(pl.col("Date").str.to_date())
    cut_date = _filter_polars_by_date(df_date, "2025-01-08")
    assert len(cut_date) == 2


def test_runner_init_validation():
    """Test constructor parameter validations."""
    with pytest.raises(ValueError, match="train_days en az 1"):
        WalkForwardBacktestRunner(train_days=0)

    with pytest.raises(ValueError, match="test_days en az 1"):
        WalkForwardBacktestRunner(test_days=0)

    with pytest.raises(ValueError, match="step_days en az 1"):
        WalkForwardBacktestRunner(step_days=0)

    with pytest.raises(ValueError, match="purge_days negatif olamaz"):
        WalkForwardBacktestRunner(purge_days=-1)

    with pytest.raises(ValueError, match="embargo_days negatif olamaz"):
        WalkForwardBacktestRunner(embargo_days=-1)

    runner = WalkForwardBacktestRunner(train_days=60, test_days=10, step_days=5)
    assert "WalkForwardBacktestRunner" in repr(runner)


def test_runner_empty_result():
    """Test empty result generation when dates are insufficient."""
    runner = WalkForwardBacktestRunner(train_days=100, test_days=20)
    market_data, b_df = _generate_synthetic_market_data(["THYAO"], n_days=30)
    result = runner.run(market_data, benchmark_data=b_df, persist=False)
    assert isinstance(result, WalkForwardBacktestResult)
    assert result.total_folds == 0
    assert result.avg_test_return_pct == 0.0


def test_runner_full_run_execution():
    """Test full walk-forward execution with small windows."""
    config = BacktestConfig(lookback_days=60, signal_threshold=50.0)
    runner = WalkForwardBacktestRunner(
        backtest_config=config,
        train_days=60,
        test_days=15,
        step_days=10,
        purge_days=2,
        embargo_days=2,
        use_panel_features=False,
    )

    market_data, b_df = _generate_synthetic_market_data(["THYAO", "GARAN"], n_days=105)
    result = runner.run(market_data, benchmark_data=b_df, persist=False)

    assert isinstance(result, WalkForwardBacktestResult)
    assert result.total_folds > 0
    assert len(result.folds) == result.total_folds
    assert result.all_leakage_ok is True


def test_singleton_runner_instance():
    """Verify singleton instance."""
    assert walk_forward_runner is not None
    assert isinstance(walk_forward_runner, WalkForwardBacktestRunner)
