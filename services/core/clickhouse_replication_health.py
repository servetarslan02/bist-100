"""ALPHA BIST — ClickHouse Replikasyon Sağlık İzleyicisi (Replication Health Monitor).

Bu modül, ClickHouse kümesindeki ReplicatedMergeTree tablolarının replikasyon durumunu,
gecikmelerini (absolute_delay), kuyruk boyutlarını, aktif replika sayısını (active_replicas),
hasarlı parça durumunu (parts_to_check) ve salt-okunur (read-only) kilitlenmelerini
`system.replicas` tablosu üzerinden izler, Prometheus ve JSON formatlarında sunar.

Hem senkron hem de asenkron (event loop dostu) çalıştırma arayüzlerini destekler.

Referanslar:
- CORE-NIHAI-SPEC.md - Section 2.5 (Replication & OLAP Health)
"""

from __future__ import annotations

import asyncio
import math
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Final

import structlog

from services.core.otel import otel_trace

from .database import ch_execute

if TYPE_CHECKING:
    from collections.abc import Sequence

logger = structlog.get_logger(__name__)

# Varsayılan Eşik Değerleri ve Sabitler
DEFAULT_DATABASE: Final[str] = "alpha_bist"
DEFAULT_MAX_ABSOLUTE_DELAY_SECONDS: Final[int] = 10
DEFAULT_MAX_QUEUE_SIZE: Final[int] = 100


@dataclass(slots=True)
class ReplicaHealthInfo:
    """Tek bir tablonun replika durum, kuyruk ve aktif düğüm bilgileri.

    Attributes:
        database: Veritabanı adı.
        table: Tablo adı.
        is_leader: Bu replikanın lider olup olmadığı.
        is_readonly: Tablonun salt-okunur modda kilitlenip kilitlenmediği.
        absolute_delay: Saniye cinsinden mutlak replikasyon gecikmesi.
        queue_size: Bekleyen işlem kuyruk boyutu.
        inserts_in_queue: Kuyruktaki ekleme işlemi sayısı.
        merges_in_queue: Kuyruktaki birleştirme (merge) işlemi sayısı.
        total_replicas: Tanımlı toplam replika adedi.
        active_replicas: Anlık olarak çalışan ve iletişimde olan aktif replika adedi.
        parts_to_check: Replikasyonda doğrulanmayı bekleyen / hasarlı parça adedi.
    """

    database: str
    table: str
    is_leader: bool
    is_readonly: bool
    absolute_delay: int
    queue_size: int
    inserts_in_queue: int
    merges_in_queue: int
    total_replicas: int
    active_replicas: int = 1
    parts_to_check: int = 0

    def to_dict(self) -> dict[str, Any]:
        """Replika verisini serileştirilebilir sözlüğe dönüştürür."""
        return {
            "database": self.database,
            "table": self.table,
            "is_leader": self.is_leader,
            "is_readonly": self.is_readonly,
            "absolute_delay": self.absolute_delay,
            "queue_size": self.queue_size,
            "inserts_in_queue": self.inserts_in_queue,
            "merges_in_queue": self.merges_in_queue,
            "total_replicas": self.total_replicas,
            "active_replicas": self.active_replicas,
            "parts_to_check": self.parts_to_check,
        }

    def __repr__(self) -> str:
        """Replika için bilgilendirici metin temsili."""
        return (
            f"ReplicaHealthInfo(table='{self.table}', leader={self.is_leader}, "
            f"readonly={self.is_readonly}, delay={self.absolute_delay}s, "
            f"queue={self.queue_size}, replicas={self.active_replicas}/{self.total_replicas})"
        )


