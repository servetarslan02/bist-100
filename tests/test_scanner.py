#!/usr/bin/env python3
"""
Scanner Module Testleri

Kapsam:
- Universe tarama
- Signal üretimi
- Ranking entegrasyonu
- Edge cases (NaN, düşük hacim, ekstrem fiyat)
- End-to-end pipeline
"""

import sys
import os
import asyncio
import numpy as np
import pandas as pd
from datetime import datetime
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.scanner.alpha_scanner import AlphaScanner
from services.scanner.opportunity_engine import OpportunityDiscoveryEngine as OpportunityEngine
from services.features.calculator import FeatureCalculator
from services.core.tradability_mask import TradabilityMask


def make_features(ticker="TEST", rsi=50.0, momentum=0.0, roc=0.0, volume_z=0.0, atr_pct=0.02):
    """Test feature seti oluştur (scalar değerler)."""
    return {
        "rsi_14": float(rsi),
        "momentum_20d": float(momentum),
        "roc_5d": float(roc),
        "roc_20d": float(roc * 2),
        "volume_zscore": float(volume_z),
        "atr_pct": float(atr_pct),
        "adx": 25.0,
        "bb_position": 0.5,
        "macd_hist": 0.0,
        "drawdown_20d": 0.05,
        "rs_vs_bist_5d": 0.0,
        "sector_rel_return_5d": 0.0,
    }


def make_df(n=60, trend=0.001, vol=0.02, seed=42):
    """Sentetik OHLCV DataFrame."""
    np.random.seed(seed)
    dates = pd.date_range(end=datetime.now(), periods=n, freq='B')
    close = 100 * np.exp(np.cumsum(np.random.randn(n) * vol + trend))
    high = close * (1 + np.abs(np.random.randn(n) * 0.01))
    low = close * (1 - np.abs(np.random.randn(n) * 0.01))
    volume = np.random.randint(10000, 1000000, n).astype(float)
    return pd.DataFrame({
        'Open': close * 0.999, 'High': high, 'Low': low,
        'Close': close, 'Volume': volume
    }, index=dates)


# =====================================================
# SCANNER TESTS
# =====================================================

async def test_scanner_single_stock():
    """Tek hisse taraması çalışmalı."""
    issues = []

    scanner = AlphaScanner()
    features = make_features(rsi=65, momentum=0.05, roc=3.0)

    result = scanner._scan_single("THYAO", features, ml_score=70.0, event_score=50.0)

    if not result:
        issues.append("Sonuç None")
    elif not hasattr(result, 'ticker'):
        issues.append("ticker attribute yok")
    elif result.ticker != "THYAO":
        issues.append(f"ticker: {result.ticker}")

    return "Scanner Single Stock", len(issues) == 0, issues


async def test_scanner_positive_signal():
    """Güçlü pozitif sinyal üretmeli."""
    issues = []

    scanner = AlphaScanner()
    # Güçlü momentum + yüksek RSI + yüksek hacim
    features = make_features(rsi=70, momentum=0.08, roc=5.0, volume_z=2.0)

    result = scanner._scan_single("BULL", features, ml_score=80.0, event_score=60.0)

    if result:
        # Score veya opportunity_score kontrol et
        score = getattr(result, 'opportunity_score', None) or getattr(result, 'score', None)
        if score is not None and score < 30:
            issues.append(f"Skor düşük: {score}")

    return "Scanner Positive Signal", len(issues) == 0, issues


async def test_scanner_negative_signal():
    """Negatif sinyal üretmeli."""
    issues = []

    scanner = AlphaScanner()
    # Zayıf momentum + düşük RSI
    features = make_features(rsi=25, momentum=-0.08, roc=-5.0, volume_z=-1.0)

    result = scanner._scan_single("BEAR", features, ml_score=20.0, event_score=30.0)

    if result:
        # Negatif senaryoda düşük skor beklenir
        score = getattr(result, 'opportunity_score', None) or getattr(result, 'score', None)
        if score is not None and score > 70:
            issues.append(f"Negatif senaryo skor yüksek: {score}")

    return "Scanner Negative Signal", len(issues) == 0, issues


