"""
ALPHA BIST — Event Infrastructure v1.0

- Event Orchestrator
- Event Priority
- Catalyst Engine
- Notification System
- Alert Engine
- Snapshot System
- Cache System
- Job Queue
"""

import hashlib
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

import structlog

logger = structlog.get_logger()


class EventPriority(StrEnum):
    CRITICAL = "CRITICAL"
    HIGH = "HIGH"
    NORMAL = "NORMAL"
    LOW = "LOW"


@dataclass
class CatalystEvent:
    """Yaklaşan olay."""

    catalyst_id: str
    ticker: str
    catalyst_type: str  # earnings, dividend, assembly, contract, regulatory, central_bank, macro
    date: str
    importance: float  # 0-1
    expected_impact: str  # POSITIVE, NEGATIVE, UNKNOWN
    uncertainty: float  # 0-1
    description: str = ""


class EventOrchestrator:
    """Event pipeline yönetimi."""

    def __init__(self):
        self._handlers: dict[str, list[Callable]] = {}
        self._priority_queue: list[dict] = []

    def register(self, event_type: str, handler: Callable, priority: EventPriority = EventPriority.NORMAL):
        """Handler kaydet."""
        if event_type not in self._handlers:
            self._handlers[event_type] = []
        self._handlers[event_type].append({"handler": handler, "priority": priority})

    async def dispatch(self, event_type: str, data: dict, priority: EventPriority = EventPriority.NORMAL):
        """Event'i dispatch et."""
        handlers = self._handlers.get(event_type, [])
        for h in sorted(handlers, key=lambda x: list(EventPriority).index(x["priority"])):
            try:
                if asyncio.iscoroutinefunction(h["handler"]):
                    await h["handler"](data)
                else:
                    h["handler"](data)
            except Exception as e:
                logger.error("Handler error", event_type=event_type, error=str(e))


class CatalystEngine:
    """Yaklaşan olayları izle."""

    def __init__(self):
        self._catalysts: list[CatalystEvent] = []

    def add_catalyst(self, catalyst: CatalystEvent):
        """Yaklaşan olay ekle."""
        self._catalysts.append(catalyst)
        if len(self._catalysts) > 500:
            self._catalysts = self._catalysts[-500:]

    def get_upcoming(self, days: int = 7) -> list[dict]:
        """Yaklaşan olayları getir."""
        now = datetime.now(UTC)
        upcoming = []
        for c in self._catalysts:
            try:
                cat_date = datetime.fromisoformat(c.date)
                if cat_date.tzinfo is None:
                    cat_date = cat_date.replace(tzinfo=UTC)
                days_until = (cat_date - now).days
                if 0 <= days_until <= days:
                    upcoming.append(
                        {
                            "ticker": c.ticker,
                            "type": c.catalyst_type,
                            "date": c.date,
                            "days_until": days_until,
                            "importance": c.importance,
                            "expected_impact": c.expected_impact,
                        }
                    )
            except Exception as e:
                logger.debug("Handled exception", error=str(e), context="infrastructure.py:100")

        return sorted(upcoming, key=lambda x: x["days_until"])


class NotificationSystem:
    """Bildirim sistemi."""

    CATEGORIES = ["OPPORTUNITY", "RISK", "NEWS", "KAP", "REGIME", "PORTFOLIO", "MODEL", "SYSTEM", "SECURITY"]

    def __init__(self):
        self._notifications: list[dict] = []

    def notify(self, category: str, title: str, message: str, severity: str = "INFO", data: dict = None):
        """Bildirim gönder."""
        notification = {
            "id": hashlib.sha256(f"{category}:{title}:{datetime.now(UTC).isoformat()}".encode()).hexdigest()[:12],
            "category": category,
            "title": title,
            "message": message,
            "severity": severity,
            "data": data or {},
            "timestamp": datetime.now(UTC).isoformat(),
            "read": False,
        }
        self._notifications.append(notification)
        if len(self._notifications) > 500:
            self._notifications = self._notifications[-500:]
        logger.info("Notification", category=category, title=title, severity=severity)

    def get_unread(self, limit: int = 20) -> list[dict]:
        """Okunmamış bildirimler."""
        return [n for n in self._notifications if not n["read"]][-limit:]

    def mark_read(self, notification_id: str):
        """Bildirimi okundu olarak işaretle."""
        for n in self._notifications:
            if n["id"] == notification_id:
                n["read"] = True


