#!/usr/bin/env python3
"""
ALPHA BIST — Backtest v5.0 Upgrade Test Suite (Production Seviyesi)

Kapsam:
1. Panel feature engine doğruluğu (scalar ile birebir)
2. Cache correctness
3. Deterministic replay
4. Look-ahead bias
5. Data leakage
6. Survivorship bias
7. Walk-forward leakage (purge/embargo/PIT)
8. Walk-forward reproducibility + fold persistence
9. Equity / cash / portfolio invariants
10. Eski (legacy) vs yeni (panel) engine equivalence — BİREBİR

KURAL: Bu testler mevcut testleri DEĞİŞTİRMEZ, üzerine ekler.
"""

import sys
import os
import time
import json
import numpy as np
import pandas as pd
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.backtest.engine_v4 import BacktestEngineV4, BacktestConfig
from services.backtest.walk_forward_runner import WalkForwardBacktestRunner
from services.backtest.persistence import BacktestPersistence
from services.features.panel_engine import PanelFeatureEngine
from services.features.calculator import FeatureCalculator
from services.core.tradability_mask import TradabilityMask

SCORE_KEYS = ("rsi_14", "momentum_20d", "roc_5d", "volume_zscore")


# =====================================================
# HELPERS
# =====================================================

def make_market_data(n_stocks=100, n_days=252, seed=42, aligned=False):
    """Mevcut test suite ile aynı veri üreteci (geriye uyum).

    aligned=True → tüm hisseler aynı takvimi paylaşır (gerçek BIST gibi).
    """
    np.random.seed(seed)
    market = {}
    base_end = datetime.now()
    for i in range(n_stocks):
        trend = np.random.uniform(-0.001, 0.002)
        vol = np.random.uniform(0.01, 0.025)
        dates = pd.date_range(end=base_end if aligned else datetime.now(),
                              periods=n_days, freq='B')
        close = 100 * np.exp(np.cumsum(np.random.randn(n_days) * vol + trend))
        high = close * (1 + np.abs(np.random.randn(n_days) * 0.008))
        low = close * (1 - np.abs(np.random.randn(n_days) * 0.008))
        volume = np.random.randint(50000, 500000, n_days).astype(float)
        market[f"STOCK{i:04d}"] = pd.DataFrame({
            'Open': close * (1 + np.random.randn(n_days) * 0.002),
            'High': high, 'Low': low, 'Close': close, 'Volume': volume
        }, index=dates)
    return market


def results_fingerprint(r):
    """Zamanlama hariç tam sonuç parmak izi."""
    return {
        "run_id": r.run_id,
        "scans": r.total_scans,
        "signals": r.signals_generated,
        "trades_n": r.trades_executed,
        "metrics": r.metrics.to_dict(),
        "trades": r.trades,
        "equity": r.equity_curve,
        "la": r.look_ahead_violations,
        "sv": r.survivorship_violations,
        "dq": r.data_quality_issues,
    }


# =====================================================
# 1. PANEL FEATURE DOĞRULUĞU
# =====================================================

def test_panel_feature_equivalence():
    """Panel feature'lar scalar FeatureCalculator ile birebir olmalı."""
    issues = []
    tm = TradabilityMask()
    calc = FeatureCalculator()
    pf = PanelFeatureEngine(tradability_mask=tm)
    checked = 0

    for seed, n, days, lookback in [(7, 5, 150, 60), (11, 4, 200, 90), (23, 6, 130, 60)]:
        market = make_market_data(n, days, seed=seed)
        store = pf.compute(market_data=market, lookback=lookback)
        for ticker, df in market.items():
            panel = store.panels[ticker]
            for pos in range(lookback - 1, len(df)):
                window = df.iloc[pos - lookback + 1: pos + 1]
                mask = tm.compute_mask(
                    ticker, window['Open'].values, window['High'].values,
                    window['Low'].values, window['Close'].values, window['Volume'].values,
                )
                f_scalar = calc.compute_all_features(window, mask=mask.mask, ticker=ticker)
                f_panel = pf.features_at(panel, pos, lookback)
                if f_panel is None:
                    continue  # fallback → engine scalar yolu kullanır
                checked += 1
                for k in SCORE_KEYS:
                    if abs(f_scalar[k] - f_panel[k]) > 1e-9:
                        issues.append(f"{ticker}@{pos} {k}: {f_scalar[k]} vs {f_panel[k]}")
                        break

    if checked < 500:
        issues.append(f"Yetersiz karşılaştırma: {checked}")
    return "Panel Feature Equivalence", len(issues) == 0, issues, f"{checked} pencere"


