"""
ALPHA BIST — Circuit Breaker Metrics Export

Circuit breaker durumunu Prometheus formatında export eder.
Monitoring dashboard'larında circuit breaker durumu görünür.

Referanslar:
- CORE-NIHAI-SPEC.md - Section 2.5
"""

import functools
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import structlog
from opentelemetry import trace

logger = structlog.get_logger(__name__)
tracer = trace.get_tracer("alpha-bist.circuit_breaker_metrics")


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


@dataclass
class CircuitBreakerSnapshot:
    """Anlık circuit breaker durumu."""

    name: str
    state: str  # CLOSED, OPEN, HALF_OPEN
    failure_count: int
    success_count: int
    failure_threshold: int
    recovery_timeout_seconds: int
    last_failure_time: str | None
    last_success_time: str | None
    total_requests: int
    total_failures: int
    total_successes: int
    uptime_percentage: float

    def to_dict(self) -> dict[str, Any]:
        """Otomatik eklendi."""
        return {
            "name": self.name,
            "state": self.state,
            "failure_count": self.failure_count,
            "success_count": self.success_count,
            "failure_threshold": self.failure_threshold,
            "recovery_timeout_seconds": self.recovery_timeout_seconds,
            "last_failure": self.last_failure_time,
            "last_success": self.last_success_time,
            "total_requests": self.total_requests,
            "total_failures": self.total_failures,
            "total_successes": self.total_successes,
            "uptime_pct": round(self.uptime_percentage, 2),
        }


class CircuitBreakerMetricsCollector:
    """
    Circuit breaker metrics toplayıcı ve export edici.

    Tüm circuit breaker'ların durumunu merkezi olarak izler.
    """

    def __init__(self):
        """Otomatik eklendi."""
        self._tracked_breakers: dict[str, Any] = {}  # name → CircuitBreaker
        self._history: list[dict[str, Any]] = []
        self._max_history = 1000

    @otel_trace("circuit_breaker_metrics.track")
    def track(self, breaker: Any) -> Any:
        """Circuit breaker'ı izleme altına al."""
        self._tracked_breakers[breaker.name] = breaker
        logger.debug("Circuit breaker tracked", name=breaker.name)

    def untrack(self, name: str) -> Any:
        """İzlemeyi kaldır."""
        self._tracked_breakers.pop(name, None)

    def get_snapshot(self, name: str) -> CircuitBreakerSnapshot | None:
        """Tek circuit breaker snapshot'ı."""
        breaker = self._tracked_breakers.get(name)
        if not breaker:
            return None

        total_req = getattr(breaker, "_total_requests", 0)
        total_fail = getattr(breaker, "_total_failures", 0)
        total_succ = getattr(breaker, "_total_successes", 0)

        uptime = (total_succ / total_req * 100) if total_req > 0 else 100.0

        return CircuitBreakerSnapshot(
            name=breaker.name,
            state=breaker.state.value if hasattr(breaker.state, "value") else str(breaker.state),
            failure_count=breaker.failure_count,
            success_count=getattr(breaker, "success_count", 0),
            failure_threshold=breaker.failure_threshold,
            recovery_timeout_seconds=breaker.recovery_timeout_seconds,
            last_failure_time=breaker.last_failure_time.isoformat() if breaker.last_failure_time else None,
            last_success_time=breaker.last_success_time.isoformat() if breaker.last_success_time else None,
            total_requests=total_req,
            total_failures=total_fail,
            total_successes=total_succ,
            uptime_percentage=uptime,
        )

    def get_all_snapshots(self) -> list[CircuitBreakerSnapshot]:
        """Tüm circuit breaker snapshot'ları."""
        return [self.get_snapshot(name) for name in self._tracked_breakers]

    @otel_trace("circuit_breaker_metrics.export_prometheus")
    def export_prometheus(self) -> str:
        """
        Prometheus formatında metrics export.

        Returns:
            Prometheus text format
        """
        lines = []

        # HELP and TYPE headers
        lines.append("# HELP circuit_breaker_state Circuit breaker state (0=CLOSED, 1=OPEN, 2=HALF_OPEN)")
        lines.append("# TYPE circuit_breaker_state gauge")

        lines.append("# HELP circuit_breaker_failures Total failure count")
        lines.append("# TYPE circuit_breaker_failures counter")

        lines.append("# HELP circuit_breaker_requests Total request count")
        lines.append("# TYPE circuit_breaker_requests counter")

        lines.append("# HELP circuit_breaker_uptime_pct Uptime percentage")
        lines.append("# TYPE circuit_breaker_uptime_pct gauge")

        for name, breaker in self._tracked_breakers.items():
            state_value = {"CLOSED": 0, "OPEN": 1, "HALF_OPEN": 2}.get(
                breaker.state.value if hasattr(breaker.state, "value") else str(breaker.state), -1
            )

            total_req = getattr(breaker, "_total_requests", 0)
            getattr(breaker, "_total_failures", 0)
            total_succ = getattr(breaker, "_total_successes", 0)
            uptime = (total_succ / total_req * 100) if total_req > 0 else 100.0

            labels = f'name="{name}"'
            lines.append(f"circuit_breaker_state{{{labels}}} {state_value}")
            lines.append(f"circuit_breaker_failures{{{labels}}} {breaker.failure_count}")
            lines.append(f"circuit_breaker_requests{{{labels}}} {total_req}")
            lines.append(f"circuit_breaker_uptime_pct{{{labels}}} {uptime:.2f}")

        return "\n".join(lines) + "\n"

    def export_json(self) -> dict[str, Any]:
        """JSON formatında export."""
        return {
            "timestamp": datetime.now(UTC).isoformat(),
            "circuit_breakers": {name: self.get_snapshot(name).to_dict() for name in self._tracked_breakers},
            "summary": {
                "total": len(self._tracked_breakers),
                "closed": sum(
                    1
                    for b in self._tracked_breakers.values()
                    if (b.state.value if hasattr(b.state, "value") else str(b.state)) == "CLOSED"
                ),
                "open": sum(
                    1
                    for b in self._tracked_breakers.values()
                    if (b.state.value if hasattr(b.state, "value") else str(b.state)) == "OPEN"
                ),
                "half_open": sum(
                    1
                    for b in self._tracked_breakers.values()
                    if (b.state.value if hasattr(b.state, "value") else str(b.state)) == "HALF_OPEN"
                ),
            },
        }

    @otel_trace("circuit_breaker_metrics.record_state_change")
    def record_state_change(self, name: str, old_state: str, new_state: str) -> Any:
        """State change kaydet."""
        entry = {
            "timestamp": datetime.now(UTC).isoformat(),
            "name": name,
            "old_state": old_state,
            "new_state": new_state,
        }
        self._history.append(entry)
        if len(self._history) > 1000:
            self._history = self._history[-1000:]

        if len(self._history) > self._max_history:
            self._history = self._history[-self._max_history :]

        logger.info("Circuit breaker state changed", name=name, old=old_state, new=new_state)

    def get_history(self, limit: int = 50) -> list[dict[str, Any]]:
        """State change geçmişi."""
        return self._history[-limit:]


# Singleton
circuit_breaker_metrics = CircuitBreakerMetricsCollector()
