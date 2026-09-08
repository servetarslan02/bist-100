"""Comprehensive integration and unit tests for services.api.app."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from starlette.testclient import TestClient

from services.api.app import create_app


@pytest.fixture(scope="module")
def api_client():
    """Create a TestClient with mocked database check to avoid external IO."""
    with patch("services.api.app.check_db_health", new_callable=AsyncMock) as mock_health:
        mock_health.return_value = {
            "postgres": "healthy",
            "clickhouse": "healthy",
            "redis": "healthy",
            "questdb": "healthy",
        }
        app = create_app()
        with TestClient(app, raise_server_exceptions=False) as client:
            yield client


def test_app_root_and_dashboard(api_client):
    """Test / and /dashboard routes return 200."""
    response = api_client.get("/")
    assert response.status_code == 200

    dash_response = api_client.get("/dashboard")
    assert dash_response.status_code == 200


def test_app_health_endpoints(api_client):
    """Test /health, /api/health, and /health/detailed."""
    res_health = api_client.get("/health")
    assert res_health.status_code == 200
    data = res_health.json()
    assert "status" in data
    assert data["version"] == "2.0.0"

    res_api_health = api_client.get("/api/health")
    assert res_api_health.status_code == 200

    res_detailed = api_client.get("/health/detailed")
    assert res_detailed.status_code == 200
    data_det = res_detailed.json()
    assert "services" in data_det


def test_app_openapi_and_docs(api_client):
    """Test /docs and /openapi.json are accessible."""
    docs_res = api_client.get("/docs")
    assert docs_res.status_code == 200

    openapi_res = api_client.get("/openapi.json")
    assert openapi_res.status_code == 200
    openapi_data = openapi_res.json()
    assert openapi_data["info"]["title"] == "ALPHA BIST API"


def test_app_timing_and_request_id_middleware(api_client):
    """Verify X-Process-Time-Ms and X-Request-ID headers are present on responses."""
    custom_req_id = "test-custom-uuid-1234"
    response = api_client.get("/health", headers={"X-Request-ID": custom_req_id})
    assert response.status_code == 200
    assert "X-Process-Time-Ms" in response.headers
    assert response.headers["X-Request-ID"] == custom_req_id


def test_app_api_version_middleware(api_client):
    """Verify X-API-Version header on /api/ routes."""
    response = api_client.get("/api/health")
    assert response.status_code == 200
    assert response.headers.get("X-API-Version") == "1.0.0"
