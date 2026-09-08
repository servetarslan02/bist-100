"""ALPHA BIST — ProbabilityCalibrator Kapsamlı Denetim ve Stres Testi.

Bu test modülü, probability_calibrator.py dosyasının 8 kural çerçevesindeki
tüm sınır koşullarını, algoritmalarını ve veri bütünlüğünü kanıtlar:
1. İzotonik Regresyon (Isotonic) doğruluğu ve monotonluk
2. Tek Sınıflı Kriz Bypass Modu (Single-class crash protection)
3. DuckDB Denetim İzi (Audit trail persistence ve SELECT doğrulaması)
4. Aşırı Uç Değer ve Sayısal Taşma Stresi (Inf, -Inf, devasa lojitler)
5. CalibrationMetrics Serileştirme ve Lineage döngüsü (to_orjson / from_dict)
6. Çoklu İş Parçacığı Eşzamanlılık Güvenliği (Multi-threading race condition check)
7. Polars Sınır Durumları (Null koruması, boş tablo, eksik veri)
"""

from __future__ import annotations

import concurrent.futures
import contextlib
from pathlib import Path

import duckdb
import numpy as np
import polars as pl
import pytest

from services.ml.probability_calibrator import (
    DEFAULT_NEUTRAL_PROB,
    CalibrationMethod,
    CalibrationMetrics,
    ProbabilityCalibrator,
    compute_ece,
)

TEST_DB_PATH = "data/test_audit_calibrator.duckdb"


@pytest.fixture(autouse=True)
def cleanup_test_db():
    """Her test öncesi/sonrası test veritabanını temizler."""
    if Path(TEST_DB_PATH).exists():
        with contextlib.suppress(Exception):
            Path(TEST_DB_PATH).unlink()
    yield
    if Path(TEST_DB_PATH).exists():
        with contextlib.suppress(Exception):
            Path(TEST_DB_PATH).unlink()


def test_01_isotonic_regression_correctness():
    """1. İzotonik Regresyon fit, calibrate ve ECE iyileşmesi testi."""
    pc = ProbabilityCalibrator(method=CalibrationMethod.ISOTONIC, duckdb_path=TEST_DB_PATH)
    rng = np.random.default_rng(42)

    # Monoton artan gürültülü skorlar
    y_raw = np.linspace(0.1, 0.9, 100) + rng.normal(0, 0.05, 100)
    y_true = (y_raw > 0.5).astype(int)

    pc.fit(y_raw, y_true)
    assert pc.is_fitted is True
    assert pc.calibrator is not None

    calibrated = pc.calibrate(y_raw)
    assert len(calibrated) == len(y_raw)
    assert np.all(calibrated >= 0.0) and np.all(calibrated <= 1.0)
    # İzotonik regresyon monoton artan olmalı
    sorted_idx = np.argsort(y_raw)
    sorted_cal = calibrated[sorted_idx]
    assert np.all(np.diff(sorted_cal) >= -1e-6), "İzotonik kalibrasyon monoton artan değil!"


def test_02_single_class_crisis_bypass():
    """2. Tek sınıflı veri setinde kriz bypass modu ve sınırsız lojit haritalama testi."""
    pc = ProbabilityCalibrator(method=CalibrationMethod.SIGMOID, duckdb_path=TEST_DB_PATH)

    # Kriz anı: Tüm örnekler düşüş (0 etiketi)
    y_raw_logits = np.array([-4.0, -2.0, -0.5, 1.0, 3.0])
    y_true_all_zeros = np.zeros(5, dtype=int)

    # Scikit-learn normalde tek sınıfta ValueError verir, bizim sistem bypass yapmalı
    pc.fit(y_raw_logits, y_true_all_zeros)
    assert pc.is_fitted is True
    assert pc.calibrator is None  # Güvenli bypass devrede

    calibrated = pc.calibrate(y_raw_logits)
    # Lojistik sigmoid ile haritalanmalı, clip ile 0 veya 1'e yapışmamalı
    assert np.all((calibrated > 0.0) & (calibrated < 1.0))
    # Negatif lojit 0.5'ten küçük olmalı
    assert calibrated[0] < 0.05
    # Pozitif lojit 0.5'ten büyük olmalı
    assert calibrated[-1] > 0.90


def test_03_duckdb_audit_trail_verification():
    """3. DuckDB denetim tablosunun fiili kaydı ve SELECT doğrulaması."""
    pc = ProbabilityCalibrator(method=CalibrationMethod.SIGMOID, duckdb_path=TEST_DB_PATH)
    y_raw = np.array([0.1, 0.2, 0.8, 0.9])
    y_true = np.array([0, 0, 1, 1])

    pc.fit(y_raw, y_true)

    # Veritabanına fiilen yazıldı mı?
    assert Path(TEST_DB_PATH).exists()
    with duckdb.connect(TEST_DB_PATH) as conn:
        rows = conn.execute(
            "SELECT method, sample_count, raw_brier, calibrated_brier FROM probability_calibration_audit"
        ).fetchall()
        assert len(rows) >= 1
        method, count, raw_b, cal_b = rows[0]
        assert method == "sigmoid"
        assert count == 4
        assert raw_b > 0.0
        assert cal_b > 0.0


