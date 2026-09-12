"""ALPHA BIST — Trace Context (İzleme Bağlamı) Modülü.

Bu modül, Alpha BIST multi-agent pipeline ve alt servislerinin (araştırma, münazara,
risk değerlendirmesi, sentez ve yürütme) tüm aşamalarını tek bir Trace ID ve hiyerarşik
Span ID'ler ile uçtan uca takip etmesini sağlar. Asenkron (asyncio) ve senkron context
yöneticilerini tam destekler; thread sınırları arasında bağlam yayılımını (context propagation)
güvence altına alır ve structlog ile derinlemesine entegre çalışır.
"""

from __future__ import annotations

import threading
import uuid
from contextvars import ContextVar, Token
from datetime import UTC, datetime
from typing import Any, Callable

import orjson

__all__ = [
    "TraceSpan",
    "TraceContext",
    "get_trace_id",
    "get_ticker",
    "get_phase",
    "get_span_id",
    "get_current_trace",
    "copy_trace_context",
    "run_with_trace",
    "trace_processor",
]

# Context Değişkenleri — Asenkron görev ve thread bazlı izolasyon
_trace_id_var: ContextVar[str] = ContextVar("trace_id", default="")
_ticker_var: ContextVar[str] = ContextVar("ticker", default="")
_phase_var: ContextVar[str] = ContextVar("phase", default="")
_span_id_var: ContextVar[str] = ContextVar("span_id", default="")
_parent_span_id_var: ContextVar[str] = ContextVar("parent_span_id", default="")
_current_trace_var: ContextVar[TraceContext | None] = ContextVar("current_trace", default=None)


class TraceSpan:
    """Tekil bir işlem adımını veya alt görevi temsil eden izleme aralığı (Span).

    Senkron ('with span:') ve asenkron ('async with span:') context manager protokollerini
    eksiksiz destekler. Hata oluştuğunda durumu otomatik kaydeder ve süreyi ölçer.
    """

    def __init__(
        self,
        name: str,
        trace: TraceContext,
        parent_span_id: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """TraceSpan başlatıcı.

        Args:
            name: Span tanımlayıcı adı (örn: 'llm_call_fundamental', 'debate_round_1').
            trace: Bağlı olduğu ana TraceContext örneği.
            parent_span_id: Üst span kimliği (varsa).
            metadata: Span başlatılırken eklenen başlangıç metaverileri.
        """
        self.span_id: str = uuid.uuid4().hex[:8]
        self.name: str = name
        self.trace: TraceContext = trace
        self.parent_span_id: str = parent_span_id
        self.metadata: dict[str, Any] = dict(metadata or {})
        self.start_time: datetime = datetime.now(UTC)
        self.end_time: datetime | None = None
        self.duration_ms: float = 0.0
        self.status: str = "running"
        self.error_message: str | None = None
        self._tokens: list[tuple[ContextVar[Any], Token[Any]]] = []

    def __enter__(self) -> TraceSpan:
        """Senkron bağlam yöneticisi girişi.

        Returns:
            TraceSpan: Aktif span örneği.
        """
        self._tokens = [
            (_span_id_var, _span_id_var.set(self.span_id)),
            (_parent_span_id_var, _parent_span_id_var.set(self.parent_span_id)),
        ]
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: Any,
    ) -> bool | None:
        """Senkron bağlam yöneticisi çıkışı.

        Args:
            exc_type: Hata tipi.
            exc_val: Hata nesnesi.
            exc_tb: Hata traceback nesnesi.

        Returns:
            bool | None: İstisnanın yutulup yutulmayacağı (False: üst katmana iletilir).
        """
        self._finish(exc_val)
        for var, token in reversed(self._tokens):
            var.reset(token)
        return False

    async def __aenter__(self) -> TraceSpan:
        """Asenkron bağlam yöneticisi girişi.

        Returns:
            TraceSpan: Aktif span örneği.
        """
        return self.__enter__()

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: Any,
    ) -> bool | None:
        """Asenkron bağlam yöneticisi çıkışı.

        Args:
            exc_type: Hata tipi.
            exc_val: Hata nesnesi.
            exc_tb: Hata traceback nesnesi.

        Returns:
            bool | None: İstisnanın yutulup yutulmayacağı (False: üst katmana iletilir).
        """
        return self.__exit__(exc_type, exc_val, exc_tb)

    def set_attribute(self, key: str, value: Any) -> None:
        """Span için ek özellik veya öznitelik kaydeder.

        Args:
            key: Özellik anahtarı.
            value: Serileştirilebilir değer.
        """
        self.metadata[key] = value

    def _finish(self, exc: BaseException | None) -> None:
        """Span tamamlanma mantığı."""
        self.end_time = datetime.now(UTC)
        self.duration_ms = max(0.0, (self.end_time - self.start_time).total_seconds() * 1000.0)
        if exc is not None:
            self.status = "error"
            self.error_message = f"{type(exc).__name__}: {str(exc)}"
            self.trace.record_error(exc)
        else:
            self.status = "completed"
        self.trace._record_span(self)

    def to_dict(self) -> dict[str, Any]:
        """Span verisini yapısal sözlük olarak döndürür.

        Returns:
            dict[str, Any]: Yapılandırılmış span verisi.
        """
        return {
            "span_id": self.span_id,
            "name": self.name,
            "parent_span_id": self.parent_span_id,
            "status": self.status,
            "duration_ms": round(self.duration_ms, 3),
            "start_time": self.start_time.isoformat(),
            "end_time": self.end_time.isoformat() if self.end_time else None,
            "error_message": self.error_message,
            "metadata": self.metadata,
        }

    def __repr__(self) -> str:
        """Span temsil metni."""
        return (
            f"TraceSpan(name={self.name!r}, span_id={self.span_id!r}, "
            f"status={self.status!r}, duration_ms={self.duration_ms:.2f})"
        )


