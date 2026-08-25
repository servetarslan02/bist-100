"""
ALPHA BIST — Drawdown Response System v1.0

Otomatik drawdown yönetimi.
Drawdown eşiğine göre otomatik aksiyon alır.

Kaynaklar:
- arXiv 2605.19337 — Agentic Trading Meta-Analiz (2026)
- ScienceDirect — Dynamic Market-Aware Portfolio Optimization (2026)
"""

from typing import List, Optional
from dataclasses import dataclass
from enum import Enum
from datetime import datetime, timezone
import structlog

logger = structlog.get_logger()


class DrawdownAction(str, Enum):
    NONE = "NONE"
    REDUCE_SIZE = "REDUCE_SIZE"           # Pozisyon boyutunu azalt
    STOP_NEW = "STOP_NEW"                 # Yeni pozisyon durdur
    CLOSE_POSITIONS = "CLOSE_POSITIONS"   # Pozisyon kapat
    HALT_SYSTEM = "HALT_SYSTEM"           # Sistem durdur


class DrawdownSeverity(str, Enum):
    NORMAL = "NORMAL"
    WARNING = "WARNING"
    CRITICAL = "CRITICAL"
    EMERGENCY = "EMERGENCY"


@dataclass
class DrawdownState:
    """Drawdown durumu."""
    current_drawdown_pct: float
    max_drawdown_pct: float
    peak_equity: float
    current_equity: float
    drawdown_duration_days: int
    action: DrawdownAction
    severity: DrawdownSeverity
    position_scale: float  # 0.0-1.0
    description: str
    timestamp: str


@dataclass
class DrawdownEvent:
    """Drawdown olay kaydı."""
    timestamp: str
    drawdown_pct: float
    action_taken: DrawdownAction
    previous_action: DrawdownAction
    equity_before: float
    equity_after: Optional[float] = None


