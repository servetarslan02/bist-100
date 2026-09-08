"""StackingEnsemble v3.0 (services/ml/stacking_ensemble.py) Kapsamlı Test Paketi.

8 denetim kuralına tam uyum:
- Sahte/mock veri yok, deterministik sentetik piyasa özellikleri
- Dataclass serileştirme (to_dict, from_dict, to_orjson_bytes)
- Çoklu base model eğitimi ve OOF meta-learner fit
- predict() ve predict_detailed() güven & uzlaşı analizleri
- Rejim duyarlı (regime-aware) meta-öğreniciler ve rejim geçişleri
- Polars DataFrame entegrasyonu (predict_polars)
- DuckDB WAL denetim izi ve get_audit_as_polars()
- İş parçacığı güvenliği (threading.RLock)
"""

from __future__ import annotations

import concurrent.futures
from typing import TYPE_CHECKING

import numpy as np
import polars as pl
from sklearn.linear_model import LinearRegression, Ridge

if TYPE_CHECKING:
    from pathlib import Path

from services.ml.stacking_ensemble import (
    StackingConfig,
    StackingEnsemble,
    StackingPredictionResult,
)


def test_dataclasses_serialization():
    """StackingConfig ve StackingPredictionResult serileştirme ve from_dict testi."""
    cfg = StackingConfig(
        meta_learner_type="ridge",
        cv_folds=3,
        use_proba=False,
        regime_aware=True,
        min_diversity_score=0.15,
    )
    c_dict = cfg.to_dict()
    assert c_dict["meta_learner_type"] == "ridge"
    assert c_dict["cv_folds"] == 3
    assert isinstance(cfg.to_orjson_bytes(), bytes)

    restored_cfg = StackingConfig.from_dict(c_dict)
    assert restored_cfg.meta_learner_type == "ridge"
    assert restored_cfg.cv_folds == 3

    res = StackingPredictionResult(
        prediction=0.035,
        confidence=0.88,
        model_predictions={"ridge": 0.03, "linear": 0.04},
        model_weights={"ridge": 0.6, "linear": 0.4},
        regime="BULL",
        agreement_score=0.92,
        diversity_score=0.45,
    )
    r_dict = res.to_dict()
    assert r_dict["prediction"] == 0.035
    assert r_dict["regime"] == "BULL"
    assert isinstance(res.to_orjson_bytes(), bytes)

    restored_res = StackingPredictionResult.from_dict(r_dict)
    assert restored_res.prediction == 0.035
    assert restored_res.regime == "BULL"
    assert restored_res.model_predictions["ridge"] == 0.03


def test_add_models_and_fit(tmp_path: Path):
    """Temel modelleri ekleme ve yığınlama modelini başarıyla eğitme testi."""
    db_file = tmp_path / "stacking_audit.duckdb"
    cfg = StackingConfig(meta_learner_type="ridge", cv_folds=3, regime_aware=False)
    ensemble = StackingEnsemble(config=cfg, duckdb_path=str(db_file))

    # 2 temel model ekle
    m1 = Ridge(alpha=1.0)
    m2 = LinearRegression()
    ensemble.add_model("ridge", m1, weight=1.0)
    ensemble.add_model("linear", m2, weight=1.0)

    assert len(ensemble.base_model_names) == 2
    assert not ensemble.is_fitted

    # Deterministik sentetik veri
    np.random.seed(42)
    n_samples = 120
    n_features = 5
    X_train = np.random.randn(n_samples, n_features)
    y_train = 0.5 * X_train[:, 0] - 0.3 * X_train[:, 1] + 0.1 * np.random.randn(n_samples)

    X_val = np.random.randn(40, n_features)
    y_val = 0.5 * X_val[:, 0] - 0.3 * X_val[:, 1] + 0.1 * np.random.randn(40)

    fit_metrics = ensemble.fit(X_train, y_train, X_val, y_val)
    assert ensemble.is_fitted
    assert "val_ic" in fit_metrics
    assert "val_rank_ic" in fit_metrics


def test_predict_and_predict_detailed(tmp_path: Path):
    """predict ve predict_detailed ile model tahminleri ve uzlaşı analizi testi."""
    db_file = tmp_path / "stacking_pred.duckdb"
    ensemble = StackingEnsemble(duckdb_path=str(db_file))

    ensemble.add_model("m1", Ridge(alpha=0.5))
    ensemble.add_model("m2", LinearRegression())

    np.random.seed(42)
    X_train = np.random.randn(100, 4)
    y_train = 0.4 * X_train[:, 0] + 0.1 * np.random.randn(100)
    X_val = np.random.randn(30, 4)
    y_val = 0.4 * X_val[:, 0] + 0.1 * np.random.randn(30)

    ensemble.fit(X_train, y_train, X_val, y_val)

    X_test = np.random.randn(10, 4)
    preds = ensemble.predict(X_test)
    assert len(preds) == 10
    assert np.all(np.isfinite(preds))

    # predict_detailed
    details = ensemble.predict_detailed(X_test, regime="BULL")
    assert isinstance(details, StackingPredictionResult)
    assert details.regime == "BULL"
    assert 0.0 <= details.confidence <= 1.0
    assert 0.0 <= details.agreement_score <= 1.0


