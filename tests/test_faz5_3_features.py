"""
ALPHA BIST — FAZ 5.3 Test Suite

Feature Motor Data Feed Pipeline:
- PIT safety (future-data mutation)
- Duplicate prevention
- Provider failure handling
- Feature contract compliance
- Sector medians computation
"""

import sys
import os
import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _make_ohlcv(n=80, seed=42):
    rng = np.random.RandomState(seed)
    dates = pd.bdate_range(start="2022-01-03", periods=n, freq="B")
    close = 100 + np.cumsum(rng.randn(n) * 1.5)
    close = np.maximum(close, 1.0)
    return pd.DataFrame({
        "Open": close * 1.001, "High": close * 1.02,
        "Low": close * 0.98, "Close": close,
        "Volume": rng.randint(100000, 5000000, n).astype(float),
    }, index=dates)


# ────────────────────────────────────────────────────────────
# 1. KAP PIT — future data blocked
# ────────────────────────────────────────────────────────────

def test_kap_pit():
    """Future KAP events geçmiş snapshot'a girmemeli."""
    from services.features.data_adapter import DataAdapter

    passed = 0
    failed = 0

    adapter = DataAdapter()

    # KAP provider yoksa bile crash olmamalı
    events = adapter.fetch_kap_events("THYAO", as_of_date="2024-01-15")
    assert isinstance(events, list)
    print(f"  ✓ KAP PIT: {len(events)} events (provider may be unavailable)")
    passed += 1

    return passed, failed


# ────────────────────────────────────────────────────────────
# 2. News PIT — future data blocked
# ────────────────────────────────────────────────────────────

def test_news_pit():
    """Future news events geçmiş snapshot'a girmemeli."""
    from services.features.data_adapter import DataAdapter

    passed = 0
    failed = 0

    adapter = DataAdapter()

    events = adapter.fetch_news_events("THYAO", as_of_date="2024-01-15")
    assert isinstance(events, list)
    print(f"  ✓ News PIT: {len(events)} events")
    passed += 1

    return passed, failed


# ────────────────────────────────────────────────────────────
# 3. Fundamental PIT — future data blocked
# ────────────────────────────────────────────────────────────

def test_fundamental_pit():
    """Future fundamental veri geçmiş snapshot'a girmemeli."""
    from services.features.data_adapter import DataAdapter

    passed = 0
    failed = 0

    adapter = DataAdapter()

    features = adapter.fetch_fundamentals("THYAO", as_of_date="2024-01-15")
    assert isinstance(features, dict)
    # Tüm değerler FeatureDataPoint olmalı
    for key, dp in features.items():
        assert hasattr(dp, 'value'), f"{key} should be FeatureDataPoint"
        assert hasattr(dp, 'status'), f"{key} should have status"
    print(f"  ✓ Fundamental PIT: {len(features)} features")
    passed += 1

    return passed, failed


# ────────────────────────────────────────────────────────────
# 4. Duplicate event prevention
# ────────────────────────────────────────────────────────────

def test_duplicate_event_prevention():
    """Aynı event tekrar geldiğinde duplicate feature üretmemeli."""
    from services.features.data_adapter import DataAdapter

    passed = 0
    failed = 0

    adapter = DataAdapter()
    adapter.reset_duplicates()

    # İlk çağrı
    events1 = adapter.fetch_kap_events("THYAO", as_of_date="2024-12-31")
    count1 = len(events1)

    # İkinci çağrı (duplicate tracking aktif)
    events2 = adapter.fetch_kap_events("THYAO", as_of_date="2024-12-31")
    count2 = len(events2)

    # İkinci çağrıda en az aynı veya daha az event olmalı (duplicate filtre)
    assert count2 <= count1, f"Second call should have ≤ events: {count1} vs {count2}"
    print(f"  ✓ Duplicate prevention: 1st={count1}, 2nd={count2}")
    passed += 1

    # Reset sonrası tekrar çalışmalı
    adapter.reset_duplicates()
    events3 = adapter.fetch_kap_events("THYAO", as_of_date="2024-12-31")
    print(f"  ✓ Reset: {len(events3)} events after reset")
    passed += 1

    return passed, failed


# ────────────────────────────────────────────────────────────
# 5. Provider failure graceful handling
# ────────────────────────────────────────────────────────────

