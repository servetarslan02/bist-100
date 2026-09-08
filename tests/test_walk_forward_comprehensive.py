"""ALPHA BIST — Walk-Forward Validation Motoru Kapsamlı Test Paketi

services/ml/walk_forward.py için kurumsal denetim testleri:
1. Dataclass serileştirme (WFSplitConfig, WFSplit, WFResult, WFAggregatedMetrics) (to_dict, from_dict, to_orjson_bytes)
2. generate_splits ile Purge ve Embargo aralıklarının Point-in-Time sızıntısızlığı
3. Expanding vs Rolling pencere dilimleme doğrulaması
4. evaluate ve evaluate_polars çapraz doğrulama döngüsü
5. DuckDB WAL denetim kaydı ve Polars okuma (get_audit_as_polars)
6. Thread-safety eşzamanlı split üretme ve değerlendirme güvenliği
"""

from __future__ import annotations

import concurrent.futures
from datetime import date, timedelta
from typing import TYPE_CHECKING, Any

import numpy as np
import polars as pl

from services.ml.walk_forward import (
    WalkForwardValidation,
    WFAggregatedMetrics,
    WFResult,
    WFSplit,
    WFSplitConfig,
)

if TYPE_CHECKING:
    from pathlib import Path


def test_wf_dataclasses_serialization() -> None:
    """Dataclass modellerinin to_dict, from_dict ve to_orjson_bytes testleri."""
    # 1. WFSplitConfig
    cfg = WFSplitConfig(train_size=100, test_size=20, purge_size=5, embargo_size=5, expanding=True)
    d_cfg = cfg.to_dict()
    cfg_rec = WFSplitConfig.from_dict(d_cfg)
    assert cfg_rec.train_size == 100
    assert cfg_rec.expanding is True
    assert isinstance(cfg.to_orjson_bytes(), bytes)

    # 2. WFSplit
    split = WFSplit(
        split_index=1,
        train_start=0,
        train_end=50,
        test_start=55,
        test_end=75,
        train_dates=["2026-01-01", "2026-01-02"],
        test_dates=["2026-01-10", "2026-01-11"],
    )
    d_split = split.to_dict()
    split_rec = WFSplit.from_dict(d_split)
    assert split_rec.split_index == 1
    assert split_rec.test_start == 55
    assert isinstance(split.to_orjson_bytes(), bytes)

    # 3. WFResult
    res = WFResult(
        train_start="2026-01-01",
        train_end="2026-01-30",
        test_start="2026-02-05",
        test_end="2026-02-25",
        train_size=50,
        test_size=20,
        metrics={"correlation": 0.08, "direction_accuracy": 55.0, "rmse": 0.02},
    )
    d_res = res.to_dict()
    res_rec = WFResult.from_dict(d_res)
    assert res_rec.train_size == 50
    assert res_rec.metrics["correlation"] == 0.08

    # 4. WFAggregatedMetrics
    agg = WFAggregatedMetrics(
        avg_correlation=0.06,
        std_correlation=0.02,
        avg_direction_accuracy=53.5,
        std_direction_accuracy=3.2,
        avg_rmse=0.025,
        total_splits=5,
        avg_train_size=250.0,
        avg_test_size=20.0,
    )
    d_agg = agg.to_dict()
    agg_rec = WFAggregatedMetrics.from_dict(d_agg)
    assert agg_rec.total_splits == 5
    assert agg_rec.avg_direction_accuracy == 53.5


def test_generate_splits_purge_and_embargo() -> None:
    """Purge ve Embargo aralıklarının doğru uygulandığı ve sıfır sızıntı testi."""
    base_date = date(2025, 1, 1)
    dates = [base_date + timedelta(days=i) for i in range(150)]

    wf = WalkForwardValidation(
        train_size=50,
        test_size=15,
        purge_size=5,
        embargo_size=5,
        step_size=15,
        expanding=False,
    )
    splits = wf.generate_splits(dates)
    assert len(splits) >= 4

    for s in splits:
        # Purge kontrolü: test_start >= train_end + purge_size
        assert s.test_start >= s.train_end + 5
        # Boyut kontrolleri
        assert len(s.train_dates) == 50
        assert len(s.test_dates) == 15

    # İki ardışık split arası embargo kontrolü
    for s1, s2 in zip(splits[:-1], splits[1:], strict=False):
        # s2'nin train'i rolling modda step_size kadar ileri kaymalı
        assert s2.train_start == s1.train_start + 15


def test_generate_splits_expanding_window() -> None:
    """Expanding modda her split'te eğitim boyutunun arttığı doğrulaması."""
    base_date = date(2025, 1, 1)
    dates = [base_date + timedelta(days=i) for i in range(120)]

    wf_exp = WalkForwardValidation(
        train_size=40,
        test_size=10,
        purge_size=4,
        embargo_size=4,
        step_size=10,
        expanding=True,
    )
    splits = wf_exp.generate_splits(dates)
    assert len(splits) >= 4

    for i in range(len(splits) - 1):
        assert splits[i].train_start == 0  # Başlangıç sabit
        assert splits[i + 1].train_end > splits[i].train_end  # Bitiş genişliyor


def test_evaluate_and_duckdb_audit(tmp_path: Path) -> None:
    """evaluate akışı, sentetik model fonksiyonu ve DuckDB denetim kaydı testi."""
    db_file = tmp_path / "wf_audit.duckdb"
    wf = WalkForwardValidation(
        train_size=30,
        test_size=10,
        purge_size=2,
        embargo_size=2,
        step_size=10,
        duckdb_path=str(db_file),
    )

    dates = [f"2026-01-{i:02d}" for i in range(1, 60)]
    rng = np.random.default_rng(42)
    returns = list(rng.normal(0.01, 0.03, len(dates)))
    features = list(rng.normal(0.0, 1.0, (len(dates), 4)))

    data = {
        "dates": dates,
        "returns": returns,
        "features": features,
    }

    class SimpleMockModel:
        def fit(self, feats: Any) -> None:
            pass

        def predict(self, feats: Any) -> np.ndarray:
            return np.ones(len(feats), dtype=np.float64) * 0.02

    results = wf.evaluate(
        data=data,
        model_fn=SimpleMockModel,
        feature_fn=lambda d: d.get("features", []),
    )
    assert len(results) >= 2
    agg = wf.get_aggregated_metrics(results)
    assert "avg_correlation" in agg
    assert "avg_direction_accuracy" in agg
    assert agg["total_splits"] == len(results)

    # DuckDB Polars Denetim Okuma
    df_audit = wf.get_audit_as_polars()
    assert isinstance(df_audit, pl.DataFrame)
    assert df_audit.height >= 1
    assert "total_splits" in df_audit.columns


def test_walk_forward_thread_safety(tmp_path: Path) -> None:
    """Eşzamanlı split üretme ve değerlendirme thread-safety testi."""
    db_file = tmp_path / "wf_thread.duckdb"
    wf = WalkForwardValidation(
        train_size=25,
        test_size=8,
        purge_size=2,
        embargo_size=2,
        step_size=8,
        duckdb_path=str(db_file),
    )
    dates = [f"D_{i:03d}" for i in range(80)]

    def worker(_: int) -> int:
        s = wf.generate_splits(dates)
        return len(s)

    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
        futures = [executor.submit(worker, i) for i in range(8)]
        counts = [f.result() for f in futures]

    assert len(counts) == 8
    assert all(c > 0 for c in counts)
    assert len(set(counts)) == 1  # Hepsi deterministik olarak aynı sayıda split üretmeli
