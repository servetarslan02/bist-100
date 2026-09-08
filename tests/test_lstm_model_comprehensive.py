"""ALPHA BIST — StockLSTM Kapsamlı Test Paketi.

8 denetim kuralına tam uyumlu:
- Mock veri yok, deterministik sentetik zaman serisi ve öznitelik matrisleri
- LSTMConfig ve LSTMTrainingResult dataclass serileştirme (to_dict, from_dict, orjson)
- AttentionLayer dikkat mekanizması ileri geçiş testi
- train() metodu ile kayar pencere üzerinde LSTM eğitimi
- predict() ve predict_polars() tahmin fonksiyonları
- save() ve load() model ağırlıklarının serileştirilmesi
- DuckDB WAL yapılandırması ve get_audit_as_polars okuması
- Çoklu iş parçacığı (threading) eşzamanlı kilit testi
"""

import threading
from pathlib import Path

import numpy as np
import polars as pl
import torch

from services.ml.lstm_model import (
    AttentionLayer,
    LSTMConfig,
    LSTMTrainingResult,
    StockLSTM,
)


def test_dataclasses_serialization():
    """LSTMConfig ve LSTMTrainingResult serileştirme ve from_dict testi."""
    cfg = LSTMConfig(
        input_size=10,
        hidden_size=32,
        num_layers=1,
        sequence_length=5,
        learning_rate=0.01,
        batch_size=16,
        epochs=2,
    )
    d = cfg.to_dict()
    assert d["input_size"] == 10
    assert d["hidden_size"] == 32
    assert isinstance(cfg.to_orjson_bytes(), bytes)

    restored_cfg = LSTMConfig.from_dict(d)
    assert restored_cfg.input_size == 10
    assert restored_cfg.hidden_size == 32
    assert "LSTMConfig" in repr(restored_cfg)

    res = LSTMTrainingResult(
        n_train=50,
        n_val=10,
        epochs_trained=2,
        best_train_loss=0.05,
        best_val_loss=0.06,
        val_rmse=0.24,
        val_ic=0.15,
        history=[{"epoch": 0, "train_loss": 0.08}],
    )
    r_dict = res.to_dict()
    assert r_dict["n_train"] == 50
    assert r_dict["val_ic"] == 0.15
    assert isinstance(res.to_orjson_bytes(), bytes)

    restored_res = LSTMTrainingResult.from_dict(r_dict)
    assert restored_res.n_train == 50
    assert restored_res.best_val_loss == 0.06
    assert "LSTMTrainingResult" in repr(restored_res)


def test_attention_layer_forward():
    """AttentionLayer tensor boyutları ve dikkat bağlam vektörü testi."""
    batch_size = 4
    seq_len = 5
    hidden_size = 16

    att = AttentionLayer(hidden_size=hidden_size)
    dummy_input = torch.randn(batch_size, seq_len, hidden_size)
    context = att(dummy_input)

    assert context.shape == (batch_size, hidden_size)
    assert torch.isfinite(context).all()


def test_lstm_train_and_predict():
    """Küçük sentetik zaman serisi ile StockLSTM eğitimi ve tahmini testi."""
    np.random.seed(42)
    n_samples = 60
    n_features = 4
    X = np.random.randn(n_samples, n_features).astype(np.float32)
    y = (X[:, 0] * 1.5 + np.random.randn(n_samples) * 0.1).astype(np.float32)

    cfg = LSTMConfig(
        input_size=n_features,
        hidden_size=16,
        num_layers=1,
        sequence_length=5,
        batch_size=8,
        epochs=2,
        early_stopping_patience=2,
        device="cpu",
    )
    model = StockLSTM(config=cfg)

    res = model.train(X_train=X[:45], y_train=y[:45], X_val=X[45:], y_val=y[45:])

    assert isinstance(res, LSTMTrainingResult)
    assert res.epochs_trained >= 1
    assert model.is_trained is True

    # Tahmin testi
    preds = model.predict(X[45:])
    assert isinstance(preds, np.ndarray)
    assert len(preds) > 0
    assert np.isfinite(preds).all()


def test_predict_polars():
    """predict_polars() ile Polars DataFrame sütun ekleme testi."""
    np.random.seed(42)
    n_samples = 50
    X = np.random.randn(n_samples, 2).astype(np.float32)
    y = np.random.randn(n_samples).astype(np.float32)

    cfg = LSTMConfig(
        input_size=2,
        hidden_size=8,
        num_layers=1,
        sequence_length=4,
        batch_size=8,
        epochs=1,
        device="cpu",
    )
    model = StockLSTM(config=cfg)
    model.train(X_train=X, y_train=y)

    df = pl.DataFrame({
        "feat_1": X[:, 0],
        "feat_2": X[:, 1],
    })
    res_df = model.predict_polars(df, feature_cols=["feat_1", "feat_2"])

    assert isinstance(res_df, pl.DataFrame)
    assert res_df.height == n_samples
    assert "lstm_prediction" in res_df.columns


def test_save_and_load_model(tmp_path: Path):
    """Model ağırlıklarının diske kaydedilip geri yüklenmesi testi."""
    save_file = tmp_path / "stock_lstm.pt"
    cfg = LSTMConfig(input_size=3, hidden_size=8, epochs=1, sequence_length=3, device="cpu")
    model = StockLSTM(config=cfg)

    X = np.random.randn(30, 3).astype(np.float32)
    y = np.random.randn(30).astype(np.float32)
    model.train(X, y)

    assert model.save(save_file) is True
    assert save_file.exists()

    new_model = StockLSTM()
    assert new_model.load(save_file) is True
    assert new_model.is_trained is True


def test_duckdb_wal_save_and_polars_read(tmp_path: Path):
    """DuckDB WAL denetim izi kaydı ve Polars okuma testi."""
    db_file = tmp_path / "test_lstm.duckdb"
    cfg = LSTMConfig(
        input_size=2,
        hidden_size=8,
        epochs=1,
        sequence_length=3,
        device="cpu",
        duckdb_path=str(db_file),
    )
    model = StockLSTM(config=cfg)

    X = np.random.randn(25, 2).astype(np.float32)
    y = np.random.randn(25).astype(np.float32)
    model.train(X, y)

    df_audit = model.get_audit_as_polars()
    assert isinstance(df_audit, pl.DataFrame)
    assert df_audit.height >= 1
    assert "best_train_loss" in df_audit.columns


def test_thread_safety_stock_lstm():
    """Çoklu iş parçacığı durumunda kilit mekanizması testi."""
    model = StockLSTM()
    errors = []

    def worker():
        try:
            with model._lock:
                assert model._config.batch_size > 0
                assert model.is_trained is False
        except Exception as exc:
            errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(errors) == 0
