import structlog
logger = structlog.get_logger(__name__)
from typing import Any
"""
ALPHA BIST — Learning System Faz 1 Test Suite (Calibration)

Test edilen:
- ConfidenceCalibrator.calibrate()
- Brier score hesaplama
- ECE / MCE hesaplama
- Overconfidence / Underconfidence tespit
- Platt scaling fit ve adjust
- Regime-specific calibration
"""

import sys

import numpy as np


def test_brier_score_perfect() -> Any:
    """Brier score mükemmel tahmin için 0 vermeli."""
    from services.learning.calibration import ConfidenceCalibrator

    cal = ConfidenceCalibrator()
    predictions = [
        {"confidence": 1.0, "outcome": 1, "regime": "BULL"},
        {"confidence": 0.0, "outcome": 0, "regime": "BULL"},
        {"confidence": 1.0, "outcome": 1, "regime": "BULL"},
        {"confidence": 0.0, "outcome": 0, "regime": "BULL"},
        {"confidence": 1.0, "outcome": 1, "regime": "BULL"},
        {"confidence": 0.0, "outcome": 0, "regime": "BULL"},
        {"confidence": 1.0, "outcome": 1, "regime": "BULL"},
        {"confidence": 0.0, "outcome": 0, "regime": "BULL"},
        {"confidence": 1.0, "outcome": 1, "regime": "BULL"},
        {"confidence": 0.0, "outcome": 0, "regime": "BULL"},
        {"confidence": 1.0, "outcome": 1, "regime": "BULL"},
        {"confidence": 0.0, "outcome": 0, "regime": "BULL"},
        {"confidence": 1.0, "outcome": 1, "regime": "BULL"},
        {"confidence": 0.0, "outcome": 0, "regime": "BULL"},
        {"confidence": 1.0, "outcome": 1, "regime": "BULL"},
        {"confidence": 0.0, "outcome": 0, "regime": "BULL"},
        {"confidence": 1.0, "outcome": 1, "regime": "BULL"},
        {"confidence": 0.0, "outcome": 0, "regime": "BULL"},
        {"confidence": 1.0, "outcome": 1, "regime": "BULL"},
        {"confidence": 0.0, "outcome": 0, "regime": "BULL"},
        {"confidence": 1.0, "outcome": 1, "regime": "BULL"},
        {"confidence": 0.0, "outcome": 0, "regime": "BULL"},
        {"confidence": 1.0, "outcome": 1, "regime": "BULL"},
        {"confidence": 0.0, "outcome": 0, "regime": "BULL"},
        {"confidence": 1.0, "outcome": 1, "regime": "BULL"},
        {"confidence": 0.0, "outcome": 0, "regime": "BULL"},
        {"confidence": 1.0, "outcome": 1, "regime": "BULL"},
        {"confidence": 0.0, "outcome": 0, "regime": "BULL"},
        {"confidence": 1.0, "outcome": 1, "regime": "BULL"},
        {"confidence": 0.0, "outcome": 0, "regime": "BULL"},
    ]
    result = cal.calibrate(predictions)
    assert result.brier_score == 0.0, f"Brier score 0 değil: {result.brier_score}"
    assert result.overconfident is False
    logger.info(f"✅ Brier perfect: {result.brier_score}")


def test_brier_score_overconfident() -> Any:
    """Brier score overconfident model için yüksek vermeli."""
    from services.learning.calibration import ConfidenceCalibrator

    cal = ConfidenceCalibrator()
    # %90 confidence ama sadece %50 doğru
    np.random.seed(42)
    predictions = []
    for _i in range(100):
        predictions.append(
            {
                "confidence": 0.9,
                "outcome": 1 if np.random.random() < 0.5 else 0,
                "regime": "BULL",
            }
        )
    result = cal.calibrate(predictions)
    assert result.brier_score > 0.2, f"Brier score düşük: {result.brier_score}"
    logger.info(f"✅ Brier overconfident: {result.brier_score}")


def test_ece_overconfident() -> Any:
    """ECE overconfident model için yüksek vermeli."""
    from services.learning.calibration import ConfidenceCalibrator

    cal = ConfidenceCalibrator()
    # Hep %90 confidence ama sadece %50 doğru
    predictions = []
    for i in range(100):
        predictions.append(
            {
                "confidence": 0.9,
                "outcome": 1 if i % 2 == 0 else 0,
                "regime": "BULL",
            }
        )
    result = cal.calibrate(predictions)
    assert result.ece > 0.3, f"ECE düşük: {result.ece}"
    assert result.overconfident is True
    logger.info(f"✅ ECE overconfident: {result.ece:.4f}, overconfident: {result.overconfident}")


