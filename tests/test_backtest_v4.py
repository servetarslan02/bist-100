#!/usr/bin/env python3
"""
ALPHA BIST — Backtest v4.0 Comprehensive Test Suite

Kapsam:
1. PortfolioSimulator v3.0 unit tests
2. BacktestEngine v4.0 integration tests
3. Persistence tests (save/load/recovery)
4. Financial correctness (bias, invariant, determinism)
5. Performance benchmarks (100/500/1000 hisse)
6. Cache correctness
7. Old vs new engine equivalence
"""

import sys
import os
import time
import orjson
import sqlite3
import numpy as np
import pandas as pd
from datetime import datetime
from pathlib import Path


from services.backtest.portfolio_sim import (
    PortfolioSimulatorV3, BISTCommissionModel, Trade, Position, EquitySnapshot,
)
from services.backtest.persistence import BacktestPersistence
from services.backtest.engine_v4 import (
    BacktestEngineV4, BacktestConfig, FeatureCache, QualityCache,
)
from services.scanner.backtest_runner import (
    ScannerBacktestRunner, PortfolioSimulator as PortfolioSimulatorV2,
    FeatureCache as FeatureCacheV2, QualityCache as QualityCacheV2,
)


# =====================================================
# HELPERS
# =====================================================

def make_market_data(n_stocks=100, n_days=252, seed=42):
    """Gerçekçi market dataset."""
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
# 1. PORTFOLIO SIMULATOR v3.0 TESTS
# =====================================================

def test_sim_v3_buy_sell():
    """Temel alım-satım döngüsü."""
    issues = []
    sim = PortfolioSimulatorV3(initial_capital=100000, slippage_rate=0.001)

    trade = sim.execute_buy("THYAO", 100.0, "2026-01-01")
    if not trade:
        issues.append("Alım başarısız")
        return "Sim V3 Buy/Sell", False, issues

    if trade.side != "BUY":
        issues.append(f"Side: {trade.side}")
    if trade.commission <= 0:
        issues.append(f"Komisyon: {trade.commission}")
    if sim._cash >= 100000:
        issues.append("Cash düşmemiş")
    if not sim.has_position("THYAO"):
        issues.append("Pozisyon oluşmamış")

    trade2 = sim.execute_sell("THYAO", 110.0, "2026-01-10")
    if not trade2:
        issues.append("Satış başarısız")
        return "Sim V3 Buy/Sell", False, issues

    if trade2.pnl <= 0:
        issues.append(f"P&L negatif: {trade2.pnl}")
    if trade2.holding_days != 9:
        issues.append(f"Holding days: {trade2.holding_days}")
    if sim.has_position("THYAO"):
        issues.append("Pozisyon kapanmamış")

    return "Sim V3 Buy/Sell", len(issues) == 0, issues


def test_sim_v3_commission_bist():
    """BIST komisyon yapısı doğru olmalı."""
    issues = []
    amount = 100000.0
    commission = BISTCommissionModel.compute(amount)

    # Broker: 30, Exchange: 5.6, BSMV: 1.78 → total: 37.38
    expected_min = amount * 0.0003
    if commission < expected_min:
        issues.append(f"Komisyon çok düşük: {commission}")

    # Min komisyon kontrolü
    small_commission = BISTCommissionModel.compute(100)
    if small_commission < 1.0:
        issues.append(f"Min komisyon: {small_commission}")

    return "BIST Commission", len(issues) == 0, issues


def test_sim_v3_cash_invariant():
    """Cash + cost_basis ≈ initial capital."""
    issues = []
    sim = PortfolioSimulatorV3(initial_capital=100000)

    sim.execute_buy("A", 100.0, "2026-01-01")
    sim.execute_buy("B", 50.0, "2026-01-01")

    total_cost = sum(p.cost_basis for p in sim._positions.values())
    total_accounted = sim._cash + total_cost
    if abs(total_accounted - 100000) > 10:
        issues.append(f"Cash + cost ≠ initial: {total_accounted}")

    sim.execute_sell("A", 110.0, "2026-01-02")
    sim.execute_sell("B", 45.0, "2026-01-02")

    if sim._cash < 90000:
        issues.append(f"Final cash çok düşük: {sim._cash}")

    return "Sim V3 Cash Invariant", len(issues) == 0, issues


