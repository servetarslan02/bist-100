"""
ALPHA BIST — Daily Workflow v3.0

Tam günlük workflow otomasyonu.
BIST saatlerine göre otomatik job yönetimi.
(2015 BISTECH sonrası tek seans — Eylül 2025 güncel)

Günlük Akış:
09:40-10:00 — PRE-MARKET (Açılış seansı emir toplama)
10:00-18:00 — SÜREKLİ İŞLEM (Tek seans, ara yok)
18:01-18:10 — KAPANIŞ (Kapanış seansı)
18:10-18:30 — POST-MARKET
18:30-23:00 — AFTER-HOURS
23:00-09:40 — NIGHT

Kaynaklar: Borsa İstanbul resmi, Eylül 2025 duyurusu
"""

from typing import Dict, Any, Optional, Callable, Awaitable, List
from datetime import datetime, timezone
from dataclasses import dataclass
import structlog

logger = structlog.get_logger()


@dataclass
class WorkflowPhase:
    """Workflow fazı."""
    name: str
    start_time: str
    end_time: str
    jobs: List[str]
    description: str


@dataclass
class WorkflowStatus:
    """Workflow durumu."""
    current_phase: str
    next_phase: str
    next_phase_in_seconds: float
    jobs_run_today: int
    jobs_failed_today: int
    daily_report_generated: bool
    timestamp: str


class DailyWorkflow:
    """Günlük workflow yöneticisi.

    Her faz için tanımlanmış job'ları otomatik çalıştırır.
    Market session manager ile entegre çalışır.
    """

    # Faz tanımları (2015 BISTECH sonrası tek seans — Eylül 2025 güncel)
    PHASES = {
        "pre_market": WorkflowPhase(
            name="PRE_MARKET",
            start_time="09:40",
            end_time="10:00",
            jobs=["market_data_update", "feature_calculation", "universe_refresh", "regime_detection"],
            description="Piyasa öncesi hazırlık (açılış seansı emir toplama)",
        ),
        "active": WorkflowPhase(
            name="CONTINUOUS",
            start_time="10:00",
            end_time="18:00",
            jobs=["batch_scan", "signal_generation", "risk_monitoring", "health_check"],
            description="Sürekli müzayede — tek seans",
        ),
        "closing": WorkflowPhase(
            name="CLOSING",
            start_time="18:01",
            end_time="18:10",
            jobs=["closing_price_update", "daily_pnl"],
            description="Kapanış seansı",
        ),
        "post_market": WorkflowPhase(
            name="POST_MARKET",
            start_time="18:10",
            end_time="18:30",
            jobs=["persistence", "daily_report", "performance_attribution", "alert_check"],
            description="Piyasa sonrası",
        ),
        "after_hours": WorkflowPhase(
            name="AFTER_HOURS",
            start_time="18:30",
            end_time="23:00",
            jobs=["learning_cycle", "model_drift_detection", "backtest", "health_check"],
            description="Mesai sonrası",
        ),
        "night": WorkflowPhase(
            name="NIGHT",
            start_time="23:00",
            end_time="09:40",
            jobs=["health_check", "backup"],
            description="Gece",
        ),
    }

    # Phase mapping: MarketPhase → workflow phase key
    _PHASE_MAP = {
        "PRE_MARKET": "pre_market",
        "OPENING_AUCTION_COLLECTION": "pre_market",
        "OPENING_AUCTION_DETERMINATION": "pre_market",
        "CONTINUOUS_AUCTION": "active",
        "CIRCUIT_BREAKER_AUCTION": "active",
        "CLOSING_AUCTION_COLLECTION": "closing",
        "CLOSING_AUCTION_DETERMINATION": "closing",
        "CLOSING_PRICE_TRADING": "closing",
        "POST_MARKET": "post_market",
        "AFTER_HOURS": "after_hours",
        "NIGHT": "night",
        "CLOSED": "night",
        # Eski uyumluluk
        "SEANS_1": "active",
        "SEANS_2": "active",
        "BREAK": "night",
    }

    def __init__(self):
        self._handlers: Dict[str, Callable[..., Awaitable[Any]]] = {}
        self._phase_handlers: Dict[str, Callable] = {}
        self._jobs_run_today: int = 0
        self._jobs_failed_today: int = 0
        self._daily_report_generated: bool = False
        self._current_phase: Optional[str] = None

    def register_handler(self, job_type: str, handler: Callable[..., Awaitable[Any]]):
        """Job handler kaydet."""
        self._handlers[job_type] = handler

    def register_phase_handler(self, phase: str, handler: Callable):
        """Faz başlangıcı handler'ı kaydet."""
        self._phase_handlers[phase] = handler

    async def execute_phase(self, phase_name: str) -> Dict[str, Any]:
        """Belirli bir faz için job'ları çalıştır."""
        phase = self.PHASES.get(phase_name)
        if not phase:
            return {"error": f"Unknown phase: {phase_name}"}

        results = {}
        self._current_phase = phase_name

        if phase_name in self._phase_handlers:
            try:
                await self._phase_handlers[phase_name]()
            except Exception as e:
                logger.error("Phase handler error", phase=phase_name, error=str(e))

        for job_type in phase.jobs:
            handler = self._handlers.get(job_type)
            if handler is None:
                continue

            try:
                result = await handler()
                results[job_type] = {"status": "SUCCESS", "result": result}
                self._jobs_run_today += 1
            except Exception as e:
                results[job_type] = {"status": "FAILED", "error": str(e)}
                self._jobs_failed_today += 1
                logger.error("Workflow job failed",
                           phase=phase_name, job=job_type, error=str(e))

        if phase_name == "post_market":
            self._daily_report_generated = True

        logger.info("Workflow phase completed",
                    phase=phase_name,
                    jobs=len(phase.jobs),
                    successful=sum(1 for r in results.values() if r.get("status") == "SUCCESS"))

        return results

    def get_status(self) -> WorkflowStatus:
        """Workflow durumu."""
        from .unified_scheduler import MarketSessionManager
        market = MarketSessionManager()
        phase = market.current_phase()

        current = self._PHASE_MAP.get(phase.value, "night")

        phase_order = list(self.PHASES.keys())
        current_idx = phase_order.index(current) if current in phase_order else 0
        next_phase = phase_order[(current_idx + 1) % len(phase_order)]

        return WorkflowStatus(
            current_phase=current,
            next_phase=next_phase,
            next_phase_in_seconds=market.seconds_until_next_phase(),
            jobs_run_today=self._jobs_run_today,
            jobs_failed_today=self._jobs_failed_today,
            daily_report_generated=self._daily_report_generated,
            timestamp=datetime.now(timezone.utc).isoformat(),
        )

    def get_phases(self) -> Dict[str, Dict[str, Any]]:
        """Tüm fazları al."""
        return {
            name: {
                "name": phase.name,
                "start_time": phase.start_time,
                "end_time": phase.end_time,
                "jobs": phase.jobs,
                "description": phase.description,
            }
            for name, phase in self.PHASES.items()
        }

    def reset_daily_counters(self):
        """Günlük sayaçları sıfırla."""
        self._jobs_run_today = 0
        self._jobs_failed_today = 0
        self._daily_report_generated = False
        try:
            from services.core.risk_gate import risk_gate
            risk_gate.reset_daily()
        except Exception:
            pass


# Singleton
daily_workflow = DailyWorkflow()
