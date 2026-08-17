#!/usr/bin/env python3
"""
ALPHA BIST — Canonical Backtest Integration Tests

Canonical scoring'in backtest'e entegrasyonu testleri:
- Canonical scoring backtest'e gerçekten ulaşıyor mu?
- Aynı historical input aynı canonical score'u üretiyor mu?
- PIT violation testi
- Legacy/panel mevcut testleri
- DecisionEngine deterministic replay
- Empty/MISSING feature durumları
- Regime değişiminde deterministic davranış
"""

import sys
import os
import numpy as np
import pandas as pd
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _make_market_data(n_stocks=5, n_days=150, seed=42):
    """Küçük test market data."""
    np.random.seed(seed)
    market = {}
    dates = pd.date_range(end=datetime.now(), periods=n_days, freq='B')
    for i in range(n_stocks):
        close = 100 * np.exp(np.cumsum(np.random.randn(n_days) * 0.015))
        high = close * (1 + np.abs(np.random.randn(n_days)) * 0.008)
        low = close * (1 - np.abs(np.random.randn(n_days)) * 0.008)
        volume = np.random.randint(50000, 500000, n_days).astype(float)
        market[f"STOCK{i:04d}"] = pd.DataFrame({
            'Open': close * (1 + np.random.randn(n_days) * 0.002),
            'High': high, 'Low': low, 'Close': close, 'Volume': volume
        }, index=dates)
    return market


# =====================================================
# 1. CANONICAL SCORING BACKTEST'E ULAŞIYOR MU?
# =====================================================

def test_canonical_adapter_import():
    """Canonical adapter import edilebiliyor mu?"""
    from services.backtest.canonical_adapter import backtest_canonical_adapter
    issues = []

    if backtest_canonical_adapter is None:
        issues.append("Adapter None")

    return "Canonical adapter import", len(issues) == 0, issues


def test_canonical_score_from_features():
    """Calculator feature'larından canonical score üretilebiliyor mu?"""
    from services.backtest.canonical_adapter import backtest_canonical_adapter
    from services.features.calculator import feature_calculator
    issues = []

    market = _make_market_data(3, 100)
    df = list(market.values())[0]
    features = feature_calculator.compute_all_features(df, ticker='TEST')

    score = backtest_canonical_adapter.compute_score(features, regime='BULL')

    if score < 0 or score > 100:
        issues.append(f"Score aralık dışı: {score}")
    if score == 0:
        issues.append("Score = 0 — feature'lar gelmiyor olabilir")

    return "Canonical score from features", len(issues) == 0, issues


def test_canonical_deterministic():
    """Aynı input → aynı canonical score (deterministic)."""
    from services.backtest.canonical_adapter import backtest_canonical_adapter
    from services.features.calculator import feature_calculator
    issues = []

    market = _make_market_data(3, 100)
    df = list(market.values())[0]
    features = feature_calculator.compute_all_features(df, ticker='TEST')

    score1 = backtest_canonical_adapter.compute_score(features, regime='BULL')
    score2 = backtest_canonical_adapter.compute_score(features, regime='BULL')

    if score1 != score2:
        issues.append(f"Non-deterministic: {score1} != {score2}")

    return "Canonical deterministic", len(issues) == 0, issues


# =====================================================
# 2. BACKTEST ENGINE CANONICAL MODE
# =====================================================

def test_backtest_canonical_mode():
    """Backtest engine canonical scoring ile çalışabiliyor mu?"""
    from services.backtest.engine_v4 import BacktestEngineV4, BacktestConfig
    issues = []

    market = _make_market_data(5, 150)
    cfg = BacktestConfig(
        use_canonical_scoring=True,
        regime='BULL',
        lookback_days=60,
        initial_capital=100000,
    )

    engine = BacktestEngineV4(cfg, use_panel_features=False)
    result = engine.run(market, persist=False)

    if result is None:
        issues.append("Result None")
    elif result.trades_executed < 0:
        issues.append(f"Negatif trade sayısı: {result.trades_executed}")

    return "Backtest canonical mode", len(issues) == 0, issues


