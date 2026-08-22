"""
ALPHA BIST — JWT Token Manager

JWT tabanlı kimlik doğrulama ve yetkilendirme.

Özellikler:
1. JWT token generation (HS256)
2. Token validation ve decoding
3. Token refresh
4. API key management
5. Secret rotation support

Referanslar:
- CORE-NIHAI-SPEC.md - Section 2.4
- RFC 7519 (JWT)
"""

import hashlib
import hmac
import os
import secrets
import json
import base64
import time
from typing import Dict, List, Optional, Any, Set
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from enum import Enum
import structlog

logger = structlog.get_logger()


class TokenType(str, Enum):
    ACCESS = "access"
    REFRESH = "refresh"
    API_KEY = "api_key"


@dataclass
class JWTClaims:
    """JWT claims."""
    sub: str  # user_id
    role: str
    permissions: List[str]
    token_type: TokenType = TokenType.ACCESS
    issued_at: float = field(default_factory=time.time)
    expires_at: float = 0.0
    jti: str = field(default_factory=lambda: secrets.token_hex(8))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "sub": self.sub,
            "role": self.role,
            "permissions": self.permissions,
            "type": self.token_type.value,
            "iat": self.issued_at,
            "exp": self.expires_at,
            "jti": self.jti,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "JWTClaims":
        return cls(
            sub=data.get("sub", ""),
            role=data.get("role", ""),
            permissions=data.get("permissions", []),
            token_type=TokenType(data.get("type", "access")),
            issued_at=data.get("iat", 0),
            expires_at=data.get("exp", 0),
            jti=data.get("jti", ""),
        )

    @property
    def is_expired(self) -> bool:
        return time.time() > self.expires_at


class JWTError(Exception):
    """JWT hataları."""
    pass


