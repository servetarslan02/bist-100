#!/usr/bin/env python3
"""
ALPHA BIST — Feature Contract Mapping Tests

Her canonical mapping için integration test:
- Motor feature'ı gerçekten RankingModel'a ulaşıyor
- Alias doğru değeri taşıyor
- Missing feature sessizce 0 olmuyor
- Feature collision sessiz overwrite yapmıyor
- Cross-sectional return feature'ları gerçekten doluyor
"""

import sys
import os
import numpy as np
import pandas as pd
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# =====================================================
# HELPERS
# =====================================================

def _make_test_data(n=250, seed=42):
    """Test verisi oluştur."""
    np.random.seed(seed)
    dates = pd.date_range(end=datetime.now(), periods=n, freq='B')
    close = 100 * np.exp(np.cumsum(np.random.randn(n) * 0.015))
    high = close * (1 + np.abs(np.random.randn(n)) * 0.008)
    low = close * (1 - np.abs(np.random.randn(n)) * 0.008)
    open_ = close * (1 + np.random.randn(n) * 0.002)
    volume = np.random.randint(50000, 500000, n).astype(float)
    df = pd.DataFrame({
        'Open': open_, 'High': high, 'Low': low,
        'Close': close, 'Volume': volume
    }, index=dates)
    return df, close, high, low, open_, volume


def _make_fundamentals():
    """Test fundamental verisi."""
    return {
        'pe_ratio': 10, 'pb_ratio': 1.5, 'ev_ebitda': 5,
        'fcf_yield': 0.08, 'dividend_yield': 0.03,
        'roe': 0.15, 'roa': 0.10, 'roic': 0.12,
        'profit_margin': 0.12, 'gross_margin': 0.35, 'operating_margin': 0.18,
        'debt_to_equity': 0.4, 'current_ratio': 2.1,
        'free_cash_flow': 5e9, 'revenue': 50e9,
        'market_cap': 100e9, 'total_assets': 80e9,
        'revenue_growth': 0.15, 'earnings_growth': 0.20, 'fcf_growth': 0.18,
    }


def _make_kap_events():
    """Test KAP verisi."""
    return [{
        'category': 'FINANCIAL_REPORT', 'importance': 0.9, 'sentiment': 0.5,
        'date': '2026-08-10', 'publish_date': '2026-08-10',
        'title': 'Test finansal rapor', 'summary': 'Olumlu sonuçlar',
    }]


def _make_news_events():
    """Test haber verisi."""
    return [{
        'title': 'Test haber', 'sentiment': 0.3, 'importance': 0.7,
        'published': '2026-08-10', 'source': 'test', 'date': '2026-08-10',
    }]


# =====================================================
# 1. NAME MISMATCH ALIAS TESTS
# =====================================================

def test_alias_rs_peer_rank():
    """rs_peer_rank alias'ı rs_peer_rank_5d'den geliyor mu?"""
    from services.features.seven_motors import seven_motor_engine
    issues = []

    df, close, high, low, open_, volume = _make_test_data()
    m1 = seven_motor_engine.motor1.compute('TEST', close, close, close, {'P': close})

    # Ham çıktı
    if 'rs_peer_rank_5d' not in m1:
        issues.append("Motor1 rs_peer_rank_5d üretmiyor")
        return "Alias: rs_peer_rank", False, issues

    # Alias testi
    all_features = seven_motor_engine.compute_all(
        'TEST', df, benchmark_close=close, peer_closes={'P': close}
    )
    if 'rs_peer_rank' not in all_features:
        issues.append(f"rs_peer_rank alias'ı oluşmadı (rs_peer_rank_5d={m1.get('rs_peer_rank_5d')})")
    elif all_features['rs_peer_rank'] != m1['rs_peer_rank_5d']:
        issues.append(f"Alias değeri yanlış: {all_features['rs_peer_rank']} != {m1['rs_peer_rank_5d']}")

    return "Alias: rs_peer_rank", len(issues) == 0, issues


def test_alias_volume_percentile():
    """volume_percentile alias'ı volume_percentile_20d'den geliyor mu?"""
    from services.features.seven_motors import seven_motor_engine
    issues = []

    df, close, high, low, open_, volume = _make_test_data()
    all_features = seven_motor_engine.compute_all('TEST', df)

    if 'volume_percentile_20d' not in all_features:
        issues.append("Motor3 volume_percentile_20d üretmiyor")
        return "Alias: volume_percentile", False, issues

    if 'volume_percentile' not in all_features:
        issues.append("volume_percentile alias'ı oluşmadı")
    elif all_features['volume_percentile'] != all_features['volume_percentile_20d']:
        issues.append(f"Alias değeri yanlış")

    return "Alias: volume_percentile", len(issues) == 0, issues


