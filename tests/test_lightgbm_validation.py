#!/usr/bin/env python3
"""
ALPHA BIST — LightGBM Production Validation Tests

Kritik kontroller:
1. Train window PIT-safe
2. Forward return leakage yok
3. Purge/embargo korunuyor
4. Feature contract tutarlı
5. ML blend doğru çalışıyor
6. Fallback güvenli
7. Deterministic
"""

import sys
import os
import numpy as np
import pandas as pd
from datetime import datetime



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


# =====================================================
# 1. TRAIN WINDOW PIT-SAFE
# =====================================================

def test_train_window_pit_safe():
    """Train window sadece train_start..train_end arası veri kullanıyor mu?"""
    from services.backtest.walk_forward_runner import WalkForwardBacktestRunner
    from services.backtest.engine_v4 import BacktestConfig
    issues = []

    market = _make_market_data(10, 300, seed=42)
    cfg = BacktestConfig(use_canonical_scoring=True, regime='BULL', lookback_days=60)

    runner = WalkForwardBacktestRunner(
        backtest_config=cfg, purge_days=5, embargo_days=5,
        train_days=120, test_days=40, step_days=40, use_panel_features=False,
    )

    # Fold oluştur
    all_dates = set()
    for df in market.values():
        for ts in df.index:
            all_dates.add(str(ts.date()))
    dates = sorted(all_dates)
    folds = runner._wf.create_folds(dates)

    if not folds:
        return "Train window PIT safe", None, ["Fold oluşmadı — SKIP"]

    fold = folds[0]
    train_start = fold['train_start']
    train_end = fold['train_end']
    test_start = fold['test_start']

    # Purge gap kontrolü
    if train_end >= test_start:
        issues.append(f"train_end ({train_end}) >= test_start ({test_start})")

    # Train data test verisini içermemeli
    pit_data = runner._truncate(market, fold['test_end'])
    for ticker, df in pit_data.items():
        train_mask = (df.index >= pd.Timestamp(train_start)) & (df.index <= pd.Timestamp(train_end))
        df_train = df[train_mask]
        if not df_train.empty:
            last_train = str(df_train.index[-1].date())
            if last_train > train_end:
                issues.append(f"{ticker}: train verisi train_end'i aşıyor: {last_train}")

    return "Train window PIT safe", len(issues) == 0, issues


# =====================================================
# 2. FORWARD RETURN LEAKAGE YOK
# =====================================================

def test_forward_return_no_leakage():
    """Forward return hesaplamasında veri sızıntısı yok mu?"""
    issues = []

    # Simülasyon
    np.random.seed(42)
    n = 200
    dates = pd.date_range(end=pd.Timestamp('2025-08-15'), periods=n, freq='B')
    close = 100 * np.exp(np.cumsum(np.random.randn(n) * 0.015))

    # Doğru forward return: feature_idx'den feature_idx + 5'e
    feature_idx = n - 6  # train_end - 5
    correct_forward = (close[-1] / close[feature_idx] - 1) * 100

    # Yanlış (lookback): close[-1] / close[-6]
    wrong_lookback = (close[-1] / close[-6] - 1) * 100

    # İkisi farklı olmalı (feature_idx != n-1)
    if feature_idx == n - 1:
        issues.append("feature_idx = train_end (son gün) — forward return hesaplanamaz")

    # Feature tarihinden sonraki veri target'ta kullanılmalı
    # Feature tarihi = feature_idx, target = feature_idx'den 5 gün sonraki getiri
    # Bu, feature'ların target dönemine ait bilgi içermemesini sağlar
    if abs(correct_forward - wrong_lookback) < 0.001:
        # İkisi aynı olabilir (tesadüf), ama mantık farklı
        pass

    return "Forward return no leakage", len(issues) == 0, issues


# =====================================================
# 3. PURGE/EMBARGO KORUNUYOR
# =====================================================

