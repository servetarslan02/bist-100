"""ALPHA BIST — PostgreSQL Replication Health Monitor

Streaming replication durumunu kontrol eder.
Primary ve Replica arasındaki lag'i ölçer.

Kullanım:
    python -m services.core.pg_replication_health
"""

import structlog
from .database import get_pg_pool, get_pg_replica_pool

logger = structlog.get_logger()


async def check_replication_health() -> dict:
    """PostgreSQL replikasyon sağlık durumunu kontrol et."""
    health = {
        "primary": {"status": "unknown"},
        "replica": {"status": "unknown"},
        "lag_bytes": None,
        "lag_seconds": None,
        "errors": [],
    }

    # Primary durumu
    try:
        pool = await get_pg_pool()
        async with pool.acquire() as conn:
            # Primary'den replikasyon durumunu al
            row = await conn.fetchrow("""
                SELECT
                    client_addr,
                    state,
                    sent_lsn,
                    write_lsn,
                    flush_lsn,
                    replay_lsn,
                    pg_wal_lsn_diff(sent_lsn, replay_lsn) AS lag_bytes
                FROM pg_stat_replication
                LIMIT 1
            """)

            if row:
                health["primary"]["status"] = "streaming"
                health["primary"]["replica_addr"] = str(row["client_addr"])
                health["primary"]["state"] = row["state"]
                health["lag_bytes"] = int(row["lag_bytes"]) if row["lag_bytes"] else 0

                # Uyarılar
                if health["lag_bytes"] and health["lag_bytes"] > 1048576:  # 1MB
                    health["errors"].append(
                        f"Replikasyon lag: {health['lag_bytes'] / 1048576:.1f} MB"
                    )
            else:
                health["primary"]["status"] = "no_replica_connected"
                health["errors"].append("Replica bağlı değil")

    except Exception as e:
        health["primary"]["status"] = "error"
        health["errors"].append(f"Primary check failed: {str(e)[:100]}")

    # Replica durumu
    try:
        replica_pool = await get_pg_replica_pool()
        async with replica_pool.acquire() as conn:
            # Replica'nın recovery modunda olup olmadığını kontrol et
            is_recovery = await conn.fetchval("SELECT pg_is_in_recovery()")

            if is_recovery:
                health["replica"]["status"] = "in_recovery"

                # Replica lag'i (saniye)
                lag = await conn.fetchval("""
                    SELECT EXTRACT(EPOCH FROM (now() - pg_last_xact_replay_timestamp()))
                """)
                health["lag_seconds"] = round(float(lag), 2) if lag else 0

                if health["lag_seconds"] and health["lag_seconds"] > 60:
                    health["errors"].append(
                        f"Replica lag: {health['lag_seconds']}s"
                    )
            else:
                health["replica"]["status"] = "not_in_recovery"
                health["errors"].append("Replica recovery modunda değil")

    except Exception as e:
        health["replica"]["status"] = "error"
        health["errors"].append(f"Replica check failed: {str(e)[:100]}")

    # Genel durum
    if not health["errors"]:
        health["status"] = "healthy"
    else:
        health["status"] = "degraded"

    return health


async def get_replication_metrics() -> dict:
    """Prometheus formatında replikasyon metrikleri."""
    health = await check_replication_health()

    metrics = {
        "pg_replica_lag_bytes": health.get("lag_bytes", 0) or 0,
        "pg_replica_lag_seconds": health.get("lag_seconds", 0) or 0,
        "pg_replica_connected": 1 if health["primary"].get("state") == "streaming" else 0,
    }

    return metrics


if __name__ == "__main__":
    import asyncio
    import orjson

    async def main():
        health = await check_replication_health()
        print(orjson.dumps(health, option=orjson.OPT_INDENT_2).decode())

    asyncio.run(main())
