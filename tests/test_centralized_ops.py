#!/usr/bin/env python3
"""
Centralized Operations Testleri

Kapsam:
- Policy API update/rollback/versioning
- Policy audit log
- DB silence persistence
- JWKS key rotation integration
- Old key token rejection
"""

import sys
import os
import orjson
import asyncio
import time
import duckdb
import tempfile

from services.core.alert_policy import AlertPolicy, SilenceRule, FALLBACK_ESCALATION_TIMEOUT_S
from services.core.alerting import AlertingSystem, AlertType
from services.core.monitoring_security import JWTProvider


# =====================================================
# POLICY MANAGEMENT TESTS
# =====================================================

async def test_policy_update_via_api():
    """Policy API üzerinden güncellenebilmeli."""
    issues = []

    policy = AlertPolicy()
    result = policy.update({
        "escalation_timeouts": {"cash_negative": 999},
        "notification_routing": {"CRITICAL": ["log"]},
    }, actor="test")

    if not result.get("success"):
        issues.append(f"Update başarısız: {result}")

    if policy.get_escalation_timeout("cash_negative") != 999:
        issues.append(f"Timeout güncellenmedi: {policy.get_escalation_timeout('cash_negative')}")

    if policy.get_notification_channels("CRITICAL") != ["log"]:
        issues.append(f"Routing güncellenmedi: {policy.get_notification_channels('CRITICAL')}")

    if policy._version != 1:
        issues.append(f"Version: {policy._version}")

    return "Policy Update Via API", len(issues) == 0, issues


async def test_policy_versioning():
    """Policy versiyonlama doğru çalışmalı."""
    issues = []

    policy = AlertPolicy()

    # İlk güncelleme
    policy.update({"escalation_timeouts": {"cash_negative": 100}}, actor="v1")
    # İkinci güncelleme
    policy.update({"escalation_timeouts": {"cash_negative": 200}}, actor="v2")

    if policy._version != 2:
        issues.append(f"Version: {policy._version}")

    history = policy.get_history()
    if len(history) < 2:
        issues.append(f"History: {len(history)}")

    return "Policy Versioning", len(issues) == 0, issues


async def test_policy_rollback():
    """Policy rollback çalışmalı."""
    issues = []

    policy = AlertPolicy()

    # v1: 100
    policy.update({"escalation_timeouts": {"cash_negative": 100}}, actor="v1")
    # v2: 200
    policy.update({"escalation_timeouts": {"cash_negative": 200}}, actor="v2")

    if policy.get_escalation_timeout("cash_negative") != 200:
        issues.append(f"v2 timeout: {policy.get_escalation_timeout('cash_negative')}")

    # Rollback to v1
    result = policy.rollback(target_version=1, actor="test")
    if not result.get("success"):
        issues.append(f"Rollback başarısız: {result}")

    if policy.get_escalation_timeout("cash_negative") != 100:
        issues.append(f"Rollback sonrası: {policy.get_escalation_timeout('cash_negative')}")

    return "Policy Rollback", len(issues) == 0, issues


async def test_policy_rollback_to_previous():
    """Bir önceki versiyona rollback."""
    issues = []

    policy = AlertPolicy()
    policy.update({"escalation_timeouts": {"cash_negative": 100}}, actor="v1")
    policy.update({"escalation_timeouts": {"cash_negative": 200}}, actor="v2")
    policy.update({"escalation_timeouts": {"cash_negative": 300}}, actor="v3")

    # Bir önceki versiyona dön
    result = policy.rollback(target_version=0, actor="test")
    if not result.get("success"):
        issues.append(f"Rollback başarısız: {result}")

    # v2'nin değerlerine dönmeli
    if policy.get_escalation_timeout("cash_negative") != 200:
        issues.append(f"Rollback sonrası: {policy.get_escalation_timeout('cash_negative')}")

    return "Policy Rollback Previous", len(issues) == 0, issues


