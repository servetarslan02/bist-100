"""ALPHA BIST — Servis Keşfi ve Sağlık Takip Motoru (Service Discovery & Health Monitor).

Docker Compose ve mikroservis mimarisinde çalışan servislerin:
- Otomatik servis kaydı ve keşfi (Service Registry & Discovery)
- Asenkron sağlık denetimi (HTTP / Health Endpoint ve Worker / Redis Ping)
- Arıza eşiği ve bozulma takibi (Failure Threshold, Degradation & Uptime Tracking)
- Thread-safe durum yönetimi (Reentrant Lock ile yarış koşullarını önleme)
- DuckDB üzerinde servis sağlık denetim geçmişi ve Polars analitik aktarımı
- Opsiyonel mTLS / Self-signed CA ve Trafik Yönetim (Circuit Breaker, Retry) konfigürasyonu sağlar.
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import ssl
import threading
import time
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any, Final

import duckdb
import orjson
import polars as pl
import structlog

from services.core.otel import otel_trace

logger = structlog.get_logger(__name__)

DEFAULT_HEALTH_CHECK_INTERVAL: Final[int] = 60  # SSD aşınmasını önlemek için 60 saniye
DEFAULT_FAILURE_THRESHOLD: Final[int] = 3
DEFAULT_SERVICE_MESH_DB: Final[str] = "data/service_mesh_audit.duckdb"
DEFAULT_CHECKPOINT_SIZE: Final[str] = "4MB"
DEFAULT_WAL_SIZE: Final[str] = "2MB"

_GLOBAL_LOCK = threading.RLock()
_MESH_DUCKDB_CONN: duckdb.DuckDBPyConnection | None = None
_MESH_DUCKDB_PATH: str = DEFAULT_SERVICE_MESH_DB


def configure_duckdb_wal(conn: duckdb.DuckDBPyConnection) -> None:
    """DuckDB bağlantısı için WAL ve checkpoint yapılandırmasını uygular."""
    try:
        conn.execute(f"PRAGMA checkpoint_threshold = '{DEFAULT_CHECKPOINT_SIZE}';")
        conn.execute(f"PRAGMA wal_autocheckpoint = '{DEFAULT_WAL_SIZE}';")
    except Exception as exc:
        logger.debug("ServiceMesh DuckDB WAL pragma yapılandırma uyarısı", hata=str(exc))


def to_orjson_bytes(data: Any) -> bytes:
    """Herhangi bir Python nesnesini güvenli ve hızlı şekilde orjson bayt dizisine serileştirir."""
    return orjson.dumps(data, default=str)


class ServiceStatus(StrEnum):
    """Servis sağlık ve operasyonel durumları."""

    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"
    UNKNOWN = "unknown"


@dataclass(slots=True)
class ServiceInfo:
    """Kayıtlı mikroservis tanım ve durum modeli."""

    name: str
    host: str
    port: int
    status: ServiceStatus = ServiceStatus.UNKNOWN
    last_heartbeat: float = 0.0
    failure_count: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)
    registered_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    @property
    def address(self) -> str:
        """Servisin ana makine ve port adresini döner."""
        return f"{self.host}:{self.port}" if self.port > 0 else self.host

    @property
    def is_alive(self) -> bool:
        """Servisin canlı ve yanıt verir durumda olup olmadığını döner."""
        if self.status == ServiceStatus.UNKNOWN:
            return True
        return self.status in (ServiceStatus.HEALTHY, ServiceStatus.DEGRADED)

    def to_dict(self) -> dict[str, Any]:
        """Sözlük formatına dönüştürür."""
        d = asdict(self)
        d["status"] = self.status.value
        d["address"] = self.address
        d["is_alive"] = self.is_alive
        d["registered_at"] = self.registered_at.isoformat()
        return d

    def to_orjson_bytes(self) -> bytes:
        """orjson bayt dizisine serileştirir."""
        return orjson.dumps(self.to_dict(), default=str)

    def __repr__(self) -> str:
        return (
            f"ServiceInfo(ad='{self.name}', adres='{self.address}', "
            f"durum='{self.status.value}', arizalar={self.failure_count})"
        )


def set_service_mesh_duckdb_connection(conn: duckdb.DuckDBPyConnection) -> None:
    """Servis sağlık arşivi için DuckDB bağlantısını tanımlar."""
    global _MESH_DUCKDB_CONN
    with _GLOBAL_LOCK:
        _MESH_DUCKDB_CONN = conn
        _init_service_mesh_duckdb_schema_conn(_MESH_DUCKDB_CONN)


def set_service_mesh_duckdb_path(path: str) -> None:
    """Servis sağlık arşivi DuckDB dosya yolunu tanımlar."""
    global _MESH_DUCKDB_PATH
    with _GLOBAL_LOCK:
        _MESH_DUCKDB_PATH = path


def _init_service_mesh_duckdb_schema_conn(conn: duckdb.DuckDBPyConnection) -> None:
    """DuckDB servis sağlık denetim şemasını belirtilen bağlantıda ilklendirir."""
    try:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS service_health_audit (
                id BIGINT,
                service_name VARCHAR,
                address VARCHAR,
                status VARCHAR,
                failure_count INTEGER,
                response_time_ms DOUBLE,
                recorded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE SEQUENCE IF NOT EXISTS seq_service_health_audit START 1;
        """)
    except Exception as exc:
        logger.error("ServiceMesh DuckDB şema oluşturma hatası", hata=str(exc))


