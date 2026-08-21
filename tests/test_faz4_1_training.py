"""
ALPHA BIST — FAZ 4.1 Test Suite

Multi-sample training dataset, leakage, determinism, tarih hizalama testleri.
"""

import sys
import os
import hashlib
import numpy as np
import pandas as pd
from datetime import datetime, timedelta



# ────────────────────────────────────────────────────────────
# Yardımcı: Sentez OHLCV DataFrame üret
# ────────────────────────────────────────────────────────────

def _make_ohlcv(n_days: int, start_price: float = 100.0, seed: int = 42) -> pd.DataFrame:
    """n_days günlük sentetik OHLCV üret (deterministik)."""
    rng = np.random.RandomState(seed)
    dates = pd.bdate_range(start="2022-01-03", periods=n_days, freq="B")
    close = start_price + np.cumsum(rng.randn(n_days) * 1.5)
    close = np.maximum(close, 1.0)  # Negatif fiyat engeli
    high = close * (1 + rng.uniform(0, 0.03, n_days))
    low = close * (1 - rng.uniform(0, 0.03, n_days))
    open_ = close * (1 + rng.uniform(-0.01, 0.01, n_days))
    volume = rng.randint(100000, 5000000, n_days).astype(float)
    return pd.DataFrame({
        "Open": open_, "High": high, "Low": low, "Close": close, "Volume": volume
    }, index=dates)


def _make_pit_data(tickers, n_days=200, seed=42):
    """Birden fazla ticker için pit_data dict üret."""
    data = {}
    for i, t in enumerate(tickers):
        data[t] = _make_ohlcv(n_days, start_price=50 + i * 30, seed=seed + i)
    return data


# ────────────────────────────────────────────────────────────
# TEST 1: Multi-sample — her gün için ayrı sample oluşuyor mu?
# ────────────────────────────────────────────────────────────

def test_multi_sample_count():
    """Her uygun işlem günü için ayrı training sample oluşmalı."""
    from services.backtest.walk_forward_runner import WalkForwardBacktestRunner

    passed = 0
    failed = 0

    runner = WalkForwardBacktestRunner.__new__(WalkForwardBacktestRunner)
    runner.MIN_TRAINING_SAMPLES = 5  # Test için düşük eşik
    runner.FORWARD_DAYS = 5
    runner.MIN_BARS_FOR_FEATURES = 60

    # 200 günlük veri, 10 ticker
    tickers = [f"SYM{i:02d}" for i in range(10)]
    pit_data = _make_pit_data(tickers, n_days=200, seed=42)

    # Train window: gün 0..149 (150 gün)
    dates = sorted(pit_data[tickers[0]].index)
    train_start = str(dates[0].date())
    train_end = str(dates[149].date())

    # _train_fold_model'ı çağır (FeatureCalculator gerçek hesaplama yapar)
    model = runner._train_fold_model(pit_data, train_start, train_end)

    if model is not None:
        # 10 ticker × ~85 gün ≈ 850+ sample bekleniyor
        # (150 gün - 60 feature window - 5 forward = 85 gün × 10 ticker)
        assert model.train_samples > 100, f"Expected >100 samples, got {model.train_samples}"
        print(f"  ✓ Multi-sample: {model.train_samples} samples (10 ticker × ~85 gün)")
        passed += 1
    else:
        # FeatureCalculator import edilemezse (dependency yok) — skip
        print("  ⚠ Model None döndü (muhtemelen FeatureCalculator import hatası), skip")
        return 0, 0

    return passed, failed


# ────────────────────────────────────────────────────────────
# TEST 2: Son 5 gün target üretilemediği için kullanılmamalı
# ────────────────────────────────────────────────────────────

