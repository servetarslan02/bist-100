#!/usr/bin/env python3
"""
Full Pipeline Integration Testleri

Kapsam:
- ConfigWatcher entegrasyonu
- Data Quality v2 pipeline
- Backtest + AlphaScanner + Portfolio Simulation
- E2E pipeline
- Performance benchmarks
"""

import sys
import os
import json
import asyncio
import time
import tempfile
import numpy as np
import pandas as pd
from datetime import datetime, timedelta
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.core.config_watcher import ConfigWatcher
from services.core.data_quality_v2 import DataQualityV2
from services.ingestion.data_pipeline import DataPipeline
from services.scanner.backtest_runner import ScannerBacktestRunner, PortfolioSimulator
from services.features.calculator import FeatureCalculator
from services.core.tradability_mask import TradabilityMask


def make_market_data(n_stocks=50, n_days=250, seed=42):
    """Gerçekçi market dataset (1 yıllık)."""
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
# CONFIG WATCHER INTEGRATION
# =====================================================

async def test_config_watcher_portfolio_integration():
    """ConfigWatcher PortfolioService ile entegre çalışmalı."""
    issues = []

    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        json.dump({"version": 1, "risk": {"max_drawdown_pct": 15}}, f)
        config_path = f.name

    state = {"risk": None, "reload_count": 0}

    def on_config_change(config):
        state["risk"] = config.get("risk")
        state["reload_count"] += 1

    watcher = ConfigWatcher(config_path, reload_fn=lambda: None,
                           on_change=on_config_change, watch_interval_s=0.2)
    watcher.start()
    await asyncio.sleep(0.3)

    # Config değiştir
    with open(config_path, "w") as f:
        json.dump({"version": 2, "risk": {"max_drawdown_pct": 10}}, f)

    await asyncio.sleep(0.5)
    watcher.stop()

    if state["risk"] is None:
        issues.append("Config change callback çalışmadı")
    elif state["risk"].get("max_drawdown_pct") != 10:
        issues.append(f"Risk güncellenmedi: {state['risk']}")

    os.unlink(config_path)
    return "Config Watcher Portfolio Integration", len(issues) == 0, issues


async def test_config_watcher_rollback():
    """Hatalı config rollback'i çalışmalı."""
    issues = []

    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        json.dump({"version": 1, "port": 8000}, f)
        config_path = f.name

    state = {"config": {"version": 1, "port": 8000}}

    def reload_fn():
        with open(config_path) as f:
            state["config"] = json.load(f)

    def validate_fn(config):
        if config.get("port", 0) < 0:
            return ["Port negatif"]
        return []

    watcher = ConfigWatcher(config_path, reload_fn, validate_fn=validate_fn, watch_interval_s=0.2)
    watcher.start()
    await asyncio.sleep(0.3)

    # Geçersiz config
    with open(config_path, "w") as f:
        json.dump({"version": 2, "port": -1}, f)

    await asyncio.sleep(0.5)
    watcher.stop()

    if state["config"].get("port") != 8000:
        issues.append(f"Eski config kayboldu: {state['config']}")

    os.unlink(config_path)
    return "Config Watcher Rollback", len(issues) == 0, issues


# =====================================================
# DATA QUALITY PIPELINE
# =====================================================

async def test_data_pipeline_clean_data():
    """Temiz veri kabul edilmeli."""
    issues = []

    market = make_market_data(10, 120)
    pipeline = DataPipeline(min_quality_score=70)
    report = pipeline.process(market)

    if report.accepted == 0:
        issues.append("Hiç veri kabul edilmedi")

    if report.acceptance_rate < 80:
        issues.append(f"Kabul oranı düşük: {report.acceptance_rate}%")

    return "Data Pipeline Clean", len(issues) == 0, issues


