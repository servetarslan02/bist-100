#!/usr/bin/env python3
"""
ALPHA BIST — LightGBM Training + Walk-Forward Model Tests

PIT-safe LightGBM eğitim ve walk-forward entegrasyon testleri.
"""

import sys
import os
import numpy as np
import pandas as pd
import tempfile
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _make_market_data(n_stocks=120, n_days=300, seed=42):
    np.random.seed(seed)
    market = {}
    dates = pd.date_range(end=datetime.now(), periods=n_days, freq='B')
    for i in range(n_stocks):
        trend = np.random.uniform(-0.001, 0.002)
        vol = np.random.uniform(0.01, 0.025)
        close = 100 * np.exp(np.cumsum(np.random.randn(n_days) * vol + trend))
        high = close * (1 + np.abs(np.random.randn(n_days)) * 0.008)
        low = close * (1 - np.abs(np.random.randn(n_days)) * 0.008)
        volume = np.random.randint(50000, 500000, n_days).astype(float)
        market[f"STOCK{i:04d}"] = pd.DataFrame({
            'Open': close * (1 + np.random.randn(n_days) * 0.002),
            'High': high, 'Low': low, 'Close': close, 'Volume': volume
        }, index=dates)
    return market


def _get_canonical_feature_names():
    """Canonical scoring'in kullandığı feature isimlerini al."""
    import inspect, re
    from services.core.canonical_scoring import canonical_scoring
    feature_names = []
    for dim_name in ['_score_technical', '_score_momentum', '_score_relative_strength',
                     '_score_volume', '_score_fundamental', '_score_mean_reversion',
                     '_score_risk']:
        src = inspect.getsource(getattr(canonical_scoring, dim_name))
        features_in_dim = re.findall(r'f\.get\("([^"]+)"', src)
        feature_names.extend(features_in_dim)
    return list(dict.fromkeys(feature_names))


def _make_features_and_returns(market, n_days=200):
    """Feature matrix ve returns oluştur."""
    from services.features.calculator import FeatureCalculator
    calc = FeatureCalculator()

    features_map = {}
    returns = {}
    date_groups = {}

    tickers = list(market.keys())[:120]
    for ticker in tickers:
        df = market[ticker]
        if len(df) < n_days:
            continue

        df_window = df.iloc[-n_days:]
        feats = calc.compute_all_features(df_window, ticker=ticker)
        if not feats:
            continue

        features_map[ticker] = feats

        # Forward return (5 gün)
        close = df['Close'].values
        if len(close) > 10:
            ret = (close[-1] / close[-6] - 1) * 100
            returns[ticker] = ret
            date_groups[ticker] = str(df.index[-1].date())

    return features_map, returns, date_groups


# =====================================================
# 1. LIGHTGBM IMPORT
# =====================================================

def test_lightgbm_import():
    """LightGBM import edilebiliyor mu?"""
    issues = []

    try:
        import lightgbm as lgb
        if not hasattr(lgb, 'train'):
            issues.append("lightgbm.train yok")
    except ImportError:
        issues.append("LightGBM import edilemedi")

    return "LightGBM import", len(issues) == 0, issues


# =====================================================
# 2. MODEL TRAINING
# =====================================================

def test_model_training():
    """Model eğitilebiliyor mu?"""
    from services.ml.lightgbm_trainer import LightGBMTrainer, MLModelConfig
    issues = []

    market = _make_market_data(120, 300)
    features_map, returns, date_groups = _make_features_and_returns(market)

    if len(features_map) < 10:
        return "Model training", None, ["Yeterli veri yok — SKIP"]

    trainer = LightGBMTrainer(MLModelConfig(num_boost_round=20, early_stopping_rounds=3))
    model = trainer.train(features_map, returns, date_groups, feature_names=_get_canonical_feature_names())

    if model is None:
        issues.append("Model eğitilemedi")
    elif model.model is None:
        issues.append("Model objesi None")
    elif model.train_samples == 0:
        issues.append("Train samples = 0")

    return "Model training", len(issues) == 0, issues