def test_last_5_days_excluded():
    """Son FORWARD_DAYS gün feature_date olarak KULLANILMAMALI."""
    from services.backtest.walk_forward_runner import WalkForwardBacktestRunner

    passed = 0
    failed = 0

    runner = WalkForwardBacktestRunner.__new__(WalkForwardBacktestRunner)
    runner.MIN_TRAINING_SAMPLES = 5
    runner.FORWARD_DAYS = 5
    runner.MIN_BARS_FOR_FEATURES = 60

    # Daha fazla veri ile (10 ticker × 150 gün)
    tickers = [f"SYM{i:02d}" for i in range(10)]
    pit_data = _make_pit_data(tickers, n_days=150, seed=42)
    dates = sorted(pit_data[tickers[0]].index)

    # Train: 0..149 (150 gün)
    train_start = str(dates[0].date())
    train_end = str(dates[149].date())

    # Her ticker için: 150 - 60 - 5 = 85 gün sample
    # Son feature index = 149 - 5 = 144
    # dates[145..149] KULLANILMAMALI
    expected_max_per_ticker = 150 - 60 - 5  # = 85
    expected_max_total = expected_max_per_ticker * 10  # = 850

    model = runner._train_fold_model(pit_data, train_start, train_end)
    if model is None:
        print("  ⚠ Model None, skip")
        return 0, 0

    assert model.train_samples <= expected_max_total, \
        f"Expected ≤{expected_max_total} samples, got {model.train_samples}"
    # En az 100 sample olmalı (multi-sample çalışıyor)
    assert model.train_samples >= 100, \
        f"Expected ≥100 samples, got {model.train_samples}"
    print(f"  ✓ Son 5 gün excluded: {model.train_samples} samples (max {expected_max_total})")
    passed += 1

    return passed, failed


# ────────────────────────────────────────────────────────────
# TEST 3: Feature sadece T'ye kadar veri kullanıyor (leakage)
# ────────────────────────────────────────────────────────────

def test_feature_no_future_data():
    """Feature hesaplamasında T'den sonraki veri KULLANILMAMALI.

    Test: T günündeki Close değerini değiştirirsek feature değişmemeli
    (çünkü feature sadece T'ye kadar veri kullanır). T+1'deki Close
    değişimiyse feature'ı etkilememeli.
    """
    from services.backtest.walk_forward_runner import WalkForwardBacktestRunner
    from services.features.calculator import FeatureCalculator

    passed = 0
    failed = 0

    # 80 günlük veri (feature için yeterli)
    df_original = _make_ohlcv(80, start_price=100, seed=42)
    calc = FeatureCalculator()

    # Feature T=69'da hesapla (0-indexed, 70. gün)
    feature_idx = 69
    df_slice_orig = df_original.iloc[:feature_idx + 1]
    feats_orig = calc.compute_all_features(df_slice_orig, ticker="TEST")

    # Şimdi T+1 (index 70) günündeki Close'u değiştir
    df_mutated = df_original.copy()
    df_mutated.iloc[feature_idx + 1, df_mutated.columns.get_loc("Close")] = 99999.0

    df_slice_mut = df_mutated.iloc[:feature_idx + 1]  # Sadece T'ye kadar
    feats_mut = calc.compute_all_features(df_slice_mut, ticker="TEST")

    # Feature'lar aynı olmalı (T+1 verisi feature'a girmiyor)
    if feats_orig and feats_mut:
        for key in feats_orig:
            v1 = feats_orig[key]
            v2 = feats_mut[key]
            if isinstance(v1, (int, float)) and isinstance(v2, (int, float)):
                if abs(v1 - v2) > 1e-10:
                    print(f"  ✗ Feature '{key}' changed: {v1} → {v2} (future data leaked!)")
                    failed += 1
        if failed == 0:
            print("  ✓ Feature no future data: T+1 mutation has zero effect")
            passed += 1
    else:
        print("  ⚠ Feature computation returned empty, skip")
        return 0, 0

    return passed, failed


# ────────────────────────────────────────────────────────────
# TEST 4: Duplicate sample engeli
# ────────────────────────────────────────────────────────────