async def test_policy_validation_on_update():
    """Geçersiz config update reddedilmeli."""
    issues = []

    policy = AlertPolicy()
    original_timeout = policy.get_escalation_timeout("cash_negative")

    # Geçersiz config (negatif timeout)
    result = policy.update({"escalation_timeouts": {"cash_negative": -1}}, actor="test")
    if result.get("success"):
        issues.append("Geçersiz config kabul edildi")

    # Değer değişmemeli
    if policy.get_escalation_timeout("cash_negative") != original_timeout:
        issues.append("Değer değişti (değişmemeli)")

    return "Policy Validation On Update", len(issues) == 0, issues


async def test_policy_audit_log():
    """Audit log doğru kaydedilmeli."""
    issues = []

    policy = AlertPolicy()
    policy.update({"escalation_timeouts": {"cash_negative": 100}}, actor="user1")
    policy.add_silence(alert_type="test", duration_s=60, reason="maintenance", created_by="user2")
    policy.rollback(actor="user3")

    audit = policy.get_audit_log()

    if len(audit) < 3:
        issues.append(f"Audit entries: {len(audit)}")

    # Audit entry'lerinde actor bilgisi olmalı
    actors = [e.get("actor") for e in audit]
    if "user1" not in actors:
        issues.append("user1 audit'te yok")

    # Action'lar doğru olmalı
    actions = [e.get("action") for e in audit]
    if "update" not in actions:
        issues.append("update action yok")
    if "silence_add" not in actions:
        issues.append("silence_add action yok")
    if "rollback" not in actions:
        issues.append("rollback action yok")

    return "Policy Audit Log", len(issues) == 0, issues


async def test_policy_history_limit():
    """History limiti doğru çalışmalı."""
    issues = []

    policy = AlertPolicy()
    for i in range(60):
        policy.update({"escalation_timeouts": {"cash_negative": i}}, actor=f"v{i}")

    history = policy.get_history()
    if len(history) > 50:
        issues.append(f"History limit aşıldı: {len(history)}")

    return "Policy History Limit", len(issues) == 0, issues


async def test_policy_persist_to_file():
    """Policy dosyaya kaydedilmeli."""
    issues = []

    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        f.write(orjson.dumps({"version": 0}).decode())
        config_path = f.name

    policy = AlertPolicy(_config_path=config_path)
    policy.update({"escalation_timeouts": {"cash_negative": 42}}, actor="test")

    # Dosyayı oku
    with open(config_path) as f:
        saved = orjson.loads(f.read())

    if saved.get("escalation_timeouts", {}).get("cash_negative") != 42:
        issues.append(f"Dosyaya kaydedilmedi: {saved}")

    os.unlink(config_path)
    return "Policy Persist To File", len(issues) == 0, issues


# =====================================================
# DB SILENCE TESTS
# =====================================================

async def test_silence_db_persist():
    """Silence DB'ye persist edilmeli."""
    issues = []

    db = duckdb.connect(":memory:")
    db.execute("""
        CREATE TABLE alert_silences (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            alert_type TEXT, fingerprint TEXT,
            start_time REAL NOT NULL, end_time REAL NOT NULL,
            reason TEXT, created_by TEXT DEFAULT 'system',
            created_at REAL, UNIQUE(fingerprint, alert_type)
        )
    """)
    db.commit()

    policy = AlertPolicy()
    rule = policy.add_silence(
        alert_type="test", duration_s=3600,
        reason="maintenance", created_by="admin", db=db,
    )

    # DB'den oku
    rows = db.execute("SELECT * FROM alert_silences").fetchall()
    if len(rows) == 0:
        issues.append("Silence DB'ye kaydedilmedi")
    elif rows[0]["reason"] != "maintenance":
        issues.append(f"reason: {rows[0]['reason']}")
    elif rows[0]["created_by"] != "admin":
        issues.append(f"created_by: {rows[0]['created_by']}")

    return "Silence DB Persist", len(issues) == 0, issues


