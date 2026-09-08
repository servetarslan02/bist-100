"""ALPHA BIST — Training Dataset Quality Validator Kapsamlı Test Paketi

services/ml/training_validator.py için kurumsal denetim testleri:
1. Dataclass serileştirme (to_dict, from_dict, to_orjson_bytes, to_polars)
2. TrainingDatasetValidator veri doğrulama ve metrik kontrolleri
3. CrossSectionalNormalizer PIT-safe z-score ve rank dönüşümleri
4. DuckDB WAL denetim kaydı ve Polars okuma
5. Live inference parity (prepare_features_for_inference)
6. Thread-safety eşzamanlı çalıştırma testi
"""

from __future__ import annotations

import concurrent.futures
from pathlib import Path
from typing import Any

import numpy as np
import polars as pl
import pytest

from services.ml.training_validator import (
    CrossSectionalNormalizer,
    DataQualityReport,
    SampleMeta,
    TrainingDatasetValidator,
    ValidationMetrics,
    configure_duckdb_wal,
    cross_sectional_normalizer,
    prepare_features_for_inference,
    training_validator,
)


def test_sample_meta_serialization() -> None:
    """SampleMeta dataclass serialization test."""
    meta = SampleMeta(
        sample_key="THYAO::2026-02-23",
        ticker="THYAO",
        feature_date="2026-02-23",
        target_date="2026-02-28",
        forward_return=0.045,
    )
    d = meta.to_dict()
    assert d["ticker"] == "THYAO"
    assert d["forward_return"] == 0.045

    reconstructed = SampleMeta.from_dict(d)
    assert reconstructed.sample_key == meta.sample_key
    assert reconstructed.forward_return == meta.forward_return

    b = meta.to_orjson_bytes()
    assert isinstance(b, bytes)
    assert b"THYAO" in b


def test_data_quality_report_and_polars() -> None:
    """DataQualityReport serileştirme ve Polars dönüşüm testi."""
    rep = DataQualityReport(
        total_samples=100,
        valid_samples=95,
        dropped_samples=5,
        drop_reasons={"missing_return": 5},
        quality_score=0.92,
        feature_stats={
            "f1": {"mean": 1.2, "std": 0.4, "median": 1.1, "min": 0.1, "max": 2.5, "nan_count": 0, "inf_count": 0, "outlier_count": 1}
        },
    )
    d = rep.to_dict()
    assert d["total_samples"] == 100
    assert d["quality_score"] == 0.92

    reconstructed = DataQualityReport.from_dict(d)
    assert reconstructed.dropped_samples == 5
    assert reconstructed.quality_score == 0.92

    df_polars = rep.to_polars()
    assert isinstance(df_polars, pl.DataFrame)
    assert df_polars.height == 1
    assert "quality_score" in df_polars.columns


def test_validation_metrics_and_computation() -> None:
    """ValidationMetrics hesaplama ve Polars dönüşüm testi."""
    validator = TrainingDatasetValidator()

    rng = np.random.default_rng(42)
    y_true = rng.normal(0.01, 0.05, 100)
    y_pred = y_true + rng.normal(0.0, 0.02, 100)

    metrics = validator.compute_validation_metrics(y_true, y_pred)
    assert metrics.mae > 0.0
    assert metrics.rmse > 0.0
    assert metrics.r_squared > 0.0
    assert metrics.directional_accuracy >= 0.0
    assert metrics.ndcg >= 0.0

    d = metrics.to_dict()
    assert "mae" in d
    assert "ic" in d

    df_p = metrics.to_polars()
    assert isinstance(df_p, pl.DataFrame)
    assert df_p.height == 1


def test_validate_dataset_flow(tmp_path: Path) -> None:
    """validate_dataset işlevselliği, leakage denetimi ve DuckDB kaydı."""
    db_file = tmp_path / "quality_audit.duckdb"
    validator = TrainingDatasetValidator(duckdb_path=str(db_file))

    # Deterministik sentetik veri
    features_map: dict[str, dict[str, Any]] = {
        "THYAO::2026-02-20": {"f1": 1.0, "f2": 2.5},
        "GARAN::2026-02-20": {"f1": 1.2, "f2": 2.1},
        "THYAO::2026-02-23": {"f1": 1.1, "f2": 2.4},
        "GARAN::2026-02-23": {"f1": 1.3, "f2": 2.2},
    }
    returns = {
        "THYAO::2026-02-20": 0.02,
        "GARAN::2026-02-20": -0.01,
        "THYAO::2026-02-23": 0.03,
        "GARAN::2026-02-23": -0.02,
    }
    date_groups = {
        "THYAO::2026-02-20": "2026-02-20",
        "GARAN::2026-02-20": "2026-02-20",
        "THYAO::2026-02-23": "2026-02-23",
        "GARAN::2026-02-23": "2026-02-23",
    }
    feature_names = ["f1", "f2"]

    # 1. Normal doğrulama
    report = validator.validate_dataset(features_map, returns, date_groups, feature_names)
    assert report.total_samples == 4
    assert report.valid_samples == 4
    assert report.dropped_samples == 0
    assert report.quality_score > 0.8
    assert not report.train_test_overlap

    # 2. Leakage tespiti
    report_leak = validator.validate_dataset(
        features_map, returns, date_groups, feature_names, test_dates={"2026-02-23"}
    )
    assert report_leak.train_test_overlap is True
    assert "2026-02-23" in report_leak.overlap_details
    assert report_leak.quality_score < 0.5

    # 3. DuckDB kayıt ve Polars ile okuma
    validator.record_quality_audit(report, dataset_name="swing_bist100_v1")
    df_audit = validator.get_audit_as_polars()
    assert isinstance(df_audit, pl.DataFrame)
    assert df_audit.height >= 1
    assert "dataset_name" in df_audit.columns