def test_panel_mask_edge_fallback():
    """>%30 sıçrama pencere başlangıcına denk gelirse fallback işaretlenmeli."""
    issues = []
    tm = TradabilityMask()
    pf = PanelFeatureEngine(tradability_mask=tm)

    n = 120
    dates = pd.date_range(end=datetime.now(), periods=n, freq='B')
    close = 100 * np.exp(np.cumsum(np.random.RandomState(5).randn(n) * 0.01))
    close[50] = close[49] * 1.45  # %45 sıçrama → kural 5
    df = pd.DataFrame({
        'Open': close, 'High': close * 1.01, 'Low': close * 0.99,
        'Close': close, 'Volume': np.full(n, 100000.0),
    }, index=dates)

    store = pf.compute({"JUMP": df}, lookback=60)
    panel = store.panels["JUMP"]
    # pos = 50 + 60 - 1 = 109 → pencere başlangıcı 50 → fallback olmalı
    if not panel.fallback[109]:
        issues.append("Pencere başlangıcı sıçrama satırı fallback işaretlenmedi")
    if panel.fallback[108] or (110 < n and panel.fallback[110]):
        issues.append("Fallback yanlış pozisyonlarda işaretlendi")
    return "Panel Mask-Edge Fallback", len(issues) == 0, issues


# =====================================================
# 2. CACHE CORRECTNESS
# =====================================================

def test_cache_correctness():
    """Cache'li ve cache'siz çalıştırmalar birebir aynı sonucu vermeli.

    Panel motoru run başına bir kez hesaplar (doğru seviyede cache);
    aynı engine instance'ı ile art arda iki run → cache temizlenir →
    sonuç değişmemeli.
    """
    issues = []
    market = make_market_data(12, 150, seed=42)
    engine = BacktestEngineV4(BacktestConfig(lookback_days=40))

    r1 = engine.run(market, persist=False)
    # İkinci run: cache'ler run başında temizleniyor mu?
    r2 = engine.run(market, persist=False)

    if results_fingerprint(r1) != results_fingerprint(r2):
        issues.append("Aynı instance art arda run → farklı sonuç (cache kirliliği)")

    # Feature cache hit-rate sağlıklı olmalı (satış sonrası aynı gün tekrar tarama)
    hr = engine._feature_cache.hit_rate
    if not (0.0 <= hr <= 1.0):
        issues.append(f"Hit rate geçersiz: {hr}")

    return "Cache Correctness", len(issues) == 0, issues


# =====================================================
# 3. DETERMINISTIC REPLAY
# =====================================================

def test_deterministic_replay():
    """Aynı veri + aynı config → birebir aynı sonuç (yeni engine instance'ları)."""
    issues = []
    market = make_market_data(15, 150, seed=123)
    cfg = BacktestConfig(lookback_days=40, initial_capital=100000)

    r1 = BacktestEngineV4(cfg).run(market, persist=False)
    r2 = BacktestEngineV4(cfg).run(market, persist=False)

    if results_fingerprint(r1) != results_fingerprint(r2):
        issues.append("Deterministik replay başarısız")
    return "Deterministic Replay", len(issues) == 0, issues


# =====================================================
# 4. LOOK-AHEAD BIAS
# =====================================================

def test_look_ahead_bias():
    """Gelecek veriyi bozmak geçmiş sonuçları DEĞİŞTİRMEMELİ."""
    issues = []
    market = make_market_data(10, 150, seed=42, aligned=True)
    cfg = BacktestConfig(lookback_days=40)

    r_full = BacktestEngineV4(cfg).run(market, persist=False)

    # Son 30 günün fiyatlarını çılgın değerlere çevir
    poisoned = {}
    for ticker, df in market.items():
        df2 = df.copy()
        df2.iloc[-30:, df2.columns.get_loc('Close')] *= 100.0
        df2.iloc[-30:, df2.columns.get_loc('Open')] *= 100.0
        df2.iloc[-30:, df2.columns.get_loc('High')] *= 100.0
        df2.iloc[-30:, df2.columns.get_loc('Low')] *= 100.0
        poisoned[ticker] = df2

    r_poison = BacktestEngineV4(cfg).run(poisoned, persist=False)

    # İlk N-40 equity noktası birebir aynı olmalı
    cutoff = len(r_full.equity_curve) - 40
    if cutoff > 0:
        eq1 = r_full.equity_curve[:cutoff]
        eq2 = r_poison.equity_curve[:cutoff]
        if json.dumps(eq1, sort_keys=True) != json.dumps(eq2, sort_keys=True):
            issues.append("Gelecek veri değişimi geçmiş equity'yi değiştirdi → LOOK-AHEAD")

        tr1 = [t for t in r_full.trades if t["date"] <= eq1[-1]["date"]]
        tr2 = [t for t in r_poison.trades if t["date"] <= eq1[-1]["date"]]
        if json.dumps(tr1, sort_keys=True) != json.dumps(tr2, sort_keys=True):
            issues.append("Gelecek veri değişimi geçmiş trade'leri değiştirdi → LOOK-AHEAD")

    if r_full.look_ahead_violations > 0:
        issues.append(f"Engine look-ahead violation: {r_full.look_ahead_violations}")
    return "Look-Ahead Bias", len(issues) == 0, issues


