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

import time
import hashlib
import hmac
from typing import Dict, Any, Optional, List
from dataclasses import dataclass, field
from enum import Enum
import structlog

logger = structlog.get_logger()


class Role(str, Enum):
    VIEWER = "VIEWER"
    ANALYST = "ANALYST"
    OPERATOR = "OPERATOR"
    ADMIN = "ADMIN"
    SYSTEM = "SYSTEM"


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
    """JWT token oluşturma ve doğrulama.

    Not: Gerçek production'da PyJWT veya python-jose kullanılır.
    Bu implementasyon basit HMAC-SHA256 tabanlıdır.
    """

    def __init__(self, secret_key: str = "alpha-bist-secret-key-change-in-production"):
        self.secret_key = secret_key
        self.algorithm = "HS256"

    def create_token(
        self,
        user_id: str,
        username: str,
        role: Role,
        expires_hours: int = 24,
    ) -> str:
        """JWT token oluştur."""
        import json
        import base64

        now = time.time()
        payload = {
            "sub": user_id,
            "username": username,
            "role": role.value,
            "permissions": ROLE_PERMISSIONS.get(role, []),
            "exp": now + (expires_hours * 3600),
            "iat": now,
        }

        # Header
        header = base64.urlsafe_b64encode(
            json.dumps({"alg": self.algorithm, "typ": "JWT"}).encode()
        ).decode().rstrip("=")

        # Payload
        payload_b64 = base64.urlsafe_b64encode(
            json.dumps(payload).encode()
        ).decode().rstrip("=")

        # Signature
        message = f"{header}.{payload_b64}"
        signature = hmac.new(
            self.secret_key.encode(),
            message.encode(),
            hashlib.sha256
        ).digest()
        signature_b64 = base64.urlsafe_b64encode(signature).decode().rstrip("=")

        return f"{header}.{payload_b64}.{signature_b64}"

    def verify_token(self, token: str) -> Optional[TokenPayload]:
        """JWT token doğrula."""
        import json
        import base64

        try:
            parts = token.split(".")
            if len(parts) != 3:
                return None

            header_b64, payload_b64, signature_b64 = parts

            # Signature doğrula
            message = f"{header_b64}.{payload_b64}"
            expected_sig = hmac.new(
                self.secret_key.encode(),
                message.encode(),
                hashlib.sha256
            ).digest()
            expected_b64 = base64.urlsafe_b64encode(expected_sig).decode().rstrip("=")

            if not hmac.compare_digest(signature_b64, expected_b64):
                logger.warning("Invalid JWT signature")
                return None

            # Payload decode
            padding = 4 - len(payload_b64) % 4
            if padding != 4:
                payload_b64 += "=" * padding

            payload = json.loads(base64.urlsafe_b64decode(payload_b64))

            # Expiration kontrolü
            if payload.get("exp", 0) < time.time():
                logger.warning("JWT token expired")
                return None

            return TokenPayload(**payload)

        except Exception as e:
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

# Varsayılan API key'ler (production'da değiştirilmeli)
api_key_manager.register_key(
    "alpha-system-key-change-me",
    "system",
    ["GET", "POST", "PUT", "DELETE"],
)
