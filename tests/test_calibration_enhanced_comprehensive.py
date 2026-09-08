"""services/ml/calibration_enhanced.py Kapsamlı ve Çok Senaryolu Test Paketi.

GEMINI.md Kural 1-8 standartlarına göre CalibrationEnhanced motorunu,
TimeSeriesSplit OOF tahminlerini, kalibrasyon drift takibini, yeniden eğitim
planlayıcısını, DuckDB ve Polars entegrasyonunu, eşzamanlılık ve sınır durumlarını doğrular.
"""

from __future__ import annotations

import concurrent.futures
from pathlib import Path
import numpy as np
import polars as pl
import pytest
from sklearn.linear_model import LogisticRegression

from services.ml.calibration_enhanced import (
    CalibrationDriftReport,
    CalibrationEnhanced,
    OutOfFoldResult,
    RetrainSchedule,
    calibration_enhanced,
)


def test_dataclasses_roundtrip() -> None:
    """Dataclass serileştirme ve yeniden inşa döngüsü (to_dict, from_dict, to_orjson_bytes)."""
    # 1. OutOfFoldResult
    preds = np.array([0.2, 0.5, 0.8])
    oof = OutOfFoldResult(
        predictions=preds,
        fold_indices=[],
        mean_ic=0.12,
        mean_brier=0.18,
        n_folds=3,
    )
    oof_d = oof.to_dict()
    assert oof_d["mean_ic"] == 0.12
    assert oof_d["n_folds"] == 3
    oof_b = oof.to_orjson_bytes()
    assert isinstance(oof_b, bytes)
    oof_restored = OutOfFoldResult.from_dict(oof_d)
    assert oof_restored.mean_ic == oof.mean_ic
    assert "OutOfFoldResult" in repr(oof_restored)

    # 2. CalibrationDriftReport
    drift_rep = CalibrationDriftReport(
        current_brier=0.22,
        baseline_brier=0.15,
        brier_change=0.07,
        current_ece=0.08,
        baseline_ece=0.03,
        ece_change=0.05,
        drift_detected=True,
        severity="WARNING",
        recommendation="Kalibrasyon kayması tespit edildi",
    )
    drift_d = drift_rep.to_dict()
    assert drift_d["drift_detected"] is True
    drift_b = drift_rep.to_orjson_bytes()
    assert isinstance(drift_b, bytes)
    drift_restored = CalibrationDriftReport.from_dict(drift_d)
    assert drift_restored.drift_detected is True
    assert drift_restored.severity == "WARNING"
    assert "CalibrationDriftReport" in repr(drift_restored)

    # 3. RetrainSchedule
    sched = RetrainSchedule(
        last_retrain="2026-09-08T10:00:00Z",
        hours_since_retrain=25.5,
        should_retrain=True,
        reason="Zaman aşımı",
        next_retrain="2026-09-08T12:00:00Z",
    )
    sched_d = sched.to_dict()
    sched_b = sched.to_orjson_bytes()
    assert isinstance(sched_b, bytes)
    sched_restored = RetrainSchedule.from_dict(sched_d)
    assert sched_restored.should_retrain is True
    assert "RetrainSchedule" in repr(sched_restored)


def test_generate_out_of_fold() -> None:
    """TimeSeriesSplit ile sıfır veri sızıntılı OOF tahmin üretimi."""
    ce = CalibrationEnhanced()

    rng = np.random.default_rng(42)
    X = rng.normal(size=(100, 4))
    y = (X[:, 0] + X[:, 1] > 0.0).astype(int)

    model = LogisticRegression()
    oof_res = ce.generate_out_of_fold(model=model, X=X, y=y, cv=4)

    assert isinstance(oof_res, OutOfFoldResult)
    assert len(oof_res.predictions) == 100
    assert oof_res.n_folds == 4
    assert np.all((oof_res.predictions >= 0.0) & (oof_res.predictions <= 1.0))
    assert oof_res.mean_brier >= 0.0


def test_generate_out_of_fold_polars() -> None:
    """Polars DataFrame girdisi ile OOF tahmini."""
    ce = CalibrationEnhanced()

    df = pl.DataFrame({
        "f1": np.linspace(0, 10, 50),
        "f2": np.sin(np.linspace(0, 10, 50)),
        "target": [0, 1] * 25,
    })

    model = LogisticRegression()
    res = ce.generate_out_of_fold_polars(
        df=df,
        feature_columns=["f1", "f2"],
        target_column="target",
        model=model,
        cv=3,
    )

    assert isinstance(res, OutOfFoldResult)
    assert len(res.predictions) == 50
    assert res.n_folds == 3


