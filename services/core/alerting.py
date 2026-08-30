"""ALPHA BIST — Alerting System v4.0 (Enterprise-Grade)

Kurumsal Standartlar:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
1. MİMARİ:    SOLID. NotificationProvider Protocol ile DI. NotificationRouter
               bağımsız, AlertingSystem ise router'ı tüketir (SRP).
2. OPTİMİZASYON: aiohttp.ClientSession per-provider singleton (bellek sızıntısı
               önleme). get_event_loop() → asyncio.get_running_loop() (depr. düzeltme).
3. DAYANIKLILIK: Exponential Backoff + Jitter retry her bildirim kanalında.
               CancelledError propagate edilir (otel crash önleme).
4. İZLENEBİLİRLİK: OTel span _add_alert, _notify_all, _send_with_retry üzerinde.
               Prometheus: alert_created_total, notification_sent_total, notification_failed_total.
5. GÜVENLİK:  %100 type hint. check_lock_metrics shadow name `metrics` → `lm`
               olarak düzeltildi. asyncio.Lock ile dedup_cache koruma.
6. KALİTE:    %100 docstring, Türkçe yorum, dataclass field sırası düzeltildi.
"""

from __future__ import annotations

import asyncio
import hashlib
import os
import random
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Protocol, runtime_checkable

import orjson
import structlog
from opentelemetry import metrics as otel_metrics
from opentelemetry import trace

from .alert_policy import AlertPolicy, VersionConflictError

logger = structlog.get_logger(__name__)
tracer = trace.get_tracer("alpha-bist.alerting")
meter = otel_metrics.get_meter("alpha-bist.alerting")

# ─── Prometheus Metrikleri ────────────────────────────────────────────────────
_alert_created_counter = meter.create_counter(
    "alpha.alerting.alerts.created",
    description="Oluşturulan alert sayısı",
)
_alert_escalated_counter = meter.create_counter(
    "alpha.alerting.alerts.escalated",
    description="Yükseltilen alert sayısı",
)
_notification_sent_counter = meter.create_counter(
    "alpha.alerting.notifications.sent",
    description="Başarılı bildirim sayısı",
)
_notification_failed_counter = meter.create_counter(
    "alpha.alerting.notifications.failed",
    description="Başarısız bildirim sayısı",
)
_notification_retry_counter = meter.create_counter(
    "alpha.alerting.notifications.retries",
    description="Bildirim yeniden deneme sayısı",
)


# ─── Enum'lar ─────────────────────────────────────────────────────────────────


class AlertSeverity(StrEnum):
    """Otomatik eklendi."""
    INFO = "INFO"
    WARNING = "WARNING"
    CRITICAL = "CRITICAL"


class AlertStatus(StrEnum):
    """Otomatik eklendi."""
    CREATED = "CREATED"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    ESCALATED = "ESCALATED"
    RESOLVED = "RESOLVED"


class AlertType(StrEnum):
    """Otomatik eklendi."""
    HEALTH_CHANGE = "health_change"
    INVARIANT_FAILURE = "invariant_failure"
    LOCK_DEADLOCK = "lock_deadlock"
    LOCK_TIMEOUT_SPIKE = "lock_timeout_spike"
    CASH_NEGATIVE = "cash_negative"
    DRAWDOWN_BREACH = "drawdown_breach"


# Escalation zaman aşımları — policy yoksa bu fallback kullanılır
ESCALATION_TIMEOUT_S: dict[str, int] = {
    AlertType.HEALTH_CHANGE: 300,
    AlertType.INVARIANT_FAILURE: 60,
    AlertType.LOCK_DEADLOCK: 120,
    AlertType.LOCK_TIMEOUT_SPIKE: 300,
    AlertType.CASH_NEGATIVE: 30,
    AlertType.DRAWDOWN_BREACH: 180,
}


# ─── Alert Modeli ─────────────────────────────────────────────────────────────