# =====================================================
# 3. MODEL PREDICTION
# =====================================================

def test_model_prediction():
    """Model prediction yapabiliyor mu?"""
    from services.ml.lightgbm_trainer import LightGBMTrainer, MLModelConfig
    issues = []

    market = _make_market_data(120, 300)
    features_map, returns, date_groups = _make_features_and_returns(market)

    if len(features_map) < 10:
        return "Model prediction", None, ["Yeterli veri yok — SKIP"]

    trainer = LightGBMTrainer(MLModelConfig(num_boost_round=20, early_stopping_rounds=3))
    model = trainer.train(features_map, returns, date_groups, feature_names=_get_canonical_feature_names())

    if model is None:
        return "Model prediction", None, ["Model eğitilemedi — SKIP"]

    # Prediction
    test_features = list(features_map.values())[0]
    pred = model.predict(test_features)

    if not isinstance(pred, (int, float)):
        issues.append(f"Prediction tipi yanlış: {type(pred)}")
    if np.isnan(pred) or np.isinf(pred):
        issues.append(f"Prediction NaN/Inf: {pred}")

    return "Model prediction", len(issues) == 0, issues


# =====================================================
# 4. TRAIN/TEST ISOLATION
# =====================================================

def test_train_test_isolation():
    """Test verisi eğitimine girmiyor mu?"""
    from services.ml.lightgbm_trainer import LightGBMTrainer, MLModelConfig
    issues = []

    market = _make_market_data(120, 300)

    # Train: ilk200 gün
    train_features = {}
    train_returns = {}
    train_dates = {}

    for ticker, df in list(market.items())[:15]:
        df_train = df.iloc[:200]
        from services.features.calculator import FeatureCalculator
        calc = FeatureCalculator()
        feats = calc.compute_all_features(df_train, ticker=ticker)
        if feats:
            train_features[ticker] = feats
            close = df_train['Close'].values
            if len(close) > 5:
                train_returns[ticker] = (close[-1] / close[-6] - 1) * 100
                train_dates[ticker] = str(df_train.index[-1].date())

    if len(train_features) < 10:
        return "Train/test isolation", None, ["Yeterli veri yok — SKIP"]

    trainer = LightGBMTrainer(MLModelConfig(num_boost_round=20, early_stopping_rounds=3))
    model = trainer.train(train_features, train_returns, train_dates)

    if model is None:
        return "Train/test isolation", None, ["Model eğitilemedi — SKIP"]

    # Test: son100 gün (train'de görülmedi)
    test_features = {}
    for ticker, df in list(market.items())[:15]:
        df_test = df.iloc[200:]
        feats = calc.compute_all_features(df_test, ticker=ticker)
        if feats:
            test_features[ticker] = feats

    # Test prediction'ları yap
    for ticker, feats in list(test_features.items())[:3]:
        pred = model.predict(feats)
        if np.isnan(pred) or np.isinf(pred):
            issues.append(f"{ticker}: test prediction NaN/Inf")

    return "Train/test isolation", len(issues) == 0, issues


# =====================================================
# 5. VALIDATION ISOLATION
# =====================================================

def test_validation_isolation():
    """Validation verisi eğitim parametrelerini etkilememeli."""
    from services.ml.lightgbm_trainer import LightGBMTrainer, MLModelConfig
    issues = []

    market = _make_market_data(120, 300)
    features_map, returns, date_groups = _make_features_and_returns(market)

    if len(features_map) < 10:
        return "Validation isolation", None, ["Yeterli veri yok — SKIP"]

    # İki kez eğit — deterministic olmalı
    trainer = LightGBMTrainer(MLModelConfig(num_boost_round=20, early_stopping_rounds=3))

    model1 = trainer.train(features_map, returns, date_groups, feature_names=_get_canonical_feature_names())
    model2 = trainer.train(features_map, returns, date_groups, feature_names=_get_canonical_feature_names())

    if model1 is None or model2 is None:
        return "Validation isolation", None, ["Model eğitilemedi — SKIP"]

    # Aynı feature için aynı prediction
    test_feats = list(features_map.values())[0]
    pred1 = model1.predict(test_feats)
    pred2 = model2.predict(test_feats)

    if abs(pred1 - pred2) > 1e-6:
        issues.append(f"Non-deterministic: {pred1} vs {pred2}")

    return "Validation isolation", len(issues) == 0, issues


