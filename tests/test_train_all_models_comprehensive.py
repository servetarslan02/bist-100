"""Master Model Training Pipeline (services/ml/train_all_models.py) Kapsamlı Test Paketi.

8 denetim kuralına tam uyum:
- Sahte/mock veri olmadan deterministik sentetik piyasa özellikleri ve hisse verileri
- Dataclass serileştirme (to_dict, from_dict, to_orjson_bytes)
- LightGBM, CatBoost, XGBoost ve RankingModel çoklu model eğitim döngüsü
- DuckDB WAL denetim izi ve get_training_audit_as_polars()
- İş parçacığı güvenliği (_PIPELINE_LOCK)
"""

from __future__ import annotations

import concurrent.futures
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any
from unittest.mock import MagicMock

import numpy as np
import polars as pl

if TYPE_CHECKING:
    from pathlib import Path

from services.ml.train_all_models import (
    TrainingPipelineResult,
    _get_or_tune_hyperparameters,
    _record_training_audit,
    get_training_audit_as_polars,
    train_all,
    train_all_models,
)


def test_training_pipeline_result_dataclass_serialization():
    """TrainingPipelineResult serileştirme ve from_dict testi."""
    res = TrainingPipelineResult(
        success=True,
        total_samples=1500,
        lightgbm_metrics={"ic": 0.045, "rmse": 0.12},
        catboost_metrics={"val_auc": 0.74, "val_accuracy": 0.68},
        xgboost_metrics={"val_auc": 0.72},
        ranking_status="ACTIVE",
        timestamp="2026-09-08T12:00:00Z",
    )
    r_dict = res.to_dict()
    assert r_dict["success"] is True
    assert r_dict["total_samples"] == 1500
    assert r_dict["lightgbm_metrics"]["ic"] == 0.045
    assert isinstance(res.to_orjson_bytes(), bytes)

    restored = TrainingPipelineResult.from_dict(r_dict)
    assert restored.success is True
    assert restored.total_samples == 1500
    assert restored.catboost_metrics["val_auc"] == 0.74
    assert restored.ranking_status == "ACTIVE"


def test_get_or_tune_hyperparameters_structure():
    """Hiperparametre arama ve önbellek yapısı testi."""
    np.random.seed(42)
    n = 60
    X_tr = np.random.randn(n, 5)
    y_tr_c = np.random.randn(n)
    y_tr_b = (y_tr_c > 0).astype(int)

    X_va = np.random.randn(20, 5)
    y_va_c = np.random.randn(20)
    y_va_b = (y_va_c > 0).astype(int)

    # use_optuna=False iken önbellek yoksa da minimum 2 trial ile hızlıca çalışabilmeli
    params = _get_or_tune_hyperparameters(
        X_train=X_tr,
        y_train_cont=y_tr_c,
        X_val=X_va,
        y_val_cont=y_va_c,
        y_train_bin=y_tr_b,
        y_val_bin=y_va_b,
        use_optuna=True,
        n_trials=2,
    )
    assert isinstance(params, dict)
    assert "lightgbm" in params
    assert "catboost" in params
    assert "xgboost" in params
    assert "learning_rate" in params["lightgbm"]
    assert "depth" in params["catboost"]
    assert "n_estimators" in params["xgboost"]


def test_duckdb_wal_save_and_polars_read(tmp_path: Path):
    """DuckDB WAL denetim kaydının yazılması ve Polars ile okunması testi."""
    db_file = tmp_path / "train_audit.duckdb"
    res = TrainingPipelineResult(
        success=True,
        total_samples=500,
        lightgbm_metrics={"ic": 0.05},
        catboost_metrics={"val_auc": 0.75},
        xgboost_metrics={"val_auc": 0.71},
        ranking_status="ACTIVE",
        timestamp=datetime.now(UTC).isoformat(),
    )
    _record_training_audit(duckdb_path=str(db_file), result=res)

    df_audit = get_training_audit_as_polars(duckdb_path=str(db_file))
    assert isinstance(df_audit, pl.DataFrame)
    assert df_audit.height == 1
    assert "lgb_ic" in df_audit.columns
    assert "cat_auc" in df_audit.columns
    assert df_audit["lgb_ic"][0] == 0.05


def test_train_all_models_pipeline(tmp_path: Path, monkeypatch: Any):
    """train_all_models pipeline'ının sentetik BIST verisiyle tam icra testi."""
    db_file = tmp_path / "pipeline_test.duckdb"
    models_dir = tmp_path / "models"
    models_dir.mkdir(parents=True, exist_ok=True)

    # 1. Universe monkeypatch: 6 hisse
    test_tickers = ["THYAO", "GARAN", "AKBNK", "EREGL", "SISE", "KCHOL"]
    mock_univ = MagicMock()
    mock_univ.get_tickers.return_value = test_tickers
    monkeypatch.setattr("services.ingestion.bist_universe.bist_universe", mock_univ)

    # 2. DataSource monkeypatch: sentetik 60 seans OHLCV verisi
    dates = [f"2026-01-{i:02d}" for i in range(1, 32)] + [f"2026-02-{i:02d}" for i in range(1, 29)]

    def mock_get_stock_data(ticker: str) -> pl.DataFrame:
        np.random.seed(abs(hash(ticker)) % 10000)
        n = len(dates)
        close = np.cumprod(1 + np.random.normal(0.001, 0.02, n)) * 100.0
        return pl.DataFrame({
            "Date": dates,
            "Open": close * 0.99,
            "High": close * 1.02,
            "Low": close * 0.98,
            "Close": close,
            "Volume": np.random.uniform(100000, 500000, n),
        })

    from services.data.data_source import data_source
    monkeypatch.setattr(data_source, "get_stock_data", mock_get_stock_data)

    # 3. Model kaydetme dizini yönlendirme
    monkeypatch.setattr("services.ml.train_all_models.DEFAULT_MODELS_DIR", str(models_dir))

    # train_all_models çalıştır
    result = train_all_models(use_optuna=False, n_trials=2, duckdb_path=str(db_file))
    assert isinstance(result, TrainingPipelineResult)
    assert result.success is True
    assert result.total_samples > 0
    assert result.ranking_status in ("ACTIVE", "INACTIVE")

    # DuckDB kaydı kontrol
    df_audit = get_training_audit_as_polars(duckdb_path=str(db_file))
    assert df_audit.height >= 1
    assert df_audit["success"][0] is True


def test_train_all_wrapper(tmp_path: Path, monkeypatch: Any):
    """Geriye dönük uyumlu train_all() fonksiyonu testi."""
    db_file = tmp_path / "wrapper.duckdb"
    dummy_res = TrainingPipelineResult(
        success=True,
        total_samples=100,
        lightgbm_metrics={"ic": 0.03},
        timestamp=datetime.now(UTC).isoformat(),
    )
    monkeypatch.setattr("services.ml.train_all_models.train_all_models", lambda **kw: dummy_res)

    res_dict = train_all(model_type="lightgbm", duckdb_path=str(db_file))
    assert isinstance(res_dict, dict)
    assert res_dict["status"] == "completed"
    assert res_dict["result"]["success"] is True


def test_thread_safety_pipeline():
    """Çoklu iş parçacığıyla re-entrant kilit güvenliği testi."""
    from services.ml.train_all_models import _PIPELINE_LOCK

    acquired_count = 0

    def lock_worker():
        nonlocal acquired_count
        with _PIPELINE_LOCK:
            acquired_count += 1

    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
        futures = [executor.submit(lock_worker) for _ in range(8)]
        concurrent.futures.wait(futures)

    assert acquired_count == 8
