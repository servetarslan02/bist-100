#!/usr/bin/env python3
"""
Production Operations Testleri

Kapsam:
- Webhook notification
- Alert retry with backoff
- Alert deduplication
- Failed notification logging
- Email provider interface
- Grafana provisioning mock
- Extensible auth interface
- OAuth/OIDC stub
"""

import sys
import os
import asyncio
import json
import time

from services.core.alerting import (
    AlertingSystem, Alert, AlertType, AlertSeverity,
    WebhookProvider, EmailProvider, LogProvider,
    NotificationResult, RetryConfig,
)
from services.core.monitoring_security import (
    MonitoringAuth, AuthProvider, AuthResult, AuthManager,
    StaticTokenProvider, OAuthProvider,
)
from services.core.grafana_provisioning import (
    GrafanaProvisioner, GrafanaConfig, DatasourceConfig,
    DashboardVersion,
)


# =====================================================
# WEBHOOK TESTS
# =====================================================

async def test_webhook_payload_format():
    """Webhook payload doğru formatta olmalı."""
    issues = []

    alert = Alert(
        alert_type=AlertType.HEALTH_CHANGE,
        severity=AlertSeverity.CRITICAL,
        message="Test alert",
        details={"key": "value"},
    )

    payload = alert.to_webhook_payload()

    if "event" not in payload:
        issues.append("event eksik")
    if payload.get("alert_type") != "health_change":
        issues.append(f"alert_type: {payload.get('alert_type')}")
    if payload.get("severity") != "CRITICAL":
        issues.append(f"severity: {payload.get('severity')}")
    if "timestamp" not in payload:
        issues.append("timestamp eksik")
    if "fingerprint" not in payload:
        issues.append("fingerprint eksik")

    return "Webhook Payload Format", len(issues) == 0, issues


async def test_webhook_provider_interface():
    """Webhook provider interface doğru olmalı."""
    issues = []

    provider = WebhookProvider(url="https://hooks.example.com/test")

    if "webhook" not in provider.name():
        issues.append(f"name: {provider.name()}")

    # URL kaydedilmeli
    if provider.url != "https://hooks.example.com/test":
        issues.append(f"url: {provider.url}")

    return "Webhook Provider Interface", len(issues) == 0, issues


async def test_log_provider():
    """Log provider her zaman başarılı olmalı."""
    issues = []

    provider = LogProvider()
    alert = Alert(alert_type=AlertType.CASH_NEGATIVE, severity="CRITICAL", message="test")

    success = await provider.send(alert)
    if not success:
        issues.append("Log provider başarısız")

    if "log" not in provider.name():
        issues.append(f"name: {provider.name()}")

    return "Log Provider", len(issues) == 0, issues


# =====================================================
# RETRY TESTS
# =====================================================

async def test_retry_config():
    """Retry yapılandırması doğru olmalı."""
    issues = []

    config = RetryConfig()
    if config.max_retries != 3:
        issues.append(f"max_retries: {config.max_retries}")
    if config.base_delay_s != 1.0:
        issues.append(f"base_delay_s: {config.base_delay_s}")
    if config.backoff_factor != 2.0:
        issues.append(f"backoff_factor: {config.backoff_factor}")

    return "Retry Config", len(issues) == 0, issues


async def test_notification_result_tracking():
    """Notification result takibi doğru olmalı."""
    issues = []

    result = NotificationResult("test_provider", "abc123")
    result.attempts = 3
    result.success = False
    result.last_error = "timeout"

    d = result.to_dict()
    if d.get("provider") != "test_provider":
        issues.append(f"provider: {d.get('provider')}")
    if d.get("attempts") != 3:
        issues.append(f"attempts: {d.get('attempts')}")
    if d.get("last_error") != "timeout":
        issues.append(f"last_error: {d.get('last_error')}")

    return "Notification Result Tracking", len(issues) == 0, issues


