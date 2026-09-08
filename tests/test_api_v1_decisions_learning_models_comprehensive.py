"""
Tests for services/api/v1/decisions.py, services/api/v1/learning.py, and services/api/v1/models.py
Covers:
- DECISIONS:
  - /list (fetch decisions)
  - /detail/{decision_id} (fetch single decision)
  - /create (insert decision with TokenPayload user id)
  - /audit/{decision_id} (audit trail)
  - /pending-opportunities (Phase 18 opportunities)
  - /plan (active trade plan)
- LEARNING:
  - /status (learning status, regime, fusion weights)
  - /performance-matrix / /metrics (performance store)
- MODELS:
  - /list / /registry (models from registry)
  - /status (learning loop state)
  - /retrain (trigger retrain)
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from services.api.v1.decisions import router as decisions_router
from services.api.v1.learning import router as learning_router
from services.api.v1.models import router as models_router


@pytest.fixture
def app() -> FastAPI:
    app = FastAPI()
    app.include_router(decisions_router, prefix="/api/v1/decisions")
    app.include_router(learning_router, prefix="/api/v1/learning")
    app.include_router(models_router, prefix="/api/v1/models")
    return app


@pytest.fixture
def client(app: FastAPI) -> TestClient:
    return TestClient(app)


# =====================================================
# Decisions Tests
# =====================================================


def test_decisions_list_and_detail(client: TestClient) -> None:
    with (
        patch("services.core.database.pg_fetch", new_callable=AsyncMock) as mock_fetch,
        patch("services.core.database.pg_fetchrow", new_callable=AsyncMock) as mock_fetchrow,
    ):
        mock_fetch.return_value = [{"id": "d-1", "ticker": "THYAO", "action": "BUY"}]
        resp_l = client.get("/api/v1/decisions/list?portfolio_id=1&limit=10")
        assert resp_l.status_code == 200
        assert resp_l.json()["count"] == 1

        mock_fetchrow.return_value = {"id": "d-1", "ticker": "THYAO", "action": "BUY"}
        resp_d = client.get("/api/v1/decisions/detail/d-1")
        assert resp_d.status_code == 200
        assert resp_d.json()["ticker"] == "THYAO"


def test_decisions_create_and_audit(client: TestClient) -> None:
    with (
        patch("services.core.database.pg_fetchrow", new_callable=AsyncMock) as mock_fetchrow,
        patch("services.core.database.pg_fetch", new_callable=AsyncMock) as mock_fetch,
    ):
        now = datetime.now(UTC)
        mock_fetchrow.return_value = {"id": "d-2", "created_at": now}
        resp_c = client.post("/api/v1/decisions/create?ticker=ASELS&action=BUY")
        assert resp_c.status_code == 200
        assert resp_c.json()["status"] == "created"
        assert resp_c.json()["decision_id"] == "d-2"

        mock_fetch.return_value = [{"id": 1, "action": "CREATED"}]
        resp_a = client.get("/api/v1/decisions/audit/d-2")
        assert resp_a.status_code == 200
        assert len(resp_a.json()["audit"]) == 1


def test_decisions_opportunities_and_plan(client: TestClient) -> None:
    with patch("services.core.database.pg_fetch", new_callable=AsyncMock) as mock_fetch:
        now = datetime.now(UTC)
        mock_fetch.return_value = [
            {
                "created_at": now,
                "target_date": now.date(),
                "tickers": ["THYAO", "BIMAS"],
                "is_cash_regime": False,
                "is_rebalance": True,
            }
        ]
        resp_o = client.get("/api/v1/decisions/pending-opportunities")
        assert resp_o.status_code == 200
        assert "opportunities" in resp_o.json()

        mock_fetch.return_value = [{"id": "d-3", "ticker": "BIMAS", "status": "pending"}]
        resp_p = client.get("/api/v1/decisions/plan?portfolio_id=1")
        assert resp_p.status_code == 200
        assert resp_p.json()["count"] == 1


# =====================================================
# Learning Tests
# =====================================================


def test_learning_status_and_metrics(client: TestClient) -> None:
    with (
        patch("services.api.v1.learning._pipeline.store.get_latest_metrics_all_models") as mock_metrics,
        patch("services.learning.model_memory_store.ModelMemoryStore.get_latest_metrics_all_models") as mock_summary,
    ):
        mock_metrics.return_value = {"lgbm": {"sharpe": 1.8}}
        resp_s = client.get("/api/v1/learning/status")
        assert resp_s.status_code == 200
        assert resp_s.json()["status"] == "active"

        mock_summary.return_value = [{"model_id": "lgbm", "score": 0.92}]
        resp_m = client.get("/api/v1/learning/performance-matrix")
        assert resp_m.status_code == 200
        assert "models" in resp_m.json()


# =====================================================
# Models Tests
# =====================================================


def test_models_registry_and_retrain(client: TestClient) -> None:
    with (
        patch("services.learning.model_registry.model_registry.get_all_versions") as mock_reg,
        patch("services.learning.learning_loop.learning_loop.get_state") as mock_st,
        patch("services.learning.learning_loop.learning_loop.should_retrain") as mock_sr,
        patch("services.learning.learning_loop.learning_loop.get_retrain_reason") as mock_rr,
        patch("services.learning.learning_loop.learning_loop.trigger_autonomous_retrain") as mock_retrain,
    ):
        mock_reg.return_value = [{"name": "lgbm_champion", "version": "1.0"}]
        resp_l = client.get("/api/v1/models/list")
        assert resp_l.status_code == 200
        assert resp_l.json()["count"] == 1

        mock_st.return_value = {"state": "idle"}
        mock_sr.return_value = False
        mock_rr.return_value = "No drift detected"
        resp_s = client.get("/api/v1/models/learning-state")
        assert resp_s.status_code == 200
        assert resp_s.json()["learning_loop"]["state"] == "idle"

        mock_retrain.return_value = {"status": "success", "models_updated": 1}
        resp_r = client.post("/api/v1/models/retrain?force=true")
        assert resp_r.status_code == 200
        assert resp_r.json()["status"] == "success"