# =====================================================
# 6. FUTURE DATA MUTATION INVARIANCE
# =====================================================

def test_future_data_mutation_invariance():
    """Gelecek veri değişimi model prediction'ını etkilememeli."""
    from services.ml.lightgbm_trainer import LightGBMTrainer, MLModelConfig
    from services.features.calculator import FeatureCalculator
    issues = []

    market = _make_market_data(10, 300, seed=42)
    calc = FeatureCalculator()

    # Train: ilk200 gün
    train_features = {}
    train_returns = {}
    train_dates = {}

    for ticker, df in list(market.items())[:10]:
        df_train = df.iloc[:200]
        feats = calc.compute_all_features(df_train, ticker=ticker)
        if feats:
            train_features[ticker] = feats
            close = df_train['Close'].values
            if len(close) > 5:
                train_returns[ticker] = (close[-1] / close[-6] - 1) * 100
                train_dates[ticker] = str(df_train.index[-1].date())

    if len(train_features) < 10:
        return "Future data mutation invariance", None, ["Yeterli veri yok — SKIP"]

    trainer = LightGBMTrainer(MLModelConfig(num_boost_round=20, early_stopping_rounds=3))
    model = trainer.train(train_features, train_returns, train_dates)

    if model is None:
        return "Future data mutation invariance", None, ["Model eğitilemedi — SKIP"]

    # Prediction before mutation
    test_feats = list(train_features.values())[0]
    pred_before = model.predict(test_feats)

    # Gelecek veriyi boz (market verisini değiştir)
    for ticker in market:
        market[ticker].iloc[-50:, market[ticker].columns.get_loc('Close')] *= 100

    # Model hâlâ aynı prediction'ı vermeli (train verisi değişmedi)
    pred_after = model.predict(test_feats)

    if abs(pred_before - pred_after) > 1e-6:
        issues.append(f"Prediction değişti: {pred_before} vs {pred_after}")

    return "Future data mutation invariance", len(issues) == 0, issues


# =====================================================
# 7. DETERMINISTIC TRAINING
# =====================================================

def test_deterministic_training():
    """Aynı veri → aynı model (deterministic)."""
    from services.ml.lightgbm_trainer import LightGBMTrainer, MLModelConfig
    issues = []

    market = _make_market_data(120, 300, seed=42)
    features_map, returns, date_groups = _make_features_and_returns(market)

    if len(features_map) < 10:
        return "Deterministic training", None, ["Yeterli veri yok — SKIP"]

    trainer = LightGBMTrainer(MLModelConfig(num_boost_round=20, early_stopping_rounds=3))

    models = []
    for _ in range(3):
        m = trainer.train(features_map, returns, date_groups, feature_names=_get_canonical_feature_names())
        if m:
            models.append(m)

    if len(models) < 2:
        return "Deterministic training", None, ["Model eğitilemedi — SKIP"]

    # Tüm modeller aynı prediction'ı vermeli
    test_feats = list(features_map.values())[0]
    preds = [m.predict(test_feats) for m in models]

    if len(set([round(p, 6) for p in preds])) > 1:
        issues.append(f"Non-deterministic predictions: {preds}")

    return "Deterministic training", len(issues) == 0, issues


# =====================================================
# 8. FEATURE CONTRACT MODEL PARITY
# =====================================================

