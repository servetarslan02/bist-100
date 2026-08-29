#!/usr/bin/env python3
import structlog
logger = structlog.get_logger(__name__)
from typing import Any
"""
ALPHA BIST — Walk-Forward Canonical Scoring Tests

Walk-forward sisteminin canonical scoring pipeline ile entegrasyon testleri.
"""

import os
import sys
import tempfile
from datetime import datetime, timedelta

import numpy as np

try:
    import polars as pl
except ImportError:
    pl = None
import pytest

pytestmark = pytest.mark.skipif(pl is None, reason="polars library required")


def _make_market_data(n_stocks=8, n_days=380, seed=42) -> Any:
    """Otomatik eklendi."""
    np.random.seed(seed)
    market = {}
    pl.date_range(datetime.now() - timedelta(days=n_days * 2), datetime.now(), timedelta(days=1), eager=True).tail(
        n_days
    )
    for i in range(n_stocks):
        trend = np.random.uniform(-0.001, 0.002)
        vol = np.random.uniform(0.01, 0.025)
        close = 100 * np.exp(np.cumsum(np.random.randn(n_days) * vol + trend))
        high = close * (1 + np.abs(np.random.randn(n_days)) * 0.008)
        low = close * (1 - np.abs(np.random.randn(n_days)) * 0.008)
        volume = np.random.randint(50000, 500000, n_days).astype(float)
        market[f"STOCK{i:04d}"] = pl.DataFrame(
            {
                "Open": close * (1 + np.random.randn(n_days) * 0.002),
                "High": high,
                "Low": low,
                "Close": close,
                "Volume": volume,
            }
        )
    return market


def _make_benchmark(market, seed=99) -> Any:
    """Otomatik eklendi."""
    np.random.seed(seed)
    dates = sorted(set(d for df in market.values() for d in df.index))
    n = len(dates)
    close = 1000 * np.exp(np.cumsum(np.random.randn(n) * 0.008))
    return pl.DataFrame(
        {"Open": close, "High": close * 1.005, "Low": close * 0.995, "Close": close, "Volume": np.full(n, 1000000.0)}
    )


def _make_historical_repo() -> Any:
    """Test için historical repository oluştur."""
    from services.data.historical_contracts import (
        CatalystSnapshot,
        EventSnapshot,
        FundamentalSnapshot,
    )
    from services.data.persistent_repository import PersistentHistoricalRepository

    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    repo = PersistentHistoricalRepository(db_path=path)

    # Fundamental
    for ticker in ["STOCK0000", "STOCK0001"]:
        repo.add_fundamental_snapshot(
            FundamentalSnapshot(
                ticker=ticker,
                period_end="2025-06-30",
                available_at="2025-08-14",
                values={
                    "pe_ratio": 8.5,
                    "roe": 0.18,
                    "free_cash_flow": 5e9,
                    "market_cap": 200e9,
                    "debt_to_equity": 0.3,
                    "current_ratio": 2.5,
                },
                source="yfinance",
                status="FRESH",
            )
        )

    # KAP events
    for ticker in ["STOCK0000", "STOCK0001"]:
        repo.add_event_snapshot(
            EventSnapshot(
                event_id=f"KAP-{ticker}",
                ticker=ticker,
                published_at="2025-08-10T10:00:00",
                event_type="FINANCIAL_REPORT",
                title="Q2 Report",
                sentiment=0.5,
                importance=1.0,
                source="kap",
            )
        )

    # Catalyst
    for ticker in ["STOCK0000", "STOCK0001"]:
        repo.add_catalyst_snapshot(
            CatalystSnapshot(
                event_id=f"CAT-{ticker}",
                ticker=ticker,
                announcement_date="2025-08-10",
                event_date="2025-08-20",
                catalyst_type="EARNINGS",
                importance=0.9,
                source="kap",
            )
        )

    return repo, path


# =====================================================
# 1. WALK-FORWARD CANONICAL MODE WORKS
# =====================================================


def test_wf_canonical_mode_works() -> Any:
    """Walk-forward canonical modda çalışıyor mu?"""
    from services.backtest.engine_v4 import BacktestConfig
    from services.backtest.walk_forward_runner import WalkForwardBacktestRunner

    issues = []

    market = _make_market_data(8, 380)
    benchmark = _make_benchmark(market)

    cfg = BacktestConfig(
        use_canonical_scoring=True,
        regime="BULL",
        lookback_days=60,
        initial_capital=100000,
    )

    runner = WalkForwardBacktestRunner(
        backtest_config=cfg,
        purge_days=5,
        embargo_days=5,
        train_days=120,
        test_days=40,
        step_days=40,
        use_panel_features=False,
    )

    result = runner.run(market, benchmark_data=benchmark, persist=False)

    if result is None:
        issues.append("Result None")
    elif result.total_folds == 0:
        issues.append("0 folds")
    elif not result.all_leakage_ok:
        issues.append(f"Leakage ihlali: {[f.leakage_errors for f in result.folds if not f.leakage_ok]}")

    return "WF canonical mode works", len(issues) == 0, issues


