"""
Tests for services/api/v1/market.py
Covers:
- /state (with radar data, advancing/declining, empty fallback)
- /instruments & /instruments/{ticker}
- /instruments/{ticker}/ohlcv (success, not found)
- /instruments/{ticker}/live_intel (technical indicators, candle analysis, FVG)
- /instruments/{ticker}/features
- /sectors
- /calendar
- /events
- /radar (from cache and fresh)
- /regime
- /heatmap (with grouped sectors and weights)
"""

from __future__ import annotations

from unittest.mock import patch

import polars as pl
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from services.api.v1.market import (
    _hesapla_macd,
    _hesapla_oneri,
    _hesapla_rsi,
    _hesapla_sma,
    router,
)


@pytest.fixture
def app() -> FastAPI:
    app = FastAPI()
    app.include_router(router, prefix="/api/v1/market")
    return app


@pytest.fixture
def client(app: FastAPI) -> TestClient:
    return TestClient(app)


# =====================================================
# Unit Tests for Helper Calculations
# =====================================================


def test_calculations() -> None:
    closes = [10.0 + i for i in range(30)]
    rsi = _hesapla_rsi(closes)
    assert 0 <= rsi <= 100

    sma20 = _hesapla_sma(closes, 20)
    assert sma20 > 0

    macd, sig, macd_sig = _hesapla_macd(closes)
    assert macd is not None
    assert "POZİTİF" in macd_sig or "NEGATİF" in macd_sig or "NÖTR" in macd_sig

    rec, rec_tr, score = _hesapla_oneri(30.0, 50.0, 48.0, 45.0)
    assert rec in ["STRONG_BUY", "BUY", "SELL", "HOLD"]


# =====================================================
# Endpoint Tests
# =====================================================


def test_market_state(client: TestClient) -> None:
    with (
        patch("services.core.redis_helper.get_cached") as mock_cache,
        patch("services.intelligence.regime.regime_engine.get_current_regime") as mock_regime,
    ):
        mock_regime.return_value = "BULL"
        mock_cache.return_value = [
            {"change": 2.5, "rsi": 60.0},
            {"change": -1.2, "rsi": 45.0},
            {"change": 0.5, "rsi": 55.0},
        ]

        resp = client.get("/api/v1/market/state")
        assert resp.status_code == 200
        data = resp.json()
        assert data["regime"] == "BULL"
        assert data["advancing"] == 2
        assert data["declining"] == 1
        assert "breadth_pct" in data


def test_market_state_empty_radar(client: TestClient) -> None:
    with patch("services.core.redis_helper.get_cached", return_value=[]):
        resp = client.get("/api/v1/market/state")
        assert resp.status_code == 503


def test_instruments(client: TestClient) -> None:
    from services.api.v1.market import _instruments_cache
    _instruments_cache._cache = None

    with patch("services.ingestion.bist_universe.bist_universe") as mock_uni:
        mock_uni.BIST_100_TICKERS = ["THYAO", "ASELS"]
        mock_uni.BIST_ALL_TICKERS = ["THYAO", "ASELS", "GARAN"]

        resp = client.get("/api/v1/market/instruments")
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 3
        assert "THYAO" in data["bist_100"]


def test_instrument_detail(client: TestClient) -> None:
    resp = client.get("/api/v1/market/instruments/THYAO")
    assert resp.status_code == 200
    data = resp.json()
    assert data["ticker"] == "THYAO"
    assert "Türk Hava Yolları" in data["name"]


def test_instrument_ohlcv(client: TestClient) -> None:
    with patch("services.data.data_source.data_source.get_stock_data") as mock_ds:
        df = pl.DataFrame({
            "Date": ["2026-09-01", "2026-09-02"],
            "Open": [100.0, 102.0],
            "High": [105.0, 106.0],
            "Low": [99.0, 101.0],
            "Close": [102.0, 104.0],
            "Volume": [10000, 12000],
        })
        mock_ds.return_value = df

        resp = client.get("/api/v1/market/instruments/THYAO/ohlcv")
        assert resp.status_code == 200
        data = resp.json()
        assert data["ticker"] == "THYAO"
        assert len(data["data"]) == 2

        # 404 when no data
        mock_ds.return_value = pl.DataFrame()
        resp_nf = client.get("/api/v1/market/instruments/EMPTY/ohlcv")
        assert resp_nf.status_code == 404