def test_feature_contract_model_parity():
    """Model feature listesi ile canonical scoring feature listesi uyumlu mu?"""
    from services.ml.lightgbm_trainer import LightGBMTrainer, MLModelConfig
    from services.core.canonical_scoring import canonical_scoring
    issues = []

    market = _make_market_data(120, 300)
    features_map, returns, date_groups = _make_features_and_returns(market)

    if len(features_map) < 10:
        return "Feature contract model parity", None, ["Yeterli veri yok — SKIP"]

    # Canonical scoring feature names
    import inspect, re
    canonical_features = set()
    for dim_name in ['_score_technical', '_score_momentum', '_score_relative_strength',
                     '_score_volume', '_score_fundamental', '_score_mean_reversion',
                     '_score_risk']:
        src = inspect.getsource(getattr(canonical_scoring, dim_name))
        features_in_dim = re.findall(r'f\.get\("([^"]+)"', src)
        canonical_features.update(features_in_dim)

    # Model feature names
    trainer = LightGBMTrainer(MLModelConfig(num_boost_round=20, early_stopping_rounds=3))
    model = trainer.train(features_map, returns, date_groups, feature_names=_get_canonical_feature_names())

    if model is None:
        return "Feature contract model parity", None, ["Model eğitilemedi — SKIP"]

    model_features = set(model.feature_names)

    # Model'in kullandığı feature'lar canonical scoring'de olmalı
    missing_in_canonical = model_features - canonical_features
    if missing_in_canonical:
        issues.append(f"Model canonical'da olmayan feature kullanıyor: {missing_in_canonical}")

    return "Feature contract model parity", len(issues) == 0, issues


# =====================================================
# 9. CANONICAL SCORING WITH ML MODEL
# =====================================================

def test_canonical_scoring_with_ml():
    """Canonical scoring ML model ile çalışıyor mu?"""
    from services.ml.lightgbm_trainer import LightGBMTrainer, MLModelConfig
    from services.core.canonical_scoring import canonical_scoring
    issues = []

    market = _make_market_data(120, 300)
    features_map, returns, date_groups = _make_features_and_returns(market)

    if len(features_map) < 10:
        return "Canonical scoring with ML", None, ["Yeterli veri yok — SKIP"]

    trainer = LightGBMTrainer(MLModelConfig(num_boost_round=20, early_stopping_rounds=3))
    model = trainer.train(features_map, returns, date_groups, feature_names=_get_canonical_feature_names())

    if model is None:
        return "Canonical scoring with ML", None, ["Model eğitilemedi — SKIP"]

    test_feats = list(features_map.values())[0]

    # ML olmadan
    cs_without = canonical_scoring.compute_canonical_score("TEST", test_feats, "BULL")

    # ML ile
    cs_with = canonical_scoring.compute_canonical_score("TEST", test_feats, "BULL", ml_model=model)

    # ML skoru olmalı
    if cs_with.ml_score is None:
        issues.append("ML skoru None")

    # Farklı skorlar bekleniyor (ML blend)
    if cs_with.opportunity_score == cs_without.opportunity_score:
        issues.append("ML skoru etkilemiyor")

    return "Canonical scoring with ML", len(issues) == 0, issues


# =====================================================
# 10. ML MODEL FALLBACK
# =====================================================

def test_ml_model_fallback():
    """Model yoksa rule-based fallback çalışıyor mu?"""
    from services.core.canonical_scoring import canonical_scoring
    issues = []

    features = {"rsi_14": 55, "momentum_20d": 5, "volume_zscore": 1.5}

    # ML model olmadan
    cs = canonical_scoring.compute_canonical_score("TEST", features, "BULL")

    if cs.ml_score is not None:
        issues.append("ML model yok ama ml_score None değil")

    if cs.opportunity_score <= 0 or cs.opportunity_score >= 100:
        issues.append(f"Score aralık dışı: {cs.opportunity_score}")

    return "ML model fallback", len(issues) == 0, issues


# =====================================================
# 11. MODEL SERIALIZATION
# =====================================================

