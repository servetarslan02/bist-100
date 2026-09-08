"""Comprehensive unit tests for services.api.auth."""

from __future__ import annotations

import time

import pytest

from services.api.auth import (
    APIKeyManager,
    AuthConfig,
    JWTHandler,
    RBACChecker,
    Role,
    TokenPayload,
    User,
    api_key_manager,
    jwt_handler,
    rbac_checker,
)


def test_auth_config_and_user_models():
    """Verify AuthConfig, User, and TokenPayload dataclasses."""
    cfg = AuthConfig(jwt_secret="super-secret-key-12345", jwt_algorithm="HS256", jwt_expires_hours=12)
    assert "jwt_algorithm='HS256'" in repr(cfg)
    assert cfg.jwt_expires_hours == 12

    user = User(user_id="u-001", username="trader_joe", role=Role.ANALYST, permissions=["GET", "POST"])
    assert "User(user_id='u-001'" in repr(user)
    assert user.is_active is True

    payload = TokenPayload(
        sub="u-001",
        username="trader_joe",
        role="analyst",
        permissions=["GET", "POST"],
        exp=time.time() + 3600,
        iat=time.time(),
    )
    assert "TokenPayload" in repr(payload)
    assert payload.sub == "u-001"


def test_jwt_handler_creation_and_verification():
    """Test token creation, round-trip verification, and expiry handling."""
    cfg = AuthConfig(jwt_secret="my-custom-test-secret-32-chars-long", jwt_algorithm="HS256", jwt_expires_hours=1)
    handler = JWTHandler(config=cfg)

    # Valid token creation
    token = handler.create_token(user_id="u-42", username="alpha_user", role=Role.ADMIN, expires_hours=2)
    assert isinstance(token, str)
    assert len(token.split(".")) == 3

    # Verification
    verified = handler.verify_token(token)
    assert isinstance(verified, TokenPayload)
    assert verified.sub == "u-42"
    assert verified.username == "alpha_user"
    assert verified.role == Role.ADMIN.value
    assert "DELETE" in verified.permissions

    # Expired token test (expires_hours negative)
    expired_token = handler.create_token(user_id="u-exp", username="expired", role=Role.VIEWER, expires_hours=-1)
    assert handler.verify_token(expired_token) is None

    # Tampered / invalid token test
    tampered_token = token[:-5] + "XXXXX"
    assert handler.verify_token(tampered_token) is None
    assert handler.verify_token("invalid.token.structure") is None
    assert handler.verify_token("") is None


def test_jwt_handler_init_validation(monkeypatch):
    """Test constructor validations without secret key."""
    monkeypatch.delenv("JWT_SECRET_KEY", raising=False)
    monkeypatch.delenv("JWT_SECRET", raising=False)

    with pytest.raises(ValueError, match="JWT_SECRET_KEY ortam değişkeni ayarlanmamış"):
        JWTHandler(config=None, secret_key=None)

    with pytest.raises(ValueError, match="JWT secret key sağlanmalıdır"):
        JWTHandler(config=AuthConfig(jwt_secret=""))


def test_api_key_manager_crud():
    """Test registering, verifying, and revoking API keys."""
    mgr = APIKeyManager()

    api_key = "test-system-secret-key-123"
    mgr.register_key(api_key, service="signal_processor", permissions=["POST", "GET"])

    info = mgr.verify_key(api_key)
    assert info is not None
    assert info["service"] == "signal_processor"
    assert "POST" in info["permissions"]

    # Non-existent key
    assert mgr.verify_key("non-existent-key") is None

    # Revocation
    mgr.revoke_key(api_key)
    assert mgr.verify_key(api_key) is None


def test_rbac_checker_permissions():
    """Test RBAC permission matrix according to defined roles."""
    # VIEWER
    assert RBACChecker.check_permission(Role.VIEWER, "GET") is True
    assert RBACChecker.check_permission(Role.VIEWER, "POST") is False
    assert RBACChecker.check_permission(Role.VIEWER, "DELETE") is False

    # ANALYST
    assert RBACChecker.check_permission(Role.ANALYST, "GET") is True
    assert RBACChecker.check_permission(Role.ANALYST, "POST") is True
    assert RBACChecker.check_permission(Role.ANALYST, "PUT") is False

    # OPERATOR
    assert RBACChecker.check_permission(Role.OPERATOR, "GET") is True
    assert RBACChecker.check_permission(Role.OPERATOR, "PUT") is True
    assert RBACChecker.check_permission(Role.OPERATOR, "DELETE") is False

    # ADMIN
    assert RBACChecker.check_permission(Role.ADMIN, "GET") is True
    assert RBACChecker.check_permission(Role.ADMIN, "POST") is True
    assert RBACChecker.check_permission(Role.ADMIN, "PUT") is True
    assert RBACChecker.check_permission(Role.ADMIN, "DELETE") is True

    # Case insensitivity
    assert RBACChecker.check_permission(Role.VIEWER, "get") is True


def test_rbac_checker_endpoint_access():
    """Test sensitive endpoint protection rules."""
    # /admin/ endpoint
    assert RBACChecker.check_endpoint_access(Role.ADMIN, "/admin/users") is True
    assert RBACChecker.check_endpoint_access(Role.SYSTEM, "/admin/system_status") is True
    assert RBACChecker.check_endpoint_access(Role.OPERATOR, "/admin/users") is False
    assert RBACChecker.check_endpoint_access(Role.VIEWER, "/admin/users") is False

    # Operator endpoints (/rebalance, /promote, /restart)
    assert RBACChecker.check_endpoint_access(Role.OPERATOR, "/api/v1/portfolio/rebalance") is True
    assert RBACChecker.check_endpoint_access(Role.ADMIN, "/api/v1/models/promote") is True
    assert RBACChecker.check_endpoint_access(Role.VIEWER, "/api/v1/portfolio/rebalance") is False

    # Public / non-sensitive endpoint
    assert RBACChecker.check_endpoint_access(Role.VIEWER, "/api/v1/market/prices") is True


def test_singletons_availability():
    """Verify module-level singleton instances."""
    assert jwt_handler is not None
    assert api_key_manager is not None
    assert rbac_checker is not None
