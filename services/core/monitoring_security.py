"""
ALPHA BIST — Monitoring Security

Authentication ve authorization for monitoring endpoints.

Endpoint koruma seviyeleri:
- PUBLIC: /health, /health/detailed (kimlik doğrulama yok)
- METRICS: /metrics (Bearer token)
- ADMIN: /admin/* (Bearer token + admin role)

Token yönetimi:
- Monitoring token'ları environment variable'dan yüklenir
- Default token production'da değiştirilmeli
"""

import hmac
import os
import time
from dataclasses import dataclass, field
from typing import Any

import functools
import structlog
from opentelemetry import trace

logger = structlog.get_logger(__name__)
tracer = trace.get_tracer("alpha-bist.monitoring_security")

def otel_trace(span_name: str):
    """Decorator to wrap a method in an OTel span."""
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            with tracer.start_as_current_span(span_name):
                return func(*args, **kwargs)
        return wrapper
    return decorator


@dataclass
class AuthConfig:
    """Authentication yapılandırması."""

    metrics_token: str = ""
    admin_token: str = ""
    enabled: bool = True
    rate_limit_per_minute: int = 60


class MonitoringAuth:
    """Monitoring endpoint authentication."""

    def __init__(self, config: AuthConfig | None = None):
        self._config = config or AuthConfig()
        self._rate_limiter: dict[str, list] = {}
        self._failed_attempts: dict[str, int] = {}

        # Token'ları environment'dan yükle
        if not self._config.metrics_token:
            self._config.metrics_token = os.environ.get("ALPHA_METRICS_TOKEN", "alpha_metrics_default_2026")
        if not self._config.admin_token:
            self._config.admin_token = os.environ.get("ALPHA_ADMIN_TOKEN", "alpha_admin_default_2026")

        # Default token uyarısı
        if self._config.metrics_token == "alpha_metrics_default_2026":
            logger.warning("⚠️ DEFAULT metrics token in use! Set ALPHA_METRICS_TOKEN environment variable.")
        if self._config.admin_token == "alpha_admin_default_2026":
            logger.warning("⚠️ DEFAULT admin token in use! Set ALPHA_ADMIN_TOKEN environment variable.")

    @otel_trace("monitoring_security.verify_metrics_token")
    def verify_metrics_token(self, token: str) -> bool:
        """Metrics endpoint token doğrulama."""
        if not self._config.enabled:
            return True
        return self._constant_time_compare(token, self._config.metrics_token)

    @otel_trace("monitoring_security.verify_admin_token")
    def verify_admin_token(self, token: str) -> bool:
        """Admin endpoint token doğrulama."""
        if not self._config.enabled:
            return True
        return self._constant_time_compare(token, self._config.admin_token)

    @otel_trace("monitoring_security.check_rate_limit")
    def check_rate_limit(self, client_ip: str) -> bool:
        """Rate limit kontrolü (dakikada N istek)."""
        now = time.time()
        window_start = now - 60

        if client_ip not in self._rate_limiter:
            self._rate_limiter[client_ip] = []

        # Eski istekleri temizle
        self._rate_limiter[client_ip] = [t for t in self._rate_limiter[client_ip] if t > window_start]

        if len(self._rate_limiter[client_ip]) >= self._config.rate_limit_per_minute:
            logger.warning("Rate limit exceeded", client_ip=client_ip)
            return False

        self._rate_limiter[client_ip].append(now)
        return True

    @otel_trace("monitoring_security.record_failed_attempt")
    def record_failed_attempt(self, client_ip: str):
        """Başarısız girişimi kaydet."""
        self._failed_attempts[client_ip] = self._failed_attempts.get(client_ip, 0) + 1
        if self._failed_attempts[client_ip] > 10:
            logger.warning("Multiple failed auth attempts", client_ip=client_ip, count=self._failed_attempts[client_ip])

    @otel_trace("monitoring_security.get_auth_status")
    def get_auth_status(self) -> dict[str, Any]:
        """Authentication durumu."""
        return {
            "auth_enabled": self._config.enabled,
            "metrics_token_set": bool(self._config.metrics_token),
            "admin_token_set": bool(self._config.admin_token),
            "rate_limit_rpm": self._config.rate_limit_per_minute,
            "tracked_clients": len(self._rate_limiter),
            "failed_attempt_ips": len(self._failed_attempts),
        }

    @staticmethod
    def _constant_time_compare(a: str, b: str) -> bool:
        """Constant-time string comparison (timing attack prevention)."""
        if not a or not b:
            return False
        return hmac.compare_digest(a.encode(), b.encode())