async def test_retry_with_failing_provider():
    """Başarısız provider retry yapmalı."""
    issues = []

    class FailingProvider:
        def __init__(self):
            self.attempts = 0
        def name(self):
            return "failing"
        def min_severity(self):
            return "INFO"
        async def send(self, alert):
            self.attempts += 1
            return False

    alerting = AlertingSystem()
    provider = FailingProvider()
    alerting._router._providers.append(provider)

    alert = Alert(alert_type=AlertType.CASH_NEGATIVE, severity="CRITICAL", message="test")

    # Retry mekanizmasını doğrudan test et
    result = await alerting._send_with_retry(provider, alert)

    if result.attempts != 3:
        issues.append(f"attempts: {result.attempts} (beklenen: 3)")
    if result.success:
        issues.append("success should be False")
    if not result.last_error:
        issues.append("last_error boş")

    return "Retry With Failing Provider", len(issues) == 0, issues


async def test_retry_with_succeeding_provider():
    """Başarılı provider ilk denemede dönmeli."""
    issues = []

    class SucceedingProvider:
        def name(self):
            return "succeeding"
        def min_severity(self):
            return "INFO"
        async def send(self, alert):
            return True

    alerting = AlertingSystem()
    provider = SucceedingProvider()

    alert = Alert(alert_type=AlertType.CASH_NEGATIVE, severity="CRITICAL", message="test")
    result = await alerting._send_with_retry(provider, alert)

    if result.attempts != 1:
        issues.append(f"attempts: {result.attempts} (beklenen: 1)")
    if not result.success:
        issues.append("success should be True")

    return "Retry With Succeeding Provider", len(issues) == 0, issues


# =====================================================
# DEDUPLICATION TESTS
# =====================================================

async def test_alert_deduplication():
    """Aynı alert tekrar üretilmemeli (dedup window içinde)."""
    issues = []

    alerting = AlertingSystem(dedup_window_s=60)

    # İlk alert
    alerting.check_negative_cash(-100)
    count1 = len(alerting.get_active_alerts())

    # Aynı koşul — tekrar alert üretilmemeli
    alerting.check_negative_cash(-100)
    count2 = len(alerting.get_active_alerts())

    if count2 != count1:
        issues.append(f"Dedup başarısız: {count1} → {count2}")

    # Farklı koşul — yeni alert üretilmeli
    alerting.check_negative_cash(-200)
    count3 = len(alerting.get_active_alerts())

    if count3 <= count2:
        issues.append(f"Farklı alert üretilmedi: {count2} → {count3}")

    return "Alert Deduplication", len(issues) == 0, issues


async def test_dedup_window_expiry():
    """Dedup window dolduğunda aynı alert tekrar üretilmeli."""
    issues = []

    alerting = AlertingSystem(dedup_window_s=0.1)  # 100ms window

    alerting.check_negative_cash(-100)
    count1 = len(alerting.get_active_alerts())

    # Window dolana kadar bekle
    await asyncio.sleep(0.15)

    alerting.check_negative_cash(-100)
    count2 = len(alerting.get_active_alerts())

    if count2 <= count1:
        issues.append(f"Window doldu ama alert üretilmedi: {count1} → {count2}")

    return "Dedup Window Expiry", len(issues) == 0, issues


async def test_fingerprint_stability():
    """Aynı koşullar aynı fingerprint üretmeli."""
    issues = []

    a1 = Alert(alert_type=AlertType.CASH_NEGATIVE, severity="CRITICAL",
               message="test", details={"cash": -100})
    a2 = Alert(alert_type=AlertType.CASH_NEGATIVE, severity="CRITICAL",
               message="test2", details={"cash": -100})

    if a1.fingerprint != a2.fingerprint:
        issues.append(f"Fingerprint farklı: {a1.fingerprint} != {a2.fingerprint}")

    a3 = Alert(alert_type=AlertType.CASH_NEGATIVE, severity="CRITICAL",
               message="test", details={"cash": -200})

    if a1.fingerprint == a3.fingerprint:
        issues.append("Farklı detaylar aynı fingerprint üretti")

    return "Fingerprint Stability", len(issues) == 0, issues


# =====================================================
# FAILED NOTIFICATION TESTS
# =====================================================

async def test_failed_notification_logging():
    """Başarısız bildirimler kaydedilmeli."""
    issues = []

    class FailProvider:
        def name(self): return "fail"
        def min_severity(self): return "INFO"
        async def send(self, alert): return False

    alerting = AlertingSystem()
    alerting._router._providers.append(FailProvider())

    alert = Alert(alert_type=AlertType.CASH_NEGATIVE, severity="CRITICAL", message="test")
    await alerting._notify_all(alert)

    failed = alerting.get_failed_notifications()
    if len(failed) == 0:
        issues.append("Başarısız bildirim kaydedilmedi")

    return "Failed Notification Logging", len(issues) == 0, issues


