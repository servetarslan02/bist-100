"""
ALPHA BIST — OpenTelemetry Integration v2.0
===========================================
Dağıtık izleme ve telemetri altyapısı:
- Otomatik enstrümantasyon (FastAPI, HTTPX, Redis, SQLAlchemy)
- Trace context yayılımı ve hiyerarşik span yönetimi
- Eşzamanlı çağrılar için hem senkron hem asenkron otel_trace dekoratörü
- Windows ve Linux uyumlu host kimliği tespiti
- Thread-safe tracer provider ve kapatma (shutdown) yaşam döngüsü
- Polars telemetri durum raporlaması (GEMINI.md Kural 2)
"""

from __future__ import annotations

import asyncio
import contextlib
import functools
import os
import platform
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

import duckdb
import orjson
import polars as pl
import structlog

logger = structlog.get_logger(__name__)

# Global tracer provider ve lock
_tracer_provider: Any = None
_tracer: Any = None
_telemetry_enabled: bool = False
_service_name: str = "alpha-bist"
_endpoint: str | None = None
_otel_lock = threading.RLock()

# Idempotent enstrümantasyon bayrakları
_instrumented_httpx: bool = False
_instrumented_redis: bool = False
_instrumented_fastapi: bool = False

DEFAULT_TELEMETRY_DB_PATH: Final[str] = "data/telemetry_status.duckdb"


def configure_duckdb_wal(conn: duckdb.DuckDBPyConnection) -> None:
    """DuckDB bağlantısı için SSD koruyucu ve optimize WAL parametrelerini ayarlar."""
    try:
        conn.execute("PRAGMA checkpoint_threshold='4MB'")
        conn.execute("PRAGMA wal_autocheckpoint='2MB'")
    except Exception as exc:
        logger.warning("duckdb_wal_yapilandirma_uyarisi", hata=str(exc))