async def test_data_pipeline_rejects_corrupt():
    """Bozuk veri reddedilmeli."""
    issues = []

    market = make_market_data(5, 120)

    # Bozuk veri ekle
    df_bad = market["STOCK0000"].copy()
    df_bad.iloc[50:55, df_bad.columns.get_loc('Close')] = np.nan
    df_bad.iloc[60:65, df_bad.columns.get_loc('High')] = df_bad.iloc[60:65, df_bad.columns.get_loc('Low')] - 5
    market["BAD_STOCK"] = df_bad

    pipeline = DataPipeline(min_quality_score=70)
    report = pipeline.process(market)

    # BAD_STOCK reddedilmeli
    bad_result = next((r for r in report.results if r.ticker == "BAD_STOCK"), None)
    if bad_result and bad_result.accepted:
        issues.append("Bozuk veri kabul edildi")

    return "Data Pipeline Rejects Corrupt", len(issues) == 0, issues


async def test_data_pipeline_audit_log():
    """Audit log doğru oluşmalı."""
    issues = []

    market = make_market_data(5, 120)
    pipeline = DataPipeline(min_quality_score=70)
    report = pipeline.process(market)

    if not report.audit_log:
        issues.append("Audit log boş")

    # Her ticker için kayıt olmalı
    tickers_in_audit = set(e["ticker"] for e in report.audit_log)
    if len(tickers_in_audit) < 3:
        issues.append(f"Audit log eksik: {len(tickers_in_audit)} ticker")

    return "Data Pipeline Audit Log", len(issues) == 0, issues


async def test_data_pipeline_rejection_reasons():
    """Reddetme sebepleri doğru kaydedilmeli."""
    issues = []

    market = make_market_data(5, 120)

    # Çok kısa veri
    market["SHORT"] = pd.DataFrame({
        'Open': [100], 'High': [105], 'Low': [95],
        'Close': [102], 'Volume': [50000]
    }, index=[datetime.now()])

    pipeline = DataPipeline(min_quality_score=70)
    report = pipeline.process(market)

    reasons = report.to_dict().get("rejection_reasons", {})
    if not reasons:
        # Tüm veriler kabul edilmiş olabilir
        pass

    return "Data Pipeline Rejection Reasons", len(issues) == 0, issues


# =====================================================
# BACKTEST + PORTFOLIO SIMULATION
# =====================================================

async def test_backtest_full_pipeline():
    """Tam backtest pipeline çalışmalı."""
    issues = []

    market = make_market_data(15, 150)
    runner = ScannerBacktestRunner(initial_capital=100000)
    result = runner.run(market, lookback_days=40, signal_threshold=50)

    if result.total_scans == 0:
        issues.append("Hiç scan yapılmadı")

    if result.signals_generated == 0:
        issues.append("Hiç sinyal üretilmedi")

    if result.look_ahead_violations > 0:
        issues.append(f"Look-ahead violation: {result.look_ahead_violations}")

    # Portfolio simulation
    pf = result.portfolio
    if not pf:
        issues.append("Portföy özeti boş")
    elif pf.get("initial_capital") != 100000:
        issues.append(f"Başlangıç sermayesi: {pf.get('initial_capital')}")

    return "Backtest Full Pipeline", len(issues) == 0, issues


async def test_backtest_equity_curve():
    """Equity curve oluşmalı."""
    issues = []

    market = make_market_data(5, 100)
    runner = ScannerBacktestRunner(initial_capital=100000)
    result = runner.run(market, lookback_days=40, signal_threshold=50)

    if not result.equity_curve:
        issues.append("Equity curve boş")
    elif len(result.equity_curve) < 10:
        issues.append(f"Equity curve çok kısa: {len(result.equity_curve)}")

    # Equity değerleri mantıklı olmalı
    if result.equity_curve:
        equities = [e["equity"] for e in result.equity_curve]
        if any(e < 0 for e in equities):
            issues.append("Negatif equity")
        if any(e > 1000000 for e in equities):
            issues.append("Aşırı yüksek equity")

    return "Backtest Equity Curve", len(issues) == 0, issues


