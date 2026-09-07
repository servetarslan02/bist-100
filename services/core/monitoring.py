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

from __future__ import annotations

import asyncio
import contextlib
import functools
import time
from datetime import UTC, datetime
from typing import Any, Callable, Final

import orjson
import polars as pl
import structlog

from .alerting import alerting
from .db_lock import get_all_metrics, get_health_report
from .observability import health_checker, prometheus_metrics

try:
    from services.core.otel import otel_trace
except ImportError:
    try:
        from opentelemetry import trace
        tracer = trace.get_tracer("alpha-bist.monitoring")

        def otel_trace(span_name: str) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
            def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
                if asyncio.iscoroutinefunction(func):
                    @functools.wraps(func)
                    async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
                        with tracer.start_as_current_span(span_name):
                            return await func(*args, **kwargs)
                    return async_wrapper

                @functools.wraps(func)
                def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
                    with tracer.start_as_current_span(span_name):
                        return func(*args, **kwargs)
                return sync_wrapper
            return decorator
    except ImportError:
        def otel_trace(span_name: str) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
            def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
                return func
            return decorator

logger = structlog.get_logger(__name__)

DEFAULT_SYNC_INTERVAL_SECONDS: Final[float] = 5.0
PROMETHEUS_HISTOGRAM_BUCKETS: Final[list[float]] = [0.001, 0.005, 0.01, 0.05, 0.1, 0.5, 1.0, 5.0]


def _extract_metric_value(val: Any) -> float:
    """Prometheus Counter/Gauge nesnesinden veya ilkel sayısal tipten güvenli float değer ayıklar."""
    if isinstance(val, (int, float)):
        return float(val)
    if hasattr(val, "_value"):
        with contextlib.suppress(Exception):
            return float(val._value.get())
    if hasattr(val, "collect"):
        with contextlib.suppress(Exception):
            collected = val.collect()
            if collected and collected[0].samples:
                return float(collected[0].samples[0].value)
    try:
        return float(val)
    except (ValueError, TypeError):
        return 0.0


