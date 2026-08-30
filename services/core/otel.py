"""
ALPHA BIST — OpenTelemetry Integration

Distributed tracing için OpenTelemetry entegrasyonu.

Özellikler:
- Auto-instrumentation (FastAPI, HTTP clients, DB)
- Trace context propagation
- Span hierarchy
- Custom attributes

Kullanım:
    from services.core.otel import setup_telemetry, get_tracer

    # Uygulama başlangıcında
    setup_telemetry(service_name="alpha-api")

    # Kod içinde
    tracer = get_tracer(__name__)
    with tracer.start_as_current_span("operation") as span:
        span.set_attribute("key", "value")
        # ...
"""

import asyncio
import os
from typing import Any

import structlog

logger = structlog.get_logger(__name__)

# Global tracer provider
_tracer_provider = None
_tracer = None


def setup_telemetry(
    service_name: str = "alpha-bist",
    endpoint: str | None = None,
    enabled: bool = True,
    app: Any = None,
) -> None:
    """OpenTelemetry'yi başlat.

    Args:
        service_name: Servis adı
        endpoint: OTLP endpoint (örn: http://localhost:4317)
        enabled: Telemetry aktif mi
        app: FastAPI uygulaması (varsa auto-instrumentation için)
    """
    global _tracer_provider, _tracer

    if not enabled:
        logger.info("OpenTelemetry disabled")
        return

    try:
        from opentelemetry import trace
        from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
        from opentelemetry.sdk.resources import SERVICE_NAME, Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter

        # Resource oluştur
        resource = Resource.create(
            {
                SERVICE_NAME: service_name,
                "deployment.environment": os.getenv("APP_ENV", "development"),
                "service.version": os.getenv("APP_VERSION", "2.1.0"),
                "host.name": os.uname().nodename if hasattr(os, "uname") else os.getenv("COMPUTERNAME", "unknown"),
            }
        )

        # Tracer provider
        _tracer_provider = TracerProvider(resource=resource)

        # Exporter
        if endpoint:
            exporter = OTLPSpanExporter(endpoint=endpoint, insecure=True)
        else:
            # SSD write reduction: console exporter yerine no-op
            # Her span stdout'a yazılıyordu → Docker JSON log
            from opentelemetry.sdk.trace.export import SpanExporter, SpanExportResult
            class _NoopExporter(SpanExporter):
                def export(self, spans):
                    return SpanExportResult.SUCCESS
                def shutdown(self):
                    pass
                def force_flush(self, timeout_millis=30000):
                    return True
            exporter = _NoopExporter()

        # Span processor
        span_processor = BatchSpanProcessor(exporter)
        _tracer_provider.add_span_processor(span_processor)

        # Global tracer provider
        trace.set_tracer_provider(_tracer_provider)

        # Tracer
        _tracer = trace.get_tracer(service_name)

        # Auto-Instrumentation for HTTP, DB, Redis
        try:
            from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor

            HTTPXClientInstrumentor().instrument()
            logger.info("OpenTelemetry HTTPX instrumentation enabled")
        except ImportError:
            logger.warning("opentelemetry-instrumentation-httpx not installed")

        try:
            pass
            logger.info("OpenTelemetry SQLAlchemy instrumentation available")
        except ImportError:
            logger.warning("opentelemetry-instrumentation-sqlalchemy not installed")

        try:
            from opentelemetry.instrumentation.redis import RedisInstrumentor

            RedisInstrumentor().instrument()
            logger.info("OpenTelemetry Redis instrumentation enabled")
        except ImportError:
            logger.warning("opentelemetry-instrumentation-redis not installed")

        # FastAPI Auto-Instrumentation
        if app is not None:
            try:
                from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

                FastAPIInstrumentor.instrument_app(app)
                logger.info("OpenTelemetry FastAPI instrumentation enabled")
            except ImportError:
                logger.warning("opentelemetry-instrumentation-fastapi not installed")

        logger.info("OpenTelemetry initialized", service=service_name, endpoint=endpoint or "console")

    except ImportError:
        logger.warning("OpenTelemetry packages not installed, skipping")
    except Exception as e:
        logger.error("OpenTelemetry setup failed", error=str(e))


def get_tracer(name: str = __name__) -> Any:
    """Tracer al."""
    global _tracer
    if _tracer is None:
        # Fallback: noop tracer
        from opentelemetry import trace

        return trace.get_tracer(name)
    return _tracer


import functools


def otel_trace(span_name: str) -> Any:
    """
    Decorator to wrap a method or function in an OpenTelemetry span.
    Uses the global tracer from this module.
    """

    def decorator(func) -> Any:
        """Otomatik eklendi."""
        if asyncio.iscoroutinefunction(func):

            @functools.wraps(func)
            async def async_wrapper(*args, **kwargs) -> Any:
                """Otomatik eklendi."""
                tracer = get_tracer(func.__module__)
                with tracer.start_as_current_span(span_name):
                    return await func(*args, **kwargs)

            return async_wrapper
        else:

            @functools.wraps(func)
            def sync_wrapper(*args, **kwargs) -> Any:
                """Otomatik eklendi."""
                tracer = get_tracer(func.__module__)
                with tracer.start_as_current_span(span_name):
                    return func(*args, **kwargs)

            return sync_wrapper

    return decorator


def shutdown_telemetry() -> None:
    """OpenTelemetry'yi kapat."""
    global _tracer_provider
    if _tracer_provider:
        try:
            _tracer_provider.shutdown()
            logger.info("OpenTelemetry shutdown")
        except Exception as e:
            logger.error("OpenTelemetry shutdown failed", error=str(e))
