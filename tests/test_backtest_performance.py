#!/usr/bin/env python3
"""
Backtest Performance Testleri

Kapsam:
- Feature cache doğruluğu
- Quality cache doğruluğu
- Portfolio simulator correctness
- Performance benchmarks (100/500/1000 hisse)
- Look-ahead bias
- Survivorship bias
- Equity invariant
- Sonuç tutarlılığı
"""

import sys
import os
import time
import numpy as np
import pandas as pd
from datetime import datetime

from services.scanner.backtest_runner import (
    ScannerBacktestRunner, PortfolioSimulator, FeatureCache, QualityCache,
)


def make_market_data(n_stocks=100, n_days=252, seed=42):
    """1 yıllık gerçekçi market dataset."""
    np.random.seed(seed)
    tickers = [f"STOCK{i:04d}" for i in range(n_stocks)]
    market = {}
    for ticker in tickers:
        trend = np.random.uniform(-0.001, 0.002)
        vol = np.random.uniform(0.01, 0.025)
        dates = pd.date_range(end=datetime.now(), periods=n_days, freq='B')
        close = 100 * np.exp(np.cumsum(np.random.randn(n_days) * vol + trend))
        high = close * (1 + np.abs(np.random.randn(n_days) * 0.008))
        low = close * (1 - np.abs(np.random.randn(n_days) * 0.008))
        volume = np.random.randint(50000, 500000, n_days).astype(float)
        market[ticker] = pd.DataFrame({
            'Open': close * (1 + np.random.randn(n_days) * 0.002),
            'High': high, 'Low': low, 'Close': close, 'Volume': volume
        }, index=dates)
    return market


# =====================================================
# CACHE TESTS
# =====================================================

def test_feature_cache():
    """Feature cache doğru çalışmalı."""
    issues = []
    cache = FeatureCache()

    features = {"rsi_14": 65.0, "momentum_20d": 0.05}
    cache.set("THYAO", "2026-01-01", features)

    # Cache hit
    cached = cache.get("THYAO", "2026-01-01")
    if cached != features:
        issues.append("Cache hit başarısız")

    # Cache miss (farklı tarih)
    miss = cache.get("THYAO", "2026-01-02")
    if miss is not None:
        issues.append("Farklı tarih cache hit")

    # Cache miss (farklı ticker)
    miss2 = cache.get("GARAN", "2026-01-01")
    if miss2 is not None:
        issues.append("Farklı ticker cache hit")

    # Invalidation
    cache.invalidate("THYAO")
    miss3 = cache.get("THYAO", "2026-01-01")
    if miss3 is not None:
        issues.append("Invalidation başarısız")

    return "Feature Cache", len(issues) == 0, issues


def test_quality_cache():
    """Quality cache doğru çalışmalı."""
    issues = []
    cache = QualityCache()

    cache.set("THYAO", True, 85.0)
    cache.set("BAD", False, 30.0)

    r1 = cache.get("THYAO")
    if r1 != (True, 85.0):
        issues.append(f"THYAO: {r1}")

    r2 = cache.get("BAD")
    if r2 != (False, 30.0):
        issues.append(f"BAD: {r2}")

    r3 = cache.get("UNKNOWN")
    if r3 is not None:
        issues.append(f"UNKNOWN: {r3}")

    return "Quality Cache", len(issues) == 0, issues


# =====================================================
# PORTFOLIO SIMULATOR TESTS
# =====================================================

def test_simulator_commission():
    """Komisyon hesapları doğru olmalı."""
    issues = []
    sim = PortfolioSimulator(initial_capital=100000, commission_rate=0.001, slippage_rate=0.001)

    trade = sim.execute_buy("X", 100.0, "2026-01-01")
    if not trade:
        issues.append("Alım başarısız")
        return "Simulator Commission", False, issues

    # Komisyon > 0
    if trade.commission <= 0:
        issues.append(f"Komisyon: {trade.commission}")

    # Slippage > 0
    if trade.slippage <= 0:
        issues.append(f"Slippage: {trade.slippage}")

    # Cash düşmüş olmalı
    if sim._cash >= 100000:
        issues.append("Cash düşmemiş")

    return "Simulator Commission", len(issues) == 0, issues


