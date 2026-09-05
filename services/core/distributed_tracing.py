"""
ALPHA BIST — Dağıtık İzleme ve Korelasyon Kimliği Yönetimi (Enterprise Distributed Tracing)

Bu modül, mikroservis ve işlem akışlarında uçtan uca istek takibi (request tracing) ve
korelasyon kimliği (correlation ID) yayılımını sağlar.
Resmi OpenTelemetry (OTel) API'si ile tam uyumlu çalışır; OTel ortamda bulunmadığında
veya devre dışı bırakıldığında ise bellek güvenli (bounded ring buffer), DuckDB ve
Polars destekli yerel izleme motoru (local tracer) üzerinden kesintisiz çalışmayı sürdürür.
"""

from __future__ import annotations

import contextvars
import functools
import threading
import time
import uuid
from collections import deque
from contextlib import asynccontextmanager, contextmanager
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator, Generator

import duckdb
import polars as pl
import structlog

logger = structlog.get_logger(__name__)

try:
    from opentelemetry import trace as otel_trace
    from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor
    from opentelemetry.trace import Span as OTelSpan
    from opentelemetry.trace import SpanKind, Status, StatusCode

    _OTEL_AVAILABLE = True
except ImportError:
    _OTEL_AVAILABLE = False
    otel_trace = None
    OTelSpan = Any  # type: ignore
    SpanKind = Any  # type: ignore
    Status = Any  # type: ignore
    StatusCode = Any  # type: ignore

# Log zenginleştirmesi ve bağlam takibi için context variable'ları
correlation_id_var: contextvars.ContextVar[str | None] = contextvars.ContextVar("correlation_id", default=None)
span_id_var: contextvars.ContextVar[str | None] = contextvars.ContextVar("span_id", default=None)


@dataclass
class TraceSpan:
    """Tekil bir izleme aralığını (span) temsil eden yerel veri yapısı.

    OTel aktif olsun ya da olmasın, tutarlı bir span arayüzü sunar ve duckdb/polars
    analitiği için gerekli metrikleri saklar.

    Attributes:
        trace_id: Ait olduğu izin (trace) benzersiz kimliği.
        span_id: Span'ın benzersiz kimliği.
        operation: Yürütülen operasyon veya fonksiyon adı.
        parent_span_id: Üst span kimliği (varsa).
        start_time: Span başlangıç zamanı (saniye cinsinden unix epoch).
        end_time: Span bitiş zamanı (saniye cinsinden unix epoch).
        duration_ms: Milisaniye cinsinden operasyon süresi.
        status: Durum ('OK', 'ERROR', 'RUNNING').
        attributes: Span'a eklenen bağlamsal etiket ve nitelikler.
        error: Hata oluştuysa hata mesajı.
    """

    trace_id: str
    span_id: str
    operation: str
    parent_span_id: str | None = None
    start_time: float = field(default_factory=time.time)
    end_time: float | None = None
    duration_ms: float | None = None
    status: str = "RUNNING"
    attributes: dict[str, Any] = field(default_factory=dict)
    error: str | None = None

    def set_attribute(self, key: str, value: Any) -> None:
        """Span niteliklerine yeni bir anahtar-değer çifti ekler."""
        self.attributes[key] = value

    def set_attributes(self, attributes: dict[str, Any]) -> None:
        """Span niteliklerini toplu olarak günceller."""
        self.attributes.update(attributes)

    def record_exception(self, exception: BaseException) -> None:
        """Span üzerine oluşan istisnayı ve hata bilgisini işler."""
        self.error = f"{type(exception).__name__}: {str(exception)}"
        self.status = "ERROR"

    def set_status(self, status: Any, description: str | None = None) -> None:
        """Span durumunu ayarlar."""
        if hasattr(status, "status_code"):
            self.status = status.status_code.name if hasattr(status.status_code, "name") else str(status.status_code)
        else:
            self.status = str(status)
        if description and not self.error:
            self.error = description

    def finish(self) -> None:
        """Span'ı sonlandırır ve çalışma süresini (duration_ms) hesaplar."""
        if self.end_time is None:
            self.end_time = time.time()
            self.duration_ms = max(0.0, (self.end_time - self.start_time) * 1000.0)
            if self.status == "RUNNING":
                self.status = "OK"

    def to_dict(self) -> dict[str, Any]:
        """Span verilerini sözlük formatında döndürür."""
        return {
            "trace_id": self.trace_id,
            "span_id": self.span_id,
            "parent_span_id": self.parent_span_id,
            "operation": self.operation,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "duration_ms": self.duration_ms,
            "status": self.status,
            "attributes": self.attributes,
            "error": self.error,
        }

    def __repr__(self) -> str:
        return (
            f"TraceSpan(op='{self.operation}', trace_id='{self.trace_id}', "
            f"span_id='{self.span_id}', status='{self.status}', duration_ms={self.duration_ms})"
        )