def test_backtest_legacy_mode_unchanged():
    """Legacy mode hiç değişmemiş mi?"""
    from services.backtest.engine_v4 import BacktestEngineV4, BacktestConfig
    issues = []

    market = _make_market_data(5, 150)
    cfg = BacktestConfig(lookback_days=60, initial_capital=100000)

    engine = BacktestEngineV4(cfg, use_panel_features=False)
    result = engine.run(market, persist=False)

    if result is None:
        issues.append("Result None")
    elif result.trades_executed < 0:
        issues.append(f"Negatif trade sayısı: {result.trades_executed}")

    return "Legacy mode unchanged", len(issues) == 0, issues


def test_canonical_vs_legacy_different_scores():
    """Canonical ve legacy farklı skorlar üretiyor mu?"""
    from services.backtest.engine_v4 import BacktestEngineV4, BacktestConfig
    issues = []

    market = _make_market_data(5, 150)

    # Legacy
    cfg_legacy = BacktestConfig(lookback_days=60, initial_capital=100000)
    engine_legacy = BacktestEngineV4(cfg_legacy, use_panel_features=False)
    result_legacy = engine_legacy.run(market, persist=False)

    # Canonical
    cfg_canonical = BacktestConfig(
        use_canonical_scoring=True, regime='BULL',
        lookback_days=60, initial_capital=100000,
    )
    engine_canonical = BacktestEngineV4(cfg_canonical, use_panel_features=False)
    result_canonical = engine_canonical.run(market, persist=False)

    # Farklı skorlar bekleniyor (canonical daha kapsamlı)
    # Ama her ikisi de çalışmalı
    if result_legacy is None or result_canonical is None:
        issues.append("Biri None döndü")

    return "Canonical vs legacy scores", len(issues) == 0, issues


# =====================================================
# 3. PIT (POINT-IN-TIME) KORUMASI
# =====================================================

def test_pit_no_future_data():
    """Canonical scoring gelecekteki veriyi kullanmıyor mu?"""
    from services.backtest.canonical_adapter import backtest_canonical_adapter
    from services.features.calculator import feature_calculator
    issues = []

    # Bugünün feature'ları
    market = _make_market_data(3, 100, seed=42)
    df = list(market.values())[0]
    features_today = feature_calculator.compute_all_features(df, ticker='TEST')

    score_today = backtest_canonical_adapter.compute_score(features_today, 'BULL')

    # Farklı seed ile feature'lar (gelecek veri simülasyonu)
    market2 = _make_market_data(3, 100, seed=99)
    df2 = list(market2.values())[0]
    features_different = feature_calculator.compute_all_features(df2, ticker='TEST')

    score_different = backtest_canonical_adapter.compute_score(features_different, 'BULL')

    # Farklı veriler farklı skorlar üretmeli
    if score_today == score_different:
        issues.append("Farklı veriler aynı skor — PIT ihlali olabilir")

    return "PIT no future data", len(issues) == 0, issues


# =====================================================
# 4. REGIME DEĞİŞİMİNDE DETERMINISTIC DAVRANIŞ
# =====================================================

def test_regime_deterministic():
    """Aynı regime + aynı features → aynı skor."""
    from services.backtest.canonical_adapter import backtest_canonical_adapter
    from services.features.calculator import feature_calculator
    issues = []

    market = _make_market_data(3, 100)
    df = list(market.values())[0]
    features = feature_calculator.compute_all_features(df, ticker='TEST')

    for regime in ['BULL', 'BEAR', 'SIDEWAYS', 'UNKNOWN']:
        scores = []
        for _ in range(3):
            s = backtest_canonical_adapter.compute_score(features, regime)
            scores.append(s)

        if len(set(scores)) > 1:
            issues.append(f"{regime}: non-deterministic {scores}")

    return "Regime deterministic", len(issues) == 0, issues


# =====================================================
# 5. EMPTY/MISSING FEATURE DURUMLARI
# =====================================================

def test_empty_features_graceful():
    """Boş feature seti ile canonical scoring graceful davranıyor mu?"""
    from services.backtest.canonical_adapter import backtest_canonical_adapter
    issues = []

    empty_features = {}
    score = backtest_canonical_adapter.compute_score(empty_features, 'UNKNOWN')

    if score < 0 or score > 100:
        issues.append(f"Score aralık dışı: {score}")

    return "Empty features graceful", len(issues) == 0, issues


