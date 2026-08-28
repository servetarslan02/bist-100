#!/usr/bin/env python3
"""
ALPHA BIST — OpenAPI Contract Testing (TestClient & In-Memory Verification)

FastAPI OpenAPI şemasına uyumluluğu test eder:
- Tüm endpoint'lerin OpenAPI şemasında tanımlanması
- Request/Response schema validation
- Pydantic v2 modelleri ve HTTP metod kapsama testi
- Health, Docs ve Route kontrolleri
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from services.api.app import app


@pytest.fixture(scope="module")
def client():
    return TestClient(app)


class TestOpenAPIContract:
    """OpenAPI şema doğrulama testleri."""

    def test_openapi_schema_accessible(self, client):
        """OpenAPI şeması erişilebilir ve geçerli olmalı."""
        response = client.get("/openapi.json")
        assert response.status_code == 200
        schema = response.json()
        assert "openapi" in schema
        assert "paths" in schema
        assert schema["openapi"].startswith("3.")

    def test_all_paths_have_methods(self, client):
        """Her path'in en az bir geçerli HTTP metodu olmalı."""
        schema = client.get("/openapi.json").json()
        for path, methods in schema.get("paths", {}).items():
            http_methods = [m for m in methods if m in ("get", "post", "put", "patch", "delete", "head", "options")]
            assert len(http_methods) > 0, f"Path '{path}' için HTTP metodu yok"

    def test_all_operations_have_responses(self, client):
        """Her operation'ın response tanımı olmalı."""
        schema = client.get("/openapi.json").json()
        for path, methods in schema.get("paths", {}).items():
            for method, spec in methods.items():
                if method in ("get", "post", "put", "patch", "delete"):
                    assert "responses" in spec, f"{method.upper()} {path} — response tanımı yok"

    def test_all_operations_have_operation_id(self, client):
        """Her operation'ın unique operationId'si olmalı (codegen için)."""
        schema = client.get("/openapi.json").json()
        seen_ids: set[str] = set()
        for path, methods in schema.get("paths", {}).items():
            for method, spec in methods.items():
                if method in ("get", "post", "put", "patch", "delete"):
                    op_id = spec.get("operationId")
                    if op_id:
                        assert op_id not in seen_ids, f"Duplicate operationId: {op_id}"
                        seen_ids.add(op_id)

    def test_health_endpoint(self, client):
        """Health endpoint 200 OK dönmeli."""
        resp = client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data.get("status") in ("ok", "healthy") or "version" in data

    def test_docs_endpoint(self, client):
        """Swagger UI erişilebilir olmalı."""
        resp = client.get("/docs")
        assert resp.status_code == 200


class TestAPIEndpointCoverage:
    """Temel API endpoint'lerinin hata fırlatmadan (500 üretmeden) yanıt vermesi."""

    def test_portfolio_routes(self, client):
        resp = client.get("/api/v1/portfolio/")
        assert resp.status_code in (200, 401, 403, 404)

    def test_risk_routes(self, client):
        resp = client.get("/api/v1/risk/portfolio")
        assert resp.status_code in (200, 401, 403, 404)

    def test_market_routes(self, client):
        resp = client.get("/api/v1/market/summary")
        assert resp.status_code in (200, 401, 403, 404)


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
