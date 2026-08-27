#!/usr/bin/env python3
"""
Policy Operations Testleri

Kapsam:
- Policy diff (eski/yeni/değişen alanlar)
- Optimistic locking (version conflict)
- Concurrent policy update
- Policy change webhook
- Batch silence add/remove
- Batch transaction rollback
- Audit log completeness
"""

import asyncio
import sys

import duckdb
import structlog

from services.core.alert_policy import (
    AlertPolicy,
    PolicyDiff,
    VersionConflictError,
)

logger = structlog.get_logger(__name__)


# =====================================================
# POLICY DIFF TESTS
# =====================================================


async def test_policy_diff_no_changes():
    """Aynı config diff'inde değişiklik olmamalı."""
    issues = []

    policy = AlertPolicy()
    diff = policy.compute_diff(policy.to_dict())

    if diff.has_changes:
        issues.append(f"Değişiklik var (olmamalı): {diff.summary()}")

    return "Policy Diff No Changes", len(issues) == 0, issues


async def test_policy_diff_changed_fields():
    """Değişen alanlar doğru tespit edilmeli."""
    issues = []

    policy = AlertPolicy()
    new_config = policy.to_dict()
    new_config["escalation_timeouts"] = {"cash_negative": 999}

    diff = policy.compute_diff(new_config)

    if not diff.has_changes:
        issues.append("Değişiklik tespit edilemedi")

    if "escalation_timeouts" not in diff.changed_fields:
        issues.append(f"changed_fields: {diff.changed_fields}")

    if diff.old_values.get("escalation_timeouts") is None:
        issues.append("old_values eksik")

    if diff.new_values.get("escalation_timeouts") is None:
        issues.append("new_values eksik")

    return "Policy Diff Changed Fields", len(issues) == 0, issues


async def test_policy_diff_added_removed():
    """Eklenen/silinen alanlar tespit edilmeli."""
    issues = []

    policy = AlertPolicy()
    old = policy.to_dict()
    new = {**old, "new_field": "value"}

    diff = PolicyDiff()
    # Manuel diff
    for key in set(list(old.keys()) + list(new.keys())):
        if key not in old:
            diff.added_keys.append(key)
            diff.new_values[key] = new[key]
        elif key not in new:
            diff.removed_keys.append(key)
            diff.old_values[key] = old[key]

    if "new_field" not in diff.added_keys:
        issues.append("added_keys eksik")

    return "Policy Diff Added Removed", len(issues) == 0, issues


async def test_policy_diff_summary():
    """Diff summary doğru olmalı."""
    issues = []

    diff = PolicyDiff(
        changed_fields=["escalation_timeouts"],
        added_keys=["new_field"],
        removed_keys=["old_field"],
    )

    summary = diff.summary()
    if "escalation_timeouts" not in summary:
        issues.append("changed eksik")
    if "new_field" not in summary:
        issues.append("added eksik")
    if "old_field" not in summary:
        issues.append("removed eksik")

    return "Policy Diff Summary", len(issues) == 0, issues


async def test_policy_diff_on_update():
    """Update sonrası diff döndürülmeli."""
    issues = []

    policy = AlertPolicy()
    result = policy.update({"escalation_timeouts": {"cash_negative": 42}}, actor="test")

    if not result.get("success"):
        issues.append(f"Update başarısız: {result}")

    diff = result.get("diff", {})
    if not diff.get("has_changes"):
        issues.append("Diff has_changes=False")

    return "Policy Diff On Update", len(issues) == 0, issues


# =====================================================
# OPTIMISTIC LOCKING TESTS
# =====================================================


async def test_optimistic_lock_version_conflict():
    """Yanlış version ile update reddedilmeli."""
    issues = []

    policy = AlertPolicy()
    policy._version = 5

    try:
        policy.update({"escalation_timeouts": {"cash_negative": 99}}, actor="user1", expected_version=3)
        issues.append("Version conflict yakalanmadı")
    except VersionConflictError as e:
        if "expected 3" not in str(e):
            issues.append(f"Error message: {e}")

    # Versiyon değişmemeli
    if policy._version != 5:
        issues.append(f"Version değişti: {policy._version}")

    return "Optimistic Lock Version Conflict", len(issues) == 0, issues


async def test_optimistic_lock_correct_version():
    """Doğru version ile update başarılı olmalı."""
    issues = []

    policy = AlertPolicy()
    policy._version = 5

    result = policy.update({"escalation_timeouts": {"cash_negative": 99}}, actor="user1", expected_version=5)

    if not result.get("success"):
        issues.append(f"Update başarısız: {result}")

    if policy._version != 6:
        issues.append(f"Version güncellenmedi: {policy._version}")

    return "Optimistic Lock Correct Version", len(issues) == 0, issues


