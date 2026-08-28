"""
ALPHA BIST — API Authentication & Authorization v2.0 (Enterprise Refactored)

JWT + RBAC (Role-Based Access Control).
Provides SOLID, DI-compatible, memory-optimized authentication handlers.

Roller:
- VIEWER: GET (dashboard, raporlar)
- ANALYST: GET + POST (analiz çalıştır)
- OPERATOR: GET + POST + PUT (emir, rebalance)
- ADMIN: Tüm endpoint'ler
- SYSTEM: Servisler arası (API key)
"""

import base64
import hashlib
import hmac
import os
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import orjson
import structlog

# Optional PyJWT dependency
try:
    import jwt
    HAS_JWT = True
except ImportError:
    jwt = None
    HAS_JWT = False

from services.core.security import Role
from services.core.otel import get_tracer

logger = structlog.get_logger(__name__)
tracer = get_tracer(__name__)


# Role → izin verilen HTTP method'ları
ROLE_PERMISSIONS: Dict[Role, List[str]] = {
    Role.VIEWER: ["GET"],
    Role.ANALYST: ["GET", "POST"],
    Role.OPERATOR: ["GET", "POST", "PUT"],
    Role.ADMIN: ["GET", "POST", "PUT", "DELETE"],
    Role.SYSTEM: ["GET", "POST", "PUT", "DELETE"],
}


@dataclass(frozen=True)
class AuthConfig:
    """
    Configuration model for authentication.
    Supports Dependency Injection by uncoupling from direct environment variable access.
    """
    jwt_secret: str
    jwt_algorithm: str = "HS256"
    jwt_expires_hours: int = 24


@dataclass
class User:
    """
    Represents an authenticated user in the system.
    """
    user_id: str
    username: str
    role: Role
    permissions: List[str] = field(default_factory=list)
    is_active: bool = True


@dataclass
class TokenPayload:
    """
    Represents the parsed payload from a valid JWT token.
    """
    sub: str          # user_id
    username: str
    role: str
    permissions: List[str]
    exp: float        # expiration timestamp
    iat: float        # issued at


class JWTHandler:
    """
    Handles generation and validation of JWT tokens.
    Uses Dependency Injection for configuration to adhere to SOLID principles.
    """

    def __init__(self, config: AuthConfig) -> None:
        """
        Initializes the JWT Handler.

        Args:
            config (AuthConfig): Injected authentication configuration.
        """
        if not config.jwt_secret:
            raise ValueError("JWT secret key must be provided in AuthConfig.")
        self.config = config

    def create_token(
        self,
        user_id: str,
        username: str,
        role: Role,
    ) -> str:
        """
        Creates a JWT token for the specified user and role.

        Args:
            user_id (str): Unique user identifier.
            username (str): Username.
            role (Role): Assigned user role.

        Returns:
            str: Encoded JWT string.
        """
        with tracer.start_as_current_span("auth.create_token") as span:
            now = time.time()
            role_value = role.value if hasattr(role, "value") else str(role)
            span.set_attribute("user.id", user_id)
            span.set_attribute("user.role", role_value)

            payload = {
                "sub": user_id,
                "username": username,
                "role": role_value,
                "permissions": ROLE_PERMISSIONS.get(role, []),
                "exp": now + (self.config.jwt_expires_hours * 3600),
                "iat": now,
            }

            if HAS_JWT and jwt is not None:
                return jwt.encode(payload, self.config.jwt_secret, algorithm=self.config.jwt_algorithm)

            return self._create_fallback_token(payload)

    def _create_fallback_token(self, payload: Dict[str, Any]) -> str:
        """
        Creates a token using HMAC and standard libraries when PyJWT is not available.
        """
        header = base64.urlsafe_b64encode(b'{"alg":"HS256","typ":"JWT"}').decode().rstrip("=")
        body = base64.urlsafe_b64encode(orjson.dumps(payload)).decode().rstrip("=")
        to_sign = f"{header}.{body}".encode()
        
        sig = base64.urlsafe_b64encode(
            hmac.new(self.config.jwt_secret.encode(), to_sign, hashlib.sha256).digest()
        ).decode().rstrip("=")
        
        return f"{header}.{body}.{sig}"

    def verify_token(self, token: str) -> Optional[TokenPayload]:
        """
        Verifies and parses a JWT token.

        Args:
            token (str): The JWT string to verify.

        Returns:
            Optional[TokenPayload]: Parsed payload if valid, None otherwise.
        """
        with tracer.start_as_current_span("auth.verify_token") as span:
            if not token or not isinstance(token, str):
                logger.warning("Invalid token format provided.")
                return None

            if HAS_JWT and jwt is not None:
                try:
                    payload = jwt.decode(token, self.config.jwt_secret, algorithms=[self.config.jwt_algorithm])
                    return TokenPayload(**payload)
                except jwt.ExpiredSignatureError:
                    logger.warning("JWT token expired.")
                    return None
                except jwt.InvalidTokenError as e:
                    logger.warning("JWT verification failed.", error=str(e))
                    return None

            return self._verify_fallback_token(token)

    def _verify_fallback_token(self, token: str) -> Optional[TokenPayload]:
        """
        Verifies an HMAC token when PyJWT is not available.
        Ensures strict, constant-time signature comparison.
        """
        try:
            parts = token.split(".")
            if len(parts) != 3:
                return None
            
            header, body, sig = parts
            to_sign = f"{header}.{body}".encode()
            
            expected_sig = base64.urlsafe_b64encode(
                hmac.new(self.config.jwt_secret.encode(), to_sign, hashlib.sha256).digest()
            ).decode().rstrip("=")
            
            if not hmac.compare_digest(sig, expected_sig):
                logger.warning("JWT signature mismatch.")
                return None

            rem = len(body) % 4
            if rem > 0:
                body += "=" * (4 - rem)
                
            payload_data = orjson.loads(base64.urlsafe_b64decode(body.encode()))
            if payload_data.get("exp", 0) < time.time():
                logger.warning("JWT token expired.")
                return None
                
            return TokenPayload(**payload_data)
        except Exception as e:
            logger.warning("Fallback JWT verification failed.", error=str(e))
            return None