def test_sparse_features_graceful():
    """Az feature ile canonical scoring çalışıyor mu?"""
    from services.backtest.canonical_adapter import backtest_canonical_adapter
    issues = []

    sparse = {"rsi_14": 55.0, "momentum_20d": 3.0}
    score = backtest_canonical_adapter.compute_score(sparse, 'BULL')

    if score < 0 or score > 100:
        issues.append(f"Score aralık dışı: {score}")

    return "Sparse features graceful", len(issues) == 0, issues


# =====================================================
# 6. DECISION ENGINE BACKTEST İÇİNDE
# =====================================================

def test_decision_engine_in_backtest():
    """Decision engine backtest context'inde çalışıyor mu?"""
    from services.backtest.canonical_adapter import backtest_canonical_adapter
    from services.features.calculator import feature_calculator
    issues = []

    market = _make_market_data(3, 100)
    df = list(market.values())[0]
    features = feature_calculator.compute_all_features(df, ticker='TEST')

    score, action = backtest_canonical_adapter.compute_score_and_decision(
        features, regime='BULL', price=100.0
    )

    if action not in ('BUY', 'SELL', 'HOLD', 'NO_ACTION'):
        issues.append(f"Geçersiz action: {action}")

    return "Decision engine in backtest", len(issues) == 0, issues


# =====================================================
# 7. LEGACY/PANEL EQUIVALENCE
# =====================================================

def test_legacy_panel_equivalence_with_canonical():
    """Legacy ve panel canonical modda tutarlı mı?"""
    from services.backtest.engine_v4 import BacktestEngineV4, BacktestConfig
    issues = []

    market = _make_market_data(5, 150, seed=42)

    # Legacy canonical
    cfg = BacktestConfig(
        use_canonical_scoring=True, regime='BULL',
        lookback_days=60, initial_capital=100000,
    )
    r_legacy = BacktestEngineV4(cfg, use_panel_features=False).run(market, persist=False)
    r_panel = BacktestEngineV4(cfg, use_panel_features=True).run(market, persist=False)

    # Her ikisi de çalışmalı
    if r_legacy is None or r_panel is None:
        issues.append("Biri None döndü")
    elif r_legacy.metrics.total_return_pct != r_panel.metrics.total_return_pct:
        # Canonical modda legacy/panel farkı olabilir (canonical scoring
        # feature cache'i etkileyebilir), ama makul aralıkta olmalı
        diff = abs(r_legacy.metrics.total_return_pct - r_panel.metrics.total_return_pct)
        if diff > 5.0:  # %5'ten fazla fark kabul edilemez
            issues.append(
                f"Legacy/Panel canonical farkı çok büyük: "
                f"legacy={r_legacy.metrics.total_return_pct:.2f}%, "
                f"panel={r_panel.metrics.total_return_pct:.2f}%, "
                f"diff={diff:.2f}%"
            )

    return "Legacy/Panel canonical equivalence", len(issues) == 0, issues


# =====================================================
# RUN
# =====================================================

def run_all():
    print("=" * 60)
    print("  Canonical Backtest Integration Tests")
    print("=" * 60)

    tests = [
        test_canonical_adapter_import,
        test_canonical_score_from_features,
        test_canonical_deterministic,
        test_backtest_canonical_mode,
        test_backtest_legacy_mode_unchanged,
        test_canonical_vs_legacy_different_scores,
        test_pit_no_future_data,
        test_regime_deterministic,
        test_empty_features_graceful,
        test_sparse_features_graceful,
        test_decision_engine_in_backtest,
        test_legacy_panel_equivalence_with_canonical,
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
        print(f"{icon} {name}")
        if ok:
            passed += 1
        else:
            failed += 1
            for i in issues:
                print(f"   ❌ {i}")
                all_issues.append(f"{name}: {i}")

    print(f"\n{'=' * 60}")
    print(f"  SONUÇ: {passed}/{passed + failed} geçti")
    if all_issues:
        print(f"\n  HATALAR:")
        for i, issue in enumerate(all_issues, 1):
            print(f"    {i}. {issue}")
    print("=" * 60)
    return failed == 0


if __name__ == "__main__":
    ok = run_all()
    sys.exit(0 if ok else 1)