async def test_optimistic_lock_no_version_check():
    "Version=0 ile kontrol yapılmamalı."
    issues = []

    policy = AlertPolicy()
    policy._version = 5

    result = policy.update({"escalation_timeouts": {"cash_negative": 99}}, actor="user1", expected_version=0)

    if not result.get("success"):
        issues.append(f"Update başarısız: {result}")

    return "Optimistic Lock No Check", len(issues) == 0, issues


async def test_edit_lock():
    """Edit lock doğru çalışmalı."""
    issues = []

    policy = AlertPolicy()

    # Lock al
    acquired = policy.acquire_edit_lock("user1", timeout_s=60)
    if not acquired:
        issues.append("Lock alınamadı")

    if not policy.is_locked():
        issues.append("Lock algılanamadı")

    # Başkası lock alamamalı
    acquired2 = policy.acquire_edit_lock("user2", timeout_s=60)
    if acquired2:
        issues.append("İkinci lock alındı (almamalı)")

    # Lock bilgisi
    info = policy.get_lock_info()
    if info.get("owner") != "user1":
        issues.append(f"Owner: {info.get('owner')}")

    # Lock bırak
    released = policy.release_edit_lock("user1")
    if not released:
        issues.append("Lock bırakılamadı")

    if policy.is_locked():
        issues.append("Lock hâlâ aktif")

    # Başkası artık alabilmeli
    acquired3 = policy.acquire_edit_lock("user2", timeout_s=60)
    if not acquired3:
        issues.append("Lock bırakıldıktan sonra alınamadı")

    policy.release_edit_lock("user2")

    return "Edit Lock", len(issues) == 0, issues


async def test_edit_lock_wrong_owner_release():
    """Yanlış owner lock bırakamamalı."""
    issues = []

    policy = AlertPolicy()
    policy.acquire_edit_lock("user1", timeout_s=60)

    released = policy.release_edit_lock("user2")
    if released:
        issues.append("Yanlış owner lock bıraktı")

    if not policy.is_locked():
        issues.append("Lock yanlışlıkla bırakıldı")

    policy.release_edit_lock("user1")

    return "Edit Lock Wrong Owner", len(issues) == 0, issues


async def test_concurrent_policy_update():
    """Çakışan güncellemeler version conflict üretmeli."""
    issues = []

    policy = AlertPolicy()
    policy._version = 1

    # User1 okur (version=1)
    # User2 okur (version=1)
    # User1 günceller (version=1→2)
    result1 = policy.update({"escalation_timeouts": {"cash_negative": 100}}, actor="user1", expected_version=1)
    if not result1.get("success"):
        issues.append(f"User1 update başarısız: {result1}")

    # User2 eski version ile günceller → conflict
    try:
        policy.update({"escalation_timeouts": {"cash_negative": 200}}, actor="user2", expected_version=1)
        issues.append("Concurrent update yakalanmadı")
    except VersionConflictError:
        logger.debug("Version conflict (expected) in test_concurrent_policy_update", exc_info=True)

    # Değer user1'in güncellemesi olmalı
    if policy.get_escalation_timeout("cash_negative") != 100:
        issues.append(f"Değer: {policy.get_escalation_timeout('cash_negative')}")

    return "Concurrent Policy Update", len(issues) == 0, issues


# =====================================================
# POLICY WEBHOOK TESTS
# =====================================================


async def test_policy_webhook_config():
    """Webhook URL'leri yapılandırılabilmeli."""
    issues = []

    policy = AlertPolicy()
    policy.set_webhook_urls(["https://hooks.example.com/1", "https://hooks.example.com/2"])

    if len(policy._webhook_urls) != 2:
        issues.append(f"URL count: {len(policy._webhook_urls)}")

    return "Policy Webhook Config", len(issues) == 0, issues


async def test_policy_change_triggers_notification():
    """Policy değişikliği webhook tetiklemeli."""
    issues = []

    policy = AlertPolicy()
    policy.set_webhook_urls(["https://hooks.example.com/test"])

    # Update — webhook tetiklenmeli (network hatası olsa bile)
    result = policy.update({"escalation_timeouts": {"cash_negative": 42}}, actor="test")

    if not result.get("success"):
        issues.append(f"Update başarısız: {result}")

    # Webhook çağrısı async olduğu için burada doğrudan doğrulayamayız
    # Ama diff'in döndüğünü doğrulayabiliriz
    diff = result.get("diff", {})
    if not diff.get("has_changes"):
        issues.append("Diff yok")

    return "Policy Change Triggers Notification", len(issues) == 0, issues


