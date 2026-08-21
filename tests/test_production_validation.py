#!/usr/bin/env python3
"""
Production Validation Testleri

Kapsam:
- Config hot reload
- Scanner backtest integration
- Data quality v2
- Intelligence real data adapter
- Performance benchmarks (100/500/1000 hisse)
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

from services.core.config_watcher import ConfigWatcher
from services.core.data_quality import DataQualityChecker as DataQualityV2
from services.scanner.backtest_runner import ScannerBacktestRunner
from services.features.calculator import FeatureCalculator
from services.core.tradability_mask import TradabilityMask


def make_market_data(n_stocks=100, n_days=120, seed=42):
    """Gerçekçi market dataset oluştur."""
    np.random.seed(seed)
    tickers = [f"STOCK{i:04d}" for i in range(n_stocks)]
    market = {}

    for ticker in tickers:
        trend = np.random.uniform(-0.002, 0.002)
        vol = np.random.uniform(0.01, 0.03)
        dates = pd.date_range(end=datetime.now(), periods=n_days, freq='B')
        close = 100 * np.exp(np.cumsum(np.random.randn(n_days) * vol + trend))
        high = close * (1 + np.abs(np.random.randn(n_days) * 0.01))
        low = close * (1 - np.abs(np.random.randn(n_days) * 0.01))
        volume = np.random.randint(10000, 1000000, n_days).astype(float)

        market[ticker] = pd.DataFrame({
            'Open': close * 0.999, 'High': high, 'Low': low,
            'Close': close, 'Volume': volume
        }, index=dates)

    return market


# =====================================================
# CONFIG HOT RELOAD TESTS
# =====================================================

async def test_config_change_detection():
    """Dosya değişikliği algılanmalı."""
    issues = []

    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        json.dump({"version": 1, "port": 8000}, f)
        config_path = f.name

    state = {"config": None, "reload_count": 0}

    def reload_fn():
        with open(config_path) as f:
            state["config"] = json.load(f)
        state["reload_count"] += 1

    watcher = ConfigWatcher(config_path, reload_fn, watch_interval_s=0.2)
    watcher.start()
    await asyncio.sleep(0.3)

    # Dosyayı değiştir
    with open(config_path, "w") as f:
        json.dump({"version": 2, "port": 9000}, f)

    await asyncio.sleep(0.5)
    watcher.stop()

    if state["reload_count"] < 1:
        issues.append(f"Reload sayısı: {state['reload_count']}")

    if state["config"] and state["config"].get("port") != 9000:
        issues.append(f"Port: {state['config'].get('port')}")

    os.unlink(config_path)
    return "Config Change Detection", len(issues) == 0, issues


async def test_config_invalid_json_rollback():
    """Geçersiz JSON'da eski config korunmalı."""
    issues = []

    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        json.dump({"version": 1, "port": 8000}, f)
        config_path = f.name

    state = {"config": {"version": 1, "port": 8000}, "reload_count": 0}

    def reload_fn():
        with open(config_path) as f:
            state["config"] = json.load(f)
        state["reload_count"] += 1

    watcher = ConfigWatcher(config_path, reload_fn, watch_interval_s=0.2)
    watcher.start()
    await asyncio.sleep(0.3)

    # Geçersiz JSON yaz
    with open(config_path, "w") as f:
        f.write("{invalid json content")

    await asyncio.sleep(0.5)
    watcher.stop()

    # Eski config korunmalı
    if state["config"].get("port") != 8000:
        issues.append(f"Eski config kayboldu: {state['config']}")

    # Reload yapılmamalı (invalid JSON)
    if state["reload_count"] != 0:
        issues.append(f"Reload sayısı: {state['reload_count']} (beklenen: 0)")

    # Audit log'da hata olmalı
    audit = watcher.get_audit_log()
    failed = [e for e in audit if e["action"] == "reload_failed"]
    if not failed:
        issues.append("Audit log'da reload_failed yok")

    os.unlink(config_path)
    return "Config Invalid JSON Rollback", len(issues) == 0, issues