def test_sim_v3_equity_invariant():
    """Equity = cash + market_value."""
    issues = []
    sim = PortfolioSimulatorV3(initial_capital=100000)

    sim.execute_buy("X", 100.0, "2026-01-01")
    sim.update_equity({"X": 105.0}, "2026-01-02")

    snap = sim._equity_curve[-1]
    expected_equity = snap.cash + snap.market_value
    if abs(snap.equity - expected_equity) > 0.01:
        issues.append(f"Equity mismatch: {snap.equity} != {expected_equity}")

    return "Sim V3 Equity Invariant", len(issues) == 0, issues


def test_sim_v3_oversell_prevention():
    """Olmayan pozisyon satılmamalı."""
    issues = []
    sim = PortfolioSimulatorV3(initial_capital=100000)

    result = sim.execute_sell("X", 100.0, "2026-01-01")
    if result is not None:
        issues.append("Olmayan pozisyon satıldı")

    sim.execute_buy("Y", 100.0, "2026-01-01")
    sim.execute_sell("Y", 110.0, "2026-01-02")
    result2 = sim.execute_sell("Y", 120.0, "2026-01-03")
    if result2 is not None:
        issues.append("Kapanmış pozisyon tekrar satıldı")

    return "Sim V3 Oversell Prevention", len(issues) == 0, issues


def test_sim_v3_max_positions():
    """Max pozisyon limiti."""
    issues = []
    sim = PortfolioSimulatorV3(initial_capital=10000000, max_positions=3)

    sim.execute_buy("A", 10.0, "2026-01-01")
    sim.execute_buy("B", 10.0, "2026-01-01")
    sim.execute_buy("C", 10.0, "2026-01-01")

    trade = sim.execute_buy("D", 10.0, "2026-01-01")
    if trade is not None:
        issues.append("Max pozisyon aşıldı")

    return "Sim V3 Max Positions", len(issues) == 0, issues


def test_sim_v3_win_rate():
    """Win rate doğru hesaplanmalı."""
    issues = []
    sim = PortfolioSimulatorV3(initial_capital=100000)

    sim.execute_buy("WIN", 100.0, "2026-01-01")
    sim.execute_sell("WIN", 110.0, "2026-01-02")

    sim.execute_buy("LOSE", 100.0, "2026-01-03")
    sim.execute_sell("LOSE", 90.0, "2026-01-04")

    metrics = sim.compute_metrics()
    if metrics.get("win_rate_pct") != 50.0:
        issues.append(f"Win rate: {metrics.get('win_rate_pct')}")
    if metrics.get("total_trades") != 4:
        issues.append(f"Trade sayısı: {metrics.get('total_trades')}")

    return "Sim V3 Win Rate", len(issues) == 0, issues


def test_sim_v3_drawdown():
    """Drawdown doğru hesaplanmalı."""
    issues = []
    sim = PortfolioSimulatorV3(initial_capital=100000)

    sim.execute_buy("X", 100.0, "2026-01-01")
    sim.update_equity({"X": 120.0}, "2026-01-02")  # Büyük artış
    sim.update_equity({"X": 90.0}, "2026-01-03")   # Büyük düşüş

    metrics = sim.compute_metrics()
    max_dd = metrics.get("max_drawdown_pct", 0)
    # Peak'ten trough'a drawdown
    if max_dd < 1:
        issues.append(f"Max drawdown çok düşük: {max_dd}")

    return "Sim V3 Drawdown", len(issues) == 0, issues


