"""ALPHA BIST — Monitoring Security Modülü.

İzleme, metrik ve yönetim uç noktaları için kimlik doğrulama (authentication),
yetkilendirme (authorization) ve oran sınırlama (rate limiting) motoru.

Endpoint Koruma Düzeyleri:
- PUBLIC:  /health, /health/detailed (Genel erişim, anonim durum)
- METRICS: /metrics (Metrik okuma token'ı / Bearer token)
- ADMIN:   /admin/* (Yönetici yetkisi, admin token veya admin rolü)

Desteklenen Sağlayıcılar:
- StaticTokenProvider: Sabit token ve rol eşleştirmesi
- JWTProvider: HS256 ve RS256 JWKS destekli JSON Web Token doğrulama (httpx + orjson)
- OAuthProvider: Genişletilebilir OAuth/OIDC yetkilendirmesi
- AuthManager: Çoklu sağlayıcı zinciri ve Rol Tabanlı Erişim Kontrolü (RBAC)
"""

from __future__ import annotations

import asyncio
import functools
import hmac
import inspect
import os
import threading
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Final, Mapping

import httpx
import orjson
import polars as pl
import structlog
from opentelemetry import trace

logger = structlog.get_logger(__name__)
tracer = trace.get_tracer("alpha-bist.monitoring_security")

# ----------------------------------------------------------------------
# Sabitler (Magic number ve string'lerin yerine açık tanımlar)
# ----------------------------------------------------------------------
DEFAULT_METRICS_TOKEN: Final[str] = "alpha_metrics_default_2026"
DEFAULT_ADMIN_TOKEN: Final[str] = "alpha_admin_default_2026"
DEFAULT_RATE_LIMIT_PER_MINUTE: Final[int] = 60
DEFAULT_MAX_FAILED_ATTEMPTS: Final[int] = 10
DEFAULT_JWKS_CACHE_TTL_SECONDS: Final[int] = 3600
DEFAULT_MAX_TRACKED_CLIENTS: Final[int] = 10_000
DEFAULT_HTTP_TIMEOUT_SECONDS: Final[float] = 10.0
DEFAULT_RATE_LIMIT_WINDOW_SECONDS: Final[float] = 60.0
DEFAULT_FAILED_ATTEMPTS_TTL_SECONDS: Final[float] = 3600.0


def otel_trace(span_name: str) -> Any:
    """Metot veya fonksiyonu OpenTelemetry span bağlamında çalıştıran sarmalayıcı (decorator).

    Args:
        span_name: Oluşturulacak span adı.

    Returns:
        Sarmalanmış senkron veya asenkron fonksiyon.
    """
    def decorator(func: Any) -> Any:
        if inspect.iscoroutinefunction(func):
            @functools.wraps(func)
            async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
                with tracer.start_as_current_span(span_name):
                    return await func(*args, **kwargs)
            return async_wrapper
        else:
            @functools.wraps(func)
            def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
                with tracer.start_as_current_span(span_name):
                    return func(*args, **kwargs)
            return sync_wrapper
    return decorator


@dataclass
class AuthConfig:
    """İzleme güvenlik ve kimlik doğrulama yapılandırması.

    Attributes:
        metrics_token: /metrics uç noktası erişim token'ı.
        admin_token: /admin/* yönetim uç noktaları erişim token'ı.
        enabled: Kimlik doğrulamanın aktif olup olmadığı.
        rate_limit_per_minute: İstemci IP başına dakikalık maksimum istek limiti.
        max_tracked_clients: Bellekte eşzamanlı izlenecek maksimum istemci IP sayısı.
    """

    metrics_token: str = ""
    admin_token: str = ""
    enabled: bool = True
    rate_limit_per_minute: int = DEFAULT_RATE_LIMIT_PER_MINUTE
    max_tracked_clients: int = DEFAULT_MAX_TRACKED_CLIENTS

    def to_dict(self) -> dict[str, Any]:
        """Yapılandırma nesnesini maskeli sözlük formatına dönüştürür."""
        return {
            "enabled": self.enabled,
            "metrics_token_set": bool(self.metrics_token),
            "admin_token_set": bool(self.admin_token),
            "rate_limit_per_minute": self.rate_limit_per_minute,
            "max_tracked_clients": self.max_tracked_clients,
        }

    def to_orjson_bytes(self) -> bytes:
        """Yapılandırma özetini orjson ikili serileştirme ile döndürür (GEMINI.md Kural 5)."""
        return orjson.dumps(self.to_dict())

    def __repr__(self) -> str:
        """Yapılandırma güvenli temsil metodu (token'lar maskelenir)."""
        metrics_masked = "***" if self.metrics_token else "YOK"
        admin_masked = "***" if self.admin_token else "YOK"
        return (
            f"AuthConfig(enabled={self.enabled}, metrics_token={metrics_masked}, "
            f"admin_token={admin_masked}, rate_limit_rpm={self.rate_limit_per_minute})"
        )


