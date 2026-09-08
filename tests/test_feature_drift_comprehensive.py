"""ALPHA BIST — FeatureDriftDetector Kapsamlı Test Paketi.

Bu test paketi 8 denetim kuralına tam uyumlu olarak FeatureDriftDetector motorunu ve veri modellerini test eder:
1. Veri modelleri ve orjson serileştirme/deserileştirme (DriftReport, DriftSummary).
2. SHAP geçmişi kaydı ve yön trendi analizi (increasing, decreasing, stable, volatile).
3. Nüfus Kararlılık İndeksi (PSI) hesaplaması, quantile dilimleme ve sabit değer guard'ları.
4. Polars DataFrame üzerinde vektörize drift analizi (check_drift_polars), ciddiyet seviyesi ve iyileştirme önerileri.
5. Parametre sınır kontrolleri ve geçersiz parametrelerde fail-closed ValueError doğrulaması.
6. Dağılım drift analizi ve DriftSummary raporu oluşturulması.
7. DuckDB SSD korumalı WAL denetim izi kaydı ve Polars DataFrame ile geçmiş okuma.
8. Eşzamanlı iş parçacığı güvenliği (thread-safety).
"""

from __future__ import annotations

import concurrent.futures
from typing import TYPE_CHECKING

import numpy as np
import orjson
import polars as pl
import pytest

from services.ml.feature_drift import (
    DriftReport,
    DriftSeverity,
    DriftSummary,
    DriftTrend,
    FeatureDriftDetector,
    check_drift_polars,
    read_drift_history_polars,
    save_drift_summary_to_duckdb,
)

if TYPE_CHECKING:
    from pathlib import Path


def test_dataclasses_serialization() -> None:
    """Veri modellerinin to_dict, from_dict ve orjson serileştirmesini test eder."""
    report_orig = DriftReport(
        feature_name="rsi_14",
        psi=0.28,
        drift_detected=True,
        importance_trend=DriftTrend.INCREASING.value,
        current_importance=0.15,
        historical_importance=0.08,
        alert=True,
        severity=DriftSeverity.HIGH.value,
        remediation="RSI özniteliğinde belirgin kayma var.",
    )
    r_bytes = report_orig.to_orjson_bytes()
    r_restored = DriftReport.from_dict(orjson.loads(r_bytes))
    assert r_restored.feature_name == "rsi_14"
    assert r_restored.psi == 0.28
    assert r_restored.drift_detected is True
    assert r_restored.severity == DriftSeverity.HIGH.value
    assert "DriftReport" in repr(report_orig)

    summary_orig = DriftSummary(
        total_features=20,
        drifted_features=3,
        alert_features=2,
        critical_features=1,
        overall_drift_score=0.15,
        recommendations=["Modeli yeniden eğitin"],
    )
    s_bytes = summary_orig.to_orjson_bytes()
    s_restored = DriftSummary.from_dict(orjson.loads(s_bytes))
    assert s_restored.total_features == 20
    assert s_restored.critical_features == 1
    assert s_restored.recommendations == ["Modeli yeniden eğitin"]
    assert "DriftSummary" in repr(summary_orig)


def test_record_shap_and_trend_analysis() -> None:
    """SHAP değerleri kaydı ve check_drift ile önem trendi analizini test eder."""
    detector = FeatureDriftDetector(psi_threshold=0.20)

    # Artan trend: her adımda volatility önemi artıyor
    for i in range(10):
        detector.record_shap({"volatility_30": 0.05 + i * 0.02, "momentum_10": 0.10})

    reports = detector.check_drift()
    assert len(reports) == 2

    report_map = {r.feature_name: r for r in reports}
    assert report_map["volatility_30"].importance_trend in [
        DriftTrend.INCREASING.value,
        DriftTrend.VOLATILE.value,
    ]
    assert report_map["momentum_10"].importance_trend == DriftTrend.STABLE.value


def test_calculate_psi_quantiles() -> None:
    """PSI hesaplamasının benzer dağılımlarda sıfıra yakın, farklı dağılımlarda yüksek olduğunu doğrular."""
    detector = FeatureDriftDetector(n_bins=10)

    np.random.seed(42)
    # Aynı dağılım: N(0, 1) vs N(0, 1)
    ref_data = np.random.normal(0, 1, 500)
    cur_same = np.random.normal(0, 1, 500)

    psi_low = detector._calculate_psi(ref_data, cur_same)
    assert psi_low < 0.10  # Stabil olmalı

    # Belirgin kaymış dağılım: N(0, 1) vs N(2, 1)
    cur_shifted = np.random.normal(2, 1, 500)
    psi_high = detector._calculate_psi(ref_data, cur_shifted)
    assert psi_high > 0.25  # Belirgin kayma olmalı

    # Sabit tek değerli dizi (Guard)
    flat_arr = np.full(100, 5.0)
    assert detector._calculate_psi(flat_arr, flat_arr) == 0.0


