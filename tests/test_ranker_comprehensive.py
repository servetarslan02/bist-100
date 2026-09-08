"""ALPHA BIST — LearningToRankModel & Ranker Kapsamlı Test Paketi.

Bu test paketi; LightGBM LambdaRank sıralama motorunu, veri modellerini, DuckDB WAL
denetim izini, Polars entegrasyonunu, kural tabanlı fallback mekanizmasını ve
iş parçacığı eşzamanlılık güvenliğini doğrular.
"""

from __future__ import annotations

import concurrent.futures
from typing import TYPE_CHECKING, Any

import duckdb
import numpy as np
import orjson
import polars as pl
import pytest

from services.ml.ranker import (
    LearningToRankModel,
    RankDirection,
    RankerTrainResult,
    RankItem,
    configure_duckdb_wal,
)

if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture
def temp_duckdb_path(tmp_path: Path) -> str:
    """Geçici test DuckDB dosya yolu sağlar."""
    return str(tmp_path / "test_ranker.duckdb")


@pytest.fixture
def sample_features_map() -> dict[str, dict[str, Any]]:
    """Örnek hisse öznitelik sözlüğü oluşturur."""
    return {
        "THYAO": {
            "momentum_20d": 0.15,
            "roc_5d": 0.08,
            "volume_zscore": 1.5,
            "momentum_20d_sector_zscore": 1.2,
            "fundamental_score": 0.85,
            "sentiment_score": 0.70,
            "rsi_14": 62.0,
        },
        "GARAN": {
            "momentum_20d": -0.05,
            "roc_5d": -0.02,
            "volume_zscore": -0.5,
            "momentum_20d_sector_zscore": -0.8,
            "fundamental_score": 0.60,
            "sentiment_score": -0.20,
            "rsi_14": 45.0,
        },
        "ASELS": {
            "momentum_20d": 0.05,
            "roc_5d": 0.03,
            "volume_zscore": 0.2,
            "momentum_20d_sector_zscore": 0.3,
            "fundamental_score": 0.75,
            "sentiment_score": 0.40,
            "rsi_14": 55.0,
        },
    }


def test_dataclasses_and_serialization() -> None:
    """RankItem ve RankerTrainResult serileştirme ve tip dönüşümlerini test eder."""
    item = RankItem(ticker="EREGL", rank=1, score=0.8523, direction=RankDirection.LONG.value)
    d = item.to_dict()
    assert d["ticker"] == "EREGL"
    assert d["rank"] == 1
    assert "score" in d
    assert "EREGL" in repr(item)

    # from_dict & orjson
    reconstructed = RankItem.from_dict(d)
    assert reconstructed.ticker == item.ticker
    assert reconstructed.rank == item.rank
    assert reconstructed.score == item.score

    b = item.to_orjson_bytes()
    parsed = orjson.loads(b)
    assert parsed["ticker"] == "EREGL"

    # RankerTrainResult
    res = RankerTrainResult(
        success=True,
        samples=150,
        groups=10,
        feature_importance={"momentum_20d": 45.0, "roc_5d": 30.0},
    )
    res_dict = res.to_dict()
    assert res_dict["success"] is True
    assert res_dict["samples"] == 150
    assert "RankerTrainResult" in repr(res)

    res_rec = RankerTrainResult.from_dict(res_dict)
    assert res_rec.success is True
    assert res_rec.samples == 150
    assert res_rec.feature_importance["momentum_20d"] == 45.0

    res_bytes = res.to_orjson_bytes()
    parsed_res = orjson.loads(res_bytes)
    assert parsed_res["samples"] == 150


def test_duckdb_wal_configuration_and_audit(temp_duckdb_path: str) -> None:
    """DuckDB 4MB/2MB WAL direktiflerini ve denetim izi tablosunu test eder."""
    with duckdb.connect(temp_duckdb_path) as conn:
        configure_duckdb_wal(conn)

    model = LearningToRankModel(duckdb_path=temp_duckdb_path)

    # Denetim olayı kaydet
    model._record_audit_event(
        operation="TEST_OP",
        samples=10,
        group_count=2,
        top_ticker="THYAO",
        top_score=0.99,
        details={"test_key": "test_val"},
    )

    with duckdb.connect(temp_duckdb_path) as conn:
        rows = conn.execute("SELECT operation, top_ticker, details FROM ranker_audit").fetchall()
        assert len(rows) == 1
        assert rows[0][0] == "TEST_OP"
        assert rows[0][1] == "THYAO"
        details_loaded = orjson.loads(rows[0][2])
        assert details_loaded["test_key"] == "test_val"


def test_prepare_training_data(temp_duckdb_path: str, sample_features_map: dict[str, dict[str, Any]]) -> None:
    """Kesitsel tarih gruplaması ve eksik/hatalı değer korumasını test eder."""
    model = LearningToRankModel(duckdb_path=temp_duckdb_path)

    # NaN, None ve string değer içeren veriler
    features = dict(sample_features_map)
    features["CORRUPT"] = {
        "momentum_20d": float("nan"),
        "roc_5d": None,
        "volume_zscore": "invalid_string",
    }

    returns = {
        "THYAO": 0.05,
        "GARAN": -0.02,
        "ASELS": 0.03,
        "CORRUPT": float("inf"),
    }

    date_groups = {
        "THYAO": "2026-03-01",
        "GARAN": "2026-03-01",
        "ASELS": "2026-03-02",
        "CORRUPT": "2026-03-02",
    }

    X, y, groups = model.prepare_training_data(features, returns, date_groups)
    assert len(X) == 4
    assert len(y) == 4
    assert len(groups) == 2
    assert sum(groups) == 4
    assert np.all(np.isfinite(X))
    assert np.all(np.isfinite(y))


