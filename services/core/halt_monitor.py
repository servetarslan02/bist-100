"""
ALPHA BIST — Halt Monitor

Şirket bazlı durdurma takibi:
- KAP açıklaması öncesi durdurma
- Bedelsiz sermaye artırımı
- Birleşme/devralma
- Olağanüstü genel kurul
- SPK geçici işlem yasağı
"""

from typing import Dict, Any, Optional
from dataclasses import dataclass, field
import structlog

logger = structlog.get_logger()


@dataclass
class HaltStatus:
    halted: bool
    reason: str = ""
    halt_type: str = ""          # KAP, CORPORATE, SPK, CIRCUIT_BREAKER
    expected_resume: Optional[str] = None
    action: str = ""             # "WAIT", "CANCEL_ORDERS", "NO_ACTION"
    details: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "halted": self.halted,
            "reason": self.reason,
            "halt_type": self.halt_type,
            "expected_resume": self.expected_resume,
            "action": self.action,
        }


class HaltMonitor:
    """Şirket bazlı durdurma takibi."""

    def __init__(self):
        self._halted_tickers: Dict[str, HaltStatus] = {}

    def add_halt(
        self,
        ticker: str,
        reason: str,
        halt_type: str = "KAP",
        expected_resume: Optional[str] = None,
    ):
        """Hisse durdurma ekle."""
        self._halted_tickers[ticker] = HaltStatus(
            halted=True,
            reason=reason,
            halt_type=halt_type,
            expected_resume=expected_resume,
            action="WAIT",
        )
        logger.info("Halt added", ticker=ticker, reason=reason, type=halt_type)

    def remove_halt(self, ticker: str):
        """Hisse durdurma kaldır."""
        if ticker in self._halted_tickers:
            del self._halted_tickers[ticker]
            logger.info("Halt removed", ticker=ticker)

    def check_halt(self, ticker: str) -> HaltStatus:
        """Hisse durdurulmuş mu kontrol et."""
        if ticker in self._halted_tickers:
            return self._halted_tickers[ticker]

        return HaltStatus(halted=False, action="NO_ACTION")

    def get_all_halted(self) -> Dict[str, HaltStatus]:
        """Tüm durdurulan hisseleri getir."""
        return dict(self._halted_tickers)

    def is_halted(self, ticker: str) -> bool:
        """Hisse durdurulmuş mu?"""
        return ticker in self._halted_tickers


# Singleton
halt_monitor = HaltMonitor()