class MonitoringAuth:
    """İzleme uç noktaları için oran sınırlama ve token doğrulama yöneticisi."""

    def __init__(self, config: AuthConfig | None = None) -> None:
        """MonitoringAuth örneğini başlatır ve ortam değişkenlerinden token'ları yükler.

        Args:
            config: Opsiyonel yapılandırma nesnesi. Belirtilmezse varsayılan değerler kullanılır.
        """
        self._config = config or AuthConfig()
        self._lock = threading.RLock()
        self._rate_limiter: dict[str, list[float]] = {}
        self._failed_attempts: dict[str, tuple[int, float]] = {}
        self._last_cleanup_time: float = time.time()

        # Token'ları ortam değişkenlerinden yükle
        if not self._config.metrics_token:
            self._config.metrics_token = os.environ.get("ALPHA_METRICS_TOKEN", DEFAULT_METRICS_TOKEN)
        if not self._config.admin_token:
            self._config.admin_token = os.environ.get("ALPHA_ADMIN_TOKEN", DEFAULT_ADMIN_TOKEN)

        # Varsayılan güvensiz token kontrolü ve uyarısı
        if self._config.metrics_token == DEFAULT_METRICS_TOKEN:
            logger.warning(
                "varsayilan_metrics_token_kullaniliyor",
                mesaj="Üretim ortamında ALPHA_METRICS_TOKEN değişkenini tanımlayınız.",
            )
        if self._config.admin_token == DEFAULT_ADMIN_TOKEN:
            logger.warning(
                "varsayilan_admin_token_kullaniliyor",
                mesaj="Üretim ortamında ALPHA_ADMIN_TOKEN değişkenini tanımlayınız.",
            )

    def __repr__(self) -> str:
        """MonitoringAuth durumunu açıklayan temsil dizesi."""
        with self._lock:
            tracked_count = len(self._rate_limiter)
            failed_count = len(self._failed_attempts)
        return (
            f"MonitoringAuth(enabled={self._config.enabled}, "
            f"tracked_clients={tracked_count}, failed_attempts={failed_count})"
        )

    @otel_trace("monitoring_security.verify_metrics_token")
    def verify_metrics_token(self, token: str) -> bool:
        """Metrik uç noktası erişim token'ını zamanlama saldırılarına karşı korumalı doğrular.

        Args:
            token: İstemciden gelen token dizesi.

        Returns:
            Doğrulama başarılıysa True, aksi takdirde False.
        """
        if not self._config.enabled:
            return True
        return self._constant_time_compare(token, self._config.metrics_token)

    @otel_trace("monitoring_security.verify_admin_token")
    def verify_admin_token(self, token: str) -> bool:
        """Yönetim uç noktası erişim token'ını zamanlama saldırılarına karşı korumalı doğrular.

        Args:
            token: İstemciden gelen yönetici token dizesi.

        Returns:
            Doğrulama başarılıysa True, aksi takdirde False.
        """
        if not self._config.enabled:
            return True
        return self._constant_time_compare(token, self._config.admin_token)

    @otel_trace("monitoring_security.check_rate_limit")
    def check_rate_limit(self, client_ip: str) -> bool:
        """İstemci IP adresi için oran limitini (rate limit) kontrol eder.

        Args:
            client_ip: İstemcinin IP adresi.

        Returns:
            İstek kabul edilirse True, sınır aşıldıysa False.
        """
        if not self._config.enabled or not client_ip:
            return True

        now = time.time()
        window_start = now - DEFAULT_RATE_LIMIT_WINDOW_SECONDS

        with self._lock:
            self._prune_tracked_clients_if_needed(now)

            timestamps = self._rate_limiter.get(client_ip, [])
            valid_timestamps = [t for t in timestamps if t > window_start]

            if len(valid_timestamps) >= self._config.rate_limit_per_minute:
                self._rate_limiter[client_ip] = valid_timestamps
                logger.warning("oran_limiti_asildi", client_ip=client_ip, limit=self._config.rate_limit_per_minute)
                return False

            valid_timestamps.append(now)
            self._rate_limiter[client_ip] = valid_timestamps
            return True

    @otel_trace("monitoring_security.record_failed_attempt")
    def record_failed_attempt(self, client_ip: str) -> None:
        """Başarısız kimlik doğrulama denemesini kaydeder ve kritik eşikte uyarır.

        Args:
            client_ip: Başarısız girişimde bulunan istemci IP adresi.
        """
        if not client_ip:
            return

        now = time.time()
        with self._lock:
            count, _ = self._failed_attempts.get(client_ip, (0, 0.0))
            attempts = count + 1
            self._failed_attempts[client_ip] = (attempts, now)

            if attempts >= DEFAULT_MAX_FAILED_ATTEMPTS:
                logger.warning(
                    "coklu_hatali_giris_tespit_edildi",
                    client_ip=client_ip,
                    deneme_sayisi=attempts,
                )

    @otel_trace("monitoring_security.reset_client")
    def reset_client(self, client_ip: str) -> None:
        """Belirtilen istemcinin oran sınırlama ve hatalı deneme sayaçlarını sıfırlar (Self-healing).

        Args:
            client_ip: Sıfırlanacak istemci IP adresi.
        """
        if not client_ip:
            return
        with self._lock:
            self._rate_limiter.pop(client_ip, None)
            self._failed_attempts.pop(client_ip, None)

    @otel_trace("monitoring_security.get_auth_status")
    def get_auth_status(self) -> dict[str, Any]:
        """Güvenlik ve kimlik doğrulama sistem durum özetini döndürür.

        Returns:
            Durum metriklerini içeren sözlük.
        """
        with self._lock:
            tracked_clients = len(self._rate_limiter)
            failed_attempt_ips = len(self._failed_attempts)

        return {
            "auth_enabled": self._config.enabled,
            "metrics_token_set": bool(self._config.metrics_token),
            "admin_token_set": bool(self._config.admin_token),
            "rate_limit_rpm": self._config.rate_limit_per_minute,
            "tracked_clients": tracked_clients,
            "failed_attempt_ips": failed_attempt_ips,
        }

    def export_security_stats_to_polars(self) -> pl.DataFrame:
        """İzlenen istemcilerin oran limiti ve hatalı deneme istatistiklerini Polars DataFrame olarak aktarır.

        Returns:
            İstemci güvenlik durumunu içeren Polars DataFrame.
        """
        now = time.time()
        window_start = now - DEFAULT_RATE_LIMIT_WINDOW_SECONDS

        records: list[dict[str, Any]] = []
        with self._lock:
            all_ips = set(self._rate_limiter.keys()) | set(self._failed_attempts.keys())
            for ip in all_ips:
                recent_reqs = [t for t in self._rate_limiter.get(ip, []) if t > window_start]
                req_count = len(recent_reqs)
                failed_count = self._failed_attempts.get(ip, (0, 0.0))[0]
                is_limited = req_count >= self._config.rate_limit_per_minute
                last_seen = max(recent_reqs) if recent_reqs else 0.0
                last_seen_iso = datetime.fromtimestamp(last_seen, tz=UTC).isoformat() if last_seen > 0 else ""

                records.append({
                    "client_ip": ip,
                    "active_request_count": req_count,
                    "failed_attempts": failed_count,
                    "is_rate_limited": is_limited,
                    "last_seen_at": last_seen_iso,
                })

        schema = {
            "client_ip": pl.String,
            "active_request_count": pl.Int64,
            "failed_attempts": pl.Int64,
            "is_rate_limited": pl.Boolean,
            "last_seen_at": pl.String,
        }
        if not records:
            return pl.DataFrame(schema=schema)
        return pl.DataFrame(records, schema=schema)

    def _prune_tracked_clients_if_needed(self, now: float) -> None:
        """Bellek şişmesini önlemek amacıyla eski kayıtları temizler (Lock altında çağrılmalıdır)."""
        if (
            len(self._rate_limiter) < self._config.max_tracked_clients
            and now - self._last_cleanup_time < DEFAULT_RATE_LIMIT_WINDOW_SECONDS
        ):
            return

        window_start = now - DEFAULT_RATE_LIMIT_WINDOW_SECONDS
        expired_ips = [
            ip for ip, timestamps in self._rate_limiter.items()
            if not timestamps or timestamps[-1] <= window_start
        ]
        for ip in expired_ips:
            del self._rate_limiter[ip]

        # Eğer halen kapasite aşıyorsa en eski anahtarları tahliye et
        if len(self._rate_limiter) >= self._config.max_tracked_clients:
            excess = len(self._rate_limiter) - self._config.max_tracked_clients + 100
            for ip in list(self._rate_limiter.keys())[:excess]:
                self._rate_limiter.pop(ip, None)

        # Süresi dolan hatalı girişleri temizle (Bellek sızıntısı önleme)
        expired_failed_ips = [
            ip for ip, (_, last_t) in self._failed_attempts.items()
            if now - last_t > DEFAULT_FAILED_ATTEMPTS_TTL_SECONDS
        ]
        for ip in expired_failed_ips:
            del self._failed_attempts[ip]

        if len(self._failed_attempts) >= self._config.max_tracked_clients:
            excess_f = len(self._failed_attempts) - self._config.max_tracked_clients + 100
            for ip in list(self._failed_attempts.keys())[:excess_f]:
                self._failed_attempts.pop(ip, None)

        self._last_cleanup_time = now

    @staticmethod
    def _constant_time_compare(a: str, b: str) -> bool:
        """Zamanlama saldırılarını (timing attacks) önleyen sabit zamanlı dize karşılaştırması.

        Args:
            a: İlk dize.
            b: İkinci dize.

        Returns:
            Dizeler tamamen eşleşiyorsa True, aksi takdirde False.
        """
        if not a or not b:
            return False
        return hmac.compare_digest(a.encode("utf-8"), b.encode("utf-8"))