class _PhaseContext:
    """Belirli bir faz aralığını yöneten bağlam yöneticisi."""

    def __init__(self, trace: TraceContext, phase_name: str) -> None:
        self.trace = trace
        self.phase_name = phase_name
        self._token: Token[str] | None = None

    def __enter__(self) -> TraceContext:
        self._token = _phase_var.set(self.phase_name)
        return self.trace

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: Any,
    ) -> bool | None:
        if self._token is not None:
            _phase_var.reset(self._token)
        return False

    async def __aenter__(self) -> TraceContext:
        return self.__enter__()

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: Any,
    ) -> bool | None:
        return self.__exit__(exc_type, exc_val, exc_tb)

    def __repr__(self) -> str:
        return f"_PhaseContext(phase_name={self.phase_name!r})"


class TraceContext:
    """Trace context — bir pipeline çalışmasının tüm aşamalarını ve span'lerini takip eder.

    Her pipeline çağrısında yeni veya devralınan bir trace oluşturulur.
    Senkron ('with') ve asenkron ('async with') bağlam yönetimini, thread güvenliğini,
    metrik toplama ve token kullanım istatistiklerini tam destekler.
    """

    def __init__(
        self,
        ticker: str = "",
        trace_id: str | None = None,
        parent_trace_id: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """TraceContext başlatıcı.

        Args:
            ticker: Takip edilen hisse kodu (örn: 'THYAO').
            trace_id: Özel izleme kimliği; boşsa otomatik UUID üretilir.
            parent_trace_id: Üst izleme kimliği (dağıtık çağrılar için).
            metadata: Başlangıç metaveri sözlüğü.
        """
        self.trace_id: str = trace_id or f"trc_{uuid.uuid4().hex[:12]}"
        self.parent_trace_id: str = parent_trace_id
        self.ticker: str = ticker.strip().upper() if ticker else ""
        self._start_time: datetime = datetime.now(UTC)
        self._end_time: datetime | None = None
        self._tokens: list[tuple[ContextVar[Any], Token[Any]]] = []

        # Thread-safe metrik ve span koleksiyonları
        self._lock: threading.Lock = threading.Lock()
        self._spans: list[TraceSpan] = []
        self._metrics: dict[str, float] = {}
        self._attributes: dict[str, Any] = dict(metadata or {})
        self._errors: list[dict[str, Any]] = []

        # Token ve maliyet sayacı
        self.total_prompt_tokens: int = 0
        self.total_completion_tokens: int = 0
        self.total_cost_usd: float = 0.0

    def __enter__(self) -> TraceContext:
        """Senkron bağlam yöneticisi girişi."""
        self._tokens = [
            (_trace_id_var, _trace_id_var.set(self.trace_id)),
            (_ticker_var, _ticker_var.set(self.ticker)),
            (_phase_var, _phase_var.set("INIT")),
            (_current_trace_var, _current_trace_var.set(self)),
        ]
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: Any,
    ) -> bool | None:
        """Senkron bağlam yöneticisi çıkışı."""
        self._finish(exc_val)
        for var, token in reversed(self._tokens):
            var.reset(token)
        return False

    async def __aenter__(self) -> TraceContext:
        """Asenkron bağlam yöneticisi girişi."""
        return self.__enter__()

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: Any,
    ) -> bool | None:
        """Asenkron bağlam yöneticisi çıkışı."""
        return self.__exit__(exc_type, exc_val, exc_tb)

    def phase(self, phase_name: str) -> _PhaseContext:
        """Belirtilen faz için scoped bağlam yöneticisi döner.

        Kullanım:
            with trace.phase("PHASE 1: RESEARCH"):
                ...
            async with trace.phase("PHASE 2: DEBATE"):
                ...

        Args:
            phase_name: Aşama adı.

        Returns:
            _PhaseContext: Bağlam yöneticisi.
        """
        return _PhaseContext(self, phase_name)

    def set_phase(self, phase: str) -> None:
        """Mevcut fazı doğrudan ayarla.

        Args:
            phase: Aşama başlığı (örn: 'PHASE 1: PARALLEL RESEARCH').
        """
        _phase_var.set(phase)

    def span(self, name: str, metadata: dict[str, Any] | None = None) -> TraceSpan:
        """Yeni bir alt span oluşturur.

        Args:
            name: Span tanımlayıcı adı.
            metadata: İsteğe bağlı başlangıç metaverileri.

        Returns:
            TraceSpan: Senkron veya asenkron kullanılabilir span nesnesi.
        """
        current_span_id = _span_id_var.get()
        return TraceSpan(
            name=name,
            trace=self,
            parent_span_id=current_span_id,
            metadata=metadata,
        )

    def _record_span(self, span: TraceSpan) -> None:
        """Tamamlanan span'i thread-safe olarak kaydeder."""
        with self._lock:
            self._spans.append(span)

    def set_attribute(self, key: str, value: Any) -> None:
        """İzleme bağlamına ek öznitelik ekler veya günceller.

        Args:
            key: Öznitelik adı.
            value: Değer.
        """
        with self._lock:
            self._attributes[key] = value

    def record_metric(self, name: str, value: float) -> None:
        """Sayısal bir metrik kaydeder (örn: confidence_score, duration_ms).

        Args:
            name: Metrik adı.
            value: Sayısal değer (NaN veya Inf korumalı).
        """
        safe_value = 0.0 if (value != value or value == float("inf") or value == float("-inf")) else float(value)
        with self._lock:
            self._metrics[name] = safe_value

    def record_error(self, error: BaseException) -> None:
        """Trace bünyesinde oluşan hatayı yapısal olarak kaydeder.

        Args:
            error: Yakalanan istisna nesnesi.
        """
        error_entry = {
            "timestamp": datetime.now(UTC).isoformat(),
            "type": type(error).__name__,
            "message": str(error),
            "phase": _phase_var.get(),
            "span_id": _span_id_var.get(),
        }
        with self._lock:
            self._errors.append(error_entry)

    def record_llm_usage(
        self,
        prompt_tokens: int,
        completion_tokens: int,
        cost_usd: float = 0.0,
    ) -> None:
        """LLM token kullanımını ve maliyetini kümülatif olarak kaydeder.

        Args:
            prompt_tokens: Giriş token sayısı.
            completion_tokens: Çıkış token sayısı.
            cost_usd: Tahmini maliyet (dolar).
        """
        with self._lock:
            self.total_prompt_tokens += max(0, prompt_tokens)
            self.total_completion_tokens += max(0, completion_tokens)
            if cost_usd > 0.0 and cost_usd == cost_usd and cost_usd != float("inf"):
                self.total_cost_usd += cost_usd

    def _finish(self, exc: BaseException | None) -> None:
        """Trace kapanış mantığı."""
        self._end_time = datetime.now(UTC)
        if exc is not None:
            self.record_error(exc)

    def elapsed_ms(self) -> float:
        """Trace başlangıcından itibaren geçen toplam süreyi (milisaniye) döner.

        Returns:
            float: Geçen süre (ms).
        """
        end = self._end_time or datetime.now(UTC)
        return max(0.0, (end - self._start_time).total_seconds() * 1000.0)

    def log_fields(self) -> dict[str, Any]:
        """structlog için standart bağlam sözlüğü döndürür.

        Returns:
            dict[str, Any]: Loglama alanları.
        """
        return {
            "trace_id": self.trace_id,
            "ticker": self.ticker,
            "phase": _phase_var.get(),
            "span_id": _span_id_var.get(),
        }

    def to_dict(self) -> dict[str, Any]:
        """Trace'in tüm span'ler, metrikler ve kullanım verileriyle tam dökümünü üretir.

        Returns:
            dict[str, Any]: Yapısal trace özeti.
        """
        with self._lock:
            spans_dump = [s.to_dict() for s in self._spans]
            metrics_dump = dict(self._metrics)
            attrs_dump = dict(self._attributes)
            errors_dump = list(self._errors)
            p_tokens = self.total_prompt_tokens
            c_tokens = self.total_completion_tokens
            cost = self.total_cost_usd

        return {
            "trace_id": self.trace_id,
            "parent_trace_id": self.parent_trace_id,
            "ticker": self.ticker,
            "status": "error" if errors_dump else "success",
            "start_time": self._start_time.isoformat(),
            "end_time": self._end_time.isoformat() if self._end_time else None,
            "duration_ms": round(self.elapsed_ms(), 3),
            "tokens": {
                "prompt_tokens": p_tokens,
                "completion_tokens": c_tokens,
                "total_tokens": p_tokens + c_tokens,
                "cost_usd": round(cost, 6),
            },
            "metrics": metrics_dump,
            "attributes": attrs_dump,
            "errors": errors_dump,
            "spans_count": len(spans_dump),
            "spans": spans_dump,
        }

    def to_json(self) -> str:
        """Trace özetini orjson kullanarak yüksek hızda JSON string'e dönüştürür.

        Returns:
            str: JSON biçimli trace verisi.
        """
        return orjson.dumps(
            self.to_dict(),
            option=orjson.OPT_INDENT_2 | orjson.OPT_NON_STR_KEYS,
        ).decode("utf-8")

    def __repr__(self) -> str:
        """TraceContext temsil metni."""
        return (
            f"TraceContext(trace_id={self.trace_id!r}, ticker={self.ticker!r}, "
            f"spans={len(self._spans)}, elapsed_ms={self.elapsed_ms():.2f})"
        )