async def test_config_validation_rollback():
    """Validation başarısızsa eski config korunmalı."""
    issues = []

    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        json.dump({"version": 1, "port": 8000}, f)
        config_path = f.name

    state = {"config": {"version": 1, "port": 8000}, "reload_count": 0}

    def reload_fn():
        with open(config_path) as f:
            state["config"] = json.load(f)
        state["reload_count"] += 1

    def validate_fn(config):
        if config.get("port", 0) < 0:
            return ["Port negatif olamaz"]
        return []

    watcher = ConfigWatcher(config_path, reload_fn, validate_fn=validate_fn, watch_interval_s=0.2)
    watcher.start()
    await asyncio.sleep(0.3)

    # Geçersiz config yaz
    with open(config_path, "w") as f:
        json.dump({"version": 2, "port": -1}, f)

    await asyncio.sleep(0.5)
    watcher.stop()

    # Eski config korunmalı
    if state["config"].get("port") != 8000:
        issues.append(f"Eski config kayboldu: {state['config']}")

    os.unlink(config_path)
    return "Config Validation Rollback", len(issues) == 0, issues


async def test_config_audit_log():
    """Config değişiklikleri audit log'a yazılmalı."""
    issues = []

    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        json.dump({"version": 1}, f)
        config_path = f.name

    def reload_fn():
        pass

    watcher = ConfigWatcher(config_path, reload_fn, watch_interval_s=0.1)
    watcher.start()
    await asyncio.sleep(0.2)

    # Değiştir
    with open(config_path, "w") as f:
        json.dump({"version": 2}, f)
    await asyncio.sleep(0.3)

    # Manuel reload
    watcher.force_reload()
    watcher.stop()

    audit = watcher.get_audit_log()
    if len(audit) < 2:
        issues.append(f"Audit entries: {len(audit)}")

    os.unlink(config_path)
    return "Config Audit Log", len(issues) == 0, issues


# =====================================================
# DATA QUALITY V2 TESTS
# =====================================================

async def test_data_quality_duplicate_detection():
    """Duplicate veri tespit edilmeli."""
    issues = []

    dq = DataQualityV2()
    dates = pd.date_range(end=datetime.now(), periods=10, freq='B')
    dates = dates.append(dates[:3])  # 3 duplicate
    df = pd.DataFrame({
        'Open': 100, 'High': 105, 'Low': 95,
        'Close': 102, 'Volume': 50000
    }, index=dates)

    report = dq.full_quality_check(df, "TEST")

    dup_issues = [i for i in report.issues if i.check == "duplicates"]
    if not dup_issues:
        issues.append("Duplicate tespit edilemedi")

    return "Data Quality Duplicates", len(issues) == 0, issues


async def test_data_quality_staleness():
    """Eski veri tespit edilmeli."""
    issues = []

    dq = DataQualityV2()
    dates = pd.date_range(end=datetime.now() - timedelta(days=10), periods=10, freq='B')
    df = pd.DataFrame({
        'Open': 100, 'High': 105, 'Low': 95,
        'Close': 102, 'Volume': 50000
    }, index=dates)

    report = dq.full_quality_check(df, "TEST")

    stale_issues = [i for i in report.issues if i.check == "staleness"]
    if not stale_issues:
        issues.append("Staleness tespit edilemedi")

    return "Data Quality Staleness", len(issues) == 0, issues


async def test_data_quality_ohlc_violation():
    """High < Low tespit edilmeli."""
    issues = []

    dq = DataQualityV2()
    dates = pd.date_range(end=datetime.now(), periods=5, freq='B')
    df = pd.DataFrame({
        'Open': [100, 100, 100, 100, 100],
        'High': [105, 90, 105, 105, 105],   # 2. satırda High < Low
        'Low':  [95, 95, 95, 95, 95],
        'Close': [102, 102, 102, 102, 102],
        'Volume': [50000, 50000, 50000, 50000, 50000]
    }, index=dates)

    report = dq.full_quality_check(df, "TEST")

    ohlc_issues = [i for i in report.issues if i.check == "ohlc_consistency"]
    if not ohlc_issues:
        issues.append("OHLC violation tespit edilemedi")

    return "Data Quality OHLC Violation", len(issues) == 0, issues


