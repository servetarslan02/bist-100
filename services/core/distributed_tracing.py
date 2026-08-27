"""
ALPHA BIST — Distributed Tracing & Correlation ID

İstek zincirini takip etmek için correlation ID ve tracing.

Özellikler:
1. Correlation ID propagation (request → service → service)
2. Span hierarchy (parent → child)
3. Performance bottleneck detection
4. Structured log correlation

Referanslar:
- CORE-NIHAI-SPEC.md - Section 3.4
- OpenTelemetry specification
"""

import asyncio
import contextvars
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

import structlog

logger = structlog.get_logger()

# F-025: OpenTelemetry integration (optional)
try:
    from opentelemetry import trace as otel_trace
    from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor

    _OTEL_AVAILABLE = True
except ImportError:
    _OTEL_AVAILABLE = False
    otel_trace = None

# Context variable for correlation ID propagation
correlation_id_var: contextvars.ContextVar[str | None] = contextvars.ContextVar("correlation_id", default=None)
span_id_var: contextvars.ContextVar[str | None] = contextvars.ContextVar("span_id", default=None)


@dataclass
class Span:
    """Tek bir tracing span'i."""

    span_id: str
    parent_id: str | None
    correlation_id: str
    operation: str
    service: str
    start_time: float
    end_time: float | None = None
    status: str = "OK"  # OK, ERROR, TIMEOUT
    attributes: dict[str, Any] = field(default_factory=dict)
    events: list[dict[str, Any]] = field(default_factory=list)

    @property
    def duration_ms(self) -> float:
        if self.end_time is None:
            return (time.monotonic() - self.start_time) * 1000
        return (self.end_time - self.start_time) * 1000

    def finish(self, status: str = "OK"):
        self.end_time = time.monotonic()
        self.status = status

    def add_event(self, name: str, attributes: dict[str, Any] | None = None):
        self.events.append(
            {
                "name": name,
                "timestamp": time.time(),
                "attributes": attributes or {},
            }
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "span_id": self.span_id,
            "parent_id": self.parent_id,
            "correlation_id": self.correlation_id,
            "operation": self.operation,
            "service": self.service,
            "duration_ms": round(self.duration_ms, 2),
            "status": self.status,
            "attributes": self.attributes,
            "events": len(self.events),
        }


@dataclass
class Trace:
    """Bir request'in tam trace'i."""

    correlation_id: str
    spans: list[Span] = field(default_factory=list)
    start_time: float = field(default_factory=time.monotonic)
    end_time: float | None = None

    @property
    def total_duration_ms(self) -> float:
        if self.end_time is None:
            return (time.monotonic() - self.start_time) * 1000
        return (self.end_time - self.start_time) * 1000

    def to_dict(self) -> dict[str, Any]:
        return {
            "correlation_id": self.correlation_id,
            "total_duration_ms": round(self.total_duration_ms, 2),
            "span_count": len(self.spans),
            "spans": [s.to_dict() for s in self.spans],
        }