# ----------------------------------------------------------------------
# Token Ayıklama Yardımcı Fonksiyonları (HTTP Başlıkları)
# ----------------------------------------------------------------------

@otel_trace("monitoring_security.extract_bearer_token")
def extract_bearer_token(authorization: str | None) -> str | None:
    """HTTP Authorization başlığından Bearer token değerini ayıklar.

    Args:
        authorization: 'Bearer <token>' biçimindeki başlık dizesi.

    Returns:
        Ayıklanan token dizesi veya biçim geçersizse None.
    """
    if not authorization or not isinstance(authorization, str):
        return None
    parts = authorization.strip().split()
    if len(parts) == 2 and parts[0].lower() == "bearer":
        return parts[1]
    return None


@otel_trace("monitoring_security.extract_api_key")
def extract_api_key(headers: Mapping[str, str] | dict[str, Any]) -> str | None:
    """HTTP istek başlıklarından API Key değerini ayıklar.

    Desteklenen başlık anahtarları: 'x-api-key', 'X-API-Key', 'X-Api-Key', 'api-key'.

    Args:
        headers: İstek başlıkları eşlemesi.

    Returns:
        Bulunan API anahtarı dizesi veya None.
    """
    if not headers or not hasattr(headers, "get"):
        return None
    for candidate in ("x-api-key", "X-API-Key", "X-Api-Key", "api-key"):
        val = headers.get(candidate)
        if val and isinstance(val, str):
            return val.strip()
    return None


