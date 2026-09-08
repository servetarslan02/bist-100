"""ALPHA BIST — XGBoost Challenger Modeli Kapsamlı Test Paketi

services/ml/xgboost_model.py için kurumsal denetim testleri:
1. Dataclass serileştirme (XGBoostConfig, XGBoostMetrics) (to_dict, from_dict, to_orjson_bytes)
2. XGBoostAdjustedLoss yön cezası ve gradyan/hessian türev doğrulaması
3. XGBoostModel çoklu tahmin ufku eğitimi ve tahmini (train, predict)
4. Platt scaling olasılık kalibrasyonu (calibrate, predict_proba)
5. Polars vektörize tahmin desteği (predict_polars)
6. Safe pickle ile model kaydetme ve SHA256 doğrulamalı yükleme (save, load)
7. compare_xgboost_vs_lightgbm karşılaştırma akışı
8. DuckDB WAL denetim kaydı ve Polars okuma (get_audit_as_polars)
9. Thread-safety eşzamanlı erişim koruması
"""

from __future__ import annotations

import concurrent.futures
from typing import TYPE_CHECKING

import numpy as np
import polars as pl
import pytest

from services.ml.xgboost_model import (
    XGBoostAdjustedLoss,
    XGBoostConfig,
    XGBoostMetrics,
    XGBoostModel,
    compare_xgboost_vs_lightgbm,
)

if TYPE_CHECKING:
    from pathlib import Path


def test_xgboost_dataclasses_serialization() -> None:
    """XGBoostConfig ve XGBoostMetrics serileştirme ve deseralizasyon testleri."""
    # 1. XGBoostConfig
    cfg = XGBoostConfig(max_depth=4, learning_rate=0.05, n_estimators=50, use_adjusted_loss=True)
    d_cfg = cfg.to_dict()
    assert d_cfg["max_depth"] == 4
    assert d_cfg["use_adjusted_loss"] is True

    cfg_rec = XGBoostConfig.from_dict(d_cfg)
    assert cfg_rec.max_depth == 4
    assert cfg_rec.learning_rate == 0.05
    assert isinstance(cfg.to_orjson_bytes(), bytes)

    # 2. XGBoostMetrics
    metrics = XGBoostMetrics(
        horizon=5,
        n_train=1000,
        n_val=200,
        feature_count=15,
        val_auc=0.74,
        val_ic=0.045,
        val_directional_accuracy=0.62,
        signal_quality="STRONG",
    )
    d_m = metrics.to_dict()
    metrics_rec = XGBoostMetrics.from_dict(d_m)
    assert metrics_rec.horizon == 5
    assert metrics_rec.val_auc == 0.74
    assert metrics_rec.signal_quality == "STRONG"
    assert isinstance(metrics.to_orjson_bytes(), bytes)


def test_xgboost_adjusted_loss() -> None:
    """XGBoostAdjustedLoss ters yön ceza katsayısı doğrulaması."""
    loss_fn = XGBoostAdjustedLoss(penalty=5.0)
    assert loss_fn.penalty == 5.0

    class MockDMatrix:
        def __init__(self, labels: np.ndarray) -> None:
            self.labels = labels

        def get_label(self) -> np.ndarray:
            return self.labels

    # Aynı yön: ceza yok
    preds_same = np.array([0.1, -0.2], dtype=np.float32)
    labels_same = np.array([0.15, -0.1], dtype=np.float32)
    dtrain_same = MockDMatrix(labels_same)
    grad_same, hess_same = loss_fn(preds_same, dtrain_same)
    np.testing.assert_allclose(hess_same, [2.0, 2.0])

    # Yanlış yön: 5.0 ceza çarpanı
    preds_wrong = np.array([0.1, -0.2], dtype=np.float32)
    labels_wrong = np.array([-0.1, 0.2], dtype=np.float32)
    dtrain_wrong = MockDMatrix(labels_wrong)
    grad_wrong, hess_wrong = loss_fn(preds_wrong, dtrain_wrong)
    np.testing.assert_allclose(hess_wrong, [10.0, 10.0])


