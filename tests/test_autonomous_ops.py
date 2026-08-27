#!/usr/bin/env python3
"""
Autonomous Operations Testleri

Kapsam:
- Alert lifecycle (CREATED→ACKNOWLEDGED→ESCALATED→RESOLVED)
- Escalation timeout
- DB persistence & restart recovery
- Notification routing (WARNING→webhook, CRITICAL→all)
- Slack/Discord/PagerDuty payload format
- JWT validation
- Role-based authorization (admin/operator/viewer)
"""

import asyncio
import sys
import time

from services.core.alerting import (
    Alert,
    AlertingSystem,
    AlertStatus,
    AlertType,
    LogProvider,
    NotificationRouter,
    SlackProvider,
    WebhookProvider,
)
from services.core.monitoring_security import (
    ROLE_PERMISSIONS,
    AuthManager,
    JWTProvider,
    OAuthProvider,
    StaticTokenProvider,
)

# =====================================================
# ALERT LIFECYCLE TESTS
# =====================================================


async def test_alert_lifecycle_states():
    """Alert lifecycle doğru geçişleri yapmalı."""
    issues = []

    alert = Alert(alert_type=AlertType.CASH_NEGATIVE, severity="CRITICAL", message="test")

    # CREATED
    if alert.status != AlertStatus.CREATED:
        issues.append(f"Başlangıç status: {alert.status}")
    if not alert.is_active:
        issues.append("CREATED active olmalı")

    # ACKNOWLEDGED
    alert.acknowledge()
    if alert.status != AlertStatus.ACKNOWLEDGED:
        issues.append(f"Acknowledge sonrası: {alert.status}")
    if not alert.is_active:
        issues.append("ACKNOWLEDGED active olmalı")

    # ESCALATED
    alert2 = Alert(alert_type=AlertType.HEALTH_CHANGE, severity="WARNING", message="test")
    alert2.escalate("CRITICAL")
    if alert2.status != AlertStatus.ESCALATED:
        issues.append(f"Escalate sonrası: {alert2.status}")
    if alert2.severity != "CRITICAL":
        issues.append(f"Escalate severity: {alert2.severity}")
    if alert2.escalation_count != 1:
        issues.append(f"Escalation count: {alert2.escalation_count}")

    # RESOLVED
    alert2.resolve()
    if alert2.status != AlertStatus.RESOLVED:
        issues.append(f"Resolve sonrası: {alert2.status}")
    if alert2.is_active:
        issues.append("RESOLVED active olmamalı")

    assert len(issues) == 0, f"Alert Lifecycle States: {issues}"


async def test_alert_serialization():
    """Alert serialization doğru olmalı."""
    issues = []

    alert = Alert(alert_type=AlertType.INVARIANT_FAILURE, severity="CRITICAL", message="test", details={"cash": -100})

    d = alert.to_dict()
    if d.get("status") != "CREATED":
        issues.append(f"dict status: {d.get('status')}")
    if "fingerprint" not in d:
        issues.append("fingerprint dict'te yok")

    # Slack payload
    slack = alert.to_slack_payload()
    if "attachments" not in slack:
        issues.append("slack attachments eksik")

    # Discord payload
    discord = alert.to_discord_payload()
    if "embeds" not in discord:
        issues.append("discord embeds eksik")

    # PagerDuty payload
    pd = alert.to_pagerduty_payload("test_key")
    if pd.get("routing_key") != "test_key":
        issues.append(f"pd routing_key: {pd.get('routing_key')}")
    if pd.get("event_action") != "trigger":
        issues.append(f"pd event_action: {pd.get('event_action')}")

    assert len(issues) == 0, f"Alert Serialization: {issues}"


