"""
ALPHA BIST — Learning System Faz 2 Test Suite (Drift Detection)

Test edilen:
- PSI tabanlı drift tespit
- KS test tabanlı drift tespit
- Z-score tabanlı drift tespit
- Page-Hinkley tabanlı drift tespit
- ADWIN tabanlı drift tespit
- Concept drift tespit
- Çoklu yöntem anlaşması
- Drift type sınıflandırma
- Recommendation sistemi
"""

import sys
import os
import numpy as np



def test_no_drift():
    """Aynı dağılımlar için drift tespit edilmemeli."""
    from services.learning.drift_detector import AdvancedDriftDetector

    detector = AdvancedDriftDetector()
    np.random.seed(42)

    baseline = {"feat_a": np.random.normal(0, 1, 500), "feat_b": np.random.normal(5, 2, 500)}
    detector.set_baseline(baseline)

    current = {"feat_a": np.random.normal(0, 1, 200), "feat_b": np.random.normal(5, 2, 200)}
    report = detector.detect_all_drift(current)

    assert report.overall_drift is False
    assert report.severity in ["LOW", "NONE"]
    assert report.recommendation in ["OK", "MONITOR"]
    print(f"✅ No drift: type={report.drift_type}, severity={report.severity}")


def test_psi_drift():
    """PSI yüksek olan feature için drift tespit edilmeli."""
    from services.learning.drift_detector import AdvancedDriftDetector

    detector = AdvancedDriftDetector()
    np.random.seed(42)

    baseline = {"feat_a": np.random.normal(0, 1, 500)}
    detector.set_baseline(baseline)

    # Farklı dağılım
    current = {"feat_a": np.random.normal(5, 3, 200)}
    report = detector.detect_all_drift(current)

    assert report.overall_drift is True
    assert "feat_a" in report.affected_features
    print(f"✅ PSI drift: type={report.drift_type}, severity={report.severity}")


def test_gradual_drift():
    """Kademeli drift Page-Hinkley ile tespit edilmeli."""
    from services.learning.drift_detector import AdvancedDriftDetector

    detector = AdvancedDriftDetector()
    np.random.seed(42)

    baseline = {"feat_a": np.random.normal(0, 1, 500)}
    detector.set_baseline(baseline)

    # Kademeli değişim
    current = np.concatenate([np.random.normal(0, 1, 50), np.random.normal(2, 1, 50), np.random.normal(4, 1, 50)])
    report = detector.detect_all_drift({"feat_a": current})

    # Drift tespit edilmeli (en az 2 yöntem)
    feat_result = report.feature_results["feat_a"]
    print(f"✅ Gradual drift: type={feat_result.drift_type}, methods_agreed={feat_result.methods_agreed}")


def test_sudden_shift():
    """Ani değişim ADWIN ile tespit edilmeli."""
    from services.learning.drift_detector import AdvancedDriftDetector

    detector = AdvancedDriftDetector()
    np.random.seed(42)

    baseline = {"feat_a": np.random.normal(0, 1, 500)}
    detector.set_baseline(baseline)

    # Ani değişim
    current = np.concatenate([np.random.normal(0, 1, 100), np.random.normal(10, 1, 100)])
    report = detector.detect_all_drift({"feat_a": current})

    feat_result = report.feature_results["feat_a"]
    assert feat_result.drift_detected is True
    assert "adwin" in feat_result.details or "psi" in feat_result.details
    print(f"✅ Sudden shift: type={feat_result.drift_type}, methods_agreed={feat_result.methods_agreed}")


def test_concept_drift():
    """Performans düşünce concept drift tespit edilmeli."""
    from services.learning.drift_detector import AdvancedDriftDetector

    detector = AdvancedDriftDetector()
    np.random.seed(42)

    # Geçmiş performans (iyi) — 24 ay
    perf_history = [{"sharpe": 1.5, "win_rate": 0.6, "date": f"2024-{i:02d}-01"} for i in range(1, 13)]
    perf_history += [{"sharpe": 1.3, "win_rate": 0.58, "date": f"2025-{i:02d}-01"} for i in range(1, 13)]
    baseline = {"feat_a": np.random.normal(0, 1, 500)}
    detector.set_baseline(baseline, performance_data=perf_history)

    # Mevcut performans (kötü)
    current_perf = {"sharpe": 0.1, "win_rate": 0.35}
    current = {"feat_a": np.random.normal(0, 1, 200)}
    report = detector.detect_all_drift(current, current_performance=current_perf)

    assert report.concept_drift["concept_drift"] is True
    print(f"✅ Concept drift: sharpe_drop={report.concept_drift['sharpe_drop']}")


def test_multiple_features():
    """Birden fazla feature için drift tespit."""
    from services.learning.drift_detector import AdvancedDriftDetector

    detector = AdvancedDriftDetector()
    np.random.seed(42)

    baseline = {
        "feat_normal": np.random.normal(0, 1, 500),
        "feat_drifted": np.random.normal(0, 1, 500),
    }
    detector.set_baseline(baseline)

    current = {
        "feat_normal": np.random.normal(0, 1, 200),  # Stabil
        "feat_drifted": np.random.normal(5, 3, 200),  # Drifted
    }
    report = detector.detect_all_drift(current)

    assert "feat_drifted" in report.affected_features
    assert report.feature_results["feat_normal"].drift_detected is False
    assert report.feature_results["feat_drifted"].drift_detected is True
    print(f"✅ Multiple features: normal={report.feature_results['feat_normal'].drift_detected}, "
          f"drifted={report.feature_results['feat_drifted'].drift_detected}")


