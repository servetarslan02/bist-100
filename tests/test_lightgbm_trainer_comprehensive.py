"""ALPHA BIST — LightGBMTrainer Kapsamlı Test Paketi.

8 denetim kuralına tam uyumlu:
- Mock veri yok, deterministik sentetik zaman serisi ve öznitelik haritaları
- MLModelConfig ve TrainedModel dataclass testleri
- compute_comprehensive_metrics() quant doğrulama metrikleri (IC, RMSE, Directional Accuracy)
- Date-Space Purge & Embargo ile train() modeli eğitimi
- train_polars() Polars DataFrame üzerinden eğitim ve TrainedModel.predict()
- Model save() ve load() serileştirme döngüsü
- DuckDB WAL yapılandırması ve get_audit_as_polars okuması
- Çoklu iş parçacığı (threading) eşzamanlı kilit testi
"""

import threading
from pathlib import Path
import numpy as np
import polars as pl
import pytest

from services.ml.lightgbm_trainer import (
    LightGBMTrainer,
    MLModelConfig,
    TrainedModel,
    compute_comprehensive_metrics,
)


def test_ml_model_config_dataclass_serialization():
    """MLModelConfig serileştirme ve from_dict testi."""
    cfg = MLModelConfig(
        objective="regression",
        metric="rmse",
        learning_rate=0.03,
        num_leaves=25,
        target_horizon=5,
        purge_gap_days=5,
    )
    d = cfg.to_dict()
    assert d["objective"] == "regression"
    assert d["learning_rate"] == 0.03
    assert isinstance(cfg.to_orjson_bytes(), bytes)

    restored = MLModelConfig.from_dict(d)
    assert restored.objective == "regression"
    assert restored.learning_rate == 0.03
    assert restored.num_leaves == 25
    assert "MLModelConfig" in repr(restored)


def test_compute_comprehensive_metrics():
    """compute_comprehensive_metrics() quant metrik hesaplama testi."""
    y_true = np.array([0.05, -0.02, 0.08, -0.01, 0.04])
    y_pred = np.array([0.04, -0.01, 0.07, 0.00, 0.05])

    metrics = compute_comprehensive_metrics(y_true, y_pred)
    assert metrics["rmse"] > 0.0
    assert metrics["mae"] > 0.0
    assert metrics["directional_accuracy"] > 0.50
    assert "ic" in metrics
    assert "rank_correlation" in metrics


def test_train_with_date_space_split(tmp_path: Path):
    """Tarihsel Point-In-Time arındırma (Date-Space Purge) ile model eğitimi testi."""
    np.random.seed(42)
    # 25 farklı tarih, her tarihte 4 hisse -> 100 örneklem
    dates = [f"2026-01-{i:02d}" for i in range(1, 26)]
    tickers = ["THYAO", "GARAN", "ASELS", "KCHOL"]

    features_map: dict[str, dict[str, float]] = {}
    returns: dict[str, float] = {}
    date_groups: dict[str, str] = {}
    feature_names = ["momentum", "rsi", "volatility"]

    for d in dates:
        for t in tickers:
            key = f"{t}_{d}"
            date_groups[key] = d
            f_vals = np.random.randn(3)
            features_map[key] = {
                "momentum": float(f_vals[0]),
                "rsi": float(f_vals[1]),
                "volatility": float(f_vals[2]),
            }
            # Deterministik getiri ilişkisi
            returns[key] = float(f_vals[0] * 1.5 - f_vals[1] * 0.8 + np.random.randn() * 0.1)

    cfg = MLModelConfig(
        num_boost_round=15,
        early_stopping_rounds=5,
        val_ratio=0.20,
        purge_gap_days=2,
        target_horizon=2,
        duckdb_path=str(tmp_path / "trainer.duckdb"),
    )
    trainer = LightGBMTrainer(config=cfg)

    trained_model = trainer.train(
        features_map=features_map,
        returns=returns,
        date_groups=date_groups,
        feature_names=feature_names,
    )

    assert trained_model is not None
    assert isinstance(trained_model, TrainedModel)
    assert len(trained_model.feature_names) == 3

    # Tahmin testi
    sample = {"momentum": 0.5, "rsi": 0.1, "volatility": -0.2}
    pred = trained_model.predict(sample)
    assert isinstance(pred, float)
    assert np.isfinite(pred)

    batch_preds = trained_model.predict_batch([sample, sample])
    assert len(batch_preds) == 2


def test_train_polars(tmp_path: Path):
    """train_polars() ile Polars DataFrame üzerinden doğrudan eğitim testi."""
    np.random.seed(42)
    rows = []
    dates = [f"2026-02-{i:02d}" for i in range(1, 26)]
    tickers = ["EREGL", "SISE", "BIMAS"]

    for d in dates:
        for t in tickers:
            m = float(np.random.randn())
            r = float(np.random.randn())
            rows.append({
                "ticker": t,
                "date": d,
                "f_mom": m,
                "f_rsi": r,
                "target": m * 1.2 - r * 0.5,
            })

    df = pl.DataFrame(rows)

    cfg = MLModelConfig(
        num_boost_round=10,
        val_ratio=0.20,
        purge_gap_days=2,
        target_horizon=2,
        duckdb_path=str(tmp_path / "polars_trainer.duckdb"),
    )
    trainer = LightGBMTrainer(config=cfg)

    trained_model = trainer.train_polars(
        df=df,
        target_col="target",
        date_col="date",
        ticker_col="ticker",
        feature_cols=["f_mom", "f_rsi"],
    )

    assert trained_model is not None
    assert isinstance(trained_model, TrainedModel)


def test_save_and_load_trained_model(tmp_path: Path):
    """TrainedModel nesnesinin diske kaydedilip yüklenmesi testi."""
    save_file = tmp_path / "trained_model.pkl"
    tm = TrainedModel(
        model=None,
        feature_names=["f1", "f2"],
        train_samples=100,
        validation_score=0.85,
    )
    tm.save(save_file)
    assert save_file.exists()

    loaded = TrainedModel.load(save_file)
    assert loaded.feature_names == ["f1", "f2"]
    assert loaded.train_samples == 100


def test_duckdb_wal_save_and_polars_read(tmp_path: Path):
    """DuckDB WAL korumalı denetim izi kaydı ve Polars ile okuma testi."""
    db_file = tmp_path / "test_trainer_audit.duckdb"
    cfg = MLModelConfig(duckdb_path=str(db_file))
    trainer = LightGBMTrainer(config=cfg)

    # Denetim kaydı tetikle
    trainer._record_audit(
        train_samples=150,
        val_samples=30,
        features_count=10,
        val_score=0.045,
        ic=0.12,
        dir_acc=0.62,
        confidence=0.75,
        target_horizon=5,
        regime="NORMAL",
    )

    df_audit = trainer.get_audit_as_polars()
    assert isinstance(df_audit, pl.DataFrame)
    assert df_audit.height >= 1
    assert df_audit["train_samples"][0] == 150
    assert df_audit["ic"][0] == 0.12


def test_thread_safety_lightgbm_trainer():
    """Çoklu iş parçacığı altında kilit testi."""
    trainer = LightGBMTrainer()
    errors = []

    def worker():
        try:
            with trainer._lock:
                assert trainer._config.learning_rate > 0
        except Exception as exc:
            errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(errors) == 0