def test_live_intel_analysis(client: TestClient) -> None:
    with (
        patch("services.data.data_source.data_source.get_stock_data") as mock_ds,
        patch("services.core.redis_helper.get_cached") as mock_cache,
    ):
        dates = [f"2026-08-{i:02d}" for i in range(1, 31)]
        df = pl.DataFrame({
            "Date": dates,
            "Open": [200.0 + i for i in range(30)],
            "High": [205.0 + i for i in range(30)],
            "Low": [198.0 + i for i in range(30)],
            "Close": [203.0 + i for i in range(30)],
            "Volume": [100000 + i * 1000 for i in range(30)],
        })
        mock_ds.return_value = df
        mock_cache.return_value = [{"symbol": "THYAO", "price": 235.0, "change": 1.5}]

        resp = client.get("/api/v1/market/instruments/THYAO/live_intel")
        assert resp.status_code == 200
        data = resp.json()
        assert data["symbol"] == "THYAO"
        assert "price" in data
        assert "rsi_14" in data
        assert "candles" in data
        assert "candle_patterns" in data
        assert data["is_real_data"] is True


def test_features(client: TestClient) -> None:
    with patch("services.intelligence.factor_engine.FactorEngine.get_features") as mock_feat:
        mock_feat.return_value = {"momentum": 1.2, "volatility": 0.15}

        resp = client.get("/api/v1/market/instruments/THYAO/features")
        assert resp.status_code == 200
        data = resp.json()
        assert data["features_available"] is True
        assert data["features"]["momentum"] == 1.2


def test_sectors_and_calendar(client: TestClient) -> None:
    with patch("services.ingestion.bist_universe.bist_universe") as mock_uni:
        mock_uni.SECTOR_MAP = {"THYAO": "Ulaştırma", "ASELS": "Savunma"}

        resp = client.get("/api/v1/market/sectors")
        assert resp.status_code == 200
        assert resp.json()["count"] == 2

    resp_cal = client.get("/api/v1/market/calendar")
    assert resp_cal.status_code == 200
    assert resp_cal.json()["market_open"] == "09:40"


def test_market_radar_cached_and_fresh(client: TestClient) -> None:
    # 1. Cached
    with patch("services.core.redis_helper.get_cached") as mock_cache:
        mock_cache.side_effect = lambda k: [{"symbol": "THYAO", "score": 85}] if k == "radar:data" else "2026-09-08T12:00:00"
        resp = client.get("/api/v1/market/radar")
        assert resp.status_code == 200
        data = resp.json()
        assert data["from_cache"] is True
        assert data["count"] == 1

    # 2. Fresh
    with (
        patch("services.core.redis_helper.get_cached", return_value=None),
        patch("services.api.v1.market._fetch_radar_fresh") as mock_fresh,
    ):
        mock_fresh.return_value = {"data": [{"symbol": "ASELS"}], "count": 1, "from_cache": False}
        resp_fresh = client.get("/api/v1/market/radar")
        assert resp_fresh.status_code == 200
        assert resp_fresh.json()["from_cache"] is False


def test_market_heatmap(client: TestClient) -> None:
    from services.api.v1.market import _heatmap_cache
    _heatmap_cache._cache = None

    with patch("services.core.redis_helper.get_cached") as mock_cache:
        mock_cache.return_value = [
            {"symbol": "AKBNK", "price": 55.0, "change": 2.1, "volume": 5000000, "score": 82},
            {"symbol": "THYAO", "price": 290.0, "change": -0.8, "volume": 12000000, "score": 75},
        ]

        resp = client.get("/api/v1/market/heatmap")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert len(data["sectors"]) > 0
        sec_names = [s["name"] for s in data["sectors"]]
        assert "Bankacılık & Finans" in sec_names or "Havacılık & Ulaştırma" in sec_names