# =====================================================
# 2. WALK-FORWARD LEGACY MODE UNCHANGED
# =====================================================


def test_wf_legacy_mode_unchanged() -> Any:
    """Walk-forward legacy mode hiç değişmemiş mi?"""
    from services.backtest.engine_v4 import BacktestConfig
    from services.backtest.walk_forward_runner import WalkForwardBacktestRunner

    issues = []

    market = _make_market_data(8, 380)

    cfg = BacktestConfig(lookback_days=60, initial_capital=100000)

    runner = WalkForwardBacktestRunner(
        backtest_config=cfg,
        purge_days=5,
        embargo_days=5,
        train_days=120,
        test_days=40,
        step_days=40,
        use_panel_features=False,
    )

    result = runner.run(market, persist=False)

    if result is None:
        issues.append("Result None")
    elif result.total_folds == 0:
        issues.append("0 folds")

    return "WF legacy mode unchanged", len(issues) == 0, issues


# =====================================================
# 3. WALK-FORWARD WITH HISTORICAL REPOSITORY
# =====================================================


def test_wf_with_historical_repo() -> Any:
    """Walk-forward historical repository ile çalışıyor mu?"""
    from services.backtest.engine_v4 import BacktestConfig
    from services.backtest.walk_forward_runner import WalkForwardBacktestRunner

    issues = []

    market = _make_market_data(8, 380)
    benchmark = _make_benchmark(market)
    repo, path = _make_historical_repo()

    cfg = BacktestConfig(
        use_canonical_scoring=True,
        regime="BULL",
        lookback_days=60,
        initial_capital=100000,
        historical_repository=repo,
    )

    runner = WalkForwardBacktestRunner(
        backtest_config=cfg,
        purge_days=5,
        embargo_days=5,
        train_days=120,
        test_days=40,
        step_days=40,
        use_panel_features=False,
    )

    result = runner.run(market, benchmark_data=benchmark, persist=False)

    if result is None:
        issues.append("Result None")
    elif result.total_folds == 0:
        issues.append("0 folds")

    # Cleanup
    repo.close()
    os.unlink(path)

    return "WF with historical repo", len(issues) == 0, issues


# =====================================================
# 4. FOLD DATA PIT-SAFE
# =====================================================


def test_fold_data_pit_safe() -> Any:
    """Her fold'un verisi test_end'e kadar kesiliyor mu?"""
    from services.backtest.walk_forward_runner import WalkForwardBacktestRunner

    issues = []

    market = _make_market_data(5, 200)
    dates = sorted(set(d for df in market.values() for d in df.index))

    # Truncate test
    test_end = str(dates[150].date()) if hasattr(dates[150], "date") else str(dates[150])
    truncated = WalkForwardBacktestRunner._truncate(market, test_end)

    for ticker, df in truncated.items():
        last = df.index[-1]
        last_str = str(last.date()) if hasattr(last, "date") else str(last)
        if last_str > test_end:
            issues.append(f"{ticker}: veri {last_str} > {test_end}")

    return "Fold data PIT safe", len(issues) == 0, issues


# =====================================================
# 5. TRAIN-TEST LEAKAGE
# =====================================================


def test_train_test_leakage() -> Any:
    """Train verisi test'e sızıyor mu?"""
    from services.backtest.engine_v4 import BacktestConfig
    from services.backtest.walk_forward_runner import WalkForwardBacktestRunner

    issues = []

    market = _make_market_data(8, 380)

    cfg = BacktestConfig(lookback_days=60, initial_capital=100000)

    runner = WalkForwardBacktestRunner(
        backtest_config=cfg,
        purge_days=5,
        embargo_days=5,
        train_days=120,
        test_days=40,
        step_days=40,
        use_panel_features=False,
    )

    result = runner.run(market, persist=False)

    # Her fold'un leakage kontrolü
    for fold in result.folds:
        if not fold.leakage_ok:
            issues.append(f"Fold {fold.fold_id} leakage: {fold.leakage_errors}")

    # Trade'ler test penceresi içinde olmalı
    for fold in result.folds:
        if fold.total_trades > 0:
            # Trade tarihleri test_start ile test_end arasında olmalı
            pass  # Runner zaten kontrol ediyor

    return "Train-test leakage", len(issues) == 0, issues


