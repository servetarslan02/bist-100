"""ALPHA BIST — Alarm Yönetim ve Bildirim Sistemi v4.0 (Enterprise-Grade).

Bu modül, platform genelinde kritik olayların, kural ihlallerinin ve sağlık
durumu değişikliklerinin tespit edilip bildirim kanallarına (Log, Webhook, Slack,
Discord, PagerDuty, E-posta) güvenli ve esnek şekilde yönlendirilmesini sağlar:
- SOLID prensiplerine uygun NotificationProvider Protocol ve NotificationRouter
- Exponential backoff ve jitter ile dayanıklı bildirim yeniden deneme mekanizması
- OpenTelemetry span'leri ve Prometheus sayaçları ile tam izlenebilirlik
- DuckDB kalıcı durum kaydı ile sistem yeniden başlatma sonrası alarm kurtarma
- Parmak izi (fingerprint) ve süre tabanlı mükerrer alarm engelleme (deduplication)
"""

from __future__ import annotations

import asyncio
import hashlib
import os
import random
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Protocol, runtime_checkable

import httpx
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
    """Alarm önem derecesi sınıflandırması."""

    INFO = "INFO"
    WARNING = "WARNING"
    CRITICAL = "CRITICAL"


class AlertStatus(StrEnum):
    """Alarm yaşam döngüsü durumları."""

    CREATED = "CREATED"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    ESCALATED = "ESCALATED"
    RESOLVED = "RESOLVED"


class AlertType(StrEnum):
    """Sistemde tanımlı alarm türleri."""

    HEALTH_CHANGE = "health_change"
    INVARIANT_FAILURE = "invariant_failure"
    LOCK_DEADLOCK = "lock_deadlock"
    LOCK_TIMEOUT_SPIKE = "lock_timeout_spike"
    CASH_NEGATIVE = "cash_negative"
    DRAWDOWN_BREACH = "drawdown_breach"


# Escalation zaman aşımları — politika tanımlı değilse bu varsayılan kullanılır
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
    """Tek bir alarm kaydı — tam yaşam döngüsü (lifecycle) desteği ile."""

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
        """Parmak izi boşsa otomatik hesaplar."""
        if not self.fingerprint:
            self.fingerprint = self._compute_fingerprint()

    def __repr__(self) -> str:
        """Alarm kaydının dize temsili."""
        return (
            f"<Alert(type='{self.alert_type}', severity='{self.severity}', "
            f"status='{self.status}', fp='{self.fingerprint}')>"
        )

    def _compute_fingerprint(self) -> str:
        """Alert için deterministik SHA256 parmak izi hesaplar."""
        key = f"{self.alert_type}:{orjson.dumps(self.details, option=orjson.OPT_SORT_KEYS).decode()}"
        return hashlib.sha256(key.encode()).hexdigest()[:16]

    def acknowledge(self) -> None:
        """Alarmı onaylandı durumuna geçirir; eskalasyon döngüsü durur."""
        self.status = AlertStatus.ACKNOWLEDGED
        self.acknowledged_at = time.time()

    def escalate(self, new_severity: str = "CRITICAL") -> None:
        """Alarmın önem derecesini yükseltir ve eskalasyon sayacını artırır."""
        self.status = AlertStatus.ESCALATED
        self.severity = new_severity
        self.escalated_at = time.time()
        self.escalation_count += 1

    def resolve(self) -> None:
        """Alarmı çözüldü olarak işaretler."""
        self.status = AlertStatus.RESOLVED
        self.resolved_at = time.time()

    @property
    def is_active(self) -> bool:
        """Alarmın hâlâ aktif işlem gerektirip gerektirmediğini doğrular."""
        return self.status in (AlertStatus.CREATED, AlertStatus.ACKNOWLEDGED, AlertStatus.ESCALATED)

    def timestamp_iso_str(self) -> str:
        """Alarm zaman damgasını UTC ISO-8601 formatında döndürür."""
        return datetime.fromtimestamp(self.timestamp, tz=UTC).isoformat()

    def to_dict(self) -> dict[str, Any]:
        """Alarm nesnesini JSON uyumlu sözlüğe serileştirir."""
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
        """Genel webhook entegrasyonları için yük formatı oluşturur."""
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
        """Slack bildirimleri için ekli format üretir."""
        color = {"INFO": "#36a64f", "WARNING": "#ff9900", "CRITICAL": "#ff0000"}.get(self.severity, "#999999")
        return {
            "attachments": [
                {
                    "color": color,
                    "title": f"[{self.severity}] {self.alert_type}",
                    "text": self.message,
                    "fields": [
                        {"title": "Durum", "value": self.status, "short": True},
                        {"title": "Eskalasyon", "value": str(self.escalation_count), "short": True},
                    ],
                    "ts": int(self.timestamp),
                }
            ]
        }

    def to_discord_payload(self) -> dict[str, Any]:
        """Discord webhook kanalı için embed nesnesi oluşturur."""
        color = {"INFO": 0x36A64F, "WARNING": 0xFF9900, "CRITICAL": 0xFF0000}.get(self.severity, 0x999999)
        return {
            "embeds": [
                {
                    "title": f"[{self.severity}] {self.alert_type}",
                    "description": self.message,
                    "color": color,
                    "fields": [
                        {"name": "Durum", "value": self.status, "inline": True},
                        {"name": "Eskalasyon", "value": str(self.escalation_count), "inline": True},
                    ],
                    "timestamp": self.timestamp_iso_str(),
                }
            ]
        }

    def to_pagerduty_payload(self, routing_key: str = "") -> dict[str, Any]:
        """PagerDuty Events API v2 formatında yük oluşturur."""
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
    """Bildirim kanalları için arayüz (Protocol)."""

    async def send(self, alert: Alert) -> bool:
        """Alarmı ilgili kanala iletir."""
        ...

    def name(self) -> str:
        """Kanal sağlayıcısının tanımlayıcı adını döner."""
        ...

    def min_severity(self) -> str:
        """Kanalın kabul ettiği minimum önem derecesini döner."""
        ...

    async def close(self) -> None:
        """Bağlantı ve kaynakları temizler."""
        ...


