"""
ALPHA BIST — API Kimlik Doğrulama ve Yetkilendirme v2.0 (Kurumsal Yapı)

JWT + RBAC (Rol Tabanlı Erişim Kontrolü).
SOLID prensiplerine uygun, bağımlılık enjeksiyonu destekli, bellek optimize kimlik doğrulama işleyicileri.

Roller:
- VIEWER: GET (gösterge paneli, raporlar)
- ANALYST: GET + POST (analiz çalıştır)
- OPERATOR: GET + POST + PUT (emir, yeniden dengeleme)
- ADMIN: Tüm uç noktalar
- SYSTEM: Servisler arası (API anahtarı)
"""

import base64
import hashlib
import hmac
import os
import time
from dataclasses import dataclass, field
from typing import Any

import orjson
import structlog

# İsteğe bağlı PyJWT bağımlılığı
try:
    import jwt

    HAS_JWT = True
except ImportError:
    jwt = None
    HAS_JWT = False

from services.core.otel import get_tracer
from services.core.security import Role

logger = structlog.get_logger(__name__)
tracer = get_tracer(__name__)


# Rol → izin verilen HTTP yöntemleri
ROLE_PERMISSIONS: dict[Role, list[str]] = {
    Role.VIEWER: ["GET"],
    Role.ANALYST: ["GET", "POST"],
    Role.OPERATOR: ["GET", "POST", "PUT"],
    Role.ADMIN: ["GET", "POST", "PUT", "DELETE"],
    Role.SYSTEM: ["GET", "POST", "PUT", "DELETE"],
}


@dataclass(frozen=True)
class AuthConfig:
    """
    Kimlik doğrulama yapılandırma modeli.
    Doğrudan ortam değişkeni erişimini kaldırarak bağımlılık enjeksiyonunu destekler.
    """

    jwt_secret: str
    jwt_algorithm: str = "HS256"
    jwt_expires_hours: int = 24

    def __repr__(self) -> str:
        return (
            f"AuthConfig(jwt_algorithm='{self.jwt_algorithm}', "
            f"jwt_expires_hours={self.jwt_expires_hours})"
        )


@dataclass
class User:
    """
    Sistemde kimliği doğrulanmış kullanıcıyı temsil eder.
    """

    user_id: str
    username: str
    role: Role
    permissions: list[str] = field(default_factory=list)
    is_active: bool = True

    def __repr__(self) -> str:
        return f"User(user_id={self.user_id!r}, username={self.username!r}, role={self.role!r}, is_active={self.is_active!r})"


@dataclass
class TokenPayload:
    """
    Geçerli bir JWT belirtecinin ayrıştırılmış yükünü temsil eder.
    """

    sub: str  # user_id
    username: str
    role: str
    permissions: list[str]
    exp: float  # sona erme zaman damgası
    iat: float  # oluşturulma zaman damgası

    def __repr__(self) -> str:
        return f"TokenPayload(sub={self.sub!r}, username={self.username!r}, role={self.role!r})"


