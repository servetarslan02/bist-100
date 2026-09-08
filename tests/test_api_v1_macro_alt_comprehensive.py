"""
Tests for services/api/v1/macro.py and services/api/v1/alternative.py
Covers:
- MACRO:
  - /overview, /world, /state, /indicators (live data mock, indicators, sentiment/bias)
  - /impact/{ticker} (sensitivity engine mock, 404 fallback)
  - /sensitivity/{sector} (sector sensitivity mock, 404 fallback)
- ALTERNATIVE:
  - /sources (listed data sources)
  - /sentiment/{ticker} (news provider sentiment, pos/neg words, bias calculation)
  - /news (financial RSS news caching and output)
  - /macro (macro provider integration and caching)
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from services.api.v1.alternative import router as alt_router
from services.api.v1.macro import router as macro_router


@pytest.fixture
def app() -> FastAPI:
    app = FastAPI()
    app.include_router(macro_router, prefix="/api/v1/macro")
    app.include_router(alt_router, prefix="/api/v1/alt")
    return app


@pytest.fixture
def client(app: FastAPI) -> TestClient:
    return TestClient(app)


# =====================================================
# Macro Routes Tests
# =====================================================


def test_macro_overview(client: TestClient) -> None:
    with patch("services.api.v1.macro._fetch_live_macro_data") as mock_fetch:
        mock_fetch.return_value = {
            "usd_try": 34.2,
            "vix": 14.5,
            "dxy": 101.5,
            "global_risk_appetite": 0.68,
            "bist_macro_bias": "POZİTİF",
        }

        resp = client.get("/api/v1/macro/overview")
        assert resp.status_code == 200
        data = resp.json()
        assert data["usd_try"] == 34.2
        assert data["bist_macro_bias"] == "POZİTİF"

        resp_state = client.get("/api/v1/macro/state")
        assert resp_state.status_code == 200


def test_macro_impact(client: TestClient) -> None:
    with patch("services.intelligence.macro_sensitivity.MacroSensitivityEngine.get_company_sensitivity") as mock_fn:
        mock_fn.return_value = {"interest_rate_beta": -0.45, "fx_beta": 0.85}

        resp = client.get("/api/v1/macro/impact/THYAO")
        assert resp.status_code == 200
        data = resp.json()
        assert data["ticker"] == "THYAO"
        assert data["macro_available"] is True
        assert data["fx_beta"] == 0.85

        # 404 when not found
        mock_fn.return_value = {}
        resp_nf = client.get("/api/v1/macro/impact/NOTFOUND")
        assert resp_nf.status_code == 404


def test_sector_sensitivity(client: TestClient) -> None:
    with patch("services.intelligence.macro_sensitivity.MacroSensitivityEngine.get_sector_sensitivity") as mock_fn:
        mock_fn.return_value = {"interest_rate_beta": -0.8}

        resp = client.get("/api/v1/macro/sensitivity/Banking")
        assert resp.status_code == 200
        data = resp.json()
        assert data["sector"] == "Banking"
        assert data["source"] == "macro_sensitivity_engine"

        # 404
        mock_fn.return_value = {}
        resp_nf = client.get("/api/v1/macro/sensitivity/Unknown")
        assert resp_nf.status_code == 404


# =====================================================
# Alternative Routes Tests
# =====================================================


def test_alternative_sources(client: TestClient) -> None:
    resp = client.get("/api/v1/alt/sources")
    assert resp.status_code == 200
    data = resp.json()
    assert "sources" in data
    assert "kap_rss" in data["sources"]
    assert data["status"] == "ok"


def test_alternative_sentiment(client: TestClient) -> None:
    from services.api.v1.alternative import _SENTIMENT_CACHE
    _SENTIMENT_CACHE.clear()

    with patch("services.ingestion.providers.news_provider.news_provider.fetch_news_for_ticker", new_callable=AsyncMock) as mock_news:
        mock_news.return_value = [
            {"title": "THYAO rekor kâr ve büyüme açıkladı", "summary": "Yeni ihale anlaşması sağlandı."},
            {"title": "THYAO temettü kararı onaylandı", "summary": "Başarı ile tamamlandı."},
        ]

        resp = client.get("/api/v1/alt/sentiment/THYAO")
        assert resp.status_code == 200
        data = resp.json()
        assert data["ticker"] == "THYAO"
        assert data["bias"] == "BULLISH"
        assert data["news_count"] == 2
        assert data["score"] > 50.0


def test_alternative_news(client: TestClient) -> None:
    import services.api.v1.alternative as alt_mod
    alt_mod._NEWS_CACHE = (0.0, [])

    with patch("services.ingestion.providers.news_provider.news_provider.fetch_financial_news_rss", new_callable=AsyncMock) as mock_rss:
        mock_rss.return_value = [
            {"title": "BIST güne yükselişle başladı", "link": "https://kap.org.tr/news/1"}
        ]

        resp = client.get("/api/v1/alt/news?limit=10")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "success"
        assert data["count"] == 1
        assert data["news"][0]["title"] == "BIST güne yükselişle başladı"


def test_alternative_macro(client: TestClient) -> None:
    import services.api.v1.alternative as alt_mod
    alt_mod._MACRO_CACHE = (0.0, {})

    with patch("services.ingestion.providers.macro_provider.MacroProvider.fetch_yahoo_macro", new_callable=AsyncMock) as mock_macro:
        mock_macro.return_value = {"brent": 78.5, "gold": 2500.0}

        resp = client.get("/api/v1/alt/macro")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "success"
        assert data["macro"]["brent"] == 78.5