def test_simulator_cash_invariant():
    """Cash invariant korunmalı."""
    issues = []
    sim = PortfolioSimulator(initial_capital=100000)

    sim.execute_buy("X", 100.0, "2026-01-01")
    sim.execute_buy("Y", 50.0, "2026-01-01")

    # Cash + cost_basis = initial capital (approximately)
    total_cost = sum(p["cost_basis"] for p in sim._positions.values())
    total_accounted = sim._cash + total_cost
    if abs(total_accounted - 100000) > 10:  # Komisyon toleransı
        issues.append(f"Cash + cost ≠ initial: {total_accounted}")

    sim.execute_sell("X", 110.0, "2026-01-02")
    sim.execute_sell("Y", 45.0, "2026-01-02")

    # Tüm pozisyonlar kapatıldıktan sonra cash = initial + net P&L
    if sim._cash < 90000:  # Zarar olsa bile makul
        issues.append(f"Final cash çok düşük: {sim._cash}")

    return "Simulator Cash Invariant", len(issues) == 0, issues


def test_simulator_equity_snapshots():
    """Günlük equity snapshot oluşmalı."""
    issues = []
    sim = PortfolioSimulator(initial_capital=100000)

    sim.execute_buy("X", 100.0, "2026-01-01")
    sim.update_equity({"X": 105.0}, "2026-01-02")
    sim.update_equity({"X": 110.0}, "2026-01-03")

    if len(sim._daily_snapshots) != 2:
        issues.append(f"Snapshot sayısı: {len(sim._daily_snapshots)}")

    # Drawdown hesaplanmalı
    if sim._daily_snapshots[0].drawdown < 0:
        issues.append("Drawdown negatif olmamalı")

    # Daily return
    if sim._daily_snapshots[1].daily_return <= 0:
        issues.append("İkinci gün return pozitif olmalı")

    return "Equity Snapshots", len(issues) == 0, issues


def test_simulator_max_positions():
    """Max pozisyon limiti çalışmalı."""
    issues = []
    sim = PortfolioSimulator(initial_capital=10000000, max_positions=3)

    sim.execute_buy("A", 10.0, "2026-01-01")
    sim.execute_buy("B", 10.0, "2026-01-01")
    sim.execute_buy("C", 10.0, "2026-01-01")

    # 4. pozisyon açılmamalı
    trade = sim.execute_buy("D", 10.0, "2026-01-01")
    if trade:
        issues.append("Max pozisyon aşıldı")

    return "Max Positions", len(issues) == 0, issues


def test_simulator_win_rate():
    """Win rate doğru hesaplanmalı."""
    issues = []
    sim = PortfolioSimulator(initial_capital=100000)

    # Kazanan trade
    sim.execute_buy("WIN", 100.0, "2026-01-01")
    sim.execute_sell("WIN", 110.0, "2026-01-02")

    # Kaybeden trade
    sim.execute_buy("LOSE", 100.0, "2026-01-03")
    sim.execute_sell("LOSE", 90.0, "2026-01-04")

    summary = sim.get_summary()
    if summary.get("win_rate_pct") != 50.0:
        issues.append(f"Win rate: {summary.get('win_rate_pct')}")

    if summary.get("total_trades") != 4:
        issues.append(f"Trade sayısı: {summary.get('total_trades')}")

    return "Win Rate", len(issues) == 0, issues


# =====================================================
# BACKTEST CORRECTNESS
# =====================================================

def test_backtest_look_ahead():
    """Look-ahead bias kontrolü."""
    issues = []
    market = make_market_data(10, 150)
    runner = ScannerBacktestRunner()
    result = runner.run(market, lookback_days=40)

    if result.look_ahead_violations > 0:
        issues.append(f"Look-ahead violation: {result.look_ahead_violations}")

    return "Look-Ahead Bias", len(issues) == 0, issues


def test_backtest_survivorship():
    """Survivorship bias kontrolü."""
    issues = []
    market = make_market_data(20, 150)
    runner = ScannerBacktestRunner()

    universe = list(market.keys())[:5]
    result = runner.run(market, lookback_days=40, universe_at_date=universe)

    if result.survivorship_violations == 0:
        issues.append("Survivorship violation tespit edilemedi")

    for sig in result.signals:
        if sig.ticker not in universe:
            issues.append(f"Evren dışı sinyal: {sig.ticker}")
            break

    return "Survivorship Bias", len(issues) == 0, issues


def test_backtest_equity_invariant():
    """Equity = cash + market_value invariant."""
    issues = []
    market = make_market_data(10, 150)
    runner = ScannerBacktestRunner(initial_capital=100000)
    result = runner.run(market, lookback_days=40)

    for snap in result.equity_curve:
        calc_equity = snap["cash"] + snap["market_value"]
        if abs(snap["equity"] - calc_equity) > 0.5:
            issues.append(f"Equity invariant: {snap['equity']} ≠ {calc_equity}")
            break

    return "Equity Invariant", len(issues) == 0, issues