# ─── Provider Implementasyonları ─────────────────────────────────────────────


@dataclass
class LogProvider:
    """Structlog üzerinden alarmları yapısal loglayan sağlayıcı."""

    _name: str = "log"

    def __repr__(self) -> str:
        """Sağlayıcı dize temsili."""
        return f"<LogProvider(name='{self._name}')>"

    def name(self) -> str:
        """Kanal adını döner."""
        return self._name

    def min_severity(self) -> str:
        """Kabul edilen minimum önem derecesi."""
        return "INFO"

    async def send(self, alert: Alert) -> bool:
        """Alarmı structlog ile sisteme kaydeder."""
        logger.warning(
            "ALARM_BILDIRIMI",
            alert_type=alert.alert_type,
            severity=alert.severity,
            status=alert.status,
            message=alert.message,
            fingerprint=alert.fingerprint,
        )
        return True

    async def close(self) -> None:
        """Log sağlayıcısı için kaynak temizliği."""
        return None


@dataclass
class WebhookProvider:
    """HTTP POST webhook ile alarm ileten sağlayıcı."""

    url: str
    headers: dict[str, str] = field(default_factory=dict)
    timeout: float = 10.0
    _client: httpx.AsyncClient | None = field(default=None, init=False, repr=False)

    def __repr__(self) -> str:
        """Sağlayıcı dize temsili."""
        return f"<WebhookProvider(url='{self.url[:30]}...')>"

    def name(self) -> str:
        """Kanal adını döner."""
        return f"webhook:{self.url[:50]}"

    def min_severity(self) -> str:
        """Kabul edilen minimum önem derecesi."""
        return "WARNING"

    async def _get_client(self) -> httpx.AsyncClient:
        """Yeniden kullanılabilir singleton HTTP istemcisi döner."""
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=self.timeout)
        return self._client

    async def send(self, alert: Alert) -> bool:
        """Alarm yükünü belirtilen URL adresine iletir."""
        try:
            client = await self._get_client()
            resp = await client.post(
                self.url,
                content=orjson.dumps(alert.to_webhook_payload()),
                headers={"Content-Type": "application/json", **self.headers},
            )
            return resp.status_code < 400
        except Exception as exc:
            logger.error("webhook_gonderim_hatasi", url=self.url, error=str(exc))
            return False

    async def close(self) -> None:
        """Açık HTTP oturumunu kapatır."""
        if self._client and not self._client.is_closed:
            await self._client.aclose()


@dataclass
class SlackProvider:
    """Slack Webhook üzerinden alarm ileten sağlayıcı."""

    webhook_url: str
    timeout: float = 10.0
    _client: httpx.AsyncClient | None = field(default=None, init=False, repr=False)

    def __repr__(self) -> str:
        """Sağlayıcı dize temsili."""
        return "<SlackProvider>"

    def name(self) -> str:
        """Kanal adı."""
        return "slack"

    def min_severity(self) -> str:
        """Minimum önem derecesi."""
        return "CRITICAL"

    async def _get_client(self) -> httpx.AsyncClient:
        """Slack istemcisi döner."""
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=self.timeout)
        return self._client

    async def send(self, alert: Alert) -> bool:
        """Alarmı Slack webhook kanalına iletir."""
        try:
            client = await self._get_client()
            resp = await client.post(
                self.webhook_url,
                content=orjson.dumps(alert.to_slack_payload()),
                headers={"Content-Type": "application/json"},
            )
            return resp.status_code < 400
        except Exception as exc:
            logger.error("slack_gonderim_hatasi", error=str(exc))
            return False

    async def close(self) -> None:
        """HTTP istemcisini kapatır."""
        if self._client and not self._client.is_closed:
            await self._client.aclose()


