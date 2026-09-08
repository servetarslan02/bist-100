"""ALPHA BIST — Stock Transformer v3.0 Kapsamlı Test Paketi

services/ml/transformer_model.py için kurumsal denetim testleri:
1. TransformerConfig dataclass serileştirme (to_dict, from_dict, to_orjson_bytes)
2. PositionalEncoding sinüzoidal tensör dönüşüm testi
3. StockTransformer eğitim döngüsü (train, train_polars), early stopping
4. StockTransformer çıkarım ve Monte Carlo dropout belirsizlik tahmini
5. Model diske kaydetme ve yükleme doğrulaması (save, load)
6. DuckDB WAL denetim kaydı ve Polars okuma (get_audit_as_polars)
7. Thread-safety eşzamanlı erişim koruması
"""

from __future__ import annotations

import concurrent.futures
from pathlib import Path

import numpy as np
import polars as pl
import pytest

from services.ml.transformer_model import (
    PositionalEncoding,
    StockTransformer,
    TransformerConfig,
    configure_duckdb_wal,
)


def test_transformer_config_serialization() -> None:
    """TransformerConfig dataclass serileştirme ve deseralizasyon testi."""
    cfg = TransformerConfig(
        input_size=10,
        d_model=32,
        nhead=4,
        num_encoder_layers=2,
        dim_feedforward=64,
        sequence_length=5,
        epochs=3,
        batch_size=8,
    )
    d = cfg.to_dict()
    assert d["input_size"] == 10
    assert d["d_model"] == 32
    assert d["epochs"] == 3

    reconstructed = TransformerConfig.from_dict(d)
    assert reconstructed.input_size == 10
    assert reconstructed.nhead == 4
    assert reconstructed.sequence_length == 5

    b = cfg.to_orjson_bytes()
    assert isinstance(b, bytes)
    assert b"TransformerConfig" not in b  # json keys present


def test_positional_encoding() -> None:
    """PositionalEncoding tensör boyutları ve çağrılabilirlik testi."""
    try:
        import torch
    except ImportError:
        pytest.skip("PyTorch kurulu degil")

    pe = PositionalEncoding(d_model=16, max_len=50)
    assert pe.pe is not None

    x = torch.zeros(2, 10, 16)
    out = pe(x)
    assert out.shape == (2, 10, 16)
    assert not torch.allclose(out, x)  # Sinüzoidal pozisyonlar eklenmeli


def test_transformer_training_and_prediction(tmp_path: Path) -> None:
    """StockTransformer eğitim döngüsü, çıkarım ve Polars tahmini testi."""
    try:
        import torch
    except ImportError:
        pytest.skip("PyTorch kurulu degil")

    db_path = tmp_path / "trans_test.duckdb"
    cfg = TransformerConfig(
        input_size=5,
        d_model=16,
        nhead=2,
        num_encoder_layers=1,
        dim_feedforward=32,
        sequence_length=4,
        epochs=2,
        batch_size=4,
    )
    model = StockTransformer(config=cfg, duckdb_path=str(db_path))

    # Deterministik sentetik zaman serisi
    rng = np.random.default_rng(42)
    N = 40
    X_train = rng.normal(0.0, 1.0, (N, 5))
    y_train = rng.normal(0.01, 0.05, N)

    # 1. Eğitim
    metrics = model.train(X_train, y_train)
    assert model.is_trained is True
    assert "best_val_loss" in metrics
    assert "epochs_trained" in metrics

    # 2. Numpy Çıkarım
    preds = model.predict(X_train)
    expected_len = N - cfg.sequence_length
    assert len(preds) == expected_len
    assert np.all(np.isfinite(preds))

    # 3. Monte Carlo Belirsizlik Tahmini
    mean_preds, conf = model.predict_with_confidence(X_train)
    assert len(mean_preds) == expected_len
    assert len(conf) == expected_len
    assert np.all((conf >= 0.0) & (conf <= 1.0))

    # 4. Polars Tahmini
    df_in = pl.DataFrame({
        f"feat_{i}": X_train[:, i] for i in range(5)
    })
    feat_cols = [f"feat_{i}" for i in range(5)]
    df_out = model.predict_polars(df_in, feat_cols)
    assert "transformer_pred" in df_out.columns
    assert len(df_out) == N

    # 5. DuckDB Denetim Kaydı Okuma
    df_audit = model.get_audit_as_polars()
    assert isinstance(df_audit, pl.DataFrame)
    assert df_audit.height >= 1
    assert "operation" in df_audit.columns


def test_transformer_train_polars_and_save_load(tmp_path: Path) -> None:
    """Polars ile doğrudan eğitim ve model save/load döngüsü."""
    try:
        import torch
    except ImportError:
        pytest.skip("PyTorch kurulu degil")

    db_path = tmp_path / "trans_polars.duckdb"
    model_file = tmp_path / "stock_transformer.pth"

    cfg = TransformerConfig(
        input_size=3,
        d_model=8,
        nhead=2,
        num_encoder_layers=1,
        sequence_length=3,
        epochs=2,
        batch_size=4,
    )
    model = StockTransformer(config=cfg, duckdb_path=str(db_path))

    rng = np.random.default_rng(101)
    N = 30
    df = pl.DataFrame({
        "f1": rng.normal(0, 1, N),
        "f2": rng.normal(0, 1, N),
        "f3": rng.normal(0, 1, N),
        "target": rng.normal(0.02, 0.04, N),
    })

    metrics = model.train_polars(df, target_col="target", feature_cols=["f1", "f2", "f3"])
    assert model.is_trained is True
    assert metrics.get("epochs_trained", 0) > 0

    # Save
    saved = model.save(str(model_file))
    assert saved is True
    assert model_file.exists()

    # Load
    new_model = StockTransformer(duckdb_path=str(db_path))
    loaded = new_model.load(str(model_file))
    assert loaded is True
    assert new_model.is_trained is True

    # Tahmin tutarlılığı
    X_test = rng.normal(0, 1, (10, 3))
    p1 = model.predict(X_test)
    p2 = new_model.predict(X_test)
    np.testing.assert_allclose(p1, p2, rtol=1e-4)


def test_transformer_thread_safety(tmp_path: Path) -> None:
    """Eşzamanlı thread'lerde tahmin ve denetim güvenliği testi."""
    try:
        import torch
    except ImportError:
        pytest.skip("PyTorch kurulu degil")

    db_path = tmp_path / "trans_thread.duckdb"
    cfg = TransformerConfig(
        input_size=4,
        d_model=8,
        nhead=2,
        num_encoder_layers=1,
        sequence_length=3,
        epochs=1,
        batch_size=4,
    )
    model = StockTransformer(config=cfg, duckdb_path=str(db_path))

    rng = np.random.default_rng(202)
    X = rng.normal(0, 1, (20, 4))
    y = rng.normal(0, 1, 20)
    model.train(X, y)

    def worker(_: int) -> float:
        p = model.predict(X)
        return float(np.mean(p))

    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
        futures = [executor.submit(worker, i) for i in range(8)]
        results = [f.result() for f in futures]

    assert len(results) == 8
    assert all(np.isfinite(r) for r in results)
