"""ALPHA BIST — Service Discovery & Health Monitor

Docker Compose ortamında servis keşfi ve sağlık takibi.
Traefik API Gateway ile birlikte çalışır.

Özellikler:
- Service Registry: Servis keşfi ve kayıt
- Health Check: Periyodik sağlık kontrolü
- Monitoring: Servis durumu metrikleri
- SSL Context: Opsiyonel self-signed CA (geliştirme ortamı)

Not: Bu bir service mesh (Istio/Linkerd) değildir.
Gerçek mTLS, traffic splitting, fault injection için
Kubernetes + service mesh gerekir.

Kullanım:
    from services.core.service_mesh import service_mesh

    # Servis kaydı
    service_mesh.register("api", "alpha-api", 8000)

    # Sağlık kontrolü
    health = service_mesh.get_health("api")

    # Tüm servislerin durumu
    all_health = service_mesh.get_all_health()
"""

import asyncio
import functools
import os
import ssl
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

import structlog
from opentelemetry import trace

logger = structlog.get_logger(__name__)
tracer = trace.get_tracer("alpha-bist.service_mesh")


def otel_trace(span_name: str) -> Any:
    """Decorator to wrap a method in an OTel span."""

    def decorator(func) -> Any:
        """Otomatik eklendi."""
        @functools.wraps(func)
        def wrapper(self, *args, **kwargs) -> Any:
            """Otomatik eklendi."""
            with tracer.start_as_current_span(span_name):
                return func(self, *args, **kwargs)

        return wrapper

    return decorator


class ServiceStatus(Enum):
    """Otomatik eklendi."""
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
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def address(self) -> str:
        """Otomatik eklendi."""
        return f"{self.host}:{self.port}"

    @property
    def is_alive(self) -> bool:
        """Otomatik eklendi."""
        if self.status == ServiceStatus.UNKNOWN:
            return True  # Henüz kontrol edilmedi
        return self.status in (ServiceStatus.HEALTHY, ServiceStatus.DEGRADED)


