"""ALPHA BIST — ClickHouse Replikasyon Sağlık İzleyicisi (Replication Health Monitor).

Bu modül, ClickHouse kümesindeki ReplicatedMergeTree tablolarının replikasyon durumunu,
gecikmelerini (absolute_delay), kuyruk boyutlarını, aktif replika sayısını (active_replicas),
hasarlı parça durumunu (parts_to_check) ve salt-okunur (read-only) kilitlenmelerini
`system.replicas` tablosu üzerinden izler, Prometheus, Polars, DuckDB ve orjson formatlarında sunar.

Hem senkron hem de asenkron (event loop dostu) çalıştırma arayüzlerini destekler.

Referanslar:
- CORE-NIHAI-SPEC.md - Section 2.5 (Replication & OLAP Health)
"""

from __future__ import annotations

import asyncio
import math
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

import duckdb
import orjson
import polars as pl
import structlog

from services.core.otel import otel_trace

from .database import ch_execute

logger = structlog.get_logger(__name__)

# Varsayılan Eşik Değerleri ve Yapılandırma Sabitleri
DEFAULT_DATABASE: Final[str] = "alpha_bist"
DEFAULT_MAX_ABSOLUTE_DELAY_SECONDS: Final[int] = 10
DEFAULT_MAX_QUEUE_SIZE: Final[int] = 100
DEFAULT_REPLICATION_HEALTH_DB_PATH: Final[str] = "data/replication_health.duckdb"
DEFAULT_CHECKPOINT_SIZE: Final[str] = "4MB"
DEFAULT_WAL_SIZE: Final[str] = "2MB"
VALID_HEALTH_STATUSES: Final[tuple[str, ...]] = (
    "healthy",
    "degraded",
    "no_replicas_found",
    "error",
    "unknown",
)
STATUS_PROMETHEUS_CODE_MAP: Final[dict[str, int]] = {
    "healthy": 0,
    "degraded": 1,
    "no_replicas_found": 2,
    "error": 3,
    "unknown": -1,
}


def configure_duckdb_wal(conn: duckdb.DuckDBPyConnection) -> None:
    """DuckDB bağlantısı için WAL ve checkpoint parametrelerini optimize eder.

    Args:
        conn: Yapılandırılacak DuckDB bağlantısı.
    """
    try:
        conn.execute(f"PRAGMA checkpoint_threshold = '{DEFAULT_CHECKPOINT_SIZE}';")
        conn.execute(f"PRAGMA wal_autocheckpoint = '{DEFAULT_WAL_SIZE}';")
    except Exception as exc:
        logger.warning("duckdb_wal_yapilandirma_uyarisi", hata=str(exc))


def to_orjson_bytes(val: Any) -> bytes:
    """Herhangi bir veriyi orjson ile güvenli bayt dizisine dönüştürür.

    Args:
        val: Serileştirilecek veri.

    Returns:
        bytes: orjson ile kodlanmış baytlar.
    """
    if hasattr(val, "to_dict"):
        val = val.to_dict()
    return orjson.dumps(val, default=str)


def _safe_int(val: Any, default: int = 0) -> int:
    """Değeri güvenli bir şekilde tamsayıya dönüştürür; NaN, Inf veya tip uyuşmazlığında default döner.

    Args:
        val: Dönüştürülecek ham değer.
        default: Hata veya eksiklik durumunda dönülecek varsayılan değer.

    Returns:
        int: Güvenli tamsayı karşılığı.
    """
    if val is None:
        return default
    try:
        f = float(val)
        if math.isnan(f) or math.isinf(f):
            return default
        return int(f)
    except (ValueError, TypeError, OverflowError):
        return default