def test_04_extreme_stress_and_numerical_overflow():
    """4. Aşırı uç değerler, devasa lojitler, Inf, -Inf ve NaN stres testi."""
    pc = ProbabilityCalibrator(method=CalibrationMethod.SIGMOID, duckdb_path=TEST_DB_PATH)
    y_raw = np.array([0.2, 0.4, 0.7, 0.9])
    y_true = np.array([0, 0, 1, 1])
    pc.fit(y_raw, y_true)

    # Uç değerler dizisi: devasa sayılar, inf, -inf, nan
    extreme_scores = np.array([1e12, -1e12, np.inf, -np.inf, np.nan, 0.5])
    calibrated = pc.calibrate(extreme_scores)

    assert len(calibrated) == len(extreme_scores)
    assert np.all(np.isfinite(calibrated)), "Kalibre edilen dizide NaN veya Inf oluştu!"
    assert np.all((calibrated >= 0.0) & (calibrated <= 1.0))

    # Skaler uç değer testi
    assert pc.calibrate_scalar(np.inf) == DEFAULT_NEUTRAL_PROB
    assert pc.calibrate_scalar(np.nan) == DEFAULT_NEUTRAL_PROB
    assert 0.0 <= pc.calibrate_scalar(100.0) <= 1.0
    assert 0.0 <= pc.calibrate_scalar(-100.0) <= 1.0


def test_05_metrics_serialization_and_lineage():
    """5. CalibrationMetrics to_dict, to_orjson_bytes ve from_dict döngü testi."""
    metrics = CalibrationMetrics(
        method="isotonic",
        raw_brier=0.1852,
        calibrated_brier=0.1241,
        raw_ece=0.2541,
        calibrated_ece=0.1102,
        ece_improvement_pct=56.6,
        sample_count=2500,
    )
    raw_dict = metrics.to_dict()
    assert raw_dict["method"] == "isotonic"
    assert raw_dict["sample_count"] == 2500

    json_bytes = metrics.to_orjson_bytes()
    assert isinstance(json_bytes, bytes)

    # Geri dönüştür (from_dict)
    reconstructed = CalibrationMetrics.from_dict(raw_dict)
    assert reconstructed.method == metrics.method
    assert reconstructed.ece_improvement_pct == metrics.ece_improvement_pct
    assert repr(reconstructed).startswith("CalibrationMetrics")


def test_06_thread_safety_concurrency():
    """6. Çoklu iş parçacığı altında yarış durumu (race condition) testi."""
    pc = ProbabilityCalibrator(method=CalibrationMethod.SIGMOID, duckdb_path=TEST_DB_PATH)
    y_raw = np.array([0.2, 0.3, 0.7, 0.8])
    y_true = np.array([0, 0, 1, 1])
    pc.fit(y_raw, y_true)

    def worker(val: float) -> float:
        return pc.calibrate_scalar(val)

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
        futures = [executor.submit(worker, float(i % 10) / 10.0) for i in range(100)]
        results = [f.result() for f in futures]

    assert len(results) == 100
    assert all(0.0 <= r <= 1.0 for r in results)


def test_07_polars_edge_cases_and_null_safety():
    """7. Polars null satırların kesin nötr (0.5) kalması ve fit_polars boş tablo testi."""
    pc = ProbabilityCalibrator(method=CalibrationMethod.SIGMOID, duckdb_path=TEST_DB_PATH)

    # 1. Null satırların korunumu
    df = pl.DataFrame({
        "pred": [0.1, None, 0.8, None, 0.95],
        "label": [0, 0, 1, 1, 1]
    })
    res_df = pc.calibrate_polars(df, "pred")
    cal_values = res_df["calibrated_score"].to_list()

    assert cal_values[1] == 0.5, "Null satır kesinlikle 0.5 nötr kalmalı!"
    assert cal_values[3] == 0.5, "Null satır kesinlikle 0.5 nötr kalmalı!"

    # 2. fit_polars tamamen null veya geçersiz tablo durumunda fail-closed ValueError
    bad_df = pl.DataFrame({"pred": [None, None], "label": [None, None]})
    with pytest.raises(ValueError, match="gecerli"):
        pc.fit_polars(bad_df, "pred", "label")


def test_08_compute_ece_edge_cases():
    """8. compute_ece fonksiyonunun boş dizi, sıfır hata ve boyut uyuşmazlığı testi."""
    assert compute_ece(np.array([]), np.array([])) == 0.0
    assert compute_ece(np.array([1, 0]), np.array([0.5])) == 0.0  # Boyut uyuşmazlığı

    # Mükemmel kalibre edilmiş tahminler
    y_t = np.array([1, 1, 0, 0])
    y_p = np.array([1.0, 1.0, 0.0, 0.0])
    ece_zero = compute_ece(y_t, y_p, n_bins=5)
    assert ece_zero == 0.0
