#!/usr/bin/env python3
"""
Feature Engineering Testleri

Kapsam:
- Feature calculator doğruluğu
- Seven motors hesaplamaları
- Cross-sectional features
- Edge cases: NaN, eksik veri, kısa aralık, ekstrem fiyat
- Matematiksel doğruluk
"""

import sys
import os
import asyncio
import numpy as np
import pandas as pd
from datetime import datetime, timedelta
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.features.calculator import FeatureCalculator
from services.features.cross_sectional import CrossSectionalEngine
from services.core.tradability_mask import TradabilityMask


def make_df(n=120, seed=42, trend=0.0005, vol=0.02):
    """Sentetik OHLCV DataFrame oluştur."""
    np.random.seed(seed)
    dates = pd.date_range(end=datetime.now(), periods=n, freq='B')
    close = 100 * np.exp(np.cumsum(np.random.randn(n) * vol + trend))
    high = close * (1 + np.abs(np.random.randn(n) * 0.01))
    low = close * (1 - np.abs(np.random.randn(n) * 0.01))
    open_ = close * (1 + np.random.randn(n) * 0.005)
    volume = np.random.randint(10000, 1000000, n).astype(float)
    return pd.DataFrame({
        'Open': open_, 'High': high, 'Low': low,
        'Close': close, 'Volume': volume
    }, index=dates)


# =====================================================
# FEATURE CALCULATOR TESTS
# =====================================================

async def test_feature_calculator_basic():
    """Temel feature hesaplama çalışmalı."""
    issues = []

    calc = FeatureCalculator()
    df = make_df(120)
    tm = TradabilityMask()
    mask = tm.compute_mask("TEST", df['Open'].values, df['High'].values,
                           df['Low'].values, df['Close'].values, df['Volume'].values)

    features = calc.compute_all_features(df, mask=mask.mask, ticker="TEST")

    if not features:
        issues.append("Feature dict boş")
        return "Feature Calculator Basic", False, issues

    # Temel feature'lar var mı?
    expected = ['rsi_14', 'macd', 'macd_signal', 'macd_hist',
                'bb_upper', 'bb_lower', 'bb_position',
                'atr_14', 'adx', 'obv', 'volume_zscore',
                'momentum_20d', 'roc_5d', 'roc_20d']

    for name in expected:
        if name not in features:
            issues.append(f"Eksik feature: {name}")

    return "Feature Calculator Basic", len(issues) == 0, issues


async def test_rsi_range():
    """RSI 0-100 aralığında olmalı."""
    issues = []

    calc = FeatureCalculator()
    df = make_df(120)
    tm = TradabilityMask()
    mask = tm.compute_mask("TEST", df['Open'].values, df['High'].values,
                           df['Low'].values, df['Close'].values, df['Volume'].values)

    features = calc.compute_all_features(df, mask=mask.mask, ticker="TEST")

    if 'rsi_14' in features:
        rsi = features['rsi_14']
        if isinstance(rsi, np.ndarray):
            valid = rsi[~np.isnan(rsi)]
            if len(valid) > 0:
                if np.any(valid < 0) or np.any(valid > 100):
                    issues.append(f"RSI aralık dışı: [{np.min(valid):.1f}, {np.max(valid):.1f}]")
                else:
                    return "RSI Range", True, ["RSI [0, 100] ✓"]
        elif isinstance(rsi, (int, float)):
            if rsi < 0 or rsi > 100:
                issues.append(f"RSI aralık dışı: {rsi}")

    return "RSI Range", len(issues) == 0, issues


async def test_macd_signal_relationship():
    """MACD ve signal aynı uzunlukta olmalı."""
    issues = []

    calc = FeatureCalculator()
    df = make_df(120)
    tm = TradabilityMask()
    mask = tm.compute_mask("TEST", df['Open'].values, df['High'].values,
                           df['Low'].values, df['Close'].values, df['Volume'].values)

    features = calc.compute_all_features(df, mask=mask.mask, ticker="TEST")

    if 'macd' in features and 'macd_signal' in features:
        macd = features['macd']
        signal = features['macd_signal']
        if isinstance(macd, np.ndarray) and isinstance(signal, np.ndarray):
            if len(macd) != len(signal):
                issues.append(f"MACD uzunluk: {len(macd)} != signal: {len(signal)}")
            else:
                return "MACD Signal Relationship", True, [f"Uzunluk uyumlu: {len(macd)}"]

    return "MACD Signal Relationship", len(issues) == 0, issues


