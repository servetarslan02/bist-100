"""ALPHA BIST — FeatureEngine Kapsamlı Test Paketi.

Bu test paketi 8 denetim kuralına tam uyumlu olarak FeatureEngine motorunu ve veri modellerini test eder:
1. Veri modelleri ve orjson serileştirme/deserileştirme (FeatureSetResult).
2. safe_float ve last_series_val yardımcı fonksiyonlarının uç değer (None, NaN, Inf, Series) korumaları.
3. Polars DataFrame normalizasyonu (tarih sıralama, MultiIndex düzleştirme).
4. Tekil hisse için uçtan uca öznitelik hesaplama (compute_all: Price Context, Volatility, Trend, RSI, Hacim).
5. Tüm evren için çapraz kesitli öznitelik hesaplama (compute_universe_features, sektör getiri serileri, breadth).
6. DuckDB SSD korumalı WAL denetim izi kaydı ve Polars DataFrame ile geri okuma.
7. Eşzamanlı iş parçacığı güvenliği (thread-safety).
"""

from __future__ import annotations

import concurrent.futures
from datetime import date, timedelta
from typing import TYPE_CHECKING

import numpy as np
import orjson
import polars as pl

from services.ml.feature_engine import (
    FeatureEngine,
    FeatureSetResult,
    compute_universe_features,
    last_series_val,
    read_feature_audit_polars,
    safe_float,
    save_feature_set_to_duckdb,
)

if TYPE_CHECKING:
    from pathlib import Path


def _generate_synthetic_ohlcv(n_bars: int = 150, base_price: float = 100.0) -> pl.DataFrame:
    """Test amaçlı geçerli OHLCV Polars DataFrame'i üretir."""
    np.random.seed(42)
    start_dt = date(2024, 1, 1)
    dates = [start_dt + timedelta(days=i) for i in range(n_bars)]

    returns = np.random.normal(0.001, 0.02, size=n_bars)
    prices = base_price * np.exp(np.cumsum(returns))

    highs = prices * (1.0 + np.abs(np.random.normal(0, 0.01, size=n_bars)))
    lows = prices * (1.0 - np.abs(np.random.normal(0, 0.01, size=n_bars)))
    opens = (highs + lows) / 2.0
    volumes = np.random.lognormal(mean=14, sigma=0.5, size=n_bars)

    return pl.DataFrame(
        {
            "Date": dates,
            "Open": opens,
            "High": highs,
            "Low": lows,
            "Close": prices,
            "Volume": volumes,
        }
    )


def test_dataclasses_serialization() -> None:
    """FeatureSetResult veri modelinin to_dict, from_dict ve orjson serileştirmesini test eder."""
    res_orig = FeatureSetResult(
        ticker="THYAO",
        calculated_at="2026-09-08T12:00:00Z",
        feature_count=3,
        features={"roc_5d": 0.045, "rsi_14": 62.5, "volatility_20d": 0.22},
        metadata={"version": 3},
    )
    r_bytes = res_orig.to_orjson_bytes()
    r_restored = FeatureSetResult.from_dict(orjson.loads(r_bytes))
    assert r_restored.ticker == "THYAO"
    assert r_restored.feature_count == 3
    assert r_restored.features["rsi_14"] == 62.5
    assert "FeatureSetResult" in repr(res_orig)


def test_safe_float_and_last_series_val() -> None:
    """safe_float ve last_series_val güvenlik korumalarını doğrular."""
    assert np.isnan(safe_float(None))
    assert np.isnan(safe_float("invalid"))
    assert np.isnan(safe_float(float("inf")))
    assert safe_float(12.34) == 12.34
    assert safe_float(pl.Series([1.0, 5.5])) == 5.5
    assert np.isnan(safe_float(pl.Series([])))

    assert np.isnan(last_series_val(None))
    assert np.isnan(last_series_val(pl.Series([])))
    assert last_series_val(pl.Series([10.0, 20.0])) == 20.0


