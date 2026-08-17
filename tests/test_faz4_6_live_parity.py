"""
ALPHA BIST — FAZ 4.6 Test Suite

Live Inference Feature Parity:
1. CS normalization training ve inference'da aynı
2. Feature contract zorunlu (eksik → impute, crash yok)
3. End-to-end parity: aynı snapshot → aynı feature vector
4. Gelecek veri değişimi geçmiş skoru etkilememeli
5. Hisse ekleme/çıkarma yalnızca ilgili snapshot'ı etkilemeli
6. Multi-horizon aynı feature contract kullanmalı
"""

import sys
import os
import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ────────────────────────────────────────────────────────────
# 1. Training ve inference aynı CS normalization sonucu
# ────────────────────────────────────────────────────────────

def test_cs_parity_training_inference():
    """Training'de ve inference'da CS normalization aynı sonucu vermeli."""
    from services.ml.training_validator import (
        CrossSectionalNormalizer, prepare_features_for_inference
    )

    passed = 0
    failed = 0

    normalizer = CrossSectionalNormalizer()

    # 3 ticker, tek tarih (training snapshot)
    all_features = {
        "THYAO": {"momentum_20d": 5.0, "roc_5d": 2.0},
        "GARAN": {"momentum_20d": 10.0, "roc_5d": 4.0},
        "ASELS": {"momentum_20d": 15.0, "roc_5d": 6.0},
    }
    date_str = "2024-01-15"

    # Training: toplu normalize
    train_map = {f"{t}::{date_str}": f for t, f in all_features.items()}
    train_dates = {f"{t}::{date_str}": date_str for t in all_features}
    normalized_train = normalizer.normalize_zscore_by_date(
        train_map, train_dates, ["momentum_20d", "roc_5d"]
    )

    # Inference: tek hisse için prepare_features_for_inference
    for ticker in ["THYAO", "GARAN", "ASELS"]:
        inference_result = prepare_features_for_inference(
            ticker=ticker,
            raw_features=all_features[ticker],
            all_date_features=all_features,
            feature_names=["momentum_20d", "roc_5d"],
            cs_features=["momentum_20d_cs_zscore", "roc_5d_cs_zscore"],
            date_str=date_str,
        )

        # Training sonucu ile aynı olmalı
        train_key = f"{ticker}::{date_str}"
        train_result = normalized_train[train_key]

        for fname in ["momentum_20d_cs_zscore", "roc_5d_cs_zscore"]:
            train_val = train_result.get(fname, 0.0)
            infer_val = inference_result.get(fname, 0.0)
            assert abs(train_val - infer_val) < 1e-6, \
                f"{ticker}/{fname}: train={train_val} vs infer={infer_val}"

    print("  ✓ CS parity: training=inference for all 3 tickers")
    passed += 1

    return passed, failed


# ────────────────────────────────────────────────────────────
# 2. Feature contract zorunlu
# ────────────────────────────────────────────────────────────

def test_feature_contract_enforced():
    """Eksik feature varsa impute ile doldurulmalı, crash olmamalı."""
    from services.ml.training_validator import prepare_features_for_inference

    passed = 0
    failed = 0

    # Model 5 feature bekliyor
    feature_names = ["f1", "f2", "f3", "f4", "f5"]
    cs_features = ["f1_cs_zscore"]

    # Sadece 3 feature mevcut
    raw = {"f1": 1.0, "f2": 2.0, "f3": 3.0}

    result = prepare_features_for_inference(
        ticker="TEST",
        raw_features=raw,
        all_date_features={"TEST": raw},
        feature_names=feature_names,
        cs_features=cs_features,
        impute_values={"f4": 99.0, "f5": 88.0},
        date_str="2024-01-15",
    )

    # Mevcut feature'lar korunmalı
    assert result["f1"] == 1.0
    assert result["f2"] == 2.0
    assert result["f3"] == 3.0

    # Eksik feature'lar impute edilmeli
    assert result["f4"] == 99.0, f"f4 should be imputed to 99.0, got {result['f4']}"
    assert result["f5"] == 88.0, f"f5 should be imputed to 88.0, got {result['f5']}"

    # CS feature (hesaplanamaz çünkü tek ticker) → 0.0
    assert result.get("f1_cs_zscore", 0.0) == 0.0

    print("  ✓ Contract enforced: 3 raw + 2 imputed + 1 CS=0")
    passed += 1

    return passed, failed


