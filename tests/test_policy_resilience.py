#!/usr/bin/env python3
"""
Policy Resilience Testleri

Kapsam:
- Lock auto-release (expired lock recovery)
- Parallel policy edit scenarios
- Three-way diff
- Webhook mock server + failure/retry
- Batch silence size limit
- Transaction rollback
"""

import sys
import os
import orjson
import asyncio
import sqlite3
import time
from aiohttp import web
import aiohttp

from services.core.alert_policy import (
    AlertPolicy, PolicyDiff, VersionConflictError,
    MAX_BATCH_SILENCE_SIZE, WEBHOOK_RETRY_COUNT,
)


# =====================================================
# MOCK WEBHOOK SERVER
# =====================================================

class MockWebhookServer:
    """Test amaçlı mock HTTP server."""

    def __init__(self, port: int = 18923):
        self.port = port
        self.received: list = []
        self.fail_until_attempt: int = 0  # Kaçıncı denemeye kadar başarısız
        self._attempt_count: int = 0
        self._runner = None
        self._site = None

    async def start(self):
        app = web.Application()
        app.router.add_post("/webhook", self._handler)
        self._runner = web.AppRunner(app)
        await self._runner.setup()
        self._site = web.TCPSite(self._runner, "localhost", self.port)
        await self._site.start()

    async def stop(self):
        if self._site:
            await self._site.stop()
        if self._runner:
            await self._runner.cleanup()

    async def _handler(self, request):
        self._attempt_count += 1
        body = await request.json()
        self.received.append({"attempt": self._attempt_count, "body": body})

        if self._attempt_count <= self.fail_until_attempt:
            return web.Response(status=500, text="Internal Server Error")
        return web.Response(status=200, text="OK")

    @property
    def url(self):
        return f"http://localhost:{self.port}/webhook"


# =====================================================
# LOCK AUTO-RELEASE TESTS
# =====================================================

async def test_lock_auto_release_expired():
    """Süresi dolmuş kilit otomatik temizlenmeli."""
    issues = []

    policy = AlertPolicy()

    # user1 kilit al (kısa süre)
    policy.acquire_edit_lock("user1", timeout_s=0.1)
    if not policy.is_locked():
        issues.append("Lock alınamadı")

    # Süre dolsun
    await asyncio.sleep(0.15)

    # user2 kilit alabilmeli (eski kilit otomatik temizlenmeli)
    acquired = policy.acquire_edit_lock("user2", timeout_s=60)
    if not acquired:
        issues.append("user2 lock alamadı (expired lock temizlenmedi)")

    if policy._lock_owner != "user2":
        issues.append(f"Lock owner: {policy._lock_owner}")

    # Audit log'da recovery kaydı olmalı
    audit = policy.get_audit_log()
    recovery = [e for e in audit if e.get("action") == "lock_expired_recovery"]
    if not recovery:
        issues.append("lock_expired_recovery audit yok")

    policy.release_edit_lock("user2")
    return "Lock Auto-Release Expired", len(issues) == 0, issues


async def test_lock_auto_release_audit_details():
    """Lock recovery audit kaydetmeli."""
    issues = []

    policy = AlertPolicy()
    policy.acquire_edit_lock("admin", timeout_s=0.1)
    await asyncio.sleep(0.15)
    policy.acquire_edit_lock("user", timeout_s=60)

    audit = policy.get_audit_log()
    recovery = [e for e in audit if e.get("action") == "lock_expired_recovery"]

    if recovery:
        details = recovery[0].get("details", {})
        if details.get("old_owner") != "admin":
            issues.append(f"old_owner: {details.get('old_owner')}")
        if details.get("new_owner") != "user":
            issues.append(f"new_owner: {details.get('new_owner')}")
    else:
        issues.append("Recovery audit yok")

    policy.release_edit_lock("user")
    return "Lock Recovery Audit", len(issues) == 0, issues


async def test_lock_not_released_if_active():
    """Aktif kilit otomatik temizlenmemeli."""
    issues = []

    policy = AlertPolicy()
    policy.acquire_edit_lock("user1", timeout_s=60)

    # user2 alamamalı
    acquired = policy.acquire_edit_lock("user2", timeout_s=60)
    if acquired:
        issues.append("Aktif lock otomatik temizlendi")

    policy.release_edit_lock("user1")
    return "Lock Not Released If Active", len(issues) == 0, issues