@dataclass(slots=True)
class ReplicationHealthReport:
    """ClickHouse replikasyon sağlık denetimi sonuç raporu.

    Attributes:
        status: Genel sağlık durumu ("healthy", "degraded", "error", "no_replicas_found").
        database: Denetlenen veritabanı adı.
        replicas: Tablo replika bilgileri listesi.
        errors: Tespit edilen replikasyon uyarı veya hata mesajları.
        timestamp: Raporun oluşturulma zaman damgası (ISO 8601).
    """

    status: str
    database: str
    replicas: list[ReplicaHealthInfo]
    errors: list[str]
    timestamp: str

    def to_dict(self) -> dict[str, Any]:
        """Sağlık raporunu serileştirilebilir sözlüğe dönüştürür."""
        return {
            "status": self.status,
            "database": self.database,
            "timestamp": self.timestamp,
            "replicas": [r.to_dict() for r in self.replicas],
            "errors": list(self.errors),
        }

    def __repr__(self) -> str:
        """Rapor için bilgilendirici metin temsili."""
        return (
            f"ReplicationHealthReport(status='{self.status}', database='{self.database}', "
            f"replicas={len(self.replicas)}, errors={len(self.errors)})"
        )


@otel_trace("clickhouse_replication_health.check_replication_health")
def check_replication_health(
    database: str = DEFAULT_DATABASE,
    max_absolute_delay: int = DEFAULT_MAX_ABSOLUTE_DELAY_SECONDS,
    max_queue_size: int = DEFAULT_MAX_QUEUE_SIZE,
) -> dict[str, Any]:
    """ClickHouse sistemindeki tabloların replikasyon sağlık durumunu senkron olarak denetler.

    Args:
        database: Denetlenecek hedef veritabanı.
        max_absolute_delay: Uyarı tetikleyecek maksimum gecikme eşiği (saniye).
        max_queue_size: Uyarı tetikleyecek maksimum kuyruk boyutu eşiği.

    Returns:
        dict[str, Any]: Replikasyon durum raporu sözlüğü (ReplicationHealthReport.to_dict()).
    """
    now_iso = datetime.now(UTC).isoformat()
    replicas: list[ReplicaHealthInfo] = []
    errors: list[str] = []
    status = "unknown"

    try:
        # system.replicas tablosundan active_replicas ve parts_to_check dahil parametrik sorgulama
        query = """
            SELECT
                database,
                table,
                is_leader,
                is_readonly,
                absolute_delay,
                queue_size,
                inserts_in_queue,
                merges_in_queue,
                total_replicas,
                active_replicas,
                parts_to_check
            FROM system.replicas
            WHERE database = {db:String}
        """

        result = ch_execute(query, parameters={"db": database})
        rows = getattr(result, "result_rows", None)
        if rows is None and isinstance(result, (list, tuple)):
            rows = result

        if rows:
            for row in rows:
                replica_info = ReplicaHealthInfo(
                    database=str(row[0]),
                    table=str(row[1]),
                    is_leader=bool(row[2]),
                    is_readonly=bool(row[3]),
                    absolute_delay=int(row[4]) if row[4] is not None and not math.isnan(row[4]) else 0,
                    queue_size=int(row[5]) if row[5] is not None and not math.isnan(row[5]) else 0,
                    inserts_in_queue=int(row[6]) if row[6] is not None and not math.isnan(row[6]) else 0,
                    merges_in_queue=int(row[7]) if row[7] is not None and not math.isnan(row[7]) else 0,
                    total_replicas=int(row[8]) if row[8] is not None and not math.isnan(row[8]) else 0,
                    active_replicas=(
                        int(row[9])
                        if len(row) > 9 and row[9] is not None and not math.isnan(row[9])
                        else (int(row[8]) if row[8] is not None else 1)
                    ),
                    parts_to_check=(
                        int(row[10])
                        if len(row) > 10 and row[10] is not None and not math.isnan(row[10])
                        else 0
                    ),
                )
                replicas.append(replica_info)

                # Sağlık ve Eşik Denetimleri
                if replica_info.absolute_delay > max_absolute_delay:
                    errors.append(
                        f"{replica_info.table}: Replikasyon gecikmesi yüksek ({replica_info.absolute_delay}s > {max_absolute_delay}s)"
                    )
                if replica_info.is_readonly:
                    errors.append(f"{replica_info.table}: Tablo salt-okunur (read-only) modda kilitli")
                if replica_info.queue_size > max_queue_size:
                    errors.append(
                        f"{replica_info.table}: Kuyruk boyutu kritik seviyede ({replica_info.queue_size} > {max_queue_size})"
                    )
                if replica_info.total_replicas > 1 and replica_info.active_replicas < replica_info.total_replicas:
                    errors.append(
                        f"{replica_info.table}: Aktif replika kaybı tespit edildi ({replica_info.active_replicas}/{replica_info.total_replicas})"
                    )
                if replica_info.parts_to_check > 0:
                    errors.append(
                        f"{replica_info.table}: Hasarlı veya kontrol bekleyen parçalar var ({replica_info.parts_to_check} parça)"
                    )

            if not errors:
                status = "healthy"
            else:
                status = "degraded"
        else:
            status = "no_replicas_found"

    except Exception as exc:
        status = "error"
        error_msg = str(exc)
        errors.append(error_msg)
        logger.error("clickhouse_replikasyon_saglik_kontrolu_basarisiz", veritabani=database, hata=error_msg)

    report = ReplicationHealthReport(
        status=status,
        database=database,
        replicas=replicas,
        errors=errors,
        timestamp=now_iso,
    )
    return report.to_dict()