async def test_escalation_timeout():
    """Escalation timeout doğru çalışmalı."""
    issues = []

    from services.core.alert_policy import AlertPolicy

    policy = AlertPolicy()
    policy.escalation_timeouts["health_change"] = 0  # Anında escalation

    alerting = AlertingSystem(policy=policy)
    alerting._last_health_status = "HEALTHY"
    alerting.check_health({"status": "DEGRADED", "issues": ["test"]})

    active = alerting.get_active_alerts()
    if not active:
        issues.append("Alert yok")
        raise AssertionError(f"Escalation Timeout: {issues}")

    # Manuel olarak timestamp'i eski yap
    for a in alerting._alerts:
        a.timestamp = time.time() - 10

    alerting._check_escalations()

    active = alerting.get_active_alerts()
    if active:
        escalated = active[0]
        if escalated["status"] != "ESCALATED":
            issues.append(f"Escalation sonrası status: {escalated['status']}")
        if escalated["severity"] != "CRITICAL":
            issues.append(f"Escalation sonrası severity: {escalated['severity']}")

    assert len(issues) == 0, f"Escalation Timeout: {issues}"


async def test_acknowledge_stops_escalation():
    """Acknowledged alert escalate edilmemeli."""
    issues = []

    from services.core.alert_policy import AlertPolicy

    policy = AlertPolicy()
    policy.escalation_timeouts["health_change"] = 0

    alerting = AlertingSystem(policy=policy)
    alerting._last_health_status = "HEALTHY"
    alerting.check_health({"status": "DEGRADED", "issues": ["test"]})

    active = alerting.get_active_alerts()
    if not active:
        issues.append("Alert yok")
        raise AssertionError(f"Acknowledge Stops Escalation: {issues}")

    fp = active[0]["fingerprint"]

    # Acknowledge et
    alerting.acknowledge_alert(fp)

    # Timestamp eski yap
    for a in alerting._alerts:
        a.timestamp = time.time() - 10

    alerting._check_escalations()

    active = alerting.get_active_alerts()
    if active and active[0]["status"] == "ESCALATED":
        issues.append("Acknowledged alert escalate edildi")

    assert len(issues) == 0, f"Acknowledge Stops Escalation: {issues}"


# =====================================================
# DB PERSISTENCE TESTS
# =====================================================


async def test_alert_db_persistence():
    """Alert DB'ye persist edilmeli."""
    import duckdb

    issues = []

    db = duckdb.connect(":memory:")

    alerting = AlertingSystem(db=db, dialect="sqlite")
    await alerting.init_db()

    alerting.check_negative_cash(-100)

    # Direkt persist et (async ensure_future beklemez)
    for a in alerting._alerts:
        await alerting.persist_alert(a)

    # DB'den oku
    rows = db.execute("SELECT * FROM alerts_state").fetchall()
    if len(rows) == 0:
        issues.append("Alert DB'ye kaydedilmedi")
    elif rows[0]["status"] != "CREATED":
        issues.append(f"DB status: {rows[0]['status']}")

    assert len(issues) == 0, f"Alert DB Persistence: {issues}"


async def test_alert_restart_recovery():
    """Restart sonrası alert'ler geri yüklenmeli."""
    import duckdb

    issues = []

    db = duckdb.connect(":memory:")

    # İlk instance — alert oluştur ve persist et
    alerting1 = AlertingSystem(db=db, dialect="sqlite")
    await alerting1.init_db()
    alerting1.check_negative_cash(-100)
    for a in alerting1._alerts:
        await alerting1.persist_alert(a)

    # İkinci instance — DB'den yükle
    alerting2 = AlertingSystem(db=db, dialect="sqlite")
    await alerting2.init_db()
    await alerting2.load_from_db()

    active = alerting2.get_active_alerts()
    if len(active) < 1:
        issues.append(f"Restart sonrası alert yüklenemedi: {len(active)}")

    assert len(issues) == 0, f"Alert Restart Recovery: {issues}"


# =====================================================
# NOTIFICATION ROUTING TESTS
# =====================================================