def test_cross_sectional_normalizer_and_clean_features() -> None:
    """PIT-safe cross-sectional z-score ve rank dönüşümleri testi."""
    cs = CrossSectionalNormalizer()

    features_map = {
        "THYAO::2026-02-20": {"momentum": 10.0, "volatility": 0.2},
        "GARAN::2026-02-20": {"momentum": 20.0, "volatility": 0.4},
        "SISE::2026-02-20": {"momentum": 30.0, "volatility": 0.6},
    }
    date_groups = {
        "THYAO::2026-02-20": "2026-02-20",
        "GARAN::2026-02-20": "2026-02-20",
        "SISE::2026-02-20": "2026-02-20",
    }
    fnames = ["momentum", "volatility"]

    # Z-Score
    z_norm = cs.normalize_zscore_by_date(features_map, date_groups, fnames)
    assert "momentum_cs_zscore" in z_norm["THYAO::2026-02-20"]
    assert "volatility_cs_zscore" in z_norm["SISE::2026-02-20"]

    # Rank
    r_norm = cs.normalize_rank_by_date(features_map, date_groups, fnames)
    assert "momentum_cs_rank" in r_norm["THYAO::2026-02-20"]
    assert r_norm["THYAO::2026-02-20"]["momentum_cs_rank"] == 0.0
    assert r_norm["SISE::2026-02-20"]["momentum_cs_rank"] == 1.0

    # clean_features
    validator = TrainingDatasetValidator()
    noisy_map = {
        "THYAO::2026-02-20": {"momentum": float("inf"), "volatility": 0.2},
        "GARAN::2026-02-20": {"momentum": 20.0, "volatility": 0.4},
    }
    cleaned, stats = validator.clean_features(noisy_map, fnames)
    assert cleaned["THYAO::2026-02-20"]["momentum"] is None
    assert stats["inf_replaced"] == 1


def test_prepare_features_for_inference_parity() -> None:
    """Inference parity hazırlığı testi."""
    raw = {"momentum": 15.0, "volatility": 0.3}
    all_date = {
        "THYAO": {"momentum": 15.0, "volatility": 0.3},
        "GARAN": {"momentum": 25.0, "volatility": 0.5},
    }
    fnames = ["momentum", "volatility"]
    cs_names = ["momentum_cs_zscore", "volatility_cs_zscore"]

    res = prepare_features_for_inference(
        ticker="THYAO",
        raw_features=raw,
        all_date_features=all_date,
        feature_names=fnames,
        cs_features=cs_names,
        date_str="2026-02-23",
    )

    assert "momentum" in res
    assert "momentum_cs_zscore" in res
    assert isinstance(res["momentum_cs_zscore"], float)


def test_training_validator_thread_safety(tmp_path: Path) -> None:
    """Çoklu iş parçacığında (thread-safety) eşzamanlı doğrulama ve denetim testi."""
    db_file = tmp_path / "thread_audit.duckdb"
    validator = TrainingDatasetValidator(duckdb_path=str(db_file))

    features_map = {
        "A::2026-01-01": {"f1": 1.0},
        "B::2026-01-01": {"f1": 2.0},
    }
    returns = {"A::2026-01-01": 0.01, "B::2026-01-01": -0.01}
    date_groups = {"A::2026-01-01": "2026-01-01", "B::2026-01-01": "2026-01-01"}
    fnames = ["f1"]

    def worker(idx: int) -> float:
        rep = validator.validate_dataset(features_map, returns, date_groups, fnames)
        validator.record_quality_audit(rep, dataset_name=f"worker_set_{idx}")
        return rep.quality_score

    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
        futures = [executor.submit(worker, i) for i in range(10)]
        results = [f.result() for f in futures]

    assert len(results) == 10
    assert all(r > 0.0 for r in results)

    df_audit = validator.get_audit_as_polars()
    assert df_audit.height == 10