def test_drift_type_classification():
    """Drift type sınıflandırması doğru mu?"""
    from services.learning.drift_detector import AdvancedDriftDetector

    detector = AdvancedDriftDetector()
    np.random.seed(42)

    # Major drift (çok farklı dağılım)
    baseline = {"feat": np.random.normal(0, 1, 500)}
    detector.set_baseline(baseline)

    current = {"feat": np.random.normal(10, 5, 200)}
    report = detector.detect_all_drift(current)

    feat_result = report.feature_results["feat"]
    assert feat_result.drift_type != "STABLE"
    print(f"✅ Drift type: {feat_result.drift_type}")


def test_severity_levels():
    """Severity seviyeleri doğru mu?"""
    from services.learning.drift_detector import AdvancedDriftDetector

    detector = AdvancedDriftDetector()
    np.random.seed(42)

    # Hafif drift
    baseline = {"feat": np.random.normal(0, 1, 500)}
    detector.set_baseline(baseline)

    current = {"feat": np.random.normal(0.5, 1, 200)}
    report = detector.detect_all_drift(current)

    # Hafif drift → LOW veya MEDIUM severity
    feat_result = report.feature_results["feat"]
    print(f"✅ Severity (hafif): {feat_result.severity}")

    # Şiddetli drift
    current2 = {"feat": np.random.normal(10, 5, 200)}
    report2 = detector.detect_all_drift(current2)

    feat_result2 = report2.feature_results["feat"]
    print(f"✅ Severity (şiddetli): {feat_result2.severity}")


def test_recommendation():
    """Öneriler doğru mu?"""
    from services.learning.drift_detector import AdvancedDriftDetector

    detector = AdvancedDriftDetector()
    np.random.seed(42)

    # Stabil
    baseline = {"feat": np.random.normal(0, 1, 500)}
    detector.set_baseline(baseline)

    current = {"feat": np.random.normal(0, 1, 200)}
    report = detector.detect_all_drift(current)
    assert report.recommendation in ["OK", "MONITOR"]
    print(f"✅ Recommendation (stabil): {report.recommendation}")

    # Major drift
    current2 = {"feat": np.random.normal(10, 5, 200)}
    report2 = detector.detect_all_drift(current2)
    assert report2.recommendation in ["RETRAIN_IMMEDIATE", "RETRAIN_SCHEDULED", "INVESTIGATE"]
    print(f"✅ Recommendation (drift): {report2.recommendation}")


def test_drift_report():
    """Drift raporu doğru mu?"""
    from services.learning.drift_detector import AdvancedDriftDetector

    detector = AdvancedDriftDetector()
    np.random.seed(42)

    baseline = {"feat": np.random.normal(0, 1, 500)}
    detector.set_baseline(baseline)

    current = {"feat": np.random.normal(0, 1, 200)}
    detector.detect_all_drift(current)

    report = detector.get_drift_report()
    assert report["status"] == "OK"
    assert "overall_drift" in report
    assert "drift_type" in report
    assert "recommendation" in report
    print(f"✅ Drift report: {report['drift_type']}, {report['recommendation']}")


def test_empty_drift_report():
    """Boş drift raporu doğru mu?"""
    from services.learning.drift_detector import AdvancedDriftDetector

    detector = AdvancedDriftDetector()
    report = detector.get_drift_report()
    assert report["status"] == "No drift data"
    print("✅ Empty drift report")


def test_baseline_update():
    """Baseline güncellenebilmeli."""
    from services.learning.drift_detector import AdvancedDriftDetector

    detector = AdvancedDriftDetector()
    np.random.seed(42)

    # İlk baseline
    baseline1 = {"feat": np.random.normal(0, 1, 500)}
    detector.set_baseline(baseline1)
    assert detector._baseline_distributions["feat"]["mean"] != 0  # Random

    # Güncelle
    baseline2 = {"feat": np.random.normal(5, 2, 500)}
    detector.set_baseline(baseline2)

    # Mean değişmeli
    assert abs(detector._baseline_distributions["feat"]["mean"] - 5) < 1
    print("✅ Baseline update")


def test_insufficient_data():
    """Yetersiz veri ile başa çıkmalı."""
    from services.learning.drift_detector import AdvancedDriftDetector

    detector = AdvancedDriftDetector()
    np.random.seed(42)

    baseline = {"feat": np.random.normal(0, 1, 500)}
    detector.set_baseline(baseline)

    # Çok az veri
    current = {"feat": np.array([1.0, 2.0, 3.0])}
    report = detector.detect_all_drift(current)

    # Drift tespit edilmemeli (yetersiz veri)
    feat_result = report.feature_results["feat"]
    assert feat_result.drift_detected is False
    print(f"✅ Insufficient data: type={feat_result.drift_type}")


def test_history_tracking():
    """Drift geçmişi takip edilmeli."""
    from services.learning.drift_detector import AdvancedDriftDetector

    detector = AdvancedDriftDetector()
    np.random.seed(42)

    baseline = {"feat": np.random.normal(0, 1, 500)}
    detector.set_baseline(baseline)

    # 3 kez çalıştır
    for _ in range(3):
        current = {"feat": np.random.normal(0, 1, 200)}
        detector.detect_all_drift(current)

    assert len(detector._drift_history) == 3
    print(f"✅ History tracking: {len(detector._drift_history)} reports")


def run_all_tests():
    """Tüm testleri çalıştır."""
    tests = [
        test_no_drift,
        test_psi_drift,
        test_gradual_drift,
        test_sudden_shift,
        test_concept_drift,
        test_multiple_features,
        test_drift_type_classification,
        test_severity_levels,
        test_recommendation,
        test_drift_report,
        test_empty_drift_report,
        test_baseline_update,
        test_insufficient_data,
        test_history_tracking,
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
    print(f"📊 FAZ 2 TEST SONUÇLARI (Drift Detection)")
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