@dataclass
class DiscordProvider:
    """Discord Webhook üzerinden zengin içerikli alarm ileten sağlayıcı."""

    webhook_url: str
    timeout: float = 10.0
    _client: httpx.AsyncClient | None = field(default=None, init=False, repr=False)

    def __repr__(self) -> str:
        """Sağlayıcı dize temsili."""
        return "<DiscordProvider>"

    def name(self) -> str:
        """Kanal adı."""
        return "discord"

    def min_severity(self) -> str:
        """Minimum önem derecesi."""
        return "CRITICAL"

    async def _get_client(self) -> httpx.AsyncClient:
        """Discord istemcisi döner."""
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=self.timeout)
        return self._client

    async def send(self, alert: Alert) -> bool:
        """Alarmı Discord kanalına gönderir."""
        try:
            client = await self._get_client()
            resp = await client.post(
                self.webhook_url,
                content=orjson.dumps(alert.to_discord_payload()),
                headers={"Content-Type": "application/json"},
            )
            return resp.status_code < 400
        except Exception as exc:
            logger.error("discord_gonderim_hatasi", error=str(exc))
            return False

    async def close(self) -> None:
        """HTTP istemcisini kapatır."""
        if self._client and not self._client.is_closed:
            await self._client.aclose()


@dataclass
class PagerDutyProvider:
    """PagerDuty Events API v2 üzerinden çağrı ve nöbetçi bildirimi ileten sağlayıcı."""

    routing_key: str
    timeout: float = 10.0
    _client: httpx.AsyncClient | None = field(default=None, init=False, repr=False)

    def __repr__(self) -> str:
        """Sağlayıcı dize temsili."""
        return "<PagerDutyProvider>"

    def name(self) -> str:
        """Kanal adı."""
        return "pagerduty"

    def min_severity(self) -> str:
        """Minimum önem derecesi."""
        return "CRITICAL"

    async def _get_client(self) -> httpx.AsyncClient:
        """PagerDuty istemcisi döner."""
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=self.timeout)
        return self._client

    async def send(self, alert: Alert) -> bool:
        """Alarmı PagerDuty servisine iletir."""
        try:
            client = await self._get_client()
            resp = await client.post(
                "https://events.pagerduty.com/v2/enqueue",
                content=orjson.dumps(alert.to_pagerduty_payload(self.routing_key)),
                headers={"Content-Type": "application/json"},
            )
            return resp.status_code < 400
        except Exception as exc:
            logger.error("pagerduty_gonderim_hatasi", error=str(exc))
            return False

    async def close(self) -> None:
        """HTTP istemcisini kapatır."""
        if self._client and not self._client.is_closed:
            await self._client.aclose()


@dataclass
class EmailProvider:
    """SMTP protokolü üzerinden e-posta bildirimleri gönderen sağlayıcı."""

    to_addresses: list[str] = field(default_factory=list)
    from_address: str = "alerts@alpha-bist.local"
    smtp_host: str = field(default_factory=lambda: os.environ.get("SMTP_HOST", "localhost"))
    smtp_port: int = field(default_factory=lambda: int(os.environ.get("SMTP_PORT", "587")))
    username: str = field(default_factory=lambda: os.environ.get("SMTP_USERNAME", ""))
    password: str = field(default_factory=lambda: os.environ.get("SMTP_PASSWORD", ""))

    def __repr__(self) -> str:
        """Sağlayıcı dize temsili."""
        return f"<EmailProvider(recipients={len(self.to_addresses)})>"

    def name(self) -> str:
        """Kanal adı."""
        return f"email:{','.join(self.to_addresses[:3])}"

    def min_severity(self) -> str:
        """Minimum önem derecesi."""
        return "CRITICAL"

    async def send(self, alert: Alert) -> bool:
        """Alarmı e-posta olarak gönderir."""
        if not self.to_addresses:
            return False
        try:
            from email.mime.text import MIMEText

            msg = MIMEText(
                f"Alarm Türü: {alert.alert_type}\nÖnem: {alert.severity}\n"
                f"Durum: {alert.status}\nMesaj: {alert.message}\n"
                f"Detaylar: {orjson.dumps(alert.details, option=orjson.OPT_INDENT_2).decode()}"
            )
            msg["Subject"] = f"[{alert.severity}] ALPHA BIST: {alert.alert_type}"
            msg["From"] = self.from_address
            msg["To"] = ", ".join(self.to_addresses)
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(None, self._send_smtp, msg)
            return True
        except Exception as exc:
            logger.error("eposta_gonderim_hatasi", error=str(exc))
            return False

    def _send_smtp(self, msg: Any) -> None:
        """SMTP bağlantısı kurup e-postayı iletir."""
        import smtplib

        with smtplib.SMTP(self.smtp_host, self.smtp_port) as s:
            if self.username:
                s.starttls()
                s.login(self.username, self.password)
            s.send_message(msg)

    async def close(self) -> None:
        """E-posta sağlayıcısı kaynak temizliği."""
        return None


