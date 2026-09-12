"""
ALPHA BIST — Optimization Service Audit Test Suite
===================================================
Tests for services/optimization hardening:
- BayesianMetricOptimizer & AsymmetricBayesianOptimizer lifecycle
- Parameter representations and trial results
- RobustnessTester parameter perturbations & cost stress testing
- Repr methods, fail-safe handling and exports
"""

from datetime import datetime, timedelta

import numpy as np
import pandas as pd

import services.optimization as opt_module
from services.optimization import (
    AsymmetricBayesianOptimizer,
    AsymmetricStrategyParameters,
    AsymmetricTrialResult,
    BayesianMetricOptimizer,
    OptimizationTrialResult,
    RobustnessReport,
    RobustnessTester,
    StrategyParameters,
)


def _generate_synthetic_market_data(n_days: int = 120) -> tuple[pd.DataFrame, dict[str, pd.DataFrame]]:
    """Generates synthetic pandas market data with DatetimeIndex for testing."""
    start_date = datetime(2020, 1, 1)
    dates = [start_date + timedelta(days=i) for i in range(n_days)]

    # Benchmark Index (XU100)
    np.random.seed(42)
    bm_prices = 100.0 + np.cumsum(np.random.randn(n_days) * 1.5)
    bm_df = pd.DataFrame(
        {
            "Open": bm_prices + np.random.uniform(-0.5, 0.5, n_days),
            "High": bm_prices + 1.0,
            "Low": bm_prices - 1.0,
            "Close": bm_prices,
            "Volume": np.random.randint(100000, 500000, n_days).astype(float),
        },
        index=pd.DatetimeIndex(dates),
    )

    # Stocks
    stock_dict = {}
    for ticker in ["THYAO", "GARAN"]:
        base_price = 20.0 if ticker == "THYAO" else 15.0
        stock_prices = base_price + np.cumsum(np.random.randn(n_days) * 0.5)
        stock_df = pd.DataFrame(
            {
                "Open": stock_prices + np.random.uniform(-0.2, 0.2, n_days),
                "High": stock_prices + 0.5,
                "Low": stock_prices - 0.5,
                "Close": stock_prices,
                "Volume": np.random.randint(50000, 200000, n_days).astype(float),
            },
            index=pd.DatetimeIndex(dates),
        )
        stock_dict[ticker] = stock_df

    return bm_df, stock_dict


def test_optimization_exports():
    """Verify module exports and __all__ list."""
    expected_exports = [
        "AsymmetricBayesianOptimizer",
        "AsymmetricStrategyParameters",
        "AsymmetricTrialResult",
        "BayesianMetricOptimizer",
        "OptimizationTrialResult",
        "RobustnessReport",
        "RobustnessTester",
        "StrategyParameters",
    ]
    for export_name in expected_exports:
        assert hasattr(opt_module, export_name)
    assert sorted(opt_module.__all__) == sorted(expected_exports)


def test_bayesian_dataclasses_repr():
    """Verify StrategyParameters and OptimizationTrialResult representations."""
    params = StrategyParameters(
        min_buyer_pressure=55.0,
        min_candle_score=75.0,
        dynamic_edge_threshold=52.0,
        rsi_oversold=30.0,
        atr_trailing_mult=3.5,
        max_positions_bull=8,
    )
    repr_str = repr(params)
    assert "StrategyParameters" in repr_str
    assert "buyer_pressure=55.0" in repr_str
    assert "candle_score=75.0" in repr_str

    trial = OptimizationTrialResult(
        trial_id=42,
        params=params,
        total_return_pct=150.5,
        sharpe_ratio=2.15,
        profit_factor=1.85,
        max_drawdown=-12.4,
        fitness_score=3.82,
    )
    trial_repr = repr(trial)
    assert "OptimizationTrialResult" in trial_repr
    assert "trial_id=42" in trial_repr
    assert "return=+150.5%" in trial_repr
    assert "sharpe=2.15" in trial_repr
    assert "fitness=3.820" in trial_repr


def test_asymmetric_dataclasses_repr():
    """Verify AsymmetricStrategyParameters and AsymmetricTrialResult representations."""
    params = AsymmetricStrategyParameters(
        min_buyer_pressure=48.0,
        min_candle_score=68.0,
        rsi_oversold=32.0,
        atr_trailing_bull_mult=7.5,
        atr_trailing_bear_mult=2.2,
        position_alloc_bull=0.18,
    )
    repr_str = repr(params)
    assert "StrategyParameters" in repr_str
    assert "atr_bull=7.5" in repr_str
    assert "atr_bear=2.2" in repr_str

    trial = AsymmetricTrialResult(
        trial_id=101,
        params=params,
        total_return_pct=210.0,
        sharpe_ratio=2.45,
        profit_factor=2.10,
        max_drawdown=-8.5,
        fitness_score=5.12,
    )
    trial_repr = repr(trial)
    assert "OptimizationTrialResult" in trial_repr
    assert "trial_id=101" in trial_repr
    assert "return=+210.0%" in trial_repr


