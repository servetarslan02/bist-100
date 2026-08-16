"""
ALPHA BIST — FAZ v3 Test Suite

Mask-First, Cross-Sectional, Label Generation, Walk-Forward testleri.
"""

import sys
import os
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def test_tradability_mask():
    """Tradability Mask testleri."""
    from services.core.tradability_mask import tradability_mask

    passed = 0
    failed = 0

    n = 30
    open_ = np.full(n, 100.0)
    high = np.full(n, 102.0)
    low = np.full(n, 98.0)
    close = np.full(n, 100.0)
    volume = np.full(n, 100000)

    # 1. Normal veri → tamamı valid
    mask_result = tradability_mask.compute_mask("TEST", open_, high, low, close, volume)
    assert mask_result.valid_pct == 100.0, f"Expected 100%, got {mask_result.valid_pct}%"
    passed += 1
    print(f"  ✓ Normal data: {mask_result.valid_pct}% valid")

    # 2. Sıfır hacim → invalid
    vol_zero = volume.copy()
    vol_zero[5] = 0
    mask_result = tradability_mask.compute_mask("TEST", open_, high, low, close, vol_zero)
    assert mask_result.mask[5] == 0
    assert mask_result.reason[5] == "zero_volume"
    passed += 1
    print(f"  ✓ Zero volume detected at index 5")

    # 3. Negatif fiyat → invalid
    close_neg = close.copy()
    close_neg[10] = -5.0
    mask_result = tradability_mask.compute_mask("TEST", open_, high, low, close_neg, volume)
    assert mask_result.mask[10] == 0
    assert mask_result.reason[10] == "zero_negative_price"
    passed += 1
    print(f"  ✓ Negative price detected at index 10")

    # 4. High < Low → invalid
    high_bad = high.copy()
    high_bad[15] = 90.0  # high < low
    mask_result = tradability_mask.compute_mask("TEST", open_, high_bad, low, close, volume)
    assert mask_result.mask[15] == 0
    assert mask_result.reason[15] == "high_less_than_low"
    passed += 1
    print(f"  ✓ High < Low detected at index 15")

    # 5. Limit-up tespiti (tutarlı OHLC ile)
    close_limit = close.copy()
    close_limit[20] = 110.0  # %10 artış
    high_limit = high.copy()
    high_limit[20] = 112.0  # high > close
    low_limit = low.copy()
    low_limit[20] = 108.0  # low < close
    open_limit = open_.copy()
    open_limit[20] = 100.0
    prev_close = np.full(n, 100.0)
    mask_result = tradability_mask.compute_mask("TEST", open_limit, high_limit, low_limit, close_limit, volume, prev_close)
    assert mask_result.mask[20] == 0
    assert "limit_up" in mask_result.reason[20]
    passed += 1
    print(f"  ✓ Limit-up detected at index 20")

    # 6. Limit-down tespiti
    close_limit_down = close.copy()
    close_limit_down[21] = 90.0  # %10 düşüş
    high_limit_down = high.copy()
    high_limit_down[21] = 92.0
    low_limit_down = low.copy()
    low_limit_down[21] = 88.0
    open_limit_down = open_.copy()
    open_limit_down[21] = 100.0
    mask_result = tradability_mask.compute_mask("TEST", open_limit_down, high_limit_down, low_limit_down, close_limit_down, volume, prev_close)
    assert mask_result.mask[21] == 0
    assert "limit_down" in mask_result.reason[21]
    passed += 1
    print(f"  ✓ Limit-down detected at index 21")

    # 7. Mask uygulama
    features = {"rsi": np.full(n, 50.0), "momentum": np.full(n, 5.0)}
    mask = np.ones(n, dtype=int)
    mask[5] = 0
    masked = tradability_mask.apply_mask_to_features(features, mask)
    assert np.isnan(masked["rsi"][5])
    assert masked["rsi"][4] == 50.0  # Diğer günler etkilenmemeli
    passed += 1
    print(f"  ✓ Mask applied to features correctly")

    return passed, failed