# ----------------------------------------------------------------------
# Genişletilebilir Kimlik Doğrulama Arayüzü (Extensible Auth)
# ----------------------------------------------------------------------

@dataclass
class AuthResult:
    """Kimlik doğrulama ve yetkilendirme işlem sonucu.

    Attributes:
        authenticated: Kimliğin geçerli olup olmadığı.
        user_id: Doğrulanan kullanıcı veya servis kimliği.
        roles: Kullanıcıya atanmış roller listesi.
        error: Başarısızlık durumunda açıklayıcı hata mesajı.
    """

    authenticated: bool
    user_id: str = ""
    roles: list[str] = field(default_factory=list)
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Doğrulama sonucunu sözlük formatına dönüştürür."""
        return {
            "authenticated": self.authenticated,
            "user_id": self.user_id,
            "roles": self.roles,
            "error": self.error,
        }

    def to_orjson_bytes(self) -> bytes:
        """Doğrulama sonucunu orjson ikili serileştirme ile döndürür (GEMINI.md Kural 5)."""
        return orjson.dumps(self.to_dict())

    def __repr__(self) -> str:
        """AuthResult durumunu açıklayan temsil dizesi."""
        return (
            f"AuthResult(auth={self.authenticated}, user_id='{self.user_id}', "
            f"roles={self.roles}, error='{self.error}')"
        )

    def has_role(self, role: str) -> bool:
        """Kullanıcının belirtilen role sahip olup olmadığını kontrol eder.

        Args:
            role: Denetlenecek rol adı.

        Returns:
            Rol mevcutsa True, değilse False.
        """
        target = role.lower()
        return any(r.lower() == target for r in self.roles)


class AuthProvider:
    """Tüm kimlik doğrulama sağlayıcıları için soyut temel arayüz."""

    @otel_trace("monitoring_security.AuthProvider.verify")
    async def verify(self, token: str, request_context: dict[str, Any] | None = None) -> AuthResult:
        """Gelen token'ı doğrular ve AuthResult döndürür.

        Args:
            token: İstemciden gelen token dizesi.
            request_context: Opsiyonel istek bağlamı verileri.

        Returns:
            Kimlik doğrulama sonucu.
        """
        raise NotImplementedError("Tüm AuthProvider alt sınıfları verify() metodunu uygulamalıdır.")

    @otel_trace("monitoring_security.AuthProvider.name")
    def name(self) -> str:
        """Sağlayıcı sınıf adını döndürür."""
        return self.__class__.__name__

    def __repr__(self) -> str:
        """AuthProvider temsil dizesi."""
        return f"{self.name()}()"


class StaticTokenProvider(AuthProvider):
    """Statik token ve ilişkili rol eşleştirmesi ile çalışan sağlayıcı."""

    def __init__(self, tokens: dict[str, list[str]]) -> None:
        """StaticTokenProvider örneğini başlatır.

        Args:
            tokens: Token değeri ve sahip olduğu roller sözlüğü: {"token_degeri": ["admin", "viewer"]}
        """
        self._tokens = dict(tokens)

    def __repr__(self) -> str:
        """StaticTokenProvider temsil dizesi (token'lar gizlenir)."""
        return f"StaticTokenProvider(token_count={len(self._tokens)})"

    @otel_trace("monitoring_security.StaticTokenProvider.verify")
    async def verify(self, token: str, request_context: dict[str, Any] | None = None) -> AuthResult:
        """Statik token listesini sabit zamanlı karşılaştırma ile kontrol eder.

        Args:
            token: İstemciden gelen token dizesi.
            request_context: Opsiyonel istek bağlamı.

        Returns:
            AuthResult nesnesi.
        """
        if not token:
            return AuthResult(authenticated=False, error="Token belirtilmedi.")

        for valid_token, roles in self._tokens.items():
            if hmac.compare_digest(token.encode("utf-8"), valid_token.encode("utf-8")):
                return AuthResult(authenticated=True, user_id="static_token_user", roles=roles)

        return AuthResult(authenticated=False, error="Geçersiz kimlik doğrulama token'ı.")


class JWTProvider(AuthProvider):
    """JSON Web Token (JWT) ve opsiyonel JWKS genel anahtar doğrulama sağlayıcısı."""

    def __init__(
        self,
        secret: str = "",
        algorithm: str = "HS256",
        issuer: str = "",
        audience: str = "",
        role_claim: str = "roles",
        jwks_url: str = "",
        jwks_cache_ttl_s: int = DEFAULT_JWKS_CACHE_TTL_SECONDS,
    ) -> None:
        """JWTProvider örneğini başlatır.

        Args:
            secret: Simetrik doğrulama için gizli anahtar (HS256).
            algorithm: İmzalamada kullanılan algoritma (HS256 veya RS256).
            issuer: Beklenen JWT veren (iss) değeri.
            audience: Beklenen hedef kitle (aud) değeri.
            role_claim: JWT claim'leri içinde rollerin bulunduğu anahtar.
            jwks_url: RS256 durumunda JWKS anahtarlarının çekileceği URL.
            jwks_cache_ttl_s: JWKS önbellek geçerlilik süresi (saniye).
        """
        self._secret = secret
        self._algorithm = algorithm
        self._issuer = issuer
        self._audience = audience
        self._role_claim = role_claim
        self._jwks_url = jwks_url
        self._jwks_cache_ttl_s = jwks_cache_ttl_s
        self._jwks_cache: dict[str, Any] = {}
        self._jwks_last_fetch: float = 0.0
        self._jwks_lock: asyncio.Lock | None = None

    def _get_jwks_lock(self) -> asyncio.Lock:
        """JWKS asenkron kilidini gerektiğinde (lazy) oluşturur."""
        if self._jwks_lock is None:
            self._jwks_lock = asyncio.Lock()
        return self._jwks_lock

    def __repr__(self) -> str:
        """JWTProvider temsil dizesi."""
        return (
            f"JWTProvider(algorithm='{self._algorithm}', issuer='{self._issuer}', "
            f"audience='{self._audience}', jwks_url='{self._jwks_url}')"
        )

    @otel_trace("monitoring_security.JWTProvider.verify")
    async def verify(self, token: str, request_context: dict[str, Any] | None = None) -> AuthResult:
        """JWT token'ını geçerlilik süresi, imza ve roller açısından denetler.

        Args:
            token: İstemciden gelen JWT dizesi.
            request_context: Opsiyonel istek bağlamı.

        Returns:
            AuthResult nesnesi.
        """
        if not token:
            return AuthResult(authenticated=False, error="Token boş olamaz.")

        try:
            import jwt as pyjwt
        except ImportError:
            try:
                from jose import jwt as pyjwt
            except ImportError:
                return AuthResult(
                    authenticated=False,
                    error="JWT kitaplığı bulunamadı (PyJWT veya python-jose kurulu olmalıdır).",
                )

        try:
            key = await self._get_key(token, pyjwt)

            payload = pyjwt.decode(
                token,
                key,
                algorithms=[self._algorithm],
                issuer=self._issuer if self._issuer else None,
                audience=self._audience if self._audience else None,
                options={"verify_exp": True},
            )

            user_id = str(payload.get("sub", payload.get("user_id", "")))
            raw_roles = payload.get(self._role_claim, [])
            roles: list[str] = [raw_roles] if isinstance(raw_roles, str) else list(raw_roles)

            return AuthResult(authenticated=True, user_id=user_id, roles=roles)

        except getattr(pyjwt, "ExpiredSignatureError", Exception) as e:
            if "expired" in str(e).lower() or isinstance(e, getattr(pyjwt, "ExpiredSignatureError", ())):
                return AuthResult(authenticated=False, error="Token süresi dolmuş.")
            return AuthResult(authenticated=False, error=f"Token doğrulama hatası: {e}")
        except getattr(pyjwt, "InvalidKeyError", ()):
            # Anahtar rotasyonu tespit edildiğinde önbelleği temizle
            async with self._get_jwks_lock():
                self._jwks_cache.clear()
                self._jwks_last_fetch = 0.0
            return AuthResult(authenticated=False, error="Anahtar rotasyonu algılandı, lütfen tekrar deneyin.")
        except Exception as e:
            return AuthResult(authenticated=False, error=f"Geçersiz token: {e}")

    async def _get_key(self, token: str, pyjwt: Any) -> str | dict[str, Any]:
        """JWT doğrulama için uygun anahtarı (simetrik secret veya JWKS public key) döndürür."""
        if self._algorithm == "HS256":
            return self._secret

        if self._jwks_url:
            await self._refresh_jwks_if_needed()
            try:
                unverified = pyjwt.get_unverified_header(token)
                kid = unverified.get("kid", "")
                if kid and kid in self._jwks_cache:
                    return self._jwks_cache[kid]
            except Exception as e:
                logger.debug("jwks_kid_ayristirma_hatasi", hata=str(e))

        return self._secret

    async def _refresh_jwks_if_needed(self) -> None:
        """Gerekiyorsa JWKS uç noktasından genel anahtarları çeker ve önbelleğe alır."""
        now = time.time()
        if now - self._jwks_last_fetch < self._jwks_cache_ttl_s:
            return

        async with self._get_jwks_lock():
            # Çift kontrol kilidi (double-checked locking)
            if now - self._jwks_last_fetch < self._jwks_cache_ttl_s:
                return

            try:
                async with httpx.AsyncClient(timeout=DEFAULT_HTTP_TIMEOUT_SECONDS) as client:
                    resp = await client.get(self._jwks_url)
                    if resp.status_code == 200:
                        jwks = orjson.loads(resp.content)
                        for key in jwks.get("keys", []):
                            kid = key.get("kid", "")
                            if kid:
                                self._jwks_cache[kid] = key
                        self._jwks_last_fetch = now
                        logger.info("jwks_anahtarlari_yenilendi", anahtar_sayisi=len(self._jwks_cache))
                    else:
                        logger.warning("jwks_istegi_hatali", durum_kodu=resp.status_code)
            except Exception as e:
                logger.warning("jwks_yenileme_hatasi", hata=str(e))


class OAuthProvider(AuthProvider):
    """OAuth 2.0 / OIDC sağlayıcısı (JWT doğrulama ve rol yetkilendirmesi)."""

    def __init__(
        self,
        issuer: str = "",
        audience: str = "",
        jwks_url: str = "",
        secret: str = "",
        role_claim: str = "roles",
    ) -> None:
        """OAuthProvider örneğini başlatır.

        Args:
            issuer: Kimlik sağlayıcı veren (iss) adresi.
            audience: Hedef kitle (aud) kimliği.
            jwks_url: JWKS anahtar kümesi URL adresi.
            secret: Simetrik doğrulama gerekliyse gizli anahtar.
            role_claim: Roller için claim adı.
        """
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
            jwks_url=jwks_url,
        )

    def __repr__(self) -> str:
        """OAuthProvider temsil dizesi."""
        return f"OAuthProvider(issuer='{self._issuer}', audience='{self._audience}')"

    @otel_trace("monitoring_security.OAuthProvider.verify")
    async def verify(self, token: str, request_context: dict[str, Any] | None = None) -> AuthResult:
        """OAuth token'ını iç JWTProvider aracılığıyla doğrular.

        Args:
            token: İstemciden gelen OAuth token dizesi.
            request_context: Opsiyonel istek bağlamı.

        Returns:
            AuthResult nesnesi.
        """
        if not self._secret and not self._jwks_url:
            return AuthResult(authenticated=False, error="OAuth yapılandırılmadı (secret veya jwks_url eksik).")
        return await self._jwt_provider.verify(token, request_context)


