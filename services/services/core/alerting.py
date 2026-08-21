"""
ALPHA BIST — Alerting System v3.0

Otonom sistem yönetimi için production-grade alerting.

Özellikler:
- Alert lifecycle: CREATED → ACKNOWLEDGED → ESCALATED → RESOLVED
- Escalation: WARNING belirli süre devam ederse → CRITICAL
- DB persistence (restart sonrası alert recovery)
- Notification routing: WARNING→log/webhook, CRITICAL→tüm kanallar
- Webhook, Slack, Discord, PagerDuty providers
- Deduplication, retry, failed notification logging
"""

import asyncio
import hashlib
import json
import time
from typing import Dict, Any, List, Optional, Protocol
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
import structlog

from .alert_policy import AlertPolicy, SilenceRule, VersionConflictError, PolicyDiff

logger = structlog.get_logger()


# =====================================================
# ENUMS
# =====================================================

class AlertSeverity(str, Enum):
    INFO = "INFO"
    WARNING = "WARNING"
    CRITICAL = "CRITICAL"


class AlertStatus(str, Enum):
    CREATED = "CREATED"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    ESCALATED = "ESCALATED"
    RESOLVED = "RESOLVED"


class AlertType(str, Enum):
    HEALTH_CHANGE = "health_change"
    INVARIANT_FAILURE = "invariant_failure"
    LOCK_DEADLOCK = "lock_deadlock"
    LOCK_TIMEOUT_SPIKE = "lock_timeout_spike"
    CASH_NEGATIVE = "cash_negative"
    DRAWDOWN_BREACH = "drawdown_breach"


# Escalation config — policy'den yüklenir, fallback olarak hard-coded
ESCALATION_TIMEOUT_S = {
    AlertType.HEALTH_CHANGE: 300,
    AlertType.INVARIANT_FAILURE: 60,
    AlertType.LOCK_DEADLOCK: 120,
    AlertType.LOCK_TIMEOUT_SPIKE: 300,
    AlertType.CASH_NEGATIVE: 30,
    AlertType.DRAWDOWN_BREACH: 180,
}


# =====================================================
# ALERT DATA
# =====================================================