def test_ece_calibrated() -> Any:
    """ECE iyi kalibre edilmiş model için düşük vermeli."""
    from services.learning.calibration import ConfidenceCalibrator

    cal = ConfidenceCalibrator()
    np.random.seed(42)
    predictions = []
    for _i in range(200):
        conf = np.random.uniform(0.3, 0.9)
        # Confidence kadar doğru
        outcome = 1 if np.random.random() < conf else 0
        predictions.append({"confidence": conf, "outcome": outcome, "regime": "BULL"})
    result = cal.calibrate(predictions)
    assert result.ece < 0.15, f"ECE yüksek: {result.ece}"
    logger.info(f"✅ ECE calibrated: {result.ece}")


def test_bins_created() -> Any:
    """Bin'ler doğru oluşturuluyor mu?"""
    from services.learning.calibration import ConfidenceCalibrator

    cal = ConfidenceCalibrator()
    np.random.seed(42)
    predictions = []
    for _i in range(200):
        conf = np.random.uniform(0, 1)
        outcome = 1 if np.random.random() < conf else 0
        predictions.append({"confidence": conf, "outcome": outcome, "regime": "BULL"})
    result = cal.calibrate(predictions, n_bins=5)
    assert len(result.bins) > 0, "Bin oluşturulmadı"
    assert all(b.count > 0 for b in result.bins), "Boş bin var"
    logger.info(f"✅ Bins created: {len(result.bins)} bin")


def test_regime_calibration() -> Any:
    """Rejim bazlı calibration çalışıyor mu?"""
    from services.learning.calibration import ConfidenceCalibrator

    cal = ConfidenceCalibrator()
    np.random.seed(42)
    predictions = []
    # BULL rejimi: iyi kalibre
    for i in range(50):
        conf = np.random.uniform(0.5, 0.9)
        outcome = 1 if np.random.random() < conf else 0
        predictions.append({"confidence": conf, "outcome": outcome, "regime": "BULL"})
    # BEAR rejimi: overconfident
    for i in range(50):
        predictions.append({"confidence": 0.9, "outcome": 1 if i % 3 == 0 else 0, "regime": "BEAR"})

    result = cal.calibrate(predictions)
    assert "BULL" in result.regime_calibration
    assert "BEAR" in result.regime_calibration
    # BEAR overconfident olmalı
    assert result.regime_calibration["BEAR"]["overconfident"] is True
    logger.info(
        f"✅ Regime calibration: BULL={result.regime_calibration['BULL']['brier_score']}, "
        f"BEAR={result.regime_calibration['BEAR']['brier_score']}"
    )


def test_platt_scaling_fit() -> Any:
    """Platt scaling parametreleri fit ediliyor mu?"""
    from services.learning.calibration import ConfidenceCalibrator

    cal = ConfidenceCalibrator()
    np.random.seed(42)
    predictions = []
    for _i in range(100):
        conf = np.random.uniform(0.3, 0.9)
        outcome = 1 if np.random.random() < conf else 0
        predictions.append({"confidence": conf, "outcome": outcome})

    params = cal.fit_platt_scaling(predictions)
    assert params.fitted is True
    assert isinstance(params.a, float)
    assert isinstance(params.b, float)
    logger.info(f"✅ Platt scaling fitted: a={params.a}, b={params.b}")


def test_platt_scaling_adjust() -> Any:
    """Platt scaling confidence'ı ayarlıyor mu?"""
    from services.learning.calibration import ConfidenceCalibrator

    cal = ConfidenceCalibrator()
    np.random.seed(42)

    # Overconfident model eğit: %90 confidence ama sadece %33 doğru
    predictions = []
    for i in range(100):
        predictions.append({"confidence": 0.9, "outcome": 1 if i % 3 == 0 else 0})
    cal.fit_platt_scaling(predictions)

    # Platt scaling confidence'ı true rate'e çekmeli
    adjusted = cal.adjust_confidence(0.9)
    # Platt scaling 0.9'u ~0.33'e çekmeli (true rate)
    assert abs(adjusted - 0.9) > 0.01, f"Adjustment yapılmadı: {adjusted}"
    logger.info(f"✅ Platt adjust: 0.9 → {adjusted:.4f}")


