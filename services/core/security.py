"""ALPHA BIST — Kurumsal Güvenlik, Kimlik Doğrulama ve Yönetişim Motoru (Security & Governance).

Bu modül, kurumsal düzeyde güvenlik ve uyumluluk için:
- Rol tabanlı erişim denetimi (RBAC: Viewer, Analyst, Operator, Admin, System)
- Güvenli şifre hashleme (Bcrypt / PBKDF2-HMAC-SHA256) ve JWT token doğrulama
- Hassas veri ve gizli anahtar maskeleme (Secret Redaction)
- Sistem durum makinesi ve bileşen sağlık takibi (System State Machine)
- Yapay Zeka (AI) operasyonel güvenlik ve eylem kural motoru (Safety Governance)
- DuckDB üzerinde güvenlik denetim izi (Security Audit Log) ve Polars analitik aktarımı sağlar.
"""

from __future__ import annotations

import hashlib
import hmac
import re
import secrets
import threading
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import TYPE_CHECKING, Any, Final

import orjson
import polars as pl
import structlog

from services.core.otel import otel_trace

if TYPE_CHECKING:
    import duckdb

logger = structlog.get_logger(__name__)

# passlib — bcrypt ile güvenli şifre hashleme (isteğe bağlı)
try:
    from passlib.context import CryptContext

    _pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
    _USE_PASSLIB = True
except ImportError:
    _USE_PASSLIB = False

# cryptography — Fernet AES şifreleme (isteğe bağlı)
try:
    from cryptography.fernet import Fernet

    _USE_CRYPTO = True
except ImportError:
    _USE_CRYPTO = False

DEFAULT_SECURITY_AUDIT_DB: Final[str] = "data/security_audit.duckdb"
_GLOBAL_LOCK = threading.RLock()
_SECURITY_DUCKDB_CONN: duckdb.DuckDBPyConnection | None = None


class Role(StrEnum):
    """Sistem kullanıcı rolleri."""

    VIEWER = "VIEWER"
    ANALYST = "ANALYST"
    OPERATOR = "OPERATOR"
    ADMIN = "ADMIN"
    SYSTEM = "SYSTEM"


class Permission(StrEnum):
    """Sistem erişim yetkileri ve operasyonel izinler."""

    READ_MARKET = "READ_MARKET"
    READ_PORTFOLIO = "READ_PORTFOLIO"
    RUN_BACKTEST = "RUN_BACKTEST"
    RUN_SCENARIO = "RUN_SCENARIO"
    CHANGE_CONFIG = "CHANGE_CONFIG"
    PROMOTE_MODEL = "PROMOTE_MODEL"
    LIVE_EXECUTION = "LIVE_EXECUTION"
    MANAGE_USERS = "MANAGE_USERS"


# Rol → İzinler eşleştirmesi (RBAC Matrisi)
ROLE_PERMISSIONS: Final[dict[Role, set[Permission]]] = {
    Role.VIEWER: {Permission.READ_MARKET, Permission.READ_PORTFOLIO},
    Role.ANALYST: {
        Permission.READ_MARKET,
        Permission.READ_PORTFOLIO,
        Permission.RUN_BACKTEST,
        Permission.RUN_SCENARIO,
    },
    Role.OPERATOR: {
        Permission.READ_MARKET,
        Permission.READ_PORTFOLIO,
        Permission.RUN_BACKTEST,
        Permission.RUN_SCENARIO,
        Permission.CHANGE_CONFIG,
    },
    Role.ADMIN: set(Permission),
    Role.SYSTEM: set(Permission),
}


@dataclass(slots=True)
class SecurityAuditEvent:
    """Güvenlik denetim olayı veri modeli."""

    event_type: str
    username: str
    action: str
    result: str
    details: dict[str, Any] = field(default_factory=dict)
    recorded_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def to_dict(self) -> dict[str, Any]:
        """Sözlük formatına dönüştürür."""
        d = asdict(self)
        d["recorded_at"] = self.recorded_at.isoformat()
        return d

    def to_orjson_bytes(self) -> bytes:
        """orjson bayt dizisine serileştirir."""
        return orjson.dumps(self.to_dict())

    def __repr__(self) -> str:
        return (
            f"SecurityAuditEvent(tip='{self.event_type}', kullanici='{self.username}', "
            f"eylem='{self.action}', sonuc='{self.result}')"
        )