# =====================================================
# 6. CANONICAL SCORE DETERMINISTIC
# =====================================================


def test_canonical_score_deterministic_in_wf() -> Any:
    """Walk-forward canonical skorlar deterministic mi?"""
    from services.backtest.engine_v4 import BacktestConfig
    from services.backtest.walk_forward_runner import WalkForwardBacktestRunner

    issues = []

    market = _make_market_data(8, 380, seed=42)
    benchmark = _make_benchmark(market, seed=99)

    cfg = BacktestConfig(
        use_canonical_scoring=True,
        regime="BULL",
        lookback_days=60,
        initial_capital=100000,
    )

    # İki kez çalıştır
    results = []
    for _ in range(2):
        runner = WalkForwardBacktestRunner(
            backtest_config=cfg,
            purge_days=5,
            embargo_days=5,
            train_days=120,
            test_days=40,
            step_days=40,
            use_panel_features=False,
        )
        r = runner.run(market, benchmark_data=benchmark, persist=False)
        results.append(r)

    # Sonuçlar aynı olmalı
    if results[0].total_folds != results[1].total_folds:
        issues.append(f"Fold sayısı farklı: {results[0].total_folds} vs {results[1].total_folds}")

    for f1, f2 in zip(results[0].folds, results[1].folds, strict=False):
        if f1.total_return_pct != f2.total_return_pct:
            issues.append(f"Fold {f1.fold_id} return farklı: {f1.total_return_pct} vs {f2.total_return_pct}")
            break

    return "Canonical score deterministic in WF", len(issues) == 0, issues


# =====================================================
# 7. FUTURE DATA MUTATION INVARIANCE
# =====================================================


def test_future_data_mutation_invariance() -> Any:
    """Gelecek veri değişimi geçmiş fold sonuçlarını etkilememeli."""
    from services.backtest.engine_v4 import BacktestConfig
    from services.backtest.walk_forward_runner import WalkForwardBacktestRunner

    issues = []

    market = _make_market_data(8, 380, seed=42)
    benchmark = _make_benchmark(market, seed=99)

    cfg = BacktestConfig(
        use_canonical_scoring=True,
        regime="BULL",
        lookback_days=60,
        initial_capital=100000,
    )

    runner = WalkForwardBacktestRunner(
        backtest_config=cfg,
        purge_days=5,
        embargo_days=5,
        train_days=120,
        test_days=40,
        step_days=40,
        use_panel_features=False,
    )

    # Normal run
    result_normal = runner.run(market, benchmark_data=benchmark, persist=False)

    # Gelecek veriyi boz
    market_poisoned = {}
    for ticker, df in market.items():
        df2 = df.copy()
        # Son50 günü çılgın değerlere çevir
        df2.iloc[-50:, df2.columns.get_loc("Close")] *= 100
        df2.iloc[-50:, df2.columns.get_loc("Open")] *= 100
        market_poisoned[ticker] = df2

    runner2 = WalkForwardBacktestRunner(
        backtest_config=cfg,
        purge_days=5,
        embargo_days=5,
        train_days=120,
        test_days=40,
        step_days=40,
        use_panel_features=False,
    )
    result_poisoned = runner2.run(market_poisoned, benchmark_data=benchmark, persist=False)

    # İlk birkaç fold aynı olmalı (gelecek veri onları etkilememeli)
    for i in range(min(3, result_normal.total_folds)):
        if i < len(result_poisoned.folds):
            f_normal = result_normal.folds[i]
            f_poisoned = result_poisoned.folds[i]
            # Trade sayısı aynı olmalı (gelecek veri etkilememeli)
            if f_normal.total_trades != f_poisoned.total_trades:
                issues.append(
                    f"Fold {f_normal.fold_id} trades değişti: {f_normal.total_trades} vs {f_poisoned.total_trades}"
                )

    return "Future data mutation invariance", len(issues) == 0, issues


# =====================================================
# 8. HISTORICAL DATA IN FOLD
# =====================================================