class APIKeyManager:
    """
    Manages API keys for inter-service authentication.
    """

    def __init__(self) -> None:
        """Initializes the API Key Manager with an empty store."""
        self._keys: Dict[str, Dict[str, Any]] = {}

    def register_key(self, api_key: str, service: str, permissions: List[str]) -> None:
        """
        Registers a new API key.

        Args:
            api_key (str): The API key string.
            service (str): The name of the service owning the key.
            permissions (List[str]): List of allowed HTTP methods.
        """
        self._keys[api_key] = {
            "service": service,
            "permissions": permissions,
            "created_at": time.time(),
        }

    def verify_key(self, api_key: str) -> Optional[Dict[str, Any]]:
        """
        Verifies if an API key exists and is valid.

        Args:
            api_key (str): The API key to verify.

        Returns:
            Optional[Dict[str, Any]]: The key metadata if valid, None otherwise.
        """
        with tracer.start_as_current_span("auth.verify_key"):
            return self._keys.get(api_key)

    def revoke_key(self, api_key: str) -> None:
        """
        Revokes an active API key.

        Args:
            api_key (str): The API key to revoke.
        """
        self._keys.pop(api_key, None)


class RBACChecker:
    """
    Handles Role-Based Access Control logic and endpoint permission validation.
    """

    @staticmethod
    def check_permission(role: Role, method: str) -> bool:
        """
        Checks if a given role is allowed to execute a specific HTTP method.

        Args:
            role (Role): The role to check.
            method (str): The HTTP method (e.g., 'GET', 'POST').

        Returns:
            bool: True if allowed, False otherwise.
        """
        allowed = ROLE_PERMISSIONS.get(role, [])
        return method.upper() in allowed

    @staticmethod
    def check_endpoint_access(role: Role, endpoint: str) -> bool:
        """
        Checks if a role has structural access to specific sensitive endpoints.

        Args:
            role (Role): The user's role.
            endpoint (str): The requested API endpoint path.

        Returns:
            bool: True if access is permitted, False otherwise.
        """
        if endpoint.startswith("/admin/"):
            return role in [Role.ADMIN, Role.SYSTEM]

        if endpoint.startswith("/api/v1/") and any(
            endpoint.endswith(suffix) for suffix in ["/rebalance", "/promote", "/restart"]
        ):
            return role in [Role.OPERATOR, Role.ADMIN, Role.SYSTEM]

        return True


# Global instances (Legacy Support/Simple Container)
# In a full DI framework, these would be managed by the IoC container.
_jwt_secret = os.environ.get("JWT_SECRET", "fallback-secret-for-development-only")
_default_config = AuthConfig(jwt_secret=_jwt_secret)

jwt_handler = JWTHandler(_default_config)
api_key_manager = APIKeyManager()
rbac_checker = RBACChecker()

_default_key = os.environ.get("SYSTEM_API_KEY")
if _default_key:
    api_key_manager.register_key(_default_key, "system", ["GET", "POST", "PUT", "DELETE"])
else:
    logger.warning("SYSTEM_API_KEY not set — inter-service auth disabled.")