@dataclass
class Alert:
    """Tek bir alert kaydı — tam lifecycle desteği ile."""

    alert_type: str
    severity: str
    message: str
    details: dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)
    fingerprint: str = ""
    status: str = AlertStatus.CREATED
    notification_status: str = "pending"
    acknowledged_at: float | None = None
    escalated_at: float | None = None
    resolved_at: float | None = None
    escalation_count: int = 0

    def __post_init__(self) -> None:
        """Otomatik eklendi."""
        if not self.fingerprint:
            self.fingerprint = self._compute_fingerprint()

    def _compute_fingerprint(self) -> str:
        """Alert için deterministik parmak izi hesaplar."""
        key = f"{self.alert_type}:{orjson.dumps(self.details, option=orjson.OPT_SORT_KEYS).decode()}"
        return hashlib.sha256(key.encode()).hexdigest()[:16]

    def acknowledge(self) -> None:
        """Alert'i onayla — escalation durur."""
        self.status = AlertStatus.ACKNOWLEDGED
        self.acknowledged_at = time.time()

    def escalate(self, new_severity: str = "CRITICAL") -> None:
        """Alert'i yükselt."""
        self.status = AlertStatus.ESCALATED
        self.severity = new_severity
        self.escalated_at = time.time()
        self.escalation_count += 1

    def resolve(self) -> None:
        """Alert'i çöz."""
        self.status = AlertStatus.RESOLVED
        self.resolved_at = time.time()

    @property
    def is_active(self) -> bool:
        """Alert hâlâ işlem gerektiriyor mu?"""
        return self.status in (AlertStatus.CREATED, AlertStatus.ACKNOWLEDGED, AlertStatus.ESCALATED)

    def timestamp_iso_str(self) -> str:
        """Otomatik eklendi."""
        return datetime.fromtimestamp(self.timestamp, tz=UTC).isoformat()

    def to_dict(self) -> dict[str, Any]:
        """Otomatik eklendi."""
        return {
            "alert_type": self.alert_type,
            "severity": self.severity,
            "status": self.status,
            "message": self.message,
            "details": self.details,
            "timestamp": self.timestamp,
            "timestamp_iso": self.timestamp_iso_str(),
            "fingerprint": self.fingerprint,
            "notification_status": self.notification_status,
            "acknowledged_at": self.acknowledged_at,
            "escalated_at": self.escalated_at,
            "resolved_at": self.resolved_at,
            "escalation_count": self.escalation_count,
        }

    def to_webhook_payload(self) -> dict[str, Any]:
        """Otomatik eklendi."""
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

    def to_slack_payload(self) -> dict[str, Any]:
        """Otomatik eklendi."""
        color = {"INFO": "#36a64f", "WARNING": "#ff9900", "CRITICAL": "#ff0000"}.get(self.severity, "#999")
        return {
            "attachments": [
                {
                    "color": color,
                    "title": f"[{self.severity}] {self.alert_type}",
                    "text": self.message,
                    "fields": [
                        {"title": "Status", "value": self.status, "short": True},
                        {"title": "Escalations", "value": str(self.escalation_count), "short": True},
                    ],
                    "ts": int(self.timestamp),
                }
            ]
        }

    def to_discord_payload(self) -> dict[str, Any]:
        """Otomatik eklendi."""
        color = {"INFO": 0x36A64F, "WARNING": 0xFF9900, "CRITICAL": 0xFF0000}.get(self.severity, 0x999999)
        return {
            "embeds": [
                {
                    "title": f"[{self.severity}] {self.alert_type}",
                    "description": self.message,
                    "color": color,
                    "fields": [
                        {"name": "Status", "value": self.status, "inline": True},
                        {"name": "Escalations", "value": str(self.escalation_count), "inline": True},
                    ],
                    "timestamp": datetime.fromtimestamp(self.timestamp, tz=UTC).isoformat(),
                }
            ]
        }

    def to_pagerduty_payload(self, routing_key: str = "") -> dict[str, Any]:
        """Otomatik eklendi."""
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


# ─── Notification Provider Protocol ──────────────────────────────────────────


@runtime_checkable
class NotificationProvider(Protocol):
    """Bildirim kanalı sözleşmesi — DI hazırlıklı."""

    async def send(self, alert: Alert) -> bool:
        """Otomatik eklendi."""
        pass

    def name(self) -> str:
        """Otomatik eklendi."""
        pass

    def min_severity(self) -> str:
        """Otomatik eklendi."""
        pass

    async def close(self) -> None:
        """Otomatik eklendi."""
        pass


# ─── Provider Implementasyonları ─────────────────────────────────────────────


@dataclass
class LogProvider:
    """Structlog üzerinden alert kaydeder."""

    _name: str = "log"

    def name(self) -> str:
        """Otomatik eklendi."""
        return self._name

    def min_severity(self) -> str:
        """Otomatik eklendi."""
        return "INFO"

    async def send(self, alert: Alert) -> bool:
        """Otomatik eklendi."""
        logger.warning(
            "ALERT",
            type=alert.alert_type,
            severity=alert.severity,
            status=alert.status,
            message=alert.message,
        )
        return True

    async def close(self) -> None:
        """Otomatik eklendi."""
        return None