def test_check_drift_polars() -> None:
    """Polars DataFrame üzerinde vektörize drift tespitini ve ciddiyet seviyesini test eder."""
    np.random.seed(99)
    n = 300

    df_ref = pl.DataFrame(
        {
            "f_stable": np.random.normal(0, 1, n),
            "f_drifted": np.random.normal(0, 1, n),
        }
    )

    df_cur = pl.DataFrame(
        {
            "f_stable": np.random.normal(0, 1, n),
            "f_drifted": np.random.normal(3, 1, n),  # Güçlü kayma
        }
    )

    reports = check_drift_polars(reference_df=df_ref, current_df=df_cur, psi_threshold=0.20)
    assert len(reports) == 2

    report_map = {r.feature_name: r for r in reports}
    assert report_map["f_stable"].drift_detected is False
    assert report_map["f_drifted"].drift_detected is True
    assert report_map["f_drifted"].severity in [DriftSeverity.HIGH.value, DriftSeverity.CRITICAL.value]
    assert len(report_map["f_drifted"].remediation) > 0


def test_feature_drift_detector_initialization_validation() -> None:
    """Geçersiz parametrelerde fail-closed ValueError üretildiğini test eder."""
    with pytest.raises(ValueError, match="Gecersiz parametreler"):
        FeatureDriftDetector(psi_threshold=-0.1)

    with pytest.raises(ValueError, match="Gecersiz parametreler"):
        FeatureDriftDetector(n_bins=1)

    det = FeatureDriftDetector()
    assert "FeatureDriftDetector" in repr(det)


def test_detect_distribution_drift_and_summary() -> None:
    """Dağılım kayması ve DriftSummary özetinin oluşturulmasını doğrular."""
    detector = FeatureDriftDetector(psi_threshold=0.20)
    np.random.seed(123)

    ref_dist = {"f1": np.random.normal(0, 1, 200), "f2": np.random.normal(0, 1, 200)}
    cur_dist = {"f1": np.random.normal(0, 1, 200), "f2": np.random.normal(2.5, 1, 200)}

    # SHAP değerleri
    detector.record_shap({"f1": 0.10, "f2": 0.10})
    detector.record_shap({"f1": 0.10, "f2": 0.35})

    # Dağılımlar
    detector.record_distribution(ref_dist)
    detector.record_distribution(cur_dist)

    reports = detector.check_drift()
    assert len(reports) == 2
    f2_rep = next(r for r in reports if r.feature_name == "f2")
    assert f2_rep.drift_detected is True

    summary = detector.get_summary()
    assert isinstance(summary, DriftSummary)
    assert summary.total_features == 2
    assert summary.drifted_features >= 1
    assert len(summary.recommendations) > 0


def test_duckdb_wal_save_and_polars_read(tmp_path: Path) -> None:
    """Drift özetinin DuckDB WAL ile kaydedilip Polars ile hatasız okunduğunu test eder."""
    db_file = str(tmp_path / "drift_audit.duckdb")

    summary = DriftSummary(
        total_features=15,
        drifted_features=2,
        alert_features=1,
        critical_features=1,
        overall_drift_score=0.133,
        recommendations=["f2 için yeniden eğitim planlayın"],
    )

    save_drift_summary_to_duckdb(summary, db_path=db_file)

    df_hist = read_drift_history_polars(db_path=db_file, limit=10)
    assert isinstance(df_hist, pl.DataFrame)
    assert df_hist.height == 1
    assert df_hist["total_features"][0] == 15
    assert df_hist["critical_features"][0] == 1


def test_thread_safety_drift() -> None:
    """Çoklu thread ile eşzamanlı SHAP ve dağılım kaydetme güvenliğini doğrular."""
    detector = FeatureDriftDetector()

    def worker(idx: int) -> None:
        for _ in range(20):
            detector.record_shap({"feat_a": 0.05 + idx * 0.01})
            detector.record_distribution({"feat_a": np.ones(50) * idx})

    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as executor:
        futs = [executor.submit(worker, i) for i in range(12)]
        for f in concurrent.futures.as_completed(futs):
            f.result()

    assert len(detector._shap_history) > 0
    assert len(detector._feature_distributions) > 0