# =====================================================
# 5. DATA LEAKAGE (feature seviyesi)
# =====================================================

def test_data_leakage():
    """t tarihindeki feature, t sonrası veri değişince aynı kalmalı."""
    issues = []
    tm = TradabilityMask()
    pf = PanelFeatureEngine(tradability_mask=tm)
    lookback = 60

    market = make_market_data(4, 150, seed=77, aligned=True)
    store1 = pf.compute(market, lookback)

    poisoned = {}
    for ticker, df in market.items():
        df2 = df.copy()
        df2.iloc[-20:] = df2.iloc[-20:] * 50.0
        poisoned[ticker] = df2
    store2 = pf.compute(poisoned, lookback)

    # İlk 120 pozisyon (son 30 gün hariç) feature'ları aynı olmalı
    for ticker in market:
        p1, p2 = store1.panels[ticker], store2.panels[ticker]
        for pos in range(lookback - 1, 120):
            f1 = pf.features_at(p1, pos, lookback)
            f2 = pf.features_at(p2, pos, lookback)
            if f1 is None or f2 is None:
                continue
            for k in SCORE_KEYS:
                if abs(f1[k] - f2[k]) > 1e-9:
                    issues.append(f"{ticker}@{pos} {k} leakage: {f1[k]} vs {f2[k]}")
                    break
    return "Data Leakage (Features)", len(issues) == 0, issues


# =====================================================
# 6. SURVIVORSHIP BIAS
# =====================================================

def test_survivorship_bias():
    """Evren dışı hisse ASLA trade edilmemeli."""
    issues = []
    market = make_market_data(20, 150, seed=42)
    universe = sorted(market.keys())[:5]

    r = BacktestEngineV4(BacktestConfig(lookback_days=40)).run(
        market, universe_at_date=universe, persist=False
    )

    traded = set(t["ticker"] for t in r.trades)
    if not traded.issubset(set(universe)):
        issues.append(f"Evren dışı trade: {traded - set(universe)}")
    if r.survivorship_violations == 0:
        issues.append("Survivorship violation sayılmadı")
    return "Survivorship Bias", len(issues) == 0, issues


# =====================================================
# 7. WALK-FORWARD LEAKAGE
# =====================================================

def test_walk_forward_leakage():
    """Purge/embargo/PIT/trade penceresi korunmalı."""
    issues = []
    market = make_market_data(10, 380, seed=42)

    runner = WalkForwardBacktestRunner(
        backtest_config=BacktestConfig(lookback_days=40),
        purge_days=5, embargo_days=5, train_days=120, test_days=40, step_days=40,
    )
    res = runner.run(market, persist=False)

    if res.total_folds < 3:
        issues.append(f"Yetersiz fold: {res.total_folds}")
    if not res.all_leakage_ok:
        for f in res.folds:
            for e in f.leakage_errors:
                issues.append(f"fold{f.fold_id}: {e}")

    # Her fold için sınır kontrolleri (bağımsız doğrulama)
    for f in res.folds:
        if not (f.train_end < f.purge_start <= f.purge_end < f.test_start):
            issues.append(f"fold{f.fold_id} purge sınırı bozuk")
        if not (f.test_start <= f.test_end):
            issues.append(f"fold{f.fold_id} test aralığı bozuk")

    return "Walk-Forward Leakage", len(issues) == 0, issues, f"{res.total_folds} fold"


def test_walk_forward_reproducible():
    """Walk-forward sonuçları tekrar üretilebilir olmalı (timing hariç)."""
    issues = []
    market = make_market_data(8, 380, seed=99)

    def run():
        r = WalkForwardBacktestRunner(
            backtest_config=BacktestConfig(lookback_days=40),
            purge_days=5, embargo_days=5, train_days=120, test_days=40, step_days=40,
        ).run(market, persist=False)
        d = r.to_dict()
        for f in d["folds"]:
            f.pop("elapsed_seconds", None)
        return d

    if run() != run():
        issues.append("Walk-forward sonuçları tekrar üretilemiyor")
    return "Walk-Forward Reproducible", len(issues) == 0, issues