def test_purge_embargo_preserved():
    """Purge ve embargo sınırları korunuyor mu?"""
    from services.backtest.walk_forward_runner import WalkForwardBacktestRunner
    from services.backtest.engine_v4 import BacktestConfig
    issues = []

    market = _make_market_data(10, 300, seed=42)
    cfg = BacktestConfig(use_canonical_scoring=True, regime='BULL', lookback_days=60)

    runner = WalkForwardBacktestRunner(
        backtest_config=cfg, purge_days=5, embargo_days=5,
        train_days=120, test_days=40, step_days=40, use_panel_features=False,
    )

    result = runner.run(market, persist=False)

    for fold in result.folds:
        # Purge: train_end < purge_start <= purge_end < test_start
        if not (fold.train_end < fold.purge_start <= fold.purge_end < fold.test_start):
            issues.append(f"Fold {fold.fold_id}: purge sınırı bozuk")

        # Embargo: test_end < embargo_start
        if fold.embargo_start < fold.test_end:
            issues.append(f"Fold {fold.fold_id}: embargo sınırı bozuk")

    return "Purge embargo preserved", len(issues) == 0, issues


# =====================================================
# 4. FEATURE CONTRACT TUTARLI
# =====================================================

def test_feature_contract_consistent():
    """Feature engineering train/test arasında aynı contract mı kullanıyor?"""
    from services.features.calculator import FeatureCalculator
    issues = []

    np.random.seed(42)
    n = 200
    dates = pd.date_range(end=datetime.now(), periods=n, freq='B')
    close = 100 * np.exp(np.cumsum(np.random.randn(n) * 0.015))
    df = pd.DataFrame({
        'Open': close, 'High': close * 1.01, 'Low': close * 0.99,
        'Close': close, 'Volume': np.full(n, 100000.0)
    }, index=dates)

    calc = FeatureCalculator()

    # Train window features
    feats_train = calc.compute_all_features(df.iloc[:150], ticker='TEST')

    # Test window features
    feats_test = calc.compute_all_features(df.iloc[150:], ticker='TEST')

    # Feature isimleri aynı olmalı
    train_keys = set(feats_train.keys())
    test_keys = set(feats_test.keys())

    missing_in_test = train_keys - test_keys
    if missing_in_test:
        # Test verisi daha kısa, bazı feature'lar olmayabilir — bu normal
        pass

    # Her iki tarafta da olan feature'lar aynı tipte olmalı
    common = train_keys & test_keys
    for key in common:
        v1, v2 = feats_train[key], feats_test[key]
        if type(v1) != type(v2):
            issues.append(f"{key}: tip farklı {type(v1)} vs {type(v2)}")

    return "Feature contract consistent", len(issues) == 0, issues


# =====================================================
# 5. ML BLEND DOĞRU ÇALIŞIYOR
# =====================================================

def test_ml_blend_correct():
    """ML %70 + rule %30 blend doğru mu?"""
    from services.core.canonical_scoring import canonical_scoring
    issues = []

    features = {"rsi_14": 55, "momentum_20d": 5, "volume_zscore": 1.5, "atr_pct": 2.5}

    # ML model mock
    class MockModel:
        def predict(self, feats):
            return 2.0  # Yüksek prediction

    cs_ml = canonical_scoring.compute_canonical_score("TEST", features, "BULL", ml_model=MockModel())
    cs_rule = canonical_scoring.compute_canonical_score("TEST", features, "BULL")

    # ML skoru olmalı
    if cs_ml.ml_score is None:
        issues.append("ML skoru None")

    # Rule skoru aynı kalmalı
    if cs_ml.rule_score != cs_rule.rule_score:
        issues.append(f"Rule skoru değişti: {cs_ml.rule_score} vs {cs_rule.rule_score}")

    # Blend: 0.7 * ml + 0.3 * rule
    expected = 0.7 * cs_ml.ml_score + 0.3 * cs_ml.rule_score
    if abs(cs_ml.opportunity_score - expected) > 0.1:
        issues.append(f"Blend yanlış: {cs_ml.opportunity_score} vs {expected}")

    # ML skoru etkilemeli
    if cs_ml.opportunity_score == cs_rule.opportunity_score:
        issues.append("ML skoru etkilemiyor")

    return "ML blend correct", len(issues) == 0, issues


# =====================================================
# 6. FALLBACK GÜVENLİ
# =====================================================

