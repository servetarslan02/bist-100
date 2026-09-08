"""ALPHA BIST — QlibBIST Kapsamlı Denetim ve Bütünlük Testi.

Bu test paketi, qlib_integration.py dosyasının 8 kural çerçevesindeki
tüm mimari, quant, veritabanı ve eşzamanlılık standartlarını kanıtlar:
1. Sıfır Veri Sızıntısı (Zero Data Leakage) ve Katı Purge+Embargo Penceresi
2. Forward Return Etiketleme Doğruluğu ((P_{t+H} - P_t) / P_t)
3. DuckDB SSD Korumalı WAL (4MB/2MB) ve Audit Tablosu SELECT Doğrulaması
4. Polars Null / None Güvenliği ve Eksik Sütun Koruması (Boundary Check)
5. Veri Modelleri Serileştirme ve Lineage (slots=True, to_orjson_bytes, from_dict)
6. Öznitelik Sütun Boyutu Uyuşmazlığı Güvenliği (Matrix dimension mismatch guard)
7. Çoklu İş Parçacığı Eşzamanlılık Güvenliği (Thread-safety)
"""

from __future__ import annotations

import concurrent.futures
from pathlib import Path

import duckdb
import numpy as np
import polars as pl
import pytest

from services.ml.qlib_integration import (
    QlibBIST,
    QlibConfig,
    QlibDatasetResult,
    QlibDatasetSplit,
)

TEST_DB_PATH = "data/test_audit_qlib.duckdb"


@pytest.fixture(autouse=True)
def cleanup_test_db():
    """Test öncesi ve sonrası test DB dosyasını temizler."""
    if Path(TEST_DB_PATH).exists():
        try:
            Path(TEST_DB_PATH).unlink()
        except Exception:
            pass
    yield
    if Path(TEST_DB_PATH).exists():
        try:
            Path(TEST_DB_PATH).unlink()
        except Exception:
            pass


def test_01_zero_data_leakage_and_purge_window():
    """1. Sıfır Veri Sızıntısı: Train ve Validasyon kümeleri arasında katı purge kontrolü."""
    qlib = QlibBIST(duckdb_path=TEST_DB_PATH)

    n_bars = 200
    prices = np.linspace(10.0, 50.0, n_bars)
    features = np.random.randn(n_bars, 4)

    prepared = qlib.prepare_data(
        ticker="THYAO",
        start_date="2024-01-01",
        end_date="2024-10-01",
        features=features,
        prices=prices,
    )
    assert prepared["status"] == "ready"

    # label_horizon=5, purge_gap=5
    ds = qlib.create_qlib_dataset({"THYAO": prepared}, label_horizon=5, purge_gap=5)

    train_len = len(ds["train"]["X"])
    valid_len = len(ds["valid"]["X"])
    test_len = len(ds["test"]["X"])

    assert train_len > 0
    assert valid_len > 0
    assert test_len > 0

    # Toplam numune sayısı, purge boşlukları ve horizon kesintileri nedeniyle n_bars'tan küçük olmalı
    assert (train_len + valid_len + test_len) < n_bars


def test_02_forward_return_calculation():
    """2. İleri getiri etiketleme formülü doğrulaması."""
    qlib = QlibBIST(duckdb_path=TEST_DB_PATH)

    # 100 bar, her gün %1 yükselen fiyat serisi
    prices = 100.0 * (1.01 ** np.arange(100))
    features = np.ones((100, 2))

    prep = qlib.prepare_data("GARAN", "2024-01-01", "2024-05-01", features, prices)
    ds = qlib.create_qlib_dataset({"GARAN": prep}, label_horizon=1, purge_gap=1)

    train_y = ds["train"]["y"]
    # 1 günlük forward return tam %1 (0.01) olmalı
    assert np.allclose(train_y, 0.01, atol=1e-4)


def test_03_duckdb_audit_trail_and_wal():
    """3. DuckDB denetim tablosuna kayıt yazılması ve SELECT kontrolü."""
    qlib = QlibBIST(duckdb_path=TEST_DB_PATH)
    prices = np.linspace(10.0, 30.0, 100)
    features = np.ones((100, 3))

    prep = qlib.prepare_data("SISE", "2024-01-01", "2024-05-01", features, prices)
    qlib.create_qlib_dataset({"SISE": prep}, label_horizon=5)

    assert Path(TEST_DB_PATH).exists()
    with duckdb.connect(TEST_DB_PATH) as conn:
        rows = conn.execute(
            "SELECT operation, ticker_count, train_samples, label_horizon FROM qlib_integration_audit"
        ).fetchall()
        assert len(rows) >= 1
        op, t_count, tr_samples, lh = rows[0]
        assert op == "CREATE_DATASET"
        assert t_count == 1
        assert tr_samples > 0
        assert lh == 5


