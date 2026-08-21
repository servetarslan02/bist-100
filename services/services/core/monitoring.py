"""
ALPHA BIST — Portfolio & Lock Monitoring Integration

Prometheus metrics + FastAPI endpoints for production observability.

Endpoints:
  GET /health/detailed     — Full system health (portfolio + locks)
  GET /metrics             — Prometheus format metrics
  GET /admin/lock-metrics  — Lock performance metrics
  GET /admin/portfolio     — Portfolio health + accounting

Metrics:
  lock_acquisition_total      — Counter
  lock_timeout_total          — Counter
  lock_deadlock_total         — Counter
  lock_renewal_total          — Counter
  lock_wait_seconds           — Histogram
  portfolio_equity            — Gauge
  portfolio_cash              — Gauge
  portfolio_positions_count   — Gauge
  portfolio_invariant_failures — Counter
"""

import time
from typing import Dict, Any, Optional
from datetime import datetime, timezone
import structlog

from .db_lock import get_all_metrics, get_health_report, get_lock_metrics
from .observability import prometheus_metrics, health_checker
from .alerting import alerting

logger = structlog.get_logger()


class PortfolioMonitor:
    """Portfolio ve lock monitoring — Prometheus + API integration."""

    def __init__(self):
        self._portfolio_service = None
        self._last_sync_time: Optional[float] = None
        self._sync_interval_s = 5.0  # 5 saniyede bir metrik güncelle
        self._invariant_failure_count = 0

    def bind(self, portfolio_service):
        """PortfolioService'i monitor'a bağla."""
        self._portfolio_service = portfolio_service
        health_checker.register("portfolio_locks")
        health_checker.register("portfolio_accounting")
        logger.info("Portfolio monitor bound to service")

    async def sync_metrics(self):
        """Portfolio metriklerini Prometheus gauge'larına yaz."""
        if not self._portfolio_service:
            return

        now = time.time()
        if self._last_sync_time and (now - self._last_sync_time) < self._sync_interval_s:
            return

        try:
            pf = await self._portfolio_service.get_portfolio()
            acc = await self._portfolio_service.get_accounting()

            # Portfolio gauges
            prometheus_metrics.set_gauge("portfolio_equity", pf.get("total_value", 0))
            prometheus_metrics.set_gauge("portfolio_cash", pf.get("cash", 0))
            prometheus_metrics.set_gauge("portfolio_positions_count", pf.get("positions_count", 0))
            prometheus_metrics.set_gauge("portfolio_unrealized_pnl", pf.get("unrealized_pnl", 0))
            prometheus_metrics.set_gauge("portfolio_realized_pnl", acc.get("realized_pnl_total", 0))
            prometheus_metrics.set_gauge("portfolio_commission_total", acc.get("commission_total", 0))
            prometheus_metrics.set_gauge("portfolio_drawdown_pct", acc.get("drawdown_pct", 0))

            # Invariant check
            if not acc.get("invariant_check", True):
                self._invariant_failure_count += 1
                prometheus_metrics.inc("portfolio_invariant_failures")
                alerting.check_invariant(False, {"equity": pf.get("total_value"), "cash": pf.get("cash")})

            # Negative cash check
            if pf.get("cash", 0) < 0:
                alerting.check_negative_cash(pf["cash"])

            # Drawdown check
            drawdown = acc.get("drawdown_pct", 0)
            if drawdown:
                alerting.check_drawdown(drawdown)

            # Lock metrics
            lock_metrics = get_all_metrics()
            for key, m in lock_metrics.items():
                prometheus_metrics.inc(f"lock_acquisition_total", m.get("total_acquisitions", 0), {"key": key})
                prometheus_metrics.set_gauge(f"lock_wait_seconds", m.get("avg_wait_ms", 0) / 1000, {"key": key})
            alerting.check_lock_metrics(lock_metrics)

            self._last_sync_time = now

        except Exception as e:
            logger.warning("Metrics sync failed", error=str(e))

    async def get_health_detailed(self) -> Dict[str, Any]:
        """Detaylı sağlık raporu (API endpoint için)."""
        await self.sync_metrics()

        lock_health = get_health_report()

        portfolio_health = {"status": "UNKNOWN", "issues": []}
        if self._portfolio_service:
            try:
                portfolio_health = self._portfolio_service.get_health_status()
            except Exception as e:
                portfolio_health = {"status": "UNHEALTHY", "issues": [str(e)]}

        # Genel durum
        statuses = [lock_health.get("overall_status", "UNKNOWN"),
                    portfolio_health.get("status", "UNKNOWN")]

        if "UNHEALTHY" in statuses:
            overall = "UNHEALTHY"
        elif "DEGRADED" in statuses:
            overall = "DEGRADED"
        else:
            overall = "HEALTHY"

        # Health checker bileşenlerini güncelle
        lock_status = lock_health.get("overall_status", "UNKNOWN")
        health_checker.update_status("portfolio_locks", lock_status,
                                     f"Lock status: {lock_status}")

        acc_status = "HEALTHY"
        if portfolio_health.get("portfolio", {}).get("invariant_check") is False:
            acc_status = "FAILED"
            overall = "UNHEALTHY"
        health_checker.update_status("portfolio_accounting", acc_status,
                                     f"Invariant: {'OK' if acc_status == 'HEALTHY' else 'FAILED'}")

        # Alert kontrolü
        alerting.check_health({"status": overall, "issues": []})

        return {
            "status": overall,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "portfolio": portfolio_health,
            "locks": lock_health,
            "components": health_checker.check_all().get("components", {}),
            "alerts": alerting.get_alert_summary(),
        }

    async def get_prometheus_text(self) -> str:
        """Prometheus text formatında metrics export."""
        await self.sync_metrics()

        lines = []
        metrics = prometheus_metrics.get_metrics()

        # Counters
        for name, value in metrics.get("counters", {}).items():
            clean_name = name.split("{")[0]
            labels = ""
            if "{" in name:
                labels = name[name.index("{"):]
            lines.append(f"# TYPE {clean_name} counter")
            lines.append(f"{name} {value}")

        # Gauges
        for name, value in metrics.get("gauges", {}).items():
            clean_name = name.split("{")[0]
            lines.append(f"# TYPE {clean_name} gauge")
            lines.append(f"{name} {value}")

        # Histograms
        for name, stats in metrics.get("histograms", {}).items():
            clean_name = name.split("{")[0]
            lines.append(f"# TYPE {clean_name} histogram")
            lines.append(f"{name}_count {stats['count']}")
            lines.append(f"{name}_sum {stats['sum']:.6f}")
            for bucket in [0.001, 0.005, 0.01, 0.05, 0.1, 0.5, 1.0, 5.0]:
                count = sum(1 for v in [stats.get("p50", 0)] if v <= bucket)
                lines.append(f"{name}_bucket{{le=\"{bucket}\"}} {count}")

        return "\n".join(lines) + "\n"

    async def get_lock_metrics_api(self) -> Dict[str, Any]:
        """Lock metrikleri (API endpoint)."""
        metrics = get_all_metrics()
        health = get_health_report()
        return {
            "metrics": metrics,
            "health": health,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    async def get_portfolio_api(self) -> Dict[str, Any]:
        """Portfolio durumu (API endpoint)."""
        if not self._portfolio_service:
            return {"error": "Portfolio service not bound"}

        try:
            pf = await self._portfolio_service.get_portfolio()
            acc = await self._portfolio_service.get_accounting()
            health = self._portfolio_service.get_health_status()
            lock_m = self._portfolio_service.get_lock_metrics()

            return {
                "portfolio": pf,
                "accounting": acc,
                "health": health,
                "lock_metrics": lock_m,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
        except Exception as e:
            return {"error": str(e)}


# Singleton
portfolio_monitor = PortfolioMonitor()