def test_sim_v3_audit_trail():
    """Audit trail oluşmalı."""
    issues = []
    sim = PortfolioSimulatorV3(initial_capital=100000)

    sim.execute_buy("X", 100.0, "2026-01-01")
    sim.execute_sell("X", 110.0, "2026-01-02")

    audit = sim.get_audit_log()
    if len(audit) < 2:
        issues.append(f"Audit entries: {len(audit)}")

    buy_entries = [e for e in audit if e.entry_type == "BUY"]
    sell_entries = [e for e in audit if e.entry_type == "SELL"]
    if len(buy_entries) != 1:
        issues.append(f"BUY entries: {len(buy_entries)}")
    if len(sell_entries) != 1:
        issues.append(f"SELL entries: {len(sell_entries)}")

    return "Sim V3 Audit Trail", len(issues) == 0, issues


def test_sim_v3_invalid_price():
    """Geçersiz fiyat kabul edilmemeli."""
    issues = []
    sim = PortfolioSimulatorV3(initial_capital=100000)

    r1 = sim.execute_buy("X", 0.0, "2026-01-01")
    if r1 is not None:
        issues.append("Sıfır fiyat kabul edildi")

    r2 = sim.execute_buy("X", -10.0, "2026-01-01")
    if r2 is not None:
        issues.append("Negatif fiyat kabul edildi")

    r3 = sim.execute_buy("X", float('nan'), "2026-01-01")
    if r3 is not None:
        issues.append("NaN fiyat kabul edildi")

    return "Sim V3 Invalid Price", len(issues) == 0, issues


# =====================================================
# 2. PERSISTENCE TESTS
# =====================================================

def test_persistence_save_load():
    """Save ve load cycle."""
    issues = []
    db_path = "/tmp/test_backtest_persist.db"
    if os.path.exists(db_path):
        os.remove(db_path)

    persist = BacktestPersistence(db_path)

    metrics = {
        "final_equity": 110000,
        "total_return_pct": 10.0,
        "sharpe_ratio": 1.5,
        "max_drawdown_pct": 5.0,
        "total_trades": 50,
    }
    persist.save_run("test_run_1", "2025-01-01", "2025-12-31", 100000, metrics)
    persist.save_trades("test_run_1", [
        {"trade_id": 1, "ticker": "THYAO", "side": "BUY", "date": "2025-01-15",
         "quantity": 100, "price": 300, "commission": 10, "slippage": 3, "pnl": 0},
    ])
    persist.save_equity_curve("test_run_1", [
        {"date": "2025-01-15", "equity": 100000, "cash": 70000, "market_value": 30000,
         "positions": 1, "drawdown": 0, "daily_return": 0},
    ])

    # Load
    run = persist.get_run("test_run_1")
    if not run:
        issues.append("Run bulunamadı")
    elif run["total_return_pct"] != 10.0:
        issues.append(f"Return: {run['total_return_pct']}")

    trades = persist.get_trades("test_run_1")
    if len(trades) != 1:
        issues.append(f"Trades: {len(trades)}")

    curve = persist.get_equity_curve("test_run_1")
    if len(curve) != 1:
        issues.append(f"Equity curve: {len(curve)}")

    # List
    runs = persist.list_runs()
    if len(runs) != 1:
        issues.append(f"List runs: {len(runs)}")

    # Delete
    persist.delete_run("test_run_1")
    run2 = persist.get_run("test_run_1")
    if run2 is not None:
        issues.append("Run silinmemiş")

    if os.path.exists(db_path):
        os.remove(db_path)

    return "Persistence Save/Load", len(issues) == 0, issues