def setup_telemetry(
    service_name: str = "alpha-bist",
    endpoint: str | None = None,
    enabled: bool = True,
    app: Any = None,
) -> None:
    """OpenTelemetry dağıtık izleme altyapısını başlatır ve yapılandırır.

    Args:
        service_name: İzlenen servisin benzersiz adı.
        endpoint: OTLP gRPC/HTTP endpoint adresi (örn: http://localhost:4317).
        enabled: Telemetrinin etkin olup olmadığı bayrağı.
        app: Otomatik enstrümante edilecek opsiyonel FastAPI uygulaması.
    """
    global _tracer_provider, _tracer, _telemetry_enabled, _service_name, _endpoint

    with _otel_lock:
        _service_name = service_name
        _endpoint = endpoint

        if not enabled:
            _telemetry_enabled = False
            logger.info("opentelemetry_devre_disi")
            return

        try:
            from opentelemetry import trace
            from opentelemetry.sdk.resources import SERVICE_NAME, Resource
            from opentelemetry.sdk.trace import TracerProvider
            from opentelemetry.sdk.trace.export import BatchSpanProcessor, SpanExporter, SpanExportResult

            # Kaynak (Resource) tanımlama
            hostname = platform.node() or os.getenv("COMPUTERNAME", "unknown")
            resource = Resource.create(
                {
                    SERVICE_NAME: service_name,
                    "deployment.environment": os.getenv("APP_ENV", "development"),
                    "service.version": os.getenv("APP_VERSION", "2.1.0"),
                    "host.name": hostname,
                }
            )

            # Tracer sağlayıcı
            _tracer_provider = TracerProvider(resource=resource)

            # Exporter seçimi
            exporter: SpanExporter
            if endpoint:
                try:
                    from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter

                    exporter = OTLPSpanExporter(endpoint=endpoint, insecure=True)
                except ImportError:
                    logger.warning("opentelemetry_otlp_grpc_exporter_bulunamadi_noop_kullaniliyor")

                    class _NoopFallbackExporter(SpanExporter):
                        def export(self, spans: Any) -> SpanExportResult:
                            return SpanExportResult.SUCCESS

                        def shutdown(self) -> None:
                            pass

                        def force_flush(self, timeout_millis: int = 30000) -> bool:
                            return True

                    exporter = _NoopFallbackExporter()
            else:

                class _NoopExporter(SpanExporter):
                    """Gereksiz disk ve konsol I/O yükünü önleyen no-op exporter."""

                    def export(self, spans: Any) -> SpanExportResult:
                        """Span kayıtlarını başarıyla yutar."""
                        return SpanExportResult.SUCCESS

                    def shutdown(self) -> None:
                        """Dışa aktarıcıyı kapatır."""
                        pass

                    def force_flush(self, timeout_millis: int = 30000) -> bool:
                        """Tamponu temizler."""
                        return True

                exporter = _NoopExporter()

            # Batch işlemci
            span_processor = BatchSpanProcessor(exporter)
            _tracer_provider.add_span_processor(span_processor)

            # Global sağlayıcıyı kaydet (yalnızca henüz gerçek bir TracerProvider atanmamışsa)
            current_provider = trace.get_tracer_provider()
            if not isinstance(current_provider, TracerProvider):
                with contextlib.suppress(Exception):
                    trace.set_tracer_provider(_tracer_provider)
            _tracer = trace.get_tracer(service_name)
            _telemetry_enabled = True

            # HTTPX otomatik enstrümantasyonu (idempotent)
            global _instrumented_httpx, _instrumented_redis, _instrumented_fastapi
            if not _instrumented_httpx:
                try:
                    from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor

                    HTTPXClientInstrumentor().instrument()
                    _instrumented_httpx = True
                    logger.info("opentelemetry_httpx_enstrumantasyon_aktif")
                except ImportError:
                    logger.debug("opentelemetry_httpx_paketi_bulunamadi")
                except Exception as exc:
                    logger.debug("opentelemetry_httpx_zaten_enstrumante", hata=str(exc))
                    _instrumented_httpx = True

            # Redis otomatik enstrümantasyonu (idempotent)
            if not _instrumented_redis:
                try:
                    from opentelemetry.instrumentation.redis import RedisInstrumentor

                    RedisInstrumentor().instrument()
                    _instrumented_redis = True
                    logger.info("opentelemetry_redis_enstrumantasyon_aktif")
                except ImportError:
                    logger.debug("opentelemetry_redis_paketi_bulunamadi")
                except Exception as exc:
                    logger.debug("opentelemetry_redis_zaten_enstrumante", hata=str(exc))
                    _instrumented_redis = True

            # FastAPI otomatik enstrümantasyonu (idempotent)
            if app is not None and not _instrumented_fastapi:
                try:
                    from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

                    FastAPIInstrumentor.instrument_app(app)
                    _instrumented_fastapi = True
                    logger.info("opentelemetry_fastapi_enstrumantasyon_aktif")
                except ImportError:
                    logger.debug("opentelemetry_fastapi_paketi_bulunamadi")
                except Exception as exc:
                    logger.debug("opentelemetry_fastapi_zaten_enstrumante", hata=str(exc))
                    _instrumented_fastapi = True

            logger.info("opentelemetry_basariyla_baslatildi", servis=service_name, endpoint=endpoint or "noop")

        except ImportError as imp_err:
            _telemetry_enabled = False
            logger.warning("opentelemetry_paketleri_eksik_atlanıyor", hata=str(imp_err))
        except Exception as e:
            _telemetry_enabled = False
            logger.error("opentelemetry_kurulum_hatasi", hata=str(e))


def get_tracer(name: str = __name__) -> Any:
    """Belirtilen modül veya kapsam için aktif Tracer nesnesini döner.

    Args:
        name: Tracer kapsam adı.

    Returns:
        Aktif trace.Tracer nesnesi veya noop fallback.
    """
    global _tracer
    with _otel_lock:
        if _tracer is None:
            try:
                from opentelemetry import trace

                return trace.get_tracer(name)
            except ImportError:

                class _FallbackSpan:
                    def __enter__(self) -> _FallbackSpan:
                        return self

                    def __exit__(self, *args: Any) -> None:
                        pass

                    def set_attribute(self, *args: Any, **kwargs: Any) -> None:
                        pass

                    def set_attributes(self, *args: Any, **kwargs: Any) -> None:
                        pass

                    def record_exception(self, *args: Any, **kwargs: Any) -> None:
                        pass

                    def set_status(self, *args: Any, **kwargs: Any) -> None:
                        pass

                    def add_event(self, *args: Any, **kwargs: Any) -> None:
                        pass

                    def is_recording(self) -> bool:
                        return False

                class _FallbackTracer:
                    def start_as_current_span(self, *args: Any, **kwargs: Any) -> _FallbackSpan:
                        return _FallbackSpan()

                    def start_span(self, *args: Any, **kwargs: Any) -> _FallbackSpan:
                        return _FallbackSpan()

                return _FallbackTracer()
        return _tracer