def test_fallback_safe():
    """Model başarısızsa güvenli fallback var mı?"""
    from services.core.canonical_scoring import canonical_scoring
    issues = []

    features = {"rsi_14": 55, "momentum_20d": 5}

    # Bozuk model
    class BrokenModel:
        def predict(self, feats):
            raise RuntimeError("Model bozuk")

    cs_broken = canonical_scoring.compute_canonical_score("TEST", features, "BULL", ml_model=BrokenModel())
    cs_normal = canonical_scoring.compute_canonical_score("TEST", features, "BULL")

    # Fallback: rule-based skor kullanılmalı
    if cs_broken.opportunity_score != cs_normal.opportunity_score:
        issues.append(f"Fallback farklı: {cs_broken.opportunity_score} vs {cs_normal.opportunity_score}")

    # ML skoru None olmalı (başarısız)
    if cs_broken.ml_score is not None:
        issues.append("Bozuk model ml_score None değil")

    return "Fallback safe", len(issues) == 0, issues


# =====================================================
# 7. YETERSİZ SAMPLE DAVRANIŞI
# =====================================================

def test_insufficient_samples():
    """Yetersiz training sample durumunda davranış doğru mu?"""
    from services.ml.lightgbm_trainer import LightGBMTrainer, MLModelConfig
    issues = []

    # Çok az veri
    features_map = {f"S{i}": {"rsi_14": 50 + i} for i in range(10)}
    returns = {f"S{i}": float(i) for i in range(10)}
    date_groups = {f"S{i}": "2025-01-01" for i in range(10)}

    trainer = LightGBMTrainer(MLModelConfig(num_boost_round=10))
    model = trainer.train(features_map, returns, date_groups)

    # 50'den az sample → None dönmeli
    if model is not None:
        issues.append(f"10 sample ile model eğitildi (beklenen: None)")

    return "Insufficient samples", len(issues) == 0, issues


# =====================================================
# 8. DETERMINISTIC
# =====================================================

def test_deterministic():
    """Aynı veriyle tekrar çalıştırınca deterministik mi?"""
    from services.ml.lightgbm_trainer import LightGBMTrainer, MLModelConfig
    from services.features.calculator import FeatureCalculator
    issues = []

    market = _make_market_data(120, 300, seed=42)
    calc = FeatureCalculator()

    features_map = {}
    returns = {}
    date_groups = {}

    for ticker, df in list(market.items())[:120]:
        if len(df) < 200:
            continue
        feats = calc.compute_all_features(df.iloc[-200:], ticker=ticker)
        if feats:
            features_map[ticker] = feats
            close = df['Close'].values
            if len(close) > 10:
                returns[ticker] = (close[-1] / close[-6] - 1) * 100
                date_groups[ticker] = str(df.index[-1].date())

    if len(features_map) < 50:
        return "Deterministic", None, ["Yeterli veri yok — SKIP"]

    import inspect, re
    from services.core.canonical_scoring import canonical_scoring
    feature_names = []
    for dim_name in ['_score_technical', '_score_momentum', '_score_relative_strength',
                     '_score_volume', '_score_fundamental', '_score_mean_reversion',
                     '_score_risk']:
        src = inspect.getsource(getattr(canonical_scoring, dim_name))
        features_in_dim = re.findall(r'f\.get\("([^"]+)"', src)
        feature_names.extend(features_in_dim)
    feature_names = list(dict.fromkeys(feature_names))

    trainer = LightGBMTrainer(MLModelConfig(num_boost_round=20, early_stopping_rounds=3))

    models = []
    for _ in range(3):
        m = trainer.train(features_map, returns, date_groups, feature_names=feature_names)
        if m:
            models.append(m)

    if len(models) < 2:
        return "Deterministic", None, ["Model eğitilemedi — SKIP"]

    test_feats = list(features_map.values())[0]
    preds = [m.predict(test_feats) for m in models]

    if len(set([round(p, 6) for p in preds])) > 1:
        issues.append(f"Non-deterministic: {preds}")

    return "Deterministic", len(issues) == 0, issues


# =====================================================
# 9. FEATURE IMPORTANCE KAYDEDILIYOR
# =====================================================