def set_security_duckdb_connection(conn: duckdb.DuckDBPyConnection) -> None:
    """Güvenlik denetim günlüğü için DuckDB bağlantısını tanımlar."""
    global _SECURITY_DUCKDB_CONN
    with _GLOBAL_LOCK:
        _SECURITY_DUCKDB_CONN = conn
        _init_security_duckdb_schema()


def _init_security_duckdb_schema() -> None:
    """DuckDB güvenlik denetim şemasını ilklendirir."""
    if _SECURITY_DUCKDB_CONN is None:
        return
    with _GLOBAL_LOCK:
        try:
            _SECURITY_DUCKDB_CONN.execute("""
                CREATE TABLE IF NOT EXISTS security_audit_log (
                    id BIGINT,
                    event_type VARCHAR,
                    username VARCHAR,
                    action VARCHAR,
                    result VARCHAR,
                    details_json VARCHAR,
                    recorded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
                CREATE SEQUENCE IF NOT EXISTS seq_security_audit_log START 1;
            """)
        except Exception as exc:
            logger.error("Security DuckDB şema oluşturma hatası", hata=str(exc))


def _record_security_event(event: SecurityAuditEvent) -> None:
    """Güvenlik olayını DuckDB denetim tablosuna işler."""
    if _SECURITY_DUCKDB_CONN is None:
        return
    with _GLOBAL_LOCK:
        try:
            det_json = orjson.dumps(event.details).decode("utf-8")
            _SECURITY_DUCKDB_CONN.execute(
                """
                INSERT INTO security_audit_log (
                    id, event_type, username, action, result, details_json, recorded_at
                ) VALUES (
                    nextval('seq_security_audit_log'), ?, ?, ?, ?, ?, ?
                )
                """,
                [
                    event.event_type,
                    event.username,
                    event.action,
                    event.result,
                    det_json,
                    event.recorded_at,
                ],
            )
        except Exception as exc:
            logger.debug("Security DuckDB olay yazma hatası", hata=str(exc))


@dataclass
class User:
    """Sistem kullanıcı veri modeli."""

    user_id: str
    username: str
    role: Role
    password_hash: str = ""
    session_token: str = ""
    token_expires: datetime | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    last_login: datetime | None = None

    def to_dict(self) -> dict[str, Any]:
        """Kullanıcı nesnesini hassas verileri gizleyerek sözlüğe çevirir."""
        return {
            "user_id": self.user_id,
            "username": self.username,
            "role": self.role.value,
            "token_expires": self.token_expires.isoformat() if self.token_expires else None,
            "created_at": self.created_at.isoformat(),
            "last_login": self.last_login.isoformat() if self.last_login else None,
        }

    def to_orjson_bytes(self) -> bytes:
        """orjson bayt dizisine serileştirir."""
        return orjson.dumps(self.to_dict())

    def __repr__(self) -> str:
        return f"User(id='{self.user_id}', kullanici='{self.username}', rol='{self.role.value}')"