def otel_trace(span_name: str) -> Any:
    """Fonksiyon veya coroutine'i OpenTelemetry span içine alan dekoratör.

    Senkron ve asenkron fonksiyonları otomatik olarak tespit eder;
    oluşan hataları span içine yapısal olarak kaydeder.

    Args:
        span_name: Oluşturulacak span'ın adı.

    Returns:
        Sarmalanmış fonksiyon veya coroutine.
    """

    def decorator(func: Any) -> Any:
        """Dekoratör gövdesi."""
        if asyncio.iscoroutinefunction(func):

            @functools.wraps(func)
            async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
                """Asenkron coroutine için OTel span sarmalayıcısı."""
                tracer = get_tracer(func.__module__)
                with tracer.start_as_current_span(span_name) as span:
                    try:
                        return await func(*args, **kwargs)
                    except Exception as exc:
                        if hasattr(span, "record_exception"):
                            span.record_exception(exc)
                        if hasattr(span, "set_status"):
                            try:
                                from opentelemetry.trace import Status, StatusCode

                                span.set_status(Status(StatusCode.ERROR, str(exc)))
                            except Exception:
                                pass
                        raise

            return async_wrapper
        else:

            @functools.wraps(func)
            def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
                """Senkron fonksiyon için OTel span sarmalayıcısı."""
                tracer = get_tracer(func.__module__)
                with tracer.start_as_current_span(span_name) as span:
                    try:
                        return func(*args, **kwargs)
                    except Exception as exc:
                        if hasattr(span, "record_exception"):
                            span.record_exception(exc)
                        if hasattr(span, "set_status"):
                            try:
                                from opentelemetry.trace import Status, StatusCode

                                span.set_status(Status(StatusCode.ERROR, str(exc)))
                            except Exception:
                                pass
                        raise

            return sync_wrapper

    return decorator


def shutdown_telemetry() -> None:
    """Açık olan OpenTelemetry tracer sağlayıcısını ve arabelleklerini düzgün kapatır."""
    global _tracer_provider, _tracer, _telemetry_enabled
    with _otel_lock:
        if _tracer_provider:
            try:
                _tracer_provider.shutdown()
                logger.info("opentelemetry_kapatildi")
            except Exception as e:
                logger.error("opentelemetry_kapatma_hatasi", hata=str(e))
            finally:
                _tracer_provider = None
                _tracer = None
                _telemetry_enabled = False


def heal_telemetry_connection() -> bool:
    """Telemetri bağlantısını kontrol eder; bozulmuş veya kapalıysa güvenli fallback ile onarır.

    Self-healing ve zero-touch çalışma için kullanılır.

    Returns:
        Telemetri aktif veya onarılmış ise True.
    """
    global _telemetry_enabled, _tracer
    with _otel_lock:
        if _telemetry_enabled and _tracer is not None:
            return True

        logger.warning("opentelemetry_baglanti_kopuk_self_healing_baslatiliyor")
        try:
            setup_telemetry(service_name=_service_name, endpoint=None, enabled=True)
            logger.info("opentelemetry_self_healing_onarimi_basarili")
            return True
        except Exception as exc:
            logger.error("opentelemetry_self_healing_onarim_hatasi", hata=str(exc))
            return False


def export_telemetry_status_to_polars() -> pl.DataFrame:
    """Mevcut telemetri durumunu Polars DataFrame olarak dışa aktarır."""
    with _otel_lock:
        record = {
            "service_name": _service_name,
            "enabled": _telemetry_enabled,
            "has_provider": _tracer_provider is not None,
            "has_tracer": _tracer is not None,
            "endpoint": _endpoint or "internal",
            "checked_at": datetime.now(UTC).isoformat(),
        }

    schema = {
        "service_name": pl.String,
        "enabled": pl.Boolean,
        "has_provider": pl.Boolean,
        "has_tracer": pl.Boolean,
        "endpoint": pl.String,
        "checked_at": pl.String,
    }
    return pl.DataFrame([record], schema=schema)


