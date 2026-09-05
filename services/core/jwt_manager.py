"""
ALPHA BIST — JWT Token Manager

Borsa İstanbul (BIST) mikroservis ve API erişimleri için JWT tabanlı kimlik doğrulama,
yetkilendirme, API anahtarı üretimi ve gizli anahtar (secret key) rotasyon motoru.

Özellikler:
1. HMAC-SHA256 (HS256) tabanlı endüstri standardı token üretimi ve doğrulaması.
2. Otomatik padding ve güvenli URL-safe Base64 kodlama/çözme.
3. Access Token, Refresh Token ve uzun ömürlü API Key desteği.
4. JTI (JWT ID) tabanlı token iptali (revocation / blacklist) ve thread-safe takip.
5. Dinamik gizli anahtar rotasyonu (secret rotation).
6. Güvenli varsayılanlar: Boş gizli anahtar durumunda otomatik CSPRNG anahtar türetimi.
7. DuckDB ve Polars entegrasyonu: Denetim ve iptal edilen token'ların analitik dışa aktarımı.

Referanslar:
- CORE-NIHAI-SPEC.md - Section 2.4
- RFC 7519 (JSON Web Token)
- SPK Bilgi Sistemleri Yönetimi Tebliği (Kimlik ve Erişim Güvenliği)
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import os
import secrets
import threading
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from pathlib import Path
from typing import Any, Final

import duckdb
import orjson
import polars as pl
import structlog

from services.core.otel import otel_trace

logger = structlog.get_logger(__name__)

# =====================================================
# SABİTLER (CONSTANTS)
# =====================================================

DEFAULT_ACCESS_TOKEN_TTL_HOURS: Final[int] = 24
DEFAULT_REFRESH_TOKEN_TTL_DAYS: Final[int] = 7
DEFAULT_API_KEY_TTL_DAYS: Final[int] = 365
DEFAULT_MIN_SECRET_LEN: Final[int] = 16
DEFAULT_JWT_ALGORITHM: Final[str] = "HS256"
DEFAULT_MAX_REVOKED_HISTORY: Final[int] = 5000
DEFAULT_JWT_AUDIT_DB_PATH: Final[Path] = Path("data/duckdb/alpha_bist_audit.duckdb")


# =====================================================
# TOKEN TÜRLERİ VE VERİ MODELLERİ
# =====================================================


class TokenType(StrEnum):
    """JWT belirteç türleri."""

    ACCESS = "access"
    REFRESH = "refresh"
    API_KEY = "api_key"


@dataclass(slots=True)
class JWTClaims:
    """JWT talep ve yetkilendirme veri modeli.

    Attributes:
        sub: Kullanıcı veya servis kimliği (user_id / service_id).
        role: Atanmış yetki rolü (TRADER, RISK_OFFICER, ADMIN vb.).
        permissions: İzin listesi (READ, WRITE, EXECUTE vb.).
        token_type: Token tipi (access, refresh, api_key).
        issued_at: Üretilme zaman damgası (Unix epoch saniye).
        expires_at: Geçerlilik bitiş zamanı (Unix epoch saniye).
        jti: Benzersiz belirteç kimliği (JWT ID).
    """

    sub: str
    role: str
    permissions: list[str] = field(default_factory=list)
    token_type: TokenType = TokenType.ACCESS
    issued_at: float = field(default_factory=time.time)
    expires_at: float = 0.0
    jti: str = field(default_factory=lambda: secrets.token_hex(8))

    def to_dict(self) -> dict[str, Any]:
        """Claims nesnesini standart JWT sözlüğüne dönüştürür.

        Returns:
            dict[str, Any]: JWT payload sözlüğü.
        """
        return {
            "sub": self.sub,
            "role": self.role,
            "permissions": self.permissions,
            "type": self.token_type.value,
            "iat": self.issued_at,
            "exp": self.expires_at,
            "jti": self.jti,
        }

    def to_orjson_bytes(self) -> bytes:
        """Claims nesnesini JSON bayt dizisine dönüştürür.

        Returns:
            bytes: JSON serileştirilmiş veri.
        """
        return orjson.dumps(self.to_dict())

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> JWTClaims:
        """Sözlükten JWTClaims nesnesi oluşturur.

        Args:
            data: JWT payload verisi.

        Returns:
            JWTClaims: Başlatılmış claims nesnesi.
        """
        raw_type = data.get("type", "access")
        try:
            tok_type = TokenType(raw_type)
        except ValueError:
            tok_type = TokenType.ACCESS

        return cls(
            sub=str(data.get("sub", "")),
            role=str(data.get("role", "")),
            permissions=list(data.get("permissions", [])),
            token_type=tok_type,
            issued_at=float(data.get("iat", 0.0)),
            expires_at=float(data.get("exp", 0.0)),
            jti=str(data.get("jti", "")),
        )

    @property
    def is_expired(self) -> bool:
        """Token süresinin dolup dolmadığını denetler.

        Returns:
            bool: Süre dolmuşsa True, geçerliyse False.
        """
        return time.time() > self.expires_at

    def __repr__(self) -> str:
        """Claims metin gösterimi."""
        kalan_sn = max(0.0, self.expires_at - time.time())
        return (
            f"JWTClaims(sub={self.sub!r}, role={self.role!r}, type={self.token_type.value!r}, "
            f"kalan_sure_sn={kalan_sn:.0f}, jti={self.jti!r})"
        )


class JWTError(Exception):
    """JWT operasyonları sırasında fırlatılan özel istisna sınıfı."""


# =====================================================
# JWT MANAGER ÇEKİRDEK SERVİSİ
# =====================================================


class JWTManager:
    """HMAC-SHA256 tabanlı JWT token yönetim servisi.

    Token oluşturma, kriptografik imza doğrulama, token yenileme,
    kara liste (revocation) ve gizli anahtar rotasyonunu thread-safe olarak yürütür.
    """

    def __init__(
        self,
        secret_key: str | None = None,
        access_token_ttl_hours: int = DEFAULT_ACCESS_TOKEN_TTL_HOURS,
        refresh_token_ttl_days: int = DEFAULT_REFRESH_TOKEN_TTL_DAYS,
        algorithm: str = DEFAULT_JWT_ALGORITHM,
    ) -> None:
        """JWTManager örneğini başlatır.

        Args:
            secret_key: HMAC imzalama için gizli anahtar (None ise ortam değişkeninden veya güvenli rastgele üretilir).
            access_token_ttl_hours: Erişim belirteci ömrü (saat).
            refresh_token_ttl_days: Yenileme belirteci ömrü (gün).
            algorithm: Kriptografik imzalama algoritması (Varsayılan HS256).
        """
        self._lock: threading.RLock = threading.RLock()
        candidate_secret = secret_key or os.environ.get("JWT_SECRET", "")

        if not candidate_secret:
            # Boş gizli anahtar güvenlik açığını önleme: CSPRNG ile güvenli anahtar türetimi
            generated_secret = secrets.token_urlsafe(32)
            logger.warning(
                "jwt_secret_not_provided_fallback_generated",
                aciklama="JWT_SECRET sağlanmadığı için dinamik CSPRNG anahtarı türetildi.",
            )
            self._secret: str = generated_secret
        else:
            self._secret = candidate_secret

        self._access_ttl: timedelta = timedelta(hours=access_token_ttl_hours)
        self._refresh_ttl: timedelta = timedelta(days=refresh_token_ttl_days)
        self._algorithm: str = algorithm
        self._revoked_tokens: set[str] = set()
        self._revoked_details: dict[str, dict[str, Any]] = {}
        self._issued_tokens_audit: list[dict[str, Any]] = []

    @otel_trace("jwt_manager.generate_token")
    def generate_token(
        self,
        user_id: str,
        role: str,
        permissions: list[str] | None = None,
        token_type: TokenType = TokenType.ACCESS,
        custom_claims: dict[str, Any] | None = None,
    ) -> str:
        """JWT belirteci oluşturur ve imzalar.

        Args:
            user_id: Kullanıcı veya servis tanımlayıcısı.
            role: Atanan yetki rolü.
            permissions: Opsiyonel izin listesi.
            token_type: Belirteç türü (access veya refresh).
            custom_claims: İlave talep alanları.

        Returns:
            str: Üretilen ve imzalanan JWT token metni.
        """
        if not user_id or not str(user_id).strip():
            raise JWTError("Kullanıcı kimliği (user_id) boş olamaz.")
        if not role or not str(role).strip():
            raise JWTError("Rol (role) boş olamaz.")

        now = time.time()
        ttl = self._access_ttl if token_type == TokenType.ACCESS else self._refresh_ttl
        clean_perms = permissions if permissions is not None else []

        claims = JWTClaims(
            sub=str(user_id).strip(),
            role=str(role).strip(),
            permissions=clean_perms,
            token_type=token_type,
            issued_at=now,
            expires_at=now + ttl.total_seconds(),
        )

        header = {"alg": self._algorithm, "typ": "JWT"}
        header_bytes = orjson.dumps(header)
        header_b64 = self._base64url_encode(header_bytes)

        payload = claims.to_dict()
        if custom_claims:
            payload.update(custom_claims)
        payload_bytes = orjson.dumps(payload)
        payload_b64 = self._base64url_encode(payload_bytes)

        message = f"{header_b64}.{payload_b64}"
        signature = self._sign(message)
        sig_b64 = self._base64url_encode(signature)

        token = f"{header_b64}.{payload_b64}.{sig_b64}"

        with self._lock:
            self._issued_tokens_audit.append(
                {
                    "jti": claims.jti,
                    "sub": claims.sub,
                    "role": claims.role,
                    "token_type": claims.token_type.value,
                    "issued_at": datetime.fromtimestamp(now, UTC).isoformat(),
                    "expires_at": datetime.fromtimestamp(claims.expires_at, UTC).isoformat(),
                }
            )
            if len(self._issued_tokens_audit) > DEFAULT_MAX_REVOKED_HISTORY:
                self._issued_tokens_audit = self._issued_tokens_audit[-DEFAULT_MAX_REVOKED_HISTORY:]

        logger.debug(
            "jwt_token_generated",
            user_id=user_id,
            role=role,
            type=token_type.value,
            jti=claims.jti,
        )
        return token

    @otel_trace("jwt_manager.validate_token")
    def validate_token(self, token: str) -> JWTClaims:
        """JWT belirtecini doğrular, imzasını teyit eder ve claims nesnesini döndürür.

        Args:
            token: Doğrulanacak JWT token metni (Bearer veya ak_ ön eki desteklenir).

        Returns:
            JWTClaims: Doğrulanmış talep modeli.

        Raises:
            JWTError: Token formatı geçersizse, imza uyuşmuyorsa, süre dolmuşsa veya iptal edilmişse.
        """
        if not token or not isinstance(token, str):
            raise JWTError("Belirteç dizesi boş veya geçersiz formatta.")

        raw_token = token.strip()
        if raw_token.lower().startswith("bearer "):
            raw_token = raw_token[7:].strip()
        elif raw_token.startswith("ak_"):
            raw_token = raw_token[3:].strip()

        parts = raw_token.split(".")
        if len(parts) != 3:
            raise JWTError(f"Geçersiz token formatı: 3 parçalı JWT beklenirken {len(parts)} parça bulundu.")

        header_b64, payload_b64, sig_b64 = parts

        try:
            message = f"{header_b64}.{payload_b64}"
            expected_sig = self._sign(message)
            actual_sig = self._base64url_decode(sig_b64)

            if not hmac.compare_digest(expected_sig, actual_sig):
                raise JWTError("Kriptografik imza doğrulaması başarısız (Invalid signature).")

            payload_bytes = self._base64url_decode(payload_b64)
            payload = orjson.loads(payload_bytes)
            claims = JWTClaims.from_dict(payload)

            if claims.is_expired:
                raise JWTError(f"Belirteç süresi dolmuş (Token expired at {claims.expires_at}).")

            with self._lock:
                if claims.jti in self._revoked_tokens:
                    raise JWTError(f"Belirteç iptal edilmiş kara listede (Token revoked: {claims.jti}).")

            return claims

        except JWTError:
            raise
        except (binascii.Error, orjson.JSONDecodeError, UnicodeDecodeError) as err:
            raise JWTError(f"Belirteç ayrıştırma veya Base64 kod çözme hatası: {err}") from err
        except Exception as exc:
            raise JWTError(f"Belirteç doğrulama sürecinde beklenmeyen hata: {exc}") from exc

    @otel_trace("jwt_manager.refresh_token")
    def refresh_token(self, token: str) -> str:
        """Geçerli bir yenileme (refresh) belirteci ile yeni bir erişim (access) belirteci üretir.

        Args:
            token: Doğrulanacak refresh token.

        Returns:
            str: Yeni access token metni.

        Raises:
            JWTError: Token geçersizse veya tipi REFRESH değilse.
        """
        claims = self.validate_token(token)

        if claims.token_type != TokenType.REFRESH:
            raise JWTError(f"Yenileme için 'refresh' tipi beklenirken '{claims.token_type.value}' bulundu.")

        return self.generate_token(
            user_id=claims.sub,
            role=claims.role,
            permissions=claims.permissions,
            token_type=TokenType.ACCESS,
        )

    @otel_trace("jwt_manager.revoke_token")
    def revoke_token(self, token_or_jti: str, reason: str = "Manual revocation") -> bool:
        """Belirteci veya JTI kimliğini kara listeye alarak iptal eder.

        Args:
            token_or_jti: İptal edilecek belirteç dizesi veya 16 karakterli benzersiz JTI kimliği.
            reason: İptal gerekçesi.

        Returns:
            bool: İptal başarılıysa True, belirteç zaten geçersizse False.
        """
        if not token_or_jti or not isinstance(token_or_jti, str):
            return False

        target = token_or_jti.strip()
        jti: str = ""
        sub: str = "unknown"

        if "." in target:
            try:
                claims = self.validate_token(target)
                jti = claims.jti
                sub = claims.sub
            except JWTError as e:
                logger.warning("jwt_revoke_validation_failed", error=str(e))
                return False
        else:
            jti = target

        with self._lock:
            self._revoked_tokens.add(jti)
            self._revoked_details[jti] = {
                "jti": jti,
                "sub": sub,
                "revoked_at": datetime.now(UTC).isoformat(),
                "reason": reason,
            }
            if len(self._revoked_tokens) > DEFAULT_MAX_REVOKED_HISTORY:
                oldest_jtis = list(self._revoked_details.keys())[:-DEFAULT_MAX_REVOKED_HISTORY]
                for old_jti in oldest_jtis:
                    self._revoked_tokens.discard(old_jti)
                    self._revoked_details.pop(old_jti, None)

        logger.info("jwt_token_revoked", user_id=sub, jti=jti, reason=reason)
        return True

    @otel_trace("jwt_manager.generate_api_key")
    def generate_api_key(
        self,
        user_id: str,
        role: str,
        permissions: list[str] | None = None,
        name: str = "service_api_key",
        ttl_days: int = DEFAULT_API_KEY_TTL_DAYS,
    ) -> str:
        """Uzun ömürlü servis API anahtarı (API Key) üretir.

        Args:
            user_id: Servis veya kullanıcı tanımlayıcısı.
            role: Servis rolü.
            permissions: İzin listesi.
            name: Anahtar tanıtıcı ismi.
            ttl_days: Geçerlilik süresi (gün).

        Returns:
            str: `ak_` ön eki ile başlayan API anahtarı.
        """
        now = time.time()
        expires = now + ttl_days * 86400.0
        clean_perms = permissions if permissions is not None else []

        claims = JWTClaims(
            sub=user_id,
            role=role,
            permissions=clean_perms,
            token_type=TokenType.API_KEY,
            issued_at=now,
            expires_at=expires,
        )

        header = {"alg": self._algorithm, "typ": "JWT", "kid": name}
        header_bytes = orjson.dumps(header)
        header_b64 = self._base64url_encode(header_bytes)

        payload_bytes = orjson.dumps(claims.to_dict())
        payload_b64 = self._base64url_encode(payload_bytes)

        message = f"{header_b64}.{payload_b64}"
        signature = self._sign(message)
        sig_b64 = self._base64url_encode(signature)

        api_key = f"ak_{header_b64}.{payload_b64}.{sig_b64}"

        with self._lock:
            self._issued_tokens_audit.append(
                {
                    "jti": claims.jti,
                    "sub": claims.sub,
                    "role": claims.role,
                    "token_type": TokenType.API_KEY.value,
                    "issued_at": datetime.fromtimestamp(now, UTC).isoformat(),
                    "expires_at": datetime.fromtimestamp(expires, UTC).isoformat(),
                }
            )

        logger.info("api_key_generated", user_id=user_id, name=name, role=role, jti=claims.jti)
        return api_key

    @otel_trace("jwt_manager.validate_api_key")
    def validate_api_key(self, api_key: str) -> JWTClaims:
        """API anahtarını doğrular ve claims modelini döndürür.

        Args:
            api_key: Doğrulanacak `ak_` formatlı API anahtarı.

        Returns:
            JWTClaims: Doğrulanmış yetki modeli.

        Raises:
            JWTError: Anahtar geçersizse veya tipi API_KEY değilse.
        """
        claims = self.validate_token(api_key)
        if claims.token_type != TokenType.API_KEY:
            raise JWTError(f"API anahtarı beklenirken '{claims.token_type.value}' tipi bulundu.")
        return claims

    @otel_trace("jwt_manager.rotate_secret")
    def rotate_secret(self, new_secret: str) -> None:
        """Gizli anahtarı atomik olarak değiştirir (Secret Rotation).

        Not: Eski anahtarla imzalanmış tüm token'lar geçersiz hale gelir.

        Args:
            new_secret: Yeni gizli anahtar dizesi.

        Raises:
            JWTError: Yeni gizli anahtar uzunluğu yetersizse.
        """
        if not new_secret or len(new_secret) < DEFAULT_MIN_SECRET_LEN:
            raise JWTError(
                f"Yeni gizli anahtar en az {DEFAULT_MIN_SECRET_LEN} karakter olmalıdır (Güvenlik Kuralı)."
            )

        with self._lock:
            old_preview = self._secret[:4] + "***" if len(self._secret) >= 4 else "***"
            self._secret = new_secret
            logger.warning("jwt_secret_rotated", old_secret_preview=old_preview)

    def is_token_revoked(self, token_or_jti: str) -> bool:
        """Belirtecin veya JTI kimliğinin iptal edilip edilmediğini denetler.

        Args:
            token_or_jti: Kontrol edilecek belirteç metni veya doğrudan JTI kimliği.

        Returns:
            bool: İptal edilmişse True, geçerliyse False.
        """
        if not token_or_jti or not isinstance(token_or_jti, str):
            return False

        target = token_or_jti.strip()
        if "." in target:
            try:
                claims = self.validate_token(target)
                target = claims.jti
            except JWTError:
                return True

        with self._lock:
            return target in self._revoked_tokens

    def is_revoked(self, jti: str) -> bool:
        """Belirteç JTI kimliğinin iptal edilip edilmediğini denetler (is_token_revoked alias)."""
        return self.is_token_revoked(jti)

    def _sign(self, message: str) -> bytes:
        """HMAC-SHA256 ile mesajı imzalar."""
        with self._lock:
            secret_bytes = self._secret.encode("utf-8")
        return hmac.new(secret_bytes, message.encode("utf-8"), hashlib.sha256).digest()

    @staticmethod
    def _base64url_encode(data: bytes | str) -> str:
        """URL-Safe Base64 kodlama (Padding karakterleri '=' budanır)."""
        raw_bytes = data.encode("utf-8") if isinstance(data, str) else data
        return base64.urlsafe_b64encode(raw_bytes).rstrip(b"=").decode("ascii")

    @staticmethod
    def _base64url_decode(s: str) -> bytes:
        """URL-Safe Base64 kod çözme (Gereken padding '=' karakterlerini otomatik tamamlar)."""
        clean_s = s.strip()
        padding = 4 - (len(clean_s) % 4)
        if padding != 4:
            clean_s += "=" * padding
        return base64.urlsafe_b64decode(clean_s.encode("ascii"))

    # =====================================================
    # POLARS VE DUCKDB ENTEGRASYONU
    # =====================================================

    def export_audit_to_polars(self) -> pl.DataFrame:
        """Üretilen token denetim kayıtlarını Polars DataFrame olarak döndürür.

        Returns:
            pl.DataFrame: Token denetim tablosu.
        """
        schema = {
            "jti": pl.Utf8,
            "sub": pl.Utf8,
            "role": pl.Utf8,
            "token_type": pl.Utf8,
            "issued_at": pl.Utf8,
            "expires_at": pl.Utf8,
        }
        with self._lock:
            records = list(self._issued_tokens_audit)

        if not records:
            return pl.DataFrame(schema=schema)
        return pl.DataFrame(records, schema=schema)

    def export_audit_to_duckdb(self, db_path: str | Path | None = None) -> int:
        """Token denetim kayıtlarını DuckDB tablosuna yazar.

        Args:
            db_path: Opsiyonel DuckDB dosya yolu.

        Returns:
            int: Kaydedilen kayıt sayısı.
        """
        target_path = Path(db_path) if db_path is not None else DEFAULT_JWT_AUDIT_DB_PATH
        target_path.parent.mkdir(parents=True, exist_ok=True)

        df = self.export_audit_to_polars()
        if len(df) == 0:
            return 0

        con = duckdb.connect(str(target_path))
        try:
            con.execute(
                """
                CREATE TABLE IF NOT EXISTS bist_jwt_audit_log (
                    jti VARCHAR PRIMARY KEY,
                    sub VARCHAR NOT NULL,
                    role VARCHAR NOT NULL,
                    token_type VARCHAR NOT NULL,
                    issued_at VARCHAR NOT NULL,
                    expires_at VARCHAR NOT NULL
                )
                """
            )
            con.register("df_jwt_audit", df.to_arrow())
            con.execute(
                """
                INSERT OR REPLACE INTO bist_jwt_audit_log
                SELECT * FROM df_jwt_audit
                """
            )
            con.commit()
            return len(df)
        finally:
            con.close()

    def export_revoked_to_polars(self) -> pl.DataFrame:
        """İptal edilen belirteç kayıtlarını Polars DataFrame olarak döndürür.

        Returns:
            pl.DataFrame: Kara liste tablosu.
        """
        schema = {
            "jti": pl.Utf8,
            "sub": pl.Utf8,
            "revoked_at": pl.Utf8,
            "reason": pl.Utf8,
        }
        with self._lock:
            records = list(self._revoked_details.values())

        if not records:
            return pl.DataFrame(schema=schema)
        return pl.DataFrame(records, schema=schema)

    def export_revoked_to_duckdb(self, db_path: str | Path | None = None) -> int:
        """İptal edilen belirteçleri DuckDB tablosuna yazar.

        Args:
            db_path: Opsiyonel DuckDB dosya yolu.

        Returns:
            int: Kaydedilen iptal sayısı.
        """
        target_path = Path(db_path) if db_path is not None else DEFAULT_JWT_AUDIT_DB_PATH
        target_path.parent.mkdir(parents=True, exist_ok=True)

        df = self.export_revoked_to_polars()
        if len(df) == 0:
            return 0

        con = duckdb.connect(str(target_path))
        try:
            con.execute(
                """
                CREATE TABLE IF NOT EXISTS bist_jwt_revoked_tokens (
                    jti VARCHAR PRIMARY KEY,
                    sub VARCHAR NOT NULL,
                    revoked_at VARCHAR NOT NULL,
                    reason VARCHAR NOT NULL
                )
                """
            )
            con.register("df_revoked_view", df.to_arrow())
            con.execute(
                """
                INSERT OR REPLACE INTO bist_jwt_revoked_tokens
                SELECT * FROM df_revoked_view
                """
            )
            con.commit()
            return len(df)
        finally:
            con.close()

    def __repr__(self) -> str:
        """JWTManager metin gösterimi."""
        with self._lock:
            return (
                f"JWTManager(alg={self._algorithm!r}, erisim_ttl={self._access_ttl}, "
                f"yenileme_ttl={self._refresh_ttl}, iptal_edilen={len(self._revoked_tokens)})"
            )


# =====================================================
# MODÜL DÜZEYİNDE KOLAYLIK (CONVENIENCE) FONKSİYONLARI
# =====================================================


def generate_jwt_token(
    user_id: str,
    role: str,
    permissions: list[str] | None = None,
    token_type: TokenType = TokenType.ACCESS,
    custom_claims: dict[str, Any] | None = None,
    manager: JWTManager | None = None,
) -> str:
    """JWT belirteci oluşturur."""
    inst = manager if manager is not None else jwt_manager
    return inst.generate_token(
        user_id=user_id,
        role=role,
        permissions=permissions,
        token_type=token_type,
        custom_claims=custom_claims,
    )


def validate_jwt_token(token: str, manager: JWTManager | None = None) -> JWTClaims:
    """JWT belirtecini doğrular."""
    inst = manager if manager is not None else jwt_manager
    return inst.validate_token(token=token)


def refresh_jwt_token(token: str, manager: JWTManager | None = None) -> str:
    """Refresh belirteci ile yeni access token üretir."""
    inst = manager if manager is not None else jwt_manager
    return inst.refresh_token(token=token)


def revoke_jwt_token(
    token_or_jti: str, reason: str = "Manual revocation", manager: JWTManager | None = None
) -> bool:
    """Belirteci veya JTI kimliğini kara listeye alarak iptal eder."""
    inst = manager if manager is not None else jwt_manager
    return inst.revoke_token(token_or_jti=token_or_jti, reason=reason)


def is_token_revoked(token_or_jti: str, manager: JWTManager | None = None) -> bool:
    """Belirtecin veya JTI kimliğinin iptal durumunu sorgular."""
    inst = manager if manager is not None else jwt_manager
    return inst.is_token_revoked(token_or_jti=token_or_jti)


def generate_api_key(
    user_id: str,
    role: str,
    permissions: list[str] | None = None,
    name: str = "service_api_key",
    ttl_days: int = DEFAULT_API_KEY_TTL_DAYS,
    manager: JWTManager | None = None,
) -> str:
    """Uzun ömürlü API anahtarı üretir."""
    inst = manager if manager is not None else jwt_manager
    return inst.generate_api_key(user_id=user_id, role=role, permissions=permissions, name=name, ttl_days=ttl_days)


def validate_api_key(api_key: str, manager: JWTManager | None = None) -> JWTClaims:
    """API anahtarını doğrular."""
    inst = manager if manager is not None else jwt_manager
    return inst.validate_api_key(api_key=api_key)


def rotate_jwt_secret(new_secret: str, manager: JWTManager | None = None) -> None:
    """Gizli anahtarı değiştirir."""
    inst = manager if manager is not None else jwt_manager
    inst.rotate_secret(new_secret=new_secret)


def get_jwt_manager() -> JWTManager:
    """Tekil JWTManager örneğini döndürür."""
    return jwt_manager


def export_jwt_audit_to_polars(manager: JWTManager | None = None) -> pl.DataFrame:
    """Token denetim kayıtlarını Polars tablosu olarak döndürür."""
    inst = manager if manager is not None else jwt_manager
    return inst.export_audit_to_polars()


def export_jwt_audit_to_duckdb(db_path: str | Path | None = None, manager: JWTManager | None = None) -> int:
    """Token denetim kayıtlarını DuckDB'ye yazar."""
    inst = manager if manager is not None else jwt_manager
    return inst.export_audit_to_duckdb(db_path=db_path)


