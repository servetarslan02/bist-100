"""
ALPHA BIST — API Test Suite v1.0

Tüm API bileşenleri için test'ler.

Kullanım:
    python3 -m pytest tests/test_api.py -v
"""

import pytest
import time
from unittest.mock import MagicMock

from services.api.auth import (
    JWTHandler, APIKeyManager, RBACChecker, Role, TokenPayload,
    jwt_handler, api_key_manager, rbac_checker,
)
from services.api.rate_limiter import InMemoryRateLimiter, rate_limiter


# =====================================================
# AUTH TESTS
# =====================================================

class TestJWT:
    """JWT handler test'leri."""

    def test_create_token(self):
        handler = JWTHandler(secret_key="test-secret")
        token = handler.create_token("user1", "testuser", Role.VIEWER)
        assert isinstance(token, str)
        assert token.count(".") == 2

    def test_verify_token(self):
        handler = JWTHandler(secret_key="test-secret")
        token = handler.create_token("user1", "testuser", Role.ANALYST)
        payload = handler.verify_token(token)
        assert payload is not None
        assert payload.sub == "user1"
        assert payload.username == "testuser"
        assert payload.role == "ANALYST"

    def test_verify_invalid_token(self):
        handler = JWTHandler(secret_key="test-secret")
        payload = handler.verify_token("invalid.token.here")
        assert payload is None

    def test_verify_expired_token(self):
        handler = JWTHandler(secret_key="test-secret")
        # 0 saat = hemen expire
        token = handler.create_token("user1", "testuser", Role.VIEWER, expires_hours=0)
        time.sleep(0.1)
        payload = handler.verify_token(token)
        assert payload is None

    def test_verify_wrong_secret(self):
        handler1 = JWTHandler(secret_key="secret1")
        handler2 = JWTHandler(secret_key="secret2")
        token = handler1.create_token("user1", "testuser", Role.VIEWER)
        payload = handler2.verify_token(token)
        assert payload is None

    def test_roles(self):
        handler = JWTHandler(secret_key="test-secret")
        for role in Role:
            token = handler.create_token("user1", "testuser", role)
            payload = handler.verify_token(token)
            assert payload.role == role.value


class TestAPIKeyManager:
    """API key manager test'leri."""

    def test_register_and_verify(self):
        manager = APIKeyManager()
        manager.register_key("test-key", "test-service", ["GET", "POST"])
        info = manager.verify_key("test-key")
        assert info is not None
        assert info["service"] == "test-service"

    def test_verify_unknown_key(self):
        manager = APIKeyManager()
        info = manager.verify_key("unknown-key")
        assert info is None

    def test_revoke_key(self):
        manager = APIKeyManager()
        manager.register_key("test-key", "test-service", ["GET"])
        manager.revoke_key("test-key")
        info = manager.verify_key("test-key")
        assert info is None


class TestRBACChecker:
    """RBAC checker test'leri."""

    def test_viewer_can_get(self):
        assert rbac_checker.check_permission(Role.VIEWER, "GET")

    def test_viewer_cannot_post(self):
        assert not rbac_checker.check_permission(Role.VIEWER, "POST")

    def test_analyst_can_post(self):
        assert rbac_checker.check_permission(Role.ANALYST, "POST")

    def test_analyst_cannot_delete(self):
        assert not rbac_checker.check_permission(Role.ANALYST, "DELETE")

    def test_admin_can_all(self):
        for method in ["GET", "POST", "PUT", "DELETE"]:
            assert rbac_checker.check_permission(Role.ADMIN, method)

    def test_system_can_all(self):
        for method in ["GET", "POST", "PUT", "DELETE"]:
            assert rbac_checker.check_permission(Role.SYSTEM, method)

    def test_operator_can_put(self):
        assert rbac_checker.check_permission(Role.OPERATOR, "PUT")

    def test_operator_cannot_delete(self):
        assert not rbac_checker.check_permission(Role.OPERATOR, "DELETE")

    def test_admin_endpoint_admin_only(self):
        assert rbac_checker.check_endpoint_access(Role.ADMIN, "/admin/policy")
        assert rbac_checker.check_endpoint_access(Role.SYSTEM, "/admin/policy")
        assert not rbac_checker.check_endpoint_access(Role.VIEWER, "/admin/policy")
        assert not rbac_checker.check_endpoint_access(Role.ANALYST, "/admin/policy")

    def test_normal_endpoint_all_roles(self):
        for role in Role:
            assert rbac_checker.check_endpoint_access(role, "/api/v1/market/state")


# =====================================================
# RATE LIMITER TESTS
# =====================================================

class TestRateLimiter:
    """Rate limiter test'leri."""

    @pytest.mark.asyncio
    async def test_allows_within_limit(self):
        limiter = InMemoryRateLimiter()
        allowed, info = await limiter.check("client1", "default")
        assert allowed
        assert info["remaining"] >= 0

    @pytest.mark.asyncio
    async def test_blocks_over_limit(self):
        limiter = InMemoryRateLimiter()
        # 100 istek gönder (default limit)
        for _ in range(100):
            await limiter.check("client1", "default")
        # 101. istek bloklanmalı
        allowed, info = await limiter.check("client1", "default")
        assert not allowed or info["remaining"] == 0

    @pytest.mark.asyncio
    async def test_different_clients(self):
        limiter = InMemoryRateLimiter()
        for _ in range(100):
            await limiter.check("client1", "default")
        # Farklı client hâlâ erişebilmeli
        allowed, info = await limiter.check("client2", "default")
        assert allowed

    @pytest.mark.asyncio
    async def test_different_groups(self):
        limiter = InMemoryRateLimiter()
        for _ in range(100):
            await limiter.check("client1", "default")
        # Farklı grup hâlâ erişebilmeli
        allowed, info = await limiter.check("client1", "analysis")
        assert allowed

    def test_endpoint_group_detection(self):
        limiter = InMemoryRateLimiter()
        assert limiter.get_endpoint_group("/api/v1/market/state", "GET") == "default"
        assert limiter.get_endpoint_group("/api/v1/backtests", "POST") == "backtest"
        assert limiter.get_endpoint_group("/api/v1/scanner/scan", "POST") == "scanner"
        assert limiter.get_endpoint_group("/api/v1/agents/TECHNICAL/run", "POST") == "analysis"
        assert limiter.get_endpoint_group("/api/v1/intelligence/THYAO", "GET") == "analysis"
        assert limiter.get_endpoint_group("/ws/market", "GET") == "websocket"


# =====================================================
# APP TESTS
# =====================================================

class TestApp:
    """FastAPI uygulama test'leri."""

    def test_create_app(self):
        from services.api.app import create_app
        app = create_app()
        assert app.title == "ALPHA BIST API"
        assert app.version == "2.0.0"

    def test_routes_count(self):
        from services.api.app import create_app
        app = create_app()
        routes = [r for r in app.routes if hasattr(r, "methods")]
        # Root + health + OpenAPI + docs endpoint'leri
        assert len(routes) >= 2

    def test_v1_router_prefix(self):
        from services.api.v1 import v1_router
        assert v1_router.prefix == "/api/v1"


# =====================================================
# MAIN
# =====================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