def export_telemetry_status_to_orjson() -> bytes:
    """Telemetri durumunu C seviyesinde yüksek hızlı orjson bayt dizisi olarak serileştirir."""
    with _otel_lock:
        status_dict = {
            "service_name": _service_name,
            "enabled": _telemetry_enabled,
            "has_provider": _tracer_provider is not None,
            "has_tracer": _tracer is not None,
            "endpoint": _endpoint or "internal",
            "checked_at": datetime.now(UTC).isoformat(),
        }
    return orjson.dumps(status_dict, option=orjson.OPT_SORT_KEYS, default=str)


def to_orjson_bytes() -> bytes:
    """export_telemetry_status_to_orjson için takma ad."""
    return export_telemetry_status_to_orjson()


def save_telemetry_status_to_duckdb(
    db_path: str = DEFAULT_TELEMETRY_DB_PATH,
) -> None:
    """Telemetri durumunu DuckDB tablosuna atomik olarak kaydeder.

    SSD koruması ve optimize WAL parametreleri ile çalışır.
    """
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = duckdb.connect(str(path))
    try:
        configure_duckdb_wal(conn)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS telemetry_status_history (
                service_name VARCHAR,
                enabled BOOLEAN,
                has_provider BOOLEAN,
                has_tracer BOOLEAN,
                endpoint VARCHAR,
                checked_at VARCHAR
            )
        """)
        df_status = export_telemetry_status_to_polars()
        if df_status.height > 0:
            conn.register("tmp_otel_status", df_status.to_arrow())
            try:
                conn.execute("""
                    INSERT INTO telemetry_status_history
                    SELECT service_name, enabled, has_provider, has_tracer, endpoint, checked_at
                    FROM tmp_otel_status
                """)
            finally:
                conn.unregister("tmp_otel_status")
        conn.commit()
        logger.info("telemetri_durumu_duckdb_kaydedildi", db_path=str(path))
    finally:
        conn.close()


def read_telemetry_status_from_duckdb(
    db_path: str = DEFAULT_TELEMETRY_DB_PATH,
    limit: int = 1000,
) -> pl.DataFrame:
    """DuckDB içindeki telemetri durum geçmişini Polars DataFrame olarak okur.

    Args:
        db_path: DuckDB veritabanı dosya yolu.
        limit: Döndürülecek maksimum kayıt sayısı.

    Returns:
        Telemetri geçmişini içeren Polars DataFrame.
    """
    path = Path(db_path)
    schema = {
        "service_name": pl.String,
        "enabled": pl.Boolean,
        "has_provider": pl.Boolean,
        "has_tracer": pl.Boolean,
        "endpoint": pl.String,
        "checked_at": pl.String,
    }
    if not path.exists():
        return pl.DataFrame(schema=schema)

    conn = duckdb.connect(str(path), read_only=True)
    try:
        configure_duckdb_wal(conn)
        tables = [t[0] for t in conn.execute("SHOW TABLES").fetchall()]
        if "telemetry_status_history" not in tables:
            return pl.DataFrame(schema=schema)
        arrow_table = conn.execute(
            f"SELECT service_name, enabled, has_provider, has_tracer, endpoint, checked_at "
            f"FROM telemetry_status_history ORDER BY checked_at DESC LIMIT {int(limit)}"
        ).arrow()
        return pl.from_arrow(arrow_table)  # type: ignore[return-value]
    finally:
        conn.close()


def clear_telemetry_status_duckdb(
    db_path: str = DEFAULT_TELEMETRY_DB_PATH,
) -> None:
    """DuckDB tablosundaki telemetri geçmiş kayıtlarını temizler.

    Args:
        db_path: DuckDB veritabanı dosya yolu.
    """
    path = Path(db_path)
    if not path.exists():
        return
    conn = duckdb.connect(str(path))
    try:
        configure_duckdb_wal(conn)
        conn.execute("DROP TABLE IF EXISTS telemetry_status_history")
        conn.commit()
        logger.info("telemetry_duckdb_temizlendi", db_path=str(path))
    finally:
        conn.close()


__all__: Final[list[str]] = [
    "DEFAULT_TELEMETRY_DB_PATH",
    "clear_telemetry_status_duckdb",
    "configure_duckdb_wal",
    "export_telemetry_status_to_orjson",
    "export_telemetry_status_to_polars",
    "get_tracer",
    "heal_telemetry_connection",
    "otel_trace",
    "read_telemetry_status_from_duckdb",
    "save_telemetry_status_to_duckdb",
    "setup_telemetry",
    "shutdown_telemetry",
    "to_orjson_bytes",
]