# =====================================================
# PARALLEL POLICY EDIT TESTS
# =====================================================

async def test_parallel_edits_version_conflict():
    """Paralel düzenlemeler version conflict üretmeli."""
    issues = []

    policy = AlertPolicy()
    policy._version = 1

    # User1 okur (v1)
    # User2 okur (v1)
    # User1 yazar (v1→v2)
    r1 = policy.update({"escalation_timeouts": {"cash_negative": 100}},
                       actor="user1", expected_version=1)
    if not r1.get("success"):
        issues.append(f"user1 başarısız: {r1}")

    # User2 eski version ile yazar → conflict
    try:
        policy.update({"escalation_timeouts": {"cash_negative": 200}},
                      actor="user2", expected_version=1)
        issues.append("Conflict yakalanmadı")
    except VersionConflictError:
        pass

    # Değer user1'in olmalı
    if policy.get_escalation_timeout("cash_negative") != 100:
        issues.append(f"Değer: {policy.get_escalation_timeout('cash_negative')}")

    return "Parallel Edits Version Conflict", len(issues) == 0, issues


async def test_parallel_edits_with_lock():
    """Lock ile paralel düzenleme engellenmeli."""
    issues = []

    policy = AlertPolicy()

    # User1 lock alır
    policy.acquire_edit_lock("user1", timeout_s=60)

    # User2 update denemez (lock var)
    if policy.is_locked():
        # User2 lock'ı zorlayamamalı
        acquired = policy.acquire_edit_lock("user2", timeout_s=60)
        if acquired:
            issues.append("Lock bypass edildi")
    else:
        issues.append("Lock algılanamadı")

    policy.release_edit_lock("user1")
    return "Parallel Edits With Lock", len(issues) == 0, issues


async def test_parallel_edits_after_lock_release():
    """Lock bırakıldıktan sonra düzenleme yapılabilmeli."""
    issues = []

    policy = AlertPolicy()
    policy.acquire_edit_lock("user1", timeout_s=60)
    policy.release_edit_lock("user1")

    r = policy.update({"escalation_timeouts": {"cash_negative": 42}}, actor="user2")
    if not r.get("success"):
        issues.append(f"Update başarısız: {r}")

    return "Parallel Edits After Lock Release", len(issues) == 0, issues


# =====================================================
# THREE-WAY DIFF TESTS
# =====================================================

async def test_three_way_diff_no_conflict():
    """Üçlü diff: farklı alanlarda değişiklik conflict olmamalı."""
    issues = []

    policy = AlertPolicy()

    # v1: base
    policy.update({"escalation_timeouts": {"cash_negative": 60}}, actor="v1")
    # v2: sadece escalation_timeouts değişti
    policy.update({"escalation_timeouts": {"cash_negative": 120}}, actor="v2")
    # v3: sadece notification_routing değişti (farklı alan)
    policy.update({
        "escalation_timeouts": {"cash_negative": 60},
        "notification_routing": {"CRITICAL": ["log", "webhook", "slack"]}
    }, actor="v3")

    result = policy.three_way_diff(base_version=1, version_a=2, version_b=3)

    a_only = result.get("a_only", {})
    b_only = result.get("b_only", {})

    # escalation_timeouts sadece A'da değişti
    if "escalation_timeouts" not in a_only:
        issues.append(f"a_only: {list(a_only.keys())} (escalation_timeouts eksik)")

    # notification_routing sadece B'de değişti
    if "notification_routing" not in b_only:
        issues.append(f"b_only: {list(b_only.keys())} (notification_routing eksik)")

    # Conflict olmamalı (farklı alanlar)
    if result.get("has_conflicts"):
        issues.append(f"Conflict var (olmamalı): {result.get('both_changed')}")

    return "Three-Way Diff No Conflict", len(issues) == 0, issues