class ServiceDiscovery:
    """Service Discovery & Health Monitor — Docker Compose ile çalışır."""

    def __init__(self):
        """Otomatik eklendi."""
        self._services: dict[str, ServiceInfo] = {}
        self._health_check_interval = 60  # SSD write reduction: 15s → 60s
        self._failure_threshold = 3
        self._running = False
        self._ca_cert: str | None = None
        self._ca_key: str | None = None
        self._health_history: dict[str, list[bool]] = {}  # Son N sağlık durumu

    # =====================================================
    # Service Registry
    # =====================================================

    @otel_trace("service_mesh.register")
    def register(self, name: str, host: str, port: int, metadata: dict = None) -> Any:
        """Servisi kaydet."""
        self._services[name] = ServiceInfo(
            name=name,
            host=host,
            port=port,
            metadata=metadata or {},
        )
        self._health_history[name] = []
        logger.info("Service registered", name=name, address=f"{host}:{port}")

    @otel_trace("service_mesh.unregister")
    def unregister(self, name: str) -> Any:
        """Servis kaydını sil."""
        self._services.pop(name, None)
        self._health_history.pop(name, None)
        logger.info("Service unregistered", name=name)

    def get_service(self, name: str) -> ServiceInfo | None:
        """Servis bilgisini al."""
        return self._services.get(name)

    def get_healthy_services(self) -> list[ServiceInfo]:
        """Sağlıklı servisleri listele."""
        return [s for s in self._services.values() if s.is_alive]

    def get_all_services(self) -> dict[str, ServiceInfo]:
        """Tüm servisleri al."""
        return dict(self._services)

    def get_all_health(self) -> dict[str, dict[str, Any]]:
        """Tüm servislerin sağlık raporu."""
        return {name: self.get_health(name) for name in self._services}

    # =====================================================
    # Health Check
    # =====================================================

    @otel_trace("service_mesh.check_health")
    async def check_health(self, name: str) -> ServiceStatus:
        """Tek servisin sağlık durumunu kontrol et."""
        service = self._services.get(name)
        if not service:
            return ServiceStatus.UNKNOWN

        service_type = service.metadata.get("type", "http" if service.port > 0 else "worker")

        if service_type == "http" and service.port > 0:
            try:
                import httpx

                async with httpx.AsyncClient(timeout=3.0) as client:
                    resp = await client.get(f"http://{service.address}/health")
                    if resp.status_code == 200:
                        service.status = ServiceStatus.HEALTHY
                        service.failure_count = 0
                        service.last_heartbeat = time.time()
                        self._record_health(name, True)
                    else:
                        service.status = ServiceStatus.DEGRADED
                        service.failure_count += 1
                        self._record_health(name, False)
            except Exception:
                service.failure_count += 1
                if service.failure_count >= self._failure_threshold:
                    service.status = ServiceStatus.UNHEALTHY
                else:
                    service.status = ServiceStatus.DEGRADED
                self._record_health(name, False)
        else:
            # Worker / Event-loop service
            try:
                from .database import get_redis
                redis = await get_redis()
                if redis and await redis.ping():
                    service.status = ServiceStatus.HEALTHY
                    service.failure_count = 0
                    service.last_heartbeat = time.time()
                    self._record_health(name, True)
                else:
                    service.status = ServiceStatus.DEGRADED
                    self._record_health(name, False)
            except Exception:
                service.status = ServiceStatus.HEALTHY
                self._record_health(name, True)

        return service.status

    def _record_health(self, name: str, healthy: bool) -> Any:
        """Sağlık durumunu geçmişe kaydet (son 100 kontrol)."""
        if name not in self._health_history:
            self._health_history[name] = []
        history = self._health_history[name]
        history.append(healthy)
        if len(history) > 100:
            history.pop(0)

    def get_uptime_percentage(self, name: str) -> float:
        """Servisin son kontrollerdeki uptime yüzdesi."""
        history = self._health_history.get(name, [])
        if not history:
            return 0.0
        return sum(history) / len(history) * 100

    @otel_trace("service_mesh.check_all_health")
    async def check_all_health(self) -> dict[str, ServiceStatus]:
        """Tüm servislerin sağlık durumunu kontrol et."""
        results = {}
        for name in self._services:
            results[name] = await self.check_health(name)
        return results

    def get_health(self, name: str) -> dict[str, Any]:
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
            "uptime_pct": round(self.get_uptime_percentage(name), 1),
        }

    # =====================================================
    # Background Health Monitor
    # =====================================================

    @otel_trace("service_mesh.start_monitoring")
    async def start_monitoring(self) -> Any:
        """Arka planda servis sağlık takibi başlat."""
        self._running = True
        logger.info(
            "Service discovery monitoring started", services=len(self._services), interval=self._health_check_interval
        )

        while self._running:
            try:
                results = await self.check_all_health()
                unhealthy = [k for k, v in results.items() if v == ServiceStatus.UNHEALTHY]
                if unhealthy:
                    logger.warning("Unhealthy services detected", services=unhealthy)
            except Exception as e:
                logger.debug("Health check cycle error", error=str(e))

            await asyncio.sleep(self._health_check_interval)

    def stop_monitoring(self) -> Any:
        """Sağlık takibini durdur."""
        self._running = False

    # =====================================================
    # SSL Context (Opsiyonel — geliştirme ortamı)
    # =====================================================

    def generate_ca(self, cert_dir: str = "/tmp/alpha-certs") -> Any:
        """Self-signed CA oluştur (geliştirme ortamı için).

        Not: Production'da gerçek CA sertifikaları kullanılmalıdır.
        Bu sadece Docker internal iletişim için basit SSL context sağlar.
        """
        os.makedirs(cert_dir, exist_ok=True)

        ca_cert_path = os.path.join(cert_dir, "ca.pem")
        ca_key_path = os.path.join(cert_dir, "ca-key.pem")

        if os.path.exists(ca_cert_path) and os.path.exists(ca_key_path):
            self._ca_cert = ca_cert_path
            self._ca_key = ca_key_path
            logger.info("CA certificate loaded", path=ca_cert_path)
            return

        try:
            import datetime
            from datetime import UTC

            from cryptography import x509
            from cryptography.hazmat.primitives import hashes, serialization
            from cryptography.hazmat.primitives.asymmetric import rsa
            from cryptography.x509.oid import NameOID

            key = rsa.generate_private_key(public_exponent=65537, key_size=2048)

            subject = issuer = x509.Name(
                [
                    x509.NameAttribute(NameOID.ORGANIZATION_NAME, "ALPHA BIST"),
                    x509.NameAttribute(NameOID.COMMON_NAME, "ALPHA BIST CA"),
                ]
            )

            cert = (
                x509.CertificateBuilder()
                .subject_name(subject)
                .issuer_name(issuer)
                .public_key(key.public_key())
                .serial_number(x509.random_serial_number())
                .not_valid_before(datetime.datetime.now(UTC))
                .not_valid_after(datetime.datetime.now(UTC) + datetime.timedelta(days=3650))
                .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
                .sign(key, hashes.SHA256())
            )

            with open(ca_key_path, "wb") as f:
                f.write(
                    key.private_bytes(
                        encoding=serialization.Encoding.PEM,
                        format=serialization.PrivateFormat.TraditionalOpenSSL,
                        encryption_algorithm=serialization.NoEncryption(),
                    )
                )

            with open(ca_cert_path, "wb") as f:
                f.write(cert.public_bytes(serialization.Encoding.PEM))

            self._ca_cert = ca_cert_path
            self._ca_key = ca_key_path
            logger.info("CA certificate generated", path=ca_cert_path)

        except ImportError:
            logger.warning("cryptography not installed, SSL disabled")

    def get_ssl_context(self, service_name: str) -> ssl.SSLContext | None:
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
    # Traffic Management Config
    # =====================================================

    def get_circuit_breaker_config(self, service_name: str) -> dict[str, Any]:
        """Servis için circuit breaker config döndür."""
        return {
            "failure_threshold": 5,
            "recovery_timeout": 30,
            "half_open_max_calls": 3,
        }

    def get_retry_config(self, service_name: str) -> dict[str, Any]:
        """Servis için retry config döndür."""
        return {
            "max_retries": 3,
            "backoff_base": 1.0,
            "backoff_max": 30.0,
        }


# Singleton — backward compatibility için service_mesh adı korundu
service_mesh = ServiceDiscovery()


def init_service_mesh() -> Any:
    """Service discovery'yi başlat — tüm servisleri kaydet."""
    services = {
        "api": ("alpha-api", 8000, {"type": "http"}),
        "ingestion": ("alpha-ingestion", 0, {"type": "worker"}),
        "feature-engine": ("alpha-feature-engine", 0, {"type": "worker"}),
        "market-state": ("alpha-market-state", 0, {"type": "worker"}),
        "intelligence": ("alpha-intelligence", 0, {"type": "worker"}),
        "simulation": ("alpha-simulation", 0, {"type": "worker"}),
        "risk": ("alpha-risk", 0, {"type": "worker"}),
        "portfolio": ("alpha-portfolio", 0, {"type": "worker"}),
        "learning": ("alpha-learning", 0, {"type": "worker"}),
    }

    for name, (host, port, metadata) in services.items():
        service_mesh.register(name, host, port, metadata)

    # Opsiyonel: Self-signed CA (geliştirme ortamı)
    if os.environ.get("ENABLE_MTLS", "false").lower() == "true":
        service_mesh.generate_ca()

    logger.info("Service discovery initialized", services=len(services))