async def test_notification_log():
    """Bildirim log'u tutulmalı."""
    issues = []

    class OkProvider:
        def name(self): return "ok"
        def min_severity(self): return "INFO"
        async def send(self, alert): return True

    alerting = AlertingSystem()
    alerting._router._providers.append(OkProvider())

    alert = Alert(alert_type=AlertType.CASH_NEGATIVE, severity="CRITICAL", message="test")
    await alerting._notify_all(alert)

    log = alerting.get_notification_log()
    if len(log) == 0:
        issues.append("Notification log boş")

    return "Notification Log", len(issues) == 0, issues


# =====================================================
# GRAFANA PROVISIONING TESTS
# =====================================================

async def test_datasource_config():
    """Datasource config doğru payload üretmeli."""
    issues = []

    ds = DatasourceConfig(
        name="Prometheus",
        type="prometheus",
        url="http://localhost:9090",
        is_default=True,
    )

    payload = ds.to_grafana_payload()

    if payload.get("name") != "Prometheus":
        issues.append(f"name: {payload.get('name')}")
    if payload.get("type") != "prometheus":
        issues.append(f"type: {payload.get('type')}")
    if payload.get("isDefault") is not True:
        issues.append(f"isDefault: {payload.get('isDefault')}")

    return "Datasource Config", len(issues) == 0, issues


async def test_grafana_provisioner_status():
    """Provisioner status doğru bilgi vermeli."""
    issues = []

    provisioner = GrafanaProvisioner(GrafanaConfig(url="http://test:3000"))

    status = provisioner.get_provisioning_status()

    if status.get("grafana_url") != "http://test:3000":
        issues.append(f"url: {status.get('grafana_url')}")
    if status.get("dashboards_provisioned") != 0:
        issues.append(f"dashboards: {status.get('dashboards_provisioned')}")

    return "Grafana Provisioner Status", len(issues) == 0, issues


async def test_dashboard_version_tracking():
    """Dashboard versiyon takibi doğru olmalı."""
    issues = []

    provisioner = GrafanaProvisioner()

    # Manuel versiyon ekleme
    provisioner._versions.append(DashboardVersion(
        uid="test123", title="Test Dashboard", version=1,
        provisioned_at="2026-01-01T00:00:00Z", file_path="/test.json",
    ))
    provisioner._provisioned_dashboards["test123"] = 1

    history = provisioner.get_version_history()
    if len(history) != 1:
        issues.append(f"history: {len(history)}")

    status = provisioner.get_provisioning_status()
    if status.get("dashboard_versions") != 1:
        issues.append(f"versions: {status.get('dashboard_versions')}")

    return "Dashboard Version Tracking", len(issues) == 0, issues


async def test_dashboard_json_valid():
    """Dashboard JSON dosyası geçerli olmalı."""
    issues = []

    dashboard_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "monitoring", "grafana_dashboard.json"
    )

    if not os.path.exists(dashboard_path):
        issues.append("Dashboard dosyası bulunamadı")
        return "Dashboard JSON Valid", False, issues

    with open(dashboard_path) as f:
        data = json.load(f)

    dash = data.get("dashboard", {})
    if not dash.get("panels"):
        issues.append("panels eksik")

    # Panel'lerin geçerli type'ları olmalı
    valid_types = {"timeseries", "stat", "gauge", "bargauge", "table", "text"}
    for panel in dash.get("panels", []):
        ptype = panel.get("type", "")
        if ptype and ptype not in valid_types:
            issues.append(f"Geçersiz panel type: {ptype}")

    return "Dashboard JSON Valid", len(issues) == 0, issues


# =====================================================
# AUTH INTERFACE TESTS
# =====================================================

