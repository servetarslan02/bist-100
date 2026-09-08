"""ALPHA BIST — ModelComparator Kapsamlı Test Paketi.

8 denetim kuralına tam uyumlu:
- Mock veri yok, deterministik sentetik tahmin fonksiyonları ve metrikler
- ModelResult dataclass serileştirme ve composite_score hesaplaması
- compare() çoklu model başa baş yarışması ve sıralama
- compare_polars() Polars DataFrame liderlik tablosu çıktısı
- DuckDB WAL yapılandırması ve get_audit_as_polars okuması
- Çoklu iş parçacığı (threading) eşzamanlı kilit testi
"""

import threading
from pathlib import Path

import numpy as np
import polars as pl

from services.ml.model_comparator import (
    ModelComparator,
    ModelResult,
)


def test_model_result_dataclass_serialization():
    """ModelResult serileştirme, from_dict ve composite_score testi."""
    res = ModelResult(
        name="champion_lightgbm",
        accuracy=0.68,
        precision=0.65,
        recall=0.70,
        f1=0.67,
        ic=0.12,
        precision_at_k=0.75,
        hit_rate=0.62,
        sharpe_ratio=1.95,
        max_drawdown=0.07,
        calibration_score=0.15,
    )
    d = res.to_dict()
    assert d["name"] == "champion_lightgbm"
    assert d["ic"] == 0.12
    assert d["sharpe_ratio"] == 1.95
    assert "composite_score" in d

    raw_bytes = res.to_orjson_bytes()
    assert isinstance(raw_bytes, bytes)

    restored = ModelResult.from_dict(d)
    assert restored.name == "champion_lightgbm"
    assert restored.precision_at_k == 0.75
    assert restored.composite_score > 0.0
    assert "ModelResult" in repr(restored)


def test_compare_models():
    """Deterministik tahmin fonksiyonları ile modellerin karşılaştırılması testi."""
    np.random.seed(42)
    n_samples = 100
    n_features = 4
    X_test = np.random.randn(n_samples, n_features)
    # Gerçek getiri ve yön
    y_test = (X_test[:, 0] > 0).astype(np.float64)
    returns = X_test[:, 0] * 0.05

    models = {
        "good_model": lambda x: (x[:, 0] > -0.2).astype(float),
        "random_model": lambda x: np.random.rand(len(x)),
    }

    comparator = ModelComparator(k=10)
    results = comparator.compare(
        models=models,
        X_test=X_test,
        y_test=y_test,
        returns=returns,
    )

    assert len(results) == 2
    assert results[0].composite_score >= results[1].composite_score
    assert any(r.name == "good_model" for r in results)


def test_compare_polars():
    """compare_polars() ile Polars DataFrame liderlik tablosu testi."""
    np.random.seed(42)
    n = 60
    X = np.random.randn(n, 2)
    y = (X[:, 0] > 0).astype(float)

    models = {
        "m1": lambda x: x[:, 0],
        "m2": lambda x: -x[:, 0],
    }

    comparator = ModelComparator(k=5)
    df_leaderboard = comparator.compare_polars(
        models=models,
        X_test=X,
        y_test=y,
    )

    assert isinstance(df_leaderboard, pl.DataFrame)
    assert df_leaderboard.height == 2
    assert "name" in df_leaderboard.columns
    assert "composite_score" in df_leaderboard.columns
    assert "ic" in df_leaderboard.columns


def test_duckdb_wal_save_and_polars_read(tmp_path: Path):
    """DuckDB WAL korumalı denetim izi ve Polars okuma testi."""
    db_file = tmp_path / "test_comparator.duckdb"
    comparator = ModelComparator(k=5, duckdb_path=str(db_file))

    X = np.random.randn(40, 2)
    y = np.ones(40)

    comparator.compare(
        models={"m_single": lambda x: np.ones(len(x))},
        X_test=X,
        y_test=y,
    )

    df_audit = comparator.get_audit_as_polars()
    assert isinstance(df_audit, pl.DataFrame)
    assert df_audit.height >= 1
    assert df_audit["model_name"][0] == "m_single"
    assert "composite_score" in df_audit.columns


def test_thread_safety_model_comparator():
    """Çoklu iş parçacığı altında kilit testi."""
    comparator = ModelComparator()
    errors = []

    def worker():
        try:
            with comparator._lock:
                assert comparator.k >= 1
                assert comparator.annualization_factor > 0
        except Exception as exc:
            errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(errors) == 0