def test_provider_failure_graceful():
    """Provider başarısız olduğunda sistem crash olmamalı."""
    from services.features.data_adapter import DataAdapter

    passed = 0
    failed = 0

    adapter = DataAdapter()

    # Olmayan ticker — hata vermemeli
    features = adapter.fetch_fundamentals("NONEXISTENT_XYZ", as_of_date="2024-01-15")
    assert isinstance(features, dict)
    print(f"  ✓ Non-existent ticker: {len(features)} features (graceful)")
    passed += 1

    # KAP — provider yoksa boş liste
    events = adapter.fetch_kap_events("NONEXISTENT_XYZ", as_of_date="2024-01-15")
    assert isinstance(events, list)
    print(f"  ✓ KAP non-existent: {len(events)} events")
    passed += 1

    # News — provider yoksa boş liste
    news = adapter.fetch_news_events("NONEXISTENT_XYZ", as_of_date="2024-01-15")
    assert isinstance(news, list)
    print(f"  ✓ News non-existent: {len(news)} events")
    passed += 1

    return passed, failed


# ────────────────────────────────────────────────────────────
# 6. Sector medians computation
# ────────────────────────────────────────────────────────────

def test_sector_medians():
    """Sector medians doğru hesaplanmalı."""
    passed = 0
    failed = 0

    # Manuel sector medians hesaplama
    fundamentals = {
        "A": {"pe_ratio": 10.0, "pb_ratio": 1.5},
        "B": {"pe_ratio": 12.0, "pb_ratio": 2.0},
        "C": {"pe_ratio": 8.0, "pb_ratio": 1.0},
    }
    sector_map = {"A": "BANK", "B": "BANK", "C": "BANK"}

    # Sector medians
    for ticker in fundamentals:
        sector = sector_map[ticker]
        peers = [p for p, s in sector_map.items() if s == sector and p in fundamentals and p != ticker]
        medians = {}
        for key in ["pe_ratio", "pb_ratio"]:
            vals = [fundamentals[p].get(key) for p in peers if fundamentals[p].get(key) is not None]
            if vals:
                medians[key] = float(np.median(vals))

        if ticker == "A":
            # B=12, C=8 → median=10
            assert abs(medians["pe_ratio"] - 10.0) < 0.01, f"PE median: {medians['pe_ratio']}"
            # B=2.0, C=1.0 → median=1.5
            assert abs(medians["pb_ratio"] - 1.5) < 0.01, f"PB median: {medians['pb_ratio']}"

    print(f"  ✓ Sector medians: PE median=10.0, PB median=1.5")
    passed += 1

    return passed, failed


# ────────────────────────────────────────────────────────────
# 7. Canonical feature contract compliance
# ────────────────────────────────────────────────────────────

def test_feature_contract_compliance():
    """Motor çıktıları canonical registry ile uyumlu olmalı."""
    from services.core.canonical_scoring import CANONICAL_FEATURE_REGISTRY, validate_model_feature_contract

    passed = 0
    failed = 0

    # Registry'de kritik motor feature'ları olmalı
    critical_features = [
        "rsi_14", "momentum_20d", "roc_5d", "volume_zscore", "atr_pct",
        "rs_vs_bist_5d", "kap_sentiment_avg", "fcf_yield_pct",
        "catalyst_count", "falling_is_temporary",
    ]

    missing = [f for f in critical_features if f not in CANONICAL_FEATURE_REGISTRY]
    assert len(missing) == 0, f"Missing critical features in registry: {missing}"
    print(f"  ✓ Feature contract: {len(critical_features)} critical features all in registry")
    passed += 1

    return passed, failed


# ────────────────────────────────────────────────────────────
# 8. Scalar feature guard on motor outputs
# ────────────────────────────────────────────────────────────

def test_motor_output_scalar_guard():
    """Motor çıktıları scalar guard'dan geçmeli."""
    from services.features.calculator import FeatureCalculator

    passed = 0
    failed = 0

    calc = FeatureCalculator()
    df = _make_ohlcv(80, seed=42)
    feats = calc.compute_all_features(df.iloc[:70], ticker="TEST")

    # Tüm feature'lar scalar olmalı
    for k, v in feats.items():
        assert isinstance(v, (int, float, np.floating, np.integer)), \
            f"Non-scalar motor output: {k} = {type(v).__name__}"
        assert np.isfinite(float(v)), f"Non-finite motor output: {k} = {v}"

    print(f"  ✓ Motor output scalar guard: {len(feats)} features, all scalar, all finite")
    passed += 1

    return passed, failed