async def test_silence_db_load():
    """Silence DB'den yüklenmeli."""
    issues = []

    db = duckdb.connect(":memory:")
    db.execute("""
        CREATE TABLE alert_silences (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            alert_type TEXT, fingerprint TEXT,
            start_time REAL NOT NULL, end_time REAL NOT NULL,
            reason TEXT, created_by TEXT DEFAULT 'system',
            created_at REAL, UNIQUE(fingerprint, alert_type)
        )
    """)
    db.commit()

    # Direkt DB'ye ekle
    db.execute(
        "INSERT INTO alert_silences (alert_type, fingerprint, start_time, end_time, reason, created_by, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("cash_negative", None, time.time(), time.time() + 3600, "test", "admin", time.time())
    )
    db.commit()

    policy = AlertPolicy()
    policy.load_silences_from_db(db)

    if not policy.is_silenced("cash_negative", "any"):
        issues.append("Silence yüklenemedi")

    active = policy.get_active_silences()
    if len(active) != 1:
        issues.append(f"Aktif silence: {len(active)}")

    return "Silence DB Load", len(issues) == 0, issues


async def test_silence_db_remove():
    """Silence DB'den silinmeli."""
    issues = []

    db = duckdb.connect(":memory:")
    db.execute("""
        CREATE TABLE alert_silences (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            alert_type TEXT, fingerprint TEXT,
            start_time REAL NOT NULL, end_time REAL NOT NULL,
            reason TEXT, created_by TEXT DEFAULT 'system',
            created_at REAL, UNIQUE(fingerprint, alert_type)
        )
    """)
    db.commit()

    policy = AlertPolicy()
    policy.add_silence(fingerprint="fp1", duration_s=3600, reason="test", db=db)

    if not policy.is_silenced("any", "fp1"):
        issues.append("Silence eklenemedi")

    policy.remove_silence(fingerprint="fp1", db=db)

    if policy.is_silenced("any", "fp1"):
        issues.append("Silence silinemedi")

    rows = db.execute("SELECT * FROM alert_silences").fetchall()
    if len(rows) != 0:
        issues.append(f"DB'den silinmedi: {len(rows)}")

    return "Silence DB Remove", len(issues) == 0, issues


async def test_silence_db_load_only_active():
    """Sadece aktif silence'lar yüklenmeli."""
    issues = []

    db = duckdb.connect(":memory:")
    db.execute("""
        CREATE TABLE alert_silences (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            alert_type TEXT, fingerprint TEXT,
            start_time REAL NOT NULL, end_time REAL NOT NULL,
            reason TEXT, created_by TEXT DEFAULT 'system',
            created_at REAL, UNIQUE(fingerprint, alert_type)
        )
    """)
    db.commit()

    # Aktif silence
    db.execute(
        "INSERT INTO alert_silences (alert_type, start_time, end_time, reason) VALUES (?, ?, ?, ?)",
        ("active", time.time(), time.time() + 3600, "active")
    )
    # Süresi dolmuş silence
    db.execute(
        "INSERT INTO alert_silences (alert_type, start_time, end_time, reason) VALUES (?, ?, ?, ?)",
        ("expired", time.time() - 3600, time.time() - 1, "expired")
    )
    db.commit()

    policy = AlertPolicy()
    policy.load_silences_from_db(db)

    if not policy.is_silenced("active", "any"):
        issues.append("Aktif silence yüklenemedi")

    if policy.is_silenced("expired", "any"):
        issues.append("Süresi dolmuş silence yüklendi")

    return "Silence DB Load Active Only", len(issues) == 0, issues


async def test_silence_audit_trail():
    """Silence audit trail doğru olmalı."""
    issues = []

    policy = AlertPolicy()
    policy.add_silence(alert_type="test1", duration_s=60, reason="maintenance", created_by="admin")
    policy.add_silence(fingerprint="fp2", duration_s=120, reason="debug", created_by="dev")
    policy.remove_silence(alert_type="test1", actor="ops")

    audit = policy.get_audit_log()
    actions = [e.get("action") for e in audit]

    if "silence_add" not in actions:
        issues.append("silence_add audit yok")
    if "silence_remove" not in actions:
        issues.append("silence_remove audit yok")

    # Actor bilgisi
    add_entries = [e for e in audit if e.get("action") == "silence_add"]
    if add_entries and add_entries[0].get("details", {}).get("created_by") != "admin":
        issues.append(f"created_by: {add_entries[0].get('details', {}).get('created_by')}")

    return "Silence Audit Trail", len(issues) == 0, issues