def test_alias_volume_up_down_ratio():
    """volume_up_down_ratio alias'ı volume_up_down_ratio_20d'den geliyor mu?"""
    from services.features.seven_motors import seven_motor_engine
    issues = []

    df, close, high, low, open_, volume = _make_test_data()
    all_features = seven_motor_engine.compute_all('TEST', df)

    if 'volume_up_down_ratio' not in all_features:
        issues.append("volume_up_down_ratio alias'ı oluşmadı")

    return "Alias: volume_up_down_ratio", len(issues) == 0, issues


def test_alias_tick_rule():
    """tick_rule alias'ı tick_rule_20d'den geliyor mu?"""
    from services.features.seven_motors import seven_motor_engine
    issues = []

    df, close, high, low, open_, volume = _make_test_data()
    all_features = seven_motor_engine.compute_all('TEST', df)

    if 'tick_rule' not in all_features:
        issues.append("tick_rule alias'ı oluşmadı")

    return "Alias: tick_rule", len(issues) == 0, issues


def test_alias_vwap_deviation():
    """vwap_deviation alias'ı vwap_deviation_20d'den geliyor mu?"""
    from services.features.seven_motors import seven_motor_engine
    issues = []

    df, close, high, low, open_, volume = _make_test_data()
    all_features = seven_motor_engine.compute_all('TEST', df)

    if 'vwap_deviation' not in all_features:
        issues.append("vwap_deviation alias'ı oluşmadı")

    return "Alias: vwap_deviation", len(issues) == 0, issues


def test_alias_fundamental_names():
    """Motor4 raw_* → canonical isim alias'ları çalışıyor mu?"""
    from services.features.seven_motors import seven_motor_engine
    issues = []

    fund = _make_fundamentals()
    m4 = seven_motor_engine.motor4.compute('TEST', fund)

    # raw_roe → roe
    if 'raw_roe' not in m4:
        issues.append("Motor4 raw_roe üretmiyor")
    # raw_roa → roa
    if 'raw_roa' not in m4:
        issues.append("Motor4 raw_roa üretmiyor")
    # raw_profit_margin → profit_margin_pct
    if 'raw_profit_margin' not in m4:
        issues.append("Motor4 raw_profit_margin üretmiyor")

    # Full pipeline alias testi
    df, close, high, low, open_, volume = _make_test_data()
    all_features = seven_motor_engine.compute_all(
        'TEST', df, fundamentals=fund
    )

    if 'roe' not in all_features:
        issues.append("roe alias'ı oluşmadı")
    elif all_features['roe'] != m4['raw_roe']:
        issues.append(f"roe alias değeri yanlış")

    if 'roa' not in all_features:
        issues.append("roa alias'ı oluşmadı")

    if 'profit_margin_pct' not in all_features:
        issues.append("profit_margin_pct alias'ı oluşmadı")

    return "Alias: Fundamental names", len(issues) == 0, issues


# =====================================================
# 2. CROSS-SECTIONAL RETURN MAPPING
# =====================================================

def test_return_alias_mapping():
    """return_5d/20d/60d → roc_5d/20d/60d mapping çalışıyor mu?"""
    from services.features.seven_motors import seven_motor_engine
    issues = []

    df, close, high, low, open_, volume = _make_test_data()
    all_features = seven_motor_engine.compute_all('TEST', df)

    for period in [1, 5, 20, 60]:
        roc_key = f'roc_{period}d'
        ret_key = f'return_{period}d'

        if roc_key not in all_features:
            issues.append(f"{roc_key} üretilmiyor")
            continue

        if ret_key not in all_features:
            issues.append(f"{ret_key} alias'ı oluşmadı (kaynak: {roc_key})")
        elif all_features[ret_key] != all_features[roc_key]:
            issues.append(f"{ret_key} değeri {roc_key} ile eşleşmiyor")

    return "Return alias mapping", len(issues) == 0, issues


# =====================================================
# 3. FEATURE COLLISION DETECTION
# =====================================================

def test_calculator_canonical_preserved():
    """Calculator canonical feature'ları motor tarafından ezilmiyor mu?"""
    from services.features.calculator import feature_calculator
    from services.features.seven_motors import seven_motor_engine
    from services.core.orchestrator import SystemOrchestrator
    issues = []

    df, close, high, low, open_, volume = _make_test_data()

    # Calculator feature'ları
    calc_features = feature_calculator.compute_all_features(df, ticker='TEST')

    # Motor feature'ları
    motor_features = seven_motor_engine.compute_all('TEST', df)

    # Collision kontrolü
    orch = SystemOrchestrator()
    canonical = orch._CALCULATOR_CANONICAL

    collisions = []
    for key in canonical:
        if key in calc_features and key in motor_features:
            if calc_features[key] != motor_features[key]:
                collisions.append(key)

    if collisions:
        # Merge sonrası calculator değerleri korunmalı
        merged = orch._merge_features(calc_features, motor_features, 'TEST')
        for key in collisions:
            if merged.get(key) != calc_features[key]:
                issues.append(
                    f"Calculator canonical '{key}' ezildi: "
                    f"calc={calc_features[key]}, motor={motor_features[key]}, merged={merged.get(key)}"
                )

    if not issues:
        return "Collision detection", True, []
    return "Collision detection", False, issues