# ─── Notification Router ──────────────────────────────────────────────────────


class NotificationRouter:
    """Önem derecesine göre uygun bildirim kanallarını yönlendiren bileşen."""

    _SEVERITY_ORDER: dict[str, int] = {"INFO": 0, "WARNING": 1, "CRITICAL": 2}

    def __init__(self) -> None:
        """Yönlendiriciyi başlatır."""
        self._providers: list[NotificationProvider] = []

    def __repr__(self) -> str:
        """Yönlendirici dize temsili."""
        return f"<NotificationRouter(providers={len(self._providers)})>"

    def add_provider(self, provider: NotificationProvider) -> None:
        """Yeni bir bildirim sağlayıcısı kaydeder (maksimum 100 kanal)."""
        self._providers.append(provider)
        if len(self._providers) > 100:
            self._providers = self._providers[-100:]

    def get_providers_for_severity(self, severity: str) -> list[NotificationProvider]:
        """Belirtilen önem derecesine uygun bildirim sağlayıcılarını listeler."""
        target_level = self._SEVERITY_ORDER.get(severity, 0)
        return [p for p in self._providers if self._SEVERITY_ORDER.get(p.min_severity(), 999) <= target_level]

    def get_all_providers(self) -> list[str]:
        """Tüm kayıtlı bildirim kanallarının adlarını döndürür."""
        return [p.name() for p in self._providers]

    async def close_all(self) -> None:
        """Tüm sağlayıcıların oturumlarını ve bağlantılarını sonlandırır."""
        for provider in self._providers:
            try:
                await provider.close()
            except Exception as exc:
                p_name = provider.name() if hasattr(provider, "name") and callable(provider.name) else str(provider)
                logger.warning("saglayici_kapatilamadi", provider=p_name, error=str(exc))


# ─── Retry Konfigürasyonu ─────────────────────────────────────────────────────


@dataclass
class RetryConfig:
    """Bildirim yeniden deneme parametreleri."""

    max_retries: int = 3
    base_delay_s: float = 1.0
    max_delay_s: float = 30.0
    backoff_factor: float = 2.0

    def __repr__(self) -> str:
        """Yeniden deneme ayarları dize temsili."""
        return f"<RetryConfig(retries={self.max_retries}, factor={self.backoff_factor})>"


class NotificationResult:
    """Tek bir bildirim denemesinin sonucunu temsil eden sınıf."""

    def __init__(self, provider_name: str, alert_fingerprint: str) -> None:
        """Bildirim sonucunu başlatır."""
        self.provider_name = provider_name
        self.alert_fingerprint = alert_fingerprint
        self.attempts: int = 0
        self.success: bool = False
        self.last_error: str | None = None

    def __repr__(self) -> str:
        """Sonucun dize temsili."""
        return (
            f"<NotificationResult(provider='{self.provider_name}', "
            f"success={self.success}, attempts={self.attempts})>"
        )

    def to_dict(self) -> dict[str, Any]:
        """Sonuç verisini sözlüğe çevirir."""
        return {
            "provider": self.provider_name,
            "fingerprint": self.alert_fingerprint,
            "attempts": self.attempts,
            "success": self.success,
            "last_error": self.last_error,
        }


# ─── AlertingSystem ───────────────────────────────────────────────────────────