class AlertEngine:
    """Alert motoru."""

    def __init__(self, notification_system: NotificationSystem):
        self._notifications = notification_system
        self._thresholds = {
            "max_drawdown_pct": 15.0,
            "daily_loss_pct": 5.0,
            "position_limit_pct": 10.0,
            "sector_limit_pct": 30.0,
        }

    def check_drawdown(self, current_drawdown: float):
        """Drawdown kontrolü."""
        threshold = self._thresholds["max_drawdown_pct"]
        if current_drawdown > threshold:
            self._notifications.notify(
                "RISK",
                "Drawdown Alert",
                f"Portfolio drawdown {current_drawdown:.1f}% exceeds threshold {threshold}%",
                severity="CRITICAL",
            )

    def check_daily_loss(self, daily_loss_pct: float):
        """Günlük zarar kontrolü."""
        threshold = self._thresholds["daily_loss_pct"]
        if abs(daily_loss_pct) > threshold:
            self._notifications.notify(
                "RISK",
                "Daily Loss Alert",
                f"Daily loss {daily_loss_pct:.1f}% exceeds threshold {threshold}%",
                severity="HIGH",
            )

    def check_position_limit(self, ticker: str, position_pct: float):
        """Pozisyon limiti kontrolü."""
        threshold = self._thresholds["position_limit_pct"]
        if position_pct > threshold:
            self._notifications.notify(
                "RISK",
                "Position Limit Alert",
                f"{ticker} position {position_pct:.1f}% exceeds limit {threshold}%",
                severity="HIGH",
            )


class SnapshotSystem:
    """Periyodik snapshot sistemi."""

    def __init__(self):
        self._snapshots: list[dict] = []

    def take_snapshot(self, state: dict[str, Any]):
        """Snapshot al."""
        snapshot = {
            "timestamp": datetime.now(UTC).isoformat(),
            "state": state,
        }
        self._snapshots.append(snapshot)
        if len(self._snapshots) > 1000:
            self._snapshots = self._snapshots[-1000:]
        # Son 100 snapshot tut
        self._snapshots = self._snapshots[-100:]

    def get_latest(self) -> dict | None:
        """Son snapshot."""
        return self._snapshots[-1] if self._snapshots else None

    def get_history(self, limit: int = 10) -> list[dict]:
        """Snapshot geçmişi."""
        return self._snapshots[-limit:]


class CacheSystem:
    """Cache sistemi."""

    def __init__(self):
        self._cache: dict[str, dict] = {}

    def get(self, key: str) -> Any | None:
        """Cache'den oku."""
        entry = self._cache.get(key)
        if entry:
            if entry.get("expires_at") and datetime.now(UTC).timestamp() > entry["expires_at"]:
                del self._cache[key]
                return None
            return entry.get("value")
        return None

    def set(self, key: str, value: Any, ttl_seconds: int = 3600):
        """Cache'e yaz."""
        self._cache[key] = {
            "value": value,
            "expires_at": datetime.now(UTC).timestamp() + ttl_seconds,
            "created_at": datetime.now(UTC).isoformat(),
        }

    def invalidate(self, key: str):
        """Cache'i temizle."""
        self._cache.pop(key, None)

    def get_stats(self) -> dict:
        """Cache istatistikleri."""
        return {"entries": len(self._cache)}


class JobQueue:
    """İş kuyruğu."""

    def __init__(self):
        self._queue: list[dict] = []
        self._running: list[dict] = []
        self._completed: list[dict] = []

    def enqueue(self, job_type: str, payload: dict, priority: str = "NORMAL"):
        """İş ekle."""
        job = {
            "job_id": hashlib.sha256(f"{job_type}:{datetime.now(UTC).isoformat()}".encode()).hexdigest()[:12],
            "type": job_type,
            "payload": payload,
            "priority": priority,
            "status": "QUEUED",
            "created_at": datetime.now(UTC).isoformat(),
        }
        self._queue.append(job)
        if len(self._queue) > 100:
            self._queue = self._queue[-100:]
        return job["job_id"]

    def dequeue(self) -> dict | None:
        """Sıradaki işi al."""
        if self._queue:
            # Priority sırası
            priority_order = {"CRITICAL": 0, "HIGH": 1, "NORMAL": 2, "LOW": 3}
            self._queue.sort(key=lambda x: priority_order.get(x.get("priority", "NORMAL"), 2))
            job = self._queue.pop(0)
            job["status"] = "RUNNING"
            self._running.append(job)
            if len(self._running) > 1000:
                self._running = self._running[-1000:]
            return job
        return None

    def complete(self, job_id: str, result: Any = None):
        """İşi tamamla."""
        for i, job in enumerate(self._running):
            if job["job_id"] == job_id:
                job["status"] = "COMPLETED"
                job["result"] = result
                job["completed_at"] = datetime.now(UTC).isoformat()
                self._completed.append(self._running.pop(i))
                if len(self._completed) > 1000:
                    self._completed = self._completed[-1000:]
                return

    def get_stats(self) -> dict:
        """Kuyruk istatistikleri."""
        return {
            "queued": len(self._queue),
            "running": len(self._running),
            "completed": len(self._completed),
        }


import asyncio

# Singletons
event_orchestrator = EventOrchestrator()
catalyst_engine = CatalystEngine()
notification_system = NotificationSystem()
alert_engine = AlertEngine(notification_system)
snapshot_system = SnapshotSystem()
cache_system = CacheSystem()
job_queue = JobQueue()