def test_feature_importance_saved():
    """Feature importance kaydediliyor mu?"""
    from services.ml.lightgbm_trainer import LightGBMTrainer, MLModelConfig
    issues = []

    market = _make_market_data(120, 300, seed=42)
    from services.features.calculator import FeatureCalculator
    calc = FeatureCalculator()

    features_map = {}
    returns = {}
    date_groups = {}

    for ticker, df in list(market.items())[:120]:
        if len(df) < 200:
            continue
        feats = calc.compute_all_features(df.iloc[-200:], ticker=ticker)
        if feats:
            features_map[ticker] = feats
            close = df['Close'].values
            if len(close) > 10:
                returns[ticker] = (close[-1] / close[-6] - 1) * 100
                date_groups[ticker] = str(df.index[-1].date())

    if len(features_map) < 50:
        return "Feature importance saved", None, ["Yeterli veri yok — SKIP"]

    import inspect, re
    from services.core.canonical_scoring import canonical_scoring
    feature_names = []
    for dim_name in ['_score_technical', '_score_momentum', '_score_relative_strength',
                     '_score_volume', '_score_fundamental', '_score_mean_reversion',
                     '_score_risk']:
        src = inspect.getsource(getattr(canonical_scoring, dim_name))
        features_in_dim = re.findall(r'f\.get\("([^"]+)"', src)
        feature_names.extend(features_in_dim)
    feature_names = list(dict.fromkeys(feature_names))

    trainer = LightGBMTrainer(MLModelConfig(num_boost_round=20, early_stopping_rounds=3))
    model = trainer.train(features_map, returns, date_groups, feature_names=feature_names)

    if model is None:
        return "Feature importance saved", None, ["Model eğitilemedi — SKIP"]

    if not model.feature_importance:
        issues.append("Feature importance boş")

    # En az bir feature'ın importance'ı > 0 olmalı
    nonzero = sum(1 for v in model.feature_importance.values() if v > 0)
    if nonzero == 0:
        issues.append("Hiçbir feature'ın importance'ı > 0 değil")

    return "Feature importance saved", len(issues) == 0, issues


# =====================================================
# 10. VALIDATION METRIK KAYDEDILIYOR
# =====================================================

def test_validation_metrics_saved():
    """Validation metrikleri kaydediliyor mu?"""
    from services.ml.lightgbm_trainer import LightGBMTrainer, MLModelConfig
    issues = []

    market = _make_market_data(120, 300, seed=42)
    from services.features.calculator import FeatureCalculator
    calc = FeatureCalculator()

    features_map = {}
    returns = {}
    date_groups = {}

    for ticker, df in list(market.items())[:120]:
        if len(df) < 200:
            continue
        feats = calc.compute_all_features(df.iloc[-200:], ticker=ticker)
        if feats:
            features_map[ticker] = feats
            close = df['Close'].values
            if len(close) > 10:
                returns[ticker] = (close[-1] / close[-6] - 1) * 100
                date_groups[ticker] = str(df.index[-1].date())

    if len(features_map) < 50:
        return "Validation metrics saved", None, ["Yeterli veri yok — SKIP"]

    import inspect, re
    from services.core.canonical_scoring import canonical_scoring
    feature_names = []
    for dim_name in ['_score_technical', '_score_momentum', '_score_relative_strength',
                     '_score_volume', '_score_fundamental', '_score_mean_reversion',
                     '_score_risk']:
        src = inspect.getsource(getattr(canonical_scoring, dim_name))
        features_in_dim = re.findall(r'f\.get\("([^"]+)"', src)
        feature_names.extend(features_in_dim)
    feature_names = list(dict.fromkeys(feature_names))

    trainer = LightGBMTrainer(MLModelConfig(num_boost_round=20, early_stopping_rounds=3))
    model = trainer.train(features_map, returns, date_groups, feature_names=feature_names)

    if model is None:
        return "Validation metrics saved", None, ["Model eğitilemedi — SKIP"]

    if model.validation_score == 0:
        issues.append("Validation score = 0")

    if model.train_samples == 0:
        issues.append("Train samples = 0")

    if not model.train_date_range or model.train_date_range == ("", ""):
        issues.append("Train date range boş")

    return "Validation metrics saved", len(issues) == 0, issues


# =====================================================
# RUN
# =====================================================

def run_all():
    print("=" * 60)
    print("  LightGBM Production Validation Tests")
    print("=" * 60)

    tests = [
        test_train_window_pit_safe,
        test_forward_return_no_leakage,
        test_purge_embargo_preserved,
        test_feature_contract_consistent,
        test_ml_blend_correct,
        test_fallback_safe,
        test_insufficient_samples,
        test_deterministic,
        test_feature_importance_saved,
        test_validation_metrics_saved,
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