async def test_data_quality_volume_spike():
    """Anormal hacim tespit edilmeli."""
    issues = []

    dq = DataQualityV2()
    dates = pd.date_range(end=datetime.now(), periods=20, freq='B')
    volume = np.full(20, 50000.0)
    volume[10] = 500000  # 10x spike

    df = pd.DataFrame({
        'Open': 100, 'High': 105, 'Low': 95,
        'Close': 102, 'Volume': volume
    }, index=dates)

    report = dq.full_quality_check(df, "TEST")

    spike_issues = [i for i in report.issues if i.check == "volume_spike"]
    if not spike_issues:
        issues.append("Volume spike tespit edilemedi")

    return "Data Quality Volume Spike", len(issues) == 0, issues


async def test_data_quality_price_gap():
    """Büyük fiyat boşluğu tespit edilmeli."""
    issues = []

    dq = DataQualityV2()
    dates = pd.date_range(end=datetime.now(), periods=10, freq='B')
    close = np.full(10, 100.0)
    close[5] = 120  # %20 gap

    df = pd.DataFrame({
        'Open': close - 0.5, 'High': close + 1,
        'Low': close - 1, 'Close': close,
        'Volume': np.full(10, 50000.0)
    }, index=dates)

    report = dq.full_quality_check(df, "TEST")

    gap_issues = [i for i in report.issues if i.check == "price_gaps"]
    if not gap_issues:
        issues.append("Price gap tespit edilemedi")

    return "Data Quality Price Gap", len(issues) == 0, issues


async def test_data_quality_score():
    """Kalite skoru doğru hesaplanmalı."""
    issues = []

    dq = DataQualityV2()

    # Temiz veri — yüksek skor
    dates = pd.date_range(end=datetime.now(), periods=100, freq='B')
    df_clean = pd.DataFrame({
        'Open': 100, 'High': 105, 'Low': 95,
        'Close': 102, 'Volume': 50000
    }, index=dates)

    report = dq.full_quality_check(df_clean, "CLEAN")
    if report.quality_score < 80:
        issues.append(f"Temiz veri skoru düşük: {report.quality_score}")

    # Boş veri — sıfır skor
    report_empty = dq.full_quality_check(pd.DataFrame(), "EMPTY")
    if report_empty.quality_score != 0:
        issues.append(f"Boş veri skoru: {report_empty.quality_score}")

    return "Data Quality Score", len(issues) == 0, issues


# =====================================================
# SCANNER BACKTEST TESTS
# =====================================================

async def test_backtest_basic():
    """Temel backtest çalışmalı."""
    issues = []

    market = make_market_data(20, 120)
    runner = ScannerBacktestRunner()
    result = runner.run(market, lookback_days=30)

    if result.total_scans == 0:
        issues.append("Hiç scan yapılmadı")

    if result.signals_generated == 0:
        issues.append("Hiç sinyal üretilmedi")

    if result.look_ahead_violations > 0:
        issues.append(f"Look-ahead violation: {result.look_ahead_violations}")

    return "Backtest Basic", len(issues) == 0, issues


async def test_backtest_look_ahead():
    """Look-ahead bias kontrolü."""
    issues = []

    market = make_market_data(10, 120)
    runner = ScannerBacktestRunner()

    # lookback_days > veri uzunluğu → hata vermemeli
    result = runner.run(market, lookback_days=200)

    if result.look_ahead_violations > 0:
        issues.append(f"Look-ahead violation: {result.look_ahead_violations}")

    return "Backtest Look-Ahead", len(issues) == 0, issues


async def test_backtest_survivorship():
    """Survivorship bias kontrolü."""
    issues = []

    market = make_market_data(20, 120)
    runner = ScannerBacktestRunner()

    # Sadece 5 hisse evrende olsun
    universe = list(market.keys())[:5]
    result = runner.run(market, universe_at_date=universe)

    if result.survivorship_violations == 0:
        issues.append("Survivorship violation tespit edilemedi")

    if result.signals_generated > len(universe):
        issues.append(f"Evren dışından sinyal: {result.signals_generated} > {len(universe)}")

    return "Backtest Survivorship", len(issues) == 0, issues