# Rol -> İzin haritası
ROLE_PERMISSIONS: Final[dict[str, list[str]]] = {
    "admin": ["read", "write", "admin", "metrics", "alerts", "portfolio"],
    "operator": ["read", "write", "metrics", "alerts", "portfolio"],
    "viewer": ["read", "metrics"],
}


class AuthManager:
    """Çoklu kimlik doğrulama sağlayıcı yöneticisi ve Rol Tabanlı Erişim Denetimi (RBAC)."""

    def __init__(self) -> None:
        """AuthManager örneğini başlatır."""
        self._providers: list[AuthProvider] = []
        self._lock = threading.RLock()

    def __repr__(self) -> str:
        """AuthManager temsil dizesi."""
        with self._lock:
            provider_names = [p.name() for p in self._providers]
        return f"AuthManager(providers={provider_names})"

    @otel_trace("monitoring_security.AuthManager.add_provider")
    def add_provider(self, provider: AuthProvider) -> None:
        """Zincire yeni bir kimlik doğrulama sağlayıcısı ekler.

        Args:
            provider: AuthProvider arayüzünü uygulayan sağlayıcı örneği.
        """
        with self._lock:
            self._providers.append(provider)
            if len(self._providers) > 100:
                self._providers = self._providers[-100:]

    @otel_trace("monitoring_security.AuthManager.verify")
    async def verify(self, token: str, request_context: dict[str, Any] | None = None) -> AuthResult:
        """Kayıtlı sağlayıcıları sırayla dener ve ilk başarılı sonucu döndürür.

        Args:
            token: İstemciden gelen token dizesi.
            request_context: Opsiyonel istek bağlamı.

        Returns:
            Başarılı ilk AuthResult veya hiçbiri doğrulamazsa başarısız AuthResult.
        """
        with self._lock:
            providers = list(self._providers)

        for provider in providers:
            result = await provider.verify(token, request_context)
            if result.authenticated:
                return result

        return AuthResult(authenticated=False, error="Hiçbir sağlayıcı token'ı doğrulamadı.")

    @otel_trace("monitoring_security.AuthManager.verify_permission")
    async def verify_permission(self, token: str, permission: str) -> AuthResult:
        """Token'ı doğrular ve kullanıcının belirtilen izne sahip olduğunu onaylar.

        Args:
            token: İstemciden gelen token.
            permission: İstenen yetki/izin adı (örn: 'metrics', 'admin', 'write').

        Returns:
            İzin onaylandıysa yetkili AuthResult, aksi halde hata içeren AuthResult.
        """
        result = await self.verify(token)
        if not result.authenticated:
            return result

        target_perm = permission.lower()
        for role in result.roles:
            perms = [p.lower() for p in ROLE_PERMISSIONS.get(role, [])]
            if target_perm in perms or "admin" in perms:
                return result

        return AuthResult(
            authenticated=True,
            user_id=result.user_id,
            roles=result.roles,
            error=f"İzin reddedildi: '{permission}' (mevcut roller: {result.roles})",
        )

    @otel_trace("monitoring_security.AuthManager.get_providers")
    def get_providers(self) -> list[str]:
        """Kayıtlı tüm sağlayıcıların adlarını liste olarak döndürür."""
        with self._lock:
            return [p.name() for p in self._providers]