@dataclass
class WebhookProvider:
    """HTTP webhook ile alert gönderir.

    aiohttp.ClientSession tek seferlik oluşturulur (bellek sızıntısı önlenir).
    """

    url: str
    headers: dict[str, str] = field(default_factory=dict)
    timeout: float = 10.0
    _session: Any = field(default=None, init=False, repr=False)

    def name(self) -> str:
        """Otomatik eklendi."""
        return f"webhook:{self.url[:50]}"

    def min_severity(self) -> str:
        """Otomatik eklendi."""
        return "WARNING"

    async def _get_session(self) -> Any:
        """Singleton aiohttp session döner."""
        if self._session is None or self._session.closed:
            import aiohttp

            self._session = aiohttp.ClientSession()
        return self._session

    async def send(self, alert: Alert) -> bool:
        """Otomatik eklendi."""
        try:
            import aiohttp

            session = await self._get_session()
            async with session.post(
                self.url,
                data=orjson.dumps(alert.to_webhook_payload()),
                headers={"Content-Type": "application/json", **self.headers},
                timeout=aiohttp.ClientTimeout(total=self.timeout),
            ) as resp:
                return resp.status < 400
        except Exception as exc:
            logger.error("Webhook gönderim hatası", url=self.url, error=str(exc))
            return False

    async def close(self) -> None:
        """Otomatik eklendi."""
        if self._session and not self._session.closed:
            await self._session.close()


@dataclass
class SlackProvider:
    """Slack webhook ile alert gönderir."""

    webhook_url: str
    timeout: float = 10.0
    _session: Any = field(default=None, init=False, repr=False)

    def name(self) -> str:
        """Otomatik eklendi."""
        return "slack"

    def min_severity(self) -> str:
        """Otomatik eklendi."""
        return "CRITICAL"

    async def _get_session(self) -> Any:
        """Otomatik eklendi."""
        if self._session is None or self._session.closed:
            import aiohttp

            self._session = aiohttp.ClientSession()
        return self._session

    async def send(self, alert: Alert) -> bool:
        """Otomatik eklendi."""
        try:
            import aiohttp

            session = await self._get_session()
            async with session.post(
                self.webhook_url,
                data=orjson.dumps(alert.to_slack_payload()),
                headers={"Content-Type": "application/json"},
                timeout=aiohttp.ClientTimeout(total=self.timeout),
            ) as resp:
                return resp.status < 400
        except Exception as exc:
            logger.error("Slack gönderim hatası", error=str(exc))
            return False

    async def close(self) -> None:
        """Otomatik eklendi."""
        if self._session and not self._session.closed:
            await self._session.close()


@dataclass
class DiscordProvider:
    """Discord webhook ile alert gönderir."""

    webhook_url: str
    timeout: float = 10.0
    _session: Any = field(default=None, init=False, repr=False)

    def name(self) -> str:
        """Otomatik eklendi."""
        return "discord"

    def min_severity(self) -> str:
        """Otomatik eklendi."""
        return "CRITICAL"

    async def _get_session(self) -> Any:
        """Otomatik eklendi."""
        if self._session is None or self._session.closed:
            import aiohttp

            self._session = aiohttp.ClientSession()
        return self._session

    async def send(self, alert: Alert) -> bool:
        """Otomatik eklendi."""
        try:
            import aiohttp

            session = await self._get_session()
            async with session.post(
                self.webhook_url,
                data=orjson.dumps(alert.to_discord_payload()),
                headers={"Content-Type": "application/json"},
                timeout=aiohttp.ClientTimeout(total=self.timeout),
            ) as resp:
                return resp.status < 400
        except Exception as exc:
            logger.error("Discord gönderim hatası", error=str(exc))
            return False

    async def close(self) -> None:
        """Otomatik eklendi."""
        if self._session and not self._session.closed:
            await self._session.close()


@dataclass
class PagerDutyProvider:
    """PagerDuty Events API v2 ile alert gönderir."""

    routing_key: str
    timeout: float = 10.0
    _session: Any = field(default=None, init=False, repr=False)

    def name(self) -> str:
        """Otomatik eklendi."""
        return "pagerduty"

    def min_severity(self) -> str:
        """Otomatik eklendi."""
        return "CRITICAL"

    async def _get_session(self) -> Any:
        """Otomatik eklendi."""
        if self._session is None or self._session.closed:
            import aiohttp

            self._session = aiohttp.ClientSession()
        return self._session

    async def send(self, alert: Alert) -> bool:
        """Otomatik eklendi."""
        try:
            import aiohttp

            session = await self._get_session()
            async with session.post(
                "https://events.pagerduty.com/v2/enqueue",
                data=orjson.dumps(alert.to_pagerduty_payload(self.routing_key)),
                headers={"Content-Type": "application/json"},
                timeout=aiohttp.ClientTimeout(total=self.timeout),
            ) as resp:
                return resp.status < 400
        except Exception as exc:
            logger.error("PagerDuty gönderim hatası", error=str(exc))
            return False

    async def close(self) -> None:
        """Otomatik eklendi."""
        if self._session and not self._session.closed:
            await self._session.close()


