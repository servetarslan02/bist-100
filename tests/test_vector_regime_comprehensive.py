"""ALPHA BIST — Vector Regime v3.0 Kapsamlı Test Paketi

services/ml/vector_regime.py için kurumsal denetim testleri:
1. Dataclass serileştirme (RegimeVector, AnalogyMatch, RegimeProtectionAdvice) (to_dict, from_dict, to_orjson_bytes)
2. vectorize_market_state ve vectorize_polars 16-boyutlu normalizasyon
3. Tarihsel kriz tohum kütüphanesi ve find_nearest_analogies (Cosine / L2)
4. Portföy koruma tavsiyesi (get_regime_protection_advice)
5. 1. derece Markov rejim geçiş matrisi hesaplama (compute_transition_matrix)
6. Yeni rejim vektörü ekleme ve DuckDB WAL Polars okuma (get_stored_vectors_as_polars)
7. Thread-safety eşzamanlı sorgulama güvenliği
"""

from __future__ import annotations

import concurrent.futures
from typing import TYPE_CHECKING

import numpy as np
import polars as pl

from services.ml.vector_regime import (
    FEATURE_DIM,
    AnalogyMatch,
    MarketRegimeEmbeddingEngine,
    RegimeProtectionAdvice,
    RegimeVector,
)

if TYPE_CHECKING:
    from pathlib import Path


def test_regime_dataclasses_serialization() -> None:
    """Dataclass modellerinin to_dict, from_dict ve to_orjson_bytes doğrulaması."""
    # 1. RegimeVector
    vec = np.ones(16, dtype=np.float32) * 0.25
    rv = RegimeVector(
        date="2026-02-23",
        vector=vec,
        regime_name="BULL_TREND",
        metadata={"subsequent_1m_return": 0.08},
    )
    d_rv = rv.to_dict()
    assert d_rv["regime_name"] == "BULL_TREND"
    assert len(d_rv["vector"]) == 16

    rv_rec = RegimeVector.from_dict(d_rv)
    assert rv_rec.date == "2026-02-23"
    assert len(rv_rec.vector) == 16
    assert isinstance(rv.to_orjson_bytes(), bytes)

    # 2. AnalogyMatch
    match = AnalogyMatch(
        historical_date="2020-03-20",
        historical_regime="2020_COVID_SHOCK",
        similarity_score=0.945,
        distance_l2=0.33,
        description="Pandemi kriz soku",
        subsequent_1m_return=0.12,
    )
    d_m = match.to_dict()
    match_rec = AnalogyMatch.from_dict(d_m)
    assert match_rec.similarity_score == 0.945
    assert match_rec.historical_date == "2020-03-20"
    assert isinstance(match.to_orjson_bytes(), bytes)

    # 3. RegimeProtectionAdvice
    adv = RegimeProtectionAdvice(
        detected_analogy="2020_COVID_SHOCK",
        similarity=0.945,
        recommended_cash_pct=30.0,
        risk_multiplier=0.6,
        strategy="DEFENSIVE_HIGH_CASH",
        reasoning="Kriz benzerligi yuksek",
    )
    d_adv = adv.to_dict()
    adv_rec = RegimeProtectionAdvice.from_dict(d_adv)
    assert adv_rec.recommended_cash_pct == 30.0
    assert adv_rec.strategy == "DEFENSIVE_HIGH_CASH"
    assert isinstance(adv.to_orjson_bytes(), bytes)


