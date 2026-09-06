"""
ALPHA BIST — mTLS (Mutual TLS) Service Mesh v1.0
=================================================
Servisler arası güvenli iletişim ve kimlik doğrulaması için mTLS implementasyonu.

Özellikler:
- Self-signed CA ve x509 sertifika desteği (cryptography kütüphanesi + openssl fallback)
- SSL context yönetimi (Sunucu + İstemci)
- FastAPI / Starlette middleware entegrasyonu (orjson tabanlı)
- gRPC TLS channel ve server credentials desteği
- Otomatik sertifika son kullanım (expiry) ve yenileme kontrolü
- Polars analitik durum dışa aktarımı (export_mtls_status_to_polars)
- Thread-safe singleton mimarisi
"""

from __future__ import annotations

import functools
import os
import ssl
import subprocess
import threading
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

import orjson
import polars as pl
import structlog
from opentelemetry import trace

logger = structlog.get_logger(__name__)
tracer = trace.get_tracer("alpha-bist.mtls")

# Sabitler
DEFAULT_RENEW_BEFORE_DAYS: Final[int] = 30
DEFAULT_MIN_TLS_VERSION: Final[int] = ssl.TLSVersion.TLSv1_2
DEFAULT_CIPHER_SUITE: Final[str] = "ECDHE+AESGCM:ECDHE+CHACHA20:DHE+AESGCM:DHE+CHACHA20:!aNULL:!MD5:!DSS"
_mtls_lock = threading.RLock()


def otel_trace(span_name: str) -> Any:
    """Metot veya fonksiyonu OpenTelemetry span içine alan dekoratör.

    Args:
        span_name: Span adı.

    Returns:
        Dekore edilmiş sarmalayıcı fonksiyon.
    """

    def decorator(func: Any) -> Any:
        """Hedef fonksiyonu OTel span ile sarmalar."""

        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            """Fonksiyon çağrısını span içinde icra eder."""
            with tracer.start_as_current_span(span_name):
                return func(*args, **kwargs)

        return wrapper

    return decorator


# =====================================================
# Konfigürasyon
# =====================================================


@dataclass
class MTLSConfig:
    """mTLS yapılandırması. Ortam değişkenlerinden veya dosya yollarından okunur."""

    # Sertifika yolları
    ca_cert: str = ""
    server_cert: str = ""
    server_key: str = ""
    client_cert: str = ""
    client_key: str = ""
    dhparam: str = ""

    # TLS ayarları
    min_tls_version: int = DEFAULT_MIN_TLS_VERSION
    verify_mode: int = ssl.CERT_REQUIRED
    check_hostname: bool = False  # Docker iç ana makine adları için

    # Sertifika yenileme
    auto_renew: bool = True
    renew_before_days: int = DEFAULT_RENEW_BEFORE_DAYS

    # Durum
    enabled: bool = True

    def __post_init__(self) -> None:
        """Varsayılan sertifika yollarını ve aktiflik durumunu belirler."""
        base = Path(__file__).parent.parent.parent / "infrastructure" / "mtls" / "certs"

        if not self.ca_cert:
            self.ca_cert = os.getenv("MTLS_CA_CERT", str(base / "ca.crt"))
        if not self.server_cert:
            self.server_cert = os.getenv("MTLS_SERVER_CERT", str(base / "server.crt"))
        if not self.server_key:
            self.server_key = os.getenv("MTLS_SERVER_KEY", str(base / "server.key"))
        if not self.client_cert:
            self.client_cert = os.getenv("MTLS_CLIENT_CERT", str(base / "client.crt"))
        if not self.client_key:
            self.client_key = os.getenv("MTLS_CLIENT_KEY", str(base / "client.key"))
        if not self.dhparam:
            self.dhparam = os.getenv("MTLS_DHPARAM", str(base / "dhparam.pem"))

        # Sertifikalar yoksa güvenli şekilde devre dışı bırak
        if not Path(self.ca_cert).exists():
            logger.warning("mtls_ca_sertifikasi_bulunamadi_devre_disi", path=self.ca_cert)
            self.enabled = False

    @otel_trace("mtls.MTLSConfig.validate")
    def validate(self) -> bool:
        """Sertifika dosyalarının varlığını ve bütünlüğünü denetler.

        Returns:
            Gerekli tüm dosyalar mevcutsa True, eksik varsa False.
        """
        if not self.enabled:
            return False

        files = {
            "CA cert": self.ca_cert,
            "Server cert": self.server_cert,
            "Server key": self.server_key,
            "Client cert": self.client_cert,
            "Client key": self.client_key,
        }

        missing = []
        for name, path in files.items():
            if not Path(path).exists():
                missing.append(f"{name}: {path}")

        if missing:
            logger.error("mtls_sertifika_dosyalari_eksik", missing=missing)
            self.enabled = False
            return False

        return True

    def __repr__(self) -> str:
        """Hassas anahtar yollarını maskeleyen metinsel temsil."""
        masked_server_key = "***" if self.server_key else "Yok"
        masked_client_key = "***" if self.client_key else "Yok"
        return (
            f"MTLSConfig(enabled={self.enabled}, ca_cert='{self.ca_cert}', "
            f"server_cert='{self.server_cert}', server_key='{masked_server_key}', "
            f"client_cert='{self.client_cert}', client_key='{masked_client_key}')"
        )