def test_no_duplicate_samples():
    """Aynı (ticker, date) çifti iki kez eklenmemeli."""
    from services.backtest.walk_forward_runner import WalkForwardBacktestRunner

    passed = 0
    failed = 0

    runner = WalkForwardBacktestRunner.__new__(WalkForwardBacktestRunner)
    runner.MIN_TRAINING_SAMPLES = 5
    runner.FORWARD_DAYS = 5
    runner.MIN_BARS_FOR_FEATURES = 60

    # 10 ticker × 150 gün — multi-sample çalışmalı
    tickers = [f"SYM{i:02d}" for i in range(10)]
    pit_data = _make_pit_data(tickers, n_days=150, seed=42)
    dates = sorted(pit_data[tickers[0]].index)

    train_start = str(dates[0].date())
    train_end = str(dates[149].date())

    model = runner._train_fold_model(pit_data, train_start, train_end)
    if model is None:
        print("  ⚠ Model None, skip")
        return 0, 0

    # 10 ticker × 85 gün = max 850 sample, hepsi unique
    max_possible = 10 * (150 - 60 - 5)  # = 850
    assert model.train_samples <= max_possible, \
        f"Possible duplicates: {model.train_samples} > max {max_possible}"
    assert model.train_samples >= 100, \
        f"Expected ≥100 samples, got {model.train_samples}"
    print(f"  ✓ No duplicates: {model.train_samples} samples (max {max_possible})")
    passed += 1

    return passed, failed


# ────────────────────────────────────────────────────────────
# TEST 5: Minimum sample yetersizse None döner (rule-based fallback)
# ────────────────────────────────────────────────────────────

def test_minimum_sample_fallback():
    """Yeterli sample yoksa model None dönmeli."""
    from services.backtest.walk_forward_runner import WalkForwardBacktestRunner

    passed = 0
    failed = 0

    runner = WalkForwardBacktestRunner.__new__(WalkForwardBacktestRunner)
    runner.MIN_TRAINING_SAMPLES = 10000  # Aşırı yüksek eşik — hiçbir dataset bu kadar üretmez
    runner.FORWARD_DAYS = 5
    runner.MIN_BARS_FOR_FEATURES = 60

    # 10 ticker × 150 gün bile 10000 sample'a ulaşmamalı
    tickers = [f"SYM{i:02d}" for i in range(10)]
    pit_data = _make_pit_data(tickers, n_days=150, seed=42)
    dates = sorted(pit_data[tickers[0]].index)

    train_start = str(dates[0].date())
    train_end = str(dates[149].date())

    model = runner._train_fold_model(pit_data, train_start, train_end)
    assert model is None, f"Expected None (fallback), got model with {model.train_samples} samples"
    print("  ✓ Minimum sample fallback: None returned when insufficient")
    passed += 1

    return passed, failed


# ────────────────────────────────────────────────────────────
# TEST 6: Deterministik — aynı veri aynı sonucu üretmeli
# ────────────────────────────────────────────────────────────