class DrawdownResponseSystem:
    """Otomatik drawdown yönetim sistemi.

    Eşikler:
    - DD > 5%  → Pozisyon boyutunu %50 azalt (WARNING)
    - DD > 10% → Yeni pozisyon durdur (CRITICAL)
    - DD > 15% → Pozisyon kapat (CRITICAL)
    - DD > 20% → Sistem durdur (EMERGENCY)
    """

    # Drawdown eşikleri ve aksiyonları
    THRESHOLDS = [
        {
            "threshold": 5.0,
            "action": DrawdownAction.REDUCE_SIZE,
            "severity": DrawdownSeverity.WARNING,
            "position_scale": 0.5,
            "description": "Pozisyon boyutunu %50 azalt",
        },
        {
            "threshold": 10.0,
            "action": DrawdownAction.STOP_NEW,
            "severity": DrawdownSeverity.CRITICAL,
            "position_scale": 0.0,
            "description": "Yeni pozisyon alımını durdur",
        },
        {
            "threshold": 15.0,
            "action": DrawdownAction.CLOSE_POSITIONS,
            "severity": DrawdownSeverity.CRITICAL,
            "position_scale": 0.0,
            "description": "Açık pozisyonları kapat",
        },
        {
            "threshold": 20.0,
            "action": DrawdownAction.HALT_SYSTEM,
            "severity": DrawdownSeverity.EMERGENCY,
            "position_scale": 0.0,
            "description": "Ticaret sistemini durdur",
        },
    ]

    # Recovery eşikleri (drawdown azalınca)
    RECOVERY_THRESHOLDS = [
        {"threshold": 3.0, "action": DrawdownAction.NONE, "position_scale": 1.0},
        {"threshold": 1.0, "action": DrawdownAction.NONE, "position_scale": 1.0},
    ]

    def __init__(self):
        self._peak_equity: float = 0.0
        self._current_equity: float = 0.0
        self._current_action: DrawdownAction = DrawdownAction.NONE
        self._drawdown_start: Optional[datetime] = None
        self._events: List[DrawdownEvent] = []
        self._max_drawdown_pct: float = 0.0

    def update_equity(self, current_equity: float) -> DrawdownState:
        """Equity güncelle ve drawdown hesapla.

        Args:
            current_equity: Mevcut equity (TL)

        Returns:
            DrawdownState
        """
        now = datetime.now(timezone.utc)

        # Peak equity güncelle
        if current_equity > self._peak_equity:
            self._peak_equity = current_equity
            self._drawdown_start = None  # Recovery

        self._current_equity = current_equity

        # Drawdown hesapla
        if self._peak_equity <= 0:
            drawdown_pct = 0.0
        else:
            drawdown_pct = ((self._peak_equity - current_equity) / self._peak_equity) * 100

        # Max drawdown güncelle
        self._max_drawdown_pct = max(self._max_drawdown_pct, drawdown_pct)

        # Drawdown süresi
        if drawdown_pct > 0 and self._drawdown_start is None:
            self._drawdown_start = now

        duration_days = 0
        if self._drawdown_start:
            duration_days = (now - self._drawdown_start).days

        # Aksiyon belirle
        previous_action = self._current_action
        action, severity, position_scale, description = self._determine_action(drawdown_pct)

        # Aksiyon değiştiyse event kaydet
        if action != previous_action:
            event = DrawdownEvent(
                timestamp=now.isoformat(),
                drawdown_pct=drawdown_pct,
                action_taken=action,
                previous_action=previous_action,
                equity_before=self._current_equity,
            )
            self._events.append(event)
            if len(self._events) > 500:
                self._events = self._events[-500:]

            logger.warning("Drawdown action changed",
                          drawdown_pct=f"{drawdown_pct:.1f}%",
                          action=action.value,
                          severity=severity.value)

            # KILL_SWITCH_TRIGGERED event publish (audit #5)
            if severity.value == "EMERGENCY":
                try:
                    from services.core.event_bus import publish_event
                    from services.core.event_schema import CanonicalEvent, EventType
                    kill_event = CanonicalEvent(
                        event_type=EventType.KILL_SWITCH_TRIGGERED,
                        payload={
                            "drawdown_pct": round(drawdown_pct, 2),
                            "action": action.value,
                            "equity": current_equity,
                            "peak_equity": self._peak_equity,
                            "description": description,
                        },
                    )
                    publish_event(kill_event, key="system")
                    logger.critical("KILL_SWITCH_TRIGGERED event published",
                                   drawdown_pct=f"{drawdown_pct:.1f}%")
                except Exception as e:
                    logger.error("Failed to publish KILL_SWITCH event", error=str(e))

        self._current_action = action

        return DrawdownState(
            current_drawdown_pct=round(drawdown_pct, 2),
            max_drawdown_pct=round(self._max_drawdown_pct, 2),
            peak_equity=self._peak_equity,
            current_equity=current_equity,
            drawdown_duration_days=duration_days,
            action=action,
            severity=severity,
            position_scale=position_scale,
            description=description,
            timestamp=now.isoformat(),
        )

    def _determine_action(self, drawdown_pct: float) -> tuple:
        """Drawdown yüzdesine göre aksiyon belirle."""
        # Eşikleri tersten kontrol et (en yüksekten en düşüğe)
        for threshold in reversed(self.THRESHOLDS):
            if drawdown_pct >= threshold["threshold"]:
                return (
                    threshold["action"],
                    threshold["severity"],
                    threshold["position_scale"],
                    threshold["description"],
                )

        # Recovery kontrolü
        if drawdown_pct < 1.0:
            return (DrawdownAction.NONE, DrawdownSeverity.NORMAL, 1.0, "Normal durum")

        if drawdown_pct < 3.0:
            return (DrawdownAction.NONE, DrawdownSeverity.NORMAL, 0.9, "Hafif drawdown — izle")

        # 3-5% arası
        return (DrawdownAction.NONE, DrawdownSeverity.WARNING, 0.75, "Dikkat — drawdown artıyor")

    def get_position_size_multiplier(self) -> float:
        """Mevcut drawdown durumuna göre pozisyon boyutu çarpanı."""
        if self._current_equity <= 0 or self._peak_equity <= 0:
            return 1.0

        drawdown_pct = ((self._peak_equity - self._current_equity) / self._peak_equity) * 100

        for threshold in reversed(self.THRESHOLDS):
            if drawdown_pct >= threshold["threshold"]:
                return threshold["position_scale"]

        if drawdown_pct < 3.0:
            return 1.0
        elif drawdown_pct < 5.0:
            return 0.75
        return 0.5

    def is_trading_allowed(self) -> bool:
        """Trading'e izin var mı?"""
        return self._current_action not in [
            DrawdownAction.STOP_NEW,
            DrawdownAction.CLOSE_POSITIONS,
            DrawdownAction.HALT_SYSTEM,
        ]

    def is_system_halted(self) -> bool:
        """Sistem durduruldu mu?"""
        return self._current_action == DrawdownAction.HALT_SYSTEM

    def get_state(self) -> DrawdownState:
        """Mevcut drawdown durumunu al."""
        if self._peak_equity <= 0:
            return DrawdownState(
                current_drawdown_pct=0.0,
                max_drawdown_pct=0.0,
                peak_equity=0.0,
                current_equity=0.0,
                drawdown_duration_days=0,
                action=DrawdownAction.NONE,
                severity=DrawdownSeverity.NORMAL,
                position_scale=1.0,
                description="Henüz equity verisi yok",
                timestamp=datetime.now(timezone.utc).isoformat(),
            )

        drawdown_pct = ((self._peak_equity - self._current_equity) / self._peak_equity) * 100
        action, severity, position_scale, description = self._determine_action(drawdown_pct)

        duration_days = 0
        if self._drawdown_start:
            duration_days = (datetime.now(timezone.utc) - self._drawdown_start).days

        return DrawdownState(
            current_drawdown_pct=round(drawdown_pct, 2),
            max_drawdown_pct=round(self._max_drawdown_pct, 2),
            peak_equity=self._peak_equity,
            current_equity=self._current_equity,
            drawdown_duration_days=duration_days,
            action=action,
            severity=severity,
            position_scale=position_scale,
            description=description,
            timestamp=datetime.now(timezone.utc).isoformat(),
        )

    def get_events(self, limit: int = 50) -> List[DrawdownEvent]:
        """Son drawdown olaylarını al."""
        return self._events[-limit:]

    def reset(self, *, force: bool = False, reason: str = ""):
        """Drawdown sistemini sıfırla.
        
        Args:
            force: True ise kill switch aktif olsa bile sıfırlar
            reason: Sıfırlama nedeni (audit trail için)
        """
        if self._current_action == DrawdownAction.KILL_SWITCH and not force:
            logger.warning("Drawdown reset blocked — kill switch active. Use force=True to override.")
            return
        logger.warning("Drawdown system reset", reason=reason, force=force,
                       peak=self._peak_equity, max_dd=self._max_drawdown_pct)
        self._peak_equity = 0.0
        self._current_equity = 0.0
        self._current_action = DrawdownAction.NONE
        self._drawdown_start = None
        self._events = []
        self._max_drawdown_pct = 0.0

    def get_alert_message(self, state: DrawdownState) -> Optional[str]:
        """Drawdown alert mesajı oluştur."""
        if state.severity == DrawdownSeverity.NORMAL:
            return None

        emoji = {
            DrawdownSeverity.WARNING: "⚠️",
            DrawdownSeverity.CRITICAL: "🔴",
            DrawdownSeverity.EMERGENCY: "🚨",
        }.get(state.severity, "⚠️")

        return (
            f"{emoji} DRAWDOWN ALERT: %{state.current_drawdown_pct:.1f}\n"
            f"Peak: {state.peak_equity:,.0f} TL → Current: {state.current_equity:,.0f} TL\n"
            f"Aksiyon: {state.description}\n"
            f"Süre: {state.drawdown_duration_days} gün"
        )


# Singleton
drawdown_system = DrawdownResponseSystem()