class JWTManager:
    """
    JWT token yöneticisi.

    HMAC-SHA256 ile token imzalama ve doğrulama.

    Kullanım:
        jwt_mgr = JWTManager("my-secret-key")
        token = jwt_mgr.generate_token("user123", "ADMIN", ["READ", "WRITE"])
        claims = jwt_mgr.validate_token(token)
    """

    def __init__(
        self,
        secret_key: str = None,
        access_token_ttl_hours: int = 24,
        refresh_token_ttl_days: int = 7,
        algorithm: str = "HS256",
    ):
        self._secret = secret_key or os.environ.get("JWT_SECRET", "")
        self._access_ttl = timedelta(hours=access_token_ttl_hours)
        self._refresh_ttl = timedelta(days=refresh_token_ttl_days)
        self._algorithm = algorithm
        self._revoked_tokens: Set[str] = set()  # revoked JTIs

    def generate_token(
        self,
        user_id: str,
        role: str,
        permissions: List[str],
        token_type: TokenType = TokenType.ACCESS,
        custom_claims: Optional[Dict[str, Any]] = None,
    ) -> str:
        """
        JWT token oluştur.

        Args:
            user_id: Kullanıcı ID
            role: Kullanıcı rolü
            permissions: İzin listesi
            token_type: Token tipi (access/refresh)
            custom_claims: Ek claims

        Returns:
            JWT token string
        """
        now = time.time()
        ttl = self._access_ttl if token_type == TokenType.ACCESS else self._refresh_ttl

        claims = JWTClaims(
            sub=user_id,
            role=role,
            permissions=permissions,
            token_type=token_type,
            issued_at=now,
            expires_at=now + ttl.total_seconds(),
        )

        # Header
        header = {"alg": self._algorithm, "typ": "JWT"}
        header_b64 = self._base64url_encode(json.dumps(header).encode())

        # Payload
        payload = claims.to_dict()
        if custom_claims:
            payload.update(custom_claims)
        payload_b64 = self._base64url_encode(json.dumps(payload).encode())

        # Signature
        message = f"{header_b64}.{payload_b64}"
        signature = self._sign(message)
        sig_b64 = self._base64url_encode(signature)

        token = f"{header_b64}.{payload_b64}.{sig_b64}"

        logger.debug("JWT token generated",
                    user_id=user_id,
                    role=role,
                    type=token_type.value,
                    expires_in=ttl)

        return token

    def validate_token(self, token: str) -> JWTClaims:
        """
        Token'ı doğrula ve claims döndür.

        Args:
            token: JWT token string

        Returns:
            JWTClaims

        Raises:
            JWTError: Token geçersiz veya süresi dolmuş
        """
        try:
            parts = token.split(".")
            if len(parts) != 3:
                raise JWTError("Invalid token format")

            header_b64, payload_b64, sig_b64 = parts

            # Verify signature
            message = f"{header_b64}.{payload_b64}"
            expected_sig = self._sign(message)
            actual_sig = self._base64url_decode(sig_b64)

            if not hmac.compare_digest(expected_sig, actual_sig):
                raise JWTError("Invalid signature")

            # Decode payload
            payload_bytes = self._base64url_decode(payload_b64)
            payload = json.loads(payload_bytes)

            claims = JWTClaims.from_dict(payload)

            # Check expiration
            if claims.is_expired:
                raise JWTError("Token expired")

            # Check revocation
            if claims.jti in self._revoked_tokens:
                raise JWTError("Token revoked")

            return claims

        except JWTError:
            raise
        except Exception as e:
            raise JWTError(f"Token validation failed: {e}")

    def refresh_token(self, token: str) -> str:
        """
        Refresh token ile yeni access token oluştur.

        Args:
            token: Refresh token

        Returns:
            Yeni access token

        Raises:
            JWTError: Refresh token geçersiz
        """
        claims = self.validate_token(token)

        if claims.token_type != TokenType.REFRESH:
            raise JWTError("Not a refresh token")

        # Generate new access token
        return self.generate_token(
            user_id=claims.sub,
            role=claims.role,
            permissions=claims.permissions,
            token_type=TokenType.ACCESS,
        )

    def revoke_token(self, token: str) -> bool:
        """Token'ı iptal et."""
        try:
            claims = self.validate_token(token)
            self._revoked_tokens.add(claims.jti)
            logger.info("Token revoked", user_id=claims.sub, jti=claims.jti)
            return True
        except JWTError:
            return False

    def generate_api_key(
        self,
        user_id: str,
        role: str,
        permissions: List[str],
        name: str = "default",
    ) -> str:
        """
        API key oluştur (sınırsız süreli).

        Args:
            user_id: Kullanıcı ID
            role: Rol
            permissions: İzinler
            key name: Key adı

        Returns:
            API key string
        """
        claims = JWTClaims(
            sub=user_id,
            role=role,
            permissions=permissions,
            token_type=TokenType.API_KEY,
            expires_at=time.time() + 365 * 24 * 3600,  # 1 yıl
        )

        header = {"alg": self._algorithm, "typ": "JWT"}
        header_b64 = self._base64url_encode(json.dumps(header).encode())
        payload_b64 = self._base64url_encode(json.dumps(claims.to_dict()).encode())

        message = f"{header_b64}.{payload_b64}"
        signature = self._sign(message)
        sig_b64 = self._base64url_encode(signature)

        api_key = f"ak_{header_b64}.{payload_b64}.{sig_b64}"

        logger.info("API key generated",
                    user_id=user_id,
                    name=name,
                    role=role)

        return api_key

    def rotate_secret(self, new_secret: str):
        """
        Secret key'i değiştir.

        Not: Mevcut token'lar geçersiz olur.
        """
        old_secret_preview = self._secret[:8] + "..."
        self._secret = new_secret
        logger.warning("JWT secret rotated",
                      old_secret_preview=old_secret_preview)

    def _sign(self, message: str) -> bytes:
        """HMAC-SHA256 ile imzala."""
        import hashlib as hl
        return hmac.new(
            self._secret.encode(),
            message.encode(),
            hl.sha256
        ).digest()

    @staticmethod
    def _base64url_encode(data: bytes) -> str:
        """Base64url encoding (JWT standard)."""
        return base64.urlsafe_b64encode(data).rstrip(b"=").decode()

    @staticmethod
    def _base64url_decode(s: str) -> bytes:
        """Base64url decoding."""
        # Padding ekle
        padding = 4 - len(s) % 4
        if padding != 4:
            s += "=" * padding
        return base64.urlsafe_b64decode(s)


# Singleton
jwt_manager = JWTManager()
