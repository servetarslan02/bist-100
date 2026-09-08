"""services/ml/calibration.py Kapsamlı ve Çok Senaryolu Test Paketi.

GEMINI.md Kural 1-8 standartlarına göre ModelCalibration sınıfını,
Platt ve Isotonic yöntemlerini, rejim kalibrasyonunu, DuckDB WAL ve Polars entegrasyonunu,
eşzamanlılık (thread-safety) ve sınır durumlarını uçtan uca doğrular.
"""

from __future__ import annotations

import concurrent.futures
from pathlib import Path
import numpy as np
import polars as pl
import pytest

from services.ml.calibration import (
    CalibrationAlert,
    CalibrationResult,
    ModelCalibration,
    RegimeCalibrationResult,
)


def test_dataclasses_serialization_and_roundtrip() -> None:
    """Veri modellerinin to_dict, from_dict ve to_orjson_bytes serileştirme doğrulaması."""
    curve = [{"bin": 0.1, "prob": 0.1, "true": 0.12}]
    res = CalibrationResult(
        is_calibrated=True,
        brier_score=0.15,
        calibration_curve=curve,
        miscalibration=0.02,
        overconfident=False,
        recommendation="EXCELLENT",
        expected_calibration_error=0.03,
        maximum_calibration_error=0.05,
        log_loss=0.45,
        brier_skill_score=0.35,
        brier_baseline=0.25,
        ece_ci_lower=0.02,
        ece_ci_upper=0.04,
        brier_ci_lower=0.12,
        brier_ci_upper=0.18,
        platt_ece=0.025,
        isotonic_ece=0.028,
        best_calibrator="platt",
        nri=0.10,
    )

    d = res.to_dict()
    assert d["is_calibrated"] is True
    assert d["brier_score"] == 0.15
    assert d["best_calibrator"] == "platt"

    b = res.to_orjson_bytes()
    assert isinstance(b, bytes)
    assert b"EXCELLENT" in b

    restored = CalibrationResult.from_dict(d)
    assert restored.is_calibrated == res.is_calibrated
    assert restored.brier_score == res.brier_score
    assert restored.best_calibrator == res.best_calibrator
    assert "CalibrationResult" in repr(restored)

    # RegimeCalibrationResult testi
    reg_res = RegimeCalibrationResult(regime="BULL", result=res, n_samples=500)
    reg_d = reg_res.to_dict()
    assert reg_d["regime"] == "BULL"
    reg_restored = RegimeCalibrationResult.from_dict(reg_d)
    assert reg_restored.regime == "BULL"
    assert reg_restored.result.brier_score == 0.15
    assert "RegimeCalibrationResult" in repr(reg_restored)

    # CalibrationAlert testi
    alert = CalibrationAlert(
        timestamp="2026-09-08T12:00:00Z",
        alert_type="OVERCONFIDENCE",
        severity="HIGH",
        message="Model overconfident",
        metric="ece",
        value=0.18,
        threshold=0.15,
    )
    alert_d = alert.to_dict()
    alert_restored = CalibrationAlert.from_dict(alert_d)
    assert alert_restored.alert_type == "OVERCONFIDENCE"
    assert alert_restored.value == 0.18
    assert "CalibrationAlert" in repr(alert_restored)


def test_check_calibration_basic_and_overconfident() -> None:
    """Kalibrasyon hesaplama, ECE, MCE, Brier ve aşırı güven tespitleri."""
    mc = ModelCalibration(n_bins=10, overconfidence_threshold=0.10)

    # 1. İyi kalibre edilmiş veri
    rng = np.random.default_rng(42)
    y_prob_well = rng.uniform(0.1, 0.9, size=200)
    y_true_well = (rng.uniform(0.0, 1.0, size=200) < y_prob_well).astype(int)

    res_well = mc.check_calibration(y_true_well, y_prob_well)
    assert res_well.expected_calibration_error < 0.15
    assert res_well.brier_score >= 0.0
    assert len(res_well.calibration_curve) > 0

    # 2. Aşırı güvenli / bozuk kalibre edilmiş veri
    y_prob_bad = np.array([0.99] * 100 + [0.01] * 100)
    # Tümü ters gerçekleşsin
    y_true_bad = np.array([0] * 100 + [1] * 100)

    res_bad = mc.check_calibration(y_true_bad, y_prob_bad)
    assert res_bad.expected_calibration_error > 0.80
    assert res_bad.is_calibrated is False
    assert res_bad.overconfident is True
    assert res_bad.recommendation in ("POOR", "CRITICAL_MISCALIBRATION")