def _escape_label_value(val: Any) -> str:
    """Prometheus label değerini standartlara uygun şekilde kaçışlar.

    Args:
        val: Etiket değeri.

    Returns:
        str: Kaçışlanmış güvenli metin.
    """
    return str(val).replace("\\", "\\\\").replace('"', '\\"').replace("\n", "")


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
        """Replika verisini serileştirilebilir sözlüğe dönüştürür.

        Returns:
            dict[str, Any]: Durum sözlüğü.
        """
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

    def to_orjson_bytes(self) -> bytes:
        """Replika verisini orjson bayt dizisine dönüştürür."""
        return to_orjson_bytes(self.to_dict())

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
        """Sağlık raporunu serileştirilebilir sözlüğe dönüştürür.

        Returns:
            dict[str, Any]: Rapor sözlüğü.
        """
        return {
            "status": self.status,
            "database": self.database,
            "timestamp": self.timestamp,
            "replicas": [r.to_dict() for r in self.replicas],
            "errors": list(self.errors),
        }

    def to_polars(self) -> pl.DataFrame:
        """Rapordaki replika bilgilerini Polars DataFrame olarak dışa aktarır.

        Returns:
            pl.DataFrame: Replikasyon verilerini içeren veri çerçevesi.
        """
        return export_replicas_to_polars(report=self)

    def to_orjson_bytes(self) -> bytes:
        """Sağlık raporunu orjson ile yüksek hızlı ikili JSON baytlarına dönüştürür.

        Returns:
            bytes: JSON baytları.
        """
        return orjson.dumps(self.to_dict(), option=orjson.OPT_INDENT_2)

    def __repr__(self) -> str:
        """Rapor için bilgilendirici metin temsili."""
        return (
            f"ReplicationHealthReport(status='{self.status}', database='{self.database}', "
            f"replicas={len(self.replicas)}, errors={len(self.errors)})"
        )