# Token extraction helpers
@otel_trace("monitoring_security.extract_bearer_token")
def extract_bearer_token(authorization: str | None) -> str | None:
    """Authorization header'dan Bearer token çıkar."""
    if not authorization:
        return None
    parts = authorization.split()
    if len(parts) == 2 and parts[0].lower() == "bearer":
        return parts[1]
    return None


@otel_trace("monitoring_security.extract_api_key")
def extract_api_key(headers: dict) -> str | None:
    """X-API-Key header'dan key çıkar."""
    return headers.get("x-api-key") or headers.get("X-API-Key")


# =====================================================
# EXTENSIBLE AUTH INTERFACE
# =====================================================


class AuthProvider:
    """Extensible auth provider interface.

    OAuth/OIDC veya custom auth implementasyonları bu interface'i kullanır.

    Kullanım:
        class OAuthProvider(AuthProvider):
            async def verify(self, token, request) -> AuthResult: ...
    """

    @otel_trace("monitoring_security.AuthProvider.verify")
    async def verify(self, token: str, request_context: dict[str, Any] = None) -> "AuthResult":
        """Token doğrula."""
        raise NotImplementedError

    @otel_trace("monitoring_security.AuthProvider.name")
    def name(self) -> str:
        return self.__class__.__name__


@dataclass
class AuthResult:
    """Auth sonucu."""

    authenticated: bool
    user_id: str = ""
    roles: list[str] = field(default_factory=list)
    error: str = ""

    def has_role(self, role: str) -> bool:
        return role in self.roles


class StaticTokenProvider(AuthProvider):
    """Static token auth (mevcut sistem)."""

    def __init__(self, tokens: dict[str, list[str]]):
        """
        tokens: {"token_value": ["role1", "role2"], ...}
        """
        self._tokens = tokens

    @otel_trace("monitoring_security.StaticTokenProvider.verify")
    async def verify(self, token: str, request_context: dict[str, Any] = None) -> AuthResult:
        if not token:
            return AuthResult(authenticated=False, error="No token provided")

        for valid_token, roles in self._tokens.items():
            if hmac.compare_digest(token.encode(), valid_token.encode()):
                return AuthResult(authenticated=True, roles=roles)

        return AuthResult(authenticated=False, error="Invalid token")


class JWTProvider(AuthProvider):
    """JWT token doğrulama provider — JWKS desteği ile.

    Özellikler:
    - HS256/RS256 algoritma desteği
    - JWKS endpoint'ten public key çekme
    - Key cache ve refresh mekanizması
    - Expired/rotated key güvenli yönetimi
    - Token expiration kontrolü
    - Role extraction
    """

    def __init__(
        self,
        secret: str = "",
        algorithm: str = "HS256",
        issuer: str = "",
        audience: str = "",
        role_claim: str = "roles",
        jwks_url: str = "",
        jwks_cache_ttl_s: int = 3600,
    ):
        self._secret = secret
        self._algorithm = algorithm
        self._issuer = issuer
        self._audience = audience
        self._role_claim = role_claim
        self._jwks_url = jwks_url
        self._jwks_cache_ttl_s = jwks_cache_ttl_s
        self._jwks_cache: dict[str, Any] = {}
        self._jwks_last_fetch: float = 0

    @otel_trace("monitoring_security.JWTProvider.verify")
    async def verify(self, token: str, request_context: dict[str, Any] = None) -> AuthResult:
        if not token:
            return AuthResult(authenticated=False, error="No token")

        try:
            import jwt as pyjwt
        except ImportError:
            try:
                from jose import jwt as pyjwt
            except ImportError:
                return AuthResult(authenticated=False, error="PyJWT not installed")

        try:
            # Key seçimi
            key = await self._get_key(token, pyjwt)

            payload = pyjwt.decode(
                token,
                key,
                algorithms=[self._algorithm],
                issuer=self._issuer if self._issuer else None,
                audience=self._audience if self._audience else None,
                options={"verify_exp": True},
            )

            user_id = payload.get("sub", payload.get("user_id", ""))
            roles = payload.get(self._role_claim, [])
            if isinstance(roles, str):
                roles = [roles]

            return AuthResult(authenticated=True, user_id=user_id, roles=roles)

        except pyjwt.ExpiredSignatureError:
            return AuthResult(authenticated=False, error="Token expired")
        except getattr(pyjwt, "InvalidKeyError", ()):
            # Key rotation — cache temizle ve tekrar dene
            self._jwks_cache.clear()
            self._jwks_last_fetch = 0
            return AuthResult(authenticated=False, error="Key rotation detected, retry")
        except Exception as e:
            return AuthResult(authenticated=False, error=f"Invalid token: {e}")

    async def _get_key(self, token: str, pyjwt) -> str:
        """JWT için key al (HS256 secret veya RS256 JWKS)."""
        if self._algorithm == "HS256":
            return self._secret

        # RS256 — JWKS'den key çek
        if self._jwks_url:
            await self._refresh_jwks_if_needed()
            # Token header'dan kid al
            try:
                unverified = pyjwt.get_unverified_header(token)
                kid = unverified.get("kid", "")
                if kid and kid in self._jwks_cache:
                    return self._jwks_cache[kid]
            except Exception as e:
                logger.debug("Handled exception", error=str(e), context="monitoring_security.py:268")

        return self._secret

    async def _refresh_jwks_if_needed(self):
        """JWKS cache'ini yenile (TTL kontrolü)."""
        now = time.time()
        if now - self._jwks_last_fetch < self._jwks_cache_ttl_s:
            return

        try:
            import aiohttp

            async with (
                aiohttp.ClientSession() as session,
                session.get(
                    self._jwks_url,
                    timeout=aiohttp.ClientTimeout(total=10),
                ) as resp,
            ):
                if resp.status == 200:
                    jwks = await resp.json()
                    for key in jwks.get("keys", []):
                        kid = key.get("kid", "")
                        if kid:
                            self._jwks_cache[kid] = key
                    self._jwks_last_fetch = now
                    logger.info("JWKS refreshed", keys=len(self._jwks_cache))
        except Exception as e:
            logger.warning("JWKS refresh failed", error=str(e))


