"""Comprehensive unit tests for services.backtest.enhanced_walk_forward."""

from __future__ import annotations

import numpy as np

from services.backtest.enhanced_walk_forward import (
    DEFAULT_EMBARGO_DAYS,
    DEFAULT_PURGE_DAYS,
    DEFAULT_STEP_DAYS,
    DEFAULT_TEST_DAYS,
    DEFAULT_TRAIN_DAYS,
    EULER_MASCHERONI,
    PurgeEmbargoFold,
    PurgeEmbargoResult,
    PurgeEmbargoWalkForward,
    purge_embargo_wf_engine,
)


def test_dataclasses_repr_and_attributes():
    """Verify dataclass reprs and structure."""
    fold = PurgeEmbargoFold(
        fold_id=1,
        train_start=0,
        train_end=251,
        test_start=257,
        test_end=319,
        train_return=0.15,
        test_return=0.08,
        precision_at_5=0.6,
        precision_at_10=0.55,
        ic=0.045,
        hit_rate=0.54,
        sharpe=1.25,
        max_drawdown=5.2,
        turnover=0.2,
    )
    r = repr(fold)
    assert "PurgeEmbargoFold" in r
    assert "id=1" in r
    assert "sharpe=1.2500" in r

    result = PurgeEmbargoResult(
        total_folds=1,
        avg_test_return=0.08,
        avg_test_sharpe=1.25,
        avg_precision_at_5=0.6,
        avg_precision_at_10=0.55,
        avg_ic=0.045,
        avg_hit_rate=0.54,
        avg_max_drawdown=5.2,
        avg_turnover=0.2,
        stability_score=0.85,
        deflated_sharpe=0.95,
        folds=[fold],
    )
    res_r = repr(result)
    assert "PurgeEmbargoResult" in res_r
    assert "folds=1" in res_r
    assert "stability=0.8500" in res_r


def test_constants():
    """Verify default constants."""
    assert DEFAULT_TRAIN_DAYS == 252
    assert DEFAULT_TEST_DAYS == 63
    assert DEFAULT_STEP_DAYS == 21
    assert DEFAULT_PURGE_DAYS == 5
    assert DEFAULT_EMBARGO_DAYS == 5
    assert abs(EULER_MASCHERONI - 0.5772156649) < 1e-6


def test_purge_embargo_split_logic():
    """Test splitting timeline into folds with purge and embargo."""
    wf = PurgeEmbargoWalkForward(train_days=100, test_days=20, purge_days=5, embargo_days=5)
    assert "PurgeEmbargoWalkForward" in repr(wf)

    # Total days: 300
    folds = wf.split(n_days=300)
    assert len(folds) >= 2

    for train_start, train_end, test_start, test_end in folds:
        assert train_end - train_start + 1 == 100
        assert test_start == train_end + 5 + 1
        assert test_end - test_start + 1 == 20
        assert test_end < 300


def test_purge_embargo_empty_split_handling():
    """Verify safe fallback when n_days is insufficient for even 1 fold."""
    wf = PurgeEmbargoWalkForward(train_days=252, test_days=63, purge_days=5, embargo_days=5)
    folds = wf.split(n_days=100)
    assert len(folds) == 0

    dummy_preds = np.zeros((100, 5))
    dummy_actuals = np.zeros((100, 5))
    res = wf.run(dummy_preds, dummy_actuals, np.array(["A", "B"]), np.array(["2025-01-01"]))
    assert isinstance(res, PurgeEmbargoResult)
    assert res.total_folds == 0
    assert res.avg_test_return == 0.0


def test_purge_embargo_full_run_with_synthetic_predictions():
    """Run full evaluation with synthetic predictions and actuals."""
    wf = PurgeEmbargoWalkForward(train_days=100, test_days=30, purge_days=3, embargo_days=3)

    np.random.seed(42)
    n_days = 320
    n_tickers = 15

    # Simulated predictions and actual returns with slight positive correlation
    actuals = np.random.normal(0.001, 0.02, (n_days, n_tickers))
    noise = np.random.normal(0, 0.01, (n_days, n_tickers))
    predictions = actuals * 0.5 + noise

    tickers = np.array([f"SYM_{i}" for i in range(n_tickers)])
    dates = np.array([f"2025-01-{i:02d}" for i in range(n_days)])

    result = wf.run(predictions, actuals, tickers, dates)
    assert isinstance(result, PurgeEmbargoResult)
    assert result.total_folds > 0
    assert len(result.folds) == result.total_folds

    for fold in result.folds:
        assert 0.0 <= fold.precision_at_5 <= 1.0
        assert 0.0 <= fold.precision_at_10 <= 1.0
        assert -1.0 <= fold.ic <= 1.0
        assert 0.0 <= fold.hit_rate <= 1.0
        assert fold.max_drawdown >= 0.0


def test_metrics_isolated_edge_cases():
    """Test individual calculation helpers on edge conditions."""
    wf = PurgeEmbargoWalkForward()

    # Empty inputs
    assert wf._precision_at_k(np.array([]), np.array([]), k=5) == 0.0
    assert wf._compute_ic(np.array([]), np.array([])) == 0.0
    assert wf._compute_hit_rate(np.array([]), np.array([])) == 0.0
    assert wf._compute_top_k_return(np.array([]), np.array([]), k=5) == 0.0
    assert wf._compute_daily_returns(np.array([]), np.array([]), k=5) == []
    assert wf._compute_sharpe([]) == 0.0
    assert wf._compute_max_drawdown([]) == 0.0
    assert wf._compute_turnover(np.array([1, 2]), np.array([1, 2])) == 0.0

    # Sharpe zero-std test
    assert wf._compute_sharpe([0.01, 0.01, 0.01]) == 0.0

    # Deflated Sharpe edge cases
    assert wf._deflated_sharpe([], 5) == 0.0
    assert wf._deflated_sharpe([1.0], 1) == 0.0
    assert wf._deflated_sharpe([1.0, 1.0, 1.0], 3) == 0.0

    # Valid Deflated Sharpe computation
    ds = wf._deflated_sharpe([1.2, 0.8, 1.5, 0.9, 1.1], 5)
    assert isinstance(ds, float)
    assert not np.isnan(ds)


def test_singleton_engine_instance():
    """Verify singleton instance availability."""
    assert purge_embargo_wf_engine is not None
    assert isinstance(purge_embargo_wf_engine, PurgeEmbargoWalkForward)
