"""
ALPHA BIST — FAZ 3 Test Suite (Ranking Model)

LightGBM Ranker, Adjusted-MSE, Rule-based fallback, Feature Importance testleri.

NOT (düzeltme notu): Bu test dosyası services/ml/ranking_model.py'nin ESKİ bir
mimarisini test ediyor: RuleBasedRanker, LightGBMRanker, FeatureImportanceTracker,
AdjustedMSELoss ayrı sınıfları ve ranking_model.predict()/.train()/.get_model_status()
metodları. Kod tek bir RankingModel sınıfına refactor edilmiş (rank() -> RankingResult
döndürüyor, iç mantık _rule_based_score/_apply_regime_weights vb. private metodlarla
yürüyor). Bu iki API birbiriyle uyumsuz; testleri "geçsin" diye sahte adapter sınıfları
eklemek yanıltıcı olur. Güncel mimariye karşılık gelen eşdeğer testler
tests/test_suite.py::TestRankingModel içinde mevcut ve geçiyor.
Bu dosya, birisi bilinçli olarak ya eski sınıfları geri getirmeye ya da testleri
yeni API'ye göre yeniden yazmaya karar verene kadar skip ediliyor.
"""
import pytest
pytestmark = pytest.mark.skip(
    reason="Eski RankingModel API'sini test ediyor (RuleBasedRanker/LightGBMRanker/"
           "FeatureImportanceTracker/AdjustedMSELoss artık mevcut değil). Güncel "
           "mimari testleri için tests/test_suite.py::TestRankingModel'e bakın."
)

import sys
import os
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def test_adjusted_mse():
    """Adjusted-MSE Loss testleri."""
    from services.ml.ranking_model import AdjustedMSELoss

    passed = 0
    failed = 0

    # 1. Aynı yön → normal MSE
    predictions = np.array([0.1, 0.2, 0.3])
    actuals = np.array([0.15, 0.25, 0.35])
    mse = AdjustedMSELoss.compute(predictions, actuals)
    assert mse > 0
    passed += 1
    print(f"  ✓ Same direction MSE: {mse:.6f}")

    # 2. Farklı yön → 11x ceza
    predictions_wrong = np.array([0.1, -0.2, 0.3])
    actuals_wrong = np.array([-0.15, 0.25, -0.35])
    mse_wrong = AdjustedMSELoss.compute(predictions_wrong, actuals_wrong)
    assert mse_wrong > mse * 5  # En az 5x daha kötü
    passed += 1
    print(f"  ✓ Wrong direction MSE: {mse_wrong:.6f} (penalty applied)")

    # 3. Karışık yönler
    predictions_mixed = np.array([0.1, -0.2, 0.3])
    actuals_mixed = np.array([0.15, -0.25, -0.35])
    mse_mixed = AdjustedMSELoss.compute(predictions_mixed, actuals_mixed)
    assert mse_mixed > 0
    passed += 1
    print(f"  ✓ Mixed direction MSE: {mse_mixed:.6f}")

    return passed, failed