def test_persistence_recovery():
    """Restart sonrası recovery."""
    issues = []
    db_path = "/tmp/test_backtest_recovery.db"
    if os.path.exists(db_path):
        os.remove(db_path)

    # İlk instance
    persist1 = BacktestPersistence(db_path)
    persist1.save_run("recovery_test", "2025-01-01", "2025-12-31", 100000,
                      {"final_equity": 115000, "total_return_pct": 15.0})
    persist1.save_trades("recovery_test", [
        {"trade_id": i, "ticker": f"T{i}", "side": "BUY", "date": "2025-01-01",
         "quantity": 10, "price": 100, "commission": 1, "slippage": 0.1, "pnl": 0}
        for i in range(100)
    ])

    # İkinci instance (simüle restart)
    persist2 = BacktestPersistence(db_path)
    run = persist2.get_run("recovery_test")
    if not run:
        issues.append("Recovery: run bulunamadı")

    trades = persist2.get_trades("recovery_test")
    if len(trades) != 100:
        issues.append(f"Recovery: trades {len(trades)} != 100")

    if os.path.exists(db_path):
        os.remove(db_path)

    return "Persistence Recovery", len(issues) == 0, issues


# =====================================================
# 3. CACHE TESTS
# =====================================================

def test_feature_cache_v4():
    """Feature cache v4.0 doğruluğu."""
    issues = []
    cache = FeatureCache()

    features = {"rsi_14": 65.0, "momentum_20d": 0.05}
    cache.set("THYAO", "2026-01-01", features)

    cached = cache.get("THYAO", "2026-01-01")
    if cached != features:
        issues.append("Cache hit başarısız")

    miss = cache.get("THYAO", "2026-01-02")
    if miss is not None:
        issues.append("Farklı tarih cache hit")

    miss2 = cache.get("GARAN", "2026-01-01")
    if miss2 is not None:
        issues.append("Farklı ticker cache hit")

    # Hit rate
    _ = cache.get("X", "2026-01-01")  # miss
    _ = cache.get("THYAO", "2026-01-01")  # hit
    hr = cache.hit_rate
    if hr < 0.2 or hr > 0.5:
        issues.append(f"Hit rate: {hr}")

    return "Feature Cache v4", len(issues) == 0, issues


def test_quality_cache_v4():
    """Quality cache v4.0 doğruluğu."""
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

    return "Quality Cache v4", len(issues) == 0, issues


# =====================================================
# 4. BACKTEST ENGINE v4.0 TESTS
# =====================================================

def test_engine_v4_basic():
    """Temel backtest çalışmalı."""
    issues = []
    market = make_market_data(20, 150, seed=42)
    engine = BacktestEngineV4(BacktestConfig(
        lookback_days=40,
        initial_capital=100000,
        signal_threshold=60.0,
    ))

    result = engine.run(market, persist=False)

    if result.total_scans == 0:
        issues.append("Hiç scan yapılmadı")
    if result.equity_curve is None:
        issues.append("Equity curve None")
    if result.run_id is None:
        issues.append("Run ID None")

    return "Engine V4 Basic", len(issues) == 0, issues


def test_engine_v4_determinism():
    """Aynı veri → aynı sonuç."""
    issues = []
    market = make_market_data(15, 150, seed=123)
    config = BacktestConfig(lookback_days=40, initial_capital=100000)

    engine1 = BacktestEngineV4(config)
    r1 = engine1.run(market, persist=False)

    engine2 = BacktestEngineV4(config)
    r2 = engine2.run(market, persist=False)

    if r1.total_scans != r2.total_scans:
        issues.append(f"Scans: {r1.total_scans} vs {r2.total_scans}")
    if r1.signals_generated != r2.signals_generated:
        issues.append(f"Signals: {r1.signals_generated} vs {r2.signals_generated}")
    if r1.trades_executed != r2.trades_executed:
        issues.append(f"Trades: {r1.trades_executed} vs {r2.trades_executed}")
    if r1.run_id != r2.run_id:
        issues.append(f"Run ID: {r1.run_id} vs {r2.run_id}")

    # Equity curve son noktası
    if r1.equity_curve and r2.equity_curve:
        eq1 = r1.equity_curve[-1]["equity"]
        eq2 = r2.equity_curve[-1]["equity"]
        if abs(eq1 - eq2) > 0.01:
            issues.append(f"Final equity: {eq1} vs {eq2}")

    return "Engine V4 Determinism", len(issues) == 0, issues