async def test_notification_routing():
    """Notification routing severity'ye göre doğru provider seçmeli."""
    issues = []

    router = NotificationRouter()
    router.add_provider(LogProvider())  # min=INFO
    router.add_provider(WebhookProvider(url="https://test"))  # min=WARNING
    router.add_provider(SlackProvider(webhook_url="https://test"))  # min=CRITICAL

    # INFO → sadece log
    info_providers = router.get_providers_for_severity("INFO")
    if len(info_providers) != 1:
        issues.append(f"INFO providers: {len(info_providers)} (beklenen: 1)")

    # WARNING → log + webhook
    warn_providers = router.get_providers_for_severity("WARNING")
    if len(warn_providers) != 2:
        issues.append(f"WARNING providers: {len(warn_providers)} (beklenen: 2)")

    # CRITICAL → tümü
    crit_providers = router.get_providers_for_severity("CRITICAL")
    if len(crit_providers) != 3:
        issues.append(f"CRITICAL providers: {len(crit_providers)} (beklenen: 3)")

    assert len(issues) == 0, f"Notification Routing: {issues}"


async def test_slack_payload_format():
    """Slack payload doğru formatta olmalı."""
    issues = []

    alert = Alert(alert_type=AlertType.INVARIANT_FAILURE, severity="CRITICAL", message="test")
    payload = alert.to_slack_payload()

    if "attachments" not in payload:
        issues.append("attachments eksik")
    else:
        att = payload["attachments"][0]
        if att.get("color") != "#ff0000":
            issues.append(f"color: {att.get('color')}")
        if "title" not in att:
            issues.append("title eksik")

    assert len(issues) == 0, f"Slack Payload Format: {issues}"


async def test_discord_payload_format():
    """Discord payload doğru formatta olmalı."""
    issues = []

    alert = Alert(alert_type=AlertType.LOCK_DEADLOCK, severity="WARNING", message="test")
    payload = alert.to_discord_payload()

    if "embeds" not in payload:
        issues.append("embeds eksik")
    else:
        embed = payload["embeds"][0]
        if embed.get("color") != 0xFF9900:
            issues.append(f"color: {embed.get('color')}")

    assert len(issues) == 0, f"Discord Payload Format: {issues}"


async def test_pagerduty_payload_format():
    """PagerDuty payload doğru formatta olmalı."""
    issues = []

    alert = Alert(alert_type=AlertType.CASH_NEGATIVE, severity="CRITICAL", message="test")
    payload = alert.to_pagerduty_payload("routing_key_123")

    if payload.get("routing_key") != "routing_key_123":
        issues.append(f"routing_key: {payload.get('routing_key')}")
    if payload.get("event_action") != "trigger":
        issues.append(f"event_action: {payload.get('event_action')}")
    if "dedup_key" not in payload:
        issues.append("dedup_key eksik")

    assert len(issues) == 0, f"PagerDuty Payload Format: {issues}"


async def test_log_provider_notification():
    """Log provider her zaman başarılı olmalı."""
    issues = []

    provider = LogProvider()
    alert = Alert(alert_type=AlertType.CASH_NEGATIVE, severity="CRITICAL", message="test")

    success = await provider.send(alert)
    if not success:
        issues.append("Log provider başarısız")

    if provider.min_severity() != "INFO":
        issues.append(f"min_severity: {provider.min_severity()}")

    assert len(issues) == 0, f"Log Provider Notification: {issues}"


# =====================================================
# JWT TESTS
# =====================================================


