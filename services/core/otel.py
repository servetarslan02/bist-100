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

import os

import structlog

logger = structlog.get_logger()

# Global tracer provider
_tracer_provider = None
_tracer = None


def setup_telemetry(
    service_name: str = "alpha-bist",
    endpoint: str | None = None,
    enabled: bool = True,
) -> None:
    """OpenTelemetry'yi başlat.

    Args:
        service_name: Servis adı
        endpoint: OTLP endpoint (örn: http://localhost:4317)
        enabled: Telemetry aktif mi
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
            }
        )

        # Tracer provider
        _tracer_provider = TracerProvider(resource=resource)

        # Exporter
        if endpoint:
            exporter = OTLPSpanExporter(endpoint=endpoint, insecure=True)
        else:
            # Development: console exporter
            exporter = ConsoleSpanExporter()

        # Span processor
        span_processor = BatchSpanProcessor(exporter)
        _tracer_provider.add_span_processor(span_processor)

        # Global tracer provider
        trace.set_tracer_provider(_tracer_provider)

        # Tracer
        _tracer = trace.get_tracer(service_name)

        logger.info("OpenTelemetry initialized", service=service_name, endpoint=endpoint or "console")

    except ImportError:
        logger.warning("OpenTelemetry packages not installed, skipping")
    except Exception as e:
        logger.error("OpenTelemetry setup failed", error=str(e))


def get_tracer(name: str = __name__):
    """Tracer al."""
    global _tracer
    if _tracer is None:
        # Fallback: noop tracer
        from opentelemetry import trace

        return trace.get_tracer(name)
    return _tracer


def shutdown_telemetry() -> None:
    """OpenTelemetry'yi kapat."""
    global _tracer_provider
    if _tracer_provider:
        try:
            _tracer_provider.shutdown()
            logger.info("OpenTelemetry shutdown")
        except Exception as e:
            logger.error("OpenTelemetry shutdown failed", error=str(e))