def test_label_generator():
    """Label Generation testleri."""
    from services.labels.generator import label_generator

    passed = 0
    failed = 0

    n = 60
    np.random.seed(42)
    close = 100 + np.cumsum(np.random.randn(n) * 2)
    close = np.maximum(close, 10)  # Negatif fiyat yok
    mask = np.ones(n, dtype=int)

    # 1. Label üretimi
    result = label_generator.generate_labels("TEST", close, mask)
    assert "y_5d" in result.labels
    assert "y_20d" in result.labels
    assert "y_5d_binary" in result.labels
    assert "y_max_dd_20d" in result.labels
    passed += 1
    print(f"  ✓ Labels generated: {len(result.labels)} types")

    # 2. Forward return doğruluğu
    # close[0] = 100, close[5] = ? → y_5d[0] = (close[5]/close[0] - 1) * 100
    expected_5d = (close[5] / close[0] - 1) * 100
    actual_5d = result.labels["y_5d"][0]
    assert abs(actual_5d - expected_5d) < 0.01, f"Expected {expected_5d:.4f}, got {actual_5d:.4f}"
    passed += 1
    print(f"  ✓ Forward return correct: y_5d[0] = {actual_5d:.2f}%")

    # 3. Binary label
    assert result.labels["y_5d_binary"][0] in [0.0, 1.0]
    passed += 1
    print(f"  ✓ Binary label: {result.labels['y_5d_binary'][0]}")

    # 4. Mask ile uyumluluk
    mask_with_invalid = mask.copy()
    mask_with_invalid[0] = 0  # İlk gün invalid
    result2 = label_generator.generate_labels("TEST", close, mask_with_invalid)
    # İlk gün invalid → label NaN olmalı
    assert np.isnan(result2.labels["y_5d"][0]) or result2.valid_mask[0] == False
    passed += 1
    print(f"  ✓ Mask compatibility verified")

    # 5. Label names
    names = label_generator.get_label_names()
    assert len(names) >= 10
    assert "y_5d" in names
    assert "y_20d_binary" in names
    passed += 1
    print(f"  ✓ Label names: {len(names)}")

    # 6. Cross-sectional rank
    all_labels = {
        "A": {"y_5d": np.array([10, 5, 3, 8, 2])},
        "B": {"y_5d": np.array([5, 10, 7, 3, 1])},
        "C": {"y_5d": np.array([3, 2, 10, 5, 8])},
    }
    ranks = label_generator.generate_cross_sectional_ranks(all_labels, "y_5d")
    assert "A" in ranks
    # Index 0: A=10, B=5, C=3 → A rank = 1.0 (highest)
    assert ranks["A"][0] == 1.0
    passed += 1
    print(f"  ✓ Cross-sectional rank correct")

    return passed, failed


def test_cross_sectional():
    """Cross-Sectional Feature Engine testleri."""
    from services.features.cross_sectional import cross_sectional_engine

    passed = 0
    failed = 0

    # Test verisi (en az 4 peer gerekli)
    universe = {
        "A": {"return_1d": 2, "return_5d": 10, "rsi_14": 70, "momentum_20d": 15, "volume_zscore": 2.5},
        "B": {"return_1d": 1, "return_5d": 5, "rsi_14": 55, "momentum_20d": 8, "volume_zscore": 1.0},
        "C": {"return_1d": -2, "return_5d": -3, "rsi_14": 35, "momentum_20d": -5, "volume_zscore": -0.5},
        "D": {"return_1d": 1.5, "return_5d": 8, "rsi_14": 62, "momentum_20d": 12, "volume_zscore": 1.8},
        "E": {"return_1d": -0.5, "return_5d": -1, "rsi_14": 45, "momentum_20d": 2, "volume_zscore": 0.3},
        "F": {"return_1d": 0.8, "return_5d": 6, "rsi_14": 58, "momentum_20d": 9, "volume_zscore": 1.2},
    }
    sectors = {"A": "TECH", "B": "TECH", "C": "BANK", "D": "TECH", "E": "BANK", "F": "TECH"}

    # 1. Rank features
    rank_features = cross_sectional_engine.compute_rank_features("A", universe["A"], universe)
    assert "rank_return_5d" in rank_features
    assert rank_features["rank_return_5d"] == 1.0  # A en yüksek return_5d
    passed += 1
    print(f"  ✓ Rank features: A rank_return_5d = {rank_features['rank_return_5d']}")

    # 2. Sector relative
    sector_rel = cross_sectional_engine.compute_sector_relative(
        "A", universe["A"], "TECH", universe, sectors
    )
    assert "sector_rel_return_5d" in sector_rel
    # A=10, B=5, D=8 → sektör ortalaması = 7.67 → A relative = 2.33
    assert sector_rel["sector_rel_return_5d"] > 0
    passed += 1
    print(f"  ✓ Sector relative: A sector_rel_return_5d = {sector_rel['sector_rel_return_5d']:.2f}")

    # 3. Market breadth
    breadth = cross_sectional_engine.compute_market_breadth_features(universe)
    assert "market_breadth" in breadth
    assert breadth["market_advancing"] == 4  # A, B, D, F pozitif
    assert breadth["market_declining"] == 2  # C, E negatif
    passed += 1
    print(f"  ✓ Market breadth: {breadth['market_breadth']:.2f} ({breadth['market_advancing']}↑/{breadth['market_declining']}↓)")

    # 4. Sector momentum
    sector_mom = cross_sectional_engine.compute_sector_momentum(universe, sectors)
    assert "sector_momentum_TECH_return_5d" in sector_mom
    assert "sector_momentum_BANK_return_5d" in sector_mom
    passed += 1
    print(f"  ✓ Sector momentum: TECH={sector_mom.get('sector_momentum_TECH_return_5d', 0):.1f}, BANK={sector_mom.get('sector_momentum_BANK_return_5d', 0):.1f}")

    # 5. Rank features for weak stock
    rank_features_c = cross_sectional_engine.compute_rank_features("C", universe["C"], universe)
    assert rank_features_c["rank_return_5d"] < 0.2  # C en düşük (0.167)
    assert rank_features_c["rank_return_5d"] < rank_features["rank_return_5d"]  # C < A
    passed += 1
    print(f"  ✓ Rank features: C rank_return_5d = {rank_features_c['rank_return_5d']:.3f} (lowest)")

    return passed, failed