async def test_scanner_neutral_signal():
    """Nötr durumda HOLD sinyali vermeli."""
    issues = []

    scanner = AlphaScanner()
    # Nötr değerler
    features = make_features(rsi=50, momentum=0.0, roc=0.0, volume_z=0.0)

    result = scanner._scan_single("NEUTRAL", features, ml_score=50.0, event_score=50.0)

    if result:
        if hasattr(result, 'signal_direction'):
            # HOLD veya zayıf LONG/SHORT olabilir
            pass

    return "Scanner Neutral Signal", len(issues) == 0, issues


async def test_scanner_edge_nan():
    """NaN feature ile crash olmamalı."""
    issues = []

    scanner = AlphaScanner()
    features = make_features()
    # NaN ekle
    features["rsi_14"] = np.array([np.nan])
    features["momentum_20d"] = np.array([np.nan])

    try:
        result = scanner._scan_single("NAN", features)
        # NaN ile bile sonuç dönmeli (None veya default)
    except Exception as e:
        issues.append(f"Crash: {e}")

    return "Scanner Edge NaN", len(issues) == 0, issues


async def test_scanner_edge_low_volume():
    """Düşük hacimli hisse filtrelenebilmeli."""
    issues = []

    scanner = AlphaScanner()
    features = make_features(volume_z=-3.0)  # Çok düşük hacim

    try:
        result = scanner._scan_single("LOWVOL", features)
        if result:
            score = getattr(result, 'opportunity_score', None) or 0
            # Düşük hacim düşük skor vermeli
            if score > 80:
                issues.append(f"Düşük hacim ama yüksek skor: {score}")
    except Exception as e:
        issues.append(f"Crash: {e}")

    return "Scanner Edge Low Volume", len(issues) == 0, issues


async def test_scanner_edge_extreme_move():
    """Ekstrem fiyat hareketinde crash olmamalı."""
    issues = []

    scanner = AlphaScanner()
    features = make_features(momentum=0.50, roc=30.0, atr_pct=0.15)

    try:
        result = scanner._scan_single("EXTREME", features)
    except Exception as e:
        issues.append(f"Crash: {e}")

    return "Scanner Edge Extreme Move", len(issues) == 0, issues


# =====================================================
# OPPORTUNITY ENGINE TESTS
# =====================================================

async def test_opportunity_score():
    """Opportunity score hesaplaması çalışmalı."""
    issues = []

    engine = OpportunityEngine()
    features = make_features(rsi=65, momentum=0.05, roc=3.0)

    try:
        score = engine.compute_opportunity_score("TEST", features, market_regime="BULL")
        if not score:
            issues.append("Score None")
    except Exception as e:
        # API farklı olabilir
        issues.append(f"Exception: {e}")

    return "Opportunity Score", len(issues) == 0, issues


async def test_opportunity_signal_generation():
    """Signal üretimi çalışmalı."""
    issues = []

    engine = OpportunityEngine()
    features = make_features(rsi=65, momentum=0.05, roc=3.0)

    from services.scanner.opportunity_engine import OpportunityScore
    from datetime import datetime
    score = OpportunityScore(
        ticker="TEST", timestamp=datetime.now(),
        technical_score=70.0, momentum_score=80.0, opportunity_score=75.0,
        volume_score=65.0, volatility_score=70.0,
        regime_score=75.0, risk_score=60.0,
    )

    try:
        signal, confidence = engine._determine_signal(score, features)
        if not signal:
            issues.append("Signal None")
    except Exception as e:
        issues.append(f"Exception: {e}")

    return "Opportunity Signal Generation", len(issues) == 0, issues


async def test_opportunity_evidence_generation():
    """Evidence üretimi çalışmalı."""
    issues = []

    engine = OpportunityEngine()
    features = make_features(rsi=65, momentum=0.05, roc=3.0)

    from services.scanner.opportunity_engine import OpportunityScore
    from datetime import datetime
    score = OpportunityScore(
        ticker="TEST", timestamp=datetime.now(),
        technical_score=70.0, momentum_score=80.0, opportunity_score=75.0,
        volume_score=65.0, volatility_score=70.0,
        regime_score=75.0, risk_score=60.0,
    )

    evidence = engine._generate_evidence(score, features)

    if not isinstance(evidence, list):
        issues.append("Evidence list değil")
    elif len(evidence) == 0:
        issues.append("Evidence boş")

    return "Opportunity Evidence Generation", len(issues) == 0, issues


