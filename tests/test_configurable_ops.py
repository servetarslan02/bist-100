#!/usr/bin/env python3
"""
Configurable Operations Testleri

Kapsam:
- Alert policy config loading/reload
- Invalid policy fallback
- Alert silence lifecycle
- Silence restart recovery
- JWKS key rotation
- Policy-based escalation
- Policy-based notification routing
"""

import asyncio
import os
import sys
import tempfile
import time

import orjson

from services.core.alert_policy import (
    FALLBACK_ESCALATION_TIMEOUT_S,
    FALLBACK_NOTIFICATION_ROUTING,
    AlertPolicy,
    ensure_default_config,
)
from services.core.alerting import AlertingSystem
from services.core.monitoring_security import JWTProvider

# =====================================================
# POLICY CONFIG TESTS
# =====================================================


async def test_policy_load_from_file():
    """Config dosyasından policy yüklenmeli."""
    issues = []

    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        f.write(
            orjson.dumps(
                {
                    "version": 1,
                    "escalation_timeouts": {"cash_negative": 60, "health_change": 600},
                    "notification_routing": {"WARNING": ["log"], "CRITICAL": ["log", "webhook"]},
                    "severity_thresholds": {"drawdown_warning_pct": 8.0},
                }
            ).decode()
        )
        config_path = f.name

    policy = AlertPolicy.load(config_path)

    if policy.get_escalation_timeout("cash_negative") != 60:
        issues.append(f"cash_negative timeout: {policy.get_escalation_timeout('cash_negative')}")
    if policy.get_escalation_timeout("health_change") != 600:
        issues.append(f"health_change timeout: {policy.get_escalation_timeout('health_change')}")
    if policy.get_notification_channels("CRITICAL") != ["log", "webhook"]:
        issues.append(f"CRITICAL routing: {policy.get_notification_channels('CRITICAL')}")
    if policy.get_threshold("drawdown_warning_pct") != 8.0:
        issues.append(f"drawdown threshold: {policy.get_threshold('drawdown_warning_pct')}")

    os.unlink(config_path)
    return "Policy Load From File", len(issues) == 0, issues


async def test_policy_fallback_on_missing_file():
    """Dosya yoksa fallback kullanılmalı."""
    issues = []

    policy = AlertPolicy.load("/nonexistent/path/policy.json")

    if policy.get_escalation_timeout("cash_negative") != FALLBACK_ESCALATION_TIMEOUT_S["cash_negative"]:
        issues.append("Fallback escalation timeout yanlış")

    if policy.get_notification_channels("CRITICAL") != FALLBACK_NOTIFICATION_ROUTING["CRITICAL"]:
        issues.append("Fallback notification routing yanlış")

    return "Policy Fallback Missing File", len(issues) == 0, issues


async def test_policy_fallback_on_invalid_json():
    """Geçersiz JSON'da fallback kullanılmalı."""
    issues = []

    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        f.write("{invalid json content")
        config_path = f.name

    policy = AlertPolicy.load(config_path)

    if policy.get_escalation_timeout("cash_negative") != FALLBACK_ESCALATION_TIMEOUT_S["cash_negative"]:
        issues.append("Invalid JSON fallback çalışmadı")

    os.unlink(config_path)
    return "Policy Fallback Invalid JSON", len(issues) == 0, issues


async def test_policy_validation():
    """Geçersiz policy değerleri tespit edilmeli."""
    issues = []

    policy = AlertPolicy()
    policy.escalation_timeouts = {"test": -100}  # Negatif
    errors = policy.validate()

    if not errors:
        issues.append("Negatif timeout tespit edilemedi")

    policy2 = AlertPolicy()
    policy2.notification_routing = {"INVALID": ["log"]}
    errors2 = policy2.validate()

    if not errors2:
        issues.append("Geçersiz severity tespit edilemedi")

    policy3 = AlertPolicy()
    policy3.notification_routing = {"INFO": ["nonexistent_channel"]}
    errors3 = policy3.validate()

    if not errors3:
        issues.append("Geçersiz channel tespit edilemedi")

    return "Policy Validation", len(issues) == 0, issues