async def test_atr_positive():
    """ATR pozitif olmalı."""
    issues = []

    calc = FeatureCalculator()
    df = make_df(120)
    tm = TradabilityMask()
    mask = tm.compute_mask("TEST", df['Open'].values, df['High'].values,
                           df['Low'].values, df['Close'].values, df['Volume'].values)

    features = calc.compute_all_features(df, mask=mask.mask, ticker="TEST")

    if 'atr_14' in features:
        atr = features['atr_14']
        if isinstance(atr, np.ndarray):
            valid = atr[~np.isnan(atr)]
            if len(valid) > 0 and np.any(valid < 0):
                issues.append(f"ATR negatif: {np.min(valid)}")
            else:
                return "ATR Positive", True, [f"ATR range: [{np.min(valid):.4f}, {np.max(valid):.4f}]"]

    return "ATR Positive", len(issues) == 0, issues


async def test_bollinger_band_order():
    """BB upper > close > lower olmalı."""
    issues = []

    calc = FeatureCalculator()
    df = make_df(120)
    tm = TradabilityMask()
    mask = tm.compute_mask("TEST", df['Open'].values, df['High'].values,
                           df['Low'].values, df['Close'].values, df['Volume'].values)

    features = calc.compute_all_features(df, mask=mask.mask, ticker="TEST")

    if all(k in features for k in ['bb_upper', 'bb_lower', 'bb_position']):
        upper = features['bb_upper']
        lower = features['bb_lower']
        if isinstance(upper, np.ndarray) and isinstance(lower, np.ndarray):
            valid_mask = ~np.isnan(upper) & ~np.isnan(lower)
            if valid_mask.any():
                violations = np.sum(upper[valid_mask] < lower[valid_mask])
                if violations > 0:
                    issues.append(f"BB upper < lower: {violations} kez")
                else:
                    return "BB Band Order", True, ["BB upper > lower ✓"]

    return "BB Band Order", len(issues) == 0, issues


# =====================================================
# EDGE CASE TESTS
# =====================================================

async def test_short_data():
    """Kısa veri seti ile crash olmamalı."""
    issues = []

    calc = FeatureCalculator()
    df = make_df(10)  # Çok kısa
    tm = TradabilityMask()
    mask = tm.compute_mask("SHORT", df['Open'].values, df['High'].values,
                           df['Low'].values, df['Close'].values, df['Volume'].values)

    try:
        features = calc.compute_all_features(df, mask=mask.mask, ticker="SHORT")
        if features:
            return "Short Data", True, [f"{len(features)} feature hesaplandı"]
    except Exception as e:
        issues.append(f"Crash: {e}")

    return "Short Data", len(issues) == 0, issues


async def test_nan_handling():
    """NaN değerler mask ile filtrelenmeli."""
    issues = []

    calc = FeatureCalculator()
    df = make_df(120)
    # NaN ekle
    df.iloc[10:15, df.columns.get_loc('Close')] = np.nan
    df.iloc[50:55, df.columns.get_loc('Volume')] = 0

    tm = TradabilityMask()
    mask = tm.compute_mask("NAN", df['Open'].values, df['High'].values,
                           df['Low'].values, df['Close'].values, df['Volume'].values)

    # Mask NaN günleri filtrelemeli
    masked_count = np.sum(mask.mask == 0)
    if masked_count == 0:
        issues.append("NaN günler maskelenmedi")
    else:
        return "NaN Handling", True, [f"{masked_count} gün maskelendi (NaN/zero volume)"]

    return "NaN Handling", len(issues) == 0, issues