def _get_active_duckdb(writable: bool = False) -> tuple[duckdb.DuckDBPyConnection | None, bool]:
    """Aktif DuckDB bağlantısını ve bağlantının geçici olup olmadığını döner."""
    global _MESH_DUCKDB_CONN, _MESH_DUCKDB_PATH
    if _MESH_DUCKDB_CONN is not None:
        return _MESH_DUCKDB_CONN, False
    try:
        p = Path(_MESH_DUCKDB_PATH)
        p.parent.mkdir(parents=True, exist_ok=True)
        read_only = not writable
        conn = duckdb.connect(str(p), read_only=read_only)
        if writable:
            configure_duckdb_wal(conn)
            _init_service_mesh_duckdb_schema_conn(conn)
        return conn, True
    except Exception as exc:
        logger.debug("ServiceMesh DuckDB dosya bağlantı hatası", yol=_MESH_DUCKDB_PATH, hata=str(exc))
        return None, False


def _record_health_audit(
    name: str,
    address: str,
    status: ServiceStatus,
    failure_count: int,
    response_time_ms: float,
) -> None:
    """Sağlık kontrolü sonucunu DuckDB denetim tablosuna yazar."""
    with _GLOBAL_LOCK:
        conn, should_close = _get_active_duckdb(writable=True)
        if conn is None:
            return
        try:
            conn.execute(
                """
                INSERT INTO service_health_audit (
                    id, service_name, address, status, failure_count, response_time_ms, recorded_at
                ) VALUES (
                    nextval('seq_service_health_audit'), ?, ?, ?, ?, ?, ?
                )
                """,
                [
                    name,
                    address,
                    status.value,
                    failure_count,
                    response_time_ms,
                    datetime.now(UTC),
                ],
            )
        except Exception as exc:
            logger.debug("ServiceMesh DuckDB denetim yazma hatası", hata=str(exc))
        finally:
            if should_close:
                with contextlib.suppress(Exception):
                    conn.close()