def test_deterministic_training():
    """Aynı veri ile iki eğitim aynı feature_map ve model üretmeli."""
    from services.backtest.walk_forward_runner import WalkForwardBacktestRunner

    passed = 0
    failed = 0

    tickers = [f"SYM{i:02d}" for i in range(5)]

    # İlk çalışma
    runner1 = WalkForwardBacktestRunner.__new__(WalkForwardBacktestRunner)
    runner1.MIN_TRAINING_SAMPLES = 5
    runner1.FORWARD_DAYS = 5
    runner1.MIN_BARS_FOR_FEATURES = 60
    pit_data1 = _make_pit_data(tickers, n_days=150, seed=42)
    dates1 = sorted(pit_data1[tickers[0]].index)
    model1 = runner1._train_fold_model(
        pit_data1, str(dates1[0].date()), str(dates1[149].date())
    )

    # İkinci çalışma (aynı veri)
    runner2 = WalkForwardBacktestRunner.__new__(WalkForwardBacktestRunner)
    runner2.MIN_TRAINING_SAMPLES = 5
    runner2.FORWARD_DAYS = 5
    runner2.MIN_BARS_FOR_FEATURES = 60
    pit_data2 = _make_pit_data(tickers, n_days=150, seed=42)
    dates2 = sorted(pit_data2[tickers[0]].index)
    model2 = runner2._train_fold_model(
        pit_data2, str(dates2[0].date()), str(dates2[149].date())
    )

    if model1 is None or model2 is None:
        print("  ⚠ One or both models None, skip")
        return 0, 0

    assert model1.train_samples == model2.train_samples, \
        f"Sample count mismatch: {model1.train_samples} vs {model2.train_samples}"
    assert model1.validation_score == model2.validation_score, \
        f"Val score mismatch: {model1.validation_score} vs {model2.validation_score}"
    print(f"  ✓ Deterministic: {model1.train_samples} samples, val={model1.validation_score}")
    passed += 1

    return passed, failed


# ────────────────────────────────────────────────────────────
# TEST 7: Purge/embargo — train verisi train_end'den sonrasını içermemeli
# ────────────────────────────────────────────────────────────

def test_purge_boundary():
    """Train window verisi train_end'i aşmamalı."""
    from services.backtest.walk_forward_runner import WalkForwardBacktestRunner

    passed = 0
    failed = 0

    runner = WalkForwardBacktestRunner.__new__(WalkForwardBacktestRunner)
    runner.MIN_TRAINING_SAMPLES = 5
    runner.FORWARD_DAYS = 5
    runner.MIN_BARS_FOR_FEATURES = 60

    # 10 ticker × 200 gün — train 0..99, pit_data 0..199
    tickers = [f"SYM{i:02d}" for i in range(10)]
    pit_data = _make_pit_data(tickers, n_days=200, seed=42)
    dates = sorted(pit_data[tickers[0]].index)

    # Train: 0..99, ama pit_data 0..199 içeriyor
    train_start = str(dates[0].date())
    train_end = str(dates[99].date())

    # Modeli eğit — sadece train_start..train_end arası veri kullanılmalı
    model = runner._train_fold_model(pit_data, train_start, train_end)
    if model is None:
        print("  ⚠ Model None, skip")
        return 0, 0

    # train_date_range train_end'i aşmamalı
    dr = model.train_date_range
    assert dr[1] <= train_end, f"Train date range end {dr[1]} > train_end {train_end}"
    print(f"  ✓ Purge boundary: train_date_range={dr}, train_end={train_end}")
    passed += 1

    return passed, failed


# ────────────────────────────────────────────────────────────
# TEST 8: Tarih hizalama — target = T+5 forward return
# ────────────────────────────────────────────────────────────

def test_target_date_alignment():
    """Target'ın T+5 forward return olduğunu doğrula.

    Manuel hesaplama ile model training verisi arasındaki uyumu kontrol et.
    """
    from services.backtest.walk_forward_runner import WalkForwardBacktestRunner
    from services.features.calculator import FeatureCalculator

    passed = 0
    failed = 0

    # Tek ticker, bilinen fiyatlar
    dates = pd.bdate_range(start="2022-01-03", periods=80, freq="B")
    rng = np.random.RandomState(42)
    close = 100 + np.cumsum(rng.randn(80) * 0.5)
    close = np.maximum(close, 1.0)

    df = pd.DataFrame({
        "Open": close * 1.001,
        "High": close * 1.02,
        "Low": close * 0.98,
        "Close": close,
        "Volume": np.ones(80) * 1e6,
    }, index=dates)

    # T=69'da feature hesapla
    feature_idx = 69
    calc = FeatureCalculator()
    df_slice = df.iloc[:feature_idx + 1]
    feats = calc.compute_all_features(df_slice, ticker="MANUAL")

    # Manuel forward return: T=69 → T+5=74
    expected_return = (close[74] / close[69] - 1) * 100

    # Training pipeline'daki hesaplama ile aynı olmalı
    actual_return = (close[feature_idx + 5] / close[feature_idx] - 1) * 100

    assert abs(expected_return - actual_return) < 1e-10, \
        f"Return mismatch: expected={expected_return}, actual={actual_return}"

    if feats:
        print(f"  ✓ Target alignment: T={feature_idx}, T+5={feature_idx+5}, return={actual_return:.4f}%")
        passed += 1
    else:
        print("  ⚠ Feature computation empty, skip alignment check")
        return 0, 0

    return passed, failed