def test_walk_forward():
    """Walk-Forward Validation testleri (purge + embargo)."""
    from services.backtest.walk_forward import walk_forward_engine

    passed = 0
    failed = 0

    # Test verisi
    signals = []
    for i in range(500):
        signals.append({
            "date": f"2024-{(i//30)+1:02d}-{(i%30)+1:02d}",
            "ticker": "TEST",
            "action": "BUY" if i % 3 == 0 else "SELL",
            "price": 100 + i * 0.1,
            "pnl_pct": 1.0 if i % 3 == 0 else -0.5,
            "pnl": 100 if i % 3 == 0 else -50,
        })

    result = walk_forward_engine.run_walk_forward(
        signals=signals, price_data={}, train_days=100, test_days=30, step_days=15,
    )
    assert result.total_folds > 0
    passed += 1
    print(f"  ✓ Walk-forward: {result.total_folds} folds")

    assert isinstance(result.avg_test_return, float)
    passed += 1
    print(f"  ✓ Avg test return: {result.avg_test_return:.2f}%")

    assert 0 <= result.stability_score <= 1
    passed += 1
    print(f"  ✓ Stability: {result.stability_score:.2f}")

    return passed, failed


def test_mask_integration():
    """Mask + Feature + Label entegrasyon testi."""
    from services.core.tradability_mask import tradability_mask
    from services.labels.generator import label_generator
    from services.features.calculator import feature_calculator
    import pandas as pd

    passed = 0
    failed = 0

    # Test verisi oluştur (bazı günler invalid)
    n = 60
    np.random.seed(42)
    close = 100 + np.cumsum(np.random.randn(n) * 2)
    close = np.maximum(close, 10)
    high = close + np.random.rand(n) * 2
    low = close - np.random.rand(n) * 2
    open_ = close - np.random.rand(n) + 0.5
    volume = (np.random.rand(n) * 1000000 + 100000).astype(int)

    # Bazı günleri invalid yap
    volume[5] = 0   # Sıfır hacim
    close[10] = -5  # Negatif fiyat
    high[15] = 90   # High < Low

    # 1. Mask hesapla
    mask_result = tradability_mask.compute_mask("TEST", open_, high, low, close, volume)
    assert mask_result.mask[5] == 0  # Sıfır hacim
    assert mask_result.mask[10] == 0  # Negatif fiyat
    assert mask_result.mask[15] == 0  # High < Low
    passed += 1
    print(f"  ✓ Mask computed: {mask_result.valid_pct}% valid")

    # 2. Mask'ı fiyatlara uygula
    m_open, m_high, m_low, m_close, m_volume = tradability_mask.apply_mask_to_prices(
        open_, high, low, close, volume, mask_result.mask
    )
    assert np.isnan(m_close[5])
    assert np.isnan(m_close[10])
    assert not np.isnan(m_close[0])  # İlk gün valid
    passed += 1
    print(f"  ✓ Mask applied to prices")

    # 3. Label üret (mask-aware)
    label_result = label_generator.generate_labels("TEST", m_close, mask_result.mask)
    assert "y_5d" in label_result.labels
    # Invalid günlerde label NaN olmalı
    assert np.isnan(label_result.labels["y_5d"][5]) or label_result.valid_mask[5] == False
    passed += 1
    print(f"  ✓ Labels generated with mask awareness")

    # 4. Feature hesaplama (mask-aware)
    df = pd.DataFrame({
        "Open": m_open,
        "High": m_high,
        "Low": m_low,
        "Close": m_close,
        "Volume": m_volume,
    })
    features = feature_calculator.compute_all_features(df)
    assert len(features) > 0
    passed += 1
    print(f"  ✓ Features computed: {len(features)}")

    return passed, failed


def main():
    print("=" * 60)
    print("  FAZ v3 — Test Suite")
    print("=" * 60)

    total_passed = 0
    total_failed = 0

    tests = [
        ("Tradability Mask", test_tradability_mask),
        ("Label Generator", test_label_generator),
        ("Cross-Sectional Engine", test_cross_sectional),
        ("Walk-Forward Validation", test_walk_forward),
        ("Mask Integration", test_mask_integration),
    ]

    for name, test_func in tests:
        print(f"\n--- {name} ---")
        try:
            p, f = test_func()
            total_passed += p
            total_failed += f
        except Exception as e:
            print(f"  ✗ Test crashed: {e}")
            import traceback
            traceback.print_exc()
            total_failed += 1

    print(f"\n{'=' * 60}")
    print(f"  SONUÇ: {total_passed} passed, {total_failed} failed")
    print(f"{'=' * 60}")

    return total_failed == 0


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