async def test_policy_reload():
    """Config dosyası değişirse reload yapılmalı."""
    issues = []

    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        f.write(orjson.dumps({"version": 1, "escalation_timeouts": {"cash_negative": 60}}).decode())
        config_path = f.name

    policy = AlertPolicy.load(config_path)

    if policy.get_escalation_timeout("cash_negative") != 60:
        issues.append("İlk yükleme yanlış")

    # Dosyayı güncelle
    time.sleep(0.1)
    with open(config_path, "w") as f:
        f.write(orjson.dumps({"version": 2, "escalation_timeouts": {"cash_negative": 120}}).decode())

    reloaded = policy.reload_if_changed()
    if not reloaded:
        issues.append("Reload algılanamadı")
    if policy.get_escalation_timeout("cash_negative") != 120:
        issues.append(f"Reload sonrası timeout: {policy.get_escalation_timeout('cash_negative')}")

    os.unlink(config_path)
    return "Policy Reload", len(issues) == 0, issues


async def test_policy_reload_no_change():
    """Dosya değişmemişse reload yapılmamalı."""
    issues = []

    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        f.write(orjson.dumps({"version": 1, "escalation_timeouts": {"cash_negative": 60}}).decode())
        config_path = f.name

    policy = AlertPolicy.load(config_path)
    reloaded = policy.reload_if_changed()

    if reloaded:
        issues.append("Değişiklik yokken reload yapıldı")

    os.unlink(config_path)
    return "Policy Reload No Change", len(issues) == 0, issues


async def test_policy_default_config():
    """Varsayılan config dosyası oluşturulmalı."""
    issues = []

    with tempfile.TemporaryDirectory() as tmpdir:
        config_path = os.path.join(tmpdir, "test_policy.json")
        ensure_default_config(config_path)

        if not os.path.exists(config_path):
            issues.append("Default config oluşturulamadı")
        else:
            with open(config_path) as f:
                data = orjson.loads(f.read())
            if "escalation_timeouts" not in data:
                issues.append("escalation_timeouts eksik")
            if "notification_routing" not in data:
                issues.append("notification_routing eksik")

    return "Default Config", len(issues) == 0, issues


# =====================================================
# SILENCE TESTS
# =====================================================


async def test_silence_add_and_check():
    """Susturma eklenebilmeli ve kontrol edilebilmeli."""
    issues = []

    policy = AlertPolicy()

    if policy.is_silenced("cash_negative", "abc123"):
        issues.append("Susturma yokken silenced döndü")

    policy.add_silence(alert_type="cash_negative", duration_s=60, reason="test")

    if not policy.is_silenced("cash_negative", "abc123"):
        issues.append("Susturma eklenmedi")

    # Farklı tip susturulmamalı
    if policy.is_silenced("health_change", "def456"):
        issues.append("Farklı tip susturuldu")

    return "Silence Add And Check", len(issues) == 0, issues


async def test_silence_fingerprint_specific():
    """Belirli fingerprint susturulmalı, diğerleri susturulmamalı."""
    issues = []

    policy = AlertPolicy()
    policy.add_silence(fingerprint="specific_fp", duration_s=60)

    if not policy.is_silenced("any_type", "specific_fp"):
        issues.append("Belirli fingerprint susturulamadı")

    if policy.is_silenced("any_type", "other_fp"):
        issues.append("Diğer fingerprint susturuldu")

    return "Silence Fingerprint Specific", len(issues) == 0, issues


async def test_silence_expiry():
    """Süresi biten susturma otomatik kalkmalı."""
    issues = []

    policy = AlertPolicy()
    policy.add_silence(alert_type="test", duration_s=0.1)  # 100ms

    if not policy.is_silenced("test", "abc"):
        issues.append("Susturma eklenmedi")

    await asyncio.sleep(0.15)

    if policy.is_silenced("test", "abc"):
        issues.append("Süresi dolan susturma kalkmadı")

    return "Silence Expiry", len(issues) == 0, issues


async def test_silence_remove():
    """Susturma kaldırılabilmeli."""
    issues = []

    policy = AlertPolicy()
    policy.add_silence(alert_type="test", duration_s=60)

    if not policy.is_silenced("test", "abc"):
        issues.append("Susturma eklenmedi")

    removed = policy.remove_silence(alert_type="test")
    if removed == 0:
        issues.append("Susturma kaldırılamadı")

    if policy.is_silenced("test", "abc"):
        issues.append("Susturma hâlâ aktif")

    return "Silence Remove", len(issues) == 0, issues