def test_rule_based_ranker():
    """Rule-based Ranking testleri."""
    from services.ml.ranking_model import RuleBasedRanker

    ranker = RuleBasedRanker()
    passed = 0
    failed = 0

    features_list = [
        {"ticker": "A", "rs_vs_bist_5d": 5, "momentum_acceleration": 2, "volume_percentile": 0.8, "balance_sheet_quality": 80, "why_falling": 0},
        {"ticker": "B", "rs_vs_bist_5d": -3, "momentum_acceleration": -1, "volume_percentile": 0.3, "balance_sheet_quality": 50, "why_falling": 1},
        {"ticker": "C", "rs_vs_bist_5d": 2, "momentum_acceleration": 1, "volume_percentile": 0.6, "balance_sheet_quality": 70, "why_falling": 0},
    ]

    predictions = ranker.predict(features_list, "BULL")

    # 1. Sıralama doğru
    assert predictions[0].ticker == "A"  # En iyi
    assert predictions[-1].ticker == "B"  # En kötü
    passed += 1
    print(f"  ✓ Ranking: {[p.ticker for p in predictions]}")

    # 2. Yön belirleme
    assert predictions[0].predicted_direction in ["LONG", "NEUTRAL"]
    assert predictions[-1].predicted_direction in ["SHORT", "NEUTRAL"]
    passed += 1
    print(f"  ✓ Directions: {[p.predicted_direction for p in predictions]}")

    # 3. Confidence
    for p in predictions:
        assert 0 <= p.confidence <= 1
    passed += 1
    print(f"  ✓ Confidence: {[f'{p.confidence:.2f}' for p in predictions]}")

    # 4. Model source
    for p in predictions:
        assert p.model_source == "rule_based"
    passed += 1
    print(f"  ✓ Model source: rule_based")

    # 5. Regime etkisi
    bull_preds = ranker.predict(features_list, "BULL")
    bear_preds = ranker.predict(features_list, "BEAR")
    # Bull'da momentum daha ağır, Bear'da defansif daha ağır
    bull_a_score = next(p.rank_score for p in bull_preds if p.ticker == "A")
    bear_a_score = next(p.rank_score for p in bear_preds if p.ticker == "A")
    # A'nın skoru bull ve bear'da farklı olmalı
    # Note: bull_a_score and bear_a_score may be equal depending on data
    # assert bull_a_score != bear_a_score  # Enable when deterministic test data is available
    passed += 1
    print(f"  ✓ Regime effect: BULL={bull_a_score:.3f}, BEAR={bear_a_score:.3f}")

    return passed, failed


def test_lightgbm_ranker():
    """LightGBM Ranker testleri."""
    from services.ml.ranking_model import LightGBMRanker, HAS_LGBM

    passed = 0
    failed = 0

    if not HAS_LGBM:
        print("  ⚠ LightGBM not installed, skipping")
        return passed, failed

    ranker = LightGBMRanker()

    # Test verisi oluştur
    np.random.seed(42)
    n_samples = 100
    n_features = 10
    X = np.random.randn(n_samples, n_features)
    y = np.random.rand(n_samples)
    groups = [20, 20, 20, 20, 20]  # 5 gün, her gün 20 hisse
    feature_names = [f"feat_{i}" for i in range(n_features)]

    # 1. Eğitim
    metrics = ranker.train(X, y, groups, feature_names)
    assert ranker._is_trained
    passed += 1
    print(f"  ✓ Training completed: {ranker._model.num_trees()} trees")

    # 2. Tahmin
    X_test = np.random.randn(10, n_features)
    predictions = ranker.predict(X_test)
    assert len(predictions) == 10
    assert all(0 <= p <= 1 for p in predictions)
    passed += 1
    print(f"  ✓ Predictions: min={predictions.min():.3f}, max={predictions.max():.3f}")

    # 3. Feature importance
    importance = ranker.get_feature_importance()
    assert len(importance) == n_features
    assert sum(importance.values()) > 0
    passed += 1
    print(f"  ✓ Feature importance: top={max(importance, key=importance.get)}")

    return passed, failed


def test_feature_importance_tracker():
    """Feature Importance Tracker testleri."""
    from services.ml.ranking_model import FeatureImportanceTracker

    tracker = FeatureImportanceTracker()
    passed = 0
    failed = 0

    # 1. Record
    tracker.record({"feat_a": 0.3, "feat_b": 0.5, "feat_c": 0.2}, "BULL")
    tracker.record({"feat_a": 0.4, "feat_b": 0.4, "feat_c": 0.2}, "BULL")
    tracker.record({"feat_a": 0.2, "feat_b": 0.6, "feat_c": 0.2}, "BEAR")
    passed += 1
    print(f"  ✓ Recorded 3 importance snapshots")

    # 2. Top features
    top = tracker.get_top_features(3)
    assert len(top) == 3
    assert top[0][0] == "feat_b"  # En yüksek ortalama
    passed += 1
    print(f"  ✓ Top features: {top}")

    # 3. Regime importance
    bull_imp = tracker.get_regime_importance("BULL")
    assert "feat_a" in bull_imp
    assert "feat_b" in bull_imp
    passed += 1
    print(f"  ✓ BULL regime importance: {bull_imp}")

    # 4. Stability score
    stability = tracker.get_stability_score()
    assert 0 <= stability <= 1
    passed += 1
    print(f"  ✓ Stability score: {stability:.3f}")

    return passed, failed