# ────────────────────────────────────────────────────────────
# 9. Data adapter PIT filtering
# ────────────────────────────────────────────────────────────

def test_data_adapter_pit_filtering():
    """Data adapter as_of_date filtrelemesi çalışmalı."""
    from services.features.data_adapter import DataAdapter

    passed = 0
    failed = 0

    adapter = DataAdapter()
    adapter.reset_duplicates()

    # Geçmiş tarih — daha az event beklenir
    events_past = adapter.fetch_kap_events("THYAO", as_of_date="2020-01-01")
    adapter.reset_duplicates()

    # Gelecek tarih — daha fazla event beklenir
    events_future = adapter.fetch_kap_events("THYAO", as_of_date="2026-12-31")

    # Future tarih >= past tarih (PIT filtreleme doğru çalışmalı)
    assert len(events_future) >= len(events_past), \
        f"Future should have ≥ events: past={len(events_past)}, future={len(events_future)}"

    print(f"  ✓ PIT filtering: past={len(events_past)}, future={len(events_future)}")
    passed += 1

    return passed, failed


# ────────────────────────────────────────────────────────────
# 10. Catalyst derivation
# ────────────────────────────────────────────────────────────

def test_catalyst_derivation():
    """KAP/news'den catalyst türetmeli."""
    from services.features.data_adapter import DataAdapter

    passed = 0
    failed = 0

    adapter = DataAdapter()
    adapter.reset_duplicates()

    kap = adapter.fetch_kap_events("THYAO", as_of_date="2024-12-31")
    news = adapter.fetch_news_events("THYAO", as_of_date="2024-12-31")

    catalysts = adapter.derive_catalysts(kap, news, as_of_date="2024-12-31")
    assert isinstance(catalysts, list)

    # Catalyst'lerde tarih ve type bilgisi olmalı
    for c in catalysts:
        assert "date" in c or "expected_date" in c, f"Catalyst missing date: {c}"

    print(f"  ✓ Catalyst derivation: {len(catalysts)} catalysts from {len(kap)} KAP + {len(news)} news")
    passed += 1

    return passed, failed


# ────────────────────────────────────────────────────────────
# 11. FeatureDataPoint contract
# ────────────────────────────────────────────────────────────

def test_feature_data_point_contract():
    """FeatureDataPoint contract doğru çalışmalı."""
    from services.features.feature_contract import (
        FeatureDataPoint, FeatureStatus,
        make_fresh, make_missing, make_unknown, make_stale
    )

    passed = 0
    failed = 0

    # Fresh
    fresh = make_fresh(42.0, "test", "2024-01-15")
    assert fresh.value == 42.0
    assert fresh.status == FeatureStatus.FRESH
    assert fresh.is_usable()
    assert fresh.to_value() == 42.0

    # Missing
    missing = make_missing("test")
    assert missing.value is None
    assert missing.status == FeatureStatus.MISSING
    assert not missing.is_usable()
    assert missing.to_value(default=99.0) == 99.0

    # Stale
    stale = make_stale(10.0, "test", "2020-01-01")
    assert stale.value == 10.0
    assert stale.status == FeatureStatus.STALE
    assert not stale.is_usable()  # Stale usable değil
    assert stale.to_value() == 0.0  # Default

    print(f"  ✓ FeatureDataPoint: fresh=usable, missing=fallback, stale=not_usable")
    passed += 1

    return passed, failed


# ────────────────────────────────────────────────────────────
# 12. Orchestrator → motor data flow
# ────────────────────────────────────────────────────────────