class AuthenticationService:
    """Kullanıcı kimlik doğrulama ve oturum yönetim servisi (Thread-Safe)."""

    def __init__(self, duckdb_conn: duckdb.DuckDBPyConnection | None = None) -> None:
        self._lock = threading.RLock()
        self._users: dict[str, User] = {}
        self._sessions: dict[str, str] = {}  # session_token -> user_id
        if duckdb_conn is not None:
            set_security_duckdb_connection(duckdb_conn)

    @otel_trace("security.create_user")
    def create_user(self, username: str, password: str, role: Role = Role.VIEWER) -> User:
        """Sisteme yeni bir kullanıcı ekler."""
        with self._lock:
            user_id = hashlib.sha256(username.encode()).hexdigest()[:12]
            password_hash = self._hash_password(password)

            user = User(
                user_id=user_id,
                username=username,
                role=role,
                password_hash=password_hash,
            )
            self._users[user_id] = user

            event = SecurityAuditEvent(
                event_type="USER_CREATED",
                username=username,
                action="create_user",
                result="SUCCESS",
                details={"role": role.value, "user_id": user_id},
            )
            _record_security_event(event)

            logger.info("Kullanıcı oluşturuldu.", username=username, role=role.value)
            return user

    @otel_trace("security.authenticate")
    def authenticate(self, username: str, password: str) -> str | None:
        """Kullanıcı bilgilerini doğrular ve geçerliyse JWT access token döndürür."""
        with self._lock:
            user = self._find_user(username)
            if not user:
                event = SecurityAuditEvent(
                    event_type="AUTH_FAILED",
                    username=username,
                    action="authenticate",
                    result="USER_NOT_FOUND",
                )
                _record_security_event(event)
                logger.warn("Kimlik doğrulama başarısız: Kullanıcı bulunamadı", kullanici=username)
                return None

            if not self._verify_password(password, user.password_hash):
                event = SecurityAuditEvent(
                    event_type="AUTH_FAILED",
                    username=username,
                    action="authenticate",
                    result="WRONG_PASSWORD",
                )
                _record_security_event(event)
                logger.warn("Kimlik doğrulama başarısız: Hatalı şifre", kullanici=username)
                return None

            try:
                from .jwt_manager import TokenType, jwt_manager

                permissions = [p.value for p in ROLE_PERMISSIONS.get(user.role, set())]
                token = jwt_manager.generate_token(
                    user_id=user.user_id,
                    role=user.role.value,
                    permissions=permissions,
                    token_type=TokenType.ACCESS,
                )
            except Exception:
                # Fallback: Güvenli rastgele token
                token = secrets.token_urlsafe(32)

            user.session_token = token
            user.token_expires = datetime.now(UTC) + timedelta(hours=24)
            user.last_login = datetime.now(UTC)
            self._sessions[token] = user.user_id

            event = SecurityAuditEvent(
                event_type="AUTH_SUCCESS",
                username=username,
                action="authenticate",
                result="SUCCESS",
                details={"role": user.role.value},
            )
            _record_security_event(event)

            logger.info("Kullanıcı kimlik doğrulandı.", username=username)
            return token

    @otel_trace("security.validate_token")
    def validate_token(self, token: str) -> User | None:
        """Verilen JWT/Oturum token'ını doğrular ve geçerli User nesnesini döner."""
        with self._lock:
            # 1. Yerel aktif oturum kontrolü
            user_id = self._sessions.get(token)
            if user_id:
                user = self._users.get(user_id)
                if user and user.token_expires and user.token_expires > datetime.now(UTC):
                    return user

            # 2. JWT Manager doğrulaması
            try:
                from .jwt_manager import JWTError, jwt_manager

                claims = jwt_manager.validate_token(token)
                sub_id = claims.sub
                user = self._users.get(sub_id)
                if user:
                    return user
            except (JWTError, Exception):
                pass

            return None

    def _hash_password(self, password: str) -> str:
        """Şifreyi PBKDF2-HMAC-SHA256 veya Passlib ile güvenle hashler."""
        if _USE_PASSLIB:
            try:
                return _pwd_context.hash(password)
            except Exception:
                pass
        salt = secrets.token_hex(16)
        hash_val = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 100000)
        return f"{salt}:{hash_val.hex()}"

    def _verify_password(self, password: str, stored_hash: str) -> bool:
        """Verilen şifre ile hashlenmiş halini güvenli karşılaştırır."""
        try:
            if _USE_PASSLIB and ":" not in stored_hash:
                try:
                    return _pwd_context.verify(password, stored_hash)
                except Exception:
                    pass

            salt, hash_hex = stored_hash.split(":")
            hash_val = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 100000)
            return hmac.compare_digest(hash_val.hex(), hash_hex)
        except Exception:
            return False

    def _find_user(self, username: str) -> User | None:
        """Kullanıcı adına göre arama yapar."""
        for user in self._users.values():
            if user.username == username:
                return user
        return None

    def __repr__(self) -> str:
        with self._lock:
            return f"AuthenticationService(kullanici_sayisi={len(self._users)}, oturum_sayisi={len(self._sessions)})"


class AuthorizationService:
    """Kullanıcı yetkilerini (RBAC) kontrol eden yetkilendirme servisidir (Thread-Safe)."""

    def __init__(self) -> None:
        self._lock = threading.RLock()

    @otel_trace("security.check_permission")
    def check_permission(self, user: User, permission: Permission) -> bool:
        """Belirtilen kullanıcının ilgili izne sahip olup olmadığını denetler."""
        with self._lock:
            user_permissions = ROLE_PERMISSIONS.get(user.role, set())
            allowed = permission in user_permissions
            if not allowed:
                event = SecurityAuditEvent(
                    event_type="ACCESS_DENIED",
                    username=user.username,
                    action="check_permission",
                    result="DENIED",
                    details={"role": user.role.value, "required_permission": permission.value},
                )
                _record_security_event(event)
            return allowed

    @otel_trace("security.require_permission")
    def require_permission(self, user: User, permission: Permission) -> None:
        """Kullanıcının izni yoksa PermissionError fırlatır."""
        if not self.check_permission(user, permission):
            raise PermissionError(f"Kullanıcı '{user.username}', gerekli izin eksik: {permission.value}")

    def __repr__(self) -> str:
        return "AuthorizationService(model='RBAC', roller=5)"