def test_predict_polars(tmp_path: Path):
    """Polars DataFrame üzerinde tahmin ve sonuç zenginleştirme testi."""
    db_file = tmp_path / "stacking_polars.duckdb"
    ensemble = StackingEnsemble(duckdb_path=str(db_file))

    ensemble.add_model("m1", Ridge())
    ensemble.add_model("m2", LinearRegression())

    np.random.seed(42)
    X_train = np.random.randn(100, 3)
    y_train = X_train[:, 0] + 0.1 * np.random.randn(100)
    ensemble.fit(X_train, y_train, X_train[:20], y_train[:20])

    df_test = pl.DataFrame({
        "feat_0": np.random.randn(15).tolist(),
        "feat_1": np.random.randn(15).tolist(),
        "feat_2": np.random.randn(15).tolist(),
    })

    df_res = ensemble.predict_polars(df_test, feature_cols=["feat_0", "feat_1", "feat_2"], regime="SIDEWAYS")
    assert isinstance(df_res, pl.DataFrame)
    assert "stacking_prediction" in df_res.columns
    assert "confidence" in df_res.columns
    assert "regime" in df_res.columns
    assert df_res.height == 15


def test_regime_aware_stacking_and_evaluation(tmp_path: Path):
    """Farklı piyasa rejimleri altında eğitim ve rejim performans değerlendirmesi testi."""
    db_file = tmp_path / "stacking_regimes.duckdb"
    cfg = StackingConfig(regime_aware=True, regime_meta_learners=True, cv_folds=2)
    ensemble = StackingEnsemble(config=cfg, duckdb_path=str(db_file))

    ensemble.add_model("m1", Ridge())
    ensemble.add_model("m2", LinearRegression())

    np.random.seed(42)
    n = 150
    X_train = np.random.randn(n, 4)
    y_train = X_train[:, 0] * 0.5 + 0.1 * np.random.randn(n)
    regimes_train = np.array(["BULL"] * 60 + ["BEAR"] * 50 + ["SIDEWAYS"] * 40)

    X_val = np.random.randn(60, 4)
    y_val = X_val[:, 0] * 0.5 + 0.1 * np.random.randn(60)
    regimes_val = np.array(["BULL"] * 25 + ["BEAR"] * 20 + ["SIDEWAYS"] * 15)

    ensemble.fit(X_train, y_train, X_val, y_val, regimes_train=regimes_train, regimes_val=regimes_val)

    report = ensemble.evaluate_by_regime(X_val, y_val, regimes_val)
    assert isinstance(report, dict)
    for reg in ["BULL", "BEAR", "SIDEWAYS"]:
        if reg in report:
            assert "ic" in report[reg]
            assert "direction_accuracy" in report[reg]


def test_duckdb_wal_save_and_polars_read(tmp_path: Path):
    """DuckDB WAL denetim kaydının yazılması ve Polars ile okunması testi."""
    db_file = tmp_path / "audit_test.duckdb"
    ensemble = StackingEnsemble(duckdb_path=str(db_file))

    ensemble.add_model("m1", Ridge())
    ensemble.add_model("m2", LinearRegression())
    X = np.random.randn(60, 3)
    y = np.random.randn(60)
    ensemble.fit(X, y, X[:15], y[:15])

    df_audit = ensemble.get_audit_as_polars()
    assert isinstance(df_audit, pl.DataFrame)
    assert df_audit.height >= 1
    assert "operation" in df_audit.columns
    assert "val_ic" in df_audit.columns


def test_thread_safety_stacking_ensemble(tmp_path: Path):
    """Çoklu iş parçacığıyla eşzamanlı tahmin sorgularının güvenliği testi."""
    db_file = tmp_path / "thread_test.duckdb"
    ensemble = StackingEnsemble(duckdb_path=str(db_file))

    ensemble.add_model("m1", Ridge())
    ensemble.add_model("m2", LinearRegression())
    X_train = np.random.randn(80, 3)
    y_train = np.random.randn(80)
    ensemble.fit(X_train, y_train, X_train[:20], y_train[:20])

    X_query = np.random.randn(10, 3)

    def worker(_: int) -> float:
        preds = ensemble.predict(X_query)
        return float(np.mean(preds))

    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
        results = list(executor.map(worker, range(10)))

    assert len(results) == 10
    # Tüm sonuçlar birbirine eşit olmalı (deterministik çıkarım)
    assert np.allclose(results, results[0])