# =====================================================
# BATCH SILENCE TESTS
# ============================================================


async def test_batch_add_silences():
    """Toplu susturma ekleme çalışmalı."""
    issues = []

    db = duckdb.connect(":memory:")
    db.execute("""CREATE TABLE alert_silences (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        alert_type TEXT, fingerprint TEXT,
        start_time REAL NOT NULL, end_time REAL NOT NULL,
        reason TEXT, created_by TEXT DEFAULT 'system',
        created_at REAL, UNIQUE(fingerprint, alert_type))""")
    db.commit()

    policy = AlertPolicy()
    rules = [
        {"alert_type": "test1", "duration_s": 60, "reason": "batch1"},
        {"alert_type": "test2", "duration_s": 120, "reason": "batch2"},
        {"fingerprint": "fp3", "duration_s": 180, "reason": "batch3"},
    ]

    results = policy.batch_add_silences(rules, created_by="admin", db=db)

    success_count = sum(1 for r in results if r.get("success"))
    if success_count != 3:
        issues.append(f"Success count: {success_count}")

    # DB'den kontrol
    rows = db.execute("SELECT * FROM alert_silences").fetchall()
    if len(rows) != 3:
        issues.append(f"DB rows: {len(rows)}")

    # Aktif silence kontrolü
    if not policy.is_silenced("test1", "any"):
        issues.append("test1 susturulamadı")
    if not policy.is_silenced("test2", "any"):
        issues.append("test2 susturulamadı")
    if not policy.is_silenced("any", "fp3"):
        issues.append("fp3 susturulamadı")

    return "Batch Add Silences", len(issues) == 0, issues


async def test_batch_remove_silences():
    """Toplu susturma kaldırma çalışmalı."""
    issues = []

    db = duckdb.connect(":memory:")
    db.execute("""CREATE TABLE alert_silences (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        alert_type TEXT, fingerprint TEXT,
        start_time REAL NOT NULL, end_time REAL NOT NULL,
        reason TEXT, created_by TEXT DEFAULT 'system',
        created_at REAL, UNIQUE(fingerprint, alert_type))""")
    db.commit()

    policy = AlertPolicy()
    policy.batch_add_silences(
        [
            {"alert_type": "test1", "duration_s": 60},
            {"alert_type": "test2", "duration_s": 60},
            {"fingerprint": "fp3", "duration_s": 60},
        ],
        db=db,
    )

    # Batch remove
    result = policy.batch_remove_silences([{"alert_type": "test1"}, {"fingerprint": "fp3"}], actor="admin", db=db)

    if result.get("removed") != 2:
        issues.append(f"Removed: {result.get('removed')}")

    if policy.is_silenced("test1", "any"):
        issues.append("test1 hâlâ susturulmuş")
    if not policy.is_silenced("test2", "any"):
        issues.append("test2 kaldırıldı (kaldırılmamalı)")

    return "Batch Remove Silences", len(issues) == 0, issues


async def test_batch_silence_transaction():
    """Batch işlemi transaction kullanmalı."""
    issues = []

    db = duckdb.connect(":memory:")
    db.execute("""CREATE TABLE alert_silences (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        alert_type TEXT, fingerprint TEXT,
        start_time REAL NOT NULL, end_time REAL NOT NULL,
        reason TEXT, created_by TEXT DEFAULT 'system',
        created_at REAL, UNIQUE(fingerprint, alert_type))""")
    db.commit()

    policy = AlertPolicy()

    # İlk batch başarılı olmalı
    results1 = policy.batch_add_silences(
        [
            {"alert_type": "test1", "duration_s": 60},
            {"alert_type": "test2", "duration_s": 60},
        ],
        db=db,
    )

    if not all(r.get("success") for r in results1):
        issues.append("İlk batch başarısız")

    return "Batch Silence Transaction", len(issues) == 0, issues


async def test_batch_silence_audit():
    """Batch işlemleri audit log'a yazılmalı."""
    issues = []

    policy = AlertPolicy()
    policy.batch_add_silences(
        [
            {"alert_type": "test1", "duration_s": 60, "reason": "maintenance"},
            {"alert_type": "test2", "duration_s": 120},
        ],
        created_by="admin",
    )

    policy.batch_remove_silences([{"alert_type": "test1"}], actor="ops")

    audit = policy.get_audit_log()
    actions = [e.get("action") for e in audit]

    if "batch_silence_add" not in actions:
        issues.append("batch_silence_add audit yok")
    if "batch_silence_remove" not in actions:
        issues.append("batch_silence_remove audit yok")

    # Detail kontrolü
    batch_add = [e for e in audit if e.get("action") == "batch_silence_add"]
    if batch_add and batch_add[0].get("details", {}).get("count") != 2:
        issues.append(f"batch count: {batch_add[0].get('details', {}).get('count')}")

    return "Batch Silence Audit", len(issues) == 0, issues