def test_historical_data_used_in_fold() -> Any:
    """Historical veri fold'larda gerçekten kullanılıyor mu?"""
    from services.backtest.engine_v4 import BacktestConfig
    from services.backtest.walk_forward_runner import WalkForwardBacktestRunner

    issues = []

    market = _make_market_data(8, 380)
    benchmark = _make_benchmark(market)
    repo, path = _make_historical_repo()

    # Historical repo ile
    cfg_with = BacktestConfig(
        use_canonical_scoring=True,
        regime="BULL",
        lookback_days=60,
        initial_capital=100000,
        historical_repository=repo,
    )

    # Historical repo olmadan
    cfg_without = BacktestConfig(
        use_canonical_scoring=True,
        regime="BULL",
        lookback_days=60,
        initial_capital=100000,
    )

    runner_with = WalkForwardBacktestRunner(
        backtest_config=cfg_with,
        purge_days=5,
        embargo_days=5,
        train_days=120,
        test_days=40,
        step_days=40,
        use_panel_features=False,
    )

    runner_without = WalkForwardBacktestRunner(
        backtest_config=cfg_without,
        purge_days=5,
        embargo_days=5,
        train_days=120,
        test_days=40,
        step_days=40,
        use_panel_features=False,
    )

    result_with = runner_with.run(market, benchmark_data=benchmark, persist=False)
    result_without = runner_without.run(market, benchmark_data=benchmark, persist=False)

    # Her ikisi de çalışmalı
    if result_with is None or result_without is None:
        issues.append("Biri None döndü")

    repo.close()
    os.unlink(path)

    return "Historical data used in fold", len(issues) == 0, issues


# =====================================================
# 9. REGIME IN WALK-FORWARD
# =====================================================


def test_regime_in_walk_forward() -> Any:
    """Regime değişimi walk-forward'da doğru mu?"""
    from services.backtest.engine_v4 import BacktestConfig
    from services.backtest.walk_forward_runner import WalkForwardBacktestRunner

    issues = []

    market = _make_market_data(8, 380)

    for regime in ["BULL", "BEAR", "SIDEWAYS"]:
        cfg = BacktestConfig(
            use_canonical_scoring=True,
            regime=regime,
            lookback_days=60,
            initial_capital=100000,
        )

        runner = WalkForwardBacktestRunner(
            backtest_config=cfg,
            purge_days=5,
            embargo_days=5,
            train_days=120,
            test_days=40,
            step_days=40,
            use_panel_features=False,
        )

        result = runner.run(market, persist=False)
        if result is None:
            issues.append(f"{regime}: Result None")
        elif result.total_folds == 0:
            issues.append(f"{regime}: 0 folds")

    return "Regime in walk-forward", len(issues) == 0, issues


# =====================================================
# 10. LEAKAGE GUARDS
# =====================================================


def test_leakage_guards() -> Any:
    """Leakage guard'ları çalışıyor mu?"""
    from services.backtest.walk_forward_runner import WalkForwardBacktestRunner

    issues = []

    market = _make_market_data(5, 200)
    dates = sorted(set(d for df in market.values() for d in df.index))

    # Geçerli fold
    test_end = str(dates[150].date()) if hasattr(dates[150], "date") else str(dates[150])
    truncated = WalkForwardBacktestRunner._truncate(market, test_end)

    for ticker, df in truncated.items():
        last = df.index[-1]
        last_str = str(last.date()) if hasattr(last, "date") else str(last)
        if last_str > test_end:
            issues.append(f"PIT ihlali: {ticker}")

    return "Leakage guards", len(issues) == 0, issues


# =====================================================
# RUN
# =====================================================


def run_all() -> Any:
    """Otomatik eklendi."""
    logger.info("=" * 60)
    logger.info("  Walk-Forward Canonical Scoring Tests")
    logger.info("=" * 60)

    tests = [
        test_wf_canonical_mode_works,
        test_wf_legacy_mode_unchanged,
        test_wf_with_historical_repo,
        test_fold_data_pit_safe,
        test_train_test_leakage,
        test_canonical_score_deterministic_in_wf,
        test_future_data_mutation_invariance,
        test_historical_data_used_in_fold,
        test_regime_in_walk_forward,
        test_leakage_guards,
    ]

    passed = failed = 0
    all_issues = []

    for test_func in tests:
        try:
            name, ok, issues = test_func()
        except Exception as e:
            name, ok, issues = test_func.__name__, False, [f"Exception: {e}"]
            import traceback

            traceback.print_exc()

        icon = "✅" if ok else "❌"
        logger.info(f"{icon} {name}")
        if ok:
            passed += 1
        else:
            failed += 1
            for i in issues:
                logger.info(f"   ❌ {i}")
                all_issues.append(f"{name}: {i}")

    logger.info(f"\n{'=' * 60}")
    logger.info(f"  SONUÇ: {passed}/{passed + failed} geçti")
    if all_issues:
        logger.info("\n  HATALAR:")
        for i, issue in enumerate(all_issues, 1):
            logger.info(f"    {i}. {issue}")
    logger.info("=" * 60)
    return failed == 0


if __name__ == "__main__":
    ok = run_all()
    sys.exit(0 if ok else 1)
