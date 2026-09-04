"""
ALPHA BIST — Trace Context

Pipeline çalışmasının tüm aşamalarını tek trace ID ile takip etmek için.
structlog ile entegre çalışır.

Kullanım:
    with TraceContext(ticker="THYAO") as trace:
        logger.info("Pipeline started", **trace.log_fields())
        # ... tüm alt işlemler trace ID'yi otomatik alır
"""

import uuid
from contextvars import ContextVar
from datetime import UTC, datetime
from typing import Any


# Context variable — async-safe
_trace_id_var: ContextVar[str] = ContextVar("trace_id", default="")
_ticker_var: ContextVar[str] = ContextVar("ticker", default="")
_phase_var: ContextVar[str] = ContextVar("phase", default="")


class TraceContext:
    """Trace context — bir pipeline çalışmasının tüm aşamalarını takip eder.

    Her pipeline.run() çağrısında yeni bir trace oluşturulur.
    Tüm alt modüller (agent, debate, risk, synthesis) aynı trace ID'yi kullanır.

    Kullanım:
        with TraceContext(ticker="THYAO") as trace:
            logger.info("Started", **trace.log_fields())
            # ... work ...
            logger.info("Done", **trace.log_fields())
    """

    def __init__(self, ticker: str = "", trace_id: str | None = None):
        self.trace_id = trace_id or uuid.uuid4().hex[:12]
        self.ticker = ticker
        self._start_time = datetime.now(UTC)
        self._tokens: list[tuple[ContextVar, Any]] = []

    def __enter__(self) -> "TraceContext":
        self._tokens = [
            (_trace_id_var, _trace_id_var.set(self.trace_id)),
            (_ticker_var, _ticker_var.set(self.ticker)),
            (_phase_var, _phase_var.set("")),
        ]
        return self

    def __exit__(self, *args: Any) -> None:
        for var, token in reversed(self._tokens):
            var.reset(token)

    def set_phase(self, phase: str) -> None:
        """Mevcut fazı ayarla (PHASE 1: PARALLEL RESEARCH vb.)."""
        _phase_var.set(phase)

    def log_fields(self) -> dict[str, Any]:
        """structlog için ek alanlar döndürür."""
        return {
            "trace_id": self.trace_id,
            "ticker": self.ticker,
            "phase": _phase_var.get(),
        }

    def elapsed_ms(self) -> float:
        """Geçen süre (ms)."""
        return (datetime.now(UTC) - self._start_time).total_seconds() * 1000

    def __repr__(self) -> str:
        return f"TraceContext(trace_id={self.trace_id!r}, ticker={self.ticker!r})"


def get_trace_id() -> str:
    """Mevcut trace ID'yi getir (context yoksa boş string)."""
    return _trace_id_var.get()


def get_ticker() -> str:
    """Mevcut ticker'ı getir (context yoksa boş string)."""
    return _ticker_var.get()


def get_phase() -> str:
    """Mevcut fazı getir (context yoksa boş string)."""
    return _phase_var.get()


def trace_processor(logger: Any, method: str, event_dict: dict[str, Any]) -> dict[str, Any]:
    """structlog processor — otomatik trace ID ekler.

    structlog.configure(processors=[..., trace_processor, ...]) şeklinde kullanılır.
    """
    trace_id = get_trace_id()
    if trace_id:
        event_dict["trace_id"] = trace_id
    ticker = get_ticker()
    if ticker:
        event_dict["ticker"] = ticker
    phase = get_phase()
    if phase:
        event_dict["phase"] = phase
    return event_dict