# =====================================================
# Sertifika Yönetimi
# =====================================================


class CertificateManager:
    """Sertifika yaşam döngüsü, son kullanma ve bilgi sorgulama yöneticisi."""

    def __init__(self, config: MTLSConfig) -> None:
        """Sertifika yöneticisini konfigürasyon ile ilklendirir.

        Args:
            config: mTLS konfigürasyon nesnesi.
        """
        self.config = config

    @otel_trace("mtls.CertificateManager.check_expiry")
    def check_expiry(self, cert_path: str) -> datetime | None:
        """Sertifikanın son kullanma tarihini (not_valid_after) döndürür.

        Önce hızlı ve hatasız cryptography kütüphanesini kullanır,
        olmaması durumunda openssl CLI'ye geri çekilir.

        Args:
            cert_path: İncelenecek PEM sertifika dosya yolu.

        Returns:
            Son kullanma UTC datetime nesnesi veya hata durumunda None.
        """
        p = Path(cert_path)
        if not p.exists():
            return None

        # 1. Saf Python ile cryptography kütüphanesi (1000x hızlı, CLI gerektirmez)
        try:
            from cryptography import x509

            cert_data = p.read_bytes()
            cert = x509.load_pem_x509_certificate(cert_data)
            # cryptography 42+ not_valid_after_utc kullanır
            if hasattr(cert, "not_valid_after_utc"):
                return cert.not_valid_after_utc
            return cert.not_valid_after.replace(tzinfo=UTC)
        except Exception as e_crypto:
            logger.debug("cryptography_sertifika_okuma_atlandi", path=cert_path, hata=str(e_crypto))

        # 2. Fallback: openssl CLI
        try:
            result = subprocess.run(
                ["openssl", "x509", "-in", cert_path, "-noout", "-enddate"],
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
            if result.returncode == 0 and "=" in result.stdout:
                date_str = result.stdout.strip().split("=")[1]
                dt = datetime.strptime(date_str, "%b %d %H:%M:%S %Y %Z")
                return dt.replace(tzinfo=UTC)
        except Exception as e_proc:
            logger.warning("openssl_cli_sertifika_okuma_hatasi", path=cert_path, hata=str(e_proc))

        return None

    @otel_trace("mtls.CertificateManager.needs_renewal")
    def needs_renewal(self, cert_path: str) -> bool:
        """Sertifikanın yenilenme zamanının gelip gelmediğini kontrol eder.

        Args:
            cert_path: İncelenecek sertifika dosya yolu.

        Returns:
            Yenileme gerekiyorsa True, aksi halde False.
        """
        expiry = self.check_expiry(cert_path)
        if not expiry:
            return True

        days_left = (expiry - datetime.now(UTC)).days
        if days_left <= self.config.renew_before_days:
            logger.warning("sertifika_suresi_yakinda_dolacak", path=cert_path, kalan_gun=days_left)
            return True

        return False

    @otel_trace("mtls.CertificateManager.get_cert_info")
    def get_cert_info(self, cert_path: str) -> dict[str, Any]:
        """Sertifikanın detaylı alanlarını sözlük olarak döndürür.

        Args:
            cert_path: İncelenecek sertifika yolu.

        Returns:
            Konu, veren kuruluş, geçerlilik tarihleri ve parmak izi bilgileri.
        """
        p = Path(cert_path)
        if not p.exists():
            return {}

        # 1. Cryptography ile ayrıştırma
        try:
            from cryptography import x509
            from cryptography.hazmat.primitives import hashes

            cert_data = p.read_bytes()
            cert = x509.load_pem_x509_certificate(cert_data)
            fingerprint = cert.fingerprint(hashes.SHA256()).hex().upper()
            formatted_fp = ":".join(fingerprint[i : i + 2] for i in range(0, len(fingerprint), 2))

            not_before = cert.not_valid_before_utc if hasattr(cert, "not_valid_before_utc") else cert.not_valid_before
            not_after = cert.not_valid_after_utc if hasattr(cert, "not_valid_after_utc") else cert.not_valid_after

            return {
                "subject": cert.subject.rfc4514_string(),
                "issuer": cert.issuer.rfc4514_string(),
                "not_before": not_before.isoformat(),
                "not_after": not_after.isoformat(),
                "sha256_fingerprint": formatted_fp,
                "serial_number": str(cert.serial_number),
            }
        except Exception as e_crypto:
            logger.debug("cryptography_detay_ayristirma_atlandi", path=cert_path, hata=str(e_crypto))

        # 2. Fallback: openssl CLI
        try:
            result = subprocess.run(
                ["openssl", "x509", "-in", cert_path, "-noout", "-subject", "-issuer", "-dates", "-fingerprint"],
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
            if result.returncode == 0:
                info = {}
                for line in result.stdout.strip().split("\n"):
                    if "=" in line:
                        key, _, value = line.partition("=")
                        info[key.strip().lower()] = value.strip()
                return info
        except Exception as e:
            logger.warning("openssl_detay_bilgisi_alinamadi", path=cert_path, hata=str(e))

        return {}

    @otel_trace("mtls.CertificateManager.get_all_status")
    def get_all_status(self) -> dict[str, Any]:
        """Tüm yapılandırılmış sertifikaların durumunu döndürür.

        Returns:
            CA, sunucu ve istemci sertifikalarının varlık ve süre durumu.
        """
        certs = {
            "ca": self.config.ca_cert,
            "server": self.config.server_cert,
            "client": self.config.client_cert,
        }

        status: dict[str, Any] = {}
        for name, path in certs.items():
            if Path(path).exists():
                expiry = self.check_expiry(path)
                days_left = (expiry - datetime.now(UTC)).days if expiry else None
                status[name] = {
                    "exists": True,
                    "path": path,
                    "expiry": expiry.isoformat() if expiry else None,
                    "days_left": days_left,
                    "needs_renewal": self.needs_renewal(path),
                }
            else:
                status[name] = {"exists": False, "path": path, "needs_renewal": True}

        return status

    @otel_trace("mtls.CertificateManager.generate_self_signed_cert")
    def generate_self_signed_cert(
        self,
        cert_path: str,
        key_path: str,
        common_name: str = "alpha-bist.local",
        days_valid: int = 365,
    ) -> bool:
        """Test veya geliştirme ortamı için saf Python ile kendinden imzalı (self-signed) sertifika üretir (Zero-touch).

        Args:
            cert_path: Üretilecek PEM sertifikasının yazılacağı dosya yolu.
            key_path: Üretilecek PEM özel anahtarının yazılacağı dosya yolu.
            common_name: Sertifika ortak adı (CN).
            days_valid: Sertifikanın geçerli kalacağı gün sayısı.

        Returns:
            Başarıyla üretilip diske yazıldıysa True, hata oluşursa False.
        """
        try:
            from datetime import timedelta

            from cryptography import x509
            from cryptography.hazmat.primitives import hashes, serialization
            from cryptography.hazmat.primitives.asymmetric import rsa
            from cryptography.x509.oid import NameOID

            key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
            subject = issuer = x509.Name([
                x509.NameAttribute(NameOID.COMMON_NAME, common_name),
                x509.NameAttribute(NameOID.ORGANIZATION_NAME, "ALPHA BIST"),
            ])
            now = datetime.now(UTC)
            cert = (
                x509.CertificateBuilder()
                .subject_name(subject)
                .issuer_name(issuer)
                .public_key(key.public_key())
                .serial_number(x509.random_serial_number())
                .not_valid_before(now)
                .not_valid_after(now + timedelta(days=days_valid))
                .add_extension(
                    x509.BasicConstraints(ca=True, path_length=None),
                    critical=True,
                )
                .sign(key, hashes.SHA256())
            )

            Path(key_path).parent.mkdir(parents=True, exist_ok=True)
            Path(key_path).write_bytes(
                key.private_bytes(
                    encoding=serialization.Encoding.PEM,
                    format=serialization.PrivateFormat.TraditionalOpenSSL,
                    encryption_algorithm=serialization.NoEncryption(),
                )
            )
            Path(cert_path).parent.mkdir(parents=True, exist_ok=True)
            Path(cert_path).write_bytes(cert.public_bytes(serialization.Encoding.PEM))
            logger.info("kendinden_imzali_sertifika_uretildi", cert=cert_path, cn=common_name)
            return True
        except Exception as exc:
            logger.warning("kendinden_imzali_sertifika_uretilemedi", hata=str(exc))
            return False

    def __repr__(self) -> str:
        """Yöneticinin metinsel özeti."""
        return f"<CertificateManager config_enabled={self.config.enabled}>"


# =====================================================
# SSL Context Factory
# =====================================================


class MTLSContext:
    """mTLS SSL context oluşturucu ve yönetici sınıfı."""

    def __init__(self, config: MTLSConfig | None = None) -> None:
        """mTLS bağlamını verilen veya varsayılan konfigürasyonla kurar.

        Args:
            config: Opsiyonel mTLS konfigürasyonu.
        """
        self.config = config or MTLSConfig()
        self.cert_manager = CertificateManager(self.config)

        if self.config.enabled:
            self.config.validate()

    @otel_trace("mtls.MTLSContext.create_server_context")
    def create_server_context(self) -> ssl.SSLContext | None:
        """Sunucu tarafı mTLS SSLContext nesnesi üretir.

        Returns:
            Yapılandırılmış ssl.SSLContext veya devre dışı/hatalıysa None.
        """
        if not self.config.enabled:
            logger.debug("mtls_devre_disi_sunucu_baglami_atil")
            return None

        try:
            ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            ctx.minimum_version = ssl.TLSVersion(self.config.min_tls_version)

            # Sunucu sertifikası ve anahtarı yükle
            ctx.load_cert_chain(
                certfile=self.config.server_cert,
                keyfile=self.config.server_key,
            )

            # İstemci doğrulama için CA sertifikası yükle
            ctx.load_verify_locations(cafile=self.config.ca_cert)
            ctx.verify_mode = self.config.verify_mode

            # Güvenli şifreleme algoritmaları
            ctx.set_ciphers(DEFAULT_CIPHER_SUITE)

            # DH parametreleri mevcutsa yükle
            if self.config.dhparam and Path(self.config.dhparam).exists():
                ctx.load_dh_params(self.config.dhparam)

            logger.info(
                "mtls_sunucu_baglami_olusturuldu",
                verify_mode="REQUIRED" if self.config.verify_mode == ssl.CERT_REQUIRED else "OPTIONAL",
            )
            return ctx

        except Exception as e:
            logger.error("mtls_sunucu_baglami_olusturma_hatasi", hata=str(e))
            return None

    @otel_trace("mtls.MTLSContext.create_client_context")
    def create_client_context(self) -> ssl.SSLContext | None:
        """İstemci tarafı mTLS SSLContext nesnesi üretir.

        Returns:
            Yapılandırılmış ssl.SSLContext veya devre dışı/hatalıysa None.
        """
        if not self.config.enabled:
            logger.debug("mtls_devre_disi_istemci_baglami_atil")
            return None

        try:
            ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
            ctx.minimum_version = ssl.TLSVersion(self.config.min_tls_version)

            # İstemci sertifikası ve anahtarını yükle (karşı sunucuya kimlik ispatı)
            ctx.load_cert_chain(
                certfile=self.config.client_cert,
                keyfile=self.config.client_key,
            )

            # Karşı sunucuyu doğrulamak için CA yükle
            ctx.load_verify_locations(cafile=self.config.ca_cert)
            ctx.verify_mode = ssl.CERT_REQUIRED

            # Docker internal hostname toleransı
            ctx.check_hostname = self.config.check_hostname

            # Güvenli şifreleme algoritmaları
            ctx.set_ciphers(DEFAULT_CIPHER_SUITE)

            logger.info("mtls_istemci_baglami_olusturuldu")
            return ctx

        except Exception as e:
            logger.error("mtls_istemci_baglami_olusturma_hatasi", hata=str(e))
            return None

    @otel_trace("mtls.MTLSContext.get_uvicorn_ssl_args")
    def get_uvicorn_ssl_args(self) -> dict[str, str]:
        """Uvicorn başlatıcı argümanlarını sözlük olarak döndürür.

        Returns:
            ssl_keyfile ve ssl_certfile anahtarlarını içeren sözlük.
        """
        if not self.config.enabled:
            return {}

        return {
            "ssl_keyfile": self.config.server_key,
            "ssl_certfile": self.config.server_cert,
        }

    @otel_trace("mtls.MTLSContext.get_grpc_channel_credentials")
    def get_grpc_channel_credentials(self) -> Any:
        """gRPC istemcisi için mTLS channel credentials üretir.

        Returns:
            grpc.ChannelCredentials nesnesi veya hata durumunda None.
        """
        if not self.config.enabled:
            return None

        try:
            import grpc

            ca_cert = Path(self.config.ca_cert).read_bytes()
            client_cert = Path(self.config.client_cert).read_bytes()
            client_key = Path(self.config.client_key).read_bytes()

            credentials = grpc.ssl_channel_credentials(
                root_certificates=ca_cert,
                private_key=client_key,
                certificate_chain=client_cert,
            )

            logger.info("grpc_istemci_mtls_kimlik_olusturuldu")
            return credentials

        except ImportError:
            logger.warning("grpcio_yuklu_degil_mtls_atlanıyor")
            return None
        except Exception as e:
            logger.error("grpc_istemci_mtls_kimlik_hatasi", hata=str(e))
            return None

    @otel_trace("mtls.MTLSContext.get_grpc_server_credentials")
    def get_grpc_server_credentials(self) -> Any:
        """gRPC sunucusu için mTLS server credentials üretir.

        Returns:
            grpc.ServerCredentials nesnesi veya hata durumunda None.
        """
        if not self.config.enabled:
            return None

        try:
            import grpc

            server_key = Path(self.config.server_key).read_bytes()
            server_cert = Path(self.config.server_cert).read_bytes()
            ca_cert = Path(self.config.ca_cert).read_bytes()

            credentials = grpc.ssl_server_credentials(
                [(server_key, server_cert)],
                root_certificates=ca_cert,
                require_client_auth=True,
            )

            logger.info("grpc_sunucu_mtls_kimlik_olusturuldu")
            return credentials

        except ImportError:
            logger.warning("grpcio_yuklu_degil_sunucu_atlanıyor")
            return None
        except Exception as e:
            logger.error("grpc_sunucu_mtls_kimlik_hatasi", hata=str(e))
            return None

    @otel_trace("mtls.MTLSContext.get_status")
    def get_status(self) -> dict[str, Any]:
        """mTLS altyapısının genel operasyonel durumunu döndürür.

        Returns:
            Aktiflik, mod ve sertifika durumları özeti.
        """
        return {
            "enabled": self.config.enabled,
            "verify_mode": "REQUIRED" if self.config.verify_mode == ssl.CERT_REQUIRED else "OPTIONAL",
            "min_tls_version": "TLSv1.2",
            "check_hostname": self.config.check_hostname,
            "certificates": self.cert_manager.get_all_status(),
        }

    def __repr__(self) -> str:
        """mTLS bağlamının metinsel temsili."""
        return f"<MTLSContext enabled={self.config.enabled} check_hostname={self.config.check_hostname}>"


# =====================================================
# Singleton & Yardımcı Fonksiyonlar
# =====================================================

_mtls_context: MTLSContext | None = None


@otel_trace("mtls.get_mtls_context")
def get_mtls_context() -> MTLSContext:
    """Global MTLSContext singleton örneğini thread-safe olarak döndürür."""
    global _mtls_context
    if _mtls_context is None:
        with _mtls_lock:
            if _mtls_context is None:
                _mtls_context = MTLSContext()
    return _mtls_context


@otel_trace("mtls.get_server_ssl")
def get_server_ssl() -> ssl.SSLContext | None:
    """Sunucu SSL bağlamı kısayol fonksiyonu."""
    return get_mtls_context().create_server_context()


@otel_trace("mtls.get_client_ssl")
def get_client_ssl() -> ssl.SSLContext | None:
    """İstemci SSL bağlamı kısayol fonksiyonu."""
    return get_mtls_context().create_client_context()


@otel_trace("mtls.get_server_ssl_args")
def get_server_ssl_args() -> dict[str, str]:
    """Uvicorn SSL argümanları kısayol fonksiyonu."""
    return get_mtls_context().get_uvicorn_ssl_args()


@otel_trace("mtls.get_grpc_client_credentials")
def get_grpc_client_credentials() -> Any:
    """gRPC istemci mTLS kimlik bilgisi kısayol fonksiyonu."""
    return get_mtls_context().get_grpc_channel_credentials()


@otel_trace("mtls.get_grpc_server_credentials")
def get_grpc_server_credentials() -> Any:
    """gRPC sunucu mTLS kimlik bilgisi kısayol fonksiyonu."""
    return get_mtls_context().get_grpc_server_credentials()


@otel_trace("mtls.get_mtls_status")
def get_mtls_status() -> dict[str, Any]:
    """mTLS durum bilgisi sözlüğü kısayol fonksiyonu."""
    return get_mtls_context().get_status()


@otel_trace("mtls.generate_self_signed_cert")
def generate_self_signed_cert(
    cert_path: str,
    key_path: str,
    common_name: str = "alpha-bist.local",
    days_valid: int = 365,
) -> bool:
    """Kendinden imzalı test/geliştirme sertifikası üretimi kısayol fonksiyonu."""
    return get_mtls_context().cert_manager.generate_self_signed_cert(
        cert_path=cert_path,
        key_path=key_path,
        common_name=common_name,
        days_valid=days_valid,
    )


# =====================================================
# Polars Analitik Dışa Aktarımı
# =====================================================


def export_mtls_status_to_polars() -> pl.DataFrame:
    """Tüm mTLS sertifikalarının durumunu Polars DataFrame olarak dışa aktarır.

    Returns:
        Sertifika adı, varlık, yol, son kullanma ve yenileme durumu tablosu.
    """
    ctx = get_mtls_context()
    status = ctx.cert_manager.get_all_status()

    records = []
    for cert_name, info in status.items():
        records.append(
            {
                "cert_name": str(cert_name),
                "exists": bool(info.get("exists", False)),
                "path": str(info.get("path", "")),
                "expiry": str(info.get("expiry") or ""),
                "days_left": int(info["days_left"]) if info.get("days_left") is not None else None,
                "needs_renewal": bool(info.get("needs_renewal", True)),
                "checked_at": datetime.now(UTC).isoformat(),
            }
        )

    schema = {
        "cert_name": pl.String,
        "exists": pl.Boolean,
        "path": pl.String,
        "expiry": pl.String,
        "days_left": pl.Int64,
        "needs_renewal": pl.Boolean,
        "checked_at": pl.String,
    }

    if not records:
        return pl.DataFrame(schema=schema)

    return pl.DataFrame(records, schema=schema)


# =====================================================
# FastAPI / Starlette Middleware
# =====================================================


class MTLSMiddleware:
    """FastAPI / Starlette mTLS ara yazılımı.

    Gelen istemcinin SSL sertifikasını doğrular, ortak adını (CN)
    çözümler ve doğrulanmamış talepleri orjson tabanlı 401 cevabıyla engeller.
    """

    def __init__(self, app: Any, required: bool = True) -> None:
        """mTLS ara yazılımını yapılandırır.

        Args:
            app: ASGI uygulaması.
            required: İstemci sertifikasının zorunlu olup olmadığı.
        """
        self.app = app
        self.required = required
        self.mtls = get_mtls_context()

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> Any:
        """ASGI çağrısını yakalar ve istemci TLS sertifikasını doğrular."""
        if scope.get("type") == "http":
            ssl_object = scope.get("ssl")

            if ssl_object and hasattr(ssl_object, "getpeercert"):
                peer_cert = ssl_object.getpeercert()
                if peer_cert:
                    scope["mtls_peer_cert"] = peer_cert
                    scope["mtls_authenticated"] = True

                    # Common Name (CN) çözümle
                    for rdn in peer_cert.get("subject", ()):
                        for attr_type, attr_value in rdn:
                            if attr_type == "commonName":
                                scope["mtls_client_cn"] = attr_value
                elif self.required:
                    from starlette.responses import Response

                    response = Response(
                        content=orjson.dumps({"error": "Istemci mTLS sertifikasi zorunludur"}),
                        status_code=401,
                        media_type="application/json",
                    )
                    await response(scope, receive, send)
                    return
            elif self.required:
                from starlette.responses import Response

                response = Response(
                    content=orjson.dumps({"error": "mTLS zorunludur ancak SSL baglami bulunamadi"}),
                    status_code=401,
                    media_type="application/json",
                )
                await response(scope, receive, send)
                return

        await self.app(scope, receive, send)

    def __repr__(self) -> str:
        """Ara yazılımın metinsel temsili."""
        return f"<MTLSMiddleware required={self.required}>"


# =====================================================
# Sağlık Kontrolü Uç Noktası
# =====================================================


@otel_trace("mtls.create_mtls_health_endpoint")
def create_mtls_health_endpoint() -> Any:
    """mTLS sağlık kontrolü APIRouter nesnesi üretir.

    Returns:
        FastAPI APIRouter örneği.
    """
    from fastapi import APIRouter

    router = APIRouter(prefix="/mtls", tags=["mTLS"])

    @router.get("/status")
    async def mtls_status() -> Any:
        """mTLS durum bilgisi."""
        return get_mtls_status()

    @router.get("/certificates")
    async def mtls_certificates() -> Any:
        """Sertifika detayları."""
        ctx = get_mtls_context()
        return ctx.cert_manager.get_all_status()

    @router.get("/health")
    async def mtls_health() -> Any:
        """mTLS sağlık kontrolü."""
        ctx = get_mtls_context()
        status = ctx.get_status()

        healthy = status["enabled"]
        if status["enabled"]:
            for _cert_name, cert_info in status["certificates"].items():
                if not cert_info.get("exists") or cert_info.get("needs_renewal"):
                    healthy = False
                    break

        return {
            "healthy": healthy,
            "mtls_enabled": status["enabled"],
            "certificates_ok": all(
                c.get("exists", False) and not c.get("needs_renewal", True) for c in status["certificates"].values()
            )
            if status["enabled"]
            else None,
        }

    return router


# =====================================================
# Modül Dışa Aktarımı
# =====================================================

__all__: Final[list[str]] = [
    "DEFAULT_CIPHER_SUITE",
    "DEFAULT_MIN_TLS_VERSION",
    "DEFAULT_RENEW_BEFORE_DAYS",
    "CertificateManager",
    "MTLSConfig",
    "MTLSContext",
    "MTLSMiddleware",
    "create_mtls_health_endpoint",
    "export_mtls_status_to_polars",
    "generate_self_signed_cert",
    "get_client_ssl",
    "get_grpc_client_credentials",
    "get_grpc_server_credentials",
    "get_mtls_context",
    "get_mtls_status",
    "get_server_ssl",
    "get_server_ssl_args",
    "otel_trace",
]