def test_no_silent_overwrite():
    """Motor feature'ı calculator'da yoksa ekleniyor mu (overwrite değil)?"""
    from services.features.seven_motors import seven_motor_engine
    from services.core.orchestrator import SystemOrchestrator
    issues = []

    df, close, high, low, open_, volume = _make_test_data()

    calc_features = {'rsi_14': 55.0, 'test_calc_only': 1.0}
    motor_features = {'rsi_14': 65.0, 'test_motor_only': 2.0, 'trend_slope_20d': 0.5}

    orch = SystemOrchestrator()
    merged = orch._merge_features(calc_features, motor_features, 'TEST')

    # rsi_14 calculator canonical → calculator değeri korunmalı
    if merged.get('rsi_14') != 55.0:
        issues.append(f"rsi_14 ezildi: {merged.get('rsi_14')} != 55.0")

    # test_motor_only eklenmeli
    if merged.get('test_motor_only') != 2.0:
        issues.append(f"test_motor_only eklenmedi: {merged.get('test_motor_only')}")

    # test_calc_only korunmalı
    if merged.get('test_calc_only') != 1.0:
        issues.append(f"test_calc_only kayboldu")

    return "No silent overwrite", len(issues) == 0, issues


# =====================================================
# 4. MISSING FEATURE DETECTION
# =====================================================

def test_missing_features_not_zero():
    """Ranking model'in beklediği ama üretilmeyen feature'lar tespit ediliyor mu?"""
    from services.ml.ranking_model import ranking_model
    from services.features.calculator import feature_calculator
    from services.features.seven_motors import seven_motor_engine
    issues = []

    df, close, high, low, open_, volume = _make_test_data()
    fund = _make_fundamentals()
    kap = _make_kap_events()
    news = _make_news_events()

    # Calculator + Motors (gerçek pipeline gibi)
    calc_features = feature_calculator.compute_all_features(df, ticker='TEST')
    motor_features = seven_motor_engine.compute_all(
        'TEST', df, benchmark_close=close,
        fundamentals=fund, kap_events=kap, news_events=news,
        upcoming_events=[{'type': 'EARNINGS', 'importance': 0.9, 'days_until': 5}],
    )
    all_features = {**calc_features, **motor_features}

    # Hangileri eksik?
    missing = []
    conditional = []  # Dış veri veya koşul gerektiren

    # Dış veri gerektiren feature'lar (sector/peer/benchmark)
    needs_external = {
        'rs_vs_bist_1d', 'rs_vs_bist_5d', 'rs_vs_bist_20d', 'rs_vs_bist_60d',
        'rs_vs_sector_5d', 'rs_vs_peers_5d', 'rs_trend', 'rs_peer_rank',
        'sector_norm_pe_ratio', 'sector_norm_pb_ratio',
        'sector_rel_return_5d', 'sector_zscore_momentum_20d',
    }

    # Koşullu feature'lar (sadece belirli durumlarda üretilir)
    conditional_features = {
        'recovery_strength',       # drawdown >5% gerekti
        'sentiment_momentum',      # yeterli event gerekti
        'fall_market_selloff',     # hisse düşmeli
        'fall_sector_selloff',     # hisse düşmeli
        'breakout_failure',        # breakout koşulu gerekti
    }

    for feat_name in ranking_model._feature_names:
        val = all_features.get(feat_name)
        if val is None:
            # Cross-sectional output
            if feat_name.startswith(('rank_', 'cs_zscore_', 'sector_rel_', 'sector_zscore_',
                                      'sector_rank_', 'market_breadth', 'market_ad_ratio',
                                      'market_advancing', 'market_declining')):
                continue
            if feat_name in needs_external:
                conditional.append(feat_name)
                continue
            if feat_name in conditional_features:
                conditional.append(feat_name)
                continue
            missing.append(feat_name)

    if missing:
        issues.append(f"Üretilmemiş ({len(missing)}): {', '.join(missing)}")
    if conditional:
        issues.append(f"Dış veri gerektiren ({len(conditional)}): {', '.join(conditional)}")

    # Not: Koşullu feature'lar (drawdown yoksa recovery_strength üretilmez, vb.)
    # sağlıklıdır —0 yerineNone olması daha güvenli.
    return "Missing feature detection", len(missing) == 0, issues