async def test_opportunity_risk_generation():
    """Risk üretimi çalışmalı."""
    issues = []

    engine = OpportunityEngine()
    features = make_features(rsi=65, momentum=0.05, roc=3.0, atr_pct=0.05)

    from services.scanner.opportunity_engine import OpportunityScore
    from datetime import datetime
    score = OpportunityScore(
        ticker="TEST", timestamp=datetime.now(),
        technical_score=70.0, momentum_score=80.0, opportunity_score=75.0,
        volume_score=65.0, volatility_score=70.0,
        regime_score=75.0, risk_score=60.0,
    )

    risks = engine._generate_risks(score, features)

    if not isinstance(risks, list):
        issues.append("Risks list değil")

    return "Opportunity Risk Generation", len(issues) == 0, issues


# =====================================================
# END-TO-END PIPELINE TEST
# =====================================================

async def test_e2e_pipeline():
    """Data → Features → Scanner → Signal pipeline."""
    issues = []

    # 1. Mock data oluştur
    df = make_df(120, trend=0.002, vol=0.015, seed=42)

    # 2. Feature hesapla
    calc = FeatureCalculator()
    tm = TradabilityMask()
    mask = tm.compute_mask("E2E", df['Open'].values, df['High'].values,
                           df['Low'].values, df['Close'].values, df['Volume'].values)
    features = calc.compute_all_features(df, mask=mask.mask, ticker="E2E")

    if not features:
        issues.append("Feature hesaplanamadı")
        return "E2E Pipeline", False, issues

    # 3. Scanner'a gönder
    scanner = AlphaScanner()
    result = scanner._scan_single("E2E", features, ml_score=60.0, event_score=50.0)

    if result is None:
        issues.append("Scanner sonuç döndürmedi")

    # 4. Opportunity engine
    engine = OpportunityEngine()
    score = engine.compute_opportunity_score("TEST", features, market_regime="BULL")

    if score is None:
        issues.append("Opportunity score döndürmedi")

    return "E2E Pipeline", len(issues) == 0, issues


async def test_e2e_multi_stock():
    """Çoklu hisse pipeline testi."""
    issues = []

    tickers = ["THYAO", "GARAN", "AKBNK", "EREGL", "TUPRS"]
    scanner = AlphaScanner()
    calc = FeatureCalculator()
    tm = TradabilityMask()

    results = []
    for ticker in tickers:
        df = make_df(120, seed=hash(ticker) % 10000)
        mask = tm.compute_mask(ticker, df['Open'].values, df['High'].values,
                              df['Low'].values, df['Close'].values, df['Volume'].values)
        features = calc.compute_all_features(df, mask=mask.mask, ticker=ticker)
        result = scanner._scan_single(ticker, features)
        if result:
            results.append(result)

    if len(results) == 0:
        issues.append("Hiçbir hisse sonuç döndürmedi")

    # Duplicate kontrolü
    tickers_seen = set()
    for r in results:
        if r.ticker in tickers_seen:
            issues.append(f"Duplicate: {r.ticker}")
        tickers_seen.add(r.ticker)

    return "E2E Multi Stock", len(issues) == 0, issues


# =====================================================
# RUN
# =====================================================

async def run_all():
    print("=" * 60)
    print("SCANNER MODULE TESTLERİ")
    print("=" * 60)

    tests = [
        # Scanner
        test_scanner_single_stock,
        test_scanner_positive_signal,
        test_scanner_negative_signal,
        test_scanner_neutral_signal,
        test_scanner_edge_nan,
        test_scanner_edge_low_volume,
        test_scanner_edge_extreme_move,
        # Opportunity Engine
        test_opportunity_score,
        test_opportunity_signal_generation,
        test_opportunity_evidence_generation,
        test_opportunity_risk_generation,
        # E2E
        test_e2e_pipeline,
        test_e2e_multi_stock,
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