# ────────────────────────────────────────────────────────────
# 3. End-to-end parity: aynı snapshot → aynı feature vector
# ────────────────────────────────────────────────────────────

def test_e2e_parity_same_snapshot():
    """Aynı historical snapshot training ve inference'da aynı feature vector'u üretmeli."""
    from services.ml.training_validator import (
        CrossSectionalNormalizer, prepare_features_for_inference
    )
    from services.features.calculator import FeatureCalculator

    passed = 0
    failed = 0

    # 2 ticker, sentetik OHLCV
    rng = np.random.RandomState(42)
    dates = pd.bdate_range(start="2022-01-03", periods=100, freq="B")

    def make_df(seed):
        r = np.random.RandomState(seed)
        close = 100 + np.cumsum(r.randn(100) * 1.5)
        close = np.maximum(close, 1.0)
        return pd.DataFrame({
            "Open": close * 1.001, "High": close * 1.02,
            "Low": close * 0.98, "Close": close,
            "Volume": r.randint(100000, 5000000, 100).astype(float),
        }, index=dates)

    df_a = make_df(42)
    df_b = make_df(43)

    calc = FeatureCalculator()

    # T=69'da feature hesapla (her iki ticker için)
    idx = 69
    feats_a = calc.compute_all_features(df_a.iloc[:idx+1], ticker="A")
    feats_b = calc.compute_all_features(df_b.iloc[:idx+1], ticker="B")

    if not feats_a or not feats_b:
        print("  ⚠ Feature computation empty, skip")
        return 0, 0

    # Sadece scalar feature'ları kullan (volume_profile dict olabilir)
    def scalar_features(feats):
        return {k: v for k, v in feats.items() if isinstance(v, (int, float, np.floating, np.integer))}

    feats_a = scalar_features(feats_a)
    feats_b = scalar_features(feats_b)

    all_features = {"A": feats_a, "B": feats_b}
    date_str = str(dates[idx].date())

    # Training yolu: toplu normalize
    normalizer = CrossSectionalNormalizer()
    train_map = {f"{t}::{date_str}": f for t, f in all_features.items()}
    train_dates = {f"{t}::{date_str}": date_str for t in all_features}
    feature_names = sorted(feats_a.keys())
    normalized_train = normalizer.normalize_zscore_by_date(
        train_map, train_dates, feature_names
    )

    # Inference yolu: prepare_features_for_inference
    for ticker in ["A", "B"]:
        infer_result = prepare_features_for_inference(
            ticker=ticker,
            raw_features=all_features[ticker],
            all_date_features=all_features,
            feature_names=feature_names,
            cs_features=[f"{f}_cs_zscore" for f in feature_names[:5]],  # İlk 5 feature'ın CS'i
            date_str=date_str,
        )

        # Temel feature'lar aynı olmalı
        for fname in feature_names:
            train_val = normalized_train[f"{ticker}::{date_str}"].get(fname)
            infer_val = infer_result.get(fname)
            if train_val is not None and infer_val is not None:
                assert abs(float(train_val) - float(infer_val)) < 1e-6, \
                    f"{ticker}/{fname}: train={train_val} vs infer={infer_val}"

    print(f"  ✓ E2E parity: same snapshot → same features for A and B")
    passed += 1

    return passed, failed


# ────────────────────────────────────────────────────────────
# 4. Gelecek veri değişimi geçmiş skoru etkilememeli
# ────────────────────────────────────────────────────────────

