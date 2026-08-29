#!/usr/bin/env python3
import structlog
logger = structlog.get_logger(__name__)
from typing import Any
"""
Monitoring Operations Testleri

Kapsam:
- Authentication (metrics, admin endpoints)
- Prometheus histogram bucket desteği
- Alerting system triggers
- Dashboard JSON doğrulama
- Rate limiting
"""

import asyncio
import os
import sys
import time

import orjson

from services.core.alerting import (
    AlertingSystem,
)
from services.core.monitoring_security import (
    AuthConfig,
    MonitoringAuth,
    extract_api_key,
    extract_bearer_token,
)
from services.core.observability import DEFAULT_BUCKETS, PrometheusMetrics

# =====================================================
# AUTHENTICATION TESTS
# =====================================================


async def test_metrics_token_auth() -> Any:
    """Metrics endpoint token doğrulama."""
    auth = MonitoringAuth(
        AuthConfig(
            metrics_token="test_metrics_token",
            admin_token="test_admin_token",
        )
    )
    issues = []

    # Doğru token
    if not auth.verify_metrics_token("test_metrics_token"):
        issues.append("Doğru metrics token reddedildi")

    # Yanlış token
    if auth.verify_metrics_token("wrong_token"):
        issues.append("Yanlış metrics token kabul edildi")

    # Boş token
    if auth.verify_metrics_token(""):
        issues.append("Boş token kabul edildi")

    return "Metrics Token Auth", len(issues) == 0, issues


async def test_admin_token_auth() -> Any:
    """Admin endpoint token doğrulama."""
    auth = MonitoringAuth(
        AuthConfig(
            metrics_token="test_metrics",
            admin_token="test_admin",
        )
    )
    issues = []

    if not auth.verify_admin_token("test_admin"):
        issues.append("Doğru admin token reddedildi")

    if auth.verify_admin_token("wrong"):
        issues.append("Yanlış admin token kabul edildi")

    # Metrics token admin için geçerli olmamalı
    if auth.verify_admin_token("test_metrics"):
        issues.append("Metrics token admin erişimi kazandı")

    return "Admin Token Auth", len(issues) == 0, issues


async def test_bearer_token_extraction() -> Any:
    """Bearer token extraction."""
    issues = []

    # Doğru format
    token = extract_bearer_token("Bearer abc123")
    if token != "abc123":
        issues.append(f"Bearer extraction: {token}")

    # Yanlış format
    token = extract_bearer_token("Basic abc123")
    if token is not None:
        issues.append(f"Basic accepted: {token}")

    # Boş header
    token = extract_bearer_token(None)
    if token is not None:
        issues.append(f"None returned: {token}")

    # Boş authorization
    token = extract_bearer_token("")
    if token is not None:
        issues.append(f"Empty returned: {token}")

    return "Bearer Token Extraction", len(issues) == 0, issues


async def test_api_key_extraction() -> Any:
    """API key extraction."""
    issues = []

    key = extract_api_key({"x-api-key": "test123"})
    if key != "test123":
        issues.append(f"x-api-key: {key}")

    key = extract_api_key({"X-API-Key": "test456"})
    if key != "test456":
        issues.append(f"X-API-Key: {key}")

    key = extract_api_key({})
    if key is not None:
        issues.append(f"Empty headers: {key}")

    return "API Key Extraction", len(issues) == 0, issues


async def test_rate_limiting() -> Any:
    """Rate limiting çalışmalı."""
    auth = MonitoringAuth(AuthConfig(rate_limit_per_minute=5))
    issues = []

    client_ip = "192.168.1.1"

    # 5 istek başarılı olmalı
    for i in range(5):
        if not auth.check_rate_limit(client_ip):
            issues.append(f"İstek {i + 1} reddedildi (limit: 5)")

    # 6. istek reddedilmeli
    if auth.check_rate_limit(client_ip):
        issues.append("6. istek kabul edildi (limit aşıldı)")

    return "Rate Limiting", len(issues) == 0, issues


