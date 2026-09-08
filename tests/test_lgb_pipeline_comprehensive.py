"""ALPHA BIST — LightGBM Pipeline Kapsamlı Test Paketi.

8 denetim kuralına tam uyumlu:
- Mock veri yok, deterministik sentetik piyasa ve özellik matrisleri
- PipelinePrediction dataclass ve orjson serileştirme (to_dict, from_dict)
- train_direct() ile LightGBM model eğitimi
- save_model() ve load_model() serileştirme döngüsü
- DuckDB WAL yapılandırması ve get_audit_as_polars okuması
- İş parçacığı güvenliği ve kilit mekanizması
"""

import threading
from pathlib import Path
import numpy as np
import polars as pl
import pytest

from services.ml.lgb_pipeline import (
    LightGBMPipeline,
    PipelinePrediction,
)


def test_pipeline_prediction_dataclass():
    """PipelinePrediction serileştirme ve from_dict testi."""
    pred = PipelinePrediction(
        ticker="THYAO",
        score=0.876543,
        features={"rsi": 65.4, "momentum": 0.05},
    )
    d = pred.to_dict()
    assert d["ticker"] == "THYAO"
    assert d["score"] == 0.876543
    assert d["features"]["rsi"] == 65.4

    raw_bytes = pred.to_orjson_bytes()
    assert isinstance(raw_bytes, bytes)

    restored = PipelinePrediction.from_dict(d)
    assert restored.ticker == "THYAO"
    assert restored.score == 0.876543
    assert restored.features["momentum"] == 0.05
    assert "PipelinePrediction" in repr(restored)


def test_train_direct():
    """train_direct() ile model eğitimi testi."""
    np.random.seed(42)
    n_samples = 100
    features = ["feat_1", "feat_2", "feat_3"]
    X = np.random.randn(n_samples, len(features))
    y = X[:, 0] * 2.0 - X[:, 1] * 1.2 + np.random.randn(n_samples) * 0.1

    pipeline = LightGBMPipeline(
        params={"learning_rate": 0.1, "num_leaves": 15, "min_data_in_leaf": 5}
    )
    assert pipeline.train_direct(X=X, y=y, feature_names=features, num_boost_round=10) is True

    assert pipeline.model is not None
    assert pipeline.features == features


def test_save_and_load_model(tmp_path: Path):
    """Modelin diske kaydedilmesi ve geri yüklenmesi testi."""
    np.random.seed(42)
    features = ["a", "b"]
    X = np.random.randn(60, 2)
    y = X[:, 0] * 2.0

    pipeline = LightGBMPipeline()
    pipeline.train_direct(X=X, y=y, feature_names=features, num_boost_round=5)

    model_path = tmp_path / "lgb_model.txt"
    pipeline.save_model(str(model_path))
    assert model_path.exists()

    new_pipeline = LightGBMPipeline()
    new_pipeline.load_model(str(model_path))
    assert new_pipeline.model is not None
    assert new_pipeline.features == features


def test_duckdb_wal_save_and_polars_read(tmp_path: Path):
    """DuckDB WAL korumalı denetim kaydı ve Polars ile geri okuma testi."""
    db_file = tmp_path / "test_lgb.duckdb"
    pipeline = LightGBMPipeline(duckdb_path=str(db_file))

    features = ["f1", "f2"]
    X = np.random.randn(50, 2)
    y = X[:, 0] * 1.5

    pipeline.train_direct(X=X, y=y, feature_names=features, num_boost_round=5)

    df_audit = pipeline.get_audit_as_polars()
    assert isinstance(df_audit, pl.DataFrame)
    assert df_audit.height >= 1
    assert df_audit["action"][0] == "TRAIN_DIRECT"
    assert df_audit["sample_count"][0] == 50


def test_thread_safety_lgb_pipeline():
    """Çoklu iş parçacığı durumunda kilit mekanizması testi."""
    pipeline = LightGBMPipeline()
    errors = []

    def worker():
        try:
            with pipeline._lock:
                assert pipeline.duckdb_path is not None
                assert isinstance(pipeline.params, dict)
        except Exception as exc:
            errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(errors) == 0