def get_trace_id() -> str:
    """Mevcut trace ID'yi döner (aktif context yoksa boş string).

    Returns:
        str: Aktif trace ID.
    """
    return _trace_id_var.get()


def get_ticker() -> str:
    """Mevcut ticker'ı döner (aktif context yoksa boş string).

    Returns:
        str: Aktif ticker sembolü.
    """
    return _ticker_var.get()


def get_phase() -> str:
    """Mevcut fazı döner (aktif context yoksa boş string).

    Returns:
        str: Aktif faz tanımı.
    """
    return _phase_var.get()


def get_span_id() -> str:
    """Mevcut span ID'yi döner (aktif span yoksa boş string).

    Returns:
        str: Aktif span ID.
    """
    return _span_id_var.get()


def get_current_trace() -> TraceContext | None:
    """Mevcut aktif TraceContext nesnesini döner.

    Returns:
        TraceContext | None: Aktif trace context veya None.
    """
    return _current_trace_var.get()


def copy_trace_context() -> dict[str, str]:
    """Mevcut trace context değişkenlerini sözlük olarak kopyalar.

    Farklı bir thread'e veya arka plan işçisine bağlam aktarımı yaparken kullanılır.

    Returns:
        dict[str, str]: Context değişkenleri anlık görüntüsü.
    """
    return {
        "trace_id": _trace_id_var.get(),
        "ticker": _ticker_var.get(),
        "phase": _phase_var.get(),
        "span_id": _span_id_var.get(),
        "parent_span_id": _parent_span_id_var.get(),
    }