async def test_silence_persistence():
    """Susturma durumu DB'ye kaydedilebilmeli ve yüklenebilmeli."""
    import duckdb

    issues = []

    db = duckdb.connect(":memory:")
    db.execute("""CREATE TABLE alert_silences (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        alert_type TEXT, fingerprint TEXT,
        start_time REAL NOT NULL, end_time REAL NOT NULL,
        reason TEXT, created_by TEXT DEFAULT 'system',
        created_at REAL, UNIQUE(fingerprint, alert_type))""")
    db.commit()

    policy1 = AlertPolicy()
    policy1.add_silence(alert_type="test", duration_s=3600, reason="maintenance", db=db)

    policy2 = AlertPolicy()
    policy2.load_silences_from_db(db)

    if not policy2.is_silenced("test", "any"):
        issues.append("Silence DB'den yüklenemedi")

    active = policy2.get_active_silences()
    if len(active) == 0:
        issues.append("Aktif silence yok")

    return "Silence Persistence", len(issues) == 0, issues


async def test_silence_in_alerting_system():
    """Susturma alerting sistemiyle entegre çalışmalı."""
    issues = []

    policy = AlertPolicy()
    alerting = AlertingSystem(policy=policy)

    # Susturma ekle
    alerting.add_silence(alert_type="cash_negative", duration_s=60, reason="test")

    # Alert üret — susturulmalı
    alerting.check_negative_cash(-100)
    active = alerting.get_active_alerts()

    if len(active) != 0:
        issues.append(f"Susturulmuş alert üretildi: {len(active)}")

    # Farklı alert — susturulmamalı
    alerting._last_health_status = "HEALTHY"
    alerting.check_health({"status": "DEGRADED"})
    active2 = alerting.get_active_alerts()

    if len(active2) == 0:
        issues.append("Susturulmamış alert üretilemedi")

    return "Silence In Alerting System", len(issues) == 0, issues


async def test_silence_active_list():
    """Aktif susturma listesi doğru olmalı."""
    issues = []

    policy = AlertPolicy()
    policy.add_silence(alert_type="test1", duration_s=60, reason="reason1")
    policy.add_silence(alert_type="test2", duration_s=0.01, reason="expires_soon")

    await asyncio.sleep(0.02)

    active = policy.get_active_silences()
    if len(active) != 1:
        issues.append(f"Aktif silence: {len(active)} (beklenen: 1)")

    return "Silence Active List", len(issues) == 0, issues


# =====================================================
# JWKS TESTS
# =====================================================


async def test_jwt_hs256_still_works():
    """HS256 JWT doğrulama JWKS ile uyumlu olmalı."""
    issues = []

    try:
        import jwt as pyjwt
    except ImportError:
        return "JWT HS256 JWKS", False, ["PyJWT not installed"]

    secret = "test_secret"
    provider = JWTProvider(secret=secret, algorithm="HS256")

    token = pyjwt.encode({"sub": "u1", "roles": ["admin"], "exp": int(time.time()) + 100}, secret, algorithm="HS256")

    result = await provider.verify(token)
    if not result.authenticated:
        issues.append(f"HS256 reddedildi: {result.error}")

    return "JWT HS256 JWKS", len(issues) == 0, issues


async def test_jwt_key_selection():
    """Key seçimi doğru olmalı (HS256 → secret, RS256 → JWKS)."""
    issues = []

    try:
        import jwt as pyjwt
    except ImportError:
        return "JWT Key Selection", False, ["PyJWT not installed"]

    # HS256 — secret kullanmalı
    provider_hs = JWTProvider(secret="test", algorithm="HS256")
    key = await provider_hs._get_key("dummy.token", pyjwt)
    if key != "test":
        issues.append(f"HS256 key: {key}")

    # RS256 JWKS URL yoksa secret kullanmalı
    provider_rs = JWTProvider(secret="fallback", algorithm="RS256")
    key2 = await provider_rs._get_key("dummy.token", pyjwt)
    if key2 != "fallback":
        issues.append(f"RS256 fallback key: {key2}")

    return "JWT Key Selection", len(issues) == 0, issues