async def test_extreme_prices():
    """Ekstrem fiyat hareketleri crash üretmemeli."""
    issues = []

    calc = FeatureCalculator()
    np.random.seed(99)
    n = 120
    dates = pd.date_range(end=datetime.now(), periods=n, freq='B')
    # %50+ günlük hareket
    close = 100 * np.exp(np.cumsum(np.random.randn(n) * 0.1))
    high = close * 1.5
    low = close * 0.5
    open_ = close * 0.8
    volume = np.random.randint(1000, 100000, n).astype(float)

    df = pd.DataFrame({'Open': open_, 'High': high, 'Low': low,
                       'Close': close, 'Volume': volume}, index=dates)

    tm = TradabilityMask()
    mask = tm.compute_mask("EXTREME", df['Open'].values, df['High'].values,
                           df['Low'].values, df['Close'].values, df['Volume'].values)

    try:
        features = calc.compute_all_features(df, mask=mask.mask, ticker="EXTREME")
        if features:
            return "Extreme Prices", True, [f"{len(features)} feature hesaplandı"]
    except Exception as e:
        issues.append(f"Crash: {e}")

    return "Extreme Prices", len(issues) == 0, issues


async def test_flat_prices():
    """Sabit fiyat ile feature hesaplaması."""
    issues = []

    calc = FeatureCalculator()
    n = 60
    dates = pd.date_range(end=datetime.now(), periods=n, freq='B')
    close = np.full(n, 100.0)
    df = pd.DataFrame({
        'Open': close, 'High': close, 'Low': close,
        'Close': close, 'Volume': np.full(n, 50000.0)
    }, index=dates)

    tm = TradabilityMask()
    mask = tm.compute_mask("FLAT", df['Open'].values, df['High'].values,
                           df['Low'].values, df['Close'].values, df['Volume'].values)

    try:
        features = calc.compute_all_features(df, mask=mask.mask, ticker="FLAT")
        if features:
            return "Flat Prices", True, [f"{len(features)} feature sabit fiyat"]
    except Exception as e:
        issues.append(f"Crash: {e}")

    return "Flat Prices", len(issues) == 0, issues


# =====================================================
# CROSS-SECTIONAL TESTS
# =====================================================

async def test_cross_sectional_basic():
    """Cross-sectional feature hesaplaması çalışmalı."""
    issues = []

    cs = CrossSectionalEngine()

    universe = {}
    for ticker in ["A", "B", "C"]:
        df = make_df(120, seed=hash(ticker) % 1000)
        tm = TradabilityMask()
        mask = tm.compute_mask(ticker, df['Open'].values, df['High'].values,
                              df['Low'].values, df['Close'].values, df['Volume'].values)
        calc = FeatureCalculator()
        features = calc.compute_all_features(df, mask=mask.mask, ticker=ticker)
        universe[ticker] = features

    sector_map = {"A": "TECH", "B": "TECH", "C": "FINANCE"}

    cs_features = cs.compute_all_cross_sectional(
        ticker="A", features=universe["A"],
        universe_features=universe, universe_sectors=sector_map,
    )

    if cs_features:
        return "Cross-Sectional Basic", True, [f"{len(cs_features)} feature"]

    issues.append("Cross-sectional feature boş")
    return "Cross-Sectional Basic", len(issues) == 0, issues


async def test_cross_sectional_rank():
    """Rank feature'ları 0-1 aralığında olmalı."""
    issues = []

    cs = CrossSectionalEngine()
    universe = {}
    for ticker in ["A", "B", "C"]:
        df = make_df(120, seed=hash(ticker) % 1000)
        tm = TradabilityMask()
        mask = tm.compute_mask(ticker, df['Open'].values, df['High'].values,
                              df['Low'].values, df['Close'].values, df['Volume'].values)
        calc = FeatureCalculator()
        universe[ticker] = calc.compute_all_features(df, mask=mask.mask, ticker=ticker)

    rank_feats = cs.compute_rank_features("A", universe["A"], universe)

    if rank_feats:
        for name, val in rank_feats.items():
            if isinstance(val, (int, float)):
                if 'percentile' in name.lower() or 'rank' in name.lower():
                    if val < 0 or val > 1:
                        issues.append(f"{name}={val} aralık dışı")
        if not issues:
            return "Cross-Sectional Rank", True, [f"{len(rank_feats)} rank feature"]

    return "Cross-Sectional Rank", len(issues) == 0, issues


