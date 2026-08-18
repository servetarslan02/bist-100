"""
ALPHA BIST — Learning System Faz 7 Test Suite (Meta Learner)

Meta-learning testing:
- Performance recording
- Best model selection (regime-specific)
- Ensemble weight calculation
- Decay prediction
- Regime summary
- Edge cases (empty, single model, no data)
"""

import sys
import os
import numpy as np
from datetime import datetime, timezone, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def test_init():
    """Meta learner init."""
    from services.learning.meta_learner import MetaLearner

    m = MetaLearner()
    assert len(m._model_history) == 0
    assert len(m._regime_performance) == 0
    print("✅ Init")


def test_singleton():
    """Singleton doğru mu?"""
    from services.learning.meta_learner import meta_learner
    assert meta_learner is not None
    print("✅ Singleton")


def test_record_performance():
    """Performans kayıt."""
    from services.learning.meta_learner import MetaLearner

    m = MetaLearner()
    m.record_performance("m1", "BULL", {"sharpe": 1.5, "win_rate": 0.6, "ic": 0.05})

    assert len(m._model_history) == 1
    assert m._model_history[0].model_id == "m1"
    assert m._model_history[0].sharpe == 1.5
    print("✅ Record performance")


def test_record_multiple():
    """Birden fazla performans kayıt."""
    from services.learning.meta_learner import MetaLearner

    m = MetaLearner()
    for i in range(10):
        m.record_performance(f"m{i}", "BULL", {"sharpe": float(i), "win_rate": 0.5, "ic": 0.01})

    assert len(m._model_history) == 10
    print("✅ Record multiple")


def test_record_regime_tracking():
    """Rejim bazlı performans takibi."""
    from services.learning.meta_learner import MetaLearner

    m = MetaLearner()
    m.record_performance("m1", "BULL", {"sharpe": 1.5, "win_rate": 0.6, "ic": 0.05})
    m.record_performance("m1", "BEAR", {"sharpe": 0.3, "win_rate": 0.45, "ic": 0.01})

    assert "BULL" in m._regime_performance
    assert "BEAR" in m._regime_performance
    assert "m1" in m._regime_performance["BULL"]
    assert "m1" in m._regime_performance["BEAR"]
    print("✅ Record regime tracking")


def test_select_best_model():
    """En iyi model seçimi."""
    from services.learning.meta_learner import MetaLearner

    m = MetaLearner()
    m.record_performance("m1", "BULL", {"sharpe": 1.5, "win_rate": 0.6, "ic": 0.05})
    m.record_performance("m2", "BULL", {"sharpe": 0.8, "win_rate": 0.52, "ic": 0.03})
    m.record_performance("m3", "BULL", {"sharpe": 2.0, "win_rate": 0.7, "ic": 0.08})

    best = m.select_best_model("BULL")
    assert best == "m3"
    print(f"✅ Select best model: {best}")


def test_select_best_model_empty():
    """Olmayan rejim için None döndürmeli."""
    from services.learning.meta_learner import MetaLearner

    m = MetaLearner()
    best = m.select_best_model("UNKNOWN")
    assert best is None
    print("✅ Select best model empty")


def test_select_best_model_regime_specific():
    """Farklı rejimler farklı model seçmeli."""
    from services.learning.meta_learner import MetaLearner

    m = MetaLearner()
    # BULL: m1 daha iyi
    m.record_performance("m1", "BULL", {"sharpe": 2.0, "win_rate": 0.7, "ic": 0.08})
    m.record_performance("m2", "BULL", {"sharpe": 0.5, "win_rate": 0.5, "ic": 0.02})

    # BEAR: m2 daha iyi
    m.record_performance("m1", "BEAR", {"sharpe": 0.2, "win_rate": 0.45, "ic": 0.01})
    m.record_performance("m2", "BEAR", {"sharpe": 1.8, "win_rate": 0.65, "ic": 0.06})

    assert m.select_best_model("BULL") == "m1"
    assert m.select_best_model("BEAR") == "m2"
    print("✅ Select best model regime specific")


def test_ensemble_weights():
    """Ensemble weights doğru mu?"""
    from services.learning.meta_learner import MetaLearner

    m = MetaLearner()
    m.record_performance("m1", "BULL", {"sharpe": 2.0, "win_rate": 0.7, "ic": 0.08})
    m.record_performance("m2", "BULL", {"sharpe": 1.0, "win_rate": 0.55, "ic": 0.04})

    weights = m.calculate_ensemble_weights(["m1", "m2"], "BULL")

    assert weights["m1"] > weights["m2"]
    assert abs(sum(weights.values()) - 1.0) < 0.01
    print(f"✅ Ensemble weights: {weights}")


def test_ensemble_weights_equal():
    """Veri olmayan modeller eşit ağırlık almalı."""
    from services.learning.meta_learner import MetaLearner

    m = MetaLearner()
    weights = m.calculate_ensemble_weights(["m1", "m2", "m3"], "UNKNOWN")

    # Eşit ağırlık
    for w in weights.values():
        assert abs(w - 1/3) < 0.01
    print(f"✅ Ensemble weights equal: {weights}")


def test_ensemble_weights_normalize():
    """Weights toplamı 1 olmalı."""
    from services.learning.meta_learner import MetaLearner

    m = MetaLearner()
    for i in range(5):
        m.record_performance(f"m{i}", "BULL", {"sharpe": float(i+1), "win_rate": 0.5, "ic": 0.01})

    weights = m.calculate_ensemble_weights([f"m{i}" for i in range(5)], "BULL")
    total = sum(weights.values())
    assert abs(total - 1.0) < 0.01
    print(f"✅ Ensemble weights normalize: sum={total:.4f}")