async def test_three_way_diff_with_conflict():
    """Üçlü diff: conflict varsa tespit etmeli."""
    issues = []

    policy = AlertPolicy()

    # v1: base
    policy.update({"escalation_timeouts": {"cash_negative": 60}}, actor="v1")
    # v2: cash_negative = 120
    policy.update({"escalation_timeouts": {"cash_negative": 120}}, actor="v2")
    # v3: cash_negative = 999 (farklı değer)
    policy.update({"escalation_timeouts": {"cash_negative": 999}}, actor="v3")

    result = policy.three_way_diff(base_version=1, version_a=2, version_b=3)

    if not result.get("has_conflicts"):
        issues.append("Conflict tespit edilemedi")

    conflicts = result.get("both_changed", {})
    if "escalation_timeouts" not in conflicts:
        issues.append(f"conflict_fields: {list(conflicts.keys())}")

    conflict_val = conflicts.get("escalation_timeouts", {})
    if isinstance(conflict_val, dict):
        a_val = conflict_val.get("a")
        if isinstance(a_val, dict):
            if a_val.get("cash_negative") != 120:
                issues.append(f"a value: {a_val}")
        elif a_val != 120:
            issues.append(f"a value: {a_val}")

    return "Three-Way Diff With Conflict", len(issues) == 0, issues


async def test_three_way_diff_version_not_found():
    """Olmayan versiyon hata döndürmeli."""
    issues = []

    policy = AlertPolicy()
    policy.update({"escalation_timeouts": {"cash_negative": 60}}, actor="v1")

    result = policy.three_way_diff(base_version=1, version_a=99, version_b=1)
    if "error" not in result:
        issues.append("Error dönmeli")

    return "Three-Way Diff Version Not Found", len(issues) == 0, issues


async def test_three_way_diff_identical_changes():
    """Her iki versiyonda aynı değişiklik conflict olmamalı."""
    issues = []

    policy = AlertPolicy()
    policy.update({"escalation_timeouts": {"cash_negative": 60}}, actor="v1")
    policy.update({"escalation_timeouts": {"cash_negative": 120}}, actor="v2")
    policy.update({"escalation_timeouts": {"cash_negative": 120}}, actor="v3")

    result = policy.three_way_diff(base_version=1, version_a=2, version_b=3)

    if result.get("has_conflicts"):
        issues.append(f"Conflict var (olmamalı): {result.get('both_changed')}")

    if "escalation_timeouts" not in result.get("identical", []):
        issues.append(f"identical: {result.get('identical')}")

    return "Three-Way Identical Changes", len(issues) == 0, issues


# =====================================================
# WEBHOOK TESTS
# =====================================================

async def test_webhook_success():
    """Başarlı webhook gönderimi."""
    issues = []

    server = MockWebhookServer()
    await server.start()

    try:
        policy = AlertPolicy()
        policy.set_webhook_urls([server.url])
        policy.update({"escalation_timeouts": {"cash_negative": 42}}, actor="test")

        await asyncio.sleep(1.5)  # Webhook async

        if len(server.received) == 0:
            issues.append("Webhook çağrılmadı")
        elif server.received[0]["body"].get("event") != "policy_change":
            issues.append(f"Event: {server.received[0]['body'].get('event')}")
    finally:
        await server.stop()

    return "Webhook Success", len(issues) == 0, issues


async def test_webhook_failure_retry():
    """Başarısız webhook retry yapmalı."""
    issues = []

    server = MockWebhookServer()
    server.fail_until_attempt = 2  # İlk 2 deneme başarısız
    await server.start()

    try:
        policy = AlertPolicy()
        policy.set_webhook_urls([server.url])
        policy.update({"escalation_timeouts": {"cash_negative": 42}}, actor="test")

        await asyncio.sleep(5)  # Retry'lar için bekle

        if server._attempt_count < 3:
            issues.append(f"Attempt count: {server._attempt_count} (beklenen: >=3)")

        # Son deneme başarılı olmalı
        if len(server.received) == 0:
            issues.append("Hiç webhook ulaşmadı")
    finally:
        await server.stop()

    return "Webhook Failure Retry", len(issues) == 0, issues