async def test_static_token_provider():
    """Static token provider doğru çalışmalı."""
    issues = []

    provider = StaticTokenProvider(tokens={
        "admin_token": ["admin", "viewer"],
        "metrics_token": ["viewer"],
    })

    # Doğru token
    result = await provider.verify("admin_token")
    if not result.authenticated:
        issues.append("Admin token reddedildi")
    if "admin" not in result.roles:
        issues.append("admin role eksik")

    # Yanlış token
    result = await provider.verify("wrong")
    if result.authenticated:
        issues.append("Yanlış token kabul edildi")

    # Boş token
    result = await provider.verify("")
    if result.authenticated:
        issues.append("Boş token kabul edildi")

    return "Static Token Provider", len(issues) == 0, issues


async def test_oauth_provider_stub():
    """OAuth provider stub çalışmalı."""
    issues = []

    provider = OAuthProvider(issuer="https://auth.example.com")

    result = await provider.verify("some_token")
    if result.authenticated:
        issues.append("OAuth stub token kabul etti (mamalı)")
    if not result.error:
        issues.append("error mesajı yok")

    return "OAuth Provider Stub", len(issues) == 0, issues


async def test_auth_manager_multi_provider():
    """Auth manager çoklu provider denemeli."""
    issues = []

    manager = AuthManager()
    manager.add_provider(StaticTokenProvider(tokens={"token1": ["viewer"]}))
    manager.add_provider(OAuthProvider())

    # İlk provider.authenticate etmeli
    result = await manager.verify("token1")
    if not result.authenticated:
        issues.append("Static token authenticate edilemedi")

    # Geçersiz token — tüm provider'lar fail
    result = await manager.verify("invalid")
    if result.authenticated:
        issues.append("Geçersiz token kabul edildi")

    providers = manager.get_providers()
    if len(providers) != 2:
        issues.append(f"providers: {len(providers)}")

    return "Auth Manager Multi Provider", len(issues) == 0, issues


async def test_auth_result_roles():
    """AuthResult role kontrolü doğru olmalı."""
    issues = []

    result = AuthResult(authenticated=True, roles=["admin", "viewer"])

    if not result.has_role("admin"):
        issues.append("admin role bulunamadı")
    if not result.has_role("viewer"):
        issues.append("viewer role bulunamadı")
    if result.has_role("superuser"):
        issues.append("superuser role bulundu (olmamalı)")

    failed = AuthResult(authenticated=False, error="invalid")
    if failed.has_role("admin"):
        issues.append("Failed result admin role bulundu")

    return "Auth Result Roles", len(issues) == 0, issues


# =====================================================
# RUN
# =====================================================

async def run_all():
    print("=" * 60)
    print("PRODUCTION OPERATIONS TESTLERİ")
    print("=" * 60)

    tests = [
        # Webhook
        test_webhook_payload_format,
        test_webhook_provider_interface,
        test_log_provider,
        # Retry
        test_retry_config,
        test_notification_result_tracking,
        test_retry_with_failing_provider,
        test_retry_with_succeeding_provider,
        # Deduplication
        test_alert_deduplication,
        test_dedup_window_expiry,
        test_fingerprint_stability,
        # Failed notifications
        test_failed_notification_logging,
        test_notification_log,
        # Grafana
        test_datasource_config,
        test_grafana_provisioner_status,
        test_dashboard_version_tracking,
        test_dashboard_json_valid,
        # Auth
        test_static_token_provider,
        test_oauth_provider_stub,
        test_auth_manager_multi_provider,
        test_auth_result_roles,
    ]

    passed = 0
    failed = 0
    all_issues = []

    for test_func in tests:
        try:
            name, ok, issues = await test_func()
        except Exception as e:
            name = test_func.__name__
            ok = False
            issues = [f"Exception: {e}"]

        icon = "✅" if ok else "❌"
        print(f"\n{icon} {name}")
        if ok:
            passed += 1
            print("   PASSED")
        else:
            failed += 1
            for i in issues:
                print(f"   ❌ {i}")
                all_issues.append(f"{name}: {i}")

    print(f"\n{'=' * 60}")
    print(f"SONUÇ: {passed}/{passed + failed} geçti")
    if all_issues:
        print("\nTÜM HATALAR:")
        for i, issue in enumerate(all_issues, 1):
            print(f"  {i}. {issue}")
    print("=" * 60)
    return failed == 0


def main():
    ok = asyncio.run(run_all())
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