async def test_auth_disabled() -> Any:
    """Auth devre dışıyken tüm token'lar geçerli."""
    auth = MonitoringAuth(AuthConfig(enabled=False))
    issues = []

    if not auth.verify_metrics_token("anything"):
        issues.append("Disabled auth metrics token reddetti")
    if not auth.verify_admin_token("anything"):
        issues.append("Disabled auth admin token reddetti")

    return "Auth Disabled", len(issues) == 0, issues


async def test_failed_attempt_tracking() -> Any:
    """Başarısız girişim takibi."""
    auth = MonitoringAuth()
    issues = []

    client_ip = "10.0.0.1"
    for _ in range(3):
        auth.record_failed_attempt(client_ip)

    status = auth.get_auth_status()
    if status.get("failed_attempt_ips", 0) < 1:
        issues.append("Failed attempt IP kaydedilmedi")

    return "Failed Attempt Tracking", len(issues) == 0, issues


# =====================================================
# PROMETHEUS HISTOGRAM TESTS
# =====================================================


async def test_histogram_buckets() -> Any:
    """Histogram bucket desteği doğru çalışmalı."""
    metrics = PrometheusMetrics()
    issues = []

    # Farklı değerler observe et
    for val in [0.0005, 0.003, 0.008, 0.03, 0.07, 0.3, 0.8, 2.0, 7.0]:
        metrics.observe("test_duration", val, buckets=DEFAULT_BUCKETS)

    m = metrics.get_metrics()
    hist = m["histograms"].get("test_duration", {})

    if not hist:
        issues.append("Histogram boş")
        return "Histogram Buckets", False, issues

    # Bucket kontrolü
    buckets = hist.get("buckets", {})
    if not buckets:
        issues.append("Bucket'lar eksik")
    else:
        # 0.001 bucket'ında 1 değer olmalı (0.0005)
        if buckets.get("0.001", 0) != 1:
            issues.append(f"0.001 bucket: {buckets.get('0.001')} (beklenen: 1)")
        # +Inf toplamı count'a eşit olmalı
        if buckets.get("+Inf", 0) != 9:
            issues.append(f"+Inf bucket: {buckets.get('+Inf')} (beklenen: 9)")

    return "Histogram Buckets", len(issues) == 0, issues


async def test_histogram_prometheus_format() -> Any:
    """Histogram Prometheus text format doğru olmalı."""
    metrics = PrometheusMetrics()
    issues = []

    metrics.observe("test_latency", 0.05, buckets=(0.01, 0.05, 0.1, 1.0))
    metrics.observe("test_latency", 0.03, buckets=(0.01, 0.05, 0.1, 1.0))
    metrics.observe("test_latency", 0.5, buckets=(0.01, 0.05, 0.1, 1.0))

    text = metrics.get_prometheus_text()

    if "# TYPE test_latency histogram" not in text:
        issues.append("TYPE declaration eksik")
    if 'test_latency_bucket{le="0.01"}' not in text:
        issues.append("Bucket 0.01 eksik")
    if "test_latency_count 3" not in text:
        issues.append("Count eksik")
    if "test_latency_sum" not in text:
        issues.append("Sum eksik")

    return "Histogram Prometheus Format", len(issues) == 0, issues


async def test_timed_context_manager() -> Any:
    """timed() context manager süre ölçmeli."""
    metrics = PrometheusMetrics()
    issues = []

    with metrics.timed("test_timer"):
        await asyncio.sleep(0.05)

    m = metrics.get_metrics()
    hist = m["histograms"].get("test_timer", {})

    if not hist:
        issues.append("Timer histogram boş")
    elif hist.get("count", 0) != 1:
        issues.append(f"Count: {hist.get('count')}")
    elif hist.get("avg", 0) < 0.03:
        issues.append(f"avg too low: {hist.get('avg')}")

    return "Timed Context Manager", len(issues) == 0, issues


# =====================================================
# ALERTING TESTS
# =====================================================