async def test_backtest_missing_data():
    """Eksik veri dönemleri yönetilmeli."""
    issues = []

    market = make_market_data(10, 120)

    # Bir hisseye NaN ekle
    df = market["STOCK0000"].copy()
    df.iloc[50:55, df.columns.get_loc('Close')] = np.nan
    market["STOCK0000"] = df

    runner = ScannerBacktestRunner()
    result = runner.run(market)

    if result.data_quality_issues == 0:
        issues.append("Eksik veri tespit edilemedi")

    return "Backtest Missing Data", len(issues) == 0, issues


async def test_backtest_performance():
    """Backtest performansı < 60 saniye (100 hisse)."""
    issues = []

    market = make_market_data(100, 120)
    runner = ScannerBacktestRunner()

    start = time.time()
    result = runner.run(market, lookback_days=30)
    elapsed = time.time() - start

    if elapsed > 60:
        issues.append(f"Performans: {elapsed:.1f}s (limit: 60s)")

    return "Backtest Performance", len(issues) == 0, issues, f"{elapsed:.1f}s"


# =====================================================
# PERFORMANCE BENCHMARKS
# =====================================================

async def benchmark_scanner(n_stocks: int):
    """N hisse tarama benchmark."""
    market = make_market_data(n_stocks, 120)
    calc = FeatureCalculator()
    tm = TradabilityMask()

    start = time.time()
    results = 0
    for ticker, df in market.items():
        try:
            mask = tm.compute_mask(ticker, df['Open'].values, df['High'].values,
                                  df['Low'].values, df['Close'].values, df['Volume'].values)
            features = calc.compute_all_features(df, mask=mask.mask, ticker=ticker)
            if features:
                results += 1
        except Exception:
            pass
    elapsed = time.time() - start

    return {
        "n_stocks": n_stocks,
        "elapsed_s": round(elapsed, 2),
        "scans_per_second": round(n_stocks / max(elapsed, 0.001), 1),
        "successful": results,
    }


async def test_benchmark_100():
    """100 hisse benchmark."""
    result = await benchmark_scanner(100)
    issues = []
    if result["elapsed_s"] > 30:
        issues.append(f"100 hisse: {result['elapsed_s']}s")
    return "Benchmark 100", len(issues) == 0, issues, f"{result['elapsed_s']}s, {result['scans_per_second']}/s"


async def test_benchmark_500():
    """500 hisse benchmark."""
    result = await benchmark_scanner(500)
    issues = []
    if result["elapsed_s"] > 120:
        issues.append(f"500 hisse: {result['elapsed_s']}s")
    return "Benchmark 500", len(issues) == 0, issues, f"{result['elapsed_s']}s, {result['scans_per_second']}/s"


async def test_benchmark_1000():
    """1000 hisse benchmark."""
    result = await benchmark_scanner(1000)
    issues = []
    if result["elapsed_s"] > 300:
        issues.append(f"1000 hisse: {result['elapsed_s']}s")
    return "Benchmark 1000", len(issues) == 0, issues, f"{result['elapsed_s']}s, {result['scans_per_second']}/s"


# =====================================================
# RUN
# =====================================================

async def run_all():
    print("=" * 60)
    print("PRODUCTION VALIDATION TESTLERİ")
    print("=" * 60)

    tests = [
        # Config Hot Reload
        test_config_change_detection,
        test_config_invalid_json_rollback,
        test_config_validation_rollback,
        test_config_audit_log,
        # Data Quality
        test_data_quality_duplicate_detection,
        test_data_quality_staleness,
        test_data_quality_ohlc_violation,
        test_data_quality_volume_spike,
        test_data_quality_price_gap,
        test_data_quality_score,
        # Scanner Backtest
        test_backtest_basic,
        test_backtest_look_ahead,
        test_backtest_survivorship,
        test_backtest_missing_data,
        test_backtest_performance,
        # Benchmarks
        test_benchmark_100,
        test_benchmark_500,
        test_benchmark_1000,
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