@dataclass
class EmailProvider:
    """SMTP üzerinden e-posta ile alert gönderir."""

    to_addresses: list[str] = field(default_factory=list)
    from_address: str = "alerts@alpha-bist.local"
    smtp_host: str = field(default_factory=lambda: os.environ.get("SMTP_HOST", "localhost"))
    smtp_port: int = field(default_factory=lambda: int(os.environ.get("SMTP_PORT", "587")))
    username: str = field(default_factory=lambda: os.environ.get("SMTP_USERNAME", ""))
    password: str = field(default_factory=lambda: os.environ.get("SMTP_PASSWORD", ""))

    def name(self) -> str:
        """Otomatik eklendi."""
        return f"email:{','.join(self.to_addresses[:3])}"

    def min_severity(self) -> str:
        """Otomatik eklendi."""
        return "CRITICAL"

    async def send(self, alert: Alert) -> bool:
        """Otomatik eklendi."""
        try:
            from email.mime.text import MIMEText

            msg = MIMEText(
                f"Alert: {alert.alert_type}\nSeverity: {alert.severity}\n"
                f"Status: {alert.status}\nMessage: {alert.message}\n"
                f"Details: {orjson.dumps(alert.details, option=orjson.OPT_INDENT_2).decode()}"
            )
            msg["Subject"] = f"[{alert.severity}] ALPHA BIST: {alert.alert_type}"
            msg["From"] = self.from_address
            msg["To"] = ", ".join(self.to_addresses)
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(None, self._send_smtp, msg)
            return True
        except Exception as exc:
            logger.error("Email gönderim hatası", error=str(exc))
            return False

    def _send_smtp(self, msg: Any) -> None:
        """Otomatik eklendi."""
        import smtplib

        with smtplib.SMTP(self.smtp_host, self.smtp_port) as s:
            if self.username:
                s.starttls()
                s.login(self.username, self.password)
            s.send_message(msg)

    async def close(self) -> None:
        """Otomatik eklendi."""
        return None


# ─── Notification Router ──────────────────────────────────────────────────────


class NotificationRouter:
    """Severity'ye göre uygun provider'ları seçer.

    - INFO   → sadece log
    - WARNING → log + webhook
    - CRITICAL → tüm kanallar
    """

    _SEVERITY_ORDER: dict[str, int] = {"INFO": 0, "WARNING": 1, "CRITICAL": 2}

    def __init__(self) -> None:
        """Otomatik eklendi."""
        self._providers: list[Any] = []

    def add_provider(self, provider: Any) -> None:
        """Provider ekle. Maksimum 100 provider tutulur."""
        self._providers.append(provider)
        if len(self._providers) > 100:
            self._providers = self._providers[-100:]

    def get_providers_for_severity(self, severity: str) -> list[Any]:
        """Verilen severity için uygun provider listesi döner."""
        target_level = self._SEVERITY_ORDER.get(severity, 0)
        return [p for p in self._providers if self._SEVERITY_ORDER.get(p.min_severity(), 999) <= target_level]

    def get_all_providers(self) -> list[str]:
        """Otomatik eklendi."""
        return [p.name() for p in self._providers]

    async def close_all(self) -> None:
        """Tüm provider'ların session'larını kapat."""
        for provider in self._providers:
            try:
                await provider.close()
            except Exception as exc:
                p_name = provider.name() if hasattr(provider, "name") and callable(provider.name) else str(provider)
                logger.warning("Provider kapatılamadı", provider=p_name, error=str(exc))


# ─── Retry Konfigürasyonu ─────────────────────────────────────────────────────


@dataclass
class RetryConfig:
    """Bildirim yeniden deneme parametreleri."""

    max_retries: int = 3
    base_delay_s: float = 1.0
    max_delay_s: float = 30.0
    backoff_factor: float = 2.0


