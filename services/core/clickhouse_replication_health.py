"""ALPHA BIST — ClickHouse Replication Health Monitor

ReplicatedMergeTree tablolarının replikasyon durumunu kontrol eder.
Prometheus metrikleri olarak dışa aktarılabilir.

Kullanım:
    python -m services.core.clickhouse_replication_health
"""

import structlog

from .database import ch_execute

logger = structlog.get_logger()


def check_replication_health() -> dict:
    """ClickHouse replikasyon sağlık durumunu kontrol et."""
    health = {
        "status": "unknown",
        "replicas": [],
        "errors": [],
    }

    try:
        # system.replicas tablosundan replikasyon durumunu al
        result = ch_execute("""
            SELECT
                database,
                table,
                is_leader,
                is_readonly,
                absolute_delay,
                queue_size,
                inserts_in_queue,
                merges_in_queue,
                total_replicas
            FROM system.replicas
            WHERE database = 'alpha_bist'
            FORMAT TabSeparated
        """)

        if result.result_rows:
            for row in result.result_rows:
                replica_info = {
                    "database": row[0],
                    "table": row[1],
                    "is_leader": bool(row[2]),
                    "is_readonly": bool(row[3]),
                    "absolute_delay": int(row[4]),
                    "queue_size": int(row[5]),
                    "inserts_in_queue": int(row[6]),
                    "merges_in_queue": int(row[7]),
                    "total_replicas": int(row[8]),
                }
                health["replicas"].append(replica_info)

                # Uyarılar
                if replica_info["absolute_delay"] > 10:
                    health["errors"].append(
                        f"{replica_info['table']}: Replikasyon gecikmesi {replica_info['absolute_delay']}s"
                    )
                if replica_info["is_readonly"]:
                    health["errors"].append(
                        f"{replica_info['table']}: Salt-okunur modda"
                    )
                if replica_info["queue_size"] > 100:
                    health["errors"].append(
                        f"{replica_info['table']}: Kuyruk boyutu {replica_info['queue_size']}"
                    )

            if not health["errors"]:
                health["status"] = "healthy"
            else:
                health["status"] = "degraded"
        else:
            health["status"] = "no_replicas_found"

    except Exception as e:
        health["status"] = "error"
        health["errors"].append(str(e))
        logger.error("ClickHouse replication health check failed", error=str(e))

    return health


def get_replication_metrics() -> dict:
    """Prometheus formatında replikasyon metrikleri."""
    health = check_replication_health()

    metrics = {
        "clickhouse_replica_count": len(health["replicas"]),
        "clickhouse_replica_errors": len(health["errors"]),
    }

    for replica in health["replicas"]:
        table = replica["table"]
        metrics[f"clickhouse_replica_delay_{table}"] = replica["absolute_delay"]
        metrics[f"clickhouse_replica_queue_{table}"] = replica["queue_size"]
        metrics[f"clickhouse_replica_leader_{table}"] = 1 if replica["is_leader"] else 0

    return metrics


if __name__ == "__main__":
    import orjson
    health = check_replication_health()
    print(orjson.dumps(health, option=orjson.OPT_INDENT_2).decode())