def run_with_trace[T](
    context_snapshot: dict[str, str],
    func: Callable[..., T],
    *args: Any,
    **kwargs: Any,
) -> T:
    """Verilen context anlık görüntüsünü yükleyerek fonksiyonu yürütür.

    Thread havuzları ve asyncio.to_thread çağrılarında bağlam kaybını önler.

    Args:
        context_snapshot: copy_trace_context() ile üretilmiş sözlük.
        func: Yürütülecek çağrılabilir fonksiyon.
        *args: Pozisyonel argümanlar.
        **kwargs: İsimli argümanlar.

    Returns:
        T: Fonksiyonun dönüş değeri.
    """
    token_trace = _trace_id_var.set(context_snapshot.get("trace_id", ""))
    token_ticker = _ticker_var.set(context_snapshot.get("ticker", ""))
    token_phase = _phase_var.set(context_snapshot.get("phase", ""))
    token_span = _span_id_var.set(context_snapshot.get("span_id", ""))
    token_parent = _parent_span_id_var.set(context_snapshot.get("parent_span_id", ""))
    try:
        return func(*args, **kwargs)
    finally:
        _trace_id_var.reset(token_trace)
        _ticker_var.reset(token_ticker)
        _phase_var.reset(token_phase)
        _span_id_var.reset(token_span)
        _parent_span_id_var.reset(token_parent)


def trace_processor(
    logger: Any,
    method: str,
    event_dict: dict[str, Any],
) -> dict[str, Any]:
    """structlog işlemcisi — loglara otomatik olarak trace ve span verilerini ekler.

    structlog.configure(processors=[..., trace_processor, ...]) olarak kullanılır.

    Args:
        logger: structlog logger nesnesi.
        method: Log çağrı metodu (info, debug vb.).
        event_dict: İşlenen log olay sözlüğü.

    Returns:
        dict[str, Any]: Zenginleştirilmiş log olay sözlüğü.
    """
    trace_id = _trace_id_var.get()
    if trace_id:
        event_dict["trace_id"] = trace_id

    ticker = _ticker_var.get()
    if ticker:
        event_dict["ticker"] = ticker

    phase = _phase_var.get()
    if phase:
        event_dict["phase"] = phase

    span_id = _span_id_var.get()
    if span_id:
        event_dict["span_id"] = span_id

    return event_dict
