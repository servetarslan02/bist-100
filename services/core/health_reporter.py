"""
ALPHA BIST — Health Reporter v1.0

Periyodik sistem sağlık raporu üretir.
Tüm bileşenlerin durumunu tek bir raporda birleştirir.

Kullanım:
    from services.core.health_reporter import health_reporter

    report = await health_reporter.generate_report()
"""

import time
from datetime import UTC, datetime
from typing import Any

import structlog

logger = structlog.get_logger()


class HealthReporter:
    """Sistem sağlık raporlayıcı.

    Tüm bileşenlerin durumunu toplayıp
    tek bir rapor halinde sunar.
    """

    def __init__(self):
        self._last_report: dict | None = None
        self._report_history: list[dict] = []
        self._max_history = 100

    async def generate_report(
        self,
        clickhouse_client=None,
        pg_pool=None,
        redis_client=None,
    ) -> dict[str, Any]:
        """Tam sağlık raporu üret."""
        start_time = time.time()

        report = {
            "timestamp": datetime.now(UTC).isoformat(),
            "uptime": self._get_uptime(),
            "components": {},
            "overall_health": "HEALTHY",
            "issues": [],
        }

        # 1. Bağlantı durumu
        try:
            from .connectivity import connectivity_monitor
            report["components"]["connectivity"] = connectivity_monitor.get_status()
            if connectivity_monitor.is_offline:
                report["overall_health"] = "DEGRADED"
                report["issues"].append("İnternet bağlantısı yok")
        except Exception:
            report["components"]["connectivity"] = {"status": "unknown"}

        # 2. Downtime durumu
        try:
            from .downtime_tracker import downtime_tracker
            report["components"]["downtime"] = downtime_tracker.get_status()
            dt = downtime_tracker.get_downtime_seconds()
            if dt > 3600:
                report["issues"].append(f"Son downtime: {dt/3600:.1f} saat")
        except Exception:
            report["components"]["downtime"] = {"status": "unknown"}

        # 3. Veri bütünlüğü
        try:
            from .data_integrity import data_integrity_validator
            report["components"]["data_integrity"] = data_integrity_validator.get_status()
        except Exception:
            report["components"]["data_integrity"] = {"status": "unknown"}

        # 4. DLQ durumu
        try:
            from .persistent_dlq import persistent_dlq
            dlq_stats = await persistent_dlq.get_stats()
            report["components"]["dlq"] = dlq_stats
            pending = dlq_stats.get("total_entries", 0)
            if pending > 100:
                report["overall_health"] = "DEGRADED"
                report["issues"].append(f"DLQ: {pending} bekleyen event")
        except Exception:
            report["components"]["dlq"] = {"status": "unknown"}

        # 5. Offline queue durumu
        try:
            from .offline_queue import offline_queue
            oq_stats = await offline_queue.get_stats()
            report["components"]["offline_queue"] = oq_stats
            pending = oq_stats.get("pending_entries", 0)
            if pending > 0:
                report["issues"].append(f"Offline queue: {pending} bekleyen event")
        except Exception:
            report["components"]["offline_queue"] = {"status": "unknown"}

        # 6. Backfill durumu
        try:
            from ..ingestion.backfill import backfill_manager
            report["components"]["backfill"] = backfill_manager.get_stats()
        except Exception:
            report["components"]["backfill"] = {"status": "unknown"}

        # 7. PostgreSQL
        if pg_pool:
            try:
                async with pg_pool.acquire() as conn:
                    version = await conn.fetchval("SELECT version()")
                    report["components"]["postgresql"] = {
                        "connected": True,
                        "version": version[:50] if version else "unknown",
                    }
            except Exception as e:
                report["components"]["postgresql"] = {
                    "connected": False,
                    "error": str(e)[:100],
                }
                report["overall_health"] = "UNHEALTHY"
                report["issues"].append("PostgreSQL bağlantı hatası")

        # 8. ClickHouse
        if clickhouse_client:
            try:
                result = clickhouse_client.query("SELECT version()")
                report["components"]["clickhouse"] = {
                    "connected": True,
                    "version": result.result_rows[0][0] if result.result_rows else "unknown",
                }
            except Exception as e:
                report["components"]["clickhouse"] = {
                    "connected": False,
                    "error": str(e)[:100],
                }
                report["overall_health"] = "UNHEALTHY"
                report["issues"].append("ClickHouse bağlantı hatası")

        # 9. Redis
        if redis_client:
            try:
                pong = await redis_client.ping()
                info = await redis_client.info("memory")
                report["components"]["redis"] = {
                    "connected": pong,
                    "memory_used": info.get("used_memory_human", "unknown"),
                    "keys": await redis_client.dbsize(),
                }
            except Exception as e:
                report["components"]["redis"] = {
                    "connected": False,
                    "error": str(e)[:100],
                }

        # Overall health belirleme
        if report["overall_health"] == "HEALTHY" and report["issues"]:
            report["overall_health"] = "DEGRADED"

        duration = time.time() - start_time
        report["generation_duration_seconds"] = round(duration, 3)

        self._last_report = report
        self._report_history.append(report)
        if len(self._report_history) > self._max_history:
            self._report_history = self._report_history[-self._max_history:]

        return report

    def _get_uptime(self) -> dict[str, Any]:
        """Process uptime bilgisi."""
        try:
            import psutil
            proc = psutil.Process()
            uptime_seconds = time.time() - proc.create_time()
            return {
                "seconds": round(uptime_seconds, 1),
                "hours": round(uptime_seconds / 3600, 2),
                "days": round(uptime_seconds / 86400, 2),
            }
        except ImportError:
            return {"status": "psutil not installed"}

    def get_last_report(self) -> dict | None:
        """Son raporu döndür."""
        return self._last_report

    def get_history(self, limit: int = 10) -> list[dict]:
        """Rapor geçmişini döndür."""
        return self._report_history[-limit:]

    def get_summary(self) -> dict[str, Any]:
        """Özet bilgi."""
        if not self._last_report:
            return {"status": "no_report_yet"}

        return {
            "overall_health": self._last_report["overall_health"],
            "issues_count": len(self._last_report["issues"]),
            "issues": self._last_report["issues"],
            "timestamp": self._last_report["timestamp"],
        }


# Singleton
health_reporter = HealthReporter()