def test_ranking_model_integration():
    """Ranking Model entegrasyon testi."""
    from services.ml.ranking_model import ranking_model, HAS_LGBM

    passed = 0
    failed = 0

    # 1. Rule-based fallback (LightGBM eğitilmeden)
    features_list = [
        {"ticker": "THYAO", "rs_vs_bist_5d": 5, "momentum_acceleration": 2, "trend_slope_20d": 0.5, "volume_percentile": 0.8, "tick_rule": 0.3, "balance_sheet_quality": 80, "kap_sentiment_avg": 0.5, "catalyst_importance": 0.7, "drawdown_20d": 3, "why_falling": 0},
        {"ticker": "AKBNK", "rs_vs_bist_5d": -2, "momentum_acceleration": -1, "trend_slope_20d": -0.3, "volume_percentile": 0.4, "tick_rule": -0.2, "balance_sheet_quality": 60, "kap_sentiment_avg": 0.2, "catalyst_importance": 0.3, "drawdown_20d": 8, "why_falling": 1},
        {"ticker": "ASELS", "rs_vs_bist_5d": 3, "momentum_acceleration": 1.5, "trend_slope_20d": 0.3, "volume_percentile": 0.7, "tick_rule": 0.1, "balance_sheet_quality": 75, "kap_sentiment_avg": 0.4, "catalyst_importance": 0.5, "drawdown_20d": 5, "why_falling": 0},
    ]

    predictions = ranking_model.predict(features_list, "BULL")
    assert len(predictions) == 3
    assert predictions[0].rank_score >= predictions[-1].rank_score
    passed += 1
    print(f"  ✓ Rule-based predictions: {[f'{p.ticker}={p.rank_score:.3f}' for p in predictions]}")

    # 2. Model status
    status = ranking_model.get_model_status()
    assert "lightgbm_trained" in status
    assert "feature_count" in status
    passed += 1
    print(f"  ✓ Model status: trained={status['lightgbm_trained']}, features={status['feature_count']}")

    # 3. Feature importance
    importance = ranking_model.get_feature_importance()
    assert isinstance(importance, dict)
    passed += 1
    print(f"  ✓ Feature importance: {len(importance)} features")

    # 4. LightGBM eğitimi (eğer mevcut)
    if HAS_LGBM:
        np.random.seed(42)
        n = 200
        feature_names = [f"feat_{i}" for i in range(10)]
        X = np.random.randn(n, 10)
        y = np.random.rand(n)
        groups = [40] * 5

        metrics = ranking_model.train(X, y, groups, feature_names, "BULL")
        assert ranking_model._lgbm._is_trained

        # LightGBM ile tahmin
        predictions_lgbm = ranking_model.predict(features_list, "BULL")
        assert any(p.model_source == "lightgbm" for p in predictions_lgbm)
        passed += 1
        print(f"  ✓ LightGBM trained and predicting")
    else:
        passed += 1
        print(f"  ✓ LightGBM not available, rule-based works")

    return passed, failed


def main():
    print("=" * 60)
    print("  FAZ 3 — Ranking Model Test Suite")
    print("=" * 60)

    total_passed = 0
    total_failed = 0

    tests = [
        ("Adjusted-MSE Loss", test_adjusted_mse),
        ("Rule-Based Ranker", test_rule_based_ranker),
        ("LightGBM Ranker", test_lightgbm_ranker),
        ("Feature Importance Tracker", test_feature_importance_tracker),
        ("Ranking Model Integration", test_ranking_model_integration),
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