async def test_health_change_alert() -> Any:
    """Health değişikliği alert üretmeli."""
    alerting = AlertingSystem()
    issues = []

    # İlk durum
    alerting.check_health({"status": "HEALTHY"})

    # DEGRADED'e geçiş
    alerting.check_health({"status": "DEGRADED", "issues": ["test"]})

    active = alerting.get_active_alerts()
    health_alerts = [a for a in active if a["alert_type"] == "health_change"]

    if len(health_alerts) == 0:
        issues.append("Health change alert üretilmedi")
    elif health_alerts[-1]["severity"] != "WARNING":
        issues.append(f"Severity: {health_alerts[-1]['severity']}")

    # UNHEALTHY'e geçiş
    alerting.check_health({"status": "UNHEALTHY", "issues": ["critical"]})
    active = alerting.get_active_alerts()
    critical_alerts = [a for a in active if a["severity"] == "CRITICAL"]
    if len(critical_alerts) == 0:
        issues.append("UNHEALTHY CRITICAL alert üretilmedi")

    return "Health Change Alert", len(issues) == 0, issues


async def test_invariant_failure_alert() -> Any:
    """Invariant failure alert üretmeli."""
    alerting = AlertingSystem()
    issues = []

    alerting.check_invariant(False, {"cash": -999})

    active = alerting.get_active_alerts()
    inv_alerts = [a for a in active if a["alert_type"] == "invariant_failure"]

    if len(inv_alerts) == 0:
        issues.append("Invariant failure alert üretilmedi")
    elif inv_alerts[0]["severity"] != "CRITICAL":
        issues.append(f"Severity: {inv_alerts[0]['severity']}")

    return "Invariant Failure Alert", len(issues) == 0, issues


async def test_lock_deadlock_alert() -> Any:
    """Lock deadlock alert üretmeli."""
    alerting = AlertingSystem()
    issues = []

    # İlk deadlock
    alerting.check_lock_metrics({"test_lock": {"total_deadlocks_detected": 1}})
    active = alerting.get_active_alerts()
    dl_alerts = [a for a in active if a["alert_type"] == "lock_deadlock"]

    if len(dl_alerts) == 0:
        issues.append("Deadlock alert üretilmedi")

    return "Lock Deadlock Alert", len(issues) == 0, issues


async def test_lock_timeout_spike_alert() -> Any:
    """Lock timeout spike alert üretmeli."""
    alerting = AlertingSystem()
    issues = []

    # İlk kontrol — 0 timeout
    alerting.check_lock_metrics({"test": {"total_timeouts": 0}})

    # Spike — 3+ artış
    alerting.check_lock_metrics({"test": {"total_timeouts": 5}})

    active = alerting.get_active_alerts()
    spike_alerts = [a for a in active if a["alert_type"] == "lock_timeout_spike"]

    if len(spike_alerts) == 0:
        issues.append("Timeout spike alert üretilmedi")

    return "Lock Timeout Spike Alert", len(issues) == 0, issues


async def test_negative_cash_alert() -> Any:
    """Negatif cash alert üretmeli."""
    alerting = AlertingSystem()
    issues = []

    alerting.check_negative_cash(-500.0)

    active = alerting.get_active_alerts()
    cash_alerts = [a for a in active if a["alert_type"] == "cash_negative"]

    if len(cash_alerts) == 0:
        issues.append("Negative cash alert üretilmedi")
    elif cash_alerts[0]["severity"] != "CRITICAL":
        issues.append(f"Severity: {cash_alerts[0]['severity']}")

    return "Negative Cash Alert", len(issues) == 0, issues


async def test_drawdown_breach_alert() -> Any:
    """Drawdown breach alert üretmeli."""
    alerting = AlertingSystem()
    issues = []

    alerting.check_drawdown(20.0, threshold_pct=15.0)

    active = alerting.get_active_alerts()
    dd_alerts = [a for a in active if a["alert_type"] == "drawdown_breach"]

    if len(dd_alerts) == 0:
        issues.append("Drawdown breach alert üretilmedi")

    return "Drawdown Breach Alert", len(issues) == 0, issues


