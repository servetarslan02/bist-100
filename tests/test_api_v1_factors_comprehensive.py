"""
Tests for services/api/v1/factors.py and services/api/v1/event_study.py
Covers:
- FACTORS:
  - _hesapla_faktor_skorlari & _hesapla_fama_french calculation helpers
  - /scores/{ticker} (from radar cache, 404 if missing)
  - /exposure/{ticker} (Fama-French 5-factor exposure, alpha, R-squared)
  - /portfolio-exposure (weighted portfolio factor exposure, positions mock, empty fallback)
- EVENT STUDY:
  - /events and /calendar (fetch live events with KAP/MACRO filtering)
  - /analyze/{ticker} (CAR cumulative abnormal returns, t-stat, p-value with yfinance mock)
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pandas as pd
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from services.api.v1.event_study import router as event_router
from services.api.v1.factors import (
    _hesapla_faktor_skorlari,
    _hesapla_fama_french,
)
from services.api.v1.factors import (
    router as factor_router,
)


@pytest.fixture
def app() -> FastAPI:
    app = FastAPI()
    app.include_router(factor_router, prefix="/api/v1/factors")
    app.include_router(event_router, prefix="/api/v1/event_study")
    return app


@pytest.fixture
def client(app: FastAPI) -> TestClient:
    return TestClient(app)


# =====================================================
# Factors Tests
# =====================================================


def test_factors_calculations() -> None:
    factors = _hesapla_faktor_skorlari(80.0, 3.5)
    assert "momentum" in factors
    assert "value" in factors
    assert "quality" in factors
    assert "volatility" in factors
    assert "liquidity" in factors
    assert "size" in factors

    ff = _hesapla_fama_french(factors)
    assert "fama_french_betas" in ff
    assert "mkt_rf" in ff["fama_french_betas"]
    assert "r_squared" in ff
    assert "alpha_annual_pct" in ff


def test_factor_scores_endpoint(client: TestClient) -> None:
    with patch("services.api.v1.factors.get_cached") as mock_cache:
        mock_cache.return_value = [
            {"symbol": "THYAO", "score": 85.0, "change": 2.4}
        ]

        resp = client.get("/api/v1/factors/scores/THYAO")
        assert resp.status_code == 200
        data = resp.json()
        assert data["ticker"] == "THYAO"
        assert data["factor_available"] is True
        assert data["composite_score"] == 85.0

        # 404 when ticker missing in radar
        resp_nf = client.get("/api/v1/factors/scores/NOTFOUND")
        assert resp_nf.status_code == 404


def test_factor_exposure_endpoint(client: TestClient) -> None:
    with patch("services.api.v1.factors.get_cached") as mock_cache:
        mock_cache.return_value = [
            {"symbol": "THYAO", "score": 85.0, "change": 2.4}
        ]

        resp = client.get("/api/v1/factors/exposure/THYAO")
        assert resp.status_code == 200
        data = resp.json()
        assert data["ticker"] == "THYAO"
        assert data["exposure_available"] is True
        assert "fama_french_betas" in data


def test_portfolio_exposure_endpoint(client: TestClient) -> None:
    with (
        patch("services.paper_trading.paper_orchestrator.paper_orchestrator.portfolio") as mock_pf,
        patch("services.api.v1.factors.get_cached") as mock_cache,
    ):
        mock_pf.get_all_positions.return_value = [
            {"ticker": "THYAO", "market_value": 60000.0},
            {"ticker": "ASELS", "market_value": 40000.0},
        ]
        mock_pf.get_total_value.return_value = 100000.0

        mock_cache.return_value = [
            {"symbol": "THYAO", "score": 80.0, "change": 2.0},
            {"symbol": "ASELS", "score": 75.0, "change": 1.0},
        ]

        resp = client.get("/api/v1/factors/portfolio-exposure")
        assert resp.status_code == 200
        data = resp.json()
        assert data["portfolio_id"] == 1
        assert data["num_positions"] == 2
        assert "factors" in data
        assert "fama_french_betas" in data

        # Empty portfolio
        mock_pf.get_all_positions.return_value = []
        resp_empty = client.get("/api/v1/factors/portfolio-exposure")
        assert resp_empty.status_code == 200
        assert resp_empty.json()["num_positions"] == 0


# =====================================================
# Event Study Tests
# =====================================================


def test_event_calendar_endpoint(client: TestClient) -> None:
    from services.api.v1.event_study import _events_cache
    _events_cache._cache = None

    with patch("services.api.v1.event_study._canli_olaylari_getir", new_callable=AsyncMock) as mock_events:
        mock_events.return_value = [
            {
                "id": "1",
                "timestamp": "08.09 14:30",
                "type": "KAP",
                "source": "KAP",
                "title": "THYAO Özel Durum Açıklaması",
                "ticker": "THYAO",
                "sentiment": 0.8,
            }
        ]

        resp = client.get("/api/v1/event_study/events")
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 1
        assert data["events"][0]["ticker"] == "THYAO"


def test_event_study_analysis(client: TestClient) -> None:
    with patch("services.api.v1.event_study.yf.download") as mock_yf:
        # Create synthetic 30 days of closes
        dates = pd.date_range("2026-08-01", periods=30)
        stock_prices = [250.0 + i * 1.5 for i in range(30)]
        bm_prices = [10000.0 + i * 20.0 for i in range(30)]

        df = pd.DataFrame(
            {
                ("Close", "THYAO.IS"): stock_prices,
                ("Close", "XU100.IS"): bm_prices,
            },
            index=dates,
        )
        mock_yf.return_value = df

        resp = client.get("/api/v1/event_study/analyze/THYAO")
        assert resp.status_code == 200
        data = resp.json()
        assert data["ticker"] == "THYAO"
        assert "car_cumulative_abnormal_return" in data
        assert "t_statistic" in data
        assert "p_value" in data
        assert "is_statistically_significant" in data