def test_xgboost_train_predict_and_calibration(tmp_path: Path) -> None:
    """XGBoostModel eğitimi, tahmini ve kalibrasyonu testi."""
    try:
        import xgboost  # noqa: F401
    except ImportError:
        pytest.skip("xgboost kütüphanesi kurulu değil")

    db_path = tmp_path / "xgb_audit.duckdb"
    cfg = XGBoostConfig(
        max_depth=3,
        learning_rate=0.1,
        n_estimators=10,
        random_state=42,
    )
    model = XGBoostModel(config=cfg, duckdb_path=str(db_path))

    rng = np.random.default_rng(42)
    N = 80
    X = rng.normal(0, 1, (N, 4))
    y = (X[:, 0] + X[:, 1] * 0.5 + rng.normal(0, 0.2, N) > 0).astype(int)
    fnames = ["f0", "f1", "f2", "f3"]

    # 1. Eğitim
    m = model.train(X[:60], y[:60], X[60:], y[60:], feature_names=fnames, horizon=5)
    assert model.is_trained is True
    assert 5 in model.trained_horizons
    assert "val_auc" in m

    # 2. Tahmin
    preds = model.predict(X[60:], horizon=5)
    assert len(preds) == 20
    assert np.all((preds >= 0.0) & (preds <= 1.0))

    # 3. Kalibrasyon
    cal_res = model.calibrate(X[60:], y[60:], horizon=5, method="sigmoid")
    assert "calibrated_brier" in cal_res

    # 4. Polars Tahmini
    df_in = pl.DataFrame({
        fnames[i]: X[:, i] for i in range(4)
    })
    df_out = model.predict_polars(df_in, fnames, horizon=5)
    assert "xgboost_pred_5d" in df_out.columns
    assert len(df_out) == N

    # 5. DuckDB Denetim Kaydı Okuma
    df_audit = model.get_audit_as_polars()
    assert isinstance(df_audit, pl.DataFrame)
    assert df_audit.height >= 1
    assert "horizon" in df_audit.columns


def test_xgboost_save_load_and_compare(tmp_path: Path) -> None:
    """Modelin diske güvenle kaydedilmesi, yüklenmesi ve LightGBM ile karşılaştırılması."""
    try:
        import xgboost  # noqa: F401
    except ImportError:
        pytest.skip("xgboost kütüphanesi kurulu değil")

    db_path = tmp_path / "xgb_compare.duckdb"
    model_file = tmp_path / "xgboost_test_model.pkl"

    cfg = XGBoostConfig(max_depth=3, n_estimators=5, random_state=123)
    model = XGBoostModel(config=cfg, duckdb_path=str(db_path))

    rng = np.random.default_rng(123)
    X = rng.normal(0, 1, (40, 3))
    y = (X[:, 0] > 0).astype(int)
    model.train(X[:30], y[:30], X[30:], y[30:], horizon=5)

    # Save
    saved = model.save(str(model_file))
    assert saved is True
    assert model_file.exists()

    # Load
    new_model = XGBoostModel(duckdb_path=str(db_path))
    loaded = new_model.load(str(model_file))
    assert loaded is True
    assert new_model.is_trained is True

    # Tahmin doğrulaması
    p1 = model.predict(X[30:], horizon=5)
    p2 = new_model.predict(X[30:], horizon=5)
    np.testing.assert_allclose(p1, p2, rtol=1e-4)

    # Karşılaştırma fonksiyonu (compare_xgboost_vs_lightgbm)
    N_comp = 120
    X_comp = rng.normal(0, 1, (N_comp, 2))
    y_comp = (X_comp[:, 0] * 0.5 + X_comp[:, 1] * 0.3 + rng.normal(0, 0.1, N_comp)).astype(float)
    features_map = {f"T{i}::2026-01-01": {"f1": float(X_comp[i, 0]), "f2": float(X_comp[i, 1])} for i in range(N_comp)}
    returns = {f"T{i}::2026-01-01": float(y_comp[i]) for i in range(N_comp)}
    date_groups = {f"T{i}::2026-01-01": "2026-01-01" for i in range(N_comp)}

    comp = compare_xgboost_vs_lightgbm(features_map, returns, date_groups, ["f1", "f2"], config=cfg)
    assert "comparison" in comp
    assert comp["comparison"]["winner"] in ["lightgbm", "xgboost", "equal"]


def test_xgboost_thread_safety(tmp_path: Path) -> None:
    """Eşzamanlı thread'lerde tahmin ve denetim thread-safety testi."""
    try:
        import xgboost  # noqa: F401
    except ImportError:
        pytest.skip("xgboost kütüphanesi kurulu değil")

    db_path = tmp_path / "xgb_thread.duckdb"
    cfg = XGBoostConfig(max_depth=2, n_estimators=5)
    model = XGBoostModel(config=cfg, duckdb_path=str(db_path))

    rng = np.random.default_rng(999)
    X = rng.normal(0, 1, (30, 2))
    y = (X[:, 0] > 0).astype(int)
    model.train(X, y, horizon=5)

    def worker(_: int) -> float:
        preds = model.predict(X, horizon=5)
        return float(np.mean(preds))

    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
        futures = [executor.submit(worker, i) for i in range(8)]
        results = [f.result() for f in futures]

    assert len(results) == 8
    assert all(np.isfinite(r) for r in results)