def test_validation_and_boundary_conditions() -> None:
    """Boş veri, boyut uyuşmazlığı ve NaN/Inf kontrolleri."""
    ce = CalibrationEnhanced()

    # Boş veri
    with pytest.raises(ValueError, match="boş olamaz"):
        ce.generate_out_of_fold(LogisticRegression(), np.array([]), np.array([]))

    # Boyut uyuşmazlığı
    with pytest.raises(ValueError, match="Boyut uyuşmazlığı"):
        ce.generate_out_of_fold(LogisticRegression(), np.ones((10, 2)), np.ones(8))

    # NaN / Inf girdisi
    with pytest.raises(ValueError, match="geçersiz NaN ya da Sonsuz"):
        bad_X = np.ones((10, 2))
        bad_X[0, 0] = np.nan
        ce.generate_out_of_fold(LogisticRegression(), bad_X, np.ones(10))


def test_record_metrics_and_drift_detection() -> None:
    """Metrik kaydetme ve kalibrasyon kayması (drift) uyarı mekanizması."""
    ce = CalibrationEnhanced(drift_threshold=0.05)

    # Başlangıçta yetersiz veri
    rep_empty = ce.check_calibration_drift()
    assert rep_empty.drift_detected is False

    # 1. Normal metrikler
    ce.record_calibration_metrics(brier_score=0.12, ece=0.03)
    ce.record_calibration_metrics(brier_score=0.13, ece=0.035)

    rep_ok = ce.check_calibration_drift()
    assert rep_ok.drift_detected is False
    assert rep_ok.severity == "OK"

    # 2. Sapma (drift) oluşumu
    ce.record_calibration_metrics(brier_score=0.25, ece=0.15)
    rep_drift = ce.check_calibration_drift()
    assert rep_drift.drift_detected is True
    assert rep_drift.severity in ("WARNING", "ALERT")


def test_should_retrain_schedule() -> None:
    """Zaman ve sapma odaklı yeniden eğitim karar mekanizması."""
    ce = CalibrationEnhanced(retrain_interval_hours=12.0)

    # Henüz hiç eğitilmediğinde derhal True dönmeli
    sched = ce.should_retrain_calibration()
    assert sched.should_retrain is True
    assert sched.hours_since_retrain == float("inf")

    # Drift eklendiğinde
    ce.record_calibration_metrics(brier_score=0.10, ece=0.02)
    ce.record_calibration_metrics(brier_score=0.28, ece=0.18)
    sched_drift = ce.should_retrain_calibration()
    assert sched_drift.should_retrain is True


def test_compare_platt_isotonic() -> None:
    """Platt ve Isotonic yöntemlerinin karşılaştırmalı testi."""
    ce = CalibrationEnhanced()

    rng = np.random.default_rng(99)
    confidences = rng.uniform(0.1, 0.9, size=50)
    outcomes = (rng.uniform(0, 1, size=50) < confidences).astype(int)

    preds = [{"confidence": float(c), "outcome": int(o)} for c, o in zip(confidences, outcomes, strict=True)]

    cmp_res = ce.compare_calibration_methods(preds)
    assert "platt_brier" in cmp_res
    assert "isotonic_brier" in cmp_res
    assert "better_method" in cmp_res
    assert cmp_res["better_method"] in ("platt", "isotonic", "equal")


def test_duckdb_and_polars_drift_export(tmp_path: Path) -> None:
    """DuckDB tablosuna aktarım ve Polars DataFrame okuması."""
    ce = CalibrationEnhanced()

    ce.record_calibration_metrics(brier_score=0.11, ece=0.025)
    ce.record_calibration_metrics(brier_score=0.14, ece=0.040)

    db_path = str(tmp_path / "test_drift.duckdb")
    ce.export_drift_history_duckdb(db_path=db_path, table_name="drift_audit")

    df_drift = ce.read_drift_history_polars(db_path=db_path, table_name="drift_audit")
    assert isinstance(df_drift, pl.DataFrame)
    assert df_drift.height >= 2
    assert "brier_score" in df_drift.columns
    assert "ece" in df_drift.columns


def test_thread_safety_concurrent_records() -> None:
    """Çoklu iş parçacıklarında metrik kaydetme yarış durumu koruması."""
    ce = CalibrationEnhanced()

    def worker(i: int) -> None:
        ce.record_calibration_metrics(brier_score=0.10 + i * 0.001, ece=0.02 + i * 0.001)

    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as executor:
        futures = [executor.submit(worker, i) for i in range(25)]
        for f in futures:
            f.result()

    b_hist = ce.get_brier_history(limit=100)
    assert len(b_hist) == 25


def test_singleton_instance() -> None:
    """Varsayılan singleton örneğinin doğruluğu."""
    assert isinstance(calibration_enhanced, CalibrationEnhanced)