def test_robustness_report_repr():
    """Verify RobustnessReport representation."""
    params = StrategyParameters()
    report = RobustnessReport(
        base_params=params,
        base_return=85.2,
        base_sharpe=1.65,
        base_max_dd=-15.0,
        base_pf=1.45,
        perturbation_results=[{"perturbation": "+10%", "sharpe": 1.55}],
        is_plateau_stable=True,
        plateau_stability_score=4.25,
        cost_stress_results={"%0.25 (Standart)": {"profit_factor": 1.40}},
        cost_resilience_passed=True,
    )
    report_repr = repr(report)
    assert "RobustnessReport" in report_repr
    assert "base_return=+85.2%" in report_repr
    assert "base_sharpe=1.65" in report_repr
    assert "is_plateau_stable=True" in report_repr
    assert "cost_resilience_passed=True" in report_repr


def test_bayesian_optimizer_lifecycle():
    """Verify BayesianMetricOptimizer precompute and simulation."""
    bm_df, stock_dict = _generate_synthetic_market_data(n_days=100)
    optimizer = BayesianMetricOptimizer(bm_df=bm_df, stock_dict=stock_dict)

    repr_str = repr(optimizer)
    assert "BayesianMetricOptimizer" in repr_str
    assert "stocks_count=2" in repr_str
    assert "cached_tickers=2" in repr_str

    # Test simulation on sample period
    params = StrategyParameters()
    res = optimizer.simulate_fast(params, start_year=2020, end_year=2020)
    assert isinstance(res, OptimizationTrialResult)
    assert res.trial_id == 0
    assert isinstance(res.fitness_score, float)


def test_asymmetric_optimizer_lifecycle():
    """Verify AsymmetricBayesianOptimizer precompute and simulation."""
    bm_df, stock_dict = _generate_synthetic_market_data(n_days=100)
    optimizer = AsymmetricBayesianOptimizer(bm_df=bm_df, stock_dict=stock_dict)

    repr_str = repr(optimizer)
    assert "AsymmetricBayesianOptimizer" in repr_str
    assert "stocks_count=2" in repr_str

    params = AsymmetricStrategyParameters()
    res = optimizer.simulate_fast(params, start_year=2020, end_year=2020)
    assert isinstance(res, AsymmetricTrialResult)
    assert res.trial_id == 0


def test_robustness_tester_execution():
    """Verify RobustnessTester parameter perturbations and cost stress audits."""
    bm_df, stock_dict = _generate_synthetic_market_data(n_days=100)
    optimizer = BayesianMetricOptimizer(bm_df=bm_df, stock_dict=stock_dict)
    tester = RobustnessTester(optimizer=optimizer)

    repr_str = repr(tester)
    assert "RobustnessTester" in repr_str
    assert "optimizer=BayesianMetricOptimizer" in repr_str

    params = StrategyParameters()
    perturb_results, is_stable, stab_score = tester.test_parameter_perturbations(params)
    assert len(perturb_results) == 5
    assert isinstance(is_stable, bool)
    assert isinstance(stab_score, float)

    cost_results, cost_passed = tester.test_cost_stress(params)
    assert len(cost_results) == 4
    assert isinstance(cost_passed, bool)

    report = tester.run_full_robustness_audit(params)
    assert isinstance(report, RobustnessReport)
    assert report.base_params == params


def test_micro_optuna_study_execution():
    """Verify Optuna Bayesian study loops execute properly without error."""
    bm_df, stock_dict = _generate_synthetic_market_data(n_days=100)

    # Bayesian study test (2 trials)
    bayesian_opt = BayesianMetricOptimizer(bm_df=bm_df, stock_dict=stock_dict)
    best_params, trial_results = bayesian_opt.run_bayesian_study(n_trials=2)
    assert isinstance(best_params, StrategyParameters)
    assert len(trial_results) == 2

    # Asymmetric study test (2 trials)
    asymmetric_opt = AsymmetricBayesianOptimizer(bm_df=bm_df, stock_dict=stock_dict)
    best_asym_params, asym_results = asymmetric_opt.run_asymmetric_study(n_trials=2)
    assert isinstance(best_asym_params, AsymmetricStrategyParameters)
    assert len(asym_results) == 2