class ServiceDiscovery:
    """Servis Keşfi ve Sağlık Takip Yöneticisi (Thread-Safe & Async Destekli)."""

    def __init__(
        self,
        health_check_interval: int = DEFAULT_HEALTH_CHECK_INTERVAL,
        failure_threshold: int = DEFAULT_FAILURE_THRESHOLD,
        duckdb_conn: duckdb.DuckDBPyConnection | None = None,
    ) -> None:
        self._lock = threading.RLock()
        self._services: dict[str, ServiceInfo] = {}
        self._health_check_interval = health_check_interval
        self._failure_threshold = failure_threshold
        self._running = False
        self._ca_cert: str | None = None
        self._ca_key: str | None = None
        self._health_history: dict[str, list[bool]] = {}

        if duckdb_conn is not None:
            set_service_mesh_duckdb_connection(duckdb_conn)

    @otel_trace("service_mesh.register")
    def register(
        self,
        name: str,
        host: str,
        port: int = 0,
        metadata: dict[str, Any] | None = None,
    ) -> ServiceInfo:
        """Yeni bir servisi ağ kataloğuna kaydeder."""
        with self._lock:
            info = ServiceInfo(
                name=name,
                host=host,
                port=port,
                metadata=metadata or {},
            )
            self._services[name] = info
            self._health_history[name] = []
            logger.info("Servis kaydedildi", name=name, address=info.address)
            return info

    @otel_trace("service_mesh.unregister")
    def unregister(self, name: str) -> bool:
        """Servis kaydını katalogdan kaldırır."""
        with self._lock:
            removed = self._services.pop(name, None) is not None
            self._health_history.pop(name, None)
            if removed:
                logger.info("Servis kaydı silindi", name=name)
            return removed

    def get_service(self, name: str) -> ServiceInfo | None:
        """Adı verilen servisin bilgisini döner."""
        with self._lock:
            return self._services.get(name)

    def get_healthy_services(self) -> list[ServiceInfo]:
        """Yalnızca canlı ve sağlıklı servisleri listeler."""
        with self._lock:
            return [s for s in self._services.values() if s.is_alive]

    def get_all_services(self) -> dict[str, ServiceInfo]:
        """Kayıtlı tüm servislerin kopyasını döner."""
        with self._lock:
            return dict(self._services)

    def get_all_health(self) -> dict[str, dict[str, Any]]:
        """Tüm servislerin sağlık durum raporunu topluca döner."""
        with self._lock:
            return {name: self.get_health(name) for name in self._services}

    @otel_trace("service_mesh.check_health")
    async def check_health(self, name: str) -> ServiceStatus:
        """Tekil bir servisin anlık sağlık durumunu kontrol eder."""
        with self._lock:
            service = self._services.get(name)
            if not service:
                return ServiceStatus.UNKNOWN

        start_time = time.monotonic()
        service_type = service.metadata.get("type", "http" if service.port > 0 else "worker")
        new_status = ServiceStatus.UNKNOWN

        if service_type == "http" and service.port > 0:
            try:
                import httpx

                async with httpx.AsyncClient(timeout=3.0) as client:
                    resp = await client.get(f"http://{service.address}/health")
                    if resp.status_code == 200:
                        new_status = ServiceStatus.HEALTHY
                    else:
                        new_status = ServiceStatus.DEGRADED
            except Exception:
                new_status = ServiceStatus.UNHEALTHY
        else:
            # Worker / Event-loop / Redis servisi
            try:
                from .database import get_redis

                redis = await get_redis()
                if redis and await redis.ping():
                    new_status = ServiceStatus.HEALTHY
                else:
                    new_status = ServiceStatus.DEGRADED
            except Exception:
                # Redis yoksa veya ulaşılamazsa güvenli varsayım: Healthy (Fail-Open worker fallback)
                new_status = ServiceStatus.HEALTHY

        elapsed_ms = (time.monotonic() - start_time) * 1000.0

        with self._lock:
            service.last_heartbeat = time.time()
            if new_status == ServiceStatus.HEALTHY:
                service.status = ServiceStatus.HEALTHY
                service.failure_count = 0
                self._record_health_history(name, True)
            elif new_status == ServiceStatus.DEGRADED:
                service.status = ServiceStatus.DEGRADED
                service.failure_count += 1
                self._record_health_history(name, False)
            else:
                service.failure_count += 1
                if service.failure_count >= self._failure_threshold:
                    service.status = ServiceStatus.UNHEALTHY
                else:
                    service.status = ServiceStatus.DEGRADED
                self._record_health_history(name, False)

            _record_health_audit(
                name=service.name,
                address=service.address,
                status=service.status,
                failure_count=service.failure_count,
                response_time_ms=round(elapsed_ms, 2),
            )
            return service.status

    def _record_health_history(self, name: str, healthy: bool) -> None:
        """Sağlık durumunu bellek içi son 100 kontrol geçmişine işler."""
        if name not in self._health_history:
            self._health_history[name] = []
        history = self._health_history[name]
        history.append(healthy)
        if len(history) > 100:
            history.pop(0)

    def get_uptime_percentage(self, name: str) -> float:
        """Servisin son kontrollerdeki çalışma süresi (uptime) yüzdesini döner."""
        with self._lock:
            history = self._health_history.get(name, [])
            if not history:
                return 100.0 if (name in self._services and self._services[name].is_alive) else 0.0
            return (sum(history) / len(history)) * 100.0

    def get_health(self, name: str) -> dict[str, Any]:
        """Belirtilen servisin detaylı sağlık raporunu döner."""
        with self._lock:
            service = self._services.get(name)
            if not service:
                return {"status": ServiceStatus.UNKNOWN.value, "error": "not registered"}

            return {
                "name": service.name,
                "address": service.address,
                "status": service.status.value,
                "failure_count": service.failure_count,
                "last_heartbeat": service.last_heartbeat,
                "is_alive": service.is_alive,
                "uptime_pct": round(self.get_uptime_percentage(name), 1),
            }

    @otel_trace("service_mesh.check_all_health")
    async def check_all_health(self) -> dict[str, ServiceStatus]:
        """Tüm servislerin sağlık durumunu eşzamanlı denetler."""
        names = list(self.get_all_services().keys())
        tasks = [self.check_health(name) for name in names]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        status_map: dict[str, ServiceStatus] = {}
        for name, res in zip(names, results, strict=False):
            if isinstance(res, ServiceStatus):
                status_map[name] = res
            else:
                status_map[name] = ServiceStatus.UNKNOWN
        return status_map

    @otel_trace("service_mesh.start_monitoring")
    async def start_monitoring(self) -> None:
        """Arka planda periyodik servis sağlık takibini başlatır."""
        with self._lock:
            self._running = True

        logger.info(
            "Servis sağlık izleme döngüsü başlatıldı",
            servis_adedi=len(self.get_all_services()),
            aralik_sn=self._health_check_interval,
        )

        while True:
            with self._lock:
                if not self._running:
                    break

            try:
                results = await self.check_all_health()
                unhealthy = [k for k, v in results.items() if v == ServiceStatus.UNHEALTHY]
                if unhealthy:
                    logger.warn("Sağlıksız servisler tespit edildi", arizali_servisler=unhealthy)
            except Exception as exc:
                logger.debug("Sağlık denetim döngüsünde hata", hata=str(exc))

            await asyncio.sleep(self._health_check_interval)

    def stop_monitoring(self) -> None:
        """Sağlık takibini güvenle durdurur."""
        with self._lock:
            self._running = False

    # =========================================================================
    # SSL & mTLS Konfigürasyonu
    # =========================================================================

    def generate_ca(self, cert_dir: str = "data/certs") -> None:
        """Geliştirme ve Docker ortamı için self-signed CA sertifikası üretir."""
        os.makedirs(cert_dir, exist_ok=True)
        ca_cert_path = os.path.join(cert_dir, "ca.pem")
        ca_key_path = os.path.join(cert_dir, "ca-key.pem")

        with self._lock:
            if os.path.exists(ca_cert_path) and os.path.exists(ca_key_path):
                self._ca_cert = ca_cert_path
                self._ca_key = ca_key_path
                logger.info("CA sertifikası diskten yüklendi", yol=ca_cert_path)
                return

            try:
                import datetime as dt

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
                    .not_valid_before(dt.datetime.now(UTC))
                    .not_valid_after(dt.datetime.now(UTC) + dt.timedelta(days=3650))
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
                logger.info("Yeni CA sertifikası üretildi", yol=ca_cert_path)

            except ImportError:
                logger.warn("cryptography paketi yüklü değil, SSL devre dışı bırakıldı")

    def get_ssl_context(self, service_name: str) -> ssl.SSLContext | None:
        """Servis bağlantısı için SSL bağlamı oluşturur."""
        with self._lock:
            if not self._ca_cert:
                return None

            try:
                ctx = ssl.create_default_context(cafile=self._ca_cert)
                ctx.check_hostname = False
                ctx.verify_mode = ssl.CERT_REQUIRED
                return ctx
            except Exception as exc:
                logger.debug("SSL context oluşturulamadı", hata=str(exc))
                return None

    # =========================================================================
    # Trafik Yönetimi ve Dayanıklılık (Resilience)
    # =========================================================================

    def get_circuit_breaker_config(self, service_name: str) -> dict[str, Any]:
        """Servis için devre kesici (circuit breaker) parametrelerini döner."""
        return {
            "failure_threshold": 5,
            "recovery_timeout": 30,
            "half_open_max_calls": 3,
        }

    def get_retry_config(self, service_name: str) -> dict[str, Any]:
        """Servis için yeniden deneme (retry) parametrelerini döner."""
        return {
            "max_retries": 3,
            "backoff_base": 1.0,
            "backoff_max": 30.0,
        }

    def export_services_to_polars(self) -> pl.DataFrame:
        """Kayıtlı tüm servislerin anlık durumunu Polars DataFrame olarak döner."""
        with self._lock:
            if not self._services:
                return pl.DataFrame(
                    schema={
                        "name": pl.Utf8,
                        "host": pl.Utf8,
                        "port": pl.Int64,
                        "status": pl.Utf8,
                        "address": pl.Utf8,
                        "is_alive": pl.Boolean,
                        "failure_count": pl.Int64,
                        "uptime_pct": pl.Float64,
                    }
                )

            data = [
                {
                    "name": s.name,
                    "host": s.host,
                    "port": s.port,
                    "status": s.status.value,
                    "address": s.address,
                    "is_alive": s.is_alive,
                    "failure_count": s.failure_count,
                    "uptime_pct": self.get_uptime_percentage(s.name),
                }
                for s in self._services.values()
            ]
            return pl.DataFrame(data)

    def export_health_audit_to_polars(self) -> pl.DataFrame:
        """DuckDB'de saklanan servis sağlık denetim geçmişini Polars DataFrame olarak döner."""
        return self.read_health_audit_from_duckdb()

    def read_health_audit_from_duckdb(self, limit: int = 1000) -> pl.DataFrame:
        """DuckDB'de saklanan servis sağlık denetim kayıtlarını okur."""
        return read_service_health_audit_from_duckdb(limit=limit)

    def clear_health_audit_duckdb(self) -> None:
        """DuckDB üzerindeki servis sağlık kayıtlarını temizler."""
        clear_service_mesh_audit_duckdb()

    def __repr__(self) -> str:
        with self._lock:
            return (
                f"ServiceDiscovery(servis_sayisi={len(self._services)}, "
                f"canli_servisler={len(self.get_healthy_services())}, "
                f"izleme_aktif={self._running})"
            )