async def check_replication_health_async(
    database: str = DEFAULT_DATABASE,
    max_absolute_delay: int = DEFAULT_MAX_ABSOLUTE_DELAY_SECONDS,
    max_queue_size: int = DEFAULT_MAX_QUEUE_SIZE,
) -> dict[str, Any]:
    """ClickHouse replikasyon sağlık durumunu event loop'u bloke etmeden asenkron denetler.

    Args:
        database: Denetlenecek hedef veritabanı.
        max_absolute_delay: Uyarı tetikleyecek maksimum gecikme eşiği.
        max_queue_size: Uyarı tetikleyecek maksimum kuyruk boyutu eşiği.

    Returns:
        dict[str, Any]: Replikasyon durum raporu sözlüğü.
    """
    return await asyncio.to_thread(
        check_replication_health,
        database=database,
        max_absolute_delay=max_absolute_delay,
        max_queue_size=max_queue_size,
    )


def is_replication_healthy(database: str = DEFAULT_DATABASE) -> bool:
    """Replikasyonun tamamen sağlıklı (healthy) olup olmadığını döner (Liveness/Readiness probe).

    Args:
        database: Hedef veritabanı.

    Returns:
        bool: Sağlıklı ise True, aksi halde False.
    """
    report = check_replication_health(database=database)
    return report.get("status") == "healthy"


async def is_replication_healthy_async(database: str = DEFAULT_DATABASE) -> bool:
    """Asenkron liveness/readiness kontrolü.

    Args:
        database: Hedef veritabanı.

    Returns:
        bool: Sağlıklı ise True, aksi halde False.
    """
    report = await check_replication_health_async(database=database)
    return report.get("status") == "healthy"


@otel_trace("clickhouse_replication_health.get_replication_metrics")
def get_replication_metrics(database: str = DEFAULT_DATABASE) -> dict[str, Any]:
    """Replikasyon metriklerini sözlük formatında döner (Geriye dönük uyumluluk).

    Args:
        database: Hedef veritabanı.

    Returns:
        dict[str, Any]: Metrik adı ve sayısal değer haritası.
    """
    health = check_replication_health(database=database)
    replicas = health.get("replicas", [])
    errors = health.get("errors", [])

    metrics: dict[str, Any] = {
        "clickhouse_replica_count": len(replicas),
        "clickhouse_replica_errors": len(errors),
        "clickhouse_replication_healthy": 1 if health.get("status") == "healthy" else 0,
    }

    for replica in replicas:
        table = replica.get("table", "unknown")
        metrics[f"clickhouse_replica_delay_{table}"] = replica.get("absolute_delay", 0)
        metrics[f"clickhouse_replica_queue_{table}"] = replica.get("queue_size", 0)
        metrics[f"clickhouse_replica_leader_{table}"] = 1 if replica.get("is_leader") else 0
        metrics[f"clickhouse_replica_readonly_{table}"] = 1 if replica.get("is_readonly") else 0
        metrics[f"clickhouse_replica_active_{table}"] = replica.get("active_replicas", 1)
        metrics[f"clickhouse_replica_parts_to_check_{table}"] = replica.get("parts_to_check", 0)

    return metrics


