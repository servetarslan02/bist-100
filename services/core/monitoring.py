"""ALPHA BIST — Portföy ve Kilit İzleme Entegrasyonu (Portfolio & Lock Monitoring Integration).

Prometheus metrikleri, OTel izleme ve FastAPI uç noktaları için üretim gözlemlenebilirlik motoru.

Endpoints:
  GET /health/detailed     — Tam sistem sağlığı (portföy + kilitler + bileşenler)
  GET /metrics             — Prometheus metin formatında metrikler
  GET /admin/lock-metrics  — Veritabanı kilit performansı ve gecikme metrikleri
  GET /admin/portfolio     — Portföy muhasebesi, nakit ve bakiye durumu

Metrikler:
  lock_acquisition_total       — Counter
  lock_timeout_total           — Counter
  lock_deadlock_total          — Counter
  lock_renewal_total           — Counter
  lock_wait_seconds            — Histogram
  portfolio_equity             — Gauge
  portfolio_cash               — Gauge
  portfolio_positions_count    — Gauge
  portfolio_invariant_failures — Counter
"""

import asyncio
import functools
import time
from datetime import UTC, datetime
from typing import Any, Callable

import polars as pl
import structlog
from opentelemetry import trace

from .alerting import alerting
from .db_lock import get_all_metrics, get_health_report
from .observability import health_checker, prometheus_metrics

logger = structlog.get_logger(__name__)
tracer = trace.get_tracer("alpha-bist.monitoring")

DEFAULT_SYNC_INTERVAL_SECONDS: float = 5.0
PROMETHEUS_HISTOGRAM_BUCKETS: list[float] = [0.001, 0.005, 0.01, 0.05, 0.1, 0.5, 1.0, 5.0]


def otel_trace(span_name: str) -> Callable:
    """Belirtilen metodu OpenTelemetry span içine alan dekoratör.

    Args:
        span_name: Oluşturulacak span adı.

    Returns:
        Dekoratör sarmalayıcı fonksiyonu.
    """

    def decorator(func: Callable) -> Callable:
        """Hedef fonksiyonu sarmalayarak span yaşam döngüsünü yönetir."""
        if asyncio.iscoroutinefunction(func):

            @functools.wraps(func)
            async def async_wrapper(*args, **kwargs) -> Any:
                with tracer.start_as_current_span(span_name):
                    return await func(*args, **kwargs)

            return async_wrapper

        @functools.wraps(func)
        def sync_wrapper(*args, **kwargs) -> Any:
            with tracer.start_as_current_span(span_name):
                return func(*args, **kwargs)

        return sync_wrapper

    return decorator