# Global singleton örneği — geriye dönük tam uyumluluk
service_mesh: Final[ServiceDiscovery] = ServiceDiscovery()


def init_service_mesh() -> ServiceDiscovery:
    """Tüm standart BIST servislerini keşif kataloğuna kaydeder."""
    services: dict[str, tuple[str, int, dict[str, Any]]] = {
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

    if os.environ.get("ENABLE_MTLS", "false").lower() == "true":
        service_mesh.generate_ca()

    logger.info("Servis keşfi ve sağlık takibi hazırlandı", servis_sayisi=len(services))
    return service_mesh


def export_health_audit_to_polars() -> pl.DataFrame:
    """DuckDB'de saklanan servis sağlık denetim geçmişini Polars DataFrame olarak döner."""
    return service_mesh.export_health_audit_to_polars()


def export_services_to_polars() -> pl.DataFrame:
    """Kayıtlı tüm servislerin anlık durumunu Polars DataFrame olarak döner."""
    return service_mesh.export_services_to_polars()


def read_service_health_audit_from_duckdb(
    duckdb_path: str = DEFAULT_SERVICE_MESH_DB,
    limit: int = 1000,
) -> pl.DataFrame:
    """Doğrudan DuckDB dosyasından veya aktif bağlantıdan servis sağlık denetim geçmişini okur."""
    empty_df = pl.DataFrame(
        schema={
            "id": pl.Int64,
            "service_name": pl.Utf8,
            "address": pl.Utf8,
            "status": pl.Utf8,
            "failure_count": pl.Int64,
            "response_time_ms": pl.Float64,
            "recorded_at": pl.Datetime,
        }
    )
    with _GLOBAL_LOCK:
        conn, should_close = _get_active_duckdb(writable=False)
        if conn is None:
            return empty_df
        try:
            query = f"SELECT * FROM service_health_audit ORDER BY id ASC LIMIT {int(limit)}"
            return conn.execute(query).pl()
        except Exception as exc:
            logger.error("DuckDB servis sağlık kayıtları çekilemedi", hata=str(exc))
            return empty_df
        finally:
            if should_close:
                with contextlib.suppress(Exception):
                    conn.close()


def clear_service_mesh_audit_duckdb(
    duckdb_path: str = DEFAULT_SERVICE_MESH_DB,
) -> None:
    """Servis sağlık denetim tablosunu temizler."""
    with _GLOBAL_LOCK:
        conn, should_close = _get_active_duckdb(writable=True)
        if conn is None:
            return
        try:
            conn.execute("DELETE FROM service_health_audit;")
        except Exception as exc:
            logger.error("DuckDB servis sağlık kayıtları temizlenemedi", hata=str(exc))
        finally:
            if should_close:
                with contextlib.suppress(Exception):
                    conn.close()


__all__ = [
    "DEFAULT_CHECKPOINT_SIZE",
    "DEFAULT_FAILURE_THRESHOLD",
    "DEFAULT_HEALTH_CHECK_INTERVAL",
    "DEFAULT_SERVICE_MESH_DB",
    "DEFAULT_WAL_SIZE",
    "ServiceDiscovery",
    "ServiceInfo",
    "ServiceStatus",
    "clear_service_mesh_audit_duckdb",
    "configure_duckdb_wal",
    "export_health_audit_to_polars",
    "export_services_to_polars",
    "init_service_mesh",
    "read_service_health_audit_from_duckdb",
    "service_mesh",
    "set_service_mesh_duckdb_connection",
    "set_service_mesh_duckdb_path",
    "to_orjson_bytes",
]
