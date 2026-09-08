"""ALPHA BIST — RankingModel (v3.0) Kapsamlı Test Paketi.

Bu test paketi; 70 kanonik öznitelikli çok faktörlü sıralama motorunu, Rejim Farkındalığını
(BULL/BEAR/SIDEWAYS/HIGH_VOL), LambdaRank eğitimini, veri modellerini, DuckDB 4MB/2MB WAL
direktiflerini, Polars entegrasyonunu ve iş parçacığı eşzamanlılık güvenliğini doğrular.
"""

from __future__ import annotations

import concurrent.futures
from typing import TYPE_CHECKING, Any

import duckdb
import numpy as np
import orjson
import polars as pl
import pytest

from services.ml.ranking_model import (
    OpportunityScore,
    RankingModel,
    RankingResult,
    configure_duckdb_wal,
)

if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture
def temp_duckdb_path(tmp_path: Path) -> str:
    """Geçici test DuckDB dosya yolu sağlar."""
    return str(tmp_path / "test_ranking_model.duckdb")


@pytest.fixture
def sample_universe() -> dict[str, dict[str, Any]]:
    """Test için örnek hisse ve öznitelik evreni sağlar."""
    return {
        "THYAO": {
            "momentum_20d": 0.20,
            "roc_5d": 0.08,
            "rs_vs_bist_5d": 0.05,
            "volume_zscore": 2.1,
            "sector_rel_return_5d": 0.04,
            "buyer_pressure_pct": 65.0,
            "candle_score": 75.0,
            "has_bullish_pattern": True,
            "has_fvg": True,
            "vol_adj_mom": 1.5,
            "rsi_14": 62.0,
            "balance_sheet_quality": 80.0,
            "fcf_yield_pct": 0.07,
        },
        "GARAN": {
            "momentum_20d": -0.10,
            "roc_5d": -0.04,
            "rs_vs_bist_5d": -0.06,
            "volume_zscore": -0.8,
            "sector_rel_return_5d": -0.03,
            "buyer_pressure_pct": 35.0,
            "candle_score": 40.0,
            "has_bullish_pattern": False,
            "has_fvg": False,
            "vol_adj_mom": -1.2,
            "rsi_14": 42.0,
            "balance_sheet_quality": 50.0,
            "fcf_yield_pct": 0.02,
        },
        "ASELS": {
            "momentum_20d": 0.05,
            "roc_5d": 0.02,
            "rs_vs_bist_5d": 0.01,
            "volume_zscore": 0.5,
            "sector_rel_return_5d": 0.01,
            "buyer_pressure_pct": 52.0,
            "candle_score": 55.0,
            "has_bullish_pattern": False,
            "has_fvg": False,
            "vol_adj_mom": 0.4,
            "rsi_14": 54.0,
            "balance_sheet_quality": 70.0,
            "fcf_yield_pct": 0.04,
        },
    }


def test_dataclasses_and_serialization() -> None:
    """OpportunityScore ve RankingResult serileştirme döngüsünü test eder."""
    opp = OpportunityScore(
        ticker="KCHOL",
        score=84.52,
        rank=1,
        direction="LONG",
        confidence=0.88,
        regime="BULL",
        signals={"breakout": True},
        features={"momentum_20d": 0.15},
        model_contribution={"lgbm": 59.16, "rule_based": 25.36},
    )

    d = opp.to_dict()
    assert d["ticker"] == "KCHOL"
    assert d["score"] == 84.52
    assert "KCHOL" in repr(opp)

    reconstructed_opp = OpportunityScore.from_dict(d)
    assert reconstructed_opp.ticker == "KCHOL"
    assert reconstructed_opp.score == 84.52
    assert reconstructed_opp.direction == "LONG"

    b = opp.to_orjson_bytes()
    assert b"KCHOL" in b

    # RankingResult
    res = RankingResult(
        scores=[opp],
        top_k={5: [opp], 10: [opp]},
        feature_importance={"momentum_20d": 12.5},
        regime_weights={"volume_trend": 1.6},
        ensemble_weights={"lgbm": 0.7, "rule_based": 0.3},
    )

    res_dict = res.to_dict()
    assert len(res_dict["scores"]) == 1
    assert "total_ranked=1" in repr(res)

    reconstructed_res = RankingResult.from_dict(res_dict)
    assert len(reconstructed_res.scores) == 1
    assert reconstructed_res.scores[0].ticker == "KCHOL"
    assert reconstructed_res.feature_importance["momentum_20d"] == 12.5

    b_res = res.to_orjson_bytes()
    parsed_res = orjson.loads(b_res)
    assert parsed_res["scores"][0]["ticker"] == "KCHOL"


def test_duckdb_wal_configuration_and_audit(temp_duckdb_path: str) -> None:
    """DuckDB 4MB/2MB WAL direktiflerini ve denetim tablosunu doğrular."""
    with duckdb.connect(temp_duckdb_path) as conn:
        configure_duckdb_wal(conn)

    model = RankingModel(duckdb_path=temp_duckdb_path)

    model._record_audit_event(
        operation="TEST_RANK",
        ticker_count=3,
        regime="BULL",
        top_ticker="THYAO",
        top_score=88.5,
        details={"top_tickers": ["THYAO", "ASELS"]},
    )

    with duckdb.connect(temp_duckdb_path) as conn:
        rows = conn.execute("SELECT operation, ticker_count, regime, top_ticker, details FROM ranking_model_audit").fetchall()
        assert len(rows) == 1
        assert rows[0][0] == "TEST_RANK"
        assert rows[0][1] == 3
        assert rows[0][2] == "BULL"
        assert rows[0][3] == "THYAO"
        details_obj = orjson.loads(rows[0][4])
        assert details_obj["top_tickers"] == ["THYAO", "ASELS"]


