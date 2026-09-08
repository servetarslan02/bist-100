"""services/ml/catboost_model.py Kapsamlı ve Çok Senaryolu Test Paketi.

GEMINI.md Kural 1-8 standartlarına göre CatBoost Challenger modelini,
asimetrik kayıp fonksiyonunu (CatBoostAdjustedLoss), çoklu ufuk (multi-horizon) eğitimini,
Polars tahminini, model kaydetme/yüklemeyi, DuckDB entegrasyonunu ve eşzamanlılığı doğrular.
"""

from __future__ import annotations

import concurrent.futures
from typing import TYPE_CHECKING

import numpy as np
import polars as pl
import pytest

from services.ml.catboost_model import (
    CatBoostAdjustedLoss,
    CatBoostConfig,
    CatBoostModel,
)

if TYPE_CHECKING:
    from pathlib import Path


def test_config_serialization_and_roundtrip() -> None:
    """CatBoostConfig to_dict, from_dict ve to_orjson_bytes doğrulaması."""
    cfg = CatBoostConfig(
        iterations=100,
        depth=5,
        learning_rate=0.05,
        loss_function="RMSE",
        eval_metric="RMSE",
        use_adjusted_loss=True,
        wrong_direction_penalty=8.0,
    )

    d = cfg.to_dict()
    assert d["iterations"] == 100
    assert d["depth"] == 5
    assert d["wrong_direction_penalty"] == 8.0
    assert d["use_adjusted_loss"] is True

    b = cfg.to_orjson_bytes()
    assert isinstance(b, bytes)
    assert b"RMSE" in b

    restored = CatBoostConfig.from_dict(d)
    assert restored.iterations == cfg.iterations
    assert restored.use_adjusted_loss == cfg.use_adjusted_loss
    assert restored.wrong_direction_penalty == cfg.wrong_direction_penalty
    assert "CatBoostConfig" in repr(restored)


def test_adjusted_loss_calc_ders_range() -> None:
    """CatBoost yerel özel kayıp fonksiyonu (CatBoostAdjustedLoss) gradyan/hessian hesabı."""
    # 1. Geçersiz katsayı hatası
    with pytest.raises(ValueError, match="Ceza çarpanı 1.0'dan küçük olamaz"):
        CatBoostAdjustedLoss(penalty=0.5)

    loss = CatBoostAdjustedLoss(penalty=10.0)
    assert "10.0" in repr(loss)

    # 2. calc_ders_range testi:
    # 1. örnek: pred: 0.5, actual: 0.5 (aynı yön, diff=0) -> der1 = 0, der2 = 2.0
    # 2. örnek: pred: 1.0, actual: -1.0 (ters yön, diff=2.0) -> der1 = 2 * 2.0 * 10 = 40.0, der2 = 2 * 10 = 20.0
    approxes = [0.5, 1.0]
    targets = [0.5, -1.0]
    der1, der2 = loss.calc_ders_range(approxes, targets, weights=None)

    assert pytest.approx(der1[0], 1e-5) == 0.0
    assert pytest.approx(der2[0], 1e-5) == 2.0
    assert pytest.approx(der1[1], 1e-5) == 40.0
    assert pytest.approx(der2[1], 1e-5) == 20.0


def test_model_training_and_prediction() -> None:
    """Hafif CatBoost sınıflandırıcı modelinin eğitimi, tahmini ve metrikleri."""
    cfg = CatBoostConfig(
        iterations=10,
        depth=3,
        learning_rate=0.1,
        loss_function="Logloss",
        eval_metric="AUC",
        verbose=0,
    )
    cb_model = CatBoostModel(cfg)
    assert "CatBoostModel" in repr(cb_model)
    assert cb_model.is_trained is False

    rng = np.random.default_rng(42)
    X_train = rng.normal(size=(80, 4))
    y_train = (X_train[:, 0] + X_train[:, 1] > 0).astype(int)

    X_val = rng.normal(size=(30, 4))
    y_val = (X_val[:, 0] + X_val[:, 1] > 0).astype(int)

    # Horizon=5 eğitimi
    metrics_5 = cb_model.train(
        X_train=X_train,
        y_train=y_train,
        X_val=X_val,
        y_val=y_val,
        feature_names=["f1", "f2", "f3", "f4"],
        horizon=5,
    )

    assert cb_model.is_trained is True
    assert 5 in cb_model.trained_horizons
    assert "val_auc" in metrics_5

    # Tahmin (predict)
    preds = cb_model.predict(X_val, horizon=5)
    assert len(preds) == len(X_val)
    assert np.all((preds >= 0.0) & (preds <= 1.0))

    # Tüm ufuklar (predict_all_horizons)
    all_preds = cb_model.predict_all_horizons(X_val)
    assert 5 in all_preds

    # Öznitelik önemi (feature_importance)
    fi = cb_model.feature_importance(horizon=5)
    assert fi is not None
    assert "f1" in fi