class PortfolioMonitor:
    """Portföy ve kilit mekanizmalarının Prometheus ve API entegrasyonlu izleyicisi."""

    def __init__(self, sync_interval_seconds: float = DEFAULT_SYNC_INTERVAL_SECONDS) -> None:
        """PortfolioMonitor bileşenini başlatır.

        Args:
            sync_interval_seconds: Metrik senkronizasyonu arasındaki minimum süre (saniye).
        """
        self._portfolio_service: Any = None
        self._last_sync_time: float | None = None
        self._sync_interval_s: float = max(0.1, float(sync_interval_seconds))
        self._invariant_failure_count: int = 0
        self._lock: asyncio.Lock | None = None

    def _get_lock(self) -> asyncio.Lock:
        """Asenkron kilit nesnesini gerektiğinde (lazy) oluşturur ve döndürür."""
        if self._lock is None:
            self._lock = asyncio.Lock()
        return self._lock

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

        async with self._get_lock():
            # Çift kilit kontrolü (double-checked locking)
            now = time.time()
            if self._last_sync_time and (now - self._last_sync_time) < self._sync_interval_s:
                return
            self._last_sync_time = now

            try:
                summary: dict[str, Any] = {}
                if self._portfolio_service and hasattr(self._portfolio_service, "get_summary"):
                    summary = self._portfolio_service.get_summary()
                elif self._portfolio_service and hasattr(self._portfolio_service, "portfolio"):
                    summary = self._portfolio_service.portfolio.get_summary()
                else:
                    with contextlib.suppress(Exception):
                        from services.paper_trading.paper_orchestrator import paper_orchestrator
                        summary = paper_orchestrator.portfolio.get_summary()

                # Portföy Göstergeleri (Gauges) — None korumalı float dönüşümü
                prometheus_metrics.set_gauge("portfolio_equity", float(summary.get("total_value") or 0.0))
                prometheus_metrics.set_gauge("portfolio_cash", float(summary.get("cash") or 0.0))
                prometheus_metrics.set_gauge("portfolio_positions_count", int(summary.get("num_positions") or 0))
                prometheus_metrics.set_gauge("portfolio_unrealized_pnl", float(summary.get("unrealized_pnl") or 0.0))
                prometheus_metrics.set_gauge("portfolio_realized_pnl", float(summary.get("total_pnl") or 0.0))
                prometheus_metrics.set_gauge(
                    "portfolio_commission_total", float(summary.get("total_commission") or 0.0)
                )
                prometheus_metrics.set_gauge("portfolio_drawdown_pct", float(summary.get("max_drawdown_pct") or 0.0))

                # Muhasebe Invariant Kontrolü: Equity == Cash + Invested
                total_val = float(summary.get("total_value") or 0.0)
                cash_val = float(summary.get("cash") or 0.0)
                invested_val = float(summary.get("invested_value") or 0.0)

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
                drawdown = float(summary.get("max_drawdown_pct") or 0.0)
                if drawdown > 0.0:
                    alerting.check_drawdown(drawdown)

                # Kilit (Lock) Metrikleri
                lock_metrics = get_all_metrics()
                for key, m in lock_metrics.items():
                    prometheus_metrics.set_gauge(
                        "lock_acquisition_total",
                        int(m.get("total_acquisitions") or 0),
                        {"key": key},
                    )
                    prometheus_metrics.set_gauge(
                        "lock_wait_seconds",
                        float(m.get("avg_wait_ms") or 0.0) / 1000.0,
                        {"key": key},
                    )
                alerting.check_lock_metrics(lock_metrics)

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
            lines.append(f"{name} {_extract_metric_value(value)}")

        # Göstergeler (Gauges)
        for name, value in metrics.get("gauges", {}).items():
            base_name, _ = self._parse_metric_name(name)
            lines.append(f"# TYPE {base_name} gauge")
            lines.append(f"{name} {_extract_metric_value(value)}")

        # Histogramlar (Histograms)
        for name, stats in metrics.get("histograms", {}).items():
            base_name, labels = self._parse_metric_name(name)
            lines.append(f"# TYPE {base_name} histogram")

            label_str = f"{{{labels}}}" if labels else ""
            prefix = f"{labels}," if labels else ""

            count_val = stats.get("count", 0)
            sum_val = float(stats.get("sum", 0.0))
            samples = stats.get("samples")

            lines.append(f"{base_name}_count{label_str} {count_val}")
            lines.append(f"{base_name}_sum{label_str} {sum_val:.6f}")

            for bucket in PROMETHEUS_HISTOGRAM_BUCKETS:
                if samples and isinstance(samples, list):
                    b_count = sum(1 for v in samples if v <= bucket)
                else:
                    b_count = sum(1 for v in [float(stats.get("p50", 0.0))] if v <= bucket)
                lines.append(f'{base_name}_bucket{{{prefix}le="{bucket}"}} {b_count}')
            lines.append(f'{base_name}_bucket{{{prefix}le="+Inf"}} {count_val}')

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
            summary: dict[str, Any] = {}
            if self._portfolio_service and hasattr(self._portfolio_service, "get_summary"):
                summary = self._portfolio_service.get_summary()
            elif self._portfolio_service and hasattr(self._portfolio_service, "portfolio"):
                summary = self._portfolio_service.portfolio.get_summary()
            else:
                from services.paper_trading.paper_orchestrator import paper_orchestrator
                summary = paper_orchestrator.portfolio.get_summary()
            return {
                "status": "HEALTHY",
                "portfolio": summary,
                "accounting": {
                    "cash": float(summary.get("cash") or 0.0),
                    "settled_cash": float(summary.get("settled_cash") or 0.0),
                    "unsettled_t1": float(summary.get("unsettled_cash_t1") or 0.0),
                    "unsettled_t2": float(summary.get("unsettled_cash_t2") or 0.0),
                    "invested_value": float(summary.get("invested_value") or 0.0),
                    "total_value": float(summary.get("total_value") or 0.0),
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
        """Güncel Prometheus metriklerini (Sayaçlar, Göstergeler, Histogramlar) Polars DataFrame olarak dışa aktarır."""
        raw_metrics = prometheus_metrics.get_metrics()
        records: list[dict[str, Any]] = []

        now_str = datetime.now(UTC).isoformat()
        for name, value in raw_metrics.get("counters", {}).items():
            base, labels = self._parse_metric_name(name)
            records.append({
                "metric_type": "counter",
                "name": base,
                "labels": labels,
                "value": _extract_metric_value(value),
                "timestamp": now_str,
            })

        for name, value in raw_metrics.get("gauges", {}).items():
            base, labels = self._parse_metric_name(name)
            records.append({
                "metric_type": "gauge",
                "name": base,
                "labels": labels,
                "value": _extract_metric_value(value),
                "timestamp": now_str,
            })

        for name, stats in raw_metrics.get("histograms", {}).items():
            base, labels = self._parse_metric_name(name)
            records.append({
                "metric_type": "histogram_count",
                "name": f"{base}_count",
                "labels": labels,
                "value": float(stats.get("count", 0)),
                "timestamp": now_str,
            })
            records.append({
                "metric_type": "histogram_p50",
                "name": f"{base}_p50",
                "labels": labels,
                "value": float(stats.get("p50", 0.0)),
                "timestamp": now_str,
            })

        if not records:
            return pl.DataFrame(schema={
                "metric_type": pl.String,
                "name": pl.String,
                "labels": pl.String,
                "value": pl.Float64,
                "timestamp": pl.String,
            })

        return pl.DataFrame(records)

    @staticmethod
    def export_lock_metrics_to_polars() -> pl.DataFrame:
        """Veritabanı ve dağıtık kilit performans telemetrisini Polars DataFrame olarak dışa aktarır."""
        lock_metrics = get_all_metrics()
        records: list[dict[str, Any]] = []
        now_str = datetime.now(UTC).isoformat()
        for key, data in lock_metrics.items():
            records.append({
                "lock_key": str(key),
                "total_acquisitions": int(data.get("total_acquisitions") or 0),
                "total_timeouts": int(data.get("total_timeouts") or 0),
                "avg_wait_ms": float(data.get("avg_wait_ms") or 0.0),
                "max_wait_ms": float(data.get("max_wait_ms") or 0.0),
                "timestamp": now_str,
            })
        if not records:
            return pl.DataFrame(schema={
                "lock_key": pl.String,
                "total_acquisitions": pl.Int64,
                "total_timeouts": pl.Int64,
                "avg_wait_ms": pl.Float64,
                "max_wait_ms": pl.Float64,
                "timestamp": pl.String,
            })
        return pl.DataFrame(records)

    def to_orjson_bytes(self) -> bytes:
        """İzleme metriklerini orjson serileştirilmiş ikili bayt dizisi olarak döndürür (GEMINI.md Kural 5)."""
        df = self.export_metrics_to_polars()
        return orjson.dumps(df.to_dicts(), default=str)

    def __repr__(self) -> str:
        """Portföy izleyicisinin durumunu özetleyen temsil."""
        return (
            f"PortfolioMonitor(sync_interval={self._sync_interval_s}s, "
            f"last_sync={self._last_sync_time}, invariant_failures={self._invariant_failure_count})"
        )


# Singleton Örneği ve kolaylık fonksiyonları
portfolio_monitor: Final[PortfolioMonitor] = PortfolioMonitor()
export_metrics_to_polars = portfolio_monitor.export_metrics_to_polars
export_lock_metrics_to_polars = portfolio_monitor.export_lock_metrics_to_polars


def export_metrics_to_orjson_bytes() -> bytes:
    """Metrikleri orjson serileştirilmiş ikili bayt dizisi olarak döndürür."""
    return portfolio_monitor.to_orjson_bytes()


def export_lock_metrics_to_orjson_bytes() -> bytes:
    """Kilit telemetrisini orjson serileştirilmiş ikili bayt dizisi olarak döndürür."""
    df = PortfolioMonitor.export_lock_metrics_to_polars()
    return orjson.dumps(df.to_dicts(), default=str)


def export_monitoring_metrics_to_duckdb(
    db_path: str = "data/monitoring_metrics.duckdb",
) -> int:
    """Portföy ve kilit telemetri metriklerini yerel DuckDB tablosuna anlık görüntü olarak kaydeder.

    Args:
        db_path: DuckDB veritabanı dosya yolu.

    Returns:
        Toplam kaydedilen telemetri satırı sayısı.
    """
    from pathlib import Path

    import duckdb

    df_metrics = export_metrics_to_polars()
    df_locks = export_lock_metrics_to_polars()
    target = Path(db_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists() and target.stat().st_size == 0:
        with contextlib.suppress(OSError):
            target.unlink()

    total_records = 0
    with duckdb.connect(db_path) as conn:
        conn.execute("PRAGMA checkpoint_threshold='4MB'")
        conn.execute("PRAGMA wal_autocheckpoint='2MB'")
        if df_metrics.height > 0:
            conn.register("df_mon_view", df_metrics.to_arrow())
            try:
                conn.execute(
                    "CREATE TABLE IF NOT EXISTS monitoring_metrics_snapshot AS SELECT * FROM df_mon_view WHERE 1=0"
                )
                conn.execute("INSERT INTO monitoring_metrics_snapshot SELECT * FROM df_mon_view")
                total_records += df_metrics.height
            finally:
                with contextlib.suppress(Exception):
                    conn.unregister("df_mon_view")
        if df_locks.height > 0:
            conn.register("df_lock_view", df_locks.to_arrow())
            try:
                conn.execute(
                    "CREATE TABLE IF NOT EXISTS monitoring_locks_snapshot AS SELECT * FROM df_lock_view WHERE 1=0"
                )
                conn.execute("INSERT INTO monitoring_locks_snapshot SELECT * FROM df_lock_view")
                total_records += df_locks.height
            finally:
                with contextlib.suppress(Exception):
                    conn.unregister("df_lock_view")
    return total_records


def clear_monitoring_metrics_duckdb(
    db_path: str = "data/monitoring_metrics.duckdb",
) -> None:
    """DuckDB izleme tablolarını siler."""
    from pathlib import Path

    import duckdb

    target = Path(db_path)
    if not target.exists():
        return
    with duckdb.connect(db_path) as conn:
        conn.execute("DROP TABLE IF EXISTS monitoring_metrics_snapshot")
        conn.execute("DROP TABLE IF EXISTS monitoring_locks_snapshot")


__all__: Final[list[str]] = [
    "DEFAULT_SYNC_INTERVAL_SECONDS",
    "PROMETHEUS_HISTOGRAM_BUCKETS",
    "PortfolioMonitor",
    "clear_monitoring_metrics_duckdb",
    "export_lock_metrics_to_orjson_bytes",
    "export_lock_metrics_to_polars",
    "export_metrics_to_orjson_bytes",
    "export_metrics_to_polars",
    "export_monitoring_metrics_to_duckdb",
    "otel_trace",
    "portfolio_monitor",
]