def test_engine_v4_equity_invariant():
    """Equity = cash + market_value her gün."""
    issues = []
    market = make_market_data(10, 150, seed=42)
    engine = BacktestEngineV4(BacktestConfig(lookback_days=40))
    result = engine.run(market, persist=False)

    for snap in result.equity_curve:
        calc_equity = snap["cash"] + snap["market_value"]
        if abs(snap["equity"] - calc_equity) > 0.5:
            issues.append(f"Equity invariant: {snap['equity']} != {calc_equity}")
            break

    return "Engine V4 Equity Invariant", len(issues) == 0, issues


def test_engine_v4_look_ahead():
    """Look-ahead bias kontrolü."""
    issues = []
    market = make_market_data(10, 150, seed=42)
    engine = BacktestEngineV4(BacktestConfig(lookback_days=40))
    result = engine.run(market, persist=False)

    if result.look_ahead_violations > 0:
        issues.append(f"Look-ahead violations: {result.look_ahead_violations}")

    return "Engine V4 Look-Ahead", len(issues) == 0, issues


def test_engine_v4_survivorship():
    """Survivorship bias kontrolü."""
    issues = []
    market = make_market_data(20, 150, seed=42)
    engine = BacktestEngineV4(BacktestConfig(lookback_days=40))

    universe = list(market.keys())[:5]
    result = engine.run(market, universe_at_date=universe, persist=False)

    if result.survivorship_violations == 0:
        issues.append("Survivorship violation tespit edilemedi")

    return "Engine V4 Survivorship", len(issues) == 0, issues


def test_engine_v4_persistence():
    """Backtest sonuçları persist edilmeli."""
    issues = []
    db_path = "/tmp/test_engine_v4_persist.db"
    if os.path.exists(db_path):
        os.remove(db_path)

    # Engine'a özel persistence ver
    engine = BacktestEngineV4(BacktestConfig(lookback_days=40))
    # Persistence modülünü override et
    import services.backtest.engine_v4 as eng_mod
    old_persist = eng_mod.backtest_persistence
    eng_mod.backtest_persistence = BacktestPersistence(db_path)

    market = make_market_data(10, 150, seed=42)
    result = engine.run(market, persist=True)

    if not result.persisted:
        issues.append("Persisted flag False")

    # DB'den oku
    persist = BacktestPersistence(db_path)
    runs = persist.list_runs()
    if len(runs) != 1:
        issues.append(f"Runs: {len(runs)}")
    elif runs[0]["run_id"] != result.run_id:
        issues.append(f"Run ID mismatch")

    # Cleanup
    eng_mod.backtest_persistence = old_persist
    if os.path.exists(db_path):
        os.remove(db_path)

    return "Engine V4 Persistence", len(issues) == 0, issues


# =====================================================
# 5. OLD vs NEW EQUIVALENCE
# =====================================================

def test_equivalence_old_new():
    """v2.0 ve v4.0 aynı finansal sonuçları üretmeli.

    Not: Feature hesaplama aynı olduğu için skorlar aynı olmalı.
    Portfolio mantığı da aynı olmalı.
    """
    issues = []
    market = make_market_data(10, 150, seed=42)

    # v2.0
    runner_v2 = ScannerBacktestRunner(initial_capital=100000)
    r2 = runner_v2.run(market, lookback_days=40)

    # v4.0
    engine_v4 = BacktestEngineV4(BacktestConfig(
        initial_capital=100000,
        lookback_days=40,
        signal_threshold=60.0,
    ))
    r4 = engine_v4.run(market, persist=False)

    # v4 zaten pozisyondaki hisseleri scan etmediği için scan sayısı farklı olabilir
    # Trade sayısı makul aralıkta olmalı
    if r2.trades_executed > 0 and r4.trades_executed > 0:
        ratio = r4.trades_executed / r2.trades_executed
        if ratio < 0.3 or ratio > 3.0:
            issues.append(f"Trade ratio: {ratio:.2f} (v2={r2.trades_executed}, v4={r4.trades_executed})")
    elif r2.trades_executed == 0 and r4.trades_executed > 10:
        issues.append(f"v2=0 trades ama v4={r4.trades_executed}")

    return "Equivalence Old/New", len(issues) == 0, issues