def test_decay_prediction_no_data():
    """Yetersiz veri ile decay prediction."""
    from services.learning.meta_learner import MetaLearner

    m = MetaLearner()
    m.record_performance("m1", "BULL", {"sharpe": 1.5, "win_rate": 0.6, "ic": 0.05})

    result = m.predict_decay("m1")
    assert result["decay_predicted"] is False
    assert "Insufficient" in result["reason"]
    print("✅ Decay prediction no data")


def test_decay_prediction_declining():
    """Azalan performans decay prediction."""
    from services.learning.meta_learner import MetaLearner

    m = MetaLearner()
    for i in range(40):
        m.record_performance("m1", "BULL", {
            "sharpe": 2.0 - i * 0.05,  # Sürekli azalan
            "win_rate": 0.6,
            "ic": 0.05,
        })

    result = m.predict_decay("m1")
    assert result["decay_predicted"] is True
    assert result["trend"] < 0
    print(f"✅ Decay prediction declining: trend={result['trend']}, days={result['estimated_days_to_retrain']}")


def test_decay_prediction_stable():
    """Stabil performans decay prediction."""
    from services.learning.meta_learner import MetaLearner

    m = MetaLearner()
    for i in range(40):
        m.record_performance("m1", "BULL", {
            "sharpe": 1.5 + np.random.randn() * 0.01,  # Stabil
            "win_rate": 0.6,
            "ic": 0.05,
        })

    result = m.predict_decay("m1")
    assert result["decay_predicted"] is False
    print(f"✅ Decay prediction stable: trend={result['trend']}")


def test_regime_summary():
    """Rejim özeti doğru mu?"""
    from services.learning.meta_learner import MetaLearner

    m = MetaLearner()
    m.record_performance("m1", "BULL", {"sharpe": 1.5, "win_rate": 0.6, "ic": 0.05})
    m.record_performance("m1", "BEAR", {"sharpe": 0.3, "win_rate": 0.45, "ic": 0.01})
    m.record_performance("m2", "BULL", {"sharpe": 1.0, "win_rate": 0.55, "ic": 0.03})

    summary = m.get_regime_summary()
    assert "BULL" in summary
    assert "BEAR" in summary
    assert "m1" in summary["BULL"]
    assert "m1" in summary["BEAR"]
    assert "m2" in summary["BULL"]
    print(f"✅ Regime summary: {list(summary.keys())}")


def test_regime_summary_empty():
    """Boş regime summary."""
    from services.learning.meta_learner import MetaLearner

    m = MetaLearner()
    summary = m.get_regime_summary()
    assert len(summary) == 0
    print("✅ Regime summary empty")


def test_report():
    """Rapor doğru mu?"""
    from services.learning.meta_learner import MetaLearner

    m = MetaLearner()
    m.record_performance("m1", "BULL", {"sharpe": 1.5, "win_rate": 0.6, "ic": 0.05})
    m.record_performance("m2", "BEAR", {"sharpe": 0.3, "win_rate": 0.45, "ic": 0.01})

    report = m.get_report()
    assert report["total_records"] == 2
    assert report["regime_count"] == 2
    assert "regime_summary" in report
    print(f"✅ Report: {report['total_records']} records, {report['regime_count']} regimes")


def test_report_empty():
    """Boş rapor."""
    from services.learning.meta_learner import MetaLearner

    m = MetaLearner()
    report = m.get_report()
    assert report["total_records"] == 0
    assert report["regime_count"] == 0
    print("✅ Report empty")


def test_current_regime():
    """Current regime takip ediliyor mu?"""
    from services.learning.meta_learner import MetaLearner

    m = MetaLearner()
    m.record_performance("m1", "BULL", {"sharpe": 1.5, "win_rate": 0.6, "ic": 0.05})
    assert m._current_regime == "BULL"

    m.record_performance("m1", "BEAR", {"sharpe": 0.3, "win_rate": 0.45, "ic": 0.01})
    assert m._current_regime == "BEAR"
    print("✅ Current regime tracking")


# ===================== MAIN =====================

def run_all_tests():
    tests = [
        test_init,
        test_singleton,
        test_record_performance,
        test_record_multiple,
        test_record_regime_tracking,
        test_select_best_model,
        test_select_best_model_empty,
        test_select_best_model_regime_specific,
        test_ensemble_weights,
        test_ensemble_weights_equal,
        test_ensemble_weights_normalize,
        test_decay_prediction_no_data,
        test_decay_prediction_declining,
        test_decay_prediction_stable,
        test_regime_summary,
        test_regime_summary_empty,
        test_report,
        test_report_empty,
        test_current_regime,
    ]

    passed = 0
    failed = 0
    errors = []

    for test in tests:
        try:
            test()
            passed += 1
        except Exception as e:
            failed += 1
            errors.append((test.__name__, str(e)))
            print(f"❌ {test.__name__}: {e}")

    print(f"\n{'='*60}")
    print(f"📊 FAZ 7 TEST SONUÇLARI (Meta Learner)")
    print(f"{'='*60}")
    print(f"✅ Geçen: {passed}")
    print(f"❌ Başarısız: {failed}")
    print(f"📈 Toplam: {passed + failed}")

    if errors:
        print(f"\n🔍 Hatalar:")
        for name, err in errors:
            print(f"  - {name}: {err}")

    return failed == 0


if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)