class PortfolioMonitor:
    """Portföy ve kilit mekanizmalarının Prometheus ve API entegrasyonlu izleyicisi."""

    def __init__(self, sync_interval_seconds: float = DEFAULT_SYNC_INTERVAL_SECONDS) -> None:
        """PortfolioMonitor bileşenini başlatır.

        Args:
            sync_interval_seconds: Metrik senkronizasyonu arasındaki minimum süre (saniye).
        """
        self._portfolio_service: Any = None
        self._last_sync_time: float | None = None
        self._sync_interval_s: float = sync_interval_seconds
        self._invariant_failure_count: int = 0
        self._lock: asyncio.Lock = asyncio.Lock()

    @otel_trace("monitoring.bind")
    def bind(self, portfolio_service: Any) -> None:
        """Portföy servisini izleyiciye bağlar ve sağlık denetleyicisine kaydeder.

        Args:
            portfolio_service: İzlenecek ana portföy yönetim servisi örneği.
        """
        self._portfolio_service = portfolio_service
        health_checker.register("portfolio_locks")
        health_checker.register("portfolio_accounting")
        logger.info("Portföy izleme servisi bağlandı", servis=type(portfolio_service).__name__)

    @otel_trace("monitoring.sync_metrics")
    async def sync_metrics(self) -> None:
        """Portföy metriklerini ve kilit telemetrisini Prometheus gauge'larına senkronize eder."""
        now = time.time()
        if self._last_sync_time and (now - self._last_sync_time) < self._sync_interval_s:
            return

        async with self._lock:
            # Kilitten sonra tekrar kontrol et (double-checked locking)
            now = time.time()
            if self._last_sync_time and (now - self._last_sync_time) < self._sync_interval_s:
                return

            try:
                from services.paper_trading.paper_orchestrator import paper_orchestrator

                summary = paper_orchestrator.portfolio.get_summary()

                # Portföy Göstergeleri (Gauges)
                prometheus_metrics.set_gauge("portfolio_equity", summary.get("total_value", 0.0))
                prometheus_metrics.set_gauge("portfolio_cash", summary.get("cash", 0.0))
                prometheus_metrics.set_gauge("portfolio_positions_count", summary.get("num_positions", 0))
                prometheus_metrics.set_gauge("portfolio_unrealized_pnl", summary.get("unrealized_pnl", 0.0))
                prometheus_metrics.set_gauge("portfolio_realized_pnl", summary.get("total_pnl", 0.0))
                prometheus_metrics.set_gauge("portfolio_commission_total", summary.get("total_commission", 0.0))
                prometheus_metrics.set_gauge("portfolio_drawdown_pct", summary.get("max_drawdown_pct", 0.0))

                # Muhasebe Invariant Kontrolü: Equity == Cash + Invested
                total_val = float(summary.get("total_value", 0.0))
                cash_val = float(summary.get("cash", 0.0))
                invested_val = float(summary.get("invested_value", 0.0))

                invariant_ok = abs(total_val - (cash_val + invested_val)) < 1.0
                if not invariant_ok:
                    self._invariant_failure_count += 1
                    prometheus_metrics.inc("portfolio_invariant_failures")
                    alerting.check_invariant(
                        False,
                        {"equity": total_val, "cash": cash_val, "invested": invested_val},
                    )

                # Negatif Nakit Kontrolü
                if cash_val < 0.0:
                    alerting.check_negative_cash(cash_val)

                # Düşüş (Drawdown) Kontrolü
                drawdown = summary.get("max_drawdown_pct", 0.0)
                if drawdown:
                    alerting.check_drawdown(drawdown)

                # Kilit (Lock) Metrikleri
                lock_metrics = get_all_metrics()
                for key, m in lock_metrics.items():
                    prometheus_metrics.set_gauge(
                        "lock_acquisition_total",
                        m.get("total_acquisitions", 0),
                        {"key": key},
                    )
                    prometheus_metrics.set_gauge(
                        "lock_wait_seconds",
                        m.get("avg_wait_ms", 0.0) / 1000.0,
                        {"key": key},
                    )
                alerting.check_lock_metrics(lock_metrics)

                self._last_sync_time = now

            except Exception as e:
                logger.warning("Portföy metrik senkronizasyonu başarısız", hata=str(e))

    @otel_trace("monitoring.get_health_detailed")
    async def get_health_detailed(self) -> dict[str, Any]:
        """Ayrıntılı sistem sağlığı raporu üretir.

        Returns:
            Kilit, portföy, bileşenler ve uyarı durumlarını içeren sözlük.
        """
        await self.sync_metrics()

        lock_health = get_health_report()
        portfolio_health: dict[str, Any] = {"status": "UNKNOWN", "issues": []}

        if self._portfolio_service:
            try:
                portfolio_health = self._portfolio_service.get_health_status()
            except Exception as e:
                portfolio_health = {"status": "UNHEALTHY", "issues": [str(e)]}

        # Genel Durum Değerlendirmesi
        statuses = [
            lock_health.get("overall_status", "UNKNOWN"),
            portfolio_health.get("status", "UNKNOWN"),
        ]

        if "UNHEALTHY" in statuses:
            overall = "UNHEALTHY"
        elif "DEGRADED" in statuses:
            overall = "DEGRADED"
        else:
            overall = "HEALTHY"

        # Sağlık Denetleyicisi Bileşenlerini Güncelle
        lock_status = lock_health.get("overall_status", "UNKNOWN")
        health_checker.update_status("portfolio_locks", lock_status, f"Kilit durumu: {lock_status}")

        acc_status = "HEALTHY"
        if portfolio_health.get("portfolio", {}).get("invariant_check") is False:
            acc_status = "FAILED"
            overall = "UNHEALTHY"
        health_checker.update_status(
            "portfolio_accounting",
            acc_status,
            f"Muhasebe Invariant: {'OK' if acc_status == 'HEALTHY' else 'FAILED'}",
        )

        # Alarm Kontrolü
        alerting.check_health({"status": overall, "issues": []})

        return {
            "status": overall,
            "timestamp": datetime.now(UTC).isoformat(),
            "portfolio": portfolio_health,
            "locks": lock_health,
            "components": health_checker.check_all().get("components", {}),
            "alerts": alerting.get_alert_summary(),
        }

    @staticmethod
    def _parse_metric_name(raw_name: str) -> tuple[str, str]:
        """Prometheus metrik adı ve etiket dizesini ayrıştırır.

        Args:
            raw_name: Örn. 'lock_wait_seconds{key="orders"}'

        Returns:
            (base_name, labels_content) demeti.
        """
        if "{" in raw_name and raw_name.endswith("}"):
            idx = raw_name.index("{")
            base = raw_name[:idx].strip()
            labels = raw_name[idx + 1 : -1].strip()
            return base, labels
        return raw_name.strip(), ""

    @otel_trace("monitoring.get_prometheus_text")
    async def get_prometheus_text(self) -> str:
        """Prometheus metin formatında tüm telemetriyi dışa aktarır.

        Returns:
            Prometheus uyumlu metrik metni.
        """
        await self.sync_metrics()

        lines: list[str] = []
        metrics = prometheus_metrics.get_metrics()

        # Sayaçlar (Counters)
        for name, value in metrics.get("counters", {}).items():
            base_name, _ = self._parse_metric_name(name)
            lines.append(f"# TYPE {base_name} counter")
            lines.append(f"{name} {value}")

        # Göstergeler (Gauges)
        for name, value in metrics.get("gauges", {}).items():
            base_name, _ = self._parse_metric_name(name)
            lines.append(f"# TYPE {base_name} gauge")
            lines.append(f"{name} {value}")

        # Histogramlar (Histograms)
        for name, stats in metrics.get("histograms", {}).items():
            base_name, labels = self._parse_metric_name(name)
            lines.append(f"# TYPE {base_name} histogram")

            label_str = f"{{{labels}}}" if labels else ""
            prefix = f"{labels}," if labels else ""

            lines.append(f"{base_name}_count{label_str} {stats.get('count', 0)}")
            lines.append(f"{base_name}_sum{label_str} {stats.get('sum', 0.0):.6f}")

            for bucket in PROMETHEUS_HISTOGRAM_BUCKETS:
                count = sum(1 for v in [stats.get("p50", 0.0)] if v <= bucket)
                lines.append(f'{base_name}_bucket{{{prefix}le="{bucket}"}} {count}')
            lines.append(f'{base_name}_bucket{{{prefix}le="+Inf"}} {stats.get("count", 0)}')

        return "\n".join(lines) + "\n"

    @otel_trace("monitoring.get_lock_metrics_api")
    async def get_lock_metrics_api(self) -> dict[str, Any]:
        """Kilit performans metriklerini API yanıtı olarak döndürür."""
        metrics = get_all_metrics()
        health = get_health_report()
        return {
            "metrics": metrics,
            "health": health,
            "timestamp": datetime.now(UTC).isoformat(),
        }

    @otel_trace("monitoring.get_portfolio_api")
    async def get_portfolio_api(self) -> dict[str, Any]:
        """Portföy ve muhasebe durumunu API yanıtı olarak döndürür."""
        try:
            from services.paper_trading.paper_orchestrator import paper_orchestrator

            summary = paper_orchestrator.portfolio.get_summary()
            return {
                "status": "HEALTHY",
                "portfolio": summary,
                "accounting": {
                    "cash": summary.get("cash", 0.0),
                    "settled_cash": summary.get("settled_cash", 0.0),
                    "unsettled_t1": summary.get("unsettled_cash_t1", 0.0),
                    "unsettled_t2": summary.get("unsettled_cash_t2", 0.0),
                    "invested_value": summary.get("invested_value", 0.0),
                    "total_value": summary.get("total_value", 0.0),
                },
                "engine": "PaperTradingOrchestrator_SingleSource",
                "timestamp": datetime.now(UTC).isoformat(),
            }
        except Exception as e:
            logger.error("Portföy API özeti alınamadı", hata=str(e), exc_info=True)
            return {
                "status": "ERROR",
                "error": str(e),
                "timestamp": datetime.now(UTC).isoformat(),
            }

    def export_metrics_to_polars(self) -> pl.DataFrame:
        """Güncel Prometheus metriklerini Polars DataFrame olarak dışa aktarır."""
        raw_metrics = prometheus_metrics.get_metrics()
        records: list[dict[str, Any]] = []

        now_str = datetime.now(UTC).isoformat()
        for name, value in raw_metrics.get("counters", {}).items():
            base, labels = self._parse_metric_name(name)
            records.append(
                {
                    "metric_type": "counter",
                    "name": base,
                    "labels": labels,
                    "value": float(value),
                    "timestamp": now_str,
                }
            )

        for name, value in raw_metrics.get("gauges", {}).items():
            base, labels = self._parse_metric_name(name)
            records.append(
                {
                    "metric_type": "gauge",
                    "name": base,
                    "labels": labels,
                    "value": float(value),
                    "timestamp": now_str,
                }
            )

        if not records:
            return pl.DataFrame(
                schema={
                    "metric_type": pl.Utf8,
                    "name": pl.Utf8,
                    "labels": pl.Utf8,
                    "value": pl.Float64,
                    "timestamp": pl.Utf8,
                }
            )

        return pl.DataFrame(records)

    def __repr__(self) -> str:
        """Portföy izleyicisinin durumunu özetleyen temsil."""
        return (
            f"PortfolioMonitor(sync_interval={self._sync_interval_s}s, "
            f"last_sync={self._last_sync_time}, invariant_failures={self._invariant_failure_count})"
        )


# Singleton Örneği
portfolio_monitor: PortfolioMonitor = PortfolioMonitor()

__all__ = [
    "DEFAULT_SYNC_INTERVAL_SECONDS",
    "PROMETHEUS_HISTOGRAM_BUCKETS",
    "PortfolioMonitor",
    "otel_trace",
    "portfolio_monitor",
]