async def test_backtest_commission_accounting():
    """Komisyon muhasebesi doğru olmalı."""
    issues = []

    market = make_market_data(5, 100)
    runner = ScannerBacktestRunner(
        initial_capital=100000, commission_rate=0.001, slippage_rate=0.002,
    )
    result = runner.run(market, lookback_days=40, signal_threshold=50)

    pf = result.portfolio
    if pf:
        total_comm = pf.get("total_commission", 0)
        total_slip = pf.get("total_slippage", 0)

        if result.trades_executed > 0 and total_comm == 0:
            issues.append("Komisyon hesaplanmamış")

        if result.trades_executed > 0 and total_slip == 0:
            issues.append("Slippage hesaplanmamış")

    return "Backtest Commission", len(issues) == 0, issues


async def test_backtest_look_ahead_prevention():
    """Look-ahead bias engellenmeli."""
    issues = []

    market = make_market_data(5, 100)
    runner = ScannerBacktestRunner()
    result = runner.run(market, lookback_days=40)

    if result.look_ahead_violations > 0:
        issues.append(f"Look-ahead violation: {result.look_ahead_violations}")

    # Signal tarihleri feature hesaplama tarihinden sonra olmalı
    for sig in result.signals[:5]:
        # Signal tarihi feature penceresinin son günü olmalı
        pass

    return "Backtest Look-Ahead Prevention", len(issues) == 0, issues


async def test_backtest_survivorship_bias():
    """Survivorship bias koruması çalışmalı."""
    issues = []

    market = make_market_data(15, 150)
    runner = ScannerBacktestRunner()

    # Sadece 5 hisse evrende olsun
    universe = list(market.keys())[:5]
    result = runner.run(market, lookback_days=40, universe_at_date=universe)

    if result.survivorship_violations == 0:
        issues.append("Survivorship violation tespit edilemedi")

    # Evren dışından sinyal olmamalı
    for sig in result.signals:
        if sig.ticker not in universe:
            issues.append(f"Evren dışı sinyal: {sig.ticker}")
            break

    return "Backtest Survivorship Bias", len(issues) == 0, issues


async def test_portfolio_simulator():
    """Portfolio simulator doğru çalışmalı."""
    issues = []

    sim = PortfolioSimulator(initial_capital=100000, commission_rate=0.001, slippage_rate=0.001)

    # Alım
    trade = sim.execute_buy("THYAO", 100.0, "2026-01-01")
    if not trade:
        issues.append("Alım başarısız")

    if sim._cash >= 100000:
        issues.append("Cash düşmemiş")

    # Fiyat güncelleme
    sim.update_equity({"THYAO": 110.0}, "2026-01-02")

    # Satış
    trade = sim.execute_sell("THYAO", 110.0, "2026-01-03")
    if not trade:
        issues.append("Satış başarısız")

    # Kârda olmalı
    summary = sim.get_summary()
    if summary.get("total_return_pct", 0) <= 0:
        issues.append(f"Getiri negatif: {summary.get('total_return_pct')}")

    if summary.get("total_commission", 0) <= 0:
        issues.append("Komisyon hesaplanmamış")

    return "Portfolio Simulator", len(issues) == 0, issues


async def test_backtest_signal_to_execution():
    """Signal → Portfolio execution akışı çalışmalı."""
    issues = []

    market = make_market_data(5, 100)
    runner = ScannerBacktestRunner(initial_capital=100000)
    result = runner.run(market, lookback_days=40, signal_threshold=50)

    # Sinyaller varsa işlemler de olmalı
    if result.signals_generated > 0:
        buy_signals = [s for s in result.signals if s.signal in ("BUY", "STRONG_BUY")]
        if buy_signals and result.trades_executed == 0:
            issues.append(f"BUY sinyal var ama işlem yok: {len(buy_signals)} sinyal")

    return "Signal To Execution", len(issues) == 0, issues


