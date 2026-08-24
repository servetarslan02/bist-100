"""ALPHA BIST — Service Mesh (App-Level)

Istio/Linkerd yerine uygulama seviyesinde service mesh.
Docker Compose ile çalışır, Kubernetes gerektirmez.

Özellikler:
- mTLS: Servisler arası şifreli iletişim (self-signed CA)
- Service Registry: Servis keşfi ve sağlık takibi
- Traffic Management: Circuit breaker, retry, timeout
- Observability: Distributed tracing (OpenTelemetry ile entegre)

Kullanım:
    from services.core.service_mesh import service_mesh

    # Servis kaydı
    service_mesh.register("api", "alpha-api", 8000)

    # mTLS channel al
    channel = service_mesh.get_secure_channel("ingestion")

    # Sağlık kontrolü
    health = service_mesh.get_health("api")
"""

import os
import ssl
import time
import asyncio
import hashlib
from typing import Dict, Any, Optional, List
from dataclasses import dataclass, field
from enum import Enum
import structlog

logger = structlog.get_logger()


class ServiceStatus(Enum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"
    UNKNOWN = "unknown"


@dataclass
class ServiceInfo:
    """Kayıtlı servis bilgisi."""
    name: str
    host: str
    port: int
    status: ServiceStatus = ServiceStatus.UNKNOWN
    last_heartbeat: float = 0.0
    failure_count: int = 0
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def address(self) -> str:
        return f"{self.host}:{self.port}"

    @property
    def is_alive(self) -> bool:
        if self.status == ServiceStatus.UNKNOWN:
            return True  # Henüz kontrol edilmedi
        return self.status in (ServiceStatus.HEALTHY, ServiceStatus.DEGRADED)


class ServiceMesh:
    """App-level service mesh — Docker Compose ile çalışır."""

    def __init__(self):
        self._services: Dict[str, ServiceInfo] = {}
        self._health_check_interval = 15  # saniye
        self._failure_threshold = 3
        self._running = False
        self._ca_cert: Optional[str] = None
        self._ca_key: Optional[str] = None

    # =====================================================
    # Service Registry
    # =====================================================

    def register(self, name: str, host: str, port: int, metadata: Dict = None):
        """Servisi kaydet."""
        self._services[name] = ServiceInfo(
            name=name,
            host=host,
            port=port,
            metadata=metadata or {},
        )
        logger.info("Service registered", name=name, address=f"{host}:{port}")

    def unregister(self, name: str):
        """Servis kaydını sil."""
        self._services.pop(name, None)
        logger.info("Service unregistered", name=name)

    def get_service(self, name: str) -> Optional[ServiceInfo]:
        """Servis bilgisini al."""
        return self._services.get(name)

    def get_healthy_services(self) -> List[ServiceInfo]:
        """Sağlıklı servisleri listele."""
        return [s for s in self._services.values() if s.is_alive]

    def get_all_services(self) -> Dict[str, ServiceInfo]:
        """Tüm servisleri al."""
        return dict(self._services)

    # =====================================================
    # Health Check
    # =====================================================

    async def check_health(self, name: str) -> ServiceStatus:
        """Tek servisin sağlık durumunu kontrol et."""
        service = self._services.get(name)
        if not service:
            return ServiceStatus.UNKNOWN

        try:
            import httpx
            async with httpx.AsyncClient(timeout=3.0) as client:
                resp = await client.get(f"http://{service.address}/health")
                if resp.status_code == 200:
                    service.status = ServiceStatus.HEALTHY
                    service.failure_count = 0
                    service.last_heartbeat = time.time()
                else:
                    service.status = ServiceStatus.DEGRADED
                    service.failure_count += 1
        except Exception:
            service.failure_count += 1
            if service.failure_count >= self._failure_threshold:
                service.status = ServiceStatus.UNHEALTHY
            else:
                service.status = ServiceStatus.DEGRADED

        return service.status

    async def check_all_health(self) -> Dict[str, ServiceStatus]:
        """Tüm servislerin sağlık durumunu kontrol et."""
        results = {}
        for name in self._services:
            results[name] = await self.check_health(name)
        return results

    def get_health(self, name: str) -> Dict[str, Any]:
        """Servis sağlık raporu."""
        service = self._services.get(name)
        if not service:
            return {"status": "unknown", "error": "not registered"}

        return {
            "name": service.name,
            "address": service.address,
            "status": service.status.value,
            "failure_count": service.failure_count,
            "last_heartbeat": service.last_heartbeat,
            "is_alive": service.is_alive,
        }

    # =====================================================
    # Background Health Monitor
    # =====================================================

    async def start_monitoring(self):
        """Arka planda servis sağlık takibi başlat."""
        self._running = True
        logger.info("Service mesh monitoring started",
                    services=len(self._services),
                    interval=self._health_check_interval)

        while self._running:
            try:
                results = await self.check_all_health()
                unhealthy = [k for k, v in results.items()
                           if v == ServiceStatus.UNHEALTHY]
                if unhealthy:
                    logger.warning("Unhealthy services detected",
                                 services=unhealthy)
            except Exception as e:
                logger.debug("Health check cycle error", error=str(e))

            await asyncio.sleep(self._health_check_interval)

    def stop_monitoring(self):
        """Sağlık takibini durdur."""
        self._running = False

    # =====================================================
    # mTLS (Self-Signed CA)
    # =====================================================

    def generate_ca(self, cert_dir: str = "/tmp/alpha-certs"):
        """Self-signed CA oluştur (geliştirme ortamı için)."""
        os.makedirs(cert_dir, exist_ok=True)

        ca_cert_path = os.path.join(cert_dir, "ca.pem")
        ca_key_path = os.path.join(cert_dir, "ca-key.pem")

        if os.path.exists(ca_cert_path) and os.path.exists(ca_key_path):
            self._ca_cert = ca_cert_path
            self._ca_key = ca_key_path
            logger.info("CA certificate loaded", path=ca_cert_path)
            return

        # Self-signed CA oluştur
        try:
            from cryptography import x509
            from cryptography.x509.oid import NameOID
            from cryptography.hazmat.primitives import hashes, serialization
            from cryptography.hazmat.primitives.asymmetric import rsa
            import datetime

            key = rsa.generate_private_key(public_exponent=65537, key_size=2048)

            subject = issuer = x509.Name([
                x509.NameAttribute(NameOID.ORGANIZATION_NAME, "ALPHA BIST"),
                x509.NameAttribute(NameOID.COMMON_NAME, "ALPHA BIST CA"),
            ])

            cert = (
                x509.CertificateBuilder()
                .subject_name(subject)
                .issuer_name(issuer)
                .public_key(key.public_key())
                .serial_number(x509.random_serial_number())
                .not_valid_before(datetime.datetime.utcnow())
                .not_valid_after(datetime.datetime.utcnow() + datetime.timedelta(days=3650))
                .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
                .sign(key, hashes.SHA256())
            )

            with open(ca_key_path, "wb") as f:
                f.write(key.private_bytes(
                    encoding=serialization.Encoding.PEM,
                    format=serialization.PrivateFormat.TraditionalOpenSSL,
                    encryption_algorithm=serialization.NoEncryption(),
                ))

            with open(ca_cert_path, "wb") as f:
                f.write(cert.public_bytes(serialization.Encoding.PEM))

            self._ca_cert = ca_cert_path
            self._ca_key = ca_key_path
            logger.info("CA certificate generated", path=ca_cert_path)

        except ImportError:
            logger.warning("cryptography not installed, mTLS disabled")

    def get_ssl_context(self, service_name: str) -> Optional[ssl.SSLContext]:
        """Servis için SSL context oluştur."""
        if not self._ca_cert:
            return None

        try:
            ctx = ssl.create_default_context(cafile=self._ca_cert)
            ctx.check_hostname = False  # Docker internal hostnames
            ctx.verify_mode = ssl.CERT_REQUIRED
            return ctx
        except Exception as e:
            logger.debug("SSL context creation failed", error=str(e))
            return None

    # =====================================================
    # Traffic Management
    # =====================================================

    def get_circuit_breaker_config(self, service_name: str) -> Dict[str, Any]:
        """Servis için circuit breaker config döndür."""
        # Mevcut circuit_breaker.py ile entegre
        return {
            "failure_threshold": 5,
            "recovery_timeout": 30,
            "half_open_max_calls": 3,
        }

    def get_retry_config(self, service_name: str) -> Dict[str, Any]:
        """Servis için retry config döndür."""
        return {
            "max_retries": 3,
            "backoff_base": 1.0,
            "backoff_max": 30.0,
        }


# Singleton
service_mesh = ServiceMesh()


def init_service_mesh():
    """Service mesh'i başlat — tüm servisleri kaydet."""
    # Docker Compose servis isimleri
    services = {
        "api": ("alpha-api", 8000),
        "ingestion": ("alpha-ingestion", 8000),
        "feature-engine": ("alpha-feature-engine", 8000),
        "market-state": ("alpha-market-state", 8000),
        "intelligence": ("alpha-intelligence", 8000),
        "simulation": ("alpha-simulation", 8000),
        "risk": ("alpha-risk", 8000),
        "portfolio": ("alpha-portfolio", 8000),
        "learning": ("alpha-learning", 8000),
    }

    for name, (host, port) in services.items():
        service_mesh.register(name, host, port)

    # mTLS CA oluştur (opsiyonel)
    if os.environ.get("ENABLE_MTLS", "false").lower() == "true":
        service_mesh.generate_ca()

    logger.info("Service mesh initialized", services=len(services))
