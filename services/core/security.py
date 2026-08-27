"""
ALPHA BIST — Security & Governance v1.0

- Authentication (session/token)
- Authorization (RBAC)
- API Security
- Secret Redaction
- Safety Governance
- System State Machine
"""

import hashlib
import hmac
import re
import secrets

# passlib for better password hashing (optional, fallback to hashlib)
try:
    from passlib.context import CryptContext
    _pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
    _USE_PASSLIB = True
except ImportError:
    _USE_PASSLIB = False

# cryptography for encryption utilities (optional)
try:
    from cryptography.fernet import Fernet
    _USE_CRYPTO = True
except ImportError:
    _USE_CRYPTO = False
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Any

import structlog

logger = structlog.get_logger()


class Role(StrEnum):
    VIEWER = "VIEWER"
    ANALYST = "ANALYST"
    OPERATOR = "OPERATOR"
    ADMIN = "ADMIN"
    SYSTEM = "SYSTEM"


class Permission(StrEnum):
    READ_MARKET = "READ_MARKET"
    READ_PORTFOLIO = "READ_PORTFOLIO"
    RUN_BACKTEST = "RUN_BACKTEST"
    RUN_SCENARIO = "RUN_SCENARIO"
    CHANGE_CONFIG = "CHANGE_CONFIG"
    PROMOTE_MODEL = "PROMOTE_MODEL"
    LIVE_EXECUTION = "LIVE_EXECUTION"
    MANAGE_USERS = "MANAGE_USERS"


# Role → Permission mapping
ROLE_PERMISSIONS: dict[Role, set[Permission]] = {
    Role.VIEWER: {Permission.READ_MARKET, Permission.READ_PORTFOLIO},
    Role.ANALYST: {Permission.READ_MARKET, Permission.READ_PORTFOLIO, Permission.RUN_BACKTEST, Permission.RUN_SCENARIO},
    Role.OPERATOR: {Permission.READ_MARKET, Permission.READ_PORTFOLIO, Permission.RUN_BACKTEST, Permission.RUN_SCENARIO, Permission.CHANGE_CONFIG},
    Role.ADMIN: {p for p in Permission},
    Role.SYSTEM: {p for p in Permission},
}


@dataclass
class User:
    """Kullanıcı."""
    user_id: str
    username: str
    role: Role
    password_hash: str = ""
    session_token: str = ""
    token_expires: datetime | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    last_login: datetime | None = None


class AuthenticationService:
    """Kimlik doğrulama servisi."""

    def __init__(self):
        self._users: dict[str, User] = {}
        self._sessions: dict[str, str] = {}  # token → user_id

    def create_user(self, username: str, password: str, role: Role = Role.VIEWER) -> User:
        """Kullanıcı oluştur."""
        user_id = hashlib.sha256(username.encode()).hexdigest()[:12]
        password_hash = self._hash_password(password)

        user = User(
            user_id=user_id,
            username=username,
            role=role,
            password_hash=password_hash,
        )
        self._users[user_id] = user
        logger.info("User created", username=username, role=role.value)
        return user

    def authenticate(self, username: str, password: str) -> str | None:
        """Kimlik doğrula, JWT token döndür."""
        user = self._find_user(username)
        if not user:
            return None

        if not self._verify_password(password, user.password_hash):
            return None

        # JWT token oluştur (jwt_manager ile)
        from .jwt_manager import TokenType, jwt_manager
        permissions = [p.value for p in ROLE_PERMISSIONS.get(user.role, set())]
        token = jwt_manager.generate_token(
            user_id=user.user_id,
            role=user.role.value,
            permissions=permissions,
            token_type=TokenType.ACCESS,
        )
        user.session_token = token
        user.token_expires = datetime.now(UTC) + timedelta(hours=24)
        user.last_login = datetime.now(UTC)
        self._sessions[token] = user.user_id

        logger.info("User authenticated", username=username)
        return token

    def validate_token(self, token: str) -> User | None:
        """JWT token doğrula."""
        from .jwt_manager import JWTError, jwt_manager
        try:
            claims = jwt_manager.validate_token(token)
        except JWTError:
            return None

        user_id = claims.sub
        user = self._users.get(user_id)
        if not user:
            return None

        return user

    def _hash_password(self, password: str) -> str:
        """Password hashle."""
        if _USE_PASSLIB:
            return _pwd_context.hash(password)
        # Fallback: hashlib PBKDF2
        salt = secrets.token_hex(16)
        hash_val = hashlib.pbkdf2_hmac('sha256', password.encode(), salt.encode(), 100000)
        return f"{salt}:{hash_val.hex()}"

    def _verify_password(self, password: str, stored_hash: str) -> bool:
        """Password doğrula."""
        try:
            if _USE_PASSLIB and ":" not in stored_hash:
                return _pwd_context.verify(password, stored_hash)
            # Fallback: hashlib PBKDF2
            salt, hash_hex = stored_hash.split(":")
            hash_val = hashlib.pbkdf2_hmac('sha256', password.encode(), salt.encode(), 100000)
            return hmac.compare_digest(hash_val.hex(), hash_hex)
        except Exception:
            return False

    def _find_user(self, username: str) -> User | None:
        """Kullanıcı bul."""
        for user in self._users.values():
            if user.username == username:
                return user
        return None