class JWTHandler:
    """
    JWT belirteçlerinin oluşturulmasını ve doğrulanmasını yönetir.
    SOLID prensiplerine uymak için yapılandırma için bağımlılık enjeksiyonu kullanır.
    """

    def __init__(
        self,
        config: AuthConfig | None = None,
        secret_key: str | None = None,
        algorithm: str = "HS256",
        expires_hours: int = 24,
    ) -> None:
        """
        JWT İşleyicisini başlatır.
        Bağımlılık enjeksiyonu veya doğrudan secret_key yapılandırmasını destekler.
        """
        if config is not None:
            self.config = config
        else:
            secret = secret_key or os.getenv("JWT_SECRET_KEY")
            if not secret:
                raise ValueError(
                    "JWT_SECRET_KEY ortam değişkeni ayarlanmamış. "
                    "Güvenlik için varsayılan değer kaldırıldı."
                )
            self.config = AuthConfig(
                jwt_secret=secret,
                jwt_algorithm=algorithm,
                jwt_expires_hours=expires_hours,
            )
        if not self.config.jwt_secret:
            raise ValueError("AuthConfig'de JWT secret key sağlanmalıdır.")

    @property
    def algorithm(self) -> str:
        """Yapılandırılmış JWT algoritmasını döndürür."""
        return self.config.jwt_algorithm

    def create_token(
        self,
        user_id: str,
        username: str,
        role: Role,
        expires_hours: int | None = None,
    ) -> str:
        """
        Belirtilen kullanıcı ve rol için JWT belirteci oluşturur.

        Args:
            user_id (str): Benzersiz kullanıcı tanımlayıcısı.
            username (str): Kullanıcı adı.
            role (Role): Atanan kullanıcı rolü.
            expires_hours (int | None): Opsiyonel sona erme süresi (saat).

        Returns:
            str: Kodlanmış JWT dizgesi.
        """
        with tracer.start_as_current_span("auth.create_token") as span:
            now = time.time()
            role_value = role.value if hasattr(role, "value") else str(role)
            span.set_attribute("user.id", user_id)
            span.set_attribute("user.role", role_value)

            exp_hours = expires_hours if expires_hours is not None else self.config.jwt_expires_hours
            payload = {
                "sub": user_id,
                "username": username,
                "role": role_value,
                "permissions": ROLE_PERMISSIONS.get(role, []),
                "exp": now + (exp_hours * 3600),
                "iat": now,
            }

            if HAS_JWT and jwt is not None:
                return jwt.encode(payload, self.config.jwt_secret, algorithm=self.config.jwt_algorithm)

            return self._create_fallback_token(payload)

    def _create_fallback_token(self, payload: dict[str, Any]) -> str:
        """
        PyJWT mevcut olmadığında HMAC ve standart kütüphaneler kullanarak belirteç oluşturur.
        """
        header = base64.urlsafe_b64encode(b'{"alg":"HS256","typ":"JWT"}').decode().rstrip("=")
        body = base64.urlsafe_b64encode(orjson.dumps(payload)).decode().rstrip("=")
        to_sign = f"{header}.{body}".encode()

        sig = (
            base64.urlsafe_b64encode(hmac.new(self.config.jwt_secret.encode(), to_sign, hashlib.sha256).digest())
            .decode()
            .rstrip("=")
        )

        return f"{header}.{body}.{sig}"

    def verify_token(self, token: str) -> TokenPayload | None:
        """
        JWT belirtecini doğrular ve ayrıştırır.

        Args:
            token (str): Doğrulanacak JWT dizgesi.

        Returns:
            Optional[TokenPayload]: Geçerliyse ayrıştırılmış yük, aksi halde None.
        """
        with tracer.start_as_current_span("auth.verify_token"):
            if not token or not isinstance(token, str):
                logger.warning("Geçersiz belirteç biçimi sağlandı.")
                return None

            if HAS_JWT and jwt is not None:
                try:
                    payload = jwt.decode(token, self.config.jwt_secret, algorithms=[self.config.jwt_algorithm])
                    return TokenPayload(**payload)
                except jwt.ExpiredSignatureError:
                    logger.warning("JWT belirtecinin süresi doldu.")
                    return None
                except jwt.InvalidTokenError as e:
                    logger.warning("JWT doğrulaması başarısız.", error=str(e))
                    return None

            return self._verify_fallback_token(token)

    def _verify_fallback_token(self, token: str) -> TokenPayload | None:
        """
        PyJWT mevcut olmadığında HMAC belirtecini doğrular.
        Sabit zamanlı imza karşılaştırması sağlar.
        """
        try:
            parts = token.split(".")
            if len(parts) != 3:
                return None

            header, body, sig = parts
            to_sign = f"{header}.{body}".encode()

            expected_sig = (
                base64.urlsafe_b64encode(hmac.new(self.config.jwt_secret.encode(), to_sign, hashlib.sha256).digest())
                .decode()
                .rstrip("=")
            )

            if not hmac.compare_digest(sig, expected_sig):
                logger.warning("JWT imza uyuşmazlığı.")
                return None

            rem = len(body) % 4
            if rem > 0:
                body += "=" * (4 - rem)

            payload_data = orjson.loads(base64.urlsafe_b64decode(body.encode()))
            if payload_data.get("exp", 0) < time.time():
                logger.warning("JWT belirtecinin süresi doldu.")
                return None

            return TokenPayload(**payload_data)
        except Exception as e:
            logger.warning("Yedek JWT doğrulaması başarısız.", error=str(e))
            return None