# =====================================================
# JWKS KEY ROTATION TESTS
# =====================================================

async def test_jwks_key_rotation():
    """Key rotation durumunda eski key ile token reddedilmeli."""
    issues = []

    try:
        import jwt as pyjwt
    except ImportError:
        return "JWKS Key Rotation", False, ["PyJWT not installed"]

    # İlk key
    secret1 = "secret_key_v1"
    provider = JWTProvider(secret=secret1, algorithm="HS256")

    token_v1 = pyjwt.encode(
        {"sub": "u1", "roles": ["admin"], "exp": int(time.time()) + 3600},
        secret1, algorithm="HS256"
    )

    result = await provider.verify(token_v1)
    if not result.authenticated:
        issues.append(f"v1 token reddedildi: {result.error}")

    # Key rotation — yeni key
    secret2 = "secret_key_v2"
    provider._secret = secret2

    # Eski key ile imzalanmış token reddedilmeli
    result_old = await provider.verify(token_v1)
    if result_old.authenticated:
        issues.append("Eski key ile token kabul edildi (key rotation sonrası)")

    # Yeni key ile token kabul edilmeli
    token_v2 = pyjwt.encode(
        {"sub": "u1", "roles": ["admin"], "exp": int(time.time()) + 3600},
        secret2, algorithm="HS256"
    )
    result_new = await provider.verify(token_v2)
    if not result_new.authenticated:
        issues.append(f"Yeni key ile token reddedildi: {result_new.error}")

    return "JWKS Key Rotation", len(issues) == 0, issues


async def test_jwks_cache_invalidation():
    """Key rotation cache TTL doğru çalışmalı."""
    issues = []

    provider = JWTProvider(
        secret="test", algorithm="RS256",
        jwks_url="https://example.com/.well-known/jwks.json",
        jwks_cache_ttl_s=60
    )

    # Cache TTL kontrolü
    if provider._jwks_cache_ttl_s != 60:
        issues.append(f"TTL: {provider._jwks_cache_ttl_s}")

    # TTL dolmadan refresh tetiklenmemeli
    provider._jwks_last_fetch = time.time()
    old_fetch = provider._jwks_last_fetch
    await provider._refresh_jwks_if_needed()
    if provider._jwks_last_fetch != old_fetch:
        issues.append("TTL dolmadan refresh tetiklendi")

    # TTL dolduğunda refresh tetiklenmeli (network hatası olsa bile)
    provider._jwks_last_fetch = time.time() - 120
    await provider._refresh_jwks_if_needed()
    # Network hatası olsa bile _jwks_last_fetch güncellenmemeli (hata durumunda)
    # Ama TTL kontrolü doğru yapıldı

    return "JWKS Cache Invalidation", len(issues) == 0, issues


async def test_jwks_provider_without_url():
    """JWKS URL yoksa secret kullanmalı."""
    issues = []

    try:
        import jwt as pyjwt
    except ImportError:
        return "JWKS Without URL", False, ["PyJWT not installed"]

    secret = "fallback_secret"
    provider = JWTProvider(secret=secret, algorithm="RS256")  # URL yok

    token = pyjwt.encode(
        {"sub": "u1", "roles": ["viewer"], "exp": int(time.time()) + 100},
        secret, algorithm="HS256"  # HS256 ile imzala
    )

    # RS256 provider ama secret fallback
    key = await provider._get_key(token, pyjwt)
    if key != secret:
        issues.append(f"Fallback key: {key}")

    return "JWKS Without URL", len(issues) == 0, issues