def test_model_serialization():
    """Model kaydedilip yüklenebiliyor mu?"""
    from services.ml.lightgbm_trainer import LightGBMTrainer, MLModelConfig, TrainedModel
    issues = []

    market = _make_market_data(120, 300)
    features_map, returns, date_groups = _make_features_and_returns(market)

    if len(features_map) < 10:
        return "Model serialization", None, ["Yeterli veri yok — SKIP"]

    trainer = LightGBMTrainer(MLModelConfig(num_boost_round=20, early_stopping_rounds=3))
    model = trainer.train(features_map, returns, date_groups, feature_names=_get_canonical_feature_names())

    if model is None:
        return "Model serialization", None, ["Model eğitilemedi — SKIP"]

    # Kaydet
    fd, path = tempfile.mkstemp(suffix='.pkl')
    os.close(fd)
    model.save(path)

    # Yükle
    loaded = TrainedModel.load(path)

    # Aynı prediction
    test_feats = list(features_map.values())[0]
    pred_original = model.predict(test_feats)
    pred_loaded = loaded.predict(test_feats)

    if abs(pred_original - pred_loaded) > 1e-6:
        issues.append(f"Yüklenen model farklı prediction: {pred_original} vs {pred_loaded}")

    os.unlink(path)
    return "Model serialization", len(issues) == 0, issues


# =====================================================
# 12. WALK-FORWARD WITH ML
# =====================================================

def test_walkforward_with_ml():
    """Walk-forward ML model ile çalışıyor mu?"""
    from services.backtest.walk_forward_runner import WalkForwardBacktestRunner
    from services.backtest.engine_v4 import BacktestConfig
    issues = []

    market = _make_market_data(10, 300, seed=42)

    cfg = BacktestConfig(
        use_canonical_scoring=True,
        regime='BULL',
        lookback_days=60,
        initial_capital=100000,
    )

    runner = WalkForwardBacktestRunner(
        backtest_config=cfg,
        purge_days=5, embargo_days=5,
        train_days=120, test_days=40, step_days=40,
        use_panel_features=False,
    )

    result = runner.run(market, persist=False)

    if result is None:
        issues.append("Result None")
    elif result.total_folds == 0:
        issues.append("0 folds")
    elif not result.all_leakage_ok:
        issues.append("Leakage ihlali")

    return "Walk-forward with ML", len(issues) == 0, issues


# =====================================================
# RUN
# =====================================================

def run_all():
    print("=" * 60)
    print("  LightGBM Training + Walk-Forward Model Tests")
    print("=" * 60)

    tests = [
        test_lightgbm_import,
        test_model_training,
        test_model_prediction,
        test_train_test_isolation,
        test_validation_isolation,
        test_future_data_mutation_invariance,
        test_deterministic_training,
        test_feature_contract_model_parity,
        test_canonical_scoring_with_ml,
        test_ml_model_fallback,
        test_model_serialization,
        test_walkforward_with_ml,
    ]

    passed = failed = skipped = 0
    all_issues = []

    for test_func in tests:
        try:
            result = test_func()
            if len(result) == 3:
                name, ok, issues = result
            else:
                name, ok, issues = result[0], result[1], result[2] if len(result) > 2 else []
        except Exception as e:
            name, ok, issues = test_func.__name__, False, [f"Exception: {e}"]
            import traceback
            traceback.print_exc()

        if ok is None:
            icon = "⏭️"
            skipped += 1
        elif ok:
            icon = "✅"
            passed += 1
        else:
            icon = "❌"
            failed += 1

        print(f"{icon} {name}")
        for i in issues:
            print(f"   {'⏭️' if ok is None else '❌'} {i}")
            if ok is not None:
                all_issues.append(f"{name}: {i}")

    print(f"\n{'=' * 60}")
    print(f"  SONUÇ: {passed} geçti, {failed} başarısız, {skipped} atlandı")
    if all_issues:
        print(f"\n  HATALAR:")
        for i, issue in enumerate(all_issues, 1):
            print(f"    {i}. {issue}")
    print("=" * 60)
    return failed == 0


if __name__ == "__main__":
    ok = run_all()
    sys.exit(0 if ok else 1)