async def test_alert_summary() -> Any:
    """Alert özeti doğru bilgi vermeli."""
    alerting = AlertingSystem()
    issues = []

    alerting.check_health({"status": "HEALTHY"})  # İlk durum
    alerting.check_invariant(False, {})
    alerting.check_negative_cash(-100)
    alerting.check_health({"status": "DEGRADED"})

    summary = alerting.get_alert_summary()

    if summary.get("active_alerts", 0) < 3:
        issues.append(f"Active alerts: {summary.get('active_alerts')} (beklenen: >=3)")
    if "CRITICAL" not in summary.get("by_severity", {}):
        issues.append("CRITICAL severity eksik")

    return "Alert Summary", len(issues) == 0, issues


async def test_alert_resolve() -> Any:
    """Alert resolve mekanizması."""
    alerting = AlertingSystem()
    issues = []

    alerting.check_negative_cash(-100)
    active_before = len(alerting.get_active_alerts())

    alerting.resolve_alerts("cash_negative")
    active_after = len(alerting.get_active_alerts())

    if active_after >= active_before:
        issues.append("Alert resolve edilmedi")

    return "Alert Resolve", len(issues) == 0, issues


# =====================================================
# DASHBOARD TEST
# =====================================================


async def test_dashboard_json() -> Any:
    """Grafana dashboard JSON geçerli olmalı."""
    issues = []

    dashboard_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "monitoring", "grafana_dashboard.json"
    )

    if not os.path.exists(dashboard_path):
        issues.append("Dashboard dosyası bulunamadı")
        return "Dashboard JSON", False, issues

    with open(dashboard_path) as f:
        data = orjson.loads(f.read())

    if "dashboard" not in data:
        issues.append("dashboard key eksik")

    dash = data.get("dashboard", {})

    if not dash.get("title"):
        issues.append("title eksik")
    if not dash.get("panels"):
        issues.append("panels eksik")
    elif len(dash["panels"]) < 5:
        issues.append(f"Yetersiz panel: {len(dash['panels'])}")

    # Temel paneller var mı?
    panel_titles = [p.get("title", "") for p in dash.get("panels", [])]
    required = ["Portfolio Equity", "Cash Balance", "Drawdown", "Lock"]
    for r in required:
        if not any(r.lower() in t.lower() for t in panel_titles):
            issues.append(f"Panel eksik: {r}")

    return "Dashboard JSON", len(issues) == 0, issues


# =====================================================
# RUN
# =====================================================


async def run_all() -> Any:
    """Otomatik eklendi."""
    logger.info("=" * 60)
    logger.info("MONITORING OPERATIONS TESTLERİ")
    logger.info("=" * 60)

    tests = [
        # Auth
        test_metrics_token_auth,
        test_admin_token_auth,
        test_bearer_token_extraction,
        test_api_key_extraction,
        test_rate_limiting,
        test_auth_disabled,
        test_failed_attempt_tracking,
        # Prometheus
        test_histogram_buckets,
        test_histogram_prometheus_format,
        test_timed_context_manager,
        # Alerting
        test_health_change_alert,
        test_invariant_failure_alert,
        test_lock_deadlock_alert,
        test_lock_timeout_spike_alert,
        test_negative_cash_alert,
        test_drawdown_breach_alert,
        test_alert_summary,
        test_alert_resolve,
        # Dashboard
        test_dashboard_json,
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
        logger.info(f"\n{icon} {name}")
        if ok:
            passed += 1
            logger.info("   PASSED")
        else:
            failed += 1
            for i in issues:
                logger.info(f"   ❌ {i}")
                all_issues.append(f"{name}: {i}")

    logger.info(f"\n{'=' * 60}")
    logger.info(f"SONUÇ: {passed}/{passed + failed} geçti")
    if all_issues:
        logger.info("\nTÜM HATALAR:")
        for i, issue in enumerate(all_issues, 1):
            logger.info(f"  {i}. {issue}")
    logger.info("=" * 60)
    return failed == 0


def main() -> Any:
    """Otomatik eklendi."""
    ok = asyncio.run(run_all())
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
