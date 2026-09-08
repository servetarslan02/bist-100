"""Comprehensive unit tests for services.api.dependencies and background_tasks."""

from __future__ import annotations

import asyncio
import time
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials

from services.api.auth import Role, TokenPayload, api_key_manager, jwt_handler
from services.api.background_tasks import (
    ml_learning_scheduler,
)
from services.api.dependencies import (
    check_rate_limit,
    get_client_id,
    get_current_user,
    require_role,
)


def _build_mock_request(
    path: str = "/api/v1/market/prices",
    method: str = "GET",
    headers: dict[str, str] | None = None,
    client_host: str = "192.168.1.100",
) -> Request:
    """Build mock FastAPI request."""
    req = MagicMock(spec=Request)
    req.url.path = path
    req.method = method
    req.headers = headers or {}
    req.client.host = client_host
    return req


@pytest.mark.asyncio
async def test_get_client_id_variations():
    """Verify IP extraction from X-Forwarded-For, X-Real-IP, and direct client."""
    # X-Forwarded-For
    req1 = _build_mock_request(headers={"X-Forwarded-For": "203.0.113.195, 70.41.3.18"})
    assert await get_client_id(req1) == "203.0.113.195"

    # X-Real-IP
    req2 = _build_mock_request(headers={"X-Real-IP": "198.51.100.1"})
    assert await get_client_id(req2) == "198.51.100.1"

    # Direct client
    req3 = _build_mock_request(client_host="10.0.0.5")
    assert await get_client_id(req3) == "10.0.0.5"

    # Unknown
    req4 = _build_mock_request()
    req4.client = None
    assert await get_client_id(req4) == "unknown"


@pytest.mark.asyncio
async def test_get_current_user_api_key():
    """Verify system authentication via X-API-Key."""
    test_key = "secret-sys-key-test"
    api_key_manager.register_key(test_key, service="order_service", permissions=["GET", "POST"])

    try:
        req = _build_mock_request(headers={"X-API-Key": test_key})
        user = await get_current_user(request=req, credentials=None, client_id="127.0.0.1")
        assert isinstance(user, TokenPayload)
        assert user.sub == "system"
        assert user.username == "order_service"
        assert user.role == Role.SYSTEM.value
    finally:
        api_key_manager.revoke_key(test_key)


@pytest.mark.asyncio
async def test_get_current_user_jwt_valid_and_rbac_violation():
    """Verify JWT parsing and method/endpoint RBAC violations."""
    token = jwt_handler.create_token(user_id="usr_view", username="viewer", role=Role.VIEWER)
    creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)

    # Valid GET on market
    req_get = _build_mock_request(path="/api/v1/market/prices", method="GET")
    user = await get_current_user(request=req_get, credentials=creds, client_id="127.0.0.1")
    assert user.username == "viewer"

    # Method RBAC violation (POST not allowed for VIEWER)
    req_post = _build_mock_request(path="/api/v1/market/order", method="POST")
    with pytest.raises(HTTPException) as exc_info:
        await get_current_user(request=req_post, credentials=creds, client_id="127.0.0.1")
    assert exc_info.value.status_code == status.HTTP_403_FORBIDDEN

    # Endpoint RBAC violation (/admin not allowed for VIEWER)
    req_admin = _build_mock_request(path="/admin/users", method="GET")
    with pytest.raises(HTTPException) as exc_info2:
        await get_current_user(request=req_admin, credentials=creds, client_id="127.0.0.1")
    assert exc_info2.value.status_code == status.HTTP_403_FORBIDDEN


@pytest.mark.asyncio
async def test_get_current_user_strict_and_public_paths(monkeypatch):
    """Verify public endpoints and strict vs relaxed mode."""
    # Public path /health allows anonymous
    req_health = _build_mock_request(path="/health", method="GET")
    user_anon = await get_current_user(request=req_health, credentials=None, client_id="127.0.0.1")
    assert user_anon.username == "public"

    # Relaxed non-strict mode gives dashboard_user
    monkeypatch.setenv("AUTH_STRICT", "false")
    req_protected = _build_mock_request(path="/api/v1/trade", method="POST")
    user_relaxed = await get_current_user(request=req_protected, credentials=None, client_id="127.0.0.1")
    assert user_relaxed.username == "dashboard_user"

    # Strict mode raises 401
    monkeypatch.setenv("AUTH_STRICT", "true")
    with pytest.raises(HTTPException) as exc:
        await get_current_user(request=req_protected, credentials=None, client_id="127.0.0.1")
    assert exc.value.status_code == status.HTTP_401_UNAUTHORIZED


@pytest.mark.asyncio
async def test_require_role_dependency():
    """Verify require_role wrapper enforcement."""
    role_checker = await require_role([Role.ADMIN, Role.OPERATOR])

    admin_payload = TokenPayload(
        sub="1",
        username="admin",
        role=Role.ADMIN.value,
        permissions=["ALL"],
        exp=time.time() + 3600,
        iat=time.time(),
    )
    viewer_payload = TokenPayload(
        sub="2",
        username="view",
        role=Role.VIEWER.value,
        permissions=["GET"],
        exp=time.time() + 3600,
        iat=time.time(),
    )

    # Allowed
    res = await role_checker(user=admin_payload)
    assert res == admin_payload

    # Forbidden
    with pytest.raises(HTTPException) as exc:
        await role_checker(user=viewer_payload)
    assert exc.value.status_code == status.HTTP_403_FORBIDDEN


@pytest.mark.asyncio
async def test_check_rate_limit_dependency():
    """Verify check_rate_limit dependency integration."""
    req = _build_mock_request()
    admin_payload = TokenPayload(
        sub="1",
        username="admin",
        role=Role.ADMIN.value,
        permissions=["ALL"],
        exp=time.time() + 3600,
        iat=time.time(),
    )

    # Should run without error
    await check_rate_limit(request=req, client_id="test_client_dep", user=admin_payload)


@pytest.mark.asyncio
async def test_background_tasks_structure():
    """Verify background task coroutines initialize without immediate crash."""
    # Run coroutine with short timeout
    with pytest.raises(asyncio.TimeoutError):
        await asyncio.wait_for(ml_learning_scheduler(), timeout=0.01)
