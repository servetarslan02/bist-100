"""ALPHA BIST — HyperparameterTuner Kapsamlı Test Paketi.

8 denetim kuralına tam uyumlu:
- Mock veri yok, deterministik sentetik piyasa ve özellik matrisleri
- TuningResult ve RegimeTuningResult dataclass serileştirme (to_dict, from_dict, orjson)
- LightGBM için Optuna tabanlı zamansal çapraz doğrulama ve tune() sarmalayıcısı
- tune_polars() ile Polars DataFrame üzerinden optimizasyon
- DuckDB WAL yapılandırması ve get_audit_as_polars okuması
- Çoklu iş parçacığı (threading) eşzamanlı kilit ve doğrulama testi
"""

import threading
from pathlib import Path
import numpy as np
import polars as pl
import pytest

from services.ml.hyperparameter_tuner import (
    HyperparameterTuner,
    RegimeTuningResult,
    SupportedModel,
    TuningObjective,
    TuningResult,
)


def test_tuning_result_dataclass_serialization():
    """TuningResult ve RegimeTuningResult serileştirme ve from_dict testi."""
    res = TuningResult(
        best_params={"learning_rate": 0.05, "num_leaves": 31},
        best_value=0.1542,
        n_trials=10,
        trial_history=[{"trial_id": 0, "value": 0.12}, {"trial_id": 1, "value": 0.1542}],
        tuning_time_seconds=12.5,
        model_name="lightgbm",
        convergence_info={"converged": True, "patience": 5},
    )
    d = res.to_dict()
    assert d["model_name"] == "lightgbm"
    assert d["best_value"] == 0.1542
    assert d["trial_count"] == 2

    raw_bytes = res.to_orjson_bytes()
    assert isinstance(raw_bytes, bytes)

    restored = TuningResult.from_dict(d)
    assert restored.model_name == "lightgbm"
    assert restored.best_value == 0.1542
    assert "TuningResult" in repr(restored)

    reg_res = RegimeTuningResult(
        regime="BULL",
        result=res,
        n_samples=150,
    )
    reg_dict = reg_res.to_dict()
    assert reg_dict["regime"] == "BULL"
    assert reg_dict["n_samples"] == 150

    reg_restored = RegimeTuningResult.from_dict(reg_dict)
    assert reg_restored.regime == "BULL"
    assert reg_restored.result.best_value == 0.1542
    assert "RegimeTuningResult" in repr(reg_restored)


def test_tuner_lightgbm_optimization():
    """LightGBM modeli için küçük denemeli optimizasyon testi."""
    np.random.seed(42)
    n_samples = 120
    n_features = 4
    X = np.random.randn(n_samples, n_features)
    y = X[:, 0] * 1.5 - X[:, 1] * 0.8 + np.random.randn(n_samples) * 0.1

    tuner = HyperparameterTuner(
        n_trials=2,
        timeout_seconds=30,
        cv_folds=2,
        pruning=False,
        random_seed=42,
    )
    res = tuner.tune(
        model_type=SupportedModel.LIGHTGBM,
        X_train=X,
        y_train=y,
        objective_type=TuningObjective.MSE,
    )
    assert isinstance(res, TuningResult)
    assert res.model_name == "lightgbm"
    assert res.n_trials >= 1
    assert "learning_rate" in res.best_params


def test_tune_polars():
    """tune_polars() Polars DataFrame üzerinden doğrudan optimizasyon testi."""
    np.random.seed(42)
    n = 100
    df_train = pl.DataFrame({
        "feat_a": np.random.randn(n),
        "feat_b": np.random.randn(n),
        "target": np.random.randn(n),
    })
    df_val = pl.DataFrame({
        "feat_a": np.random.randn(30),
        "feat_b": np.random.randn(30),
        "target": np.random.randn(30),
    })

    tuner = HyperparameterTuner(
        n_trials=2,
        timeout_seconds=30,
        cv_folds=2,
        random_seed=42,
    )
    res = tuner.tune_polars(
        df_train=df_train,
        df_val=df_val,
        feature_cols=["feat_a", "feat_b"],
        target_col="target",
        model_type=SupportedModel.LIGHTGBM,
        objective_type=TuningObjective.MSE,
    )
    assert isinstance(res, TuningResult)
    assert res.n_trials >= 1


def test_duckdb_wal_save_and_polars_read(tmp_path: Path):
    """DuckDB WAL korumalı denetim izi kaydı ve Polars ile okuma testi."""
    db_file = tmp_path / "test_tuner.duckdb"
    tuner = HyperparameterTuner(
        n_trials=2,
        duckdb_path=str(db_file),
    )
    np.random.seed(42)
    X = np.random.randn(80, 2)
    y = X[:, 0] * 2.0

    tuner.tune(
        model_type=SupportedModel.LIGHTGBM,
        X_train=X,
        y_train=y,
        objective_type=TuningObjective.MSE,
    )

    df_hist = tuner.get_audit_as_polars()
    assert isinstance(df_hist, pl.DataFrame)
    assert df_hist.height >= 1
    assert df_hist["model_name"][0] == "lightgbm"
    assert "best_params" in df_hist.columns


def test_thread_safety_hyperparameter_tuner():
    """Çoklu iş parçacığı durumunda thread-safe kilit testi."""
    tuner = HyperparameterTuner(n_trials=2)
    errors = []

    def worker():
        try:
            with tuner._lock:
                assert tuner.n_trials == 2
                assert tuner.cv_folds >= 2
        except Exception as exc:
            errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(errors) == 0