# ----------------------------------------------------------------------
# Tekil Örnekler ve Kolaylık Fonksiyonları (Singleton Instances & Aliases)
# ----------------------------------------------------------------------
monitoring_auth: Final[MonitoringAuth] = MonitoringAuth()
auth_manager: Final[AuthManager] = AuthManager()

export_security_stats_to_polars = monitoring_auth.export_security_stats_to_polars
check_rate_limit = monitoring_auth.check_rate_limit
verify_metrics_token = monitoring_auth.verify_metrics_token
verify_admin_token = monitoring_auth.verify_admin_token
reset_client = monitoring_auth.reset_client

__all__: Final[list[str]] = [
    "DEFAULT_ADMIN_TOKEN",
    "DEFAULT_FAILED_ATTEMPTS_TTL_SECONDS",
    "DEFAULT_HTTP_TIMEOUT_SECONDS",
    "DEFAULT_JWKS_CACHE_TTL_SECONDS",
    "DEFAULT_MAX_FAILED_ATTEMPTS",
    "DEFAULT_MAX_TRACKED_CLIENTS",
    "DEFAULT_METRICS_TOKEN",
    "DEFAULT_RATE_LIMIT_PER_MINUTE",
    "DEFAULT_RATE_LIMIT_WINDOW_SECONDS",
    "ROLE_PERMISSIONS",
    "AuthConfig",
    "AuthManager",
    "AuthProvider",
    "AuthResult",
    "JWTProvider",
    "MonitoringAuth",
    "OAuthProvider",
    "StaticTokenProvider",
    "auth_manager",
    "check_rate_limit",
    "export_security_stats_to_polars",
    "extract_api_key",
    "extract_bearer_token",
    "monitoring_auth",
    "otel_trace",
    "reset_client",
    "verify_admin_token",
    "verify_metrics_token",
]