# Geriye dönük uyumluluk için Span tipi tanımı
Span = OTelSpan if _OTEL_AVAILABLE else TraceSpan


class Trace:
    """Bir istek veya işlem zincirine ait tüm span'ları toplayan kurumsal izleme nesnesi.

    Sistemde geriye dönük uyumluluk sağlar ve trace bazlı özet analitiği sunar.
    """

    def __init__(self, trace_id: str | None = None) -> None:
        """Trace yöneticisini başlatır."""
        self.trace_id: str = trace_id or uuid.uuid4().hex
        self.spans: list[TraceSpan] = []
        self.created_at: float = time.time()

    def add_span(self, span: TraceSpan) -> None:
        """Trace altına yeni bir span ekler."""
        self.spans.append(span)

    @property
    def total_duration_ms(self) -> float:
        """Trace altındaki tüm span'ların toplam çalışma süresini hesaplar."""
        return sum(s.duration_ms or 0.0 for s in self.spans)

    @property
    def has_error(self) -> bool:
        """Trace içinde hata alan herhangi bir span olup olmadığını döndürür."""
        return any(s.status == "ERROR" for s in self.spans)

    def to_dict(self) -> dict[str, Any]:
        """Trace verilerini sözlük formatında serileştirir."""
        return {
            "trace_id": self.trace_id,
            "created_at": self.created_at,
            "span_count": len(self.spans),
            "total_duration_ms": self.total_duration_ms,
            "has_error": self.has_error,
            "spans": [s.to_dict() for s in self.spans],
        }

    def __repr__(self) -> str:
        return (
            f"Trace(trace_id='{self.trace_id}', span_count={len(self.spans)}, "
            f"has_error={self.has_error}, total_ms={self.total_duration_ms:.2f})"
        )


