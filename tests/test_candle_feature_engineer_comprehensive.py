"""services/ml/candle_feature_engineer.py Kapsamlı ve Çok Senaryolu Test Paketi.

GEMINI.md Kural 1-8 standartlarına göre CandleFeatureEngineer motorunu,
mum formasyonu öznitelik çıkarımını, ampirik getiri karnesini, DuckDB ve Polars entegrasyonunu,
eşzamanlılık ve sınır durumlarını doğrular.
"""

from __future__ import annotations

import concurrent.futures
from pathlib import Path
import numpy as np
import polars as pl
import pytest

from services.ml.candle_feature_engineer import (
    CandleEmpiricalSummary,
    CandleFeatureEngineer,
    candle_feature_engineer,
)


def _generate_synthetic_ohlcv(n_bars: int = 60) -> pl.DataFrame:
    """Testler için sentetik BIST OHLCV verisi üretir."""
    rng = np.random.default_rng(42)
    base_price = 100.0
    returns = rng.normal(0.001, 0.02, size=n_bars)
    close = base_price * np.cumprod(1.0 + returns)
    high = close * (1.0 + rng.uniform(0.005, 0.02, size=n_bars))
    low = close * (1.0 - rng.uniform(0.005, 0.02, size=n_bars))
    open_p = low + rng.uniform(0.0, 1.0, size=n_bars) * (high - low)
    volume = rng.uniform(10000, 500000, size=n_bars)

    return pl.DataFrame({
        "Date": [f"2026-01-{(i % 28) + 1:02d}" for i in range(n_bars)],
        "Open": open_p,
        "High": high,
        "Low": low,
        "Close": close,
        "Volume": volume,
    })


def test_dataclass_serialization_and_roundtrip() -> None:
    """CandleEmpiricalSummary to_dict, from_dict ve to_orjson_bytes serileştirme doğrulaması."""
    summary = CandleEmpiricalSummary(
        pattern="BULLISH_ENGULFING",
        sample_count=85,
        win_rate=62.4,
        avg_forward_return=3.45,
        profit_factor=1.85,
        payoff_ratio=1.52,
        expectancy=1.80,
        recommendation="⭐⭐⭐⭐⭐ (Güçlü Al)",
    )

    d = summary.to_dict()
    assert d["pattern"] == "BULLISH_ENGULFING"
    assert d["sample_count"] == 85
    assert d["win_rate"] == 62.4

    b = summary.to_orjson_bytes()
    assert isinstance(b, bytes)
    assert b"BULLISH_ENGULFING" in b

    restored = CandleEmpiricalSummary.from_dict(d)
    assert restored.pattern == summary.pattern
    assert restored.expectancy == summary.expectancy
    assert "CandleEmpiricalSummary" in repr(restored)


def test_extract_features_for_dataframe_standard() -> None:
    """Geçerli OHLCV verisinde mum özniteliklerinin çıkarılması ve kolon doğrulaması."""
    cfe = CandleFeatureEngineer()
    df = _generate_synthetic_ohlcv(50)

    df_feat = cfe.extract_features_for_dataframe(df, ticker="THYAO")

    assert isinstance(df_feat, pl.DataFrame)
    assert df_feat.height == 50

    expected_cols = [
        "feat_buyer_pressure",
        "feat_candle_score",
        "feat_has_bull_engulfing",
        "feat_has_hammer",
        "feat_has_morning_star",
        "feat_has_soldiers",
        "feat_has_fvg",
        "feat_has_shooting_star",
        "feat_has_crows",
    ]
    for col in expected_cols:
        assert col in df_feat.columns, f"Eksik öznitelik sütunu: {col}"
        # Değerlerin sonlu float olduğunu doğrula
        vals = df_feat[col].to_numpy()
        assert np.all(np.isfinite(vals))


def test_extract_features_boundary_conditions() -> None:
    """Boş tablo veya 4 bardan az veri verildiğinde sıfır değerli güvenli kolon üretimi."""
    cfe = CandleFeatureEngineer()

    # 1. Boş DataFrame
    df_empty = pl.DataFrame()
    res_empty = cfe.extract_features_for_dataframe(df_empty)
    assert res_empty.height == 0

    # 2. 2 barlık kısa veri
    df_short = pl.DataFrame({
        "Open": [10.0, 11.0],
        "High": [12.0, 13.0],
        "Low": [9.0, 10.0],
        "Close": [11.0, 12.0],
        "Volume": [100.0, 200.0],
    })
    res_short = cfe.extract_features_for_dataframe(df_short)
    assert res_short.height == 2
    assert "feat_candle_score" in res_short.columns
    assert np.all(res_short["feat_candle_score"].to_numpy() == 0.0)


def test_compute_empirical_edge_table() -> None:
    """Tarihsel BIST hisse havuzundan ampirik mum başarı karnesi çıkarılması."""
    cfe = CandleFeatureEngineer()

    # 2 sembol için yeterli veri
    stocks = {
        "AKBNK": _generate_synthetic_ohlcv(60),
        "GARAN": _generate_synthetic_ohlcv(60),
    }

    edge_df = cfe.compute_empirical_edge_table(stocks, forward_days=5)
    assert isinstance(edge_df, pl.DataFrame)
    # Formasyon tespit edilmişse karne dolmalı
    if edge_df.height > 0:
        assert "pattern" in edge_df.columns
        assert "expectancy" in edge_df.columns
        assert "win_rate" in edge_df.columns
        assert len(cfe.pattern_stats) > 0


def test_duckdb_and_polars_integration(tmp_path: Path) -> None:
    """DuckDB tablosuna aktarım ve Polars DataFrame okuma testi."""
    cfe = CandleFeatureEngineer()

    dummy_edge = pl.DataFrame({
        "pattern": ["BULLISH_ENGULFING", "HAMMER_PINBAR"],
        "sample_count": [50, 30],
        "win_rate": [60.0, 55.0],
        "avg_forward_return": [2.5, 1.8],
        "profit_factor": [1.7, 1.4],
        "payoff_ratio": [1.5, 1.2],
        "expectancy": [1.2, 0.8],
        "recommendation": ["Al", "Nötr"],
    })

    db_path = str(tmp_path / "candle_edge.duckdb")
    cfe.export_empirical_table_duckdb(dummy_edge, db_path=db_path, table_name="test_edge")

    # Polars ile oku
    df_read = cfe.read_empirical_table_polars(db_path=db_path, table_name="test_edge")
    assert isinstance(df_read, pl.DataFrame)
    assert df_read.height == 2
    assert "expectancy" in df_read.columns

    # Boş tablo aktarımı hatasız loglanmalı
    cfe.export_empirical_table_duckdb(pl.DataFrame(), db_path=db_path, table_name="test_empty")


def test_thread_safety_concurrent_feature_extraction() -> None:
    """Çoklu iş parçacıklarında eşzamanlı mum öznitelik çıkarımı."""
    cfe = CandleFeatureEngineer()
    df = _generate_synthetic_ohlcv(40)

    def worker(i: int) -> int:
        res = cfe.extract_features_for_dataframe(df, ticker=f"TICKER_{i}")
        return res.height

    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as executor:
        futures = [executor.submit(worker, i) for i in range(20)]
        results = [f.result() for f in futures]

    assert len(results) == 20
    assert all(r == 40 for r in results)


def test_singleton_instance() -> None:
    """Varsayılan singleton örneğinin doğruluğu."""
    assert isinstance(candle_feature_engineer, CandleFeatureEngineer)