def test_platt_scaling_insufficient_data() -> Any:
    """Yetersiz veri ile Platt scaling fit edilmemeli."""
    from services.learning.calibration import ConfidenceCalibrator

    cal = ConfidenceCalibrator()
    predictions = [{"confidence": 0.8, "outcome": 1}] * 10  # 10 < 30

    params = cal.fit_platt_scaling(predictions)
    assert params.fitted is False
    logger.info("✅ Platt scaling insufficient data → not fitted")


def test_confidence_adjustment_no_calibration() -> Any:
    """Calibration yoksa confidence değişmemeli."""
    from services.learning.calibration import ConfidenceCalibrator

    cal = ConfidenceCalibrator()
    adjusted = cal.adjust_confidence(0.8)
    assert adjusted == 0.8
    logger.info("✅ No calibration → no adjustment")


def test_confidence_level() -> Any:
    """Confidence level doğru belirleniyor mu?"""
    from services.learning.calibration import ConfidenceCalibrator

    cal = ConfidenceCalibrator()

    # Yeterli sample, düşük ECE → HIGH
    np.random.seed(42)
    predictions = []
    for _i in range(250):
        conf = np.random.uniform(0.4, 0.6)
        outcome = 1 if np.random.random() < conf else 0
        predictions.append({"confidence": conf, "outcome": outcome, "regime": "BULL"})
    result = cal.calibrate(predictions)
    assert result.confidence in ["HIGH", "MEDIUM"], f"Confidence level: {result.confidence}"
    logger.info(f"✅ Confidence level: {result.confidence}")


def test_calibration_report() -> Any:
    """Calibration raporu doğru mu?"""
    from services.learning.calibration import ConfidenceCalibrator

    cal = ConfidenceCalibrator()
    np.random.seed(42)
    predictions = []
    for _i in range(100):
        conf = np.random.uniform(0.3, 0.9)
        outcome = 1 if np.random.random() < conf else 0
        predictions.append({"confidence": conf, "outcome": outcome, "regime": "BULL"})
    cal.calibrate(predictions)

    report = cal.get_calibration_report()
    assert report["status"] == "OK"
    assert "metrics" in report
    assert "diagnosis" in report
    assert "brier_score" in report["metrics"]
    logger.info(f"✅ Calibration report: brier={report['metrics']['brier_score']}, ece={report['metrics']['ece']}")


def test_calibration_report_empty() -> Any:
    """Boş calibration raporu doğru mu?"""
    from services.learning.calibration import ConfidenceCalibrator

    cal = ConfidenceCalibrator()
    report = cal.get_calibration_report()
    assert report["status"] == "No calibration data"
    logger.info("✅ Empty calibration report")


def test_multiple_calibrations() -> Any:
    """Birden fazla calibration çalıştırılabilmeli."""
    from services.learning.calibration import ConfidenceCalibrator

    cal = ConfidenceCalibrator()
    np.random.seed(42)

    for _ in range(3):
        predictions = []
        for _i in range(50):
            conf = np.random.uniform(0.3, 0.9)
            outcome = 1 if np.random.random() < conf else 0
            predictions.append({"confidence": conf, "outcome": outcome, "regime": "BULL"})
        cal.calibrate(predictions)

    assert len(cal._calibration_history) == 3
    logger.info(f"✅ Multiple calibrations: {len(cal._calibration_history)}")


def run_all_tests() -> Any:
    """Tüm testleri çalıştır."""
    tests = [
        test_brier_score_perfect,
        test_brier_score_overconfident,
        test_ece_overconfident,
        test_ece_calibrated,
        test_bins_created,
        test_regime_calibration,
        test_platt_scaling_fit,
        test_platt_scaling_adjust,
        test_platt_scaling_insufficient_data,
        test_confidence_adjustment_no_calibration,
        test_confidence_level,
        test_calibration_report,
        test_calibration_report_empty,
        test_multiple_calibrations,
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
            logger.info(f"❌ {test.__name__}: {e}")

    logger.info(f"\n{'=' * 60}")
    logger.info("📊 FAZ 1 TEST SONUÇLARI (Calibration)")
    logger.info(f"{'=' * 60}")
    logger.info(f"✅ Geçen: {passed}")
    logger.info(f"❌ Başarısız: {failed}")
    logger.info(f"📈 Toplam: {passed + failed}")

    if errors:
        logger.info("\n🔍 Hatalar:")
        for name, err in errors:
            logger.info(f"  - {name}: {err}")

    return failed == 0


if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)