class DistributedTracer:
    """Kurumsal OpenTelemetry ve yerel ring-buffer tabanlı dağıtık izleme yöneticisi.

    OTel altyapısı mevcut olduğunda resmi BatchSpanProcessor ve OTLP exporter ile
    çalışır; OTel olmadığında bellek sızıntısını engelleyen sınırlandırılmış (bounded)
    bir halka arabellek (ring buffer) üzerinden DuckDB/Polars ile analitik imkanı sunar.
    """

    def __init__(self, service_name: str = "alpha-bist", buffer_size: int = 1000) -> None:
        """Dağıtık izleme yöneticisini başlatır.

        Args:
            service_name: İzlenen servisin kurumsal adı.
            buffer_size: Yerel halka arabellek boyutu (varsayılan: 1000).
        """
        self._service_name: str = service_name
        self._tracer: Any = None
        self._buffer_size: int = max(100, buffer_size)
        self._local_buffer: deque[TraceSpan] = deque(maxlen=self._buffer_size)
        self._lock: threading.RLock = threading.RLock()
        self._otel_enabled: bool = False

        if _OTEL_AVAILABLE:
            try:
                resource = Resource.create({"service.name": service_name})
                provider = TracerProvider(resource=resource)
                processor = BatchSpanProcessor(OTLPSpanExporter())
                provider.add_span_processor(processor)
                otel_trace.set_tracer_provider(provider)
                self._tracer = otel_trace.get_tracer(service_name)
                self._otel_enabled = True
                logger.info("Enterprise OpenTelemetry tracing etkinleştirildi.", service=service_name)
            except Exception as e:
                logger.warning(
                    "OpenTelemetry başlatılamadı, yerel güvenli izleme moduna geçiliyor.",
                    servis=service_name,
                    hata=str(e),
                )
        else:
            logger.info(
                "OpenTelemetry paketi bulunamadı, yerel güvenli halka arabellek izleme modu aktif.",
                servis=service_name,
            )

    def generate_correlation_id(self) -> str:
        """Mevcut bağlamdaki korelasyon kimliğini getirir veya yeni bir kimlik üretir.

        Returns:
            str: 16 karakterlik benzersiz korelasyon kimliği.
        """
        current = correlation_id_var.get()
        if current:
            return current
        new_id = uuid.uuid4().hex[:16]
        correlation_id_var.set(new_id)
        return new_id

    def generate_span_id(self) -> str:
        """Yeni bir span kimliği üretir.

        Returns:
            str: 16 karakterlik benzersiz span kimliği.
        """
        return uuid.uuid4().hex[:16]

    def _record_local_span(self, span: TraceSpan) -> None:
        """Span'ı thread-safe olarak yerel halka arabelleğe kaydeder."""
        with self._lock:
            self._local_buffer.append(span)

    @contextmanager
    def start_span(
        self,
        operation: str,
        attributes: dict[str, Any] | None = None,
        kind: int = 0,
    ) -> Generator[Any, None, None]:
        """Senkron işlemler için span bağlamı başlatır.

        Args:
            operation: İzlenen operasyon veya fonksiyon adı.
            attributes: Span'a eklenecek özel nitelikler sözlüğü.
            kind: OTel SpanKind değeri (varsayılan: INTERNAL / 0).

        Yields:
            Span nesnesi (OTel span veya yerel TraceSpan).
        """
        corr_id = self.generate_correlation_id()
        current_span_id = self.generate_span_id()
        parent_span_id = span_id_var.get()

        corr_token = correlation_id_var.set(corr_id)
        span_token = span_id_var.set(current_span_id)

        local_span = TraceSpan(
            trace_id=corr_id,
            span_id=current_span_id,
            operation=operation,
            parent_span_id=parent_span_id,
            attributes={"correlation_id": corr_id, **(attributes or {})},
        )

        try:
            if self._tracer and _OTEL_AVAILABLE:
                span_kind = SpanKind(kind) if hasattr(SpanKind, "__members__") else None
                with self._tracer.start_as_current_span(operation, kind=span_kind) as otel_span:
                    otel_span.set_attribute("correlation_id", corr_id)
                    if attributes:
                        otel_span.set_attributes(attributes)
                    try:
                        yield otel_span
                    except Exception as exc:
                        otel_span.record_exception(exc)
                        otel_span.set_status(Status(StatusCode.ERROR, str(exc)))
                        local_span.record_exception(exc)
                        raise
            else:
                try:
                    yield local_span
                except Exception as exc:
                    local_span.record_exception(exc)
                    raise
        finally:
            local_span.finish()
            self._record_local_span(local_span)
            correlation_id_var.reset(corr_token)
            span_id_var.reset(span_token)

    @asynccontextmanager
    async def start_async_span(
        self,
        operation: str,
        attributes: dict[str, Any] | None = None,
        kind: int = 0,
    ) -> AsyncGenerator[Any, None]:
        """Asenkron işlemler için span bağlamı başlatır.

        Args:
            operation: İzlenen asenkron operasyon adı.
            attributes: Span nitelikleri sözlüğü.
            kind: OTel SpanKind değeri.

        Yields:
            Span nesnesi (OTel span veya yerel TraceSpan).
        """
        corr_id = self.generate_correlation_id()
        current_span_id = self.generate_span_id()
        parent_span_id = span_id_var.get()

        corr_token = correlation_id_var.set(corr_id)
        span_token = span_id_var.set(current_span_id)

        local_span = TraceSpan(
            trace_id=corr_id,
            span_id=current_span_id,
            operation=operation,
            parent_span_id=parent_span_id,
            attributes={"correlation_id": corr_id, **(attributes or {})},
        )

        try:
            if self._tracer and _OTEL_AVAILABLE:
                span_kind = SpanKind(kind) if hasattr(SpanKind, "__members__") else None
                with self._tracer.start_as_current_span(operation, kind=span_kind) as otel_span:
                    otel_span.set_attribute("correlation_id", corr_id)
                    if attributes:
                        otel_span.set_attributes(attributes)
                    try:
                        yield otel_span
                    except Exception as exc:
                        otel_span.record_exception(exc)
                        otel_span.set_status(Status(StatusCode.ERROR, str(exc)))
                        local_span.record_exception(exc)
                        raise
            else:
                try:
                    yield local_span
                except Exception as exc:
                    local_span.record_exception(exc)
                    raise
        finally:
            local_span.finish()
            self._record_local_span(local_span)
            correlation_id_var.reset(corr_token)
            span_id_var.reset(span_token)

    def get_current_correlation_id(self) -> str | None:
        """Mevcut bağlamdaki korelasyon kimliğini döndürür."""
        return correlation_id_var.get()

    def get_current_span_id(self) -> str | None:
        """Mevcut bağlamdaki span kimliğini döndürür."""
        return span_id_var.get()

    def get_recent_spans(self, limit: int = 100) -> list[TraceSpan]:
        """Yerel arabellekteki en güncel span kayıtlarını döndürür.

        Args:
            limit: Döndürülecek maksimum span sayısı.

        Returns:
            list[TraceSpan]: Span nesneleri listesi.
        """
        with self._lock:
            spans = list(self._local_buffer)
        return spans[-limit:] if limit > 0 else spans

    def clear_local_buffer(self) -> None:
        """Yerel halka arabelleği temizler."""
        with self._lock:
            self._local_buffer.clear()

    def export_spans_to_polars(self) -> pl.DataFrame:
        """Yerel arabellekteki span kayıtlarını Polars DataFrame formatına dönüştürür.

        Returns:
            pl.DataFrame: Span analitik tablosu.
        """
        with self._lock:
            data = [s.to_dict() for s in self._local_buffer]

        if not data:
            return pl.DataFrame(
                schema={
                    "trace_id": pl.Utf8,
                    "span_id": pl.Utf8,
                    "parent_span_id": pl.Utf8,
                    "operation": pl.Utf8,
                    "start_time": pl.Float64,
                    "end_time": pl.Float64,
                    "duration_ms": pl.Float64,
                    "status": pl.Utf8,
                    "error": pl.Utf8,
                }
            )

        # Polars için attributes sözlüğünü sadeleştirelim
        rows = []
        for d in data:
            row = {
                "trace_id": d["trace_id"],
                "span_id": d["span_id"],
                "parent_span_id": d["parent_span_id"],
                "operation": d["operation"],
                "start_time": d["start_time"],
                "end_time": d["end_time"],
                "duration_ms": d["duration_ms"],
                "status": d["status"],
                "error": d["error"],
            }
            rows.append(row)
        return pl.DataFrame(rows)

    def export_spans_to_duckdb(self, db_path: str = ":memory:") -> duckdb.DuckDBPyConnection:
        """Span kayıtlarını DuckDB veritabanında 'trace_spans' tablosuna kaydeder.

        Args:
            db_path: DuckDB veritabanı dosya yolu (varsayılan: in-memory).

        Returns:
            duckdb.DuckDBPyConnection: DuckDB bağlantı nesnesi.
        """
        df = self.export_spans_to_polars()
        conn = duckdb.connect(db_path)
        conn.register("df_spans", df)
        conn.execute("CREATE TABLE IF NOT EXISTS trace_spans AS SELECT * FROM df_spans")
        conn.unregister("df_spans")
        return conn

    def __repr__(self) -> str:
        with self._lock:
            buf_len = len(self._local_buffer)
        return (
            f"DistributedTracer(service='{self._service_name}', "
            f"otel_enabled={self._otel_enabled}, buffer_records={buf_len}/{self._buffer_size})"
        )


