"""
ALPHA BIST — Halt Monitor

Şirket bazlı durdurma takibi:
- KAP açıklaması öncesi durdurma
- Bedelsiz sermaye artırımı
- Birleşme/devralma
- Olağanüstü genel kurul
- SPK geçici işlem yasağı
"""

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import functools
import structlog
from opentelemetry import trace

logger = structlog.get_logger(__name__)
tracer = trace.get_tracer("alpha-bist.halt_monitor")

def otel_trace(span_name: str):
    """Decorator to wrap a method in an OTel span."""
    def decorator(func):
        @functools.wraps(func)
        def wrapper(self, *args, **kwargs):
            with tracer.start_as_current_span(span_name):
                return func(self, *args, **kwargs)
        return wrapper
    return decorator


@dataclass
class HaltStatus:
    halted: bool
    reason: str = ""
    halt_type: str = ""  # KAP, CORPORATE, SPK, CIRCUIT_BREAKER
    expected_resume: str | None = None
    action: str = ""  # "WAIT", "CANCEL_ORDERS", "NO_ACTION"
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "halted": self.halted,
            "reason": self.reason,
            "halt_type": self.halt_type,
            "expected_resume": self.expected_resume,
            "action": self.action,
        }


class HaltMonitor:
    """Şirket bazlı durdurma takibi — DuckDB (state_store) persistence ile."""

    def __init__(self):
        self._halted_tickers: dict[str, HaltStatus] = {}
        self._restore_state()

    @otel_trace("halt_monitor.add_halt")
    def add_halt(
        self,
        ticker: str,
        reason: str,
        halt_type: str = "KAP",
        expected_resume: str | None = None,
    ):
        """Hisse durdurma ekle."""
        self._halted_tickers[ticker] = HaltStatus(
            halted=True,
            reason=reason,
            halt_type=halt_type,
            expected_resume=expected_resume,
            action="WAIT",
        )
        self._persist_state(ticker)
        logger.info("Halt added", ticker=ticker, reason=reason, type=halt_type)

    @otel_trace("halt_monitor.remove_halt")
    def remove_halt(self, ticker: str):
        """Hisse durdurma kaldır."""
        if ticker in self._halted_tickers:
            del self._halted_tickers[ticker]
            self._remove_persisted(ticker)
            logger.info("Halt removed", ticker=ticker)

    @otel_trace("halt_monitor.check_halt")
    def check_halt(self, ticker: str) -> HaltStatus:
        """Hisse durdurulmuş mu kontrol et."""
        if ticker in self._halted_tickers:
            return self._halted_tickers[ticker]

        return HaltStatus(halted=False, action="NO_ACTION")

    def get_all_halted(self) -> dict[str, HaltStatus]:
        """Tüm durdurulan hisseleri getir."""
        return dict(self._halted_tickers)

    def is_halted(self, ticker: str) -> bool:
        """Hisse durdurulmuş mu?"""
        return ticker in self._halted_tickers

    def _persist_state(self, ticker: str):
        """Halt durumunu SQLite'a kaydet."""
        try:
            from .state_store import state_store

            status = self._halted_tickers.get(ticker)
            if status:
                with state_store._connect() as conn:
                    conn.execute(
                        "INSERT OR REPLACE INTO halt_states (ticker, reason, halt_type, expected_resume, action, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
                        (
                            ticker,
                            status.reason,
                            status.halt_type,
                            status.expected_resume,
                            status.action,
                            datetime.now(UTC).isoformat(),
                        ),
                    )
        except Exception as e:
            logger.debug("Halt persist skipped", ticker=ticker, error=str(e))

    def _remove_persisted(self, ticker: str):
        """Halt durumunu SQLite'dan sil."""
        try:
            from .state_store import state_store

            with state_store._connect() as conn:
                conn.execute("DELETE FROM halt_states WHERE ticker = ?", (ticker,))
        except Exception as e:
            logger.debug("Halt remove persist skipped", ticker=ticker, error=str(e))

    def _restore_state(self):
        """Halt durumunu SQLite'dan geri yükle."""
        try:
            from .state_store import state_store

            with state_store._connect() as conn:
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS halt_states (
                        ticker TEXT PRIMARY KEY,
                        reason TEXT,
                        halt_type TEXT,
                        expected_resume TEXT,
                        action TEXT,
                        updated_at TEXT
                    )
                """)
                rows = conn.execute(
                    "SELECT ticker, reason, halt_type, expected_resume, action FROM halt_states"
                ).fetchall()
                for row in rows:
                    self._halted_tickers[row[0]] = HaltStatus(
                        halted=True,
                        reason=row[1],
                        halt_type=row[2],
                        expected_resume=row[3],
                        action=row[4],
                    )
                if rows:
                    logger.info("Halt states restored", count=len(rows))
        except Exception as e:
            logger.debug("Halt restore skipped", error=str(e))


# Singleton
halt_monitor = HaltMonitor()