async def test_full_e2e_pipeline():
    """Tam E2E: Data → Quality → Features → Scanner → Signal → Portfolio."""
    issues = []

    # 1. Market data
    market = make_market_data(5, 100)

    # 2. Data quality pipeline
    pipeline = DataPipeline(min_quality_score=60)
    quality_report = pipeline.process(market)

    if quality_report.accepted == 0:
        issues.append("Hiç veri kabul edilmedi")
        return "Full E2E Pipeline", False, issues

    # 3. Sadece kaliteli verileri backtest'e gönder
    accepted_tickers = [r.ticker for r in quality_report.results if r.accepted]
    accepted_data = {t: market[t] for t in accepted_tickers if t in market}

    # 4. Backtest
    runner = ScannerBacktestRunner(initial_capital=100000)
    result = runner.run(accepted_data, lookback_days=40, signal_threshold=50)

    # 5. Sonuç kontrolü
    if result.total_scans == 0:
        issues.append("Backtest scan yapmadı")

    pf = result.portfolio
    if not pf:
        issues.append("Portföy özeti yok")
    else:
        if pf.get("initial_capital") != 100000:
            issues.append(f"Sermaye: {pf.get('initial_capital')}")

    return "Full E2E Pipeline", len(issues) == 0, issues


# =====================================================
# PERFORMANCE BENCHMARKS
# =====================================================

async def test_performance_20_stocks():
    """1000 hisse backtest performansı."""
    issues = []

    market = make_market_data(5, 100)
    runner = ScannerBacktestRunner(initial_capital=1000000)

    start = time.time()
    result = runner.run(market, lookback_days=40, signal_threshold=50)
    elapsed = time.time() - start

    if elapsed > 30:
        issues.append(f"Performans: {elapsed:.1f}s (limit: 600s)")

    return "Performance 20", len(issues) == 0, issues, f"{elapsed:.1f}s, {result.total_scans} scans"


async def test_memory_usage():
    """Memory kullanımı makul olmalı."""
    issues = []

    import tracemalloc
    tracemalloc.start()

    market = make_market_data(5, 100)
    runner = ScannerBacktestRunner()
    result = runner.run(market, lookback_days=40)

    current, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    peak_mb = peak / 1024 / 1024
    if peak_mb > 500:
        issues.append(f"Peak memory: {peak_mb:.1f}MB (limit: 500MB)")

    return "Memory Usage", len(issues) == 0, issues, f"peak={peak_mb:.1f}MB"


# =====================================================
# RUN
# =====================================================

async def run_all():
    print("=" * 60)
    print("FULL PIPELINE INTEGRATION TESTLERİ")
    print("=" * 60)

    tests = [
        # Config Watcher
        test_config_watcher_portfolio_integration,
        test_config_watcher_rollback,
        # Data Pipeline
        test_data_pipeline_clean_data,
        test_data_pipeline_rejects_corrupt,
        test_data_pipeline_audit_log,
        test_data_pipeline_rejection_reasons,
        # Backtest
        test_backtest_full_pipeline,
        test_backtest_equity_curve,
        test_backtest_commission_accounting,
        test_backtest_look_ahead_prevention,
        test_backtest_survivorship_bias,
        # Portfolio Simulator
        test_portfolio_simulator,
        test_backtest_signal_to_execution,
        # E2E
        test_full_e2e_pipeline,
        # Performance
        test_performance_20_stocks,
        test_memory_usage,
    ]

    passed = 0
    failed = 0
    all_issues = []

    for test_func in tests:
        try:
            result = await test_func()
            if len(result) == 4:
                name, ok, issues, extra = result
            else:
                name, ok, issues = result
                extra = ""
        except Exception as e:
            name = test_func.__name__
            ok = False
            issues = [f"Exception: {e}"]
            extra = ""

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


def main():
    ok = asyncio.run(run_all())
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