@otel_trace("clickhouse_replication_health.get_replication_report_object")
def get_replication_report_object(
    database: str = DEFAULT_DATABASE,
    max_absolute_delay: int = DEFAULT_MAX_ABSOLUTE_DELAY_SECONDS,
    max_queue_size: int = DEFAULT_MAX_QUEUE_SIZE,
) -> ReplicationHealthReport:
    """ClickHouse replikasyon sağlık durumunu denetleyip nesne olarak döner.

    Args:
        database: Denetlenecek hedef veritabanı.
        max_absolute_delay: Maksimum gecikme eşiği (saniye).
        max_queue_size: Maksimum işlem kuyruk boyutu.

    Returns:
        ReplicationHealthReport: Güçlü tipli rapor nesnesi.
    """
    safe_db = (database or DEFAULT_DATABASE).strip()
    safe_max_delay = max(0, _safe_int(max_absolute_delay, DEFAULT_MAX_ABSOLUTE_DELAY_SECONDS))
    safe_max_queue = max(0, _safe_int(max_queue_size, DEFAULT_MAX_QUEUE_SIZE))

    now_iso = datetime.now(UTC).isoformat()
    replicas: list[ReplicaHealthInfo] = []
    errors: list[str] = []
    status = "unknown"

    try:
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

        result = ch_execute(query, parameters={"db": safe_db})
        rows = getattr(result, "result_rows", None)
        if rows is None and isinstance(result, (list, tuple)):
            rows = result

        if rows:
            for row in rows:
                tot_rep = _safe_int(row[8], 0) if len(row) > 8 else 0
                act_rep = _safe_int(row[9], tot_rep or 1) if len(row) > 9 else (tot_rep or 1)
                parts = _safe_int(row[10], 0) if len(row) > 10 else 0

                replica_info = ReplicaHealthInfo(
                    database=str(row[0]) if len(row) > 0 and row[0] is not None else safe_db,
                    table=str(row[1]) if len(row) > 1 and row[1] is not None else "unknown",
                    is_leader=bool(row[2]) if len(row) > 2 else False,
                    is_readonly=bool(row[3]) if len(row) > 3 else False,
                    absolute_delay=_safe_int(row[4], 0) if len(row) > 4 else 0,
                    queue_size=_safe_int(row[5], 0) if len(row) > 5 else 0,
                    inserts_in_queue=_safe_int(row[6], 0) if len(row) > 6 else 0,
                    merges_in_queue=_safe_int(row[7], 0) if len(row) > 7 else 0,
                    total_replicas=tot_rep,
                    active_replicas=act_rep,
                    parts_to_check=parts,
                )
                replicas.append(replica_info)

                # Sağlık ve Eşik Denetimleri
                if replica_info.absolute_delay > safe_max_delay:
                    errors.append(
                        f"{replica_info.table}: Replikasyon gecikmesi yüksek "
                        f"({replica_info.absolute_delay}s > {safe_max_delay}s)"
                    )
                if replica_info.is_readonly:
                    errors.append(f"{replica_info.table}: Tablo salt-okunur (read-only) modda kilitli")
                if replica_info.queue_size > safe_max_queue:
                    errors.append(
                        f"{replica_info.table}: Kuyruk boyutu kritik seviyede "
                        f"({replica_info.queue_size} > {safe_max_queue})"
                    )
                if replica_info.total_replicas > 1 and replica_info.active_replicas < replica_info.total_replicas:
                    errors.append(
                        f"{replica_info.table}: Aktif replika kaybı tespit edildi "
                        f"({replica_info.active_replicas}/{replica_info.total_replicas})"
                    )
                if replica_info.parts_to_check > 0:
                    errors.append(
                        f"{replica_info.table}: Hasarlı veya kontrol bekleyen parçalar var "
                        f"({replica_info.parts_to_check} parça)"
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
        logger.error("clickhouse_replikasyon_saglik_kontrolu_basarisiz", veritabani=safe_db, hata=error_msg)

    return ReplicationHealthReport(
        status=status,
        database=safe_db,
        replicas=replicas,
        errors=errors,
        timestamp=now_iso,
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
    report = get_replication_report_object(
        database=database,
        max_absolute_delay=max_absolute_delay,
        max_queue_size=max_queue_size,
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

    Metrikler Prometheus format standartlarına uygun olarak aynı metrik grubu altında toplanır.

    Args:
        database: Hedef veritabanı.

    Returns:
        str: Prometheus metin formatı çıktısı.
    """
    safe_db = (database or DEFAULT_DATABASE).strip()
    health = check_replication_health(database=safe_db)
    replicas = health.get("replicas", [])
    errors = health.get("errors", [])
    status = str(health.get("status", "unknown"))

    status_val = STATUS_PROMETHEUS_CODE_MAP.get(status, -1)
    db_escaped = _escape_label_value(safe_db)

    lines: list[str] = [
        "# HELP clickhouse_replication_status Replikasyon genel durumu "
        "(0=HEALTHY, 1=DEGRADED, 2=NO_REPLICAS, 3=ERROR, -1=UNKNOWN)",
        "# TYPE clickhouse_replication_status gauge",
        f'clickhouse_replication_status{{database="{db_escaped}"}} {status_val}',
        "# HELP clickhouse_replica_count İzlenen toplam replika adedi",
        "# TYPE clickhouse_replica_count gauge",
        f'clickhouse_replica_count{{database="{db_escaped}"}} {len(replicas)}',
        "# HELP clickhouse_replica_errors Tespit edilen replikasyon hata/uyarı sayısı",
        "# TYPE clickhouse_replica_errors gauge",
        f'clickhouse_replica_errors{{database="{db_escaped}"}} {len(errors)}',
    ]

    if replicas:
        # Prometheus formatına uygun şekilde metrikleri grup grup ekleme
        # 1. Delay
        lines.append("# HELP clickhouse_replica_absolute_delay_seconds Replikasyon mutlak gecikmesi (saniye)")
        lines.append("# TYPE clickhouse_replica_absolute_delay_seconds gauge")
        for replica in replicas:
            table = _escape_label_value(replica.get("table", "unknown"))
            delay = _safe_int(replica.get("absolute_delay", 0))
            lines.append(f'clickhouse_replica_absolute_delay_seconds{{database="{db_escaped}",table="{table}"}} {delay}')

        # 2. Queue Size
        lines.append("# HELP clickhouse_replica_queue_size Replikasyon işlem kuyruğu boyutu")
        lines.append("# TYPE clickhouse_replica_queue_size gauge")
        for replica in replicas:
            table = _escape_label_value(replica.get("table", "unknown"))
            queue = _safe_int(replica.get("queue_size", 0))
            lines.append(f'clickhouse_replica_queue_size{{database="{db_escaped}",table="{table}"}} {queue}')

        # 3. Is Leader
        lines.append("# HELP clickhouse_replica_is_leader Bu replika lider mi (1=Evet, 0=Hayır)")
        lines.append("# TYPE clickhouse_replica_is_leader gauge")
        for replica in replicas:
            table = _escape_label_value(replica.get("table", "unknown"))
            leader = 1 if replica.get("is_leader") else 0
            lines.append(f'clickhouse_replica_is_leader{{database="{db_escaped}",table="{table}"}} {leader}')

        # 4. Is Readonly
        lines.append("# HELP clickhouse_replica_is_readonly Replika salt-okunur mu (1=Evet, 0=Hayır)")
        lines.append("# TYPE clickhouse_replica_is_readonly gauge")
        for replica in replicas:
            table = _escape_label_value(replica.get("table", "unknown"))
            readonly = 1 if replica.get("is_readonly") else 0
            lines.append(f'clickhouse_replica_is_readonly{{database="{db_escaped}",table="{table}"}} {readonly}')

        # 5. Active Nodes
        lines.append("# HELP clickhouse_replica_active_nodes Aktif replika düğüm sayısı")
        lines.append("# TYPE clickhouse_replica_active_nodes gauge")
        for replica in replicas:
            table = _escape_label_value(replica.get("table", "unknown"))
            active = _safe_int(replica.get("active_replicas", 1), 1)
            lines.append(f'clickhouse_replica_active_nodes{{database="{db_escaped}",table="{table}"}} {active}')

        # 6. Parts to Check
        lines.append("# HELP clickhouse_replica_parts_to_check Kontrol bekleyen / hasarlı veri parçası sayısı")
        lines.append("# TYPE clickhouse_replica_parts_to_check gauge")
        for replica in replicas:
            table = _escape_label_value(replica.get("table", "unknown"))
            parts = _safe_int(replica.get("parts_to_check", 0), 0)
            lines.append(f'clickhouse_replica_parts_to_check{{database="{db_escaped}",table="{table}"}} {parts}')

    return "\n".join(lines) + "\n"


async def export_prometheus_async(database: str = DEFAULT_DATABASE) -> str:
    """Asenkron Prometheus metin çıktısı.

    Args:
        database: Hedef veritabanı.

    Returns:
        str: Prometheus metrik çıktısı.
    """
    return await asyncio.to_thread(export_prometheus, database=database)


def export_replicas_to_polars(
    report: ReplicationHealthReport | dict[str, Any] | None = None,
    database: str = DEFAULT_DATABASE,
) -> pl.DataFrame:
    """Replika durum verilerini analitik Polars DataFrame olarak dışa aktarır (GEMINI.md Kural 2).

    Args:
        report: İsteğe bağlı önceden üretilmiş rapor veya sözlük; None ise anlık sorgulanır.
        database: Hedef veritabanı adı.

    Returns:
        pl.DataFrame: Replikasyon sağlık metrikleri veri çerçevesi.
    """
    if report is None:
        rep_dict = check_replication_health(database=database)
    elif isinstance(report, ReplicationHealthReport):
        rep_dict = report.to_dict()
    else:
        rep_dict = report

    replicas = rep_dict.get("replicas", [])
    timestamp = rep_dict.get("timestamp", datetime.now(UTC).isoformat())

    if not replicas:
        return pl.DataFrame(
            schema={
                "database": pl.Utf8,
                "table": pl.Utf8,
                "is_leader": pl.Boolean,
                "is_readonly": pl.Boolean,
                "absolute_delay": pl.Int64,
                "queue_size": pl.Int64,
                "inserts_in_queue": pl.Int64,
                "merges_in_queue": pl.Int64,
                "total_replicas": pl.Int64,
                "active_replicas": pl.Int64,
                "parts_to_check": pl.Int64,
                "timestamp": pl.Utf8,
            }
        )

    records: list[dict[str, Any]] = []
    for r in replicas:
        records.append(
            {
                "database": str(r.get("database", database)),
                "table": str(r.get("table", "unknown")),
                "is_leader": bool(r.get("is_leader", False)),
                "is_readonly": bool(r.get("is_readonly", False)),
                "absolute_delay": _safe_int(r.get("absolute_delay", 0)),
                "queue_size": _safe_int(r.get("queue_size", 0)),
                "inserts_in_queue": _safe_int(r.get("inserts_in_queue", 0)),
                "merges_in_queue": _safe_int(r.get("merges_in_queue", 0)),
                "total_replicas": _safe_int(r.get("total_replicas", 0)),
                "active_replicas": _safe_int(r.get("active_replicas", 1)),
                "parts_to_check": _safe_int(r.get("parts_to_check", 0)),
                "timestamp": timestamp,
            }
        )

    return pl.DataFrame(records)


def export_replication_health_to_duckdb(
    report: ReplicationHealthReport | dict[str, Any] | None = None,
    db_path: str | Path = DEFAULT_REPLICATION_HEALTH_DB_PATH,
    database: str = DEFAULT_DATABASE,
) -> int:
    """Replikasyon durumunu DuckDB veritabanında kalıcı olarak saklar (GEMINI.md Kural 5).

    Args:
        report: İsteğe bağlı rapor nesnesi veya sözlüğü.
        db_path: DuckDB dosya yolu.
        database: Hedef veritabanı.

    Returns:
        int: Kaydedilen replika satır sayısı.
    """
    df = export_replicas_to_polars(report=report, database=database)
    if df.is_empty():
        return 0

    path_obj = Path(db_path)
    path_obj.parent.mkdir(parents=True, exist_ok=True)

    status_str = (
        report.status
        if isinstance(report, ReplicationHealthReport)
        else (report.get("status", "unknown") if isinstance(report, dict) else "unknown")
    )
    df = df.with_columns(pl.lit(status_str).alias("status"))

    con = duckdb.connect(str(path_obj))
    try:
        configure_duckdb_wal(con)
        con.execute(
            """
            CREATE TABLE IF NOT EXISTS replication_health_history (
                database VARCHAR,
                table_name VARCHAR,
                is_leader BOOLEAN,
                is_readonly BOOLEAN,
                absolute_delay BIGINT,
                queue_size BIGINT,
                inserts_in_queue BIGINT,
                merges_in_queue BIGINT,
                total_replicas BIGINT,
                active_replicas BIGINT,
                parts_to_check BIGINT,
                timestamp VARCHAR,
                status VARCHAR
            )
            """
        )
        con.register("df_temp", df)
        con.execute(
            """
            INSERT INTO replication_health_history
            SELECT
                database,
                "table" AS table_name,
                is_leader,
                is_readonly,
                absolute_delay,
                queue_size,
                inserts_in_queue,
                merges_in_queue,
                total_replicas,
                active_replicas,
                parts_to_check,
                timestamp,
                status
            FROM df_temp
            """
        )
        return len(df)
    finally:
        con.close()


def query_replication_health_from_duckdb(
    db_path: str | Path = DEFAULT_REPLICATION_HEALTH_DB_PATH,
    limit: int = 100,
    database: str | None = None,
) -> pl.DataFrame:
    """DuckDB'de saklanan replikasyon geçmişini Polars DataFrame olarak sorgular.

    Args:
        db_path: DuckDB dosya yolu.
        limit: Döndürülecek maksimum kayıt sayısı.
        database: İsteğe bağlı veritabanı filtresi.

    Returns:
        pl.DataFrame: Geçmiş kayıtları.
    """
    path_obj = Path(db_path)
    if not path_obj.exists():
        return pl.DataFrame()

    try:
        with duckdb.connect(str(path_obj), read_only=True) as con:
            table_check = con.execute(
                "SELECT count(*) FROM information_schema.tables WHERE table_name = 'replication_health_history'"
            ).fetchone()
            if not table_check or table_check[0] == 0:
                return pl.DataFrame()

            query = "SELECT * FROM replication_health_history"
            params: list[Any] = []
            if database:
                query += " WHERE database = ?"
                params.append(database)
            query += " ORDER BY timestamp DESC LIMIT ?"
            params.append(max(1, limit))

            arrow_table = con.execute(query, params).arrow()
            return pl.from_arrow(arrow_table)  # type: ignore[return-value]
    except Exception as exc:
        logger.warning("duckdb_replikasyon_sorgusu_basarisiz", hata=str(exc))
        return pl.DataFrame()


def read_replication_health_from_duckdb(
    db_path: str | Path = DEFAULT_REPLICATION_HEALTH_DB_PATH,
    database: str | None = None,
    limit: int = 100,
) -> pl.DataFrame:
    """DuckDB'de depolanan replikasyon geçmişini Polars DataFrame olarak okur."""
    return query_replication_health_from_duckdb(db_path=db_path, limit=limit, database=database)


def clear_replication_health_duckdb(
    db_path: str | Path = DEFAULT_REPLICATION_HEALTH_DB_PATH,
) -> None:
    """DuckDB'de depolanan replikasyon geçmişi tablosunu temizler.

    Args:
        db_path: DuckDB dosya yolu.
    """
    path_obj = Path(db_path)
    if not path_obj.exists():
        return
    try:
        with duckdb.connect(str(path_obj)) as con:
            configure_duckdb_wal(con)
            con.execute("DROP TABLE IF EXISTS replication_health_history;")
    except Exception as exc:
        logger.error("duckdb_replikasyon_temizleme_hatasi", db_path=str(db_path), hata=str(exc))


def export_replication_health_orjson(database: str = DEFAULT_DATABASE) -> bytes:
    """Replikasyon durumunu orjson ile yüksek hızlı ikili JSON baytlarına dönüştürür.

    Args:
        database: Hedef veritabanı.

    Returns:
        bytes: JSON formatında veri baytları.
    """
    health = check_replication_health(database=database)
    return orjson.dumps(health, option=orjson.OPT_INDENT_2)


# Modül Seviyesinde Kolaylık ve Takma Adlar (Convenience Aliases)
export_clickhouse_replication_prometheus = export_prometheus
export_clickhouse_replication_prometheus_async = export_prometheus_async
export_clickhouse_replicas_to_polars = export_replicas_to_polars
export_clickhouse_replication_to_duckdb = export_replication_health_to_duckdb
query_clickhouse_replication_from_duckdb = query_replication_health_from_duckdb

if __name__ == "__main__":
    _health = check_replication_health()
    logger.info("clickhouse_replikasyon_raporu", rapor=export_replication_health_orjson().decode("utf-8"))

__all__ = [
    "DEFAULT_CHECKPOINT_SIZE",
    "DEFAULT_DATABASE",
    "DEFAULT_MAX_ABSOLUTE_DELAY_SECONDS",
    "DEFAULT_MAX_QUEUE_SIZE",
    "DEFAULT_REPLICATION_HEALTH_DB_PATH",
    "DEFAULT_WAL_SIZE",
    "STATUS_PROMETHEUS_CODE_MAP",
    "VALID_HEALTH_STATUSES",
    "ReplicaHealthInfo",
    "ReplicationHealthReport",
    "check_replication_health",
    "check_replication_health_async",
    "clear_replication_health_duckdb",
    "configure_duckdb_wal",
    "export_clickhouse_replicas_to_polars",
    "export_clickhouse_replication_prometheus",
    "export_clickhouse_replication_prometheus_async",
    "export_clickhouse_replication_to_duckdb",
    "export_prometheus",
    "export_prometheus_async",
    "export_replicas_to_polars",
    "export_replication_health_orjson",
    "export_replication_health_to_duckdb",
    "get_replication_metrics",
    "get_replication_report_object",
    "is_replication_healthy",
    "is_replication_healthy_async",
    "query_clickhouse_replication_from_duckdb",
    "query_replication_health_from_duckdb",
    "read_replication_health_from_duckdb",
    "to_orjson_bytes",
]