class OAuthProvider(AuthProvider):
    """OAuth/OIDC auth provider.

    JWT validation + role-based authorization.
    """

    def __init__(
        self, issuer: str = "", audience: str = "", jwks_url: str = "", secret: str = "", role_claim: str = "roles"
    ):
        self._issuer = issuer
        self._audience = audience
        self._jwks_url = jwks_url
        self._secret = secret
        self._role_claim = role_claim
        self._jwt_provider = JWTProvider(
            secret=secret,
            issuer=issuer,
            audience=audience,
            role_claim=role_claim,
        )

    @otel_trace("monitoring_security.OAuthProvider.verify")
    async def verify(self, token: str, request_context: dict[str, Any] = None) -> AuthResult:
        if not self._secret:
            return AuthResult(authenticated=False, error="OAuth not configured (no secret)")
        return await self._jwt_provider.verify(token, request_context)


# Role → permission mapping
ROLE_PERMISSIONS = {
    "admin": ["read", "write", "admin", "metrics", "alerts", "portfolio"],
    "operator": ["read", "write", "metrics", "alerts", "portfolio"],
    "viewer": ["read", "metrics"],
}


class AuthManager:
    """Çoklu auth provider yöneticisi + RBAC."""

    def __init__(self):
        self._providers: list[AuthProvider] = []

    @otel_trace("monitoring_security.AuthManager.add_provider")
    def add_provider(self, provider: AuthProvider):
        self._providers.append(provider)
        if len(self._providers) > 100:
            self._providers = self._providers[-100:]

    @otel_trace("monitoring_security.AuthManager.verify")
    async def verify(self, token: str, request_context: dict[str, Any] = None) -> AuthResult:
        """Tüm provider'ları dene — ilk başarılı olanı döndür."""
        for provider in self._providers:
            result = await provider.verify(token, request_context)
            if result.authenticated:
                return result
        return AuthResult(authenticated=False, error="No provider authenticated the token")

    @otel_trace("monitoring_security.AuthManager.verify_permission")
    async def verify_permission(self, token: str, permission: str) -> AuthResult:
        """Token doğrula + belirli bir permission kontrolü."""
        result = await self.verify(token)
        if not result.authenticated:
            return result

        # Role-based permission check
        for role in result.roles:
            perms = ROLE_PERMISSIONS.get(role, [])
            if permission in perms or "admin" in perms:
                return result

        return AuthResult(
            authenticated=True,
            user_id=result.user_id,
            roles=result.roles,
            error=f"Permission denied: {permission} (roles: {result.roles})",
        )

    @otel_trace("monitoring_security.AuthManager.get_providers")
    def get_providers(self) -> list[str]:
        return [p.name() for p in self._providers]


# Singleton instances
monitoring_auth = MonitoringAuth()
auth_manager = AuthManager()