@dataclass
class Alert:
    """Tek bir alert kaydı (lifecycle ile)."""
    alert_type: str
    severity: str
    message: str
    details: Dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)
    fingerprint: str = ""
    status: str = AlertStatus.CREATED
    notification_status: str = "pending"
    acknowledged_at: Optional[float] = None
    escalated_at: Optional[float] = None
    resolved_at: Optional[float] = None
    escalation_count: int = 0

    def __post_init__(self):
        if not self.fingerprint:
            self.fingerprint = self._compute_fingerprint()

    def _compute_fingerprint(self) -> str:
        key = f"{self.alert_type}:{json.dumps(self.details, sort_keys=True)}"
        return hashlib.sha256(key.encode()).hexdigest()[:16]

    def acknowledge(self):
        self.status = AlertStatus.ACKNOWLEDGED
        self.acknowledged_at = time.time()

    def escalate(self, new_severity: str = "CRITICAL"):
        self.status = AlertStatus.ESCALATED
        self.severity = new_severity
        self.escalated_at = time.time()
        self.escalation_count += 1

    def resolve(self):
        self.status = AlertStatus.RESOLVED
        self.resolved_at = time.time()

    @property
    def is_active(self) -> bool:
        return self.status in (AlertStatus.CREATED, AlertStatus.ACKNOWLEDGED, AlertStatus.ESCALATED)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "alert_type": self.alert_type,
            "severity": self.severity,
            "status": self.status,
            "message": self.message,
            "details": self.details,
            "timestamp": self.timestamp,
            "timestamp_iso": datetime.fromtimestamp(self.timestamp, tz=timezone.utc).isoformat(),
            "fingerprint": self.fingerprint,
            "notification_status": self.notification_status,
            "acknowledged_at": self.acknowledged_at,
            "escalated_at": self.escalated_at,
            "resolved_at": self.resolved_at,
            "escalation_count": self.escalation_count,
        }

    def to_webhook_payload(self) -> Dict[str, Any]:
        return {
            "event": "alert",
            "alert_type": self.alert_type,
            "severity": self.severity,
            "status": self.status,
            "message": self.message,
            "details": self.details,
            "timestamp": self.timestamp_iso_str(),
            "fingerprint": self.fingerprint,
            "escalation_count": self.escalation_count,
        }

    def to_slack_payload(self) -> Dict[str, Any]:
        color = {"INFO": "#36a64f", "WARNING": "#ff9900", "CRITICAL": "#ff0000"}.get(self.severity, "#999")
        return {
            "attachments": [{
                "color": color,
                "title": f"[{self.severity}] {self.alert_type}",
                "text": self.message,
                "fields": [
                    {"title": "Status", "value": self.status, "short": True},
                    {"title": "Escalations", "value": str(self.escalation_count), "short": True},
                ],
                "ts": int(self.timestamp),
            }]
        }

    def to_discord_payload(self) -> Dict[str, Any]:
        color = {"INFO": 0x36A64F, "WARNING": 0xFF9900, "CRITICAL": 0xFF0000}.get(self.severity, 0x999999)
        return {
            "embeds": [{
                "title": f"[{self.severity}] {self.alert_type}",
                "description": self.message,
                "color": color,
                "fields": [
                    {"name": "Status", "value": self.status, "inline": True},
                    {"name": "Escalations", "value": str(self.escalation_count), "inline": True},
                ],
                "timestamp": datetime.fromtimestamp(self.timestamp, tz=timezone.utc).isoformat(),
            }]
        }

    def to_pagerduty_payload(self, routing_key: str = "") -> Dict[str, Any]:
        severity_map = {"INFO": "info", "WARNING": "warning", "CRITICAL": "critical"}
        return {
            "routing_key": routing_key,
            "event_action": "trigger",
            "payload": {
                "summary": f"[{self.severity}] {self.alert_type}: {self.message}",
                "severity": severity_map.get(self.severity, "info"),
                "source": "alpha-bist",
                "custom_details": self.details,
            },
            "dedup_key": self.fingerprint,
        }

    def timestamp_iso_str(self) -> str:
        return datetime.fromtimestamp(self.timestamp, tz=timezone.utc).isoformat()


# =====================================================
# NOTIFICATION PROVIDERS
# =====================================================

class NotificationProvider(Protocol):
    async def send(self, alert: Alert) -> bool: ...
    def name(self) -> str: ...
    def min_severity(self) -> str: ...  # INFO, WARNING, CRITICAL


@dataclass
class LogProvider:
    _name: str = "log"
    def name(self) -> str: return self._name
    def min_severity(self) -> str: return "INFO"
    async def send(self, alert: Alert) -> bool:
        logger.warning("ALERT", type=alert.alert_type, severity=alert.severity,
                      status=alert.status, message=alert.message)
        return True


@dataclass
class WebhookProvider:
    url: str
    headers: Dict[str, str] = field(default_factory=dict)
    timeout: float = 10.0
    def name(self) -> str: return f"webhook:{self.url[:50]}"
    def min_severity(self) -> str: return "WARNING"
    async def send(self, alert: Alert) -> bool:
        try:
            import aiohttp
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    self.url, json=alert.to_webhook_payload(),
                    headers={"Content-Type": "application/json", **self.headers},
                    timeout=aiohttp.ClientTimeout(total=self.timeout),
                ) as resp:
                    return resp.status < 400
        except Exception as e:
            logger.error("Webhook error", url=self.url, error=str(e))
            return False


@dataclass
class SlackProvider:
    webhook_url: str
    timeout: float = 10.0
    def name(self) -> str: return "slack"
    def min_severity(self) -> str: return "CRITICAL"
    async def send(self, alert: Alert) -> bool:
        try:
            import aiohttp
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    self.webhook_url, json=alert.to_slack_payload(),
                    timeout=aiohttp.ClientTimeout(total=self.timeout),
                ) as resp:
                    return resp.status < 400
        except Exception as e:
            logger.error("Slack error", error=str(e))
            return False


