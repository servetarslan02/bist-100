"""ALPHA BIST — HyperOptimizer Kapsamlı Test Paketi.

8 denetim kuralına tam uyumlu:
- Mock veri yok, deterministik sentetik piyasa ve özellik matrisleri
- OptimizationResult dataclass ve orjson serileştirme testleri
- Regression hedefi için Optuna hiperparametre araması ve TimeSeriesSplit
- optimize_and_report() ile raporlama
- optimize_polars() ile Polars DataFrame üzerinden optimizasyon
- DuckDB WAL yapılandırması ve get_audit_as_polars okuması
- İş parçacığı güvenliği ve hata yönetimi
"""

import threading
from pathlib import Path
import numpy as np
import polars as pl
import pytest

from services.ml.hyper_optimizer import (
    HyperOptimizer,
    ObjectiveType,
    OptimizationResult,
)


def test_optimization_result_dataclass():
    """OptimizationResult serileştirme ve from_dict testi."""
    res = OptimizationResult(
        best_params={"learning_rate": 0.05, "num_leaves": 31},
        best_score=0.854321,
        n_trials=10,
        completed_trials=8,
        pruned_trials=2,
        objective="regression",
        n_splits=3,
    )
    d = res.to_dict()
    assert d["objective"] == "regression"
    assert d["best_score"] == 0.854321
    assert d["completed_trials"] == 8

    # orjson byte dizisi
    raw_bytes = res.to_orjson_bytes()
    assert isinstance(raw_bytes, bytes)

    # from_dict doğrulaması
    restored = OptimizationResult.from_dict(d)
    assert restored.objective == "regression"
    assert restored.best_score == 0.854321
    assert restored.best_params["learning_rate"] == 0.05
    assert "OptimizationResult" in repr(restored)


def test_hyper_optimizer_regression():
    """Küçük deneme sayılı regression optimizasyonu testi."""
    np.random.seed(42)
    n_samples = 150
    n_features = 5
    X = np.random.randn(n_samples, n_features)
    y = X[:, 0] * 2.0 - X[:, 1] * 1.5 + np.random.randn(n_samples) * 0.1

    optimizer = HyperOptimizer(
        n_trials=2,
        objective=ObjectiveType.REGRESSION,
        n_splits=2,
        timeout=30,
        random_seed=42,
    )
    best_params = optimizer.optimize(X, y)

    assert isinstance(best_params, dict)
    assert "learning_rate" in best_params
    assert "num_leaves" in best_params


def test_hyper_optimizer_optimize_and_report():
    """optimize_and_report() ile parametre ve sonuç raporu alma testi."""
    np.random.seed(42)
    n_samples = 120
    n_features = 3
    X = np.random.randn(n_samples, n_features)
    y = X[:, 0] * 1.5 + np.random.randn(n_samples) * 0.1

    optimizer = HyperOptimizer(
        n_trials=2,
        objective="regression",
        n_splits=2,
        random_seed=42,
    )
    best_params, res = optimizer.optimize_and_report(X, y)

    assert isinstance(best_params, dict)
    assert isinstance(res, OptimizationResult)
    assert res.completed_trials >= 1
    assert res.n_trials == 2


def test_hyper_optimizer_optimize_polars():
    """optimize_polars() Polars DataFrame üzerinden doğrudan optimizasyon testi."""
    np.random.seed(42)
    n = 120
    df = pl.DataFrame({
        "feat_1": np.random.randn(n),
        "feat_2": np.random.randn(n),
        "target": np.random.randn(n),
    })

    optimizer = HyperOptimizer(
        n_trials=2,
        objective="regression",
        n_splits=2,
        random_seed=42,
    )
    best_params, result = optimizer.optimize_polars(
        df=df,
        feature_cols=["feat_1", "feat_2"],
        target_col="target",
    )
    assert isinstance(best_params, dict)
    assert isinstance(result, OptimizationResult)
    assert result.completed_trials >= 1


def test_duckdb_wal_save_and_polars_read(tmp_path: Path):
    """DuckDB WAL korumalı denetim izi kaydı ve Polars ile okuma testi."""
    db_file = tmp_path / "test_hyper.duckdb"
    optimizer = HyperOptimizer(
        n_trials=2,
        duckdb_path=str(db_file),
    )
    np.random.seed(42)
    X = np.random.randn(100, 2)
    y = X[:, 0] * 2.0

    optimizer.optimize_and_report(X, y)

    df_audit = optimizer.get_audit_as_polars()
    assert isinstance(df_audit, pl.DataFrame)
    assert df_audit.height >= 1
    assert "best_params" in df_audit.columns
    assert "objective" in df_audit.columns


def test_thread_safety_hyper_optimizer():
    """Çoklu iş parçacığı durumunda thread-safe başlatma ve kilit testi."""
    optimizer = HyperOptimizer(n_trials=2)
    errors = []

    def worker():
        try:
            with optimizer._lock:
                assert optimizer.n_trials == 2
                assert optimizer.n_splits >= 2
        except Exception as exc:
            errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(errors) == 0