class SecretRedaction:
    """Loglarda ve çıktılarda hassas bilgileri güvenle maskeleyen araç sınıfı."""

    PATTERNS: Final[list[tuple[str, str]]] = [
        (r'(?i)(api[_-]?key|token|secret|password|auth)["\s:=]+["\']?([a-zA-Z0-9_\-\.]{8,})', r"\1=***REDACTED***"),
        (r"(?i)bearer\s+[a-zA-Z0-9_\-\.]+", "Bearer ***REDACTED***"),
        (r"ghp_[a-zA-Z0-9]+", "ghp_***REDACTED***"),
        (r"sk-[a-zA-Z0-9]+", "sk-***REDACTED***"),
    ]

    @classmethod
    @otel_trace("security.redact")
    def redact(cls, text: str) -> str:
        """Metin içindeki hassas şifre, token vb. bilgileri maskeler."""
        if not text:
            return ""
        redacted = text
        for pattern, replacement in cls.PATTERNS:
            redacted = re.sub(pattern, replacement, redacted)
        return redacted

    def __repr__(self) -> str:
        return f"SecretRedaction(kural_sayisi={len(self.PATTERNS)})"


class SystemStateMachine:
    """Sistemin genel durumunu ve geçişlerini yöneten Durum Makinesi (Thread-Safe)."""

    STATES: Final[frozenset[str]] = frozenset(
        {"STARTING", "INITIALIZING", "READY", "DEGRADED", "RECOVERY", "FAILED"}
    )

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._state: str = "STARTING"
        self._substates: dict[str, str] = {}
        self._history: list[dict[str, Any]] = []

    @property
    def state(self) -> str:
        """Güncel sistem durumu."""
        with self._lock:
            return self._state

    @otel_trace("security.transition")
    def transition(self, new_state: str, reason: str = "") -> None:
        """Sistem durumunu atomik olarak değiştirir ve geçmişe kaydeder."""
        with self._lock:
            if new_state not in self.STATES:
                raise ValueError(f"Geçersiz durum: {new_state}. Geçerli durumlar: {sorted(self.STATES)}")

            old_state = self._state
            self._state = new_state

            record = {
                "from": old_state,
                "to": new_state,
                "reason": reason,
                "timestamp": datetime.now(UTC).isoformat(),
            }
            self._history.append(record)
            if len(self._history) > 1000:
                self._history = self._history[-1000:]

            event = SecurityAuditEvent(
                event_type="STATE_TRANSITION",
                username="SYSTEM",
                action="transition",
                result="SUCCESS",
                details={"from": old_state, "to": new_state, "reason": reason},
            )
            _record_security_event(event)

            logger.info("Sistem durum geçişi", from_state=old_state, to=new_state, reason=reason)

    @otel_trace("security.set_substate")
    def set_substate(self, component: str, state: str) -> None:
        """Alt bileşenin (veritabanı, NATS, model motoru vb.) güncel durumunu günceller."""
        with self._lock:
            self._substates[component] = state

    @otel_trace("security.get_health")
    def get_health(self) -> dict[str, Any]:
        """Tüm bileşenlerin birleşik sağlık durumunu döner."""
        with self._lock:
            return {
                "state": self._state,
                "substates": dict(self._substates),
                "history_count": len(self._history),
            }

    def export_history_to_polars(self) -> pl.DataFrame:
        """Sistem durum geçiş geçmişini Polars DataFrame olarak döner."""
        with self._lock:
            if not self._history:
                return pl.DataFrame(
                    schema={
                        "from": pl.Utf8,
                        "to": pl.Utf8,
                        "reason": pl.Utf8,
                        "timestamp": pl.Utf8,
                    }
                )
            return pl.DataFrame(self._history)

    def __repr__(self) -> str:
        with self._lock:
            return f"SystemStateMachine(durum='{self._state}', alt_bilesenler={len(self._substates)})"