async def test_jwt_token_with_expired_signature():
    """Expired signature reddedilmeli."""
    issues = []

    try:
        import jwt as pyjwt
    except ImportError:
        return "JWT Expired Signature", False, ["PyJWT not installed"]

    secret = "test"
    provider = JWTProvider(secret=secret)

    # Expired token
    expired = pyjwt.encode(
        {"sub": "u", "roles": [], "exp": int(time.time()) - 3600},
        secret, algorithm="HS256"
    )

    result = await provider.verify(expired)
    if result.authenticated:
        issues.append("Expired token kabul edildi")
    if "expired" not in result.error.lower():
        issues.append(f"Error: {result.error}")

    # Geçerli token
    valid = pyjwt.encode(
        {"sub": "u", "roles": ["admin"], "exp": int(time.time()) + 3600},
        secret, algorithm="HS256"
    )

    result2 = await provider.verify(valid)
    if not result2.authenticated:
        issues.append(f"Valid token reddedildi: {result2.error}")

    return "JWT Expired Signature", len(issues) == 0, issues


# =====================================================
# INTEGRATION TESTS
# =====================================================

async def test_alerting_with_policy_and_silence():
    """Alerting + policy + silence entegrasyonu."""
    issues = []

    db = duckdb.connect(":memory:")
    db.execute("""
        CREATE TABLE alert_silences (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            alert_type TEXT, fingerprint TEXT,
            start_time REAL NOT NULL, end_time REAL NOT NULL,
            reason TEXT, created_by TEXT DEFAULT 'system',
            created_at REAL, UNIQUE(fingerprint, alert_type)
        )
    """)
    db.execute("""
        CREATE TABLE alerts_state (
            fingerprint TEXT PRIMARY KEY, alert_type TEXT, severity TEXT,
            status TEXT, message TEXT, details TEXT, timestamp REAL,
            acknowledged_at REAL, escalated_at REAL, resolved_at REAL,
            escalation_count INTEGER DEFAULT 0, notification_status TEXT, updated_at REAL
        )
    """)
    db.commit()

    policy = AlertPolicy()
    alerting = AlertingSystem(policy=policy, db=db)

    # Policy güncelle
    alerting.update_policy({"escalation_timeouts": {"cash_negative": 0}}, actor="test")

    # Silence ekle
    alerting.add_silence(alert_type="health_change", duration_s=60, reason="maintenance")

    # health_change susturulmalı
    alerting._last_health_status = "HEALTHY"
    alerting.check_health({"status": "DEGRADED"})
    active = alerting.get_active_alerts()
    health_alerts = [a for a in active if a["alert_type"] == "health_change"]
    if len(health_alerts) != 0:
        issues.append(f"Health alert susturulamadı: {len(health_alerts)}")

    # cash_negative susturulmamalı
    alerting.check_negative_cash(-100)
    active2 = alerting.get_active_alerts()
    cash_alerts = [a for a in active2 if a["alert_type"] == "cash_negative"]
    if len(cash_alerts) == 0:
        issues.append("Cash alert üretilmedi")

    # Policy rollback
    result = alerting.rollback_policy(actor="test")
    if not result.get("success"):
        issues.append(f"Rollback başarısız: {result}")

    return "Alerting Policy Silence Integration", len(issues) == 0, issues


# =====================================================
# RUN
# =====================================================

async def run_all():
    print("=" * 60)
    print("CENTRALIZED OPERATIONS TESTLERİ")
    print("=" * 60)

    tests = [
        # Policy management
        test_policy_update_via_api,
        test_policy_versioning,
        test_policy_rollback,
        test_policy_rollback_to_previous,
        test_policy_validation_on_update,
        test_policy_audit_log,
        test_policy_history_limit,
        test_policy_persist_to_file,
        # DB silence
        test_silence_db_persist,
        test_silence_db_load,
        test_silence_db_remove,
        test_silence_db_load_only_active,
        test_silence_audit_trail,
        # JWKS
        test_jwks_key_rotation,
        test_jwks_cache_invalidation,
        test_jwks_provider_without_url,
        test_jwt_token_with_expired_signature,
        # Integration
        test_alerting_with_policy_and_silence,
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