class AuthorizationService:
    """Yetkilendirme servisi."""

    def check_permission(self, user: User, permission: Permission) -> bool:
        """Kullanıcının bu izni var mı?"""
        user_permissions = ROLE_PERMISSIONS.get(user.role, set())
        return permission in user_permissions

    def require_permission(self, user: User, permission: Permission):
        """İzin yoksa exception fırlat."""
        if not self.check_permission(user, permission):
            raise PermissionError(f"User {user.username} lacks permission {permission.value}")


class SecretRedaction:
    """Loglarda hassas bilgi gizleme."""

    PATTERNS = [
        (r'(?i)(api[_-]?key|token|secret|password|auth)["\s:=]+["\']?([a-zA-Z0-9_\-\.]{8,})', r'\1=***REDACTED***'),
        (r'(?i)bearer\s+[a-zA-Z0-9_\-\.]+', 'Bearer ***REDACTED***'),
        (r'ghp_[a-zA-Z0-9]+', 'ghp_***REDACTED***'),
        (r'sk-[a-zA-Z0-9]+', 'sk-***REDACTED***'),
    ]

    @classmethod
    def redact(cls, text: str) -> str:
        """Metin içindeki hassas bilgileri gizle."""
        for pattern, replacement in cls.PATTERNS:
            text = re.sub(pattern, replacement, text)
        return text


class SystemStateMachine:
    """Sistem durum makinesi."""

    STATES = ["STARTING", "INITIALIZING", "READY", "DEGRADED", "RECOVERY", "FAILED"]

    def __init__(self):
        self._state = "STARTING"
        self._substates: dict[str, str] = {}
        self._history: list[dict] = []

    @property
    def state(self) -> str:
        return self._state

    def transition(self, new_state: str, reason: str = ""):
        """Durum değiştir."""
        if new_state not in self.STATES:
            raise ValueError(f"Invalid state: {new_state}")

        old_state = self._state
        self._state = new_state
        self._history.append({
            "from": old_state,
            "to": new_state,
            "reason": reason,
            "timestamp": datetime.now(UTC).isoformat(),
        })
        if len(self._history) > 1000:
            self._history = self._history[-1000:]
        logger.info("System state transition", from_state=old_state, to=new_state, reason=reason)

    def set_substate(self, component: str, state: str):
        """Alt bileşen durumu."""
        self._substates[component] = state

    def get_health(self) -> dict[str, Any]:
        """Sistem sağlık durumu."""
        return {
            "state": self._state,
            "substates": dict(self._substates),
            "history_count": len(self._history),
        }


class SafetyGovernance:
    """Güvenlik yönetimi."""

    # AI'nın yapamayacağı şeyler
    AI_RESTRICTIONS = [
        "AI cannot bypass risk limits",
        "AI cannot modify portfolio state directly",
        "AI cannot delete audit history",
        "AI cannot self-promote to production",
        "AI cannot create trades directly",
        "AI cannot access other users' data",
    ]

    @staticmethod
    def validate_ai_action(action: str, context: dict) -> bool:
        """AI eyleminin güvenli olup olmadığını kontrol et."""
        # Risk bypass
        if action == "bypass_risk":
            logger.warning("AI attempted to bypass risk", context=context)
            return False

        # Direct portfolio modification
        if action == "modify_portfolio" and context.get("source") == "ai":
            logger.warning("AI attempted direct portfolio modification", context=context)
            return False

        # Audit deletion
        if action == "delete_audit":
            logger.warning("AI attempted audit deletion", context=context)
            return False

        return True


# Singletons
auth_service = AuthenticationService()
authz_service = AuthorizationService()
secret_redaction = SecretRedaction()
system_state = SystemStateMachine()
safety_governance = SafetyGovernance()


# === Encryption Utilities (optional, requires cryptography) ===

def encrypt_data(data: str, key: bytes | None = None) -> bytes:
    """Encrypt string data using Fernet (AES-128-CBC).

    Args:
        data: String to encrypt
        key: Fernet key (32 url-safe base64-encoded bytes). Auto-generated if None.

    Returns:
        Encrypted bytes + key (if auto-generated, returns tuple)
    """
    if not _USE_CRYPTO:
        raise RuntimeError("cryptography package not installed. Install with: pip install cryptography")
    if key is None:
        key = Fernet.generate_key()
    f = Fernet(key)
    return f.encrypt(data.encode()), key


def decrypt_data(token: bytes, key: bytes) -> str:
    """Decrypt Fernet-encrypted data.

    Args:
        token: Encrypted bytes
        key: Fernet key used for encryption

    Returns:
        Decrypted string
    """
    if not _USE_CRYPTO:
        raise RuntimeError("cryptography package not installed. Install with: pip install cryptography")
    f = Fernet(key)
    return f.decrypt(token).decode()