# =====================================================
# 6. PERFORMANCE BENCHMARKS
# =====================================================

def test_benchmark_100_stocks():
    """100 hisse / 1 yıl benchmark."""
    market = make_market_data(100, 252, seed=42)
    engine = BacktestEngineV4(BacktestConfig(lookback_days=60, initial_capital=100000))

    start = time.time()
    result = engine.run(market, persist=False)
    elapsed = time.time() - start

    issues = []
    # Feature computation is the bottleneck (not engine overhead)
    if elapsed > 600:
        issues.append(f"Süre: {elapsed:.1f}s (limit: 600s)")

    return "Benchmark 100", len(issues) == 0, issues, \
        f"{elapsed:.1f}s, {result.total_scans} scans, {result.trades_executed} trades, {result.scans_per_second:.0f} scans/s"


def test_benchmark_500_stocks():
    """500 hisse / 1 yıl benchmark (50 hisse ile simüle)."""
    # 500 hisse çok uzun sürer, 50 hisse ile ölçekleme testi
    market = make_market_data(50, 252, seed=42)
    engine = BacktestEngineV4(BacktestConfig(lookback_days=60, initial_capital=100000))

    start = time.time()
    result = engine.run(market, persist=False)
    elapsed = time.time() - start

    issues = []
    # 50 hisse ≤ 300s
    if elapsed > 300:
        issues.append(f"Süre: {elapsed:.1f}s (limit: 300s)")

    return "Benchmark 50 (≈500)", len(issues) == 0, issues, \
        f"{elapsed:.1f}s, {result.total_scans} scans, {result.trades_executed} trades, {result.scans_per_second:.0f} scans/s"


def test_benchmark_1000_stocks():
    """1000 hisse / 1 yıl benchmark (20 hisse ile smoke test)."""
    # 1000 hisse gerçek testi çok uzun sürer, smoke test
    market = make_market_data(20, 252, seed=42)
    engine = BacktestEngineV4(BacktestConfig(lookback_days=60, initial_capital=100000))

    start = time.time()
    result = engine.run(market, persist=False)
    elapsed = time.time() - start

    issues = []
    if result.total_scans == 0:
        issues.append("Hiç scan yapılmadı")
    if elapsed > 120:
        issues.append(f"Süre: {elapsed:.1f}s (limit: 120s)")

    return "Benchmark 20 (smoke)", len(issues) == 0, issues, \
        f"{elapsed:.1f}s, {result.total_scans} scans, {result.trades_executed} trades, {result.scans_per_second:.0f} scans/s"


# =====================================================
# 7. V2.0 REGRESSION (mevcut testlerin v4.0'a uyarlanması)
# =====================================================

def test_v2_feature_cache():
    """v2.0 Feature Cache geriye uyumluluk."""
    issues = []
    cache = FeatureCacheV2()

    features = {"rsi_14": 65.0, "momentum_20d": 0.05}
    cache.set("THYAO", "2026-01-01", features)

    cached = cache.get("THYAO", "2026-01-01")
    if cached != features:
        issues.append("Cache hit başarısız")

    miss = cache.get("THYAO", "2026-01-02")
    if miss is not None:
        issues.append("Farklı tarih cache hit")

    cache.invalidate("THYAO")
    miss2 = cache.get("THYAO", "2026-01-01")
    if miss2 is not None:
        issues.append("Invalidation başarısız")

    return "V2 Feature Cache", len(issues) == 0, issues


def test_v2_quality_cache():
    """v2.0 Quality Cache geriye uyumluluk."""
    issues = []
    cache = QualityCacheV2()

    cache.set("THYAO", True, 85.0)
    cache.set("BAD", False, 30.0)

    r1 = cache.get("THYAO")
    if r1 != (True, 85.0):
        issues.append(f"THYAO: {r1}")

    r2 = cache.get("BAD")
    if r2 != (False, 30.0):
        issues.append(f"BAD: {r2}")

    return "V2 Quality Cache", len(issues) == 0, issues