@dataclass
class DiscordProvider:
    webhook_url: str
    timeout: float = 10.0
    def name(self) -> str: return "discord"
    def min_severity(self) -> str: return "CRITICAL"
    async def send(self, alert: Alert) -> bool:
        try:
            import aiohttp
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    self.webhook_url, json=alert.to_discord_payload(),
                    timeout=aiohttp.ClientTimeout(total=self.timeout),
                ) as resp:
                    return resp.status < 400
        except Exception as e:
            logger.error("Discord error", error=str(e))
            return False


@dataclass
class PagerDutyProvider:
    routing_key: str
    timeout: float = 10.0
    def name(self) -> str: return "pagerduty"
    def min_severity(self) -> str: return "CRITICAL"
    async def send(self, alert: Alert) -> bool:
        try:
            import aiohttp
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    "https://events.pagerduty.com/v2/enqueue",
                    json=alert.to_pagerduty_payload(self.routing_key),
                    timeout=aiohttp.ClientTimeout(total=self.timeout),
                ) as resp:
                    return resp.status < 400
        except Exception as e:
            logger.error("PagerDuty error", error=str(e))
            return False


@dataclass
class EmailProvider:
    to_addresses: List[str] = field(default_factory=list)
    from_address: str = "alerts@alpha-bist.local"
    smtp_host: str = "localhost"
    smtp_port: int = 587
    username: str = ""
    password: str = ""
    def name(self) -> str: return f"email:{','.join(self.to_addresses[:3])}"
    def min_severity(self) -> str: return "CRITICAL"
    async def send(self, alert: Alert) -> bool:
        try:
            import smtplib
            from email.mime.text import MIMEText
            msg = MIMEText(
                f"Alert: {alert.alert_type}\nSeverity: {alert.severity}\n"
                f"Status: {alert.status}\nMessage: {alert.message}\n"
                f"Details: {json.dumps(alert.details, indent=2)}"
            )
            msg["Subject"] = f"[{alert.severity}] ALPHA BIST: {alert.alert_type}"
            msg["From"] = self.from_address
            msg["To"] = ", ".join(self.to_addresses)
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, self._send_smtp, msg)
            return True
        except Exception as e:
            logger.error("Email error", error=str(e))
            return False
    def _send_smtp(self, msg):
        import smtplib
        with smtplib.SMTP(self.smtp_host, self.smtp_port) as s:
            if self.username: s.starttls(); s.login(self.username, self.password)
            s.send_message(msg)


# =====================================================
# NOTIFICATION ROUTER
# =====================================================

class NotificationRouter:
    """Notification routing: severity'ye göre provider seçimi.

    Kural:
    - INFO → log only
    - WARNING → log + webhook
    - CRITICAL → tüm kanallar (slack, discord, pagerduty, email)
    """

    def __init__(self):
        self._providers: List[Any] = []

    def add_provider(self, provider):
        self._providers.append(provider)

    def get_providers_for_severity(self, severity: str) -> List[Any]:
        """Severity'ye göre uygun provider'ları döndür."""
        severity_order = {"INFO": 0, "WARNING": 1, "CRITICAL": 2}
        target_level = severity_order.get(severity, 0)
        return [
            p for p in self._providers
            if severity_order.get(p.min_severity(), 999) <= target_level
        ]

    def get_all_providers(self) -> List[str]:
        return [p.name() for p in self._providers]


# =====================================================
# RETRY
# =====================================================

@dataclass
class RetryConfig:
    max_retries: int = 3
    base_delay_s: float = 1.0
    max_delay_s: float = 30.0
    backoff_factor: float = 2.0


class NotificationResult:
    def __init__(self, provider_name: str, alert_fingerprint: str):
        self.provider_name = provider_name
        self.alert_fingerprint = alert_fingerprint
        self.attempts: int = 0
        self.success: bool = False
        self.last_error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {"provider": self.provider_name, "fingerprint": self.alert_fingerprint,
                "attempts": self.attempts, "success": self.success, "last_error": self.last_error}


# =====================================================
# ALERTING SYSTEM
# =====================================================

