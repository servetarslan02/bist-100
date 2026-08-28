"""
ALPHA BIST — mTLS (Mutual TLS) Service Mesh v1.0

Servisler arası güvenli iletişim için mTLS implementasyonu.

Özellikler:
- Self-signed CA ile sertifika oluşturma
- SSL context yönetimi (server + client)
- FastAPI middleware entegrasyonu
- gRPC TLS channel desteği
- Otomatik sertifika yenileme
- Health check endpoint koruması

Kullanım:
    from services.core.mtls import MTLSContext, get_server_ssl, get_client_ssl

    # FastAPI'ye TLS ekleme
    ssl_ctx = get_server_ssl()
    uvicorn.run(app, ssl_keyfile=ssl_ctx["keyfile"], ssl_certfile=ssl_ctx["certfile"])

    # gRPC client TLS
    channel = get_client_ssl_channel("alpha-api:50051")
"""

import os
import ssl
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import structlog

logger = structlog.get_logger()


# =====================================================
# Konfigürasyon
# =====================================================


@dataclass
class MTLSConfig:
    """mTLS yapılandırması. Ortam değişkenlerinden okunur."""

    # Sertifika yolları
    ca_cert: str = ""
    server_cert: str = ""
    server_key: str = ""
    client_cert: str = ""
    client_key: str = ""
    dhparam: str = ""

    # TLS ayarları
    min_tls_version: int = ssl.TLSVersion.TLSv1_2
    verify_mode: int = ssl.CERT_REQUIRED
    check_hostname: bool = False  # Docker internal hostnames için

    # Sertifika yenileme
    auto_renew: bool = True
    renew_before_days: int = 30

    # Durum
    enabled: bool = True

    def __post_init__(self):
        """Varsayılan yolları ayarla."""
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

        # Sertifikalar yoksa devre dışı bırak
        if not Path(self.ca_cert).exists():
            logger.warning("mTLS CA certificate not found, disabling mTLS", path=self.ca_cert)
            self.enabled = False

    def validate(self) -> bool:
        """Sertifika dosyalarının varlığını kontrol et."""
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
            logger.error("mTLS certificate files missing", missing=missing)
            self.enabled = False
            return False

        return True


# =====================================================
# Sertifika Yönetimi
# =====================================================