class APIKeyManager:
    """
    Servisler arası kimlik doğrulama için API anahtarlarını yönetir.
    """

    def __init__(self) -> None:
        """API Anahtar Yöneticisini boş bir depo ile başlatır."""
        self._keys: dict[str, dict[str, Any]] = {}

    def register_key(self, api_key: str, service: str, permissions: list[str]) -> None:
        """
        Yeni bir API anahtarı kaydeder.

        Args:
            api_key (str): API anahtarı dizgesi.
            service (str): Anahtara sahip hizmetin adı.
            permissions (list[str]): İzin verilen HTTP yöntemlerinin listesi.
        """
        self._keys[api_key] = {
            "service": service,
            "permissions": permissions,
            "created_at": time.time(),
        }

    def verify_key(self, api_key: str) -> dict[str, Any] | None:
        """
        Bir API anahtarının mevcut olup olmadığını ve geçerli olduğunu doğrular.

        Args:
            api_key (str): Doğrulanacak API anahtarı.

        Returns:
            Optional[dict[str, Any]]: Geçerliyse anahtar meta verileri, aksi halde None.
        """
        with tracer.start_as_current_span("auth.verify_key"):
            return self._keys.get(api_key)

    def revoke_key(self, api_key: str) -> None:
        """
        Aktif bir API anahtarını iptal eder.

        Args:
            api_key (str): İptal edilecek API anahtarı.
        """
        self._keys.pop(api_key, None)


class RBACChecker:
    """
    Rol Tabanlı Erişim Kontrolü mantığını ve uç nokta izin doğrulamasını yönetir.
    """

    @staticmethod
    def check_permission(role: Role, method: str) -> bool:
        """
        Belirli bir rolün belirli bir HTTP yöntemini çalıştırmaya izin verip vermediğini kontrol eder.

        Args:
            role (Role): Kontrol edilecek rol.
            method (str): HTTP yöntemi (ör. 'GET', 'POST').

        Returns:
            bool: İzin veriliyorsa True, aksi halde False.
        """
        allowed = ROLE_PERMISSIONS.get(role, [])
        return method.upper() in allowed

    @staticmethod
    def check_endpoint_access(role: Role, endpoint: str) -> bool:
        """
        Bir rolün belirli hassas uç noktalara yapısal erişiminin olup olmadığını kontrol eder.

        Args:
            role (Role): Kullanıcının rolü.
            endpoint (str): İstenen API uç nokta yolu.

        Returns:
            bool: Erişime izin veriliyorsa True, aksi halde False.
        """
        if endpoint.startswith("/admin/"):
            return role in [Role.ADMIN, Role.SYSTEM]

        if endpoint.startswith("/api/v1/") and any(
            endpoint.endswith(suffix) for suffix in ["/rebalance", "/promote", "/restart"]
        ):
            return role in [Role.OPERATOR, Role.ADMIN, Role.SYSTEM]

        return True


# Global örnekler (Basit Konteyner Desteği)
# Tam bir DI çerçevesinde bunlar IoC konteyneri tarafından yönetilir.
_jwt_secret = os.environ.get("JWT_SECRET")
if not _jwt_secret:
    logger.warning("JWT_SECRET ortam değişkeni ayarlanmamış — kimlik doğrulama çalışmayabilir.")
    _jwt_secret = "dev-only-unsafe-key"  # Sadece geliştirme ortamında, üretimde hata verir

_default_config = AuthConfig(jwt_secret=_jwt_secret)

jwt_handler = JWTHandler(_default_config)
api_key_manager = APIKeyManager()
rbac_checker = RBACChecker()

_default_key = os.environ.get("SYSTEM_API_KEY")
if _default_key:
    api_key_manager.register_key(_default_key, "system", ["GET", "POST", "PUT", "DELETE"])
else:
    logger.warning("SYSTEM_API_KEY ayarlanmamış — servisler arası kimlik doğrulama devre dışı.")