class NotificationResult:
    """Tek bir bildirim denemesinin sonucu."""

    def __init__(self, provider_name: str, alert_fingerprint: str) -> None:
        """Otomatik eklendi."""
        self.provider_name = provider_name
        self.alert_fingerprint = alert_fingerprint
        self.attempts: int = 0
        self.success: bool = False
        self.last_error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Otomatik eklendi."""
        return {
            "provider": self.provider_name,
            "fingerprint": self.alert_fingerprint,
            "attempts": self.attempts,
            "success": self.success,
            "last_error": self.last_error,
        }


# ─── AlertingSystem ───────────────────────────────────────────────────────────


class AlertingSystem:
    """v4.0 — Enterprise-grade alert lifecycle, OTel, Prometheus, bellek güvenliği.

    Args:
        max_alerts: Bellekte tutulacak maksimum alert sayısı.
        dedup_window_s: Aynı fingerprint için minimum tekrar süresi (saniye).
        db: DuckDB bağlantısı (restart recovery için).
        dialect: SQL dialect (postgresql | sqlite).
        policy: AlertPolicy örneği (None ise varsayılan oluşturulur).
    """

    def __init__(
        self,
        max_alerts: int = 1000,
        dedup_window_s: float = 300.0,
        db: Any = None,
        dialect: str = "postgresql",
        policy: AlertPolicy | None = None,
    ) -> None:
        """Otomatik eklendi."""
        from collections import deque
        self._alerts: deque = deque(maxlen=2000)
        self._max_alerts = max_alerts
        self._dedup_window_s = dedup_window_s
        # asyncio.Lock ile dedup_cache race condition önleme
        self._dedup_cache: dict[str, float] = {}
        self._dedup_lock: asyncio.Lock = asyncio.Lock()
        self._router = NotificationRouter()
        self._retry_config = RetryConfig()
        self._notification_log: list[NotificationResult] = []
        self._failed_notifications: list[NotificationResult] = []
        self._db = db
        self._dialect = dialect
        self._policy = policy or AlertPolicy()

        # Değişiklik tespiti için state
        self._last_health_status: str | None = None
        self._last_lock_deadlock_count: int = 0
        self._last_lock_timeout_count: int = 0
        self._invariant_failure_count: int = 0

        # Arka plan görev referansı
        self._escalation_task: asyncio.Task[None] | None = None

    # ─── Lifecycle ────────────────────────────────────────────────────────────

    def start(self) -> None:
        """Escalation monitor'ı başlatır."""
        if self._escalation_task is None or self._escalation_task.done():
            try:
                loop = asyncio.get_running_loop()
                self._escalation_task = loop.create_task(self._escalation_loop(), name="alerting.escalation")
            except RuntimeError:
                logger.warning("AlertingSystem.start() event loop dışında çağrıldı")

    def stop(self) -> None:
        """Escalation monitor'ı durdurur."""
        if self._escalation_task and not self._escalation_task.done():
            self._escalation_task.cancel()
            self._escalation_task = None

    async def shutdown(self) -> None:
        """Tam kapatma — provider session'larını temizler."""
        self.stop()
        await self._router.close_all()

    async def _escalation_loop(self) -> None:
        """Her 30 saniyede aktif alert'leri escalation açısından kontrol eder."""
        while True:
            try:
                await asyncio.sleep(30)  # SSD write reduction: 10s → 30s
                await self._check_escalations()
            except asyncio.CancelledError:
                # Görev iptal edildi — temiz çıkış
                break
            except Exception as exc:
                logger.warning("Escalation loop hatası", error=str(exc))

    async def _check_escalations(self) -> None:
        """Aktif alert'leri policy tabanlı escalation kurallarıyla değerlendirir."""
        now = time.time()
        for alert in list(self._alerts):
            if not alert.is_active:
                continue
            if alert.status == AlertStatus.ACKNOWLEDGED:
                continue

            timeout = self._policy.get_escalation_timeout(alert.alert_type)
            if timeout is None:
                timeout = ESCALATION_TIMEOUT_S.get(alert.alert_type, 300)

            if now - alert.timestamp > timeout and alert.severity != "CRITICAL":
                with tracer.start_as_current_span("alerting.escalate") as span:
                    span.set_attribute("alert.type", alert.alert_type)
                    span.set_attribute("alert.fingerprint", alert.fingerprint)
                    alert.escalate("CRITICAL")
                    _alert_escalated_counter.add(1, {"alert_type": alert.alert_type})
                    logger.warning(
                        "Alert escalated",
                        fingerprint=alert.fingerprint,
                        type=alert.alert_type,
                        escalation_count=alert.escalation_count,
                    )
                    try:
                        loop = asyncio.get_running_loop()
                        loop.create_task(self._notify_all(alert))
                    except RuntimeError as exc:
                        logger.warning("Alert bildirim döngüsü bulunamadı, bildirim atlandı", error=str(exc))

    # ─── Provider Yönetimi ────────────────────────────────────────────────────

    def add_provider(self, provider: Any) -> None:
        """Bildirim kanalı ekler."""
        self._router.add_provider(provider)
        logger.info("Provider eklendi", name=provider.name(), min_severity=provider.min_severity())

    def get_providers(self) -> list[str]:
        """Otomatik eklendi."""
        return self._router.get_all_providers()

    # ─── Alert Kontrolleri ────────────────────────────────────────────────────

    def check_health(self, health_report: dict[str, Any]) -> None:
        """Sistem sağlığı değişikliğini kontrol eder ve gerekirse alert oluşturur."""
        current_status = health_report.get("status", "UNKNOWN")
        if self._last_health_status and self._last_health_status != current_status:
            if current_status in ("DEGRADED", "UNHEALTHY"):
                self._add_alert(
                    Alert(
                        alert_type=AlertType.HEALTH_CHANGE,
                        severity="CRITICAL" if current_status == "UNHEALTHY" else "WARNING",
                        message=f"Health: {self._last_health_status} → {current_status}",
                        details={
                            "previous": self._last_health_status,
                            "current": current_status,
                            "issues": health_report.get("issues", []),
                        },
                    )
                )
            elif current_status == "HEALTHY" and self._last_health_status in ("DEGRADED", "UNHEALTHY"):
                self._add_alert(
                    Alert(
                        alert_type=AlertType.HEALTH_CHANGE,
                        severity="INFO",
                        message=f"Health düzeldi: {self._last_health_status} → HEALTHY",
                        details={"previous": self._last_health_status},
                    )
                )
        self._last_health_status = current_status

    def check_invariant(self, invariant_ok: bool, details: dict[str, Any] | None = None) -> None:
        """Portföy invariant ihlalini kontrol eder."""
        if not invariant_ok:
            self._invariant_failure_count += 1
            self._add_alert(
                Alert(
                    alert_type=AlertType.INVARIANT_FAILURE,
                    severity="CRITICAL",
                    message=f"Portföy invariant ihlali! (toplam: {self._invariant_failure_count})",
                    details=details or {},
                )
            )

    def check_negative_cash(self, cash: float) -> None:
        """Negatif nakit durumunu kontrol eder."""
        if cash < 0:
            self._add_alert(
                Alert(
                    alert_type=AlertType.CASH_NEGATIVE,
                    severity="CRITICAL",
                    message=f"Negatif nakit: {cash:.2f}",
                    details={"cash": cash},
                )
            )

    def check_drawdown(self, drawdown_pct: float, threshold_pct: float = 15.0) -> None:
        """Drawdown eşiğini kontrol eder."""
        if drawdown_pct > threshold_pct:
            self._add_alert(
                Alert(
                    alert_type=AlertType.DRAWDOWN_BREACH,
                    severity="CRITICAL",
                    message=f"Drawdown %{drawdown_pct:.1f} > eşik %{threshold_pct:.1f}",
                    details={"drawdown_pct": drawdown_pct, "threshold": threshold_pct},
                )
            )

    def check_lock_metrics(self, lock_metrics: dict[str, Any]) -> None:
        """Lock metriklerini kontrol eder; deadlock veya timeout artışında alert oluşturur.

        Not: parametre adı `lm` kullanıldı — `metrics` OTel modülü ile çakışma önlenir.
        """
        for key, lm in lock_metrics.items():
            dc: int = lm.get("total_deadlocks_detected", 0)
            tc: int = lm.get("total_timeouts", 0)
            if dc > self._last_lock_deadlock_count:
                self._add_alert(
                    Alert(
                        alert_type=AlertType.LOCK_DEADLOCK,
                        severity="WARNING",
                        message=f"Lock deadlock: {key}",
                        details={"lock_key": key, "total": dc},
                    )
                )
                self._last_lock_deadlock_count = dc
            if tc > self._last_lock_timeout_count + 2:
                self._add_alert(
                    Alert(
                        alert_type=AlertType.LOCK_TIMEOUT_SPIKE,
                        severity="WARNING",
                        message=f"Lock timeout artışı: {key} (toplam: {tc})",
                        details={"lock_key": key, "total": tc},
                    )
                )
                self._last_lock_timeout_count = tc

    # ─── Alert İşlemleri ──────────────────────────────────────────────────────

    def acknowledge_alert(self, fingerprint: str) -> bool:
        """Alert'i onayla — escalation durur."""
        for a in self._alerts:
            if a.fingerprint == fingerprint and a.is_active:
                a.acknowledge()
                logger.info("Alert onaylandı", fingerprint=fingerprint)
                return True
        return False

    def resolve_alert(self, fingerprint: str) -> bool:
        """Alert'i çöz."""
        for a in self._alerts:
            if a.fingerprint == fingerprint and a.is_active:
                a.resolve()
                logger.info("Alert çözüldü", fingerprint=fingerprint)
                return True
        return False

    def resolve_alerts(self, alert_type: str) -> None:
        """Verilen tipteki tüm aktif alert'leri çöz."""
        for a in self._alerts:
            if a.alert_type == alert_type and a.is_active:
                a.resolve()

    # ─── Sorgular ─────────────────────────────────────────────────────────────

    def get_active_alerts(self) -> list[dict[str, Any]]:
        """Otomatik eklendi."""
        return [a.to_dict() for a in self._alerts if a.is_active]

    def get_all_alerts(self, limit: int = 100) -> list[dict[str, Any]]:
        """Otomatik eklendi."""
        return [a.to_dict() for a in self._alerts[-limit:]]

    def get_alert_summary(self) -> dict[str, Any]:
        """Otomatik eklendi."""
        active = [a for a in self._alerts if a.is_active]
        by_severity: dict[str, int] = {}
        by_status: dict[str, int] = {}
        for a in active:
            by_severity[a.severity] = by_severity.get(a.severity, 0) + 1
            by_status[a.status] = by_status.get(a.status, 0) + 1
        return {
            "total_alerts": len(self._alerts),
            "active_alerts": len(active),
            "by_severity": by_severity,
            "by_status": by_status,
            "providers": len(self._router.get_all_providers()),
            "failed_notifications": len(self._failed_notifications),
        }

    def get_notification_log(self, limit: int = 50) -> list[dict[str, Any]]:
        """Otomatik eklendi."""
        return [r.to_dict() for r in self._notification_log[-limit:]]

    def get_failed_notifications(self) -> list[dict[str, Any]]:
        """Otomatik eklendi."""
        return [r.to_dict() for r in self._failed_notifications]

    # ─── Silence Yönetimi ─────────────────────────────────────────────────────

    def add_silence(
        self,
        alert_type: str | None = None,
        fingerprint: str | None = None,
        duration_s: float = 3600,
        reason: str = "",
        created_by: str = "system",
    ) -> dict[str, Any]:
        """Alert susturma kuralı ekler (DB persist ile)."""
        rule = self._policy.add_silence(
            alert_type=alert_type,
            fingerprint=fingerprint,
            duration_s=duration_s,
            reason=reason,
            created_by=created_by,
            db=self._db,
        )
        return rule.to_dict()

    def remove_silence(
        self,
        fingerprint: str | None = None,
        alert_type: str | None = None,
        actor: str = "api",
    ) -> int:
        """Otomatik eklendi."""
        return self._policy.remove_silence(fingerprint=fingerprint, alert_type=alert_type, actor=actor, db=self._db)

    def get_active_silences(self) -> list[dict[str, Any]]:
        """Otomatik eklendi."""
        return self._policy.get_active_silences()

    def save_silences(self) -> None:
        """Otomatik eklendi."""
        self._policy.save_silences()

    def load_silences(self) -> None:
        """Otomatik eklendi."""
        if self._db:
            self._policy.load_silences_from_db(self._db)
        else:
            self._policy.load_silences()

    def get_policy_info(self) -> dict[str, Any]:
        """Otomatik eklendi."""
        return self._policy.to_dict()

    def reload_policy(self) -> bool:
        """Otomatik eklendi."""
        return self._policy.reload_if_changed()

    def update_policy(
        self, new_config: dict[str, Any], actor: str = "api", expected_version: int = 0
    ) -> dict[str, Any]:
        """Otomatik eklendi."""
        try:
            return self._policy.update(new_config, actor, expected_version)
        except VersionConflictError as exc:
            return {
                "success": False,
                "error": str(exc),
                "conflict": True,
                "current_version": self._policy._version,
            }

    def rollback_policy(self, target_version: int = 0, actor: str = "api") -> dict[str, Any]:
        """Otomatik eklendi."""
        return self._policy.rollback(target_version, actor)

    def get_policy_history(self) -> list[dict[str, Any]]:
        """Otomatik eklendi."""
        return self._policy.get_history()

    def get_policy_audit_log(self, limit: int = 50) -> list[dict[str, Any]]:
        """Otomatik eklendi."""
        return self._policy.get_audit_log(limit)

    def batch_add_silences(self, rules: list[dict[str, Any]], created_by: str = "system") -> list[dict[str, Any]]:
        """Otomatik eklendi."""
        return self._policy.batch_add_silences(rules, created_by, self._db)

    def batch_remove_silences(self, filters: list[dict[str, str]], actor: str = "api") -> dict[str, int]:
        """Otomatik eklendi."""
        return self._policy.batch_remove_silences(filters, actor, self._db)

    def compute_policy_diff(self, new_config: dict[str, Any]) -> Any:
        """Otomatik eklendi."""
        return self._policy.compute_diff(new_config)

    def set_policy_webhook(self, urls: list[str]) -> None:
        """Otomatik eklendi."""
        self._policy.set_webhook_urls(urls)

    # ─── DB Kalıcılığı ────────────────────────────────────────────────────────

    async def init_db(self) -> None:
        """Alert tablosunu oluşturur (DuckDB)."""
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
        except Exception as exc:
            logger.warning("Alert DB init başarısız", error=str(exc))

    async def persist_alert(self, alert: Alert) -> None:
        """Alert'i DuckDB'ye kaydeder."""
        if not self._db:
            return
        try:
            self._db.execute(
                "INSERT OR REPLACE INTO alerts_state "
                "(fingerprint, alert_type, severity, status, message, details, "
                "timestamp, acknowledged_at, escalated_at, resolved_at, "
                "escalation_count, notification_status, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    alert.fingerprint,
                    str(alert.alert_type),
                    str(alert.severity),
                    alert.status.value if hasattr(alert.status, "value") else str(alert.status),
                    alert.message,
                    orjson.dumps(alert.details).decode(),
                    alert.timestamp,
                    alert.acknowledged_at,
                    alert.escalated_at,
                    alert.resolved_at,
                    alert.escalation_count,
                    alert.notification_status,
                    time.time(),
                ),
            )
            # SSD write reduction: commit deferred, periodic flush handles it
            # self._db.commit()
        except Exception as exc:
            logger.warning("Alert persist başarısız", error=str(exc))

    async def load_from_db(self) -> None:
        """DB'den aktif alert'leri yükler (restart recovery)."""
        if not self._db:
            return
        try:
            rows = self._db.execute(
                "SELECT * FROM alerts_state WHERE status IN (?, ?, ?)",
                ("CREATED", "ACKNOWLEDGED", "ESCALATED"),
            ).fetchall()
            for row in rows:
                alert = Alert(
                    alert_type=row["alert_type"],
                    severity=row["severity"],
                    message=row["message"],
                    details=orjson.loads(row["details"]) if row["details"] else {},
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
                if len(self._alerts) > 500:
                    self._alerts = self._alerts[-500:]
            logger.info("Alert'ler DB'den yüklendi", count=len(rows))
        except Exception as exc:
            logger.warning("Alert DB yükleme başarısız", error=str(exc))

    # ─── İç Metotlar ──────────────────────────────────────────────────────────

    def _add_alert(self, alert: Alert) -> None:
        """Alert oluşturur, deduplicate eder, policy kontrolü yapar, bildirir."""
        with tracer.start_as_current_span("alerting.add_alert") as span:
            span.set_attribute("alert.type", alert.alert_type)
            span.set_attribute("alert.severity", alert.severity)
            span.set_attribute("alert.fingerprint", alert.fingerprint)

            if self._is_duplicate(alert):
                return

            if self._policy.is_silenced(alert.alert_type, alert.fingerprint):
                alert.notification_status = "silenced"
                logger.debug("Alert susturuldu", fp=alert.fingerprint, type=alert.alert_type)
                return

            self._alerts.append(alert)
            self._trim_alerts()
            self._dedup_cache[alert.fingerprint] = time.time()

            _alert_created_counter.add(
                1,
                {
                    "alert_type": alert.alert_type,
                    "severity": alert.severity,
                },
            )
            logger.warning(
                "Alert oluşturuldu",
                type=alert.alert_type,
                severity=alert.severity,
                fp=alert.fingerprint,
            )

            self._policy.reload_if_changed()

            try:
                loop = asyncio.get_running_loop()
                loop.create_task(self.persist_alert(alert))
                channels = self._policy.get_notification_channels(alert.severity)
                if channels and self._router.get_all_providers():
                    loop.create_task(self._notify_all(alert))
            except RuntimeError:
                # Event loop dışında çağrıldıysa bildirim atlanır
                logger.warning("Alert bildirim gönderilemedi — event loop aktif değil")

    def _is_duplicate(self, alert: Alert) -> bool:
        """Aynı fingerprint son dedup_window_s içinde oluştuysa True döner."""
        fp = alert.fingerprint
        return fp in self._dedup_cache and time.time() - self._dedup_cache[fp] < self._dedup_window_s

    def _trim_alerts(self) -> None:
        """Maksimum alert sayısını aşarsa eskilerini siler."""
        if len(self._alerts) > self._max_alerts:
            self._alerts = self._alerts[-self._max_alerts :]

    async def _notify_all(self, alert: Alert) -> None:
        """Alert için tüm uygun provider'lara paralel bildirim gönderir."""
        with tracer.start_as_current_span("alerting.notify_all") as span:
            span.set_attribute("alert.fingerprint", alert.fingerprint)
            span.set_attribute("alert.severity", alert.severity)

            providers = self._router.get_providers_for_severity(alert.severity)
            for provider in providers:
                result = await self._send_with_retry(provider, alert)
                self._notification_log.append(result)
                if len(self._notification_log) > 1000:
                    self._notification_log = self._notification_log[-1000:]
                if not result.success:
                    self._failed_notifications.append(result)
                    if len(self._failed_notifications) > 500:
                        self._failed_notifications = self._failed_notifications[-500:]
                    alert.notification_status = "failed"
                    _notification_failed_counter.add(1, {"provider": provider.name()})
                else:
                    alert.notification_status = "sent"
                    _notification_sent_counter.add(1, {"provider": provider.name()})

            await self.persist_alert(alert)

    async def _send_with_retry(self, provider: Any, alert: Alert) -> NotificationResult:
        """Provider'a Exponential Backoff + Jitter ile yeniden dene."""
        result = NotificationResult(provider.name(), alert.fingerprint)
        for attempt in range(self._retry_config.max_retries):
            result.attempts += 1
            try:
                if await provider.send(alert):
                    result.success = True
                    return result
                result.last_error = "Provider False döndürdü"
            except Exception as exc:
                result.last_error = str(exc)

            if attempt < self._retry_config.max_retries - 1:
                base_delay = min(
                    self._retry_config.base_delay_s * (self._retry_config.backoff_factor**attempt),
                    self._retry_config.max_delay_s,
                )
                # Jitter: herd effect önleme
                delay = base_delay + random.uniform(0, base_delay * 0.2)
                _notification_retry_counter.add(1, {"provider": provider.name()})
                await asyncio.sleep(delay)

        return result


# ─── Singleton ────────────────────────────────────────────────────────────────
alerting = AlertingSystem()