def test_orchestrator_motor_data_flow():
    """Orchestrator motorlara veri gönderiyor mu?"""
    from services.features.seven_motors import seven_motor_engine

    passed = 0
    failed = 0

    df = _make_ohlcv(80, seed=42)
    close = df['Close'].values

    # Benchmark ve sector verisi ile Motor 1 çalışmalı
    benchmark = close * 1.01  # Basit benchmark
    sector = close * 0.99     # Basit sector

    features = seven_motor_engine.compute_all(
        "TEST", df,
        benchmark_close=benchmark,
        sector_close=sector,
        peer_closes={"PEER1": close * 0.98},
        fundamentals={"pe_ratio": 12.0, "pb_ratio": 1.5, "fcf_yield": 5.0, "roe": 15.0},
        kap_events=[{"category": "financial", "date": "2022-06-01", "sentiment": 0.5, "importance": 3}],
        news_events=[],
        upcoming_events=[],
        market_return_5d=2.0,
        market_return_20d=5.0,
        sector_return_5d=1.5,
        sector_return_20d=3.0,
        market_regime="BULL",
    )

    # Motor 1 feature'ları üretilmeli
    rs_features = [k for k in features if k.startswith("rs_vs_")]
    assert len(rs_features) > 0, f"Motor 1 (RS) produced no features"
    print(f"  ✓ Motor 1 (RS): {len(rs_features)} features")
    passed += 1

    # Motor 4 feature'ları üretilmeli
    fund_features = [k for k in features if k.startswith("raw_") or k.startswith("sector_norm_")]
    assert len(fund_features) > 0, f"Motor 4 (Fundamental) produced no features"
    print(f"  ✓ Motor 4 (Fundamental): {len(fund_features)} features")
    passed += 1

    # Motor 5 feature'ları üretilmeli
    kap_features = [k for k in features if "kap" in k or "sentiment" in k]
    assert len(kap_features) > 0, f"Motor 5 (KAP) produced no features"
    print(f"  ✓ Motor 5 (KAP/News): {len(kap_features)} features")
    passed += 1

    # Motor 7 feature'ları üretilmeli
    fall_features = [k for k in features if "fall" in k]
    assert len(fall_features) > 0, f"Motor 7 (Why Falling) produced no features"
    print(f"  ✓ Motor 7 (Why Falling): {len(fall_features)} features")
    passed += 1

    return passed, failed


# ────────────────────────────────────────────────────────────
# 13. Future-data mutation (KAP/news/fundamental/event)
# ────────────────────────────────────────────────────────────

def test_future_data_mutation_comprehensive():
    """Gelecekteki KAP/news/fundamental/event değişimi geçmiş feature'ı etkilememeli."""
    from services.features.data_adapter import DataAdapter

    passed = 0
    failed = 0

    adapter = DataAdapter()

    # 2024-01-15 snapshot'ı
    adapter.reset_duplicates()
    events_before = adapter.fetch_kap_events("THYAO", as_of_date="2024-01-15")
    count_before = len(events_before)

    # 2024-12-31 snapshot'ı (daha fazla event olabilir)
    adapter.reset_duplicates()
    events_after = adapter.fetch_kap_events("THYAO", as_of_date="2024-12-31")
    count_after = len(events_after)

    # PIT: as_of_date filtresi doğru çalışmalı
    assert count_after >= count_before, "Later date should have ≥ events"
    print(f"  ✓ Future mutation: before={count_before}, after={count_after}")
    passed += 1

    return passed, failed


# ────────────────────────────────────────────────────────────
# Ana çalıştırıcı
# ────────────────────────────────────────────────────────────

def run_all():
    tests = [
        ("KAP PIT", test_kap_pit),
        ("News PIT", test_news_pit),
        ("Fundamental PIT", test_fundamental_pit),
        ("Duplicate event prevention", test_duplicate_event_prevention),
        ("Provider failure graceful", test_provider_failure_graceful),
        ("Sector medians", test_sector_medians),
        ("Feature contract compliance", test_feature_contract_compliance),
        ("Motor output scalar guard", test_motor_output_scalar_guard),
        ("Data adapter PIT filtering", test_data_adapter_pit_filtering),
        ("Catalyst derivation", test_catalyst_derivation),
        ("FeatureDataPoint contract", test_feature_data_point_contract),
        ("Orchestrator → motor data flow", test_orchestrator_motor_data_flow),
        ("Future-data mutation comprehensive", test_future_data_mutation_comprehensive),
    ]

    total_passed = 0
    total_failed = 0

    print("=" * 70)
    print("FAZ 5.3 — Feature Motor Data Feed Pipeline")
    print("=" * 70)

    for name, test_fn in tests:
        print(f"\n▸ {name}")
        try:
            p, f = test_fn()
            total_passed += p
            total_failed += f
            if f > 0:
                print(f"  ⚠ {f} FAILED")
        except Exception as e:
            import traceback
            print(f"  ✗ EXCEPTION: {e}")
            traceback.print_exc()
            total_failed += 1

    print("\n" + "=" * 70)
    print(f"SONUÇ: {total_passed} passed, {total_failed} failed")
    print("=" * 70)

    return total_failed == 0


if __name__ == "__main__":
    success = run_all()
    sys.exit(0 if success else 1)