def export_revoked_tokens_to_polars(manager: JWTManager | None = None) -> pl.DataFrame:
    """İptal edilen belirteçleri Polars tablosu olarak döndürür."""
    inst = manager if manager is not None else jwt_manager
    return inst.export_revoked_to_polars()


def export_revoked_tokens_to_duckdb(db_path: str | Path | None = None, manager: JWTManager | None = None) -> int:
    """İptal edilen belirteçleri DuckDB'ye yazar."""
    inst = manager if manager is not None else jwt_manager
    return inst.export_revoked_to_duckdb(db_path=db_path)


# Global Singleton Örneği
jwt_manager: Final[JWTManager] = JWTManager()

__all__: list[str] = [
    "DEFAULT_ACCESS_TOKEN_TTL_HOURS",
    "DEFAULT_API_KEY_TTL_DAYS",
    "DEFAULT_JWT_ALGORITHM",
    "DEFAULT_JWT_AUDIT_DB_PATH",
    "DEFAULT_MAX_REVOKED_HISTORY",
    "DEFAULT_MIN_SECRET_LEN",
    "DEFAULT_REFRESH_TOKEN_TTL_DAYS",
    "JWTClaims",
    "JWTError",
    "JWTManager",
    "TokenType",
    "export_jwt_audit_to_duckdb",
    "export_jwt_audit_to_polars",
    "export_revoked_tokens_to_duckdb",
    "export_revoked_tokens_to_polars",
    "generate_api_key",
    "generate_jwt_token",
    "get_jwt_manager",
    "is_token_revoked",
    "jwt_manager",
    "refresh_jwt_token",
    "revoke_jwt_token",
    "rotate_jwt_secret",
    "validate_api_key",
    "validate_jwt_token",
]