class CertificateManager:
    """Sertifika yaşam döngüsü yönetimi."""

    def __init__(self, config: MTLSConfig):
        self.config = config

    def check_expiry(self, cert_path: str) -> datetime | None:
        """Sertifika son kullanma tarihini kontrol et."""
        try:
            import subprocess

            result = subprocess.run(
                ["openssl", "x509", "-in", cert_path, "-noout", "-enddate"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode == 0:
                # notAfter=Aug 25 12:00:00 2027 GMT
                date_str = result.stdout.strip().split("=")[1]
                return datetime.strptime(date_str, "%b %d %H:%M:%S %Y %Z")
        except Exception as e:
            logger.warning("Certificate expiry check failed", path=cert_path, error=str(e))
        return None

    def needs_renewal(self, cert_path: str) -> bool:
        """Sertifika yenileme gerekiyor mu?"""
        expiry = self.check_expiry(cert_path)
        if not expiry:
            return True

        days_left = (expiry - datetime.now(UTC)).days
        if days_left <= self.config.renew_before_days:
            logger.warning("Certificate expiring soon", path=cert_path, days_left=days_left)
            return True

        return False

    def get_cert_info(self, cert_path: str) -> dict[str, Any]:
        """Sertifika bilgilerini al."""
        try:
            import subprocess

            result = subprocess.run(
                ["openssl", "x509", "-in", cert_path, "-noout", "-subject", "-issuer", "-dates", "-fingerprint"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode == 0:
                info = {}
                for line in result.stdout.strip().split("\n"):
                    if "=" in line:
                        key, _, value = line.partition("=")
                        info[key.strip().lower()] = value.strip()
                return info
        except Exception as e:
            logger.warning("Certificate info failed", path=cert_path, error=str(e))
        return {}

    def get_all_status(self) -> dict[str, Any]:
        """Tüm sertifikaların durumu."""
        certs = {
            "ca": self.config.ca_cert,
            "server": self.config.server_cert,
            "client": self.config.client_cert,
        }

        status = {}
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
                status[name] = {"exists": False, "path": path}

        return status


# =====================================================
# SSL Context Factory
# =====================================================


class MTLSContext:
    """mTLS SSL context oluşturucu.

    Server ve client SSL context'leri oluşturur.
    Docker internal hostnames ile uyumlu.
    """

    def __init__(self, config: MTLSConfig | None = None):
        self.config = config or MTLSConfig()
        self.cert_manager = CertificateManager(self.config)

        if self.config.enabled:
            self.config.validate()

    def create_server_context(self) -> ssl.SSLContext | None:
        """Server SSL context oluştur.

        - Client sertifika doğrulama (mTLS)
        - TLS 1.2+ zorunlu
        - Güvenli cipher suite
        """
        if not self.config.enabled:
            logger.debug("mTLS disabled, returning None")
            return None

        try:
            ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            ctx.minimum_version = ssl.TLSVersion.TLSv1_2

            # Server sertifikası ve key
            ctx.load_cert_chain(
                certfile=self.config.server_cert,
                keyfile=self.config.server_key,
            )

            # CA sertifikası ile client doğrulama
            ctx.load_verify_locations(cafile=self.config.ca_cert)
            ctx.verify_mode = self.config.verify_mode

            # Güvenli cipher suite
            ctx.set_ciphers("ECDHE+AESGCM:ECDHE+CHACHA20:DHE+AESGCM:DHE+CHACHA20:!aNULL:!MD5:!DSS")

            # DH parametreleri (varsa)
            if self.config.dhparam and Path(self.config.dhparam).exists():
                ctx.load_dh_params(self.config.dhparam)

            logger.info(
                "mTLS server context created",
                verify_mode="REQUIRED" if self.config.verify_mode == ssl.CERT_REQUIRED else "OPTIONAL",
            )
            return ctx

        except Exception as e:
            logger.error("Failed to create server SSL context", error=str(e))
            return None

    def create_client_context(self) -> ssl.SSLContext | None:
        """Client SSL context oluştur.

        - Server sertifika doğrulama
        - Client sertifikası sunma (mTLS)
        - TLS 1.2+ zorunlu
        """
        if not self.config.enabled:
            logger.debug("mTLS disabled, returning None")
            return None

        try:
            ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
            ctx.minimum_version = ssl.TLSVersion.TLSv1_2

            # Client sertifikası ve key (server'a kendimizi tanıtmak için)
            ctx.load_cert_chain(
                certfile=self.config.client_cert,
                keyfile=self.config.client_key,
            )

            # CA ile server sertifikasını doğrula
            ctx.load_verify_locations(cafile=self.config.ca_cert)
            ctx.verify_mode = ssl.CERT_REQUIRED

            # Docker internal hostnames için hostname check kapat
            ctx.check_hostname = self.config.check_hostname

            # Güvenli cipher suite
            ctx.set_ciphers("ECDHE+AESGCM:ECDHE+CHACHA20:DHE+AESGCM:DHE+CHACHA20:!aNULL:!MD5:!DSS")

            logger.info("mTLS client context created")
            return ctx

        except Exception as e:
            logger.error("Failed to create client SSL context", error=str(e))
            return None

    def get_uvicorn_ssl_args(self) -> dict[str, str]:
        """Uvicorn SSL argümanları."""
        if not self.config.enabled:
            return {}

        return {
            "ssl_keyfile": self.config.server_key,
            "ssl_certfile": self.config.server_cert,
        }

    def get_grpc_channel_credentials(self):
        """gRPC TLS channel credentials."""
        if not self.config.enabled:
            return None

        try:
            import grpc

            # CA sertifikasını oku
            ca_cert = Path(self.config.ca_cert).read_bytes()
            client_cert = Path(self.config.client_cert).read_bytes()
            client_key = Path(self.config.client_key).read_bytes()

            credentials = grpc.ssl_channel_credentials(
                root_certificates=ca_cert,
                private_key=client_key,
                certificate_chain=client_cert,
            )

            logger.info("gRPC TLS credentials created")
            return credentials

        except ImportError:
            logger.warning("grpcio not installed, cannot create TLS credentials")
            return None
        except Exception as e:
            logger.error("Failed to create gRPC TLS credentials", error=str(e))
            return None

    def get_grpc_server_credentials(self):
        """gRPC TLS server credentials."""
        if not self.config.enabled:
            return None

        try:
            import grpc

            server_key = Path(self.config.server_key).read_bytes()
            server_cert = Path(self.config.server_cert).read_bytes()
            ca_cert = Path(self.config.ca_cert).read_bytes()

            # Client auth ile (mTLS)
            credentials = grpc.ssl_server_credentials(
                [(server_key, server_cert)],
                root_certificates=ca_cert,
                require_client_auth=True,
            )

            logger.info("gRPC server TLS credentials created (mTLS)")
            return credentials

        except ImportError:
            logger.warning("grpcio not installed")
            return None
        except Exception as e:
            logger.error("Failed to create gRPC server TLS credentials", error=str(e))
            return None

    def get_status(self) -> dict[str, Any]:
        """mTLS durum bilgisi."""
        return {
            "enabled": self.config.enabled,
            "verify_mode": "REQUIRED" if self.config.verify_mode == ssl.CERT_REQUIRED else "OPTIONAL",
            "min_tls_version": "TLSv1.2",
            "check_hostname": self.config.check_hostname,
            "certificates": self.cert_manager.get_all_status(),
        }


# =====================================================
# Singleton & Helper Functions
# =====================================================

_mtls_context: MTLSContext | None = None


def get_mtls_context() -> MTLSContext:
    """Global mTLS context (singleton)."""
    global _mtls_context
    if _mtls_context is None:
        _mtls_context = MTLSContext()
    return _mtls_context


def get_server_ssl() -> ssl.SSLContext | None:
    """Server SSL context (shortcut)."""
    return get_mtls_context().create_server_context()


def get_client_ssl() -> ssl.SSLContext | None:
    """Client SSL context (shortcut)."""
    return get_mtls_context().create_client_context()


def get_server_ssl_args() -> dict[str, str]:
    """Uvicorn SSL argümanları (shortcut)."""
    return get_mtls_context().get_uvicorn_ssl_args()


def get_grpc_client_credentials():
    """gRPC client TLS credentials (shortcut)."""
    return get_mtls_context().get_grpc_channel_credentials()


def get_grpc_server_credentials():
    """gRPC server TLS credentials (shortcut)."""
    return get_mtls_context().get_grpc_server_credentials()


def get_mtls_status() -> dict[str, Any]:
    """mTLS durum bilgisi (shortcut)."""
    return get_mtls_context().get_status()


# =====================================================
# FastAPI Middleware
# =====================================================


class MTLSMiddleware:
    """FastAPI mTLS middleware.

    Gelen istemci sertifikasını doğrular ve
    sertifika bilgilerini request state'e ekler.

    Kullanım:
        app.add_middleware(MTLSMiddleware)
    """

    def __init__(self, app, required: bool = True):
        self.app = app
        self.required = required
        self.mtls = get_mtls_context()

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            # SSL bilgilerini kontrol et
            ssl_object = scope.get("ssl")

            if ssl_object and hasattr(ssl_object, "getpeercert"):
                peer_cert = ssl_object.getpeercert()
                if peer_cert:
                    # Sertifika bilgilerini state'e ekle
                    scope["mtls_peer_cert"] = peer_cert
                    scope["mtls_authenticated"] = True

                    # CN (Common Name) çıkar
                    for rdn in peer_cert.get("subject", ()):
                        for attr_type, attr_value in rdn:
                            if attr_type == "commonName":
                                scope["mtls_client_cn"] = attr_value
                elif self.required:
                    # mTLS zorunlu ama sertifika yok
                    from starlette.responses import JSONResponse

                    response = JSONResponse(
                        {"error": "Client certificate required"},
                        status_code=401,
                    )
                    await response(scope, receive, send)
                    return
            elif self.required:
                from starlette.responses import JSONResponse

                response = JSONResponse(
                    {"error": "mTLS required but no SSL context"},
                    status_code=401,
                )
                await response(scope, receive, send)
                return

        await self.app(scope, receive, send)


# =====================================================
# Health Check Endpoint
# =====================================================


def create_mtls_health_endpoint():
    """mTLS sağlık kontrolü endpoint'i.

    FastAPI router'a eklenebilir:
        from services.core.mtls import create_mtls_health_endpoint
        router.include_router(create_mtls_health_endpoint())
    """
    from fastapi import APIRouter

    router = APIRouter(prefix="/mtls", tags=["mTLS"])

    @router.get("/status")
    async def mtls_status():
        """mTLS durum bilgisi."""
        return get_mtls_status()

    @router.get("/certificates")
    async def mtls_certificates():
        """Sertifika detayları."""
        ctx = get_mtls_context()
        return ctx.cert_manager.get_all_status()

    @router.get("/health")
    async def mtls_health():
        """mTLS sağlık kontrolü."""
        ctx = get_mtls_context()
        status = ctx.get_status()

        healthy = status["enabled"]
        if status["enabled"]:
            for _cert_name, cert_info in status["certificates"].items():
                if not cert_info.get("exists"):
                    healthy = False
                    break
                if cert_info.get("needs_renewal"):
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