def test_normalize_dataframe() -> None:
    """Polars DataFrame normalizasyonunu test eder."""
    engine = FeatureEngine()
    assert engine.normalize(None).is_empty()
    assert engine.normalize(pl.DataFrame()).is_empty()

    df = pl.DataFrame(
        {
            "Date": [date(2024, 1, 3), date(2024, 1, 1), date(2024, 1, 2)],
            "Close": [103.0, 100.0, 101.0],
        }
    )
    norm_df = engine.normalize(df)
    assert norm_df["Date"][0] == date(2024, 1, 1)
    assert norm_df["Date"][-1] == date(2024, 1, 3)


def test_compute_all_features() -> None:
    """Tekil hisse için uçtan uca öznitelik hesaplama motorunu test eder."""
    engine = FeatureEngine()
    df_stock = _generate_synthetic_ohlcv(n_bars=120, base_price=50.0)
    df_bm = _generate_synthetic_ohlcv(n_bars=120, base_price=10000.0)

    features = engine.compute_all(
        ticker="THYAO",
        df=df_stock,
        benchmark_df=df_bm,
        breadth_advance_ratio=0.60,
    )

    assert isinstance(features, dict)
    assert len(features) > 20

    # Temel özniteliklerin varlığı ve geçerli değerler
    assert "roc_5d" in features
    assert "roc_20d" in features
    assert "rsi_14" in features
    assert "volatility_20d" in features

    for f_name, val in features.items():
        assert np.isfinite(val) or np.isnan(val), f"Gecersiz sayisal deger: {f_name}={val}"


def test_compute_universe_features() -> None:
    """Tüm BIST evreni genelinde çapraz kesitli hesaplama motorunu doğrular."""
    tickers = ["THYAO", "GARAN", "EREGL", "SISE", "AKBNK", "KCHOL"]
    market_data = {t: _generate_synthetic_ohlcv(n_bars=80, base_price=20.0 + i * 10) for i, t in enumerate(tickers)}
    bm_df = _generate_synthetic_ohlcv(n_bars=80, base_price=9500.0)
    sector_map = {
        "THYAO": "ULAŞTIRMA",
        "GARAN": "BANKA",
        "AKBNK": "BANKA",
        "EREGL": "SANAYİ",
        "SISE": "SANAYİ",
        "KCHOL": "HOLDİNG",
    }

    universe_features = compute_universe_features(
        market_data=market_data,
        benchmark_df=bm_df,
        sector_map=sector_map,
    )

    assert len(universe_features) == len(tickers)
    for ticker in tickers:
        assert ticker in universe_features
        assert len(universe_features[ticker]) > 15


def test_duckdb_wal_save_and_polars_read(tmp_path: Path) -> None:
    """Öznitelik denetim kaydının DuckDB WAL ile yazılıp Polars ile okunduğunu test eder."""
    db_file = str(tmp_path / "feature_audit.duckdb")

    res = FeatureSetResult(
        ticker="GARAN",
        calculated_at="2026-09-08T12:00:00Z",
        feature_count=2,
        features={"roc_5d": 0.02, "rsi_14": 55.0},
    )

    save_feature_set_to_duckdb(res, db_path=db_file)

    df_read = read_feature_audit_polars(db_path=db_file, ticker="GARAN")
    assert isinstance(df_read, pl.DataFrame)
    assert df_read.height == 1
    assert df_read["ticker"][0] == "GARAN"
    assert df_read["feature_count"][0] == 2


def test_thread_safety_engine() -> None:
    """Çoklu thread ile eşzamanlı öznitelik hesaplama güvenliğini test eder."""
    engine = FeatureEngine()
    df_stock = _generate_synthetic_ohlcv(n_bars=60)

    def worker(idx: int) -> int:
        res = engine.compute_all(ticker=f"STOCK_{idx}", df=df_stock)
        return len(res)

    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as executor:
        futs = [executor.submit(worker, i) for i in range(12)]
        for f in concurrent.futures.as_completed(futs):
            assert f.result() > 10