def test_validation_and_boundary_conditions() -> None:
    """Boş girdi, boyut uyuşmazlığı ve NaN/Inf koruma kontrolleri."""
    mc = ModelCalibration()

    # Boş dizi
    with pytest.raises(ValueError, match="Kalibrasyon dizileri boş olamaz"):
        mc.check_calibration(np.array([]), np.array([]))

    # Boyut uyuşmazlığı
    with pytest.raises(ValueError, match="Boyut uyuşmazlığı"):
        mc.check_calibration(np.array([1, 0]), np.array([0.5]))

    # NaN / Inf verisi
    with pytest.raises(ValueError, match="geçersiz NaN ya da Sonsuz"):
        mc.check_calibration(np.array([1, 0]), np.array([0.5, np.nan]))

    with pytest.raises(ValueError, match="geçersiz NaN ya da Sonsuz"):
        mc.check_calibration(np.array([np.inf, 0]), np.array([0.5, 0.4]))


def test_platt_and_isotonic_calibration() -> None:
    """Platt Scaling ve Isotonic Regresyon kalibratörlerinin eğitimi ve tahmini."""
    mc = ModelCalibration()

    rng = np.random.default_rng(123)
    y_prob = rng.uniform(0.2, 0.8, size=150)
    y_true = (rng.uniform(0.0, 1.0, size=150) < y_prob).astype(int)

    # Platt
    platt_model, platt_calibrated = mc.calibrate_platt(y_true, y_prob)
    assert platt_model is not None
    assert len(platt_calibrated) == len(y_prob)
    assert np.all((platt_calibrated >= 0.0) & (platt_calibrated <= 1.0))

    # Isotonic
    iso_model, iso_calibrated = mc.calibrate_isotonic(y_true, y_prob)
    assert iso_model is not None
    assert len(iso_calibrated) == len(y_prob)
    assert np.all((iso_calibrated >= 0.0) & (iso_calibrated <= 1.0))


def test_regime_calibration() -> None:
    """Farklı piyasa rejimlerinde (BULL, BEAR) bağımsız kalibrasyon."""
    mc = ModelCalibration()

    rng = np.random.default_rng(99)
    y_prob = rng.uniform(0.3, 0.7, size=100)
    y_true = rng.integers(0, 2, size=100)
    regimes = np.array(["BULL"] * 50 + ["BEAR"] * 50)

    reg_calibrators = mc.calibrate_regime_specific(y_true, y_prob, regimes, method="isotonic")
    assert "BULL" in reg_calibrators
    assert "BEAR" in reg_calibrators

    # Kalibratör uygulama
    cal_bull = mc.apply_calibration(np.array([0.6, 0.4]), regime="BULL")
    assert len(cal_bull) == 2
    assert np.all((cal_bull >= 0.0) & (cal_bull <= 1.0))


def test_duckdb_and_polars_integration(tmp_path: Path) -> None:
    """DuckDB denetim tablosuna yazma, Polars DataFrame olarak okuma ve Polars kalibrasyon kontrolü."""
    mc = ModelCalibration()

    y_prob = np.array([0.2, 0.4, 0.6, 0.8] * 10)
    y_true = np.array([0, 0, 1, 1] * 10)

    # Kalibrasyon çalıştır ve geçmiş oluştur
    mc.check_calibration(y_true, y_prob)

    db_file = str(tmp_path / "calibration_audit.duckdb")
    mc.export_calibration_audit_duckdb(db_path=db_file, table_name="test_cal_audit")

    # Polars ile oku
    df_audit = mc.read_calibration_audit_polars(db_path=db_file, table_name="test_cal_audit")
    assert isinstance(df_audit, pl.DataFrame)
    assert df_audit.height >= 1
    assert "brier_score" in df_audit.columns
    assert "ece" in df_audit.columns

    # check_calibration_polars testi
    df_test = pl.DataFrame({
        "actual": [1, 0, 1, 0, 1, 0, 1, 0, 1, 0],
        "prediction": [0.8, 0.2, 0.7, 0.3, 0.9, 0.1, 0.6, 0.4, 0.85, 0.15],
    })

    polars_res = mc.check_calibration_polars(df_test, true_column="actual", prob_column="prediction")
    assert isinstance(polars_res, CalibrationResult)
    assert polars_res.brier_score >= 0.0

    # Olmayan sütun hatası
    with pytest.raises(KeyError, match="Sütunlar tabloda bulunamadı"):
        mc.check_calibration_polars(df_test, true_column="non_existent", prob_column="prediction")


def test_thread_safety_concurrent_access() -> None:
    """Eşzamanlı çoklu iş parçacığı altında ModelCalibration thread-safety garantisi."""
    mc = ModelCalibration()

    def worker(seed: int) -> float:
        rng = np.random.default_rng(seed)
        yp = rng.uniform(0.1, 0.9, size=50)
        yt = (rng.uniform(0.0, 1.0, size=50) < yp).astype(int)
        res = mc.check_calibration(yt, yp)
        return res.brier_score

    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as executor:
        futures = [executor.submit(worker, s) for s in range(30)]
        results = [f.result() for f in futures]

    assert len(results) == 30
    assert all(r >= 0.0 for r in results)