def test_predict_polars() -> None:
    """Polars DataFrame girdisi üzerinden doğrudan CatBoost tahmini."""
    cfg = CatBoostConfig(iterations=8, depth=2, verbose=0)
    cb_model = CatBoostModel(cfg)

    rng = np.random.default_rng(99)
    X_train = rng.normal(size=(60, 2))
    y_train = (X_train[:, 0] > 0).astype(int)

    cb_model.train(X_train=X_train, y_train=y_train, feature_names=["col_a", "col_b"], horizon=1)

    df_test = pl.DataFrame({
        "col_a": [0.5, -0.2, 1.2],
        "col_b": [-0.1, 0.4, 0.3],
    })

    polars_preds = cb_model.predict_polars(df_test, feature_columns=["col_a", "col_b"], horizon=1)
    assert len(polars_preds) == 3
    assert np.all(np.isfinite(polars_preds))


def test_save_and_load(tmp_path: Path) -> None:
    """Modelin diske güvenle kaydedilmesi ve geri yüklenmesi."""
    cfg = CatBoostConfig(iterations=5, depth=2, verbose=0)
    cb_model = CatBoostModel(cfg)

    X = np.random.normal(size=(40, 2))
    y = (X[:, 0] > 0).astype(int)
    cb_model.train(X_train=X, y_train=y, feature_names=["a", "b"], horizon=5)

    save_file = str(tmp_path / "catboost_test.pkl")
    ok = cb_model.save(save_file)
    assert ok is True

    # Yeni model örneğine yükle
    loaded_model = CatBoostModel()
    load_ok = loaded_model.load(save_file)
    assert load_ok is True
    assert loaded_model.is_trained is True
    assert 5 in loaded_model.trained_horizons

    preds = loaded_model.predict(X[:5], horizon=5)
    assert len(preds) == 5


def test_duckdb_and_polars_metrics_export(tmp_path: Path) -> None:
    """Eğitim metriklerinin DuckDB'ye yazılması ve Polars ile okunması."""
    cfg = CatBoostConfig(iterations=5, depth=2, verbose=0)
    cb_model = CatBoostModel(cfg)

    X = np.random.normal(size=(40, 2))
    y = (X[:, 0] > 0).astype(int)
    cb_model.train(X_train=X, y_train=y, horizon=10)

    db_path = str(tmp_path / "catboost_audit.duckdb")
    cb_model.export_metrics_duckdb(db_path=db_path, table_name="test_cb_audit")

    df_metrics = cb_model.read_metrics_polars(db_path=db_path, table_name="test_cb_audit")
    assert isinstance(df_metrics, pl.DataFrame)
    assert df_metrics.height >= 1
    assert "horizon" in df_metrics.columns


def test_thread_safety_concurrent_predict() -> None:
    """Çoklu iş parçacığında eşzamanlı CatBoost tahmin doğrulaması."""
    cfg = CatBoostConfig(iterations=5, depth=2, verbose=0)
    cb_model = CatBoostModel(cfg)

    X = np.random.normal(size=(50, 3))
    y = (X[:, 0] > 0).astype(int)
    cb_model.train(X_train=X, y_train=y, horizon=5)

    def worker(i: int) -> int:
        test_x = np.random.normal(size=(10, 3))
        p = cb_model.predict(test_x, horizon=5)
        return len(p)

    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as executor:
        futures = [executor.submit(worker, i) for i in range(20)]
        results = [f.result() for f in futures]

    assert len(results) == 20
    assert all(r == 10 for r in results)