class AlertingSystem:
    """v3.0 — Lifecycle, escalation, DB persistence, notification routing."""

    def __init__(self, max_alerts: int = 1000, dedup_window_s: float = 300.0,
                 db=None, dialect: str = "sqlite", policy: AlertPolicy = None):
        self._alerts: List[Alert] = []
        self._max_alerts = max_alerts
        self._dedup_window_s = dedup_window_s
        self._dedup_cache: Dict[str, float] = {}
        self._router = NotificationRouter()
        self._retry_config = RetryConfig()
        self._notification_log: List[NotificationResult] = []
        self._failed_notifications: List[NotificationResult] = []
        self._db = db
        self._dialect = dialect
        self._policy = policy or AlertPolicy()

        # State for change detection
        self._last_health_status: Optional[str] = None
        self._last_lock_deadlock_count: int = 0
        self._last_lock_timeout_count: int = 0
        self._invariant_failure_count: int = 0

        # Escalation task
        self._escalation_task: Optional[asyncio.Task] = None

    # =====================================================
    # LIFECYCLE
    # =====================================================

    def start(self):
        """Escalation monitor'ı başlat."""
        if self._escalation_task is None:
            try:
                self._escalation_task = asyncio.ensure_future(self._escalation_loop())
            except RuntimeError:
                pass

    def stop(self):
        """Escalation monitor'ı durdur."""
        if self._escalation_task and not self._escalation_task.done():
            self._escalation_task.cancel()
            self._escalation_task = None

    async def _escalation_loop(self):
        """Periyodik escalation kontrolü."""
        while True:
            try:
                await asyncio.sleep(10)  # Her 10 saniyede kontrol
                self._check_escalations()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.debug("Handled exception", error=str(e), context="alerting.py:443")
                pass

    def _check_escalations(self):
        """Aktif alert'ler için escalation kontrolü (policy-based)."""
        now = time.time()
        for alert in self._alerts:
            if not alert.is_active:
                continue
            if alert.status == AlertStatus.ACKNOWLEDGED:
                continue

            alert_type = alert.alert_type

            # Policy'den timeout al
            timeout = self._policy.get_escalation_timeout(alert_type)
            if timeout is None:
                timeout = ESCALATION_TIMEOUT_S.get(alert_type, 300)

            if now - alert.timestamp > timeout and alert.severity != "CRITICAL":
                alert.escalate("CRITICAL")
                logger.warning("Alert escalated", fingerprint=alert.fingerprint,
                             type=alert_type, escalation_count=alert.escalation_count)
                try:
                    loop = asyncio.get_event_loop()
                    if loop.is_running():
                        asyncio.ensure_future(self._notify_all(alert))
                except RuntimeError:
                    pass

    # =====================================================
    # PROVIDER MANAGEMENT
    # =====================================================

    def add_provider(self, provider):
        self._router.add_provider(provider)
        logger.info("Provider added", name=provider.name(),
                   min_severity=provider.min_severity())

    def get_providers(self) -> List[str]:
        return self._router.get_all_providers()

    # =====================================================
    # ALERT CHECKS
    # =====================================================

    def check_health(self, health_report: Dict[str, Any]):
        current_status = health_report.get("status", "UNKNOWN")
        if self._last_health_status and self._last_health_status != current_status:
            if current_status in ("DEGRADED", "UNHEALTHY"):
                self._add_alert(Alert(
                    alert_type=AlertType.HEALTH_CHANGE,
                    severity="CRITICAL" if current_status == "UNHEALTHY" else "WARNING",
                    message=f"Health: {self._last_health_status} → {current_status}",
                    details={"previous": self._last_health_status, "current": current_status,
                             "issues": health_report.get("issues", [])},
                ))
            elif current_status == "HEALTHY" and self._last_health_status in ("DEGRADED", "UNHEALTHY"):
                self._add_alert(Alert(
                    alert_type=AlertType.HEALTH_CHANGE, severity="INFO",
                    message=f"Health düzeldi: {self._last_health_status} → HEALTHY",
                    details={"previous": self._last_health_status},
                ))
        self._last_health_status = current_status

    def check_invariant(self, invariant_ok: bool, details: Dict[str, Any] = None):
        if not invariant_ok:
            self._invariant_failure_count += 1
            self._add_alert(Alert(
                alert_type=AlertType.INVARIANT_FAILURE, severity="CRITICAL",
                message=f"Portfolio invariant ihlali! (toplam: {self._invariant_failure_count})",
                details=details or {},
            ))

    def check_negative_cash(self, cash: float):
        if cash < 0:
            self._add_alert(Alert(
                alert_type=AlertType.CASH_NEGATIVE, severity="CRITICAL",
                message=f"Negatif cash: {cash:.2f}", details={"cash": cash},
            ))

    def check_drawdown(self, drawdown_pct: float, threshold_pct: float = 15.0):
        if drawdown_pct > threshold_pct:
            self._add_alert(Alert(
                alert_type=AlertType.DRAWDOWN_BREACH, severity="CRITICAL",
                message=f"Drawdown %{drawdown_pct:.1f} > eşik %{threshold_pct:.1f}",
                details={"drawdown_pct": drawdown_pct, "threshold": threshold_pct},
            ))

    def check_lock_metrics(self, lock_metrics: Dict[str, Any]):
        for key, metrics in lock_metrics.items():
            dc = metrics.get("total_deadlocks_detected", 0)
            tc = metrics.get("total_timeouts", 0)
            if dc > self._last_lock_deadlock_count:
                self._add_alert(Alert(
                    alert_type=AlertType.LOCK_DEADLOCK, severity="WARNING",
                    message=f"Lock deadlock: {key}", details={"lock_key": key, "total": dc},
                ))
                self._last_lock_deadlock_count = dc
            if tc > self._last_lock_timeout_count + 2:
                self._add_alert(Alert(
                    alert_type=AlertType.LOCK_TIMEOUT_SPIKE, severity="WARNING",
                    message=f"Lock timeout artışı: {key} (toplam: {tc})",
                    details={"lock_key": key, "total": tc},
                ))
                self._last_lock_timeout_count = tc

    # =====================================================
    # ALERT ACTIONS
    # =====================================================

    def acknowledge_alert(self, fingerprint: str) -> bool:
        """Alert'i onayla (escalation durdurur)."""
        for a in self._alerts:
            if a.fingerprint == fingerprint and a.is_active:
                a.acknowledge()
                logger.info("Alert acknowledged", fingerprint=fingerprint)
                return True
        return False

    def resolve_alert(self, fingerprint: str) -> bool:
        """Alert'i çöz."""
        for a in self._alerts:
            if a.fingerprint == fingerprint and a.is_active:
                a.resolve()
                logger.info("Alert resolved", fingerprint=fingerprint)
                return True
        return False

    def resolve_alerts(self, alert_type: str):
        for a in self._alerts:
            if a.alert_type == alert_type and a.is_active:
                a.resolve()

    # =====================================================
    # QUERIES
    # =====================================================

    def get_active_alerts(self) -> List[Dict[str, Any]]:
        return [a.to_dict() for a in self._alerts if a.is_active]

    def get_all_alerts(self, limit: int = 100) -> List[Dict[str, Any]]:
        return [a.to_dict() for a in self._alerts[-limit:]]

    # =====================================================
    # SILENCE MANAGEMENT
    # =====================================================

    def add_silence(self, alert_type: str = None, fingerprint: str = None,
                    duration_s: float = 3600, reason: str = "",
                    created_by: str = "system") -> Dict[str, Any]:
        """Alert susturma ekle (DB persist ile)."""
        rule = self._policy.add_silence(
            alert_type=alert_type, fingerprint=fingerprint,
            duration_s=duration_s, reason=reason, created_by=created_by,
            db=self._db,
        )
        return rule.to_dict()

    def remove_silence(self, fingerprint: str = None, alert_type: str = None,
                       actor: str = "api") -> int:
        """Alert susturma kaldır."""
        return self._policy.remove_silence(
            fingerprint=fingerprint, alert_type=alert_type,
            actor=actor, db=self._db,
        )

    def get_active_silences(self) -> List[Dict[str, Any]]:
        """Aktif susturmalar."""
        return self._policy.get_active_silences()

    def save_silences(self):
        """Silence durumunu kaydet (restart recovery)."""
        self._policy.save_silences()

    def load_silences(self):
        """Silence durumunu yükle (DB + file restart recovery)."""
        if self._db:
            self._policy.load_silences_from_db(self._db)
        else:
            self._policy.load_silences()

    def get_policy_info(self) -> Dict[str, Any]:
        """Policy bilgisi."""
        return self._policy.to_dict()

    def reload_policy(self) -> bool:
        """Policy'yi yeniden yükle."""
        return self._policy.reload_if_changed()

    def update_policy(self, new_config: Dict[str, Any], actor: str = "api",
                      expected_version: int = 0) -> Dict[str, Any]:
        """Policy güncelle (optimistic locking ile)."""
        try:
            return self._policy.update(new_config, actor, expected_version)
        except VersionConflictError as e:
            return {"success": False, "error": str(e), "conflict": True,
                    "current_version": self._policy._version}

    def rollback_policy(self, target_version: int = 0, actor: str = "api") -> Dict[str, Any]:
        """Policy rollback."""
        return self._policy.rollback(target_version, actor)

    def get_policy_history(self) -> List[Dict[str, Any]]:
        """Policy versiyon geçmişi."""
        return self._policy.get_history()

    def get_policy_audit_log(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Policy audit log."""
        return self._policy.get_audit_log(limit)

    def batch_add_silences(self, rules: List[Dict[str, Any]],
                           created_by: str = "system") -> List[Dict[str, Any]]:
        """Toplu susturma ekle (transaction)."""
        return self._policy.batch_add_silences(rules, created_by, self._db)

    def batch_remove_silences(self, filters: List[Dict[str, str]],
                               actor: str = "api") -> Dict[str, int]:
        """Toplu susturma kaldır (transaction)."""
        return self._policy.batch_remove_silences(filters, actor, self._db)

    def compute_policy_diff(self, new_config: Dict[str, Any]):
        """Policy diff hesapla (uygulamadan)."""
        return self._policy.compute_diff(new_config)

    def set_policy_webhook(self, urls: List[str]):
        """Policy değişiklik webhook URL'leri."""
        self._policy.set_webhook_urls(urls)

    def get_alert_summary(self) -> Dict[str, Any]:
        active = [a for a in self._alerts if a.is_active]
        by_severity = {}
        for a in active:
            by_severity[a.severity] = by_severity.get(a.severity, 0) + 1
        by_status = {}
        for a in active:
            by_status[a.status] = by_status.get(a.status, 0) + 1
        return {
            "total_alerts": len(self._alerts),
            "active_alerts": len(active),
            "by_severity": by_severity,
            "by_status": by_status,
            "providers": len(self._router.get_all_providers()),
            "failed_notifications": len(self._failed_notifications),
        }

    def get_notification_log(self, limit: int = 50) -> List[Dict[str, Any]]:
        return [r.to_dict() for r in self._notification_log[-limit:]]

    def get_failed_notifications(self) -> List[Dict[str, Any]]:
        return [r.to_dict() for r in self._failed_notifications]

    # =====================================================
    # DB PERSISTENCE
    # =====================================================

    async def init_db(self):
        """Alert tablosunu oluştur."""
        if not self._db:
            return
        try:
            self._db.execute(
                "CREATE TABLE IF NOT EXISTS alerts_state ("
                "fingerprint TEXT PRIMARY KEY, "
                "alert_type TEXT NOT NULL, "
                "severity TEXT NOT NULL, "
                "status TEXT NOT NULL, "
                "message TEXT, "
                "details TEXT DEFAULT '{}', "
                "timestamp REAL NOT NULL, "
                "acknowledged_at REAL, "
                "escalated_at REAL, "
                "resolved_at REAL, "
                "escalation_count INTEGER DEFAULT 0, "
                "notification_status TEXT DEFAULT 'pending', "
                "updated_at REAL)"
            )
            self._db.commit()
        except Exception as e:
            logger.warning("Alert DB init failed", error=str(e))

    async def persist_alert(self, alert: Alert):
        """Alert'i DB'ye kaydet."""
        if not self._db:
            return
        try:
            self._db.execute(
                "INSERT OR REPLACE INTO alerts_state "
                "(fingerprint, alert_type, severity, status, message, details, "
                "timestamp, acknowledged_at, escalated_at, resolved_at, "
                "escalation_count, notification_status, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (alert.fingerprint, str(alert.alert_type), str(alert.severity),
                 alert.status.value if hasattr(alert.status, "value") else str(alert.status), alert.message, json.dumps(alert.details),
                 alert.timestamp, alert.acknowledged_at, alert.escalated_at,
                 alert.resolved_at, alert.escalation_count,
                 alert.notification_status, time.time())
            )
            self._db.commit()
        except Exception as e:
            logger.warning("Alert persist failed", error=str(e))

    async def load_from_db(self):
        """DB'den aktif alert'leri geri yükle."""
        if not self._db:
            return
        try:
            rows = self._db.execute(
                "SELECT * FROM alerts_state WHERE status IN (?, ?, ?)",
                ("CREATED", "ACKNOWLEDGED", "ESCALATED")
            ).fetchall()
            for row in rows:
                alert = Alert(
                    alert_type=row["alert_type"],
                    severity=row["severity"],
                    message=row["message"],
                    details=json.loads(row["details"]) if row["details"] else {},
                    timestamp=row["timestamp"],
                    fingerprint=row["fingerprint"],
                    status=row["status"],
                    acknowledged_at=row["acknowledged_at"],
                    escalated_at=row["escalated_at"],
                    resolved_at=row["resolved_at"],
                    escalation_count=row["escalation_count"],
                    notification_status=row["notification_status"],
                )
                self._alerts.append(alert)
            logger.info("Alerts loaded from DB", count=len(rows))
        except Exception as e:
            logger.warning("Alert load from DB failed", error=str(e))

    # =====================================================
    # INTERNAL
    # =====================================================

    def _add_alert(self, alert: Alert):
        if self._is_duplicate(alert):
            return

        # Silence check
        if self._policy.is_silenced(alert.alert_type, alert.fingerprint):
            alert.notification_status = "silenced"
            logger.debug("Alert silenced", fp=alert.fingerprint, type=alert.alert_type)
            return

        self._alerts.append(alert)
        self._trim_alerts()
        self._dedup_cache[alert.fingerprint] = time.time()

        logger.warning("Alert created", type=alert.alert_type,
                      severity=alert.severity, fp=alert.fingerprint)

        # Policy reload check
        self._policy.reload_if_changed()

        # Persist to DB
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                asyncio.ensure_future(self.persist_alert(alert))
        except RuntimeError:
            pass

        # Notify — policy routing ile
        channels = self._policy.get_notification_channels(alert.severity)
        if channels and self._router.get_all_providers():
            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    asyncio.ensure_future(self._notify_all(alert))
            except RuntimeError:
                pass

    def _is_duplicate(self, alert: Alert) -> bool:
        fp = alert.fingerprint
        if fp in self._dedup_cache:
            if time.time() - self._dedup_cache[fp] < self._dedup_window_s:
                return True
        return False

    def _trim_alerts(self):
        if len(self._alerts) > self._max_alerts:
            self._alerts = self._alerts[-self._max_alerts:]

    async def _notify_all(self, alert: Alert):
        # Policy-based routing
        channels = self._policy.get_notification_channels(alert.severity)
        all_providers = self._router.get_all_providers()
        providers = self._router.get_providers_for_severity(alert.severity)
        for provider in providers:
            result = await self._send_with_retry(provider, alert)
            self._notification_log.append(result)
            if not result.success:
                self._failed_notifications.append(result)
                alert.notification_status = "failed"
            else:
                alert.notification_status = "sent"
        await self.persist_alert(alert)

    async def _send_with_retry(self, provider, alert: Alert) -> NotificationResult:
        result = NotificationResult(provider.name(), alert.fingerprint)
        for attempt in range(self._retry_config.max_retries):
            result.attempts += 1
            try:
                if await provider.send(alert):
                    result.success = True
                    return result
                result.last_error = "Provider returned False"
            except Exception as e:
                result.last_error = str(e)
            if attempt < self._retry_config.max_retries - 1:
                delay = min(
                    self._retry_config.base_delay_s * (self._retry_config.backoff_factor ** attempt),
                    self._retry_config.max_delay_s
                )
                await asyncio.sleep(delay)
        return result


# Singleton
alerting = AlertingSystem()