class DistributedTracer:
    """
    Distributed tracing yönetici.

    Correlation ID üretir, span'leri takip eder,
    performans darboğazlarını tespit eder.

    Kullanım:
        tracer = DistributedTracer()

        # Request başı
        corr_id = tracer.start_trace("market.scan")

        # Service calls
        with tracer.start_span("feature.calc") as span:
            span.attributes["ticker"] = "THYAO"
            # ... work ...
    """

    def __init__(self, service_name: str = "alpha-bist"):
        self._service_name = service_name
        self._traces: dict[str, Trace] = {}
        self._active_spans: dict[str, Span] = {}
        self._max_traces = 1000
        self._slow_threshold_ms = 1000  # 1 saniye

        # F-025: OpenTelemetry tracer (optional)
        self._otel_tracer = None
        if _OTEL_AVAILABLE:
            try:
                provider = TracerProvider()
                processor = BatchSpanProcessor(OTLPSpanExporter())
                provider.add_span_processor(processor)
                otel_trace.set_tracer_provider(provider)
                self._otel_tracer = otel_trace.get_tracer(service_name)
                logger.info("OpenTelemetry tracing enabled")
            except Exception as e:
                logger.debug("OpenTelemetry not configured", error=str(e))

    def generate_correlation_id(self) -> str:
        """Yeni correlation ID üret."""
        return str(uuid.uuid4())[:16]

    def start_trace(self, operation: str) -> str:
        """
        Yeni trace başlat.

        Returns:
            Correlation ID
        """
        corr_id = self.generate_correlation_id()
        correlation_id_var.set(corr_id)

        trace = Trace(correlation_id=corr_id)
        self._traces[corr_id] = trace

        # Root span
        self.start_span(operation, correlation_id=corr_id)

        logger.debug("Trace started", correlation_id=corr_id, operation=operation)

        return corr_id

    def start_span(
        self,
        operation: str,
        parent_id: str | None = None,
        correlation_id: str | None = None,
        attributes: dict[str, Any] | None = None,
    ) -> Span:
        """
        Yeni span başlat.

        Args:
            operation: İşlem adı
            parent_id: Parent span ID
            correlation_id: Correlation ID (yoksa context'ten)
            attributes: Span attributes

        Returns:
            Span
        """
        corr_id = correlation_id or correlation_id_var.get()
        if corr_id is None:
            corr_id = self.generate_correlation_id()
            correlation_id_var.set(corr_id)

        span_id = str(uuid.uuid4())[:12]
        parent = parent_id or span_id_var.get()

        span = Span(
            span_id=span_id,
            parent_id=parent,
            correlation_id=corr_id,
            operation=operation,
            service=self._service_name,
            start_time=time.monotonic(),
            attributes=attributes or {},
        )

        # Set context
        span_id_var.set(span_id)

        # Add to trace
        if corr_id in self._traces:
            self._traces[corr_id].spans.append(span)

        self._active_spans[span_id] = span

        return span

    def finish_span(self, span: Span, status: str = "OK"):
        """Span'i bitir."""
        span.finish(status)
        self._active_spans.pop(span.span_id, None)

        # Slow span warning
        if span.duration_ms > self._slow_threshold_ms:
            logger.warning(
                "Slow span detected",
                operation=span.operation,
                duration_ms=round(span.duration_ms, 2),
                threshold_ms=self._slow_threshold_ms,
            )

    def finish_trace(self, correlation_id: str | None = None):
        """Trace'i bitir."""
        corr_id = correlation_id or correlation_id_var.get()
        if corr_id and corr_id in self._traces:
            self._traces[corr_id].end_time = time.monotonic()

        # Cleanup old traces
        if len(self._traces) > self._max_traces:
            oldest = sorted(self._traces.keys(), key=lambda k: self._traces[k].start_time)[
                : len(self._traces) - self._max_traces
            ]
            for k in oldest:
                del self._traces[k]

    def get_current_correlation_id(self) -> str | None:
        """Mevcut correlation ID."""
        return correlation_id_var.get()

    def get_trace(self, correlation_id: str) -> dict[str, Any] | None:
        """Trace'i getir."""
        trace = self._traces.get(correlation_id)
        return trace.to_dict() if trace else None

    def get_slow_traces(self, threshold_ms: float | None = None) -> list[dict[str, Any]]:
        """Yavaş trace'leri listele."""
        threshold = threshold_ms or self._slow_threshold_ms
        slow = [trace for trace in self._traces.values() if trace.total_duration_ms > threshold]
        return [t.to_dict() for t in sorted(slow, key=lambda t: t.total_duration_ms, reverse=True)[:20]]

    def get_stats(self) -> dict[str, Any]:
        """Tracing istatistikleri."""
        durations = [t.total_duration_ms for t in self._traces.values()]
        return {
            "total_traces": len(self._traces),
            "active_spans": len(self._active_spans),
            "avg_duration_ms": round(sum(durations) / max(len(durations), 1), 2),
            "slow_traces": len([d for d in durations if d > self._slow_threshold_ms]),
        }


class SpanContextManager:
    """Span context manager."""

    def __init__(self, tracer: DistributedTracer, operation: str, **kwargs):
        self._tracer = tracer
        self._operation = operation
        self._kwargs = kwargs
        self._span: Span | None = None

    def __enter__(self) -> Span:
        self._span = self._tracer.start_span(self._operation, **self._kwargs)
        return self._span

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self._span:
            status = "ERROR" if exc_type else "OK"
            self._tracer.finish_span(self._span, status)

    async def __aenter__(self) -> Span:
        self._span = self._tracer.start_span(self._operation, **self._kwargs)
        return self._span

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self._span:
            status = "ERROR" if exc_type else "OK"
            self._tracer.finish_span(self._span, status)


# Singleton
distributed_tracer = DistributedTracer()


def trace(operation: str, **kwargs):
    """Tracing decorator."""

    def decorator(func):
        if asyncio.iscoroutinefunction(func):

            async def async_wrapper(*args, **kw):
                with SpanContextManager(distributed_tracer, operation, **kwargs) as span:
                    try:
                        result = await func(*args, **kw)
                        return result
                    except Exception as e:
                        span.add_event("error", {"error": str(e)})
                        raise

            return async_wrapper
        else:

            def sync_wrapper(*args, **kw):
                with SpanContextManager(distributed_tracer, operation, **kwargs) as span:
                    try:
                        result = func(*args, **kw)
                        return result
                    except Exception as e:
                        span.add_event("error", {"error": str(e)})
                        raise

            return sync_wrapper

    return decorator