# Global Singleton Tracer Örneği
distributed_tracer = DistributedTracer()


def trace(operation: str | None = None, attributes: dict[str, Any] | None = None) -> Any:
    """Senkron fonksiyonlar için otomatik span başlatan dekoratör.

    Args:
        operation: İsteğe bağlı span adı (varsayılan: fonksiyon adı).
        attributes: Span nitelikleri sözlüğü.

    Returns:
        Dekore edilmiş senkron fonksiyon çağrıcısı.
    """

    def decorator(func: Any) -> Any:
        op_name = operation or func.__name__

        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            with distributed_tracer.start_span(op_name, attributes):
                return func(*args, **kwargs)

        return wrapper

    return decorator


def trace_async(operation: str | None = None, attributes: dict[str, Any] | None = None) -> Any:
    """Asenkron fonksiyonlar için otomatik span başlatan dekoratör.

    Args:
        operation: İsteğe bağlı span adı (varsayılan: fonksiyon adı).
        attributes: Span nitelikleri sözlüğü.

    Returns:
        Dekore edilmiş asenkron fonksiyon çağrıcısı.
    """

    def decorator(func: Any) -> Any:
        op_name = operation or func.__name__

        @functools.wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            async with distributed_tracer.start_async_span(op_name, attributes):
                return await func(*args, **kwargs)

        return wrapper

    return decorator


__all__ = [
    "DistributedTracer",
    "Span",
    "Trace",
    "TraceSpan",
    "correlation_id_var",
    "distributed_tracer",
    "span_id_var",
    "trace",
    "trace_async",
]
