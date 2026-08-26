"""
ALPHA BIST — API Authentication & Authorization v1.0

JWT + RBAC (Role-Based Access Control).

Roller:
- VIEWER: GET (dashboard, raporlar)
- ANALYST: GET + POST (analiz çalıştır)
- OPERATOR: GET + POST + PUT (emir, rebalance)
- ADMIN: Tüm endpoint'ler
- SYSTEM: Servisler arası (API key)
"""

import os
import time
import orjson
from typing import Dict, Any, Optional, List
from dataclasses import dataclass, field
from enum import Enum
import structlog
import jwt

from services.core.security import Role

logger = structlog.get_logger()


# Role → izin verilen HTTP method'ları
ROLE_PERMISSIONS: Dict[Role, List[str]] = {
    Role.VIEWER: ["GET"],
    Role.ANALYST: ["GET", "POST"],
    Role.OPERATOR: ["GET", "POST", "PUT"],
    Role.ADMIN: ["GET", "POST", "PUT", "DELETE"],
    Role.SYSTEM: ["GET", "POST", "PUT", "DELETE"],
}


@dataclass
class User:
    """Kullanıcı modeli."""
    user_id: str
    username: str
    role: Role
    permissions: List[str] = field(default_factory=list)
    is_active: bool = True


@dataclass
class TokenPayload:
    """JWT token payload."""
    sub: str  # user_id
    username: str
    role: str
    permissions: List[str]
    exp: float  # expiration timestamp
    iat: float  # issued at


class JWTHandler:
    """JWT token oluşturma ve doğrulama (PyJWT ile)."""

    def __init__(self, secret_key: str = None):
        self.secret_key = secret_key or os.environ.get("JWT_SECRET")
        if not self.secret_key:
            raise RuntimeError("JWT_SECRET environment variable is required")
        self.algorithm = "HS256"

    def create_token(
        self,
        user_id: str,
        username: str,
        role: Role,
        expires_hours: int = 24,
    ) -> str:
        """JWT token oluştur."""
        now = time.time()
        payload = {
            "sub": user_id,
            "username": username,
            "role": role.value,
            "permissions": ROLE_PERMISSIONS.get(role, []),
            "exp": now + (expires_hours * 3600),
            "iat": now,
        }
        return jwt.encode(payload, self.secret_key, algorithm=self.algorithm)

    def verify_token(self, token: str) -> Optional[TokenPayload]:
        """JWT token doğrula."""
        try:
            payload = jwt.decode(token, self.secret_key, algorithms=[self.algorithm])
            return TokenPayload(**payload)
        except jwt.ExpiredSignatureError:
            logger.warning("JWT token expired")
            return None
        except jwt.InvalidTokenError as e:
            logger.warning("JWT verification failed", error=str(e))
            return None


class APIKeyManager:
    """API key yönetimi (servisler arası)."""

    def __init__(self):
        self._keys: Dict[str, Dict[str, Any]] = {}

    def register_key(self, api_key: str, service: str, permissions: List[str]):
        """API key kaydet."""
        self._keys[api_key] = {
            "service": service,
            "permissions": permissions,
            "created_at": time.time(),
        }

    def verify_key(self, api_key: str) -> Optional[Dict[str, Any]]:
        """API key doğrula."""
        return self._keys.get(api_key)

    def revoke_key(self, api_key: str):
        """API key iptal et."""
        self._keys.pop(api_key, None)


class RBACChecker:
    """RBAC kontrolcüsü."""

    @staticmethod
    def check_permission(role: Role, method: str) -> bool:
        """Bu rol bu method'u kullanabilir mi?"""
        allowed = ROLE_PERMISSIONS.get(role, [])
        return method.upper() in allowed

    @staticmethod
    def check_endpoint_access(role: Role, endpoint: str) -> bool:
        """Bu rol bu endpoint'e erişebilir mi?"""
        # Admin endpoint'leri sadece ADMIN ve SYSTEM
        if endpoint.startswith("/admin/"):
            return role in [Role.ADMIN, Role.SYSTEM]

        # Write endpoint'leri OPERATOR+
        if endpoint.startswith("/api/v1/") and any(
            endpoint.endswith(suffix) for suffix in ["/rebalance", "/promote", "/restart"]
        ):
            return role in [Role.OPERATOR, Role.ADMIN, Role.SYSTEM]

        return True


# Singleton
jwt_handler = JWTHandler()
api_key_manager = APIKeyManager()
rbac_checker = RBACChecker()

# Varsayılan API key (environment variable'dan okunur)
_default_key = os.environ.get("SYSTEM_API_KEY")
if _default_key:
    api_key_manager.register_key(_default_key, "system", ["GET", "POST", "PUT", "DELETE"])
else:
    logger.warning("SYSTEM_API_KEY not set — inter-service auth disabled")