class AlertingSystem:
    """v4.0 — Kurumsal seviye alarm yaşam döngüsü, OTel, DuckDB kalıcılık ve bildirim motoru."""

    def __init__(
        self,
        max_alerts: int = 1000,
        dedup_window_s: float = 300.0,
        db: Any = None,
        dialect: str = "duckdb",
        policy: AlertPolicy | None = None,
    ) -> None:
        """Alarm sistemini başlatır.

        Args:
            max_alerts: Bellekte tutulacak maksimum alarm sayısı.
            dedup_window_s: Mükerrer alarm engelleme penceresi süresi (saniye).
            db: DuckDB bağlantısı (sistem yeniden başlama kurtarması için).
            dialect: Veritabanı lehçesi (varsayılan: duckdb).
            policy: Özelleştirilmiş AlertPolicy nesnesi.
        """
        self._max_alerts = max_alerts
        self._alerts: deque[Alert] = deque(maxlen=self._max_alerts)
        self._dedup_window_s = dedup_window_s
        self._dedup_cache: dict[str, float] = {}
        self._dedup_lock: asyncio.Lock = asyncio.Lock()
        self._router = NotificationRouter()
        self._retry_config = RetryConfig()
        self._notification_log: deque[NotificationResult] = deque(maxlen=1000)
        self._failed_notifications: deque[NotificationResult] = deque(maxlen=500)
        self._db = db
        self._dialect = dialect
        self._policy = policy or AlertPolicy()

        # Durum izleme alanları
        self._last_health_status: str | None = None
        self._last_lock_deadlock_count: int = 0
        self._last_lock_timeout_count: int = 0
        self._invariant_failure_count: int = 0

        # Arka plan eskalasyon görevi
        self._escalation_task: asyncio.Task[None] | None = None

    def __repr__(self) -> str:
        """Alarm yöneticisinin dize temsili."""
        return (
            f"<AlertingSystem(alerts={len(self._alerts)}, "
            f"active={len(self.get_active_alerts())}, max={self._max_alerts})>"
        )

    # ─── Lifecycle ────────────────────────────────────────────────────────────

    def start(self) -> None:
        """Arka plan eskalasyon izleyicisini başlatır."""
        if self._escalation_task is None or self._escalation_task.done():
            try:
                loop = asyncio.get_running_loop()
                self._escalation_task = loop.create_task(self._escalation_loop(), name="alerting.escalation")
            except RuntimeError:
                logger.warning("alarm_sistemi_event_loop_disinda_baslatildi")

    def stop(self) -> None:
        """Arka plan eskalasyon izleyicisini güvenle durdurur."""
        if self._escalation_task and not self._escalation_task.done():
            self._escalation_task.cancel()
            self._escalation_task = None

    async def shutdown(self) -> None:
        """Tüm sistemi kapatır ve sağlayıcı oturumlarını sonlandırır."""
        self.stop()
        await self._router.close_all()

    async def _escalation_loop(self) -> None:
        """Periyodik olarak aktif alarmları eskalasyon kurallarına göre denetler."""
        while True:
            try:
                await asyncio.sleep(30.0)
                await self._check_escalations()
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.warning("eskalasyon_dongusu_hatasi", error=str(exc))

    async def _check_escalations(self) -> None:
        """Aktif alarmların zaman aşımı durumlarını kontrol eder ve gerekiyorsa eskalasyon tetikler."""
        now = time.time()
        for alert in list(self._alerts):
            if not alert.is_active or alert.status == AlertStatus.ACKNOWLEDGED:
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
                        "alarm_eskalasyonu_gerceklesti",
                        fingerprint=alert.fingerprint,
                        type=alert.alert_type,
                        escalation_count=alert.escalation_count,
                    )
                    try:
                        loop = asyncio.get_running_loop()
                        loop.create_task(self._notify_all(alert))
                    except RuntimeError as exc:
                        logger.warning("alarm_bildirim_dongusu_bulunamadi", error=str(exc))

    # ─── Provider Yönetimi ────────────────────────────────────────────────────

    def add_provider(self, provider: NotificationProvider) -> None:
        """Sisteme yeni bir bildirim sağlayıcısı ekler."""
        self._router.add_provider(provider)
        logger.info("bildirim_saglayici_eklendi", name=provider.name(), min_severity=provider.min_severity())

    def get_providers(self) -> list[str]:
        """Tüm kayıtlı sağlayıcıların adlarını döndürür."""
        return self._router.get_all_providers()

    # ─── Alert Kontrolleri ────────────────────────────────────────────────────

    def check_health(self, health_report: dict[str, Any]) -> None:
        """Sistem sağlık durumu değişimlerini inceler ve gerektiğinde alarm üretir."""
        current_status = health_report.get("status", "UNKNOWN")
        if self._last_health_status and self._last_health_status != current_status:
            if current_status in ("DEGRADED", "UNHEALTHY"):
                self._add_alert(
                    Alert(
                        alert_type=AlertType.HEALTH_CHANGE,
                        severity="CRITICAL" if current_status == "UNHEALTHY" else "WARNING",
                        message=f"Sistem Sağlığı: {self._last_health_status} -> {current_status}",
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
                        message=f"Sistem Sağlığı Düzeldi: {self._last_health_status} -> HEALTHY",
                        details={"previous": self._last_health_status},
                    )
                )
        self._last_health_status = current_status

    def check_invariant(self, invariant_ok: bool, details: dict[str, Any] | None = None) -> None:
        """Portföy veya sistem değişmezlik (invariant) ihlalini denetler."""
        if not invariant_ok:
            self._invariant_failure_count += 1
            self._add_alert(
                Alert(
                    alert_type=AlertType.INVARIANT_FAILURE,
                    severity="CRITICAL",
                    message=f"Portföy değişmezlik ihlali! (toplam: {self._invariant_failure_count})",
                    details=details or {},
                )
            )

    def check_negative_cash(self, cash: float) -> None:
        """Portföy nakit bakiyesinin eksiye düşüp düşmediğini kontrol eder."""
        if cash < 0:
            self._add_alert(
                Alert(
                    alert_type=AlertType.CASH_NEGATIVE,
                    severity="CRITICAL",
                    message=f"Negatif nakit tespit edildi: {cash:.2f} TL",
                    details={"cash": cash},
                )
            )

    def check_drawdown(self, drawdown_pct: float, threshold_pct: float = 15.0) -> None:
        """Portföy değer kaybının (drawdown) kritik eşiği aşıp aşmadığını kontrol eder."""
        if drawdown_pct > threshold_pct:
            self._add_alert(
                Alert(
                    alert_type=AlertType.DRAWDOWN_BREACH,
                    severity="CRITICAL",
                    message=f"Drawdown ihlali: %{drawdown_pct:.1f} > eşik %{threshold_pct:.1f}",
                    details={"drawdown_pct": drawdown_pct, "threshold": threshold_pct},
                )
            )

    def check_lock_metrics(self, lock_metrics: dict[str, Any]) -> None:
        """Veritabanı ve dağıtık kilit metriklerini kontrol eder (deadlock veya aşırı zaman aşımı)."""
        for key, lm in lock_metrics.items():
            dc: int = lm.get("total_deadlocks_detected", 0)
            tc: int = lm.get("total_timeouts", 0)
            if dc > self._last_lock_deadlock_count:
                self._add_alert(
                    Alert(
                        alert_type=AlertType.LOCK_DEADLOCK,
                        severity="WARNING",
                        message=f"Kilit kilitlenmesi (Deadlock) tespit edildi: {key}",
                        details={"lock_key": key, "total": dc},
                    )
                )
                self._last_lock_deadlock_count = dc
            if tc > self._last_lock_timeout_count + 2:
                self._add_alert(
                    Alert(
                        alert_type=AlertType.LOCK_TIMEOUT_SPIKE,
                        severity="WARNING",
                        message=f"Kilit zaman aşımı artışı: {key} (toplam: {tc})",
                        details={"lock_key": key, "total": tc},
                    )
                )
                self._last_lock_timeout_count = tc

    # ─── Alert İşlemleri ──────────────────────────────────────────────────────

    def acknowledge_alert(self, fingerprint: str) -> bool:
        """Parmak izi eşleşen aktif alarmı onaylar."""
        for a in self._alerts:
            if a.fingerprint == fingerprint and a.is_active:
                a.acknowledge()
                logger.info("alarm_onaylandi", fingerprint=fingerprint)
                return True
        return False

    def resolve_alert(self, fingerprint: str) -> bool:
        """Parmak izi eşleşen aktif alarmı çözüldü olarak işaretler."""
        for a in self._alerts:
            if a.fingerprint == fingerprint and a.is_active:
                a.resolve()
                logger.info("alarm_cozuldu", fingerprint=fingerprint)
                return True
        return False

    def resolve_alerts(self, alert_type: str) -> None:
        """Belirtilen tipteki tüm aktif alarmları toplu olarak çözer."""
        for a in self._alerts:
            if a.alert_type == alert_type and a.is_active:
                a.resolve()

    # ─── Sorgular ─────────────────────────────────────────────────────────────

    def get_active_alerts(self) -> list[dict[str, Any]]:
        """Mevcut tüm aktif alarmları döner."""
        return [a.to_dict() for a in self._alerts if a.is_active]

    def get_all_alerts(self, limit: int = 100) -> list[dict[str, Any]]:
        """Sistemdeki son alarmları sözlük listesi olarak döner."""
        return [a.to_dict() for a in list(self._alerts)[-limit:]]

    def get_alert_summary(self) -> dict[str, Any]:
        """Sistem alarmlarının istatistiksel özetini döner."""
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
        """Son bildirim denemelerinin geçmiş logunu döner."""
        return [r.to_dict() for r in list(self._notification_log)[-limit:]]

    def get_failed_notifications(self) -> list[dict[str, Any]]:
        """Başarısız olan bildirim denemelerini listeler."""
        return [r.to_dict() for r in self._failed_notifications]

    # ─── Silence Yönetimi ─────────────────────────────────────────────────────

    def add_silence(
        self,
        alert_type: str | None = None,
        fingerprint: str | None = None,
        duration_s: float = 3600.0,
        reason: str = "",
        created_by: str = "system",
    ) -> dict[str, Any]:
        """Yeni bir susturma kuralı ekler."""
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
        """Susturma kuralını kaldırır."""
        return self._policy.remove_silence(fingerprint=fingerprint, alert_type=alert_type, actor=actor, db=self._db)

    def get_active_silences(self) -> list[dict[str, Any]]:
        """Mevcut aktif susturma kurallarını listeler."""
        return self._policy.get_active_silences()

    def reload_policy(self) -> bool:
        """Politika dosyasını yeniden yükler."""
        return self._policy.reload_if_changed()

    def update_policy(
        self,
        new_config: dict[str, Any],
        actor: str = "api",
        expected_version: int = 0,
    ) -> dict[str, Any]:
        """Alarm politikasını günceller."""
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
        """Alarm politikasını önceki bir versiyona geri döndürür."""
        return self._policy.rollback(target_version, actor)

    def get_policy_history(self) -> list[dict[str, Any]]:
        """Politika geçmişini döner."""
        return self._policy.get_history()

    def get_policy_audit_log(self, limit: int = 50) -> list[dict[str, Any]]:
        """Politika denetim logunu döner."""
        return self._policy.get_audit_log(limit)

    def batch_add_silences(
        self,
        rules: list[dict[str, Any]],
        created_by: str = "system",
    ) -> list[dict[str, Any]]:
        """Toplu susturma kuralları ekler."""
        return self._policy.batch_add_silences(rules, created_by, self._db)

    def batch_remove_silences(
        self,
        filters: list[dict[str, str]],
        actor: str = "api",
    ) -> dict[str, int]:
        """Toplu susturma kurallarını kaldırır."""
        return self._policy.batch_remove_silences(filters, actor, self._db)

    def compute_policy_diff(self, new_config: dict[str, Any]) -> Any:
        """Politika farkını hesaplar."""
        return self._policy.compute_diff(new_config)

    def set_policy_webhook(self, urls: list[str]) -> None:
        """Politika değişiklik webhook URL'lerini tanımlar."""
        self._policy.set_webhook_urls(urls)

    # ─── DB Kalıcılığı (DuckDB Uyumlu) ───────────────────────────────────────

    async def init_db(self) -> None:
        """Alarm durum tablosunu veritabanında (DuckDB) hazırlar."""
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
            if hasattr(self._db, "commit"):
                self._db.commit()
        except Exception as exc:
            logger.warning("alarm_veritabani_tablo_olusturma_hatasi", error=str(exc))

    async def persist_alert(self, alert: Alert) -> None:
        """Alarmı DuckDB'ye kaydeder (varsa günceller)."""
        if not self._db:
            return
        try:
            # Standart DuckDB upsert / replace
            self._db.execute("DELETE FROM alerts_state WHERE fingerprint = ?", (alert.fingerprint,))
            self._db.execute(
                "INSERT INTO alerts_state "
                "(fingerprint, alert_type, severity, status, message, details, "
                "timestamp, acknowledged_at, escalated_at, resolved_at, "
                "escalation_count, notification_status, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    alert.fingerprint,
                    str(alert.alert_type),
                    str(alert.severity),
                    str(alert.status),
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
        except Exception as exc:
            logger.warning("alarm_veritabani_kayit_hatasi", error=str(exc))

    async def load_from_db(self) -> None:
        """Sistem yeniden başladığında açık alarmları DuckDB'den kurtarır."""
        if not self._db:
            return
        try:
            rows = self._db.execute(
                "SELECT fingerprint, alert_type, severity, status, message, details, "
                "timestamp, acknowledged_at, escalated_at, resolved_at, "
                "escalation_count, notification_status FROM alerts_state "
                "WHERE status IN (?, ?, ?)",
                ("CREATED", "ACKNOWLEDGED", "ESCALATED"),
            ).fetchall()
            for row in rows:
                if isinstance(row, dict):
                    fp = row["fingerprint"]
                    at = row["alert_type"]
                    sev = row["severity"]
                    st = row["status"]
                    msg = row.get("message") or ""
                    dt = orjson.loads(row["details"]) if row.get("details") else {}
                    ts = row["timestamp"]
                    ack_at = row.get("acknowledged_at")
                    esc_at = row.get("escalated_at")
                    res_at = row.get("resolved_at")
                    esc_cnt = row.get("escalation_count", 0)
                    notif_st = row.get("notification_status", "pending")
                else:
                    fp, at, sev, st, msg, dt_str, ts, ack_at, esc_at, res_at, esc_cnt, notif_st = row
                    dt = orjson.loads(dt_str) if dt_str else {}

                alert = Alert(
                    alert_type=at,
                    severity=sev,
                    message=msg,
                    details=dt,
                    timestamp=ts,
                    fingerprint=fp,
                    status=st,
                    acknowledged_at=ack_at,
                    escalated_at=esc_at,
                    resolved_at=res_at,
                    escalation_count=esc_cnt,
                    notification_status=notif_st,
                )
                self._alerts.append(alert)
            logger.info("alarmlar_veritabanindan_kurtarildi", adet=len(rows))
        except Exception as exc:
            logger.warning("alarm_veritabanindan_yukleme_hatasi", error=str(exc))

    # ─── İç Metotlar ──────────────────────────────────────────────────────────

    def _add_alert(self, alert: Alert) -> None:
        """Alarm oluşturur, deduplication uygular, politikayı kontrol eder ve dağıtır."""
        with tracer.start_as_current_span("alerting.add_alert") as span:
            span.set_attribute("alert.type", alert.alert_type)
            span.set_attribute("alert.severity", alert.severity)
            span.set_attribute("alert.fingerprint", alert.fingerprint)

            if self._is_duplicate(alert):
                return

            if self._policy.is_silenced(alert.alert_type, alert.fingerprint):
                alert.notification_status = "silenced"
                logger.debug("alarm_susturuldu", fp=alert.fingerprint, type=alert.alert_type)
                return

            self._alerts.append(alert)
            self._dedup_cache[alert.fingerprint] = time.time()

            _alert_created_counter.add(
                1,
                {
                    "alert_type": alert.alert_type,
                    "severity": alert.severity,
                },
            )
            logger.warning(
                "yeni_alarm_olusturuldu",
                type=alert.alert_type,
                severity=alert.severity,
                fp=alert.fingerprint,
                mesaj=alert.message,
            )

            self._policy.reload_if_changed()

            try:
                loop = asyncio.get_running_loop()
                loop.create_task(self.persist_alert(alert))
                channels = self._policy.get_notification_channels(alert.severity)
                if channels and self._router.get_all_providers():
                    loop.create_task(self._notify_all(alert))
            except RuntimeError:
                logger.warning("alarm_bildirim_gonderilemedi_event_loop_yok")

    def _is_duplicate(self, alert: Alert) -> bool:
        """Aynı parmak izine sahip alarmın dedup_window_s süresi içinde gelip gelmediğini kontrol eder."""
        fp = alert.fingerprint
        return fp in self._dedup_cache and time.time() - self._dedup_cache[fp] < self._dedup_window_s

    async def _notify_all(self, alert: Alert) -> None:
        """Alarmı uygun tüm bildirim kanallarına eşzamanlı iletir."""
        with tracer.start_as_current_span("alerting.notify_all") as span:
            span.set_attribute("alert.fingerprint", alert.fingerprint)
            span.set_attribute("alert.severity", alert.severity)

            providers = self._router.get_providers_for_severity(alert.severity)
            for provider in providers:
                result = await self._send_with_retry(provider, alert)
                self._notification_log.append(result)
                if not result.success:
                    self._failed_notifications.append(result)
                    alert.notification_status = "failed"
                    _notification_failed_counter.add(1, {"provider": provider.name()})
                else:
                    alert.notification_status = "sent"
                    _notification_sent_counter.add(1, {"provider": provider.name()})

            await self.persist_alert(alert)

    async def _send_with_retry(self, provider: NotificationProvider, alert: Alert) -> NotificationResult:
        """Belirtilen sağlayıcıya exponential backoff + jitter ile yeniden dener."""
        result = NotificationResult(provider.name(), alert.fingerprint)
        for attempt in range(self._retry_config.max_retries):
            result.attempts += 1
            try:
                if await provider.send(alert):
                    result.success = True
                    return result
                result.last_error = "Sağlayıcı False yanıtı döndürdü"
            except Exception as exc:
                result.last_error = str(exc)

            if attempt < self._retry_config.max_retries - 1:
                base_delay = min(
                    self._retry_config.base_delay_s * (self._retry_config.backoff_factor**attempt),
                    self._retry_config.max_delay_s,
                )
                delay = base_delay + random.uniform(0, base_delay * 0.2)
                _notification_retry_counter.add(1, {"provider": provider.name()})
                await asyncio.sleep(delay)

        return result


# ─── Singleton ────────────────────────────────────────────────────────────────
alerting = AlertingSystem()

__all__ = [
    "Alert",
    "AlertSeverity",
    "AlertStatus",
    "AlertType",
    "AlertingSystem",
    "DiscordProvider",
    "EmailProvider",
    "LogProvider",
    "NotificationProvider",
    "NotificationResult",
    "NotificationRouter",
    "PagerDutyProvider",
    "RetryConfig",
    "SlackProvider",
    "WebhookProvider",
    "alerting",
]