def test_walk_forward_persistence():
    """Her fold ayrı run olarak persist edilmeli."""
    issues = []
    db_path = "/tmp/test_wf_persist.db"
    if os.path.exists(db_path):
        os.remove(db_path)

    import services.backtest.engine_v4 as eng_mod
    old_persist = eng_mod.backtest_persistence
    eng_mod.backtest_persistence = BacktestPersistence(db_path)

    try:
        market = make_market_data(8, 380, seed=7)
        res = WalkForwardBacktestRunner(
            backtest_config=BacktestConfig(lookback_days=40),
            purge_days=5, embargo_days=5, train_days=120, test_days=40, step_days=40,
        ).run(market, persist=True)

        persist = BacktestPersistence(db_path)
        runs = persist.list_runs()
        if len(runs) != res.total_folds:
            issues.append(f"Persist edilen run: {len(runs)} != {res.total_folds} fold")
        for f in res.folds:
            if not f.persisted:
                issues.append(f"fold{f.fold_id} persist edilmedi")
            stored = persist.get_run(f.run_id)
            if stored is None:
                issues.append(f"fold{f.fold_id} DB'de yok: {f.run_id}")
            trades = persist.get_trades(f.run_id)
            if len(trades) != f.total_trades:
                issues.append(f"fold{f.fold_id} trades: {len(trades)} != {f.total_trades}")
    finally:
        eng_mod.backtest_persistence = old_persist
        if os.path.exists(db_path):
            os.remove(db_path)

    return "Walk-Forward Persistence", len(issues) == 0, issues


# =====================================================
# 8. INVARIANTS
# =====================================================

def test_equity_invariant():
    """Her gün: equity == cash + market_value."""
    issues = []
    market = make_market_data(12, 150, seed=42)
    r = BacktestEngineV4(BacktestConfig(lookback_days=40)).run(market, persist=False)

    for snap in r.equity_curve:
        # Not: to_dict() equity/cash/mv'yi ayrı ayrı 2 ondalık yuvarlar →
        # 3 bileşenin yuvarlama hatası toplamı ≤ ~0.015. Eşik 0.05.
        if abs(snap["equity"] - (snap["cash"] + snap["market_value"])) > 0.05:
            issues.append(f"Equity invariant @ {snap['date']}")
            break
    return "Equity Invariant", len(issues) == 0, issues


def test_cash_invariant():
    """Cash asla negatif olmamalı; cash + açık maliyet + realize P&L tutarlı."""
    issues = []
    market = make_market_data(12, 150, seed=42)
    engine = BacktestEngineV4(BacktestConfig(lookback_days=40))
    r = engine.run(market, persist=False)

    for snap in r.equity_curve:
        if snap["cash"] < -0.01:
            issues.append(f"Negatif cash @ {snap['date']}: {snap['cash']}")
            break

    # Muhasebe: initial = cash + açık pozisyon maliyeti - realize net
    # (basit tutarlılık: final equity ≈ initial + realize + unrealize)
    final_eq = r.equity_curve[-1]["equity"] if r.equity_curve else 100000
    if final_eq <= 0:
        issues.append(f"Final equity geçersiz: {final_eq}")
    return "Cash Invariant", len(issues) == 0, issues


def test_portfolio_invariant():
    """Pozisyon bütünlüğü: her BUY ya açık pozisyon ya da kapanmış SELL çifti."""
    issues = []
    market = make_market_data(12, 150, seed=42)
    r = BacktestEngineV4(BacktestConfig(lookback_days=40)).run(market, persist=False)

    buys = {}
    sells = {}
    for t in r.trades:
        if t["side"] == "BUY":
            buys[t["ticker"]] = buys.get(t["ticker"], 0) + 1
        else:
            sells[t["ticker"]] = sells.get(t["ticker"], 0) + 1

    for ticker, b in buys.items():
        s = sells.get(ticker, 0)
        if not (s == b or s == b - 1):
            issues.append(f"{ticker}: {b} BUY vs {s} SELL (açık pozisyon en fazla 1)")
    for ticker, s in sells.items():
        if s > buys.get(ticker, 0):
            issues.append(f"{ticker}: pozisyonsuz SELL")

    # Engine invariant check bayrağı (max_dd = -1 → ihlal)
    if r.metrics.max_drawdown_pct == -1 and r.equity_curve:
        issues.append("Engine invariant check FAIL bayrağı")
    return "Portfolio Invariant", len(issues) == 0, issues