async def test_jwt_validation():
    """JWT token doğrulama doğru çalışmalı."""
    issues = []

    try:
        import jwt as pyjwt
    except ImportError:
        try:
            from jose import jwt as pyjwt
        except ImportError:
            raise AssertionError("JWT Validation: PyJWT not installed") from None

    secret = "test_secret_key_12345"
    provider = JWTProvider(secret=secret, algorithm="HS256")

    # Geçerli token oluştur
    payload = {"sub": "user1", "roles": ["admin"], "exp": int(time.time()) + 3600}
    token = pyjwt.encode(payload, secret, algorithm="HS256")

    result = await provider.verify(token)
    if not result.authenticated:
        issues.append(f"Geçerli token reddedildi: {result.error}")
    if result.user_id != "user1":
        issues.append(f"user_id: {result.user_id}")
    if "admin" not in result.roles:
        issues.append(f"roles: {result.roles}")

    # Expired token
    expired_payload = {"sub": "user1", "roles": ["viewer"], "exp": int(time.time()) - 100}
    expired_token = pyjwt.encode(expired_payload, secret, algorithm="HS256")

    result = await provider.verify(expired_token)
    if result.authenticated:
        issues.append("Expired token kabul edildi")
    if "expired" not in result.error.lower():
        issues.append(f"Expired error: {result.error}")

    # Yanlış secret
    wrong_token = pyjwt.encode(
        {"sub": "x", "roles": [], "exp": int(time.time()) + 100}, "wrong_secret", algorithm="HS256"
    )
    result = await provider.verify(wrong_token)
    if result.authenticated:
        issues.append("Yanlış secret ile token kabul edildi")

    # Boş token
    result = await provider.verify("")
    if result.authenticated:
        issues.append("Boş token kabul edildi")

    assert len(issues) == 0, f"JWT Validation: {issues}"


async def test_jwt_role_extraction():
    """JWT'den roller doğru çıkarılmalı."""
    issues = []

    try:
        import jwt as pyjwt
    except ImportError:
        try:
            from jose import jwt as pyjwt
        except ImportError:
            raise AssertionError("JWT Role Extraction: PyJWT not installed") from None

    secret = "test_secret"

    # Array roles
    token = pyjwt.encode(
        {"sub": "u1", "roles": ["admin", "viewer"], "exp": int(time.time()) + 100}, secret, algorithm="HS256"
    )
    provider = JWTProvider(secret=secret)
    result = await provider.verify(token)
    if set(result.roles) != {"admin", "viewer"}:
        issues.append(f"Array roles: {result.roles}")

    # String role (tekil)
    token2 = pyjwt.encode({"sub": "u2", "roles": "operator", "exp": int(time.time()) + 100}, secret, algorithm="HS256")
    result2 = await provider.verify(token2)
    if result2.roles != ["operator"]:
        issues.append(f"String role: {result2.roles}")

    assert len(issues) == 0, f"JWT Role Extraction: {issues}"


# =====================================================
# RBAC TESTS
# =====================================================


async def test_role_permissions():
    """Role permission mapping doğru olmalı."""
    issues = []

    if "admin" not in ROLE_PERMISSIONS:
        issues.append("admin role eksik")
    elif "admin" not in ROLE_PERMISSIONS["admin"]:
        issues.append("admin/admin permission eksik")

    if "viewer" not in ROLE_PERMISSIONS:
        issues.append("viewer role eksik")
    elif "write" in ROLE_PERMISSIONS.get("viewer", []):
        issues.append("viewer write permission almamalı")

    assert len(issues) == 0, f"Role Permissions: {issues}"


async def test_rbac_admin_access():
    """Admin tüm izinlere sahip olmalı."""
    issues = []

    manager = AuthManager()
    manager.add_provider(StaticTokenProvider(tokens={"admin_tok": ["admin"]}))

    for perm in ["read", "write", "admin", "metrics", "alerts", "portfolio"]:
        result = await manager.verify_permission("admin_tok", perm)
        if not result.authenticated:
            issues.append(f"Admin {perm} reddedildi")

    assert len(issues) == 0, f"RBAC Admin Access: {issues}"


