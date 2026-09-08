"""Comprehensive unit tests for services.backtest.walk_forward."""

from __future__ import annotations

import pytest

from services.backtest.walk_forward import (
    ANNUALIZATION_FACTOR,
    DEFAULT_EMBARGO_DAYS,
    DEFAULT_PURGE_DAYS,
    DEFAULT_STEP_DAYS,
    DEFAULT_TEST_DAYS,
    DEFAULT_TRAIN_DAYS,
    WalkForwardEngine,
    WalkForwardFold,
    WalkForwardResult,
    walk_forward_engine,
)


def test_dataclasses_repr_and_defaults():
    """Test WalkForwardFold and WalkForwardResult representation and defaults."""
    fold = WalkForwardFold(
        fold_id=1,
        train_start="2024-01-01",
        train_end="2024-06-30",
        test_start="2024-07-08",
        test_end="2024-09-30",
        purge_start="2024-07-01",
        purge_end="2024-07-07",
        embargo_start="2024-10-01",
        embargo_end="2024-10-07",
        train_samples=120,
        test_samples=60,
        test_return=0.12,
        sharpe=1.45,
    )
    r = repr(fold)
    assert "WalkForwardFold" in r
    assert "id=1" in r
    assert "test_ret=12.00%" in r

    result = WalkForwardResult(
        total_folds=1,
        avg_test_return=0.12,
        avg_test_sharpe=1.45,
        avg_test_drawdown=4.2,
        avg_win_rate=0.58,
        avg_precision_at_5=0.6,
        avg_precision_at_10=0.55,
        avg_precision_at_20=0.50,
        avg_ic=0.06,
        stability_score=0.9,
        worst_fold_return=0.12,
        best_fold_return=0.12,
        deflated_sharpe=1.1,
        folds=[fold],
    )
    res_r = repr(result)
    assert "WalkForwardResult" in res_r
    assert "folds=1" in res_r
    assert "avg_ret=12.00%" in res_r


def test_constants():
    """Verify constants defined in walk_forward."""
    assert DEFAULT_PURGE_DAYS == 5
    assert DEFAULT_EMBARGO_DAYS == 5
    assert DEFAULT_TRAIN_DAYS == 252
    assert DEFAULT_TEST_DAYS == 63
    assert DEFAULT_STEP_DAYS == 21
    assert ANNUALIZATION_FACTOR == 252


def test_engine_init_validation():
    """Test boundary validation in WalkForwardEngine constructor."""
    with pytest.raises(ValueError, match="negatif olamaz"):
        WalkForwardEngine(purge_days=-1, _warn=False)

    with pytest.raises(ValueError, match="negatif olamaz"):
        WalkForwardEngine(embargo_days=-1, _warn=False)

    with pytest.raises(ValueError, match="pozitif olmalıdır"):
        WalkForwardEngine(train_days=0, _warn=False)

    with pytest.raises(ValueError, match="pozitif olmalıdır"):
        WalkForwardEngine(test_days=-5, _warn=False)

    with pytest.raises(ValueError, match="pozitif olmalıdır"):
        WalkForwardEngine(step_days=0, _warn=False)

    engine = WalkForwardEngine(purge_days=3, embargo_days=3, train_days=100, test_days=20, step_days=10, _warn=False)
    assert "WalkForwardEngine" in repr(engine)
    assert engine.purge_days == 3


def test_create_folds_calculation():
    """Test create_folds generation and temporal intervals."""
    engine = WalkForwardEngine(purge_days=5, embargo_days=5, train_days=60, test_days=20, step_days=15, _warn=False)

    dates = [f"2024-{(i//30)+1:02d}-{(i%30)+1:02d}" for i in range(150)]
    folds = engine.create_folds(dates)
    assert len(folds) >= 2

    for f in folds:
        assert "train_start" in f
        assert "train_end" in f
        assert "purge_start" in f
        assert "purge_end" in f
        assert "test_start" in f
        assert "test_end" in f
        assert "embargo_start" in f
        assert "embargo_end" in f

    # Empty or short date range
    assert engine.create_folds([]) == []
    assert engine.create_folds(dates[:50]) == []


def test_extract_returns_from_price_data():
    """Test parsing varied price_data structures."""
    engine = WalkForwardEngine(_warn=False)

    # Dictionary already mapped {date: {ticker: return}}
    d_map = {"2024-01-01": {"THYAO": 0.02, "GARAN": -0.01}}
    extracted = engine._extract_returns_from_price_data(d_map)
    assert extracted == d_map

    # List of closes {ticker: [{date, close}]}
    series_map = {
        "THYAO": [
            {"date": "2024-01-01", "close": 100.0},
            {"date": "2024-01-02", "close": 102.0},
            {"date": "2024-01-03", "close": 105.06},
        ]
    }
    extracted_series = engine._extract_returns_from_price_data(series_map)
    assert "2024-01-02" in extracted_series
    assert abs(extracted_series["2024-01-02"]["THYAO"] - 0.02) < 1e-4

    # Invalid input
    assert engine._extract_returns_from_price_data(None) == {}


def test_run_walk_forward_full_workflow():
    """Test full execution of run_walk_forward with signals and returns."""
    engine = WalkForwardEngine(
        purge_days=2,
        embargo_days=2,
        train_days=30,
        test_days=10,
        step_days=10,
        _warn=False,
    )

    n_days = 70
    dates = [f"2024-{(i//30)+1:02d}-{(i%30)+1:02d}" for i in range(n_days)]

    predictions = []
    actual_returns = {}

    for d in dates:
        actual_returns[d] = {"THYAO": 0.01, "GARAN": -0.005, "ASELS": 0.02}
        predictions.append({"date": d, "ticker": "THYAO", "score": 75.0, "predicted_return": 1.0})
        predictions.append({"date": d, "ticker": "GARAN", "score": 45.0, "predicted_return": -0.5})
        predictions.append({"date": d, "ticker": "ASELS", "score": 85.0, "predicted_return": 2.0})

    result = engine.run_walk_forward(
        predictions=predictions,
        actual_returns=actual_returns,
        dates=dates,
    )

    assert isinstance(result, WalkForwardResult)
    assert result.total_folds > 0
    assert len(result.folds) == result.total_folds
    assert result.avg_test_return != 0.0
    assert result.summary["total_predictions"] > 0


def test_run_walk_forward_insufficient_data():
    """Test graceful handling when dates are insufficient."""
    engine = WalkForwardEngine(train_days=100, test_days=30, _warn=False)
    res = engine.run_walk_forward(dates=["2024-01-01", "2024-01-02"])
    assert res.total_folds == 0
    assert res.avg_test_return == 0.0


def test_singleton_instance():
    """Verify singleton instance."""
    assert walk_forward_engine is not None
    assert isinstance(walk_forward_engine, WalkForwardEngine)