def test_vectorize_market_state_and_polars(tmp_path: Path) -> None:
    """Numpy ve Polars üzerinden 16 boyutlu durum vektörü üretimi ve norm testi."""
    db_file = tmp_path / "vec_regime.duckdb"
    engine = MarketRegimeEmbeddingEngine(duckdb_path=str(db_file))

    # Numpy üretimi
    v = engine.vectorize_market_state(
        bist_return_20d=0.05,
        bist_volatility_20d=0.22,
        usdtry_change_20d=0.01,
        cds_5y_level=280.0,
        vix_level=16.5,
        advance_decline_ratio=1.4,
        foreign_flow_ratio=0.1,
        rate_change_bps=0.0,
    )
    assert len(v) == FEATURE_DIM
    norm = float(np.linalg.norm(v))
    np.testing.assert_allclose(norm, 1.0, rtol=1e-3)

    # Polars üretimi
    df = pl.DataFrame({
        "bist_return_20d": [0.01, 0.05],
        "bist_volatility_20d": [0.20, 0.22],
        "usdtry_change_20d": [0.02, 0.01],
        "cds_5y_level": [290.0, 280.0],
        "vix_level": [18.0, 16.5],
        "advance_decline_ratio": [1.1, 1.4],
        "foreign_flow_ratio": [0.0, 0.1],
        "rate_change_bps": [0.0, 0.0],
    })
    v_polars = engine.vectorize_polars(df)
    assert len(v_polars) == FEATURE_DIM
    np.testing.assert_allclose(v_polars, v, rtol=1e-3)


def test_analogies_and_protection_advice(tmp_path: Path) -> None:
    """Tarihsel kriz benzerlik araması ve portföy koruma tavsiyesi testi."""
    db_file = tmp_path / "vec_analogies.duckdb"
    engine = MarketRegimeEmbeddingEngine(duckdb_path=str(db_file))

    # Kriz koşulları vektörü üret
    crisis_vec = engine.vectorize_market_state(
        bist_return_20d=-0.25,
        bist_volatility_20d=0.65,
        usdtry_change_20d=0.15,
        cds_5y_level=650.0,
        vix_level=45.0,
        advance_decline_ratio=0.2,
        foreign_flow_ratio=-0.5,
        rate_change_bps=500.0,
    )

    matches = engine.find_nearest_analogies(crisis_vec, top_k=3)
    assert len(matches) == 3
    assert matches[0].similarity_score > 0.5
    assert "CRISIS" in matches[0].historical_regime or "SHOCK" in matches[0].historical_regime

    # Koruma tavsiyesi
    advice = engine.get_regime_protection_advice(matches)
    assert advice.recommended_cash_pct >= 25.0
    assert advice.risk_multiplier <= 0.70
    assert advice.strategy == "DEFENSIVE_HIGH_CASH"


def test_transition_matrix_and_duckdb_storage(tmp_path: Path) -> None:
    """Markov geçiş matrisi ve yeni vektör kaydı/Polars okuma testi."""
    db_file = tmp_path / "vec_store.duckdb"
    engine = MarketRegimeEmbeddingEngine(duckdb_path=str(db_file))

    # Markov matrisi
    regimes = ["BULL", "BULL", "SIDEWAYS", "BEAR", "BULL"]
    mat = engine.compute_transition_matrix(regimes)
    assert "BULL" in mat
    assert "SIDEWAYS" in mat["BULL"]

    # Yeni vektör ekle
    custom_vec = np.zeros(16, dtype=np.float32)
    custom_vec[0] = 1.0
    initial_count = engine.vector_count
    engine.add_historical_vector(
        date="2026-03-01",
        vector=custom_vec,
        regime_name="CUSTOM_SUPER_BULL",
        description="Özel rejim testi",
        subsequent_1m_return=0.18,
    )
    assert engine.vector_count == initial_count + 1

    # DuckDB Polars okuma
    df_vectors = engine.get_stored_vectors_as_polars()
    assert isinstance(df_vectors, pl.DataFrame)
    assert df_vectors.height >= initial_count + 1
    assert "2026-03-01" in df_vectors["date"].to_list()


def test_vector_regime_thread_safety(tmp_path: Path) -> None:
    """Eşzamanlı arama ve tavsiye üretiminde thread-safety testi."""
    db_file = tmp_path / "vec_thread.duckdb"
    engine = MarketRegimeEmbeddingEngine(duckdb_path=str(db_file))

    dummy_vec = np.random.default_rng(42).normal(0, 1, 16).astype(np.float32)

    def worker(_: int) -> float:
        matches = engine.find_nearest_analogies(dummy_vec, top_k=2)
        adv = engine.get_regime_protection_advice(matches)
        return adv.similarity

    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
        futures = [executor.submit(worker, i) for i in range(8)]
        results = [f.result() for f in futures]

    assert len(results) == 8
    assert all(r >= 0.0 for r in results)