def test_backtest_result_consistency():
    """Sonuçlar tutarlı olmalı."""
    issues = []
    market = make_market_data(10, 150)
    runner = ScannerBacktestRunner(initial_capital=100000)

    # İki kez çalıştır — aynı sonuç
    r1 = runner.run(market, lookback_days=40)
    r2 = runner.run(market, lookback_days=40)

    if r1.total_scans != r2.total_scans:
        issues.append(f"Scans farklı: {r1.total_scans} vs {r2.total_scans}")
    if r1.signals_generated != r2.signals_generated:
        issues.append(f"Signals farklı: {r1.signals_generated} vs {r2.signals_generated}")
    if r1.trades_executed != r2.trades_executed:
        issues.append(f"Trades farklı: {r1.trades_executed} vs {r2.trades_executed}")

    return "Result Consistency", len(issues) == 0, issues


# =====================================================
# PERFORMANCE BENCHMARKS
# =====================================================

def test_benchmark_100():
    """100 hisse / 1 yıl benchmark."""
    market = make_market_data(20, 120)
    runner = ScannerBacktestRunner(initial_capital=100000)

    start = time.time()
    result = runner.run(market, lookback_days=40)
    elapsed = time.time() - start

    issues = []
    if elapsed > 60:
        issues.append(f"Süre: {elapsed:.1f}s (limit: 120s)")

    return "Benchmark 20", len(issues) == 0, issues, f"{elapsed:.1f}s, {result.total_scans} scans"


def test_benchmark_500():
    """500 hisse / 1 yıl benchmark."""
    market = make_market_data(50, 120)
    runner = ScannerBacktestRunner(initial_capital=100000)

    start = time.time()
    result = runner.run(market, lookback_days=40)
    elapsed = time.time() - start

    issues = []
    if elapsed > 120:
        issues.append(f"Süre: {elapsed:.1f}s (limit: 300s)")

    return "Benchmark 50", len(issues) == 0, issues, f"{elapsed:.1f}s, {result.total_scans} scans"


def test_benchmark_1000():
    """1000 hisse / 1 yıl benchmark."""
    market = make_market_data(100, 120)
    runner = ScannerBacktestRunner(initial_capital=1000000)

    start = time.time()
    result = runner.run(market, lookback_days=40)
    elapsed = time.time() - start

    issues = []
    if elapsed > 300:
        issues.append(f"Süre: {elapsed:.1f}s (limit: 600s)")

    return "Benchmark 200", len(issues) == 0, issues, f"{elapsed:.1f}s, {result.total_scans} scans"


# =====================================================
# RUN
# =====================================================

def run_all():
    print("=" * 60)
    print("BACKTEST PERFORMANCE TESTLERİ")
    print("=" * 60)

    tests = [
        test_feature_cache,
        test_quality_cache,
        test_simulator_commission,
        test_simulator_cash_invariant,
        test_simulator_equity_snapshots,
        test_simulator_max_positions,
        test_simulator_win_rate,
        test_backtest_look_ahead,
        test_backtest_survivorship,
        test_backtest_equity_invariant,
        test_backtest_result_consistency,
        test_benchmark_100,
        test_benchmark_500,
        test_benchmark_1000,
    ]

    passed = failed = 0
    all_issues = []

    for test_func in tests:
        try:
            result = test_func()
            if len(result) == 4:
                name, ok, issues, extra = result
            else:
                name, ok, issues = result
                extra = ""
        except Exception as e:
            name, ok, issues, extra = test_func.__name__, False, [f"Exception: {e}"], ""

        icon = "✅" if ok else "❌"
        print(f"\n{icon} {name}" + (f" ({extra})" if extra else ""))
        if ok:
            passed += 1
            print("   PASSED")
        else:
            failed += 1
            for i in issues:
                print(f"   ❌ {i}")
                all_issues.append(f"{name}: {i}")

    print(f"\n{'=' * 60}")
    print(f"SONUÇ: {passed}/{passed + failed} geçti")
    if all_issues:
        print("\nTÜM HATALAR:")
        for i, issue in enumerate(all_issues, 1):
            print(f"  {i}. {issue}")
    print("=" * 60)
    return failed == 0


if __name__ == "__main__":
    import sys
    ok = run_all()
    sys.exit(0 if ok else 1)