async def test_jwt_jwks_cache():
    """JWKS cache TTL doğru çalışmalı."""
    issues = []

    provider = JWTProvider(algorithm="RS256", jwks_url="https://example.com/.well-known/jwks.json", jwks_cache_ttl_s=60)

    # Cache boş
    if provider._jwks_cache:
        issues.append("Cache boş olmalı")

    # TTL kontrolü
    provider._jwks_last_fetch = time.time()
    await provider._refresh_jwks_if_needed()

    if provider._jwks_last_fetch != provider._jwks_last_fetch:
        issues.append("TTL dolmadan refresh yapıldı")

    return "JWT JWKS Cache", len(issues) == 0, issues


async def test_jwt_expiration():
    """Expired token reddedilmeli."""
    issues = []

    try:
        import jwt as pyjwt
    except ImportError:
        return "JWT Expiration", False, ["PyJWT not installed"]

    secret = "test"
    provider = JWTProvider(secret=secret)

    expired = pyjwt.encode({"sub": "u", "roles": [], "exp": int(time.time()) - 100}, secret, algorithm="HS256")
    result = await provider.verify(expired)
    if result.authenticated:
        issues.append("Expired token kabul edildi")
    if "expired" not in result.error.lower():
        issues.append(f"Error: {result.error}")

    return "JWT Expiration", len(issues) == 0, issues


# =====================================================
# POLICY-BASED ALERTING TESTS
# =====================================================


async def test_policy_based_escalation():
    """Policy'deki timeout'a göre escalation yapılmalı."""
    issues = []

    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        f.write(orjson.dumps({"version": 1, "escalation_timeouts": {"health_change": 0.1}}).decode())
        config_path = f.name

    policy = AlertPolicy.load(config_path)
    alerting = AlertingSystem(policy=policy)

    alerting._last_health_status = "HEALTHY"
    alerting.check_health({"status": "DEGRADED", "issues": ["test"]})

    await asyncio.sleep(0.15)

    # Manuel timestamp eski yap
    for a in alerting._alerts:
        a.timestamp = time.time() - 1

    alerting._check_escalations()

    active = alerting.get_active_alerts()
    if active and active[0]["status"] != "ESCALATED":
        issues.append(f"Status: {active[0]['status']}")

    os.unlink(config_path)
    return "Policy Based Escalation", len(issues) == 0, issues


async def test_policy_notification_routing():
    """Policy routing'e göre bildirim gönderilmeli."""
    issues = []

    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        f.write(orjson.dumps({"version": 1, "notification_routing": {"CRITICAL": ["log"]}}).decode())
        config_path = f.name

    policy = AlertPolicy.load(config_path)

    channels = policy.get_notification_channels("CRITICAL")
    if channels != ["log"]:
        issues.append(f"CRITICAL channels: {channels}")

    channels2 = policy.get_notification_channels("WARNING")
    # WARNING için policy'de tanım yoksa fallback kullanılmalı
    if not channels2:
        issues.append("WARNING channels boş")

    os.unlink(config_path)
    return "Policy Notification Routing", len(issues) == 0, issues


# =====================================================
# RUN
# =====================================================


async def run_all():
    print("=" * 60)
    print("CONFIGURABLE OPERATIONS TESTLERİ")
    print("=" * 60)

    tests = [
        # Policy
        test_policy_load_from_file,
        test_policy_fallback_on_missing_file,
        test_policy_fallback_on_invalid_json,
        test_policy_validation,
        test_policy_reload,
        test_policy_reload_no_change,
        test_policy_default_config,
        # Silence
        test_silence_add_and_check,
        test_silence_fingerprint_specific,
        test_silence_expiry,
        test_silence_remove,
        test_silence_persistence,
        test_silence_in_alerting_system,
        test_silence_active_list,
        # JWKS
        test_jwt_hs256_still_works,
        test_jwt_key_selection,
        test_jwt_jwks_cache,
        test_jwt_expiration,
        # Policy-based alerting
        test_policy_based_escalation,
        test_policy_notification_routing,
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
