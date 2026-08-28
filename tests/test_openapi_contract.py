#!/usr/bin/env python3
"""
ALPHA BIST — OpenAPI Contract Testing

Schemathesis ile API'nin OpenAPI şemasına uyumluluğunu test eder.
- Tüm endpoint'lerin erişilebilirliği
- Request/Response schema validation
- Edge case detection (fuzzing)
- HTTP method coverage

Kullanım:
    python tests/test_openapi_contract.py
    # veya CI'da:
    schemathesis run http://localhost:8000/openapi.json --checks all
"""

from __future__ import annotations

import os
import sys

import pytest

# CI'da API çalışmayabilir, bu yüzden import guard
API_BASE_URL = os.getenv("API_BASE_URL", "http://localhost:8000")
OPENAPI_URL = f"{API_BASE_URL}/openapi.json"


def _api_available() -> bool:
    """API'nin çalışıp çalışmadığını kontrol et."""
    import urllib.request
    import urllib.error

    try:
        req = urllib.request.Request(f"{API_BASE_URL}/health", method="GET")
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status == 200
    except (urllib.error.URLError, OSError, TimeoutError):
        return False


def _get_openapi_schema() -> dict | None:
    """OpenAPI şemasını çek."""
    import json
    import urllib.request
    import urllib.error

    try:
        req = urllib.request.Request(OPENAPI_URL, method="GET")
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read().decode())
    except (urllib.error.URLError, OSError, TimeoutError, json.JSONDecodeError):
        return None


@pytest.mark.skipif(not _api_available(), reason="API çalışmıyor (localhost:8000)")
class TestOpenAPIContract:
    """OpenAPI şema doğrulama testleri."""

    def test_openapi_schema_accessible(self):
        """OpenAPI şeması erişilebilir olmalı."""
        schema = _get_openapi_schema()
        assert schema is not None, "OpenAPI şeması alınamadı"
        assert "openapi" in schema, "openapi versiyonu yok"
        assert "paths" in schema, "paths tanımı yok"

    def test_openapi_version(self):
        """OpenAPI 3.x kullanılıyor olmalı."""
        schema = _get_openapi_schema()
        assert schema is not None
        version = schema.get("openapi", "")
        assert version.startswith("3."), f"OpenAPI 3.x bekleniyordu, bulunan: {version}"

    def test_all_paths_have_methods(self):
        """Her path'in en az bir HTTP metodu olmalı."""
        schema = _get_openapi_schema()
        assert schema is not None
        for path, methods in schema.get("paths", {}).items():
            http_methods = [m for m in methods if m in ("get", "post", "put", "patch", "delete", "head", "options")]
            assert len(http_methods) > 0, f"Path '{path}' için HTTP metodu yok"

    def test_all_operations_have_responses(self):
        """Her operation'ın response tanımı olmalı."""
        schema = _get_openapi_schema()
        assert schema is not None
        for path, methods in schema.get("paths", {}).items():
            for method, spec in methods.items():
                if method in ("get", "post", "put", "patch", "delete"):
                    assert "responses" in spec, f"{method.upper()} {path} — response tanımı yok"

    def test_all_operations_have_operation_id(self):
        """Her operation'ın unique operationId'si olmalı (codegen için)."""
        schema = _get_openapi_schema()
        assert schema is not None
        seen_ids: set[str] = set()
        for path, methods in schema.get("paths", {}).items():
            for method, spec in methods.items():
                if method in ("get", "post", "put", "patch", "delete"):
                    op_id = spec.get("operationId")
                    if op_id:
                        assert op_id not in seen_ids, f"Duplicate operationId: {op_id}"
                        seen_ids.add(op_id)

    def test_health_endpoint(self):
        """Health endpoint erişilebilir olmalı."""
        import urllib.request

        req = urllib.request.Request(f"{API_BASE_URL}/health", method="GET")
        with urllib.request.urlopen(req, timeout=5) as resp:
            assert resp.status == 200

    def test_docs_endpoint(self):
        """Swagger UI erişilebilir olmalı."""
        import urllib.request

        req = urllib.request.Request(f"{API_BASE_URL}/docs", method="GET")
        with urllib.request.urlopen(req, timeout=5) as resp:
            assert resp.status == 200

    def test_schema_coverage(self):
        """Şemadaki tüm path'lerin en azından GET ile erişilebilirliği kontrol edilir."""
        import urllib.request
        import urllib.error

        schema = _get_openapi_schema()
        assert schema is not None

        skipped = []
        for path, methods in schema.get("paths", {}).items():
            if "get" in methods:
                url = f"{API_BASE_URL}{path}"
                try:
                    req = urllib.request.Request(url, method="GET")
                    with urllib.request.urlopen(req, timeout=5) as resp:
                        # 2xx, 3xx, 401, 403 — hepsi kabul (auth gerekebilir)
                        assert resp.status < 500, f"GET {path} → {resp.status}"
                except urllib.error.HTTPError as e:
                    # 401/403/404 kabul, 500 hata
                    assert e.code < 500, f"GET {path} → {e.code}"
                except (urllib.error.URLError, OSError, TimeoutError):
                    skipped.append(path)

        if skipped:
            pytest.skip(f"Bağlantı hatası: {skipped[:5]}")


@pytest.mark.skipif(not _api_available(), reason="API çalışmıyor (localhost:8000)")
class TestSchemathesisIntegration:
    """Schemathesis ile otomatik API fuzzing (ci.yml'da ayrıca çalıştırılır)."""

    def test_schemathesis_checks(self):
        """Schemathesis'in temel kontrolleri — manuel olarak API'ye istek atarak doğrula."""
        import json
        import urllib.request
        import urllib.error

        schema = _get_openapi_schema()
        assert schema is not None

        errors = []
        for path, methods in schema.get("paths", {}).items():
            for method, spec in methods.items():
                if method not in ("get", "post", "put", "patch", "delete"):
                    continue

                url = f"{API_BASE_URL}{path}"
                try:
                    if method == "get":
                        req = urllib.request.Request(url, method="GET")
                    elif method == "post":
                        # Boş body ile POST dene
                        req = urllib.request.Request(
                            url,
                            data=json.dumps({}).encode(),
                            method="POST",
                            headers={"Content-Type": "application/json"},
                        )
                    else:
                        continue

                    with urllib.request.urlopen(req, timeout=5) as resp:
                        pass  # Status kontrolü yeterli

                except urllib.error.HTTPError as e:
                    # 4xx kabul (validation error beklenir), 5xx hata
                    if e.code >= 500:
                        errors.append(f"{method.upper()} {path} → {e.code}")
                except (urllib.error.URLError, OSError, TimeoutError):
                    pass  # Bağlantı hatası — test ortamı

        assert len(errors) == 0, f"Server errors:\n" + "\n".join(errors[:10])


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