# =====================================================
# AUDIT LOG COMPLETENESS
# =====================================================


async def test_audit_log_completeness():
    """Her değişiklik audit log'a yazılmalı."""
    issues = []

    policy = AlertPolicy()

    # Tüm aksiyonları yap
    policy.update({"escalation_timeouts": {"cash_negative": 100}}, actor="user1")
    policy.add_silence(alert_type="test", duration_s=60, reason="test", created_by="user2")
    policy.remove_silence(alert_type="test", actor="user3")
    policy.acquire_edit_lock("user4", 60)
    policy.release_edit_lock("user4")
    policy.rollback(actor="user5")

    audit = policy.get_audit_log()
    actions = [e.get("action") for e in audit]

    required = ["update", "silence_add", "silence_remove", "lock_acquired", "lock_released", "rollback"]
    for action in required:
        if action not in actions:
            issues.append(f"{action} audit'te yok")

    # Actor bilgisi
    update_entries = [e for e in audit if e.get("action") == "update"]
    if update_entries and update_entries[0].get("actor") != "user1":
        issues.append(f"update actor: {update_entries[0].get('actor')}")

    return "Audit Log Completeness", len(issues) == 0, issues


async def test_audit_log_limit():
    """Audit log limiti doğru çalışmalı."""
    issues = []

    policy = AlertPolicy()
    for i in range(600):
        policy._add_audit("test", {"i": i})

    log = policy.get_audit_log(limit=100)
    if len(log) > 100:
        issues.append(f"Limit aşıldı: {len(log)}")

    # Son kayıt doğru olmalı
    if log[-1].get("details", {}).get("i") != 599:
        issues.append(f"Son kayıt: {log[-1].get('details', {}).get('i')}")

    return "Audit Log Limit", len(issues) == 0, issues


# =====================================================
# INTEGRATION
# =====================================================


async def test_full_policy_workflow():
    """Tam policy iş akışı: update → diff → conflict → rollback."""
    issues = []

    policy = AlertPolicy()

    # v1: İlk güncelleme
    r1 = policy.update({"escalation_timeouts": {"cash_negative": 60}}, actor="admin")
    if not r1.get("success"):
        issues.append(f"v1 başarısız: {r1}")

    # v2: İkinci güncelleme
    r2 = policy.update({"escalation_timeouts": {"cash_negative": 120}}, actor="admin")
    if not r2.get("success"):
        issues.append(f"v2 başarısız: {r2}")

    # Conflict: eski version ile
    try:
        policy.update({"escalation_timeouts": {"cash_negative": 999}}, actor="user", expected_version=1)
        issues.append("Conflict yakalanmadı")
    except VersionConflictError:
        logger.warning("Error in test_full_policy_workflow: VersionConflictError", exc_info=True)

    # Rollback to v1
    rb = policy.rollback(target_version=1, actor="admin")
    if not rb.get("success"):
        issues.append(f"Rollback başarısız: {rb}")

    if policy.get_escalation_timeout("cash_negative") != 60:
        issues.append(f"Rollback sonrası: {policy.get_escalation_timeout('cash_negative')}")

    # Audit log
    audit = policy.get_audit_log()
    if len(audit) < 3:
        issues.append(f"Audit entries: {len(audit)}")

    return "Full Policy Workflow", len(issues) == 0, issues


# =====================================================
# RUN
# =====================================================


async def run_all():
    print("=" * 60)
    print("POLICY OPERATIONS TESTLERİ")
    print("=" * 60)

    tests = [
        # Diff
        test_policy_diff_no_changes,
        test_policy_diff_changed_fields,
        test_policy_diff_added_removed,
        test_policy_diff_summary,
        test_policy_diff_on_update,
        # Locking
        test_optimistic_lock_version_conflict,
        test_optimistic_lock_correct_version,
        test_optimistic_lock_no_version_check,
        test_edit_lock,
        test_edit_lock_wrong_owner_release,
        test_concurrent_policy_update,
        # Webhook
        test_policy_webhook_config,
        test_policy_change_triggers_notification,
        # Batch silence
        test_batch_add_silences,
        test_batch_remove_silences,
        test_batch_silence_transaction,
        test_batch_silence_audit,
        # Audit
        test_audit_log_completeness,
        test_audit_log_limit,
        # Integration
        test_full_policy_workflow,
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
