"""
Tests for services/api/v1/agents.py and services/api/v1/intelligence.py
Covers:
- AGENTS:
  - /list (AgentRole enum list)
  - /status (agent_system status)
  - /run (agent execution)
- INTELLIGENCE:
  - /regime (regime detector / engine)
  - /decisions (latest decisions from alpha_scanner)
  - /simulation/{ticker} (Monte Carlo GBM simulation)
  - /analysis/{ticker} (quantitative technical/sentiment analysis)
  - /ask_gemini & /gemini_report/{ticker}
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pandas as pd
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from services.api.v1.agents import router as agents_router
from services.api.v1.intelligence import router as intel_router


@pytest.fixture
def app() -> FastAPI:
    app = FastAPI()
    app.include_router(agents_router, prefix="/api/v1/agents")
    app.include_router(intel_router, prefix="/api/v1/intelligence")
    return app


@pytest.fixture
def client(app: FastAPI) -> TestClient:
    return TestClient(app)


# =====================================================
# Agents Tests
# =====================================================


def test_agents_list_status_run(client: TestClient) -> None:
    # 1. List
    resp_l = client.get("/api/v1/agents/list")
    assert resp_l.status_code == 200
    assert "agents" in resp_l.json()
    assert resp_l.json()["count"] > 0

    # 2. Status
    with patch("services.agents.agent_system.agent_system.get_status") as mock_st:
        mock_st.return_value = [{"role": "researcher", "status": "idle"}]
        resp_s = client.get("/api/v1/agents/status")
        assert resp_s.status_code == 200
        assert len(resp_s.json()["agents"]) == 1

    # 3. Run
    with patch("services.agents.agent_system.agent_system.run", new_callable=AsyncMock) as mock_run:
        mock_run.return_value = {"output": "research complete"}
        resp_r = client.post("/api/v1/agents/run?agent_name=researcher")
        assert resp_r.status_code == 200
        assert resp_r.json()["status"] == "started"


# =====================================================
# Intelligence Tests
# =====================================================


def test_intelligence_regime_and_decisions(client: TestClient) -> None:
    # 1. Regime
    with patch("services.intelligence.regime.regime_engine.detect_regime") as mock_reg:
        res = MagicMock()
        res.regime = "BULL"
        res.volatility_regime = "LOW"
        res.confidence = 0.85
        res.description = "Bullish trend"
        mock_reg.return_value = res

        resp_reg = client.get("/api/v1/intelligence/regime")
        assert resp_reg.status_code == 200
        assert resp_reg.json()["regime"] == "BULL"

    # 2. Decisions
    with patch("services.scanner.alpha_scanner.alpha_scanner.get_latest_results") as mock_res:
        mock_res.return_value = [{"ticker": "THYAO", "action": "BUY", "confidence": 0.9}]
        resp_dec = client.get("/api/v1/intelligence/decisions?limit=10")
        assert resp_dec.status_code == 200
        assert resp_dec.json()["count"] == 1


def test_intelligence_simulation(client: TestClient) -> None:
    with (
        patch("services.core.redis_helper.get_cached") as mock_cache,
        patch("yfinance.download") as mock_yf,
        patch("services.intelligence.advanced_monte_carlo.AdvancedMonteCarloEngine.gbm_sim") as mock_gbm,
    ):
        mock_cache.return_value = {"price": 300.0}

        dates = pd.date_range("2026-08-01", periods=25)
        mock_yf.return_value = pd.DataFrame(
            {"Close": [290.0 + i for i in range(25)]},
            index=dates,
        )

        sim_res = MagicMock()
        sim_res.expected_price = 320.0
        sim_res.median_price = 318.0
        sim_res.p5_worst = 280.0
        sim_res.p95_best = 360.0
        sim_res.prob_profit = 75.0
        sim_res.var_95 = 20.0
        sim_res.cvar_95 = 28.0
        sim_res.max_drawdown_sim = 8.5
        mock_gbm.return_value = sim_res

        resp = client.get("/api/v1/intelligence/simulation/THYAO?horizon_days=20&n_sims=500")
        assert resp.status_code == 200
        data = resp.json()
        assert data["expected_price"] == 320.0
        assert data["prob_profit"] == 75.0


def test_intelligence_analysis(client: TestClient) -> None:
    with patch("services.core.redis_helper.get_cached") as mock_cache:
        mock_cache.return_value = [
            {"symbol": "THYAO", "score": 85.0, "change": 2.5}
        ]

        resp = client.get("/api/v1/intelligence/analysis/THYAO")
        assert resp.status_code == 200
        data = resp.json()
        assert data["ticker"] == "THYAO"
        assert data["recommendation"] == "STRONG_BUY"
        assert data["sentiment"] == "BULLISH"


def test_intelligence_gemini(client: TestClient) -> None:
    with (
        patch("services.intelligence.gemini_service.call_gemini") as mock_gemini,
        patch("services.intelligence.gemini_service.analyze_company_gemini") as mock_analyze,
    ):
        mock_gemini.return_value = "Piyasa analizi yapıldı."
        resp_ask = client.post("/api/v1/intelligence/ask_gemini", json={"prompt": "Piyasa nasıl?"})
        assert resp_ask.status_code == 200
        assert resp_ask.json()["model"] == "gemini-3.7-flash"

        mock_analyze.return_value = "THYAO teknik ve temel araştırma raporu"
        resp_rep = client.get("/api/v1/intelligence/gemini_report/THYAO?price=300")
        assert resp_rep.status_code == 200
        assert resp_rep.json()["ticker"] == "THYAO"