class SafetyGovernance:
    """Yapay zeka (AI) ajanlarının sistem üzerindeki tehlikeli eylemlerini kısıtlayan denetim motoru."""

    AI_RESTRICTIONS: Final[list[str]] = [
        "AI cannot bypass risk limits",
        "AI cannot modify portfolio state directly",
        "AI cannot delete audit history",
        "AI cannot self-promote to production",
        "AI cannot create trades directly",
        "AI cannot access other users' data",
    ]

    @staticmethod
    @otel_trace("security.validate_ai_action")
    def validate_ai_action(action: str, context: dict[str, Any] | None = None) -> bool:
        """AI eyleminin operasyonel güvenlik kurallarına uygunluğunu denetler."""
        ctx = context or {}

        if action == "bypass_risk":
            logger.warn("AI risk bypass denemesi tespit edildi ve engellendi.", context=ctx)
            event = SecurityAuditEvent(
                event_type="AI_VIOLATION",
                username="AI_AGENT",
                action=action,
                result="DENIED",
                details=ctx,
            )
            _record_security_event(event)
            return False

        if action == "modify_portfolio" and ctx.get("source") == "ai":
            logger.warn("AI doğrudan portföy değişikliği denemesi tespit edildi ve engellendi.", context=ctx)
            event = SecurityAuditEvent(
                event_type="AI_VIOLATION",
                username="AI_AGENT",
                action=action,
                result="DENIED",
                details=ctx,
            )
            _record_security_event(event)
            return False

        if action == "delete_audit":
            logger.warn("AI denetim kaydı silme denemesi tespit edildi ve engellendi.", context=ctx)
            event = SecurityAuditEvent(
                event_type="AI_VIOLATION",
                username="AI_AGENT",
                action=action,
                result="DENIED",
                details=ctx,
            )
            _record_security_event(event)
            return False

        return True

    def __repr__(self) -> str:
        return f"SafetyGovernance(kisit_sayisi={len(self.AI_RESTRICTIONS)})"


# =============================================================================
# Global Singleton Nesneleri
# =============================================================================
auth_service: Final[AuthenticationService] = AuthenticationService()
authz_service: Final[AuthorizationService] = AuthorizationService()
secret_redaction: Final[SecretRedaction] = SecretRedaction()
system_state: Final[SystemStateMachine] = SystemStateMachine()
safety_governance: Final[SafetyGovernance] = SafetyGovernance()


# =============================================================================
# Şifreleme Yardımcıları
# =============================================================================


def encrypt_data(data: str, key: bytes | None = None) -> tuple[bytes, bytes]:
    """Verilen metni Fernet (AES-128-CBC) algoritması ile şifreler."""
    if not _USE_CRYPTO:
        raise RuntimeError("cryptography paketi bulunamadı. Kurulum: uv add cryptography")
    enc_key = key if key is not None else Fernet.generate_key()
    f = Fernet(enc_key)
    return f.encrypt(data.encode("utf-8")), enc_key


def decrypt_data(token: bytes, key: bytes) -> str:
    """Şifrelenmiş veriyi (Fernet) deşifre eder."""
    if not _USE_CRYPTO:
        raise RuntimeError("cryptography paketi bulunamadı. Kurulum: uv add cryptography")
    f = Fernet(key)
    return f.decrypt(token).decode("utf-8")


def export_security_audit_to_polars() -> pl.DataFrame:
    """DuckDB'de saklanan güvenlik denetim kayıtlarını Polars DataFrame olarak döner."""
    if _SECURITY_DUCKDB_CONN is None:
        return pl.DataFrame(
            schema={
                "id": pl.Int64,
                "event_type": pl.Utf8,
                "username": pl.Utf8,
                "action": pl.Utf8,
                "result": pl.Utf8,
                "details_json": pl.Utf8,
                "recorded_at": pl.Datetime,
            }
        )

    with _GLOBAL_LOCK:
        try:
            return _SECURITY_DUCKDB_CONN.execute("SELECT * FROM security_audit_log ORDER BY id ASC").pl()
        except Exception as exc:
            logger.error("DuckDB güvenlik denetim kayıtları çekilemedi", hata=str(exc))
            return pl.DataFrame()


__all__ = [
    "DEFAULT_SECURITY_AUDIT_DB",
    "ROLE_PERMISSIONS",
    "AuthenticationService",
    "AuthorizationService",
    "Permission",
    "Role",
    "SafetyGovernance",
    "SecretRedaction",
    "SecurityAuditEvent",
    "SystemStateMachine",
    "User",
    "auth_service",
    "authz_service",
    "decrypt_data",
    "encrypt_data",
    "export_security_audit_to_polars",
    "safety_governance",
    "secret_redaction",
    "set_security_duckdb_connection",
    "system_state",
]