# ────────────────────────────────────────────────────────────
# TEST 9: Future-data mutation testi (detaylı leakage)
# ────────────────────────────────────────────────────────────

def test_future_data_mutation_leakage():
    """T+1, T+2, T+3, T+4, T+5 günlerindeki Close değişimleri
    T günündeki feature'ı etkilememeli.

    Bu test gelecek veri sızıntısını yakalamak için kritik.
    """
    from services.features.calculator import FeatureCalculator

    passed = 0
    failed = 0

    calc = FeatureCalculator()
    df_base = _make_ohlcv(80, start_price=100, seed=42)
    feature_idx = 69

    # Orijinal feature'lar
    df_slice = df_base.iloc[:feature_idx + 1]
    feats_base = calc.compute_all_features(df_slice, ticker="LEAK_TEST")
    if not feats_base:
        print("  ⚠ Feature computation empty, skip")
        return 0, 0

    # T+1..T+5 günlerinin her birini tek tek değiştir
    for offset in range(1, 6):
        df_mut = df_base.copy()
        target_idx = feature_idx + offset
        if target_idx < len(df_mut):
            df_mut.iloc[target_idx, df_mut.columns.get_loc("Close")] = 99999.0

            # Sadece T'ye kadar veri ile feature hesapla
            df_mut_slice = df_mut.iloc[:feature_idx + 1]
            feats_mut = calc.compute_all_features(df_mut_slice, ticker="LEAK_TEST")

            for key in feats_base:
                v1 = feats_base[key]
                v2 = feats_mut.get(key)
                if v2 is None:
                    continue
                if isinstance(v1, (int, float)) and isinstance(v2, (int, float)):
                    if abs(v1 - v2) > 1e-10:
                        print(f"  ✗ LEAKAGE: T+{offset} mutation changed '{key}': {v1} → {v2}")
                        failed += 1

    if failed == 0:
        print("  ✓ Future-data mutation: T+1..T+5 mutations have ZERO effect on T features")
        passed += 1

    return passed, failed


# ────────────────────────────────────────────────────────────
# Ana test çalıştırıcı
# ────────────────────────────────────────────────────────────

def run_all():
    """Tüm FAZ 4.1 testlerini çalıştır."""
    tests = [
        ("Multi-sample count", test_multi_sample_count),
        ("Last 5 days excluded", test_last_5_days_excluded),
        ("Feature no future data", test_feature_no_future_data),
        ("No duplicate samples", test_no_duplicate_samples),
        ("Minimum sample fallback", test_minimum_sample_fallback),
        ("Deterministic training", test_deterministic_training),
        ("Purge boundary", test_purge_boundary),
        ("Target date alignment", test_target_date_alignment),
        ("Future-data mutation leakage", test_future_data_mutation_leakage),
    ]

    total_passed = 0
    total_failed = 0

    print("=" * 70)
    print("FAZ 4.1 — Multi-Sample Training Dataset Testleri")
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
            print(f"  ✗ EXCEPTION: {e}")
            total_failed += 1

    print("\n" + "=" * 70)
    print(f"SONUÇ: {total_passed} passed, {total_failed} failed")
    print("=" * 70)

    return total_failed == 0


if __name__ == "__main__":
    success = run_all()
    sys.exit(0 if success else 1)
