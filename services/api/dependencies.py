"""
ALPHA BIST — API Dependencies v1.0

FastAPI dependency injection.
Auth, rate limiting, service resolution.
"""

import time
from typing import Optional, Dict, Any
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
import structlog

from .auth import jwt_handler, api_key_manager, rbac_checker, Role, TokenPayload
from .rate_limiter import rate_limiter

logger = structlog.get_logger()

security = HTTPBearer(auto_error=False)


async def get_client_id(request: Request) -> str:
    """İstemci kimliğini belirle."""
    # X-Forwarded-For (proxy arkasında)
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()

    # X-Real-IP
    real_ip = request.headers.get("X-Real-IP")
    if real_ip:
        return real_ip

    # Doğrudan IP
    if request.client:
        return request.client.host

    return "unknown"


async def get_current_user(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
    client_id: str = Depends(get_client_id),
) -> TokenPayload:
    """Mevcut kullanıcıyı doğrula (JWT veya API key)."""
    path = request.url.path
    method = request.method

    # API key kontrolü
    api_key = request.headers.get("X-API-Key")
    if api_key:
        key_info = api_key_manager.verify_key(api_key)
        if key_info:
            return TokenPayload(
                sub="system",
                username=key_info["service"],
                role=Role.SYSTEM.value,
                permissions=key_info["permissions"],
                exp=time.time() + 3600,
                iat=time.time(),
            )

    # JWT token kontrolü
    if credentials:
        payload = jwt_handler.verify_token(credentials.credentials)
        if payload:
            # RBAC kontrolü
            role = Role(payload.role)
            if not rbac_checker.check_permission(role, method):
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=f"Role {role.value} cannot use {method}",
                )
            if not rbac_checker.check_endpoint_access(role, path):
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=f"Role {role.value} cannot access {path}",
                )
            return payload

    # Health ve docs endpoint'leri auth gerektirmez
    if path in ["/health", "/docs", "/openapi.json", "/redoc", "/"]:
        return TokenPayload(
            sub="anonymous",
            username="anonymous",
            role=Role.VIEWER.value,
            permissions=["GET"],
            exp=time.time() + 3600,
            iat=time.time(),
        )

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Authentication required",
        headers={"WWW-Authenticate": "Bearer"},
    )


async def check_rate_limit(
    request: Request,
    client_id: str = Depends(get_client_id),
    user: TokenPayload = Depends(get_current_user),
) -> None:
    """Rate limit kontrolü."""
    path = request.url.path
    method = request.method

    group = rate_limiter.get_endpoint_group(path, method)
    allowed, info = await rate_limiter.check(client_id, group)

    if not allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Rate limit exceeded. Retry after {info.get('retry_after', 60)}s",
            headers={"Retry-After": str(info.get("retry_after", 60))},
        )


async def require_role(required_roles: list[Role]):
    """Belirli roller gerektiren dependency."""
    async def checker(
        user: TokenPayload = Depends(get_current_user),
    ) -> TokenPayload:
        role = Role(user.role)
        if role not in required_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Required roles: {[r.value for r in required_roles]}",
            )
        return user
    return checker


async def get_service_orchestrator():
    """Orchestrator servisini getir."""
    from services.core.orchestrator import MasterOrchestrator
    orch = MasterOrchestrator()
    if not orch._initialized:
        await orch.initialize()
    return orch