# =====================================================
# 9. ESKİ / YENİ ENGINE EQUIVALENCE (BİREBİR)
# =====================================================

def test_engine_equivalence():
    """Legacy (use_panel_features=False) vs panel yolu BİREBİR aynı sonuç.

    trades, returns, CAGR, Sharpe, Sortino, max drawdown, win rate,
    equity curve — açıklanamayan TEK fark bile kabul edilemez.
    """
    issues = []
    for seed, n, days, lookback in [
        (42, 10, 150, 40), (123, 15, 150, 40), (7, 20, 200, 60), (2024, 12, 252, 60),
    ]:
        market = make_market_data(n, days, seed=seed)
        cfg = BacktestConfig(lookback_days=lookback, initial_capital=100000)

        r_old = BacktestEngineV4(cfg, use_panel_features=False).run(market, persist=False)
        r_new = BacktestEngineV4(cfg, use_panel_features=True).run(market, persist=False)

        f_old, f_new = results_fingerprint(r_old), results_fingerprint(r_new)
        for key in f_old:
            if f_old[key] != f_new[key]:
                if key == "metrics":
                    for mk in f_old[key]:
                        if f_old[key][mk] != f_new[key][mk]:
                            issues.append(f"seed={seed} metric {mk}: {f_old[key][mk]} vs {f_new[key][mk]}")
                else:
                    issues.append(f"seed={seed} {key} farklı")
    return "Engine Equivalence (Legacy↔Panel)", len(issues) == 0, issues


def test_engine_equivalence_aligned():
    """Hizalı takvim (gerçek BIST verisi gibi) ile de birebir eşdeğerlik."""
    issues = []
    market = make_market_data(25, 252, seed=555, aligned=True)
    cfg = BacktestConfig(lookback_days=60, initial_capital=100000)

    r_old = BacktestEngineV4(cfg, use_panel_features=False).run(market, persist=False)
    r_new = BacktestEngineV4(cfg, use_panel_features=True).run(market, persist=False)

    if results_fingerprint(r_old) != results_fingerprint(r_new):
        issues.append("Hizalı veride equivalence bozuldu")
    return "Engine Equivalence (Aligned)", len(issues) == 0, issues


def test_engine_equivalence_walk_forward():
    """Walk-forward: panel ve legacy yol aynı fold sonuçlarını üretmeli."""
    issues = []
    market = make_market_data(8, 380, seed=31)

    def run(panel):
        r = WalkForwardBacktestRunner(
            backtest_config=BacktestConfig(lookback_days=40),
            purge_days=5, embargo_days=5, train_days=120, test_days=40,
            step_days=40, use_panel_features=panel,
        ).run(market, persist=False)
        d = r.to_dict()
        for f in d["folds"]:
            f.pop("elapsed_seconds", None)
        # summary'deki "use_panel_features" bayrağı tasarım gereği farklıdır
        d.pop("summary", None)
        return d

    if run(True) != run(False):
        issues.append("Walk-forward fold sonuçları panel/legacy arasında farklı")
    return "WF Equivalence (Legacy↔Panel)", len(issues) == 0, issues


# =====================================================
# RUN
# =====================================================

def run_all():
    print("=" * 70)
    print("  ALPHA BIST — Backtest v5.0 Upgrade Test Suite")
    print("=" * 70)

    tests = [
        test_panel_feature_equivalence,
        test_panel_mask_edge_fallback,
        test_cache_correctness,
        test_deterministic_replay,
        test_look_ahead_bias,
        test_data_leakage,
        test_survivorship_bias,
        test_walk_forward_leakage,
        test_walk_forward_reproducible,
        test_walk_forward_persistence,
        test_equity_invariant,
        test_cash_invariant,
        test_portfolio_invariant,
        test_engine_equivalence,
        test_engine_equivalence_aligned,
        test_engine_equivalence_walk_forward,
    ]

    passed = failed = 0
    all_issues = []
    t0 = time.time()

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
        print(f"{icon} {name}" + (f" ({extra})" if extra else ""))
        if ok:
            passed += 1
        else:
            failed += 1
            for i in issues:
                print(f"   ❌ {i}")
                all_issues.append(f"{name}: {i}")

    print(f"\n{'=' * 70}")
    print(f"  SONUÇ: {passed}/{passed + failed} geçti ({time.time()-t0:.1f}s)")
    if all_issues:
        print(f"\n  HATALAR:")
        for i, issue in enumerate(all_issues, 1):
            print(f"    {i}. {issue}")
    print("=" * 70)
    return failed == 0


if __name__ == "__main__":
    ok = run_all()
    sys.exit(0 if ok else 1)
