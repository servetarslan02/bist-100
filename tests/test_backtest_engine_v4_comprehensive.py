"""Comprehensive unit tests for services.backtest.engine_v4."""

from __future__ import annotations

import datetime

import numpy as np
import polars as pl

from services.backtest.engine_v4 import (
    DEFAULT_INITIAL_CAPITAL,
    BacktestConfig,
    BacktestEngineV4,
    BacktestMetrics,
    BacktestResultV4,
    FeatureCache,
    QualityCache,
    _FallbackCalculator,
    _FallbackMask,
    _FallbackQuality,
)


def _generate_synthetic_market_data(
    tickers: list[str],
    n_days: int = 150,
    base_price: float = 100.0,
) -> tuple[dict[str, pl.DataFrame], pl.DataFrame]:
    """Generates synthetic OHLCV data for testing BacktestEngineV4."""
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


def test_dataclasses_repr_and_dict():
    """Verify BacktestConfig, BacktestMetrics, and BacktestResultV4 representations."""
    cfg = BacktestConfig(initial_capital=200_000.0, lookback_days=90)
    assert "200,000" in repr(cfg)
    cfg_dict = cfg.to_dict()
    assert cfg_dict["initial_capital"] == 200_000.0
    assert cfg_dict["lookback_days"] == 90

    metrics = BacktestMetrics(total_return_pct=15.5, sharpe_ratio=1.45, total_trades=25)
    assert "15.50%" in repr(metrics)
    assert "1.4500" in repr(metrics)
    m_dict = metrics.to_dict()
    assert m_dict["total_return_pct"] == 15.5
    assert m_dict["sharpe_ratio"] == 1.45

    res = BacktestResultV4(
        run_id="test_run_123",
        start_date="2025-01-01",
        end_date="2025-06-01",
        config=cfg,
        metrics=metrics,
        total_scans=100,
        signals_generated=20,
        trades_executed=15,
        look_ahead_violations=0,
        survivorship_violations=0,
        data_quality_issues=0,
        elapsed_seconds=1.25,
        scans_per_second=80.0,
        equity_curve=[],
        trades=[],
    )
    assert "test_run_123" in repr(res)
    assert "15" in repr(res)
    res_dict = res.to_dict()
    assert res_dict["run_id"] == "test_run_123"
    assert res_dict["trades_executed"] == 15
    assert res_dict["scans_per_second"] == 80.0


def test_feature_cache_and_quality_cache():
    """Verify FeatureCache and QualityCache thread-safe caching mechanisms."""
    fc = FeatureCache()
    assert fc.hit_rate == 0.0
    assert fc.get("THYAO", "2025-01-01") is None

    fc.set("THYAO", "2025-01-01", {"rsi_14": 55.0, "roc_5d": 0.02})
    # Date mismatch
    assert fc.get("THYAO", "2025-01-02") is None
    # Hit
    cached = fc.get("THYAO", "2025-01-01")
    assert cached is not None
    assert cached["rsi_14"] == 55.0
    assert fc.hit_rate > 0.0
    assert "FeatureCache" in repr(fc)

    fc.clear()
    assert fc.get("THYAO", "2025-01-01") is None
    assert fc.hit_rate == 0.0

    qc = QualityCache()
    assert qc.get("GARAN") is None
    qc.set("GARAN", True, 95.0)
    res = qc.get("GARAN")
    assert res == (True, 95.0)
    assert "QualityCache" in repr(qc)
    qc.clear()
    assert qc.get("GARAN") is None


def test_fallback_helpers():
    """Verify fallback implementations when core features are missing."""
    calc = _FallbackCalculator()
    assert "_FallbackCalculator" in repr(calc)
    feats = calc.compute_all_features(None, ticker="ASELS")
    assert feats["rsi_14"] == 50

    mask = _FallbackMask()
    assert "_FallbackMask" in repr(mask)
    m_res = mask.compute_mask()
    assert m_res.mask is None

    quality = _FallbackQuality()
    assert "_FallbackQuality" in repr(quality)
    q_res = quality.full_quality_check(None, ticker="KCHOL")
    assert q_res.passed is True
    assert q_res.quality_score == 80.0


def test_engine_v4_insufficient_data_handling():
    """Verify that BacktestEngineV4 handles insufficient historical bars gracefully."""
    market_data, b_df = _generate_synthetic_market_data(["THYAO"], n_days=30)
    config = BacktestConfig(lookback_days=100)
    engine = BacktestEngineV4(config=config, use_panel_features=False)

    result = engine.run(market_data, benchmark_data=b_df, persist=False)
    assert result.trades_executed == 0
    assert result.total_scans == 0
    assert result.metrics.total_return_pct == 0.0


def test_engine_v4_run_legacy_execution():
    """Test standard ticker-by-ticker legacy execution path."""
    market_data, b_df = _generate_synthetic_market_data(["THYAO", "GARAN", "ASELS"], n_days=140)
    config = BacktestConfig(
        initial_capital=DEFAULT_INITIAL_CAPITAL,
        lookback_days=60,
        signal_threshold=50.0,
        max_positions=5,
        max_position_pct=0.20,
    )
    engine = BacktestEngineV4(config=config, use_panel_features=False)
    assert "panel=False" in repr(engine)

    result = engine.run(market_data, benchmark_data=b_df, persist=False)
    assert isinstance(result, BacktestResultV4)
    assert result.total_scans > 0
    assert len(result.equity_curve) > 0
    assert result.run_id is not None
    assert result.metrics is not None


def test_engine_v4_run_panel_execution():
    """Test vectorized panel feature execution path."""
    market_data, b_df = _generate_synthetic_market_data(["THYAO", "SISE"], n_days=140)
    config = BacktestConfig(
        initial_capital=50_000.0,
        lookback_days=60,
        signal_threshold=52.0,
    )
    engine = BacktestEngineV4(config=config, use_panel_features=True)
    assert "panel=True" in repr(engine)

    result = engine.run(market_data, benchmark_data=b_df, persist=False)
    assert isinstance(result, BacktestResultV4)
    assert result.total_scans > 0
    assert len(result.equity_curve) > 0


def test_engine_v4_canonical_scoring_mode():
    """Test engine with canonical scoring option enabled."""
    market_data, b_df = _generate_synthetic_market_data(["BIMAS", "AKBNK"], n_days=140)
    config = BacktestConfig(
        lookback_days=60,
        use_canonical_scoring=True,
        regime="BULL",
        signal_threshold=45.0,
    )
    engine = BacktestEngineV4(config=config, use_panel_features=False)
    result = engine.run(market_data, benchmark_data=b_df, persist=False)
    assert isinstance(result, BacktestResultV4)
    assert result.total_scans > 0
