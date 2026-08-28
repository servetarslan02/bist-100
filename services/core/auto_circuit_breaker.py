"""
ALPHA BIST â€” Automatic Circuit Breaker Trigger Engine

Otomatik devre kesici tetikleme:
- Fiyat deÄŸiÅŸimini izler
- EÅŸik aÅŸÄ±ldÄ±ÄŸÄ±nda otomatik tetikler
- EBDKS iÃ§in BIST-100 endeks deÄŸiÅŸimini izler
- Tetikleme geÃ§miÅŸini kaydeder

Kaynak: Borsa Ä°stanbul, AÄŸustos 2025 duyurularÄ±
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Any

import structlog

from services.core.market_session_fsm import BISTMarketPhase, bist_session_fsm

logger = structlog.get_logger(__name__)


@dataclass
class CircuitBreakerEvent:
    """Devre kesici tetikleme olayÄ±."""

    ticker: str
    event_type: str  # "PAY_BAZINDA" | "EBDKS"
    trigger_price: float
    reference_price: float
    change_pct: float
    threshold_pct: float
    triggered_at: datetime
    duration_minutes: int
    feature_code: str | None = None
    market_phase: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "ticker": self.ticker,
            "event_type": self.event_type,
            "trigger_price": self.trigger_price,
            "reference_price": self.reference_price,
            "change_pct": round(self.change_pct, 2),
            "threshold_pct": self.threshold_pct,
            "triggered_at": self.triggered_at.isoformat(),
            "duration_minutes": self.duration_minutes,
            "feature_code": self.feature_code,
            "market_phase": self.market_phase,
        }


class AutoCircuitBreakerEngine:
    """Otomatik devre kesici tetikleme motoru.

    Her fiyat gÃ¼ncellemesinde:
    1. Pay bazÄ±nda devre kesici eÅŸiklerini kontrol eder
    2. BIST-100 endeks deÄŸiÅŸimini izler (EBDKS)
    3. EÅŸik aÅŸÄ±ldÄ±ÄŸÄ±nda otomatik tetikler
    """

    def __init__(self):
        self._events: list[CircuitBreakerEvent] = []
        self._triggered_today: dict[str, list[float]] = {}  # ticker â†’ [threshold_pct, ...]
        self._bist100_reference: float = 0.0  # Ã–nceki kapanÄ±ÅŸ
        self._bist100_current: float = 0.0
        self._ebdks_triggered_today: int = 0

    def set_bist100_reference(self, reference_price: float):
        """BIST-100 referans fiyatÄ±nÄ± (Ã¶nceki kapanÄ±ÅŸ) ayarla."""
        self._bist100_reference = reference_price

    def update_bist100_price(self, current_price: float) -> CircuitBreakerEvent | None:
        """BIST-100 gÃ¼ncel fiyatÄ±nÄ± gÃ¼ncelle ve EBDKS kontrolÃ¼ yap.

        Args:
            current_price: BIST-100 gÃ¼ncel endeks deÄŸeri

        Returns:
            Tetiklenirse CircuitBreakerEvent, yoksa None
        """
        self._bist100_current = current_price

        if self._bist100_reference <= 0:
            return None

        # Piyasa aÃ§Ä±k deÄŸilse kontrol etme
        phase = bist_session_fsm.get_phase()
        if phase == BISTMarketPhase.CLOSED:
            return None

        change_pct = ((current_price / self._bist100_reference) - 1) * 100

        # EBDKS: BIST-100 %6 veya daha fazla dÃ¼ÅŸÃ¼ÅŸ
        if change_pct <= -bist_session_fsm.EBDKS_THRESHOLD_PCT:
            # BugÃ¼n zaten tetiklendi mi kontrol et (aynÄ± eÅŸik seviyesinde tekrar tetiklenmemeli)
            if self._ebdks_triggered_today == 0 or (
                self._ebdks_triggered_today > 0 and change_pct <= -(bist_session_fsm.EBDKS_THRESHOLD_PCT + 2)
            ):
                # Ä°lk tetikleme veya ek %2 dÃ¼ÅŸÃ¼ÅŸ daha

                # Ã–zellik kodu belirle (ÅŸimdilik varsayÄ±lan)
                feature_code = None  # GerÃ§ek sistemde hisse Ã¶zellik kodundan alÄ±nÄ±r

                bist_session_fsm.trigger_ebdks(feature_code=feature_code)

                event = CircuitBreakerEvent(
                    ticker="BIST-100",
                    event_type="EBDKS",
                    trigger_price=current_price,
                    reference_price=self._bist100_reference,
                    change_pct=change_pct,
                    threshold_pct=bist_session_fsm.EBDKS_THRESHOLD_PCT,
                    triggered_at=bist_session_fsm.now_istanbul(),
                    duration_minutes=bist_session_fsm.EBDKS_DEFAULT_DURATION,
                    feature_code=feature_code,
                    market_phase=phase.value,
                )
                self._events.append(event)
                self._ebdks_triggered_today += 1

                logger.warning(
                    "EBDKS OTOMATÄ°K TETÄ°KLENDÄ°",
                    change_pct=f"{change_pct:.2f}%",
                    threshold=f"%{bist_session_fsm.EBDKS_THRESHOLD_PCT}",
                    current=current_price,
                    reference=self._bist100_reference,
                    count_today=self._ebdks_triggered_today,
                )

                return event

        return None

    def check_pay_circuit_breaker(
        self,
        ticker: str,
        current_price: float,
        reference_price: float,
        market_type: str = "ana",
    ) -> CircuitBreakerEvent | None:
        """Pay bazÄ±nda devre kesici kontrolÃ¼.

        Args:
            ticker: Hisse kodu
            current_price: GÃ¼ncel fiyat
            reference_price: Ã–nceki kapanÄ±ÅŸ / baz fiyat
            market_type: Pazar tipi (yildiz, ana, alt)

        Returns:
            Tetiklenirse CircuitBreakerEvent, yoksa None
        """
        if reference_price <= 0 or current_price <= 0:
            return None

        # Piyasa aÃ§Ä±k deÄŸilse kontrol etme
        phase = bist_session_fsm.get_phase()
        if phase == BISTMarketPhase.CLOSED:
            return None

        change_pct = ((current_price / reference_price) - 1) * 100

        # Pazar bazÄ±nda eÅŸikleri al
        thresholds = bist_session_fsm.CIRCUIT_BREAKER_THRESHOLDS.get(
            market_type, bist_session_fsm.CIRCUIT_BREAKER_THRESHOLDS["ana"]
        )

        # BugÃ¼n bu hisse iÃ§in hangi eÅŸikler tetiklendi?
        triggered_thresholds = self._triggered_today.get(ticker, [])

        for threshold in thresholds:
            if change_pct <= -threshold and threshold not in triggered_thresholds:
                # Devre kesici tetikle
                bist_session_fsm.trigger_circuit_breaker(ticker)

                event = CircuitBreakerEvent(
                    ticker=ticker,
                    event_type="PAY_BAZINDA",
                    trigger_price=current_price,
                    reference_price=reference_price,
                    change_pct=change_pct,
                    threshold_pct=threshold,
                    triggered_at=bist_session_fsm.now_istanbul(),
                    duration_minutes=bist_session_fsm.CIRCUIT_BREAKER_DURATION_MINUTES,
                    market_phase=phase.value,
                )
                self._events.append(event)

                if ticker not in self._triggered_today:
                    self._triggered_today[ticker] = []
                self._triggered_today[ticker].append(threshold)

                logger.warning(
                    "PAY BAZINDA DEVRE KESICI TETÄ°KLENDÄ°",
                    ticker=ticker,
                    change_pct=f"{change_pct:.2f}%",
                    threshold=f"%{threshold}",
                    current=current_price,
                    reference=reference_price,
                )

                return event

        return None

    def reset_daily(self):
        """GÃ¼nlÃ¼k sayaÃ§larÄ± sÄ±fÄ±rla (seans sonunda Ã§aÄŸrÄ±lÄ±r)."""
        self._triggered_today.clear()
        self._ebdks_triggered_today = 0
        bist_session_fsm.clear_ebdks()
        logger.info("Devre kesici gÃ¼nlÃ¼k sayaÃ§larÄ± sÄ±fÄ±rlandÄ±")

    def get_events_today(self) -> list[dict[str, Any]]:
        """BugÃ¼nkÃ¼ tÃ¼m devre kesici olaylarÄ±nÄ± dÃ¶ndÃ¼r."""
        return [e.to_dict() for e in self._events]

    def get_status(self) -> dict[str, Any]:
        """Durum bilgisi."""
        return {
            "ebdks_triggered_today": self._ebdks_triggered_today,
            "bist100_reference": self._bist100_reference,
            "bist100_current": self._bist100_current,
            "bist100_change_pct": round(((self._bist100_current / self._bist100_reference) - 1) * 100, 2)
            if self._bist100_reference > 0
            else 0,
            "pay_circuit_breakers_today": len(self._triggered_today),
            "total_events_today": len(self._events),
            "ebdks_active": bist_session_fsm.is_ebdks_active(),
            "ebdks_late_session": bist_session_fsm.is_ebdks_late_session(),
        }


# Singleton
auto_circuit_breaker = AutoCircuitBreakerEngine()