@otel_trace("clickhouse_replication_health.export_prometheus")
def export_prometheus(database: str = DEFAULT_DATABASE) -> str:
    """Replikasyon metriklerini etiketli (labeled) standart Prometheus formatında döner.

    Returns:
        str: Prometheus metin formatı çıktısı.
    """
    health = check_replication_health(database=database)
    replicas = health.get("replicas", [])
    errors = health.get("errors", [])
    status = health.get("status", "unknown")

    status_val = {"healthy": 0, "degraded": 1, "no_replicas_found": 2, "error": 3}.get(status, -1)

    lines: list[str] = [
        "# HELP clickhouse_replication_status Replikasyon genel durumu (0=HEALTHY, 1=DEGRADED, 2=NO_REPLICAS, 3=ERROR)",
        "# TYPE clickhouse_replication_status gauge",
        f'clickhouse_replication_status{{database="{database}"}} {status_val}',
        "# HELP clickhouse_replica_count İzlenen toplam replika adedi",
        "# TYPE clickhouse_replica_count gauge",
        f'clickhouse_replica_count{{database="{database}"}} {len(replicas)}',
        "# HELP clickhouse_replica_errors Tespit edilen replikasyon hata/uyarı sayısı",
        "# TYPE clickhouse_replica_errors gauge",
        f'clickhouse_replica_errors{{database="{database}"}} {len(errors)}',
        "# HELP clickhouse_replica_absolute_delay_seconds Replikasyon mutlak gecikmesi (saniye)",
        "# TYPE clickhouse_replica_absolute_delay_seconds gauge",
        "# HELP clickhouse_replica_queue_size Replikasyon işlem kuyruğu boyutu",
        "# TYPE clickhouse_replica_queue_size gauge",
        "# HELP clickhouse_replica_is_leader Bu replika lider mi (1=Evet, 0=Hayır)",
        "# TYPE clickhouse_replica_is_leader gauge",
        "# HELP clickhouse_replica_is_readonly Replika salt-okunur mu (1=Evet, 0=Hayır)",
        "# TYPE clickhouse_replica_is_readonly gauge",
        "# HELP clickhouse_replica_active_nodes Aktif replika düğüm sayısı",
        "# TYPE clickhouse_replica_active_nodes gauge",
        "# HELP clickhouse_replica_parts_to_check Kontrol bekleyen / hasarlı veri parçası sayısı",
        "# TYPE clickhouse_replica_parts_to_check gauge",
    ]

    for replica in replicas:
        table = str(replica.get("table", "unknown")).replace('"', '\\"')
        labels = f'database="{database}",table="{table}"'

        delay = replica.get("absolute_delay", 0)
        queue = replica.get("queue_size", 0)
        leader = 1 if replica.get("is_leader") else 0
        readonly = 1 if replica.get("is_readonly") else 0
        active = replica.get("active_replicas", 1)
        parts = replica.get("parts_to_check", 0)

        lines.append(f"clickhouse_replica_absolute_delay_seconds{{{labels}}} {delay}")
        lines.append(f"clickhouse_replica_queue_size{{{labels}}} {queue}")
        lines.append(f"clickhouse_replica_is_leader{{{labels}}} {leader}")
        lines.append(f"clickhouse_replica_is_readonly{{{labels}}} {readonly}")
        lines.append(f"clickhouse_replica_active_nodes{{{labels}}} {active}")
        lines.append(f"clickhouse_replica_parts_to_check{{{labels}}} {parts}")

    return "\n".join(lines) + "\n"


async def export_prometheus_async(database: str = DEFAULT_DATABASE) -> str:
    """Asenkron Prometheus metin çıktısı."""
    return await asyncio.to_thread(export_prometheus, database=database)


if __name__ == "__main__":
    import orjson

    _health = check_replication_health()
    logger.info("clickhouse_replikasyon_raporu", rapor=orjson.dumps(_health, option=orjson.OPT_INDENT_2).decode())

__all__: Sequence[str] = [
    "DEFAULT_DATABASE",
    "DEFAULT_MAX_ABSOLUTE_DELAY_SECONDS",
    "DEFAULT_MAX_QUEUE_SIZE",
    "ReplicaHealthInfo",
    "ReplicationHealthReport",
    "check_replication_health",
    "check_replication_health_async",
    "export_prometheus",
    "export_prometheus_async",
    "get_replication_metrics",
    "is_replication_healthy",
    "is_replication_healthy_async",
]