async def test_rbac_viewer_restrictions():
    """Viewer sadece read ve metrics iznine sahip olmalı."""
    issues = []

    manager = AuthManager()
    manager.add_provider(StaticTokenProvider(tokens={"viewer_tok": ["viewer"]}))

    # İzinli
    for perm in ["read", "metrics"]:
        result = await manager.verify_permission("viewer_tok", perm)
        if not result.authenticated:
            issues.append(f"Viewer {perm} reddedildi")

    # İzsiz
    for perm in ["write", "admin", "alerts", "portfolio"]:
        result = await manager.verify_permission("viewer_tok", perm)
        if result.authenticated and not result.error:
            issues.append(f"Viewer {perm} izni var (olmamalı)")

    assert len(issues) == 0, f"RBAC Viewer Restrictions: {issues}"


async def test_rbac_operator_permissions():
    """Operator read, write, metrics, alerts, portfolio iznine sahip olmalı."""
    issues = []

    manager = AuthManager()
    manager.add_provider(StaticTokenProvider(tokens={"op_tok": ["operator"]}))

    for perm in ["read", "write", "metrics", "alerts", "portfolio"]:
        result = await manager.verify_permission("op_tok", perm)
        if not result.authenticated:
            issues.append(f"Operator {perm} reddedildi")

    # Admin izni yok
    result = await manager.verify_permission("op_tok", "admin")
    if result.authenticated and not result.error:
        issues.append("Operator admin izni var (olmamalı)")

    assert len(issues) == 0, f"RBAC Operator Permissions: {issues}"


async def test_oauth_provider_without_secret():
    """Secret yoksa OAuthProvider authenticate etmemeli."""
    issues = []

    provider = OAuthProvider(issuer="https://auth.example.com")
    result = await provider.verify("some_token")
    if result.authenticated:
        issues.append("Secret yokken token kabul edildi")

    assert len(issues) == 0, f"OAuth Without Secret: {issues}"


async def test_auth_manager_multi_provider():
    """Auth manager tüm provider'ları denemeli."""
    issues = []

    manager = AuthManager()
    manager.add_provider(StaticTokenProvider(tokens={"tok1": ["viewer"]}))

    result = await manager.verify("tok1")
    if not result.authenticated:
        issues.append("Static token reddedildi")

    result = await manager.verify("invalid")
    if result.authenticated:
        issues.append("Geçersiz token kabul edildi")

    providers = manager.get_providers()
    if len(providers) < 1:
        issues.append("Provider yok")

    assert len(issues) == 0, f"Auth Manager Multi Provider: {issues}"


# =====================================================
# RUN
# =====================================================


async def run_all():
    print("=" * 60)
    print("AUTONOMOUS OPERATIONS TESTLERİ")
    print("=" * 60)

    tests = [
        # Lifecycle
        test_alert_lifecycle_states,
        test_alert_serialization,
        test_escalation_timeout,
        test_acknowledge_stops_escalation,
        # DB
        test_alert_db_persistence,
        test_alert_restart_recovery,
        # Notification routing
        test_notification_routing,
        test_slack_payload_format,
        test_discord_payload_format,
        test_pagerduty_payload_format,
        test_log_provider_notification,
        # JWT
        test_jwt_validation,
        test_jwt_role_extraction,
        # RBAC
        test_role_permissions,
        test_rbac_admin_access,
        test_rbac_viewer_restrictions,
        test_rbac_operator_permissions,
        test_oauth_provider_without_secret,
        test_auth_manager_multi_provider,
    ]

    passed = 0
    failed = 0
    all_issues = []

    for test_func in tests:
        try:
            await test_func()
            name = test_func.__name__
            passed += 1
            print(f"\n✅ {name}")
            print("   PASSED")
        except AssertionError as e:
            name = test_func.__name__
            failed += 1
            issues = [str(e)]
            print(f"\n❌ {name}")
            for i in issues:
                print(f"   ❌ {i}")
                all_issues.append(f"{name}: {i}")
        except Exception as e:
            name = test_func.__name__
            failed += 1
            issues = [f"Exception: {e}"]
            print(f"\n❌ {name}")
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