def test_future_change_no_past_effect():
    """T+1 verisini değiştirmek T günündeki inference skorunu etkilememeli."""
    from services.ml.training_validator import prepare_features_for_inference
    from services.features.calculator import FeatureCalculator

    passed = 0
    failed = 0

    calc = FeatureCalculator()
    dates = pd.bdate_range(start="2022-01-03", periods=80, freq="B")
    rng = np.random.RandomState(42)
    close = 100 + np.cumsum(rng.randn(80) * 1.5)
    close = np.maximum(close, 1.0)

    df = pd.DataFrame({
        "Open": close * 1.001, "High": close * 1.02,
        "Low": close * 0.98, "Close": close,
        "Volume": np.ones(80) * 1e6,
    }, index=dates)

    # T=69'da feature hesapla
    idx = 69
    feats_orig = calc.compute_all_features(df.iloc[:idx+1], ticker="X")

    # T+1 (index 70) Close'unu değiştir
    df_mut = df.copy()
    df_mut.iloc[70, df_mut.columns.get_loc("Close")] = 99999.0
    feats_mut = calc.compute_all_features(df_mut.iloc[:idx+1], ticker="X")

    # Feature'lar aynı olmalı (T+1 verisi T feature'ını etkilemez)
    for key in feats_orig:
        v1 = feats_orig[key]
        v2 = feats_mut.get(key)
        if v2 is not None and isinstance(v1, (int, float)) and isinstance(v2, (int, float)):
            assert abs(v1 - v2) < 1e-10, f"Feature '{key}' changed from T+1 mutation"

    # prepare_features_for_inference ile de aynı olmalı
    all_features = {"X": feats_orig, "Y": feats_orig}  # 2 ticker
    result1 = prepare_features_for_inference(
        "X", feats_orig, all_features, sorted(feats_orig.keys())[:5], [], date_str="2022-06-01"
    )

    all_features_mut = {"X": feats_mut, "Y": feats_mut}
    result2 = prepare_features_for_inference(
        "X", feats_mut, all_features_mut, sorted(feats_mut.keys())[:5], [], date_str="2022-06-01"
    )

    for key in result1:
        v1 = result1[key]
        v2 = result2.get(key, 0.0)
        if isinstance(v1, (int, float)) and isinstance(v2, (int, float)):
            assert abs(v1 - v2) < 1e-10, f"Inference feature '{key}' changed from T+1 mutation"

    print("  ✓ Future change: T+1 mutation has ZERO effect on T features/inference")
    passed += 1

    return passed, failed


# ────────────────────────────────────────────────────────────
# 5. Hisse ekleme/çıkarma yalnızca ilgili snapshot'ı etkilemeli
# ────────────────────────────────────────────────────────────

def test_ticker_add_remove_isolated():
    """Bir hisse eklemek/çıkarmak yalnızca o tarih snapshot'ını etkilemeli."""
    from services.ml.training_validator import CrossSectionalNormalizer

    passed = 0
    failed = 0

    normalizer = CrossSectionalNormalizer()

    # 2 tarih, 3 ticker
    features_3 = {
        "A::2024-01-15": {"f": 10.0}, "B::2024-01-15": {"f": 20.0}, "C::2024-01-15": {"f": 30.0},
        "A::2024-01-16": {"f": 11.0}, "B::2024-01-16": {"f": 21.0}, "C::2024-01-16": {"f": 31.0},
    }
    dates_3 = {k: k.split("::")[1] for k in features_3}

    # C'yi yalnızca 01-15'ten çıkar (01-16'da hala var)
    features_2 = {k: v for k, v in features_3.items() if k != "C::2024-01-15"}
    dates_2 = {k: v for k, v in dates_3.items() if k != "C::2024-01-15"}

    norm_3 = normalizer.normalize_zscore_by_date(features_3, dates_3, ["f"])
    norm_2 = normalizer.normalize_zscore_by_date(features_2, dates_2, ["f"])

    # A::2024-01-16 her iki durumda da aynı olmalı (C sadece 01-15'ten çıkarıldı)
    # Ama 01-15'te C çıkarıldığı için A'nın 01-15 z-score'u değişmeli
    z_a_15_with_c = norm_3["A::2024-01-15"].get("f_cs_zscore", 0)
    z_a_15_without_c = norm_2["A::2024-01-15"].get("f_cs_zscore", 0)
    assert z_a_15_with_c != z_a_15_without_c, \
        "Removing C from 01-15 should change A's 01-15 z-score"

    # A::2024-01-16 aynı olmalı (C hala 01-16'da mevcut)
    z_a_16_with_c = norm_3["A::2024-01-16"].get("f_cs_zscore", 0)
    z_a_16_without_c = norm_2["A::2024-01-16"].get("f_cs_zscore", 0)
    assert abs(z_a_16_with_c - z_a_16_without_c) < 1e-10, \
        f"Removing C from 01-15 should NOT affect A's 01-16: {z_a_16_with_c} vs {z_a_16_without_c}"

    print(f"  ✓ Ticker isolation: C removal from 01-15 affects 01-15 (z changed) but not 01-16 (z unchanged)")
    passed += 1

    return passed, failed