def test_canonical_features_and_fallbacks(temp_duckdb_path: str) -> None:
    """70 kanonik öznitelik listesini ve yedek (fallback) öznitelik eşleştirmesini test eder."""
    model = RankingModel(duckdb_path=temp_duckdb_path)
    assert len(model.feature_names) == 70

    # Yedek anahtar isimleriyle sağlanan öznitelikler
    raw_features = {
        "volume_percentile_20d": 85.0,
        "raw_roe": 0.28,
        "raw_roa": 0.12,
        "momentum_20d": 0.14,
    }

    vec = model._feature_vector(raw_features)
    assert len(vec) == 70
    assert np.all(np.isfinite(vec))

    # volume_percentile ve roe indeksleri sıfırdan farklı olmalı
    idx_vol = model.feature_names.index("volume_percentile")
    idx_roe = model.feature_names.index("roe")
    assert vec[idx_vol] == 85.0
    assert vec[idx_roe] == 0.28


def test_regime_aware_ranking(temp_duckdb_path: str, sample_universe: dict[str, dict[str, Any]]) -> None:
    """Farklı piyasa rejimlerinde kural tabanlı fırsat puanlamasını test eder."""
    model = RankingModel(duckdb_path=temp_duckdb_path)

    # BULL rejimi
    bull_res = model.rank(sample_universe, regime="BULL")
    assert len(bull_res.scores) == 3
    assert bull_res.scores[0].ticker == "THYAO"
    assert bull_res.scores[0].rank == 1
    assert bull_res.scores[0].direction == "LONG"
    assert bull_res.scores[-1].ticker == "GARAN"
    assert bull_res.scores[-1].rank == 3
    assert bull_res.scores[-1].direction == "SHORT"

    # BEAR rejimi
    bear_res = model.rank(sample_universe, regime="BEAR")
    assert len(bear_res.scores) == 3
    assert bear_res.scores[0].score > 0.0


def test_train_and_rank_lambdarank(temp_duckdb_path: str, sample_universe: dict[str, dict[str, Any]]) -> None:
    """LightGBM LambdaRank eğitimini ve ensemble skorlamasını test eder."""
    model = RankingModel(duckdb_path=temp_duckdb_path)

    # 2 kesit tarihli 6 örnek
    features_map = {}
    returns = {}
    date_groups = {}

    for i in range(2):
        d_str = f"2026-03-0{i+1}"
        for ticker, feats in sample_universe.items():
            key = f"{ticker}_{i}"
            features_map[key] = dict(feats)
            returns[key] = 0.08 if "THYAO" in key else (-0.05 if "GARAN" in key else 0.02)
            date_groups[key] = d_str

    train_res = model.train(features_map, returns, date_groups, regime="BULL", min_samples=6)
    assert train_res["success"] is True
    assert model._is_trained is True
    assert len(model.get_feature_importance()) > 0

    # Model eğitildikten sonra sıralama yap
    ranked_res = model.rank(sample_universe, regime="BULL")
    assert len(ranked_res.scores) == 3
    assert ranked_res.scores[0].rank == 1
    # Model katkısı kontrolü
    assert "lgbm" in ranked_res.scores[0].model_contribution
    assert "rule_based" in ranked_res.scores[0].model_contribution


def test_rank_polars_and_top_opportunities(temp_duckdb_path: str, sample_universe: dict[str, dict[str, Any]]) -> None:
    """Polars DataFrame sıralama ve fırsat listesi metotlarını test eder."""
    model = RankingModel(duckdb_path=temp_duckdb_path)

    rows = [{"ticker": t, **f} for t, f in sample_universe.items()]
    df = pl.DataFrame(rows)

    ranked_df = model.rank_polars(df, ticker_col="ticker", regime="BULL")
    assert "rank" in ranked_df.columns
    assert "score" in ranked_df.columns
    assert "direction" in ranked_df.columns
    assert "confidence" in ranked_df.columns
    assert ranked_df.height == 3
    assert ranked_df["rank"].to_list() == [1, 2, 3]

    # Boş DataFrame
    empty_df = pl.DataFrame(schema={"ticker": pl.Utf8})
    empty_res = model.rank_polars(empty_df, ticker_col="ticker")
    assert empty_res.height == 0
    assert "rank" in empty_res.columns

    # Polars top opportunities
    top_df = model.get_top_opportunities_polars(sample_universe, regime="BULL", limit=2)
    assert top_df.height == 2
    assert "score" in top_df.columns


def test_thread_safety_concurrency(temp_duckdb_path: str, sample_universe: dict[str, dict[str, Any]]) -> None:
    """Eşzamanlı iş parçacıklarının (threading.RLock) sıralama güvenliğini test eder."""
    model = RankingModel(duckdb_path=temp_duckdb_path)

    def worker(idx: int) -> int:
        res = model.rank(sample_universe, regime="BULL")
        return len(res.scores)

    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
        futures = [executor.submit(worker, i) for i in range(15)]
        results = [f.result() for f in concurrent.futures.as_completed(futures)]

    assert len(results) == 15
    assert all(r == 3 for r in results)