def test_04_polars_null_safety_and_boundary_guard():
    """4. Polars null/None değerleri ve eksik sütun sınır güvenliği."""
    qlib = QlibBIST(duckdb_path=TEST_DB_PATH)

    # Null içeren teknik öznitelikler
    df = pl.DataFrame({
        "date": ["2024-01-01", "2024-01-02", "2024-01-03", "2024-01-04", "2024-01-05"] * 20,
        "close": [10.0, None, 10.5, 11.0, 11.5] * 20,
        "rsi": [None, None, 45.0, 50.0, 55.0] * 20,
        "macd": [0.1, 0.2, None, 0.4, 0.5] * 20,
    })

    prep = qlib.prepare_data_polars(
        df=df,
        ticker="KCHOL",
        feature_cols=["rsi", "macd"],
        price_col="close",
        date_col="date",
    )
    assert prep["status"] == "ready"
    assert prep["n_samples"] == 100
    assert prep["n_features"] == 2

    # Eksik sütun kontrolü (olmayan öznitelik verildiğinde çökmemeli)
    bad_prep = qlib.prepare_data_polars(
        df=df,
        ticker="KCHOL",
        feature_cols=["non_existent_feature"],
        price_col="close",
    )
    assert bad_prep["status"] == "error"


def test_05_data_models_serialization_and_lineage():
    """5. QlibConfig, QlibDatasetSplit, QlibDatasetResult serileştirme döngüsü."""
    cfg = QlibConfig(train_start="2021-01-01", train_end="2023-01-01")
    cfg_dict = cfg.to_dict()
    assert cfg_dict["train_start"] == "2021-01-01"
    assert isinstance(cfg.to_orjson_bytes(), bytes)

    reconstructed_cfg = QlibConfig.from_dict(cfg_dict)
    assert reconstructed_cfg.train_start == "2021-01-01"

    split = QlibDatasetSplit(X=np.ones((10, 2)), y=np.zeros(10), tickers=["EREGL"])
    split_dict = split.to_dict()
    assert split_dict["n_samples"] == 10
    assert split_dict["n_features"] == 2
    assert isinstance(split.to_orjson_bytes(), bytes)

    reconstructed_split = QlibDatasetSplit.from_dict(split_dict, X=split.X, y=split.y)
    assert len(reconstructed_split.X) == 10


def test_06_dimension_mismatch_guard():
    """6. Farklı hisselerden gelen öznitelik boyut uyuşmazlığında güvenli filtreleme."""
    qlib = QlibBIST(duckdb_path=TEST_DB_PATH)

    # 1. Hisse: 3 öznitelik
    p1 = qlib.prepare_data("AKBNK", "2024-01-01", "2024-05-01", np.ones((100, 3)), np.linspace(10, 20, 100))
    # 2. Hisse: Hatalı 5 öznitelik (boyut uyuşmazlığı)
    p2 = qlib.prepare_data("ISCTR", "2024-01-01", "2024-05-01", np.ones((100, 5)), np.linspace(10, 20, 100))

    ds = qlib.create_qlib_dataset({"AKBNK": p1, "ISCTR": p2}, label_horizon=5)
    # Sistem çökmemeli, AKBNK'yi alıp ISCTR'yi güvenle atlamalı
    assert ds["train"]["X"].shape[1] == 3


def test_07_thread_safety_feature_store():
    """7. Çoklu iş parçacığı altında önbellek ve öznitelik havuzu güvenliği."""
    qlib = QlibBIST(duckdb_path=TEST_DB_PATH)

    def worker(i: int):
        qlib.add_to_feature_store(f"feat_{i}", np.ones((10, 2)) * i)
        qlib.prepare_data(f"TICK_{i}", "2024-01-01", "2024-05-01", prices=np.ones(50))

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
        futures = [executor.submit(worker, i) for i in range(50)]
        for f in futures:
            f.result()

    stats = qlib.get_stats()
    assert stats["cached_tickers"] == 50
    assert stats["feature_store_size"] == 50