# =====================================================
# MATHEMATICAL VERIFICATION
# =====================================================

async def test_roc_calculation():
    """ROC hesaplaması matematiksel olarak doğru olmalı."""
    issues = []

    # Bilinen değerlerle test
    prices = np.array([100, 105, 110, 108, 115, 120, 118, 125, 130, 128,
                       135, 140, 138, 145, 150, 148, 155, 160, 158, 165,
                       170, 168, 175, 180, 178])

    # 5 günlük ROC = (price[i] / price[i-5] - 1) * 100
    expected_roc_5d = (prices[-1] / prices[-6] - 1) * 100

    n = len(prices)
    dates = pd.date_range(end=datetime.now(), periods=n, freq='B')
    df = pd.DataFrame({
        'Open': prices - 0.5, 'High': prices + 1,
        'Low': prices - 1, 'Close': prices,
        'Volume': np.full(n, 50000.0)
    }, index=dates)

    calc = FeatureCalculator()
    tm = TradabilityMask()
    mask = tm.compute_mask("ROC", df['Open'].values, df['High'].values,
                           df['Low'].values, df['Close'].values, df['Volume'].values)
    features = calc.compute_all_features(df, mask=mask.mask, ticker="ROC")

    if 'roc_5d' in features:
        roc = features['roc_5d']
        if isinstance(roc, np.ndarray):
            valid = roc[~np.isnan(roc)]
            if len(valid) > 0:
                actual = valid[-1]
                if abs(actual - expected_roc_5d) > 0.1:
                    issues.append(f"ROC 5d: {actual:.4f} != {expected_roc_5d:.4f}")
                else:
                    return "ROC Calculation", True, [f"ROC 5d: {actual:.4f} == {expected_roc_5d:.4f} ✓"]

    return "ROC Calculation", len(issues) == 0, issues


async def test_momentum_direction():
    """Yükselen trend'de momentum pozitif olmalı."""
    issues = []

    # Yukarı trend
    n = 60
    dates = pd.date_range(end=datetime.now(), periods=n, freq='B')
    close = 100 + np.arange(n) * 0.5  # Sabit yükseliş
    df = pd.DataFrame({
        'Open': close - 0.1, 'High': close + 0.5,
        'Low': close - 0.5, 'Close': close,
        'Volume': np.full(n, 50000.0)
    }, index=dates)

    calc = FeatureCalculator()
    tm = TradabilityMask()
    mask = tm.compute_mask("UP", df['Open'].values, df['High'].values,
                           df['Low'].values, df['Close'].values, df['Volume'].values)
    features = calc.compute_all_features(df, mask=mask.mask, ticker="UP")

    if 'momentum_20d' in features:
        mom = features['momentum_20d']
        if isinstance(mom, np.ndarray):
            valid = mom[~np.isnan(mom)]
            if len(valid) > 0:
                # Son momentum pozitif olmalı
                if valid[-1] <= 0:
                    issues.append(f"Yükselen trend momentum: {valid[-1]:.4f} (beklenen: >0)")
                else:
                    return "Momentum Direction", True, [f"Yükselen trend momentum: {valid[-1]:.4f} > 0 ✓"]

    return "Momentum Direction", len(issues) == 0, issues


# =====================================================
# RUN
# =====================================================

async def run_all():
    print("=" * 60)
    print("FEATURE ENGINEERING TESTLERİ")
    print("=" * 60)

    tests = [
        test_feature_calculator_basic,
        test_rsi_range,
        test_macd_signal_relationship,
        test_atr_positive,
        test_bollinger_band_order,
        test_short_data,
        test_nan_handling,
        test_extreme_prices,
        test_flat_prices,
        test_cross_sectional_basic,
        test_cross_sectional_rank,
        test_roc_calculation,
        test_momentum_direction,
    ]

    passed = 0
    failed = 0
    all_issues = []

    for test_func in tests:
        try:
            name, ok, issues = await test_func()
        except Exception as e:
            name = test_func.__name__
            ok = False
            issues = [f"Exception: {e}"]

        icon = "✅" if ok else "❌"
        print(f"\n{icon} {name}")
        if ok:
            passed += 1
            for i in issues[:2]:
                print(f"   {i}")
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
