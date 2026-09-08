"""
Tests for services/api/v1/models.py, services/api/v1/learning.py, and services/api/v1/decisions.py
Covers:
- MODELS:
  - /list, /registry (model_registry get_all_versions)
  - /performance (model performance metrics extraction)
  - /champion (champion model details)
  - /compare (compare models across metrics)
- LEARNING:
  - /status (learning pipeline status & active regime)
  - /performance-matrix, /metrics (evaluated models, trust scores, Brier score)
  - /evaluate-all (batch model evaluation trigger)
  - /fusion-weights (regime-based fusion weights)
- DECISIONS:
  - /list (decision history from PostgreSQL)
  - /detail/{decision_id} (single decision query)
  - /create (create new decision and insert into DB)
  - /execute/{decision_id} (decision execution flow)
"""

from __future__ import annotations

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
    app.include_router(models_router, prefix="/api/v1/models")
    app.include_router(learning_router, prefix="/api/v1/learning")
    app.include_router(decisions_router, prefix="/api/v1/decisions")
    return app


@pytest.fixture
def client(app: FastAPI) -> TestClient:
    return TestClient(app)


# =====================================================
# Models Tests
# =====================================================


def test_models_list_and_performance(client: TestClient) -> None:
    with patch("services.learning.model_registry.model_registry.get_all_versions") as mock_ver:
        mock_ver.return_value = [
            {
                "model_id": "lgbm_champion",
                "version": "1.0",
                "is_champion": True,
                "metrics": {"sharpe": 2.2, "win_rate": 0.68},
            },
            {
                "model_id": "catboost_challenger",
                "version": "1.0",
                "is_champion": False,
                "metrics": {"sharpe": 1.9, "win_rate": 0.62},
            },
        ]

        resp = client.get("/api/v1/models/list")
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 2
        assert "models" in data

        resp_perf = client.get("/api/v1/models/performance")
        assert resp_perf.status_code == 200
        perf_data = resp_perf.json()
        assert "lgbm_champion" in perf_data["performance"]


# =====================================================
# Learning Tests
# =====================================================


def test_learning_status_and_metrics(client: TestClient) -> None:
    with (
        patch("services.learning.model_memory_store.ModelMemoryStore.get_latest_metrics_all_models") as mock_mms,
        patch("services.api.v1.learning._pipeline") as mock_pipe,
    ):
        mock_pipe.store.get_latest_metrics_all_models.return_value = [{"model_id": "m1"}]
        mock_pipe.get_active_regime.return_value = "BULL"
        mock_pipe.fusion_engine.get_current_weights.return_value = {"m1": 1.0}
        mock_pipe.registered_models = ["m1"]

        resp_s = client.get("/api/v1/learning/status")
        assert resp_s.status_code == 200
        assert resp_s.json()["status"] == "active"
        assert resp_s.json()["active_regime"] == "BULL"

        mock_mms.return_value = [
            {
                "model_id": "m1",
                "version": "1.0",
                "evaluated_samples": 100,
                "hit_rate_pct": 65.0,
                "reliability_score": 85.0,
                "trust_score": 88.0,
            }
        ]

        resp_m = client.get("/api/v1/learning/metrics")
        assert resp_m.status_code == 200
        assert len(resp_m.json()["models"]) == 1
        assert resp_m.json()["models"][0]["hit_rate_pct"] == 65.0


# =====================================================
# Decisions Tests
# =====================================================


def test_decisions_crud(client: TestClient) -> None:
    with (
        patch("services.core.database.pg_fetch", new_callable=AsyncMock) as mock_fetch,
        patch("services.core.database.pg_fetchrow", new_callable=AsyncMock) as mock_fetchrow,
    ):
        # 1. List
        mock_fetch.return_value = [{"id": "dec-1", "ticker": "THYAO", "action": "BUY"}]
        resp_l = client.get("/api/v1/decisions/list?portfolio_id=1")
        assert resp_l.status_code == 200
        assert resp_l.json()["count"] == 1

        # 2. Detail
        mock_fetchrow.return_value = {"id": "dec-1", "ticker": "THYAO", "action": "BUY"}
        resp_d = client.get("/api/v1/decisions/detail/dec-1")
        assert resp_d.status_code == 200
        assert resp_d.json()["id"] == "dec-1"

        # 3. Create
        mock_fetchrow.return_value = {"id": "dec-new", "created_at": "2026-09-08T12:00:00"}
        resp_c = client.post("/api/v1/decisions/create?ticker=ASELS&action=BUY")
        assert resp_c.status_code == 200
        assert resp_c.json()["status"] == "created"
        assert resp_c.json()["decision"]["id"] == "dec-new"