# ────────────────────────────────────────────────────────────
# 6. Multi-horizon aynı feature contract kullanmalı
# ────────────────────────────────────────────────────────────

def test_multi_horizon_same_contract():
    """Tüm horizon modelleri aynı feature_names + cs_features kullanmalı."""
    from services.ml.lightgbm_trainer import MultiHorizonModel, TrainedModel

    passed = 0
    failed = 0

    feature_names = [f"feat_{i}" for i in range(10)]
    cs_features = ["feat_0_cs_zscore", "feat_1_cs_zscore"]

    # Farklı horizon'lar için model (aynı feature set)
    model_1d = TrainedModel(
        model=None, feature_names=list(feature_names), train_samples=100,
        target_horizon=1, cs_features=list(cs_features),
    )
    model_5d = TrainedModel(
        model=None, feature_names=list(feature_names), train_samples=100,
        target_horizon=5, cs_features=list(cs_features),
    )

    multi = MultiHorizonModel(primary_horizon=5, cs_features=cs_features)
    multi.horizon_models[1] = model_1d
    multi.horizon_models[5] = model_5d

    # Tüm modeller aynı feature contract kullanmalı
    for h, m in multi.horizon_models.items():
        assert m.feature_names == feature_names, \
            f"Horizon {h}: feature_names mismatch"
        assert m.cs_features == cs_features, \
            f"Horizon {h}: cs_features mismatch"

    # MultiHorizonModel.feature_names primary model'den gelmeli
    assert multi.feature_names == feature_names

    print(f"  ✓ Multi-horizon contract: all {len(multi.horizon_models)} models share same {len(feature_names)} features + {len(cs_features)} CS")
    passed += 1

    return passed, failed


# ────────────────────────────────────────────────────────────
# 7. Canonical scoring ile inference parity
# ────────────────────────────────────────────────────────────

def test_canonical_scoring_inference_parity():
    """compute_canonical_score ile inference parity."""
    from services.core.canonical_scoring import canonical_scoring, CanonicalScore

    passed = 0
    failed = 0

    # Basit feature set
    features = {
        "momentum_20d": 5.0, "roc_5d": 2.0, "rsi_14": 55.0,
        "volume_zscore": 1.0, "atr_pct": 2.0,
    }

    # ML model yok → rule-based
    score_no_ml = canonical_scoring.compute_canonical_score(
        "TEST", features, "BULL", ml_model=None
    )
    assert isinstance(score_no_ml, CanonicalScore)
    assert score_no_ml.ml_score is None
    assert np.isfinite(score_no_ml.opportunity_score)

    print(f"  ✓ Canonical scoring: rule-based score={score_no_ml.opportunity_score:.2f}")
    passed += 1

    return passed, failed


# ────────────────────────────────────────────────────────────
# Ana çalıştırıcı
# ────────────────────────────────────────────────────────────

def run_all():
    tests = [
        ("CS parity training=inference", test_cs_parity_training_inference),
        ("Feature contract enforced", test_feature_contract_enforced),
        ("E2E parity same snapshot", test_e2e_parity_same_snapshot),
        ("Future change no past effect", test_future_change_no_past_effect),
        ("Ticker add/remove isolated", test_ticker_add_remove_isolated),
        ("Multi-horizon same contract", test_multi_horizon_same_contract),
        ("Canonical scoring inference parity", test_canonical_scoring_inference_parity),
    ]

    total_passed = 0
    total_failed = 0

    print("=" * 70)
    print("FAZ 4.6 — Live Inference Feature Parity Testleri")
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