def test_train_and_rank_with_lightgbm(temp_duckdb_path: str) -> None:
    """LightGBM LambdaRank eğitimini ve model tahminli sıralamayı test eder."""
    model = LearningToRankModel(
        feature_names=["momentum_20d", "roc_5d", "volume_zscore"],
        duckdb_path=temp_duckdb_path,
    )

    # 2 grup, toplam 6 örnek
    X = np.array(
        [
            [0.10, 0.05, 1.2],
            [0.02, 0.01, 0.0],
            [-0.05, -0.02, -1.0],
            [0.20, 0.10, 2.0],
            [0.05, 0.02, 0.5],
            [-0.10, -0.05, -1.5],
        ],
        dtype=np.float64,
    )
    y = np.array([0.08, 0.02, -0.04, 0.15, 0.04, -0.08], dtype=np.float64)
    groups = np.array([3, 3], dtype=np.int32)

    result = model.train_result(X, y, groups)
    assert result.success is True
    assert result.samples == 6
    assert result.groups == 2
    assert repr(model).startswith("LearningToRankModel(is_trained=True")

    # Model öznitelik önemini döndürmeli
    importances = model.get_feature_importance()
    assert len(importances) > 0

    # Sıralama yap
    query_features = {
        "HIGH_MOM": {"momentum_20d": 0.25, "roc_5d": 0.12, "volume_zscore": 2.1},
        "LOW_MOM": {"momentum_20d": -0.15, "roc_5d": -0.08, "volume_zscore": -1.8},
    }
    ranked = model.rank(query_features)
    assert len(ranked) == 2
    assert ranked[0]["rank"] == 1
    assert ranked[1]["rank"] == 2
    assert ranked[0]["direction"] in (RankDirection.LONG.value, RankDirection.SHORT.value)

    # Rank objects
    rank_objs = model.rank_objects(query_features)
    assert len(rank_objs) == 2
    assert isinstance(rank_objs[0], RankItem)


def test_fallback_rank_untrained(temp_duckdb_path: str, sample_features_map: dict[str, dict[str, Any]]) -> None:
    """Eğitilmemiş model durumunda kural tabanlı çok faktörlü fallback sıralamasını test eder."""
    model = LearningToRankModel(duckdb_path=temp_duckdb_path)
    assert model._is_trained is False

    ranked = model.rank(sample_features_map)
    assert len(ranked) == 3

    # En yüksek momentum ve roc THYAO'da
    assert ranked[0]["ticker"] == "THYAO"
    assert ranked[0]["rank"] == 1
    assert ranked[0]["direction"] == RankDirection.LONG.value

    # En düşük getiri GARAN'da
    assert ranked[-1]["ticker"] == "GARAN"
    assert ranked[-1]["rank"] == 3
    assert ranked[-1]["direction"] == RankDirection.SHORT.value


def test_rank_polars(temp_duckdb_path: str, sample_features_map: dict[str, dict[str, Any]]) -> None:
    """Polars DataFrame ile sıralama, boş veri ve null korumasını test eder."""
    model = LearningToRankModel(duckdb_path=temp_duckdb_path)

    # Normal Polars DataFrame
    rows = []
    for ticker, feats in sample_features_map.items():
        row = {"ticker": ticker, **feats}
        rows.append(row)
    df = pl.DataFrame(rows)

    res_df = model.rank_polars(df, ticker_col="ticker")
    assert "rank" in res_df.columns
    assert "score" in res_df.columns
    assert "direction" in res_df.columns
    assert res_df.height == 3
    assert res_df["rank"].to_list() == [1, 2, 3]

    # Boş Polars DataFrame
    empty_df = pl.DataFrame(schema={"ticker": pl.Utf8, "momentum_20d": pl.Float64})
    empty_res = model.rank_polars(empty_df, ticker_col="ticker")
    assert empty_res.height == 0
    assert "rank" in empty_res.columns

    # Ticker sütunu olmayan DataFrame
    no_ticker_df = pl.DataFrame({"feature1": [1.0, 2.0]})
    no_ticker_res = model.rank_polars(no_ticker_df, ticker_col="ticker")
    assert no_ticker_res.height == 2


def test_thread_safety_concurrency(temp_duckdb_path: str, sample_features_map: dict[str, dict[str, Any]]) -> None:
    """Eşzamanlı iş parçacıklarının (threading.RLock) güvenliğini test eder."""
    model = LearningToRankModel(duckdb_path=temp_duckdb_path)

    def worker_task(idx: int) -> int:
        ranked = model.rank(sample_features_map)
        return len(ranked)

    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
        futures = [executor.submit(worker_task, i) for i in range(15)]
        results = [f.result() for f in concurrent.futures.as_completed(futures)]

    assert len(results) == 15
    assert all(r == 3 for r in results)