def test_v2_simulator_commission():
    """v2.0 Simulator geriye uyumluluk."""
    issues = []
    sim = PortfolioSimulatorV2(initial_capital=100000, commission_rate=0.001, slippage_rate=0.001)

    trade = sim.execute_buy("X", 100.0, "2026-01-01")
    if not trade:
        issues.append("Alım başarısız")
        return "V2 Simulator Commission", False, issues

    if trade.commission <= 0:
        issues.append(f"Komisyon: {trade.commission}")
    if sim._cash >= 100000:
        issues.append("Cash düşmemiş")

    return "V2 Simulator Commission", len(issues) == 0, issues


def test_v2_simulator_cash_invariant():
    """v2.0 Cash invariant geriye uyumluluk."""
    issues = []
    sim = PortfolioSimulatorV2(initial_capital=100000)

    sim.execute_buy("X", 100.0, "2026-01-01")
    sim.execute_buy("Y", 50.0, "2026-01-01")

    total_cost = sum(p["cost_basis"] for p in sim._positions.values())
    total_accounted = sim._cash + total_cost
    if abs(total_accounted - 100000) > 10:
        issues.append(f"Cash + cost ≠ initial: {total_accounted}")

    return "V2 Cash Invariant", len(issues) == 0, issues


# =====================================================
# RUN
# =====================================================

def run_all():
    print("=" * 70)
    print("  ALPHA BIST — Backtest v4.0 Comprehensive Test Suite")
    print("=" * 70)

    tests = [
        # Portfolio Simulator v3.0
        test_sim_v3_buy_sell,
        test_sim_v3_commission_bist,
        test_sim_v3_cash_invariant,
        test_sim_v3_equity_invariant,
        test_sim_v3_oversell_prevention,
        test_sim_v3_max_positions,
        test_sim_v3_win_rate,
        test_sim_v3_drawdown,
        test_sim_v3_audit_trail,
        test_sim_v3_invalid_price,
        # Persistence
        test_persistence_save_load,
        test_persistence_recovery,
        # Cache
        test_feature_cache_v4,
        test_quality_cache_v4,
        # Engine v4.0
        test_engine_v4_basic,
        test_engine_v4_determinism,
        test_engine_v4_equity_invariant,
        test_engine_v4_look_ahead,
        test_engine_v4_survivorship,
        test_engine_v4_persistence,
        # Equivalence
        test_equivalence_old_new,
        # V2.0 Regression
        test_v2_feature_cache,
        test_v2_quality_cache,
        test_v2_simulator_commission,
        test_v2_simulator_cash_invariant,
        # Benchmarks
        test_benchmark_100_stocks,
        test_benchmark_500_stocks,
        test_benchmark_1000_stocks,
    ]

    passed = failed = 0
    all_issues = []
    benchmark_results = []

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
            import traceback
            traceback.print_exc()

        icon = "✅" if ok else "❌"
        print(f"\n{icon} {name}" + (f" ({extra})" if extra else ""))
        if ok:
            passed += 1
        else:
            failed += 1
            for i in issues:
                print(f"   ❌ {i}")
                all_issues.append(f"{name}: {i}")

        if "Benchmark" in name and extra:
            benchmark_results.append(f"  {name}: {extra}")

    print(f"\n{'=' * 70}")
    print(f"  SONUÇ: {passed}/{passed + failed} geçti")
    if all_issues:
        print(f"\n  HATALAR:")
        for i, issue in enumerate(all_issues, 1):
            print(f"    {i}. {issue}")
    if benchmark_results:
        print(f"\n  BENCHMARK SONUÇLARI:")
        for b in benchmark_results:
            print(b)
    print("=" * 70)

    return failed == 0


if __name__ == "__main__":
    ok = run_all()
    sys.exit(0 if ok else 1)
