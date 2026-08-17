# core/alerting

**Dosya:** `services/core/alerting.py`
**Satır:** 863

## Açıklama

ALPHA BIST — Alerting System v3.0

Otonom sistem yönetimi için production-grade alerting.

Özellikler:
- Alert lifecycle: CREATED → ACKNOWLEDGED → ESCALATED → RESOLVED
- Escalation: WARNING belirli süre devam ederse → CRITICAL
- DB persistence (restart sonrası alert recovery)
- Notification routing: WARNING→log/webhook, CRITICAL→tüm kanallar
- Webhook, Slack, Discord, PagerDuty providers
- Deduplication, retry, failed notification logging

## Sınıflar (15)

- `AlertSeverity`
- `AlertStatus`
- `AlertType`
- `Alert`
- `NotificationProvider`
- `LogProvider`
- `WebhookProvider`
- `SlackProvider`
- `DiscordProvider`
- `PagerDutyProvider`
- `EmailProvider`
- `NotificationRouter`
- `RetryConfig`
- `NotificationResult`
- `AlertingSystem`

## Fonksiyonlar (70)

- `__post_init__()`
- `_compute_fingerprint()`
- `acknowledge()`
- `escalate()`
- `resolve()`
- `is_active()`
- `to_dict()`
- `to_webhook_payload()`
- `to_slack_payload()`
- `to_discord_payload()`
- `to_pagerduty_payload()`
- `timestamp_iso_str()`
- `name()`
- `min_severity()`
- `name()`
- `min_severity()`
- `name()`
- `min_severity()`
- `name()`
- `min_severity()`
- `name()`
- `min_severity()`
- `name()`
- `min_severity()`
- `name()`
- `min_severity()`
- `_send_smtp()`
- `__init__()`
- `add_provider()`
- `get_providers_for_severity()`
- ... ve 40 daha