async def test_webhook_failure_audit():
    """Başarısız webhook audit log'a yazılmalı."""
    issues = []

    # Var olmayan URL
    policy = AlertPolicy()
    policy.set_webhook_urls(["http://localhost:1/nonexistent"])
    policy.update({"escalation_timeouts": {"cash_negative": 42}}, actor="test")

    await asyncio.sleep(5)  # Retry'lar için bekle

    audit = policy.get_audit_log()
    failed = [e for e in audit if e.get("action") == "webhook_failed"]
    if not failed:
        issues.append("webhook_failed audit yok")

    return "Webhook Failure Audit", len(issues) == 0, issues


# =====================================================
# BATCH SILENCE LIMIT TESTS
# =====================================================

async def test_batch_within_limit():
    """Limit dahilinde batch başarılı olmalı."""
    issues = []

    policy = AlertPolicy()
    rules = [{"alert_type": f"test_{i}", "duration_s": 60} for i in range(50)]
    results = policy.batch_add_silences(rules, created_by="test")

    success = sum(1 for r in results if r.get("success"))
    if success != 50:
        issues.append(f"Success: {success}")

    return "Batch Within Limit", len(issues) == 0, issues


async def test_batch_exceeds_limit():
    """Limit aşan batch hata döndürmeli."""
    issues = []

    policy = AlertPolicy()
    rules = [{"alert_type": f"test_{i}", "duration_s": 60} for i in range(MAX_BATCH_SILENCE_SIZE + 1)]
    results = policy.batch_add_silences(rules, created_by="test")

    if results and results[0].get("success"):
        issues.append("Limit aşıldı ama başarılı oldu")

    if results and "exceeds limit" not in results[0].get("error", ""):
        issues.append(f"Error: {results[0].get('error')}")

    return "Batch Exceeds Limit", len(issues) == 0, issues


async def test_batch_exactly_at_limit():
    """Tam limitte batch başarılı olmalı."""
    issues = []

    policy = AlertPolicy()
    rules = [{"alert_type": f"test_{i}", "duration_s": 60} for i in range(MAX_BATCH_SILENCE_SIZE)]
    results = policy.batch_add_silences(rules, created_by="test")

    success = sum(1 for r in results if r.get("success"))
    if success != MAX_BATCH_SILENCE_SIZE:
        issues.append(f"Success: {success} (beklenen: {MAX_BATCH_SILENCE_SIZE})")

    return "Batch Exactly At Limit", len(issues) == 0, issues


async def test_batch_transaction_rollback():
    """DB hatası transaction rollback yapmalı."""
    issues = []

    # Hatalı DB (commit çalışmasın)
    class BrokenDB:
        def execute(self, *args): pass
        def commit(self): raise sqlite3.OperationalError("disk full")
        def rollback(self): pass

    policy = AlertPolicy()
    results = policy.batch_add_silences([
        {"alert_type": "test1", "duration_s": 60},
        {"alert_type": "test2", "duration_s": 60},
    ], db=BrokenDB())

    success = sum(1 for r in results if r.get("success"))
    if success != 0:
        issues.append(f"Success: {success} (beklenen: 0, rollback)")

    # In-memory de geri alınmalı
    if len(policy.silence_rules) != 0:
        issues.append(f"Silence rules: {len(policy.silence_rules)} (beklenen: 0)")

    return "Batch Transaction Rollback", len(issues) == 0, issues


# =====================================================
# RUN
# =====================================================

async def run_all():
    print("=" * 60)
    print("POLICY RESILIENCE TESTLERİ")
    print("=" * 60)

    tests = [
        # Lock auto-release
        test_lock_auto_release_expired,
        test_lock_auto_release_audit_details,
        test_lock_not_released_if_active,
        # Parallel edits
        test_parallel_edits_version_conflict,
        test_parallel_edits_with_lock,
        test_parallel_edits_after_lock_release,
        # Three-way diff
        test_three_way_diff_no_conflict,
        test_three_way_diff_with_conflict,
        test_three_way_diff_version_not_found,
        test_three_way_diff_identical_changes,
        # Webhook
        test_webhook_success,
        test_webhook_failure_retry,
        test_webhook_failure_audit,
        # Batch limits
        test_batch_within_limit,
        test_batch_exceeds_limit,
        test_batch_exactly_at_limit,
        test_batch_transaction_rollback,
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