# =====================================================
# 5. RANKING MODEL FEATURE VECTOR
# =====================================================

def test_ranking_feature_vector_nonzero():
    """Ranking model feature vektöründe kaç feature gerçekten dolu?"""
    from services.ml.ranking_model import ranking_model
    from services.features.calculator import feature_calculator
    from services.features.seven_motors import seven_motor_engine
    issues = []

    df, close, high, low, open_, volume = _make_test_data()
    fund = _make_fundamentals()

    # Calculator + Motors (gerçek pipeline gibi)
    calc_features = feature_calculator.compute_all_features(df, ticker='TEST')
    motor_features = seven_motor_engine.compute_all(
        'TEST', df, benchmark_close=close,
        fundamentals=fund, kap_events=_make_kap_events(), news_events=_make_news_events(),
    )
    all_features = {**calc_features, **motor_features}

    # Feature vektörü
    vec = ranking_model._feature_vector(all_features)
    nonzero = sum(1 for v in vec if v != 0)
    total = len(vec)

    # Dış veri gerektiren feature'ları hariç tut
    needs_external = {
        'rs_vs_bist_1d', 'rs_vs_bist_5d', 'rs_vs_bist_20d', 'rs_vs_bist_60d',
        'rs_vs_sector_5d', 'rs_vs_peers_5d', 'rs_trend', 'rs_peer_rank',
        'sector_norm_pe_ratio', 'sector_norm_pb_ratio',
        'rank_return_5d', 'rank_return_20d', 'rank_volume_zscore', 'rank_rsi_14',
        'sector_rel_return_5d', 'sector_zscore_momentum_20d',
        'cs_zscore_roc_5d', 'cs_zscore_roc_20d',
        'market_breadth', 'market_ad_ratio',
    }
    effective_total = sum(1 for n in ranking_model._feature_names if n not in needs_external)
    effective_nonzero = sum(
        1 for n, v in zip(ranking_model._feature_names, vec)
        if v != 0 and n not in needs_external
    )

    pct = effective_nonzero / effective_total * 100 if effective_total > 0 else 0
    if pct < 60:
        issues.append(f"Feature vektörü çok boş: {effective_nonzero}/{effective_total} ({pct:.0f}%)")

    # Hangileri hiç üretilmemiş (None)?
    conditional_features = {
        'recovery_strength', 'sentiment_momentum',
        'fall_market_selloff', 'fall_sector_selloff', 'breakout_failure',
    }
    not_produced = [
        name for name in ranking_model._feature_names
        if all_features.get(name) is None
        and name not in needs_external
        and name not in conditional_features
    ]
    if not_produced:
        issues.append(f"Üretilmemiş ({len(not_produced)}): {', '.join(not_produced[:10])}")

    return "Ranking feature vector", len(issues) == 0, issues


# =====================================================
# 6. INTEGRATION: MOTOR → RANKING
# =====================================================

def test_motor_to_ranking_flow():
    """Motor feature'ları gerçekten ranking model'e ulaşıyor mu?"""
    from services.ml.ranking_model import ranking_model
    from services.features.seven_motors import seven_motor_engine
    issues = []

    df, close, high, low, open_, volume = _make_test_data()
    fund = _make_fundamentals()

    all_features = seven_motor_engine.compute_all(
        'TEST', df, benchmark_close=close,
        fundamentals=fund, kap_events=_make_kap_events(), news_events=_make_news_events(),
    )

    # Rule-based score hesapla
    score = ranking_model._rule_based_score(all_features, 'BULL')

    if score == 50.0:
        issues.append("Score tam50.0 — hiçbir feature katkı yapmıyor olabilir")
    elif score < 0 or score > 100:
        issues.append(f"Score aralık dışı: {score}")

    # Rank fonksiyonu çalışmalı
    features_map = {'TEST': all_features, 'TEST2': all_features}
    try:
        result = ranking_model.rank(features_map, regime='BULL')
        if len(result.scores) != 2:
            issues.append(f"Rank sonucu yanlış: {len(result.scores)} != 2")
    except Exception as e:
        issues.append(f"Rank çalışmadı: {e}")

    return "Motor → Ranking flow", len(issues) == 0, issues


# =====================================================
# RUN
# =====================================================

def run_all():
    print("=" * 60)
    print("  Feature Contract Mapping Tests")
    print("=" * 60)

    tests = [
        test_alias_rs_peer_rank,
        test_alias_volume_percentile,
        test_alias_volume_up_down_ratio,
        test_alias_tick_rule,
        test_alias_vwap_deviation,
        test_alias_fundamental_names,
        test_return_alias_mapping,
        test_calculator_canonical_preserved,
        test_no_silent_overwrite,
        test_missing_features_not_zero,
        test_ranking_feature_vector_nonzero,
        test_motor_to_ranking_flow,
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
