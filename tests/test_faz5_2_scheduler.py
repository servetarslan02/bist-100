"""
ALPHA BIST — FAZ 5.2 Test Suite (v2.0 — Unified Scheduler)

Market Session + Worker + Unified Scheduler + Idempotency
"""

import sys
import os
import asyncio
import time



# ────────────────────────────────────────────────────────────
# 1. Market session — timezone
# ────────────────────────────────────────────────────────────

def test_market_session_timezone():
    """Market session Istanbul timezone kullanmalı."""
    from services.scheduler.unified_scheduler import MarketSessionManager, _TZ_ISTANBUL

    passed = 0
    failed = 0

    market = MarketSessionManager()
    now = market.now_istanbul()
    assert now.tzinfo is not None
    assert now.utcoffset().total_seconds() == 3 * 3600  # UTC+3
    print(f"  ✓ Timezone: {now.isoformat()} (UTC+3)")
    passed += 1

    return passed, failed


# ────────────────────────────────────────────────────────────
# 2. Market session — weekend detection
# ────────────────────────────────────────────────────────────

def test_market_session_weekend():
    """Hafta sonu piyasa kapalı olmalı."""
    from services.scheduler.unified_scheduler import MarketSessionManager, MarketPhase
    from datetime import datetime, timezone, timedelta

    passed = 0
    failed = 0

    IST = timezone(timedelta(hours=3))

    class FakeSaturday(MarketSessionManager):
        def now_istanbul(self):
            return datetime(2026, 8, 22, 12, 0, tzinfo=IST)

    mgr = FakeSaturday()
    assert mgr.current_phase() == MarketPhase.CLOSED
    assert not mgr.is_trading_hours()
    print("  ✓ Saturday: CLOSED")
    passed += 1

    class FakeSunday(MarketSessionManager):
        def now_istanbul(self):
            return datetime(2026, 8, 23, 14, 0, tzinfo=IST)

    mgr2 = FakeSunday()
    assert mgr2.current_phase() == MarketPhase.CLOSED
    print("  ✓ Sunday: CLOSED")
    passed += 1

    return passed, failed


# ────────────────────────────────────────────────────────────
# 3. Market session — holiday detection
# ────────────────────────────────────────────────────────────

def test_market_session_holiday():
    """Tatil günlerinde piyasa kapalı olmalı."""
    from services.scheduler.unified_scheduler import MarketSessionManager, MarketPhase
    from datetime import datetime, timezone, timedelta

    passed = 0
    failed = 0

    IST = timezone(timedelta(hours=3))

    class FakeHoliday(MarketSessionManager):
        def now_istanbul(self):
            return datetime(2026, 1, 1, 14, 0, tzinfo=IST)

    mgr = FakeHoliday()
    assert mgr.current_phase() == MarketPhase.CLOSED
    print("  ✓ Holiday (2026-01-01): CLOSED")
    passed += 1

    return passed, failed


# ────────────────────────────────────────────────────────────
# 4. Market session — market open/close phases
# ────────────────────────────────────────────────────────────

def test_market_session_phases():
    """Market phase'leri doğru ayrılmalı."""
    from services.scheduler.unified_scheduler import MarketSessionManager, MarketPhase
    from datetime import datetime, timezone, timedelta

    passed = 0
    failed = 0

    IST = timezone(timedelta(hours=3))

    class Fake(MarketSessionManager):
        def __init__(self, dt):
            super().__init__()
            self._dt = dt
        def now_istanbul(self):
            return self._dt

    # 09:30 → NIGHT (piyasa kapalı, 09:40'tan önce)
    m = Fake(datetime(2026, 8, 18, 9, 30, tzinfo=IST))
    assert m.current_phase() == MarketPhase.NIGHT
    assert not m.is_trading_hours()
    print("  ✓ 09:30: NIGHT (piyasa kapalı)")
    passed += 1

    # 09:45 → PRE_MARKET
    m = Fake(datetime(2026, 8, 18, 9, 45, tzinfo=IST))
    assert m.current_phase() == MarketPhase.PRE_MARKET
    print("  ✓ 09:45: PRE_MARKET")
    passed += 1

    # 10:30 → SEANS_1
    m = Fake(datetime(2026, 8, 18, 10, 30, tzinfo=IST))
    assert m.current_phase() == MarketPhase.SEANS_1
    assert m.is_trading_hours()
    print("  ✓ 10:30: SEANS_1 (trading hours)")
    passed += 1

    # 13:00 → BREAK
    m = Fake(datetime(2026, 8, 18, 13, 0, tzinfo=IST))
    assert m.current_phase() == MarketPhase.BREAK
    print("  ✓ 13:00: BREAK")
    passed += 1

    # 15:00 → SEANS_2
    m = Fake(datetime(2026, 8, 18, 15, 0, tzinfo=IST))
    assert m.current_phase() == MarketPhase.SEANS_2
    assert m.is_trading_hours()
    print("  ✓ 15:00: SEANS_2 (trading hours)")
    passed += 1

    # 17:50 → CLOSING
    m = Fake(datetime(2026, 8, 18, 17, 50, tzinfo=IST))
    assert m.current_phase() == MarketPhase.CLOSING
    print("  ✓ 17:50: CLOSING")
    passed += 1

    # 18:15 → POST_MARKET
    m = Fake(datetime(2026, 8, 18, 18, 15, tzinfo=IST))
    assert m.current_phase() == MarketPhase.POST_MARKET
    print("  ✓ 18:15: POST_MARKET")
    passed += 1

    # 20:00 → AFTER_HOURS
    m = Fake(datetime(2026, 8, 18, 20, 0, tzinfo=IST))
    assert m.current_phase() == MarketPhase.AFTER_HOURS
    print("  ✓ 20:00: AFTER_HOURS")
    passed += 1

    # 23:30 → NIGHT
    m = Fake(datetime(2026, 8, 18, 23, 30, tzinfo=IST))
    assert m.current_phase() == MarketPhase.NIGHT
    print("  ✓ 23:30: NIGHT")
    passed += 1

    return passed, failed


# ────────────────────────────────────────────────────────────
# 5. Unified Scheduler — handler registration
# ────────────────────────────────────────────────────────────

def test_scheduler_handler_registration():
    """Scheduler handler kaydı yapabilmeli."""
    from services.scheduler.unified_scheduler import UnifiedScheduler

    passed = 0
    failed = 0

    scheduler = UnifiedScheduler()

    async def my_handler():
        return "ok"

    scheduler.register_handler("test_job", my_handler)
    assert "test_job" in scheduler._handlers

    print("  ✓ Scheduler handler registration: OK")
    passed += 1

    return passed, failed


# ────────────────────────────────────────────────────────────
# 6. Unified Scheduler — market closed skips trading jobs
# ────────────────────────────────────────────────────────────

def test_scheduler_market_closed():
    """Market kapalıyken trading job'ları çalışmamalı."""
    from services.scheduler.unified_scheduler import MarketSessionManager, MarketPhase
    from datetime import datetime, timezone, timedelta

    passed = 0
    failed = 0

    IST = timezone(timedelta(hours=3))

    class FakeWeekend(MarketSessionManager):
        def now_istanbul(self):
            return datetime(2026, 8, 22, 14, 0, tzinfo=IST)  # Cumartesi

    mgr = FakeWeekend()
    assert not mgr.should_run_trading_job()
    print("  ✓ Weekend: trading jobs blocked")
    passed += 1

    class FakeActive(MarketSessionManager):
        def now_istanbul(self):
            return datetime(2026, 8, 18, 14, 0, tzinfo=IST)  # Salı 14:00

    mgr2 = FakeActive()
    assert mgr2.should_run_trading_job()
    print("  ✓ Active hours: trading jobs allowed")
    passed += 1

    return passed, failed


# ────────────────────────────────────────────────────────────
# 7. Unified Scheduler — priority ordering
# ────────────────────────────────────────────────────────────

def test_priority_ordering():
    """Priority'ye göre job sıralaması doğru olmalı."""
    from services.scheduler.unified_scheduler import UnifiedScheduler

    passed = 0
    failed = 0

    scheduler = UnifiedScheduler()
    configs = scheduler._configs
    sorted_jobs = sorted(configs.items(), key=lambda x: x[1].priority)

    # İlk job en yüksek önceliğe sahip
    assert sorted_jobs[0][1].priority == 1
    # Son job en düşük önceliğe sahip
    assert sorted_jobs[-1][1].priority == 10

    print(f"  ✓ Priority ordering: {sorted_jobs[0][0]} (p=1) → {sorted_jobs[-1][0]} (p=10)")
    passed += 1

    return passed, failed


# ────────────────────────────────────────────────────────────
# 8. Unified Scheduler — trigger
# ────────────────────────────────────────────────────────────

def test_trigger_job():
    """Manuel tetikleme çalışmalı."""
    from services.scheduler.unified_scheduler import UnifiedScheduler, JobConfig

    passed = 0
    failed = 0

    scheduler = UnifiedScheduler()

    # Handler yok → ERROR
    result = asyncio.run(scheduler.trigger_job("nonexistent"))
    assert result["status"] == "ERROR"
    print("  ✓ Trigger without handler: ERROR")
    passed += 1

    # Handler var → QUEUED
    async def dummy():
        return "ok"

    scheduler.register_handler("test_trigger", dummy)
    scheduler._configs["test_trigger"] = JobConfig(
        job_type="test_trigger", interval_seconds=60
    )
    result = asyncio.run(scheduler.trigger_job("test_trigger"))
    assert result["status"] == "QUEUED"
    print("  ✓ Trigger with handler: QUEUED")
    passed += 1

    return passed, failed


# ────────────────────────────────────────────────────────────
# 9. Holiday Provider — dynamic
# ────────────────────────────────────────────────────────────

def test_holiday_provider():
    """Tatil takvimi dinamik olmalı."""
    from services.scheduler.unified_scheduler import HolidayProvider
    from datetime import date, datetime, timezone, timedelta

    passed = 0
    failed = 0

    provider = HolidayProvider()

    # Fallback tatilleri yüklenmeli
    holidays = provider.get_holidays()
    assert len(holidays) >= 14
    print(f"  ✓ Fallback holidays: {len(holidays)}")
    passed += 1

    # Runtime ekleme
    provider.add_holiday(date(2026, 12, 31))
    dt = datetime(2026, 12, 31, 14, 0, tzinfo=timezone(timedelta(hours=3)))
    assert provider.is_holiday(dt) is True
    print("  ✓ Runtime add_holiday: OK")
    passed += 1

    # Runtime kaldırma
    provider.remove_holiday(date(2026, 12, 31))
    assert provider.is_holiday(dt) is False
    print("  ✓ Runtime remove_holiday: OK")
    passed += 1

    return passed, failed


# ────────────────────────────────────────────────────────────
# 10. DB Job Tracker — memory fallback
# ────────────────────────────────────────────────────────────

def test_db_job_tracker():
    """DB yoksa memory fallback çalışmalı."""
    from services.scheduler.unified_scheduler import DBJobTracker, JobResult
    from datetime import datetime, timezone

    passed = 0
    failed = 0

    tracker = DBJobTracker()

    result = JobResult(
        job_type="test", status="SUCCESS",
        duration_ms=100.0, timestamp=datetime.now(timezone.utc).isoformat()
    )
    success = asyncio.run(tracker.record_job(result))
    assert success is True
    assert len(tracker._memory_history) == 1
    print("  ✓ DB tracker memory fallback: OK")
    passed += 1

    # History
    history = asyncio.run(tracker.get_job_history())
    assert len(history) == 1
    print("  ✓ DB tracker get_job_history: OK")
    passed += 1

    return passed, failed


# ────────────────────────────────────────────────────────────
# 11. Worker — job execution
# ────────────────────────────────────────────────────────────

def test_worker_job_execution():
    """Worker job çalıştırabilmeli."""
    from services.core.worker import JobWorker

    passed = 0
    failed = 0

    worker = JobWorker(worker_id="test-w1")
    result_holder = {}

    async def handler(**kwargs):
        result_holder["executed"] = True
        result_holder["kwargs"] = kwargs
        return {"status": "ok"}

    async def run():
        job_id = await worker.submit_job(
            job_type="test_job",
            handler=handler,
            payload={"ticker": "THYAO"},
            idempotency_key="test_key_1",
        )
        await asyncio.sleep(0.05)
        return job_id

    loop = asyncio.new_event_loop()
    try:
        job_id = loop.run_until_complete(run())
        print(f"  ✓ Worker job: job_id={job_id}, executed={result_holder.get('executed', False)}")
        passed += 1
    finally:
        loop.close()

    return passed, failed


# ────────────────────────────────────────────────────────────
# 12. Worker — idempotency
# ────────────────────────────────────────────────────────────

def test_idempotency_key_generation():
    """Aynı payload aynı key üretmeli."""
    from services.core.worker import JobWorker

    passed = 0
    failed = 0

    w = JobWorker()
    k1 = w._generate_idempotency_key("test", {"a": 1, "b": 2})
    k2 = w._generate_idempotency_key("test", {"b": 2, "a": 1})
    k3 = w._generate_idempotency_key("test", {"a": 1, "b": 3})

    assert k1 == k2, "Same payload should produce same key regardless of order"
    assert k1 != k3, "Different payload should produce different key"
    assert len(k1) == 32

    print(f"  ✓ Idempotency key: deterministic, order-independent")
    passed += 1

    return passed, failed


# ────────────────────────────────────────────────────────────
# Ana çalıştırıcı
# ────────────────────────────────────────────────────────────

def run_all():
    tests = [
        ("Market session timezone", test_market_session_timezone),
        ("Weekend detection", test_market_session_weekend),
        ("Holiday detection", test_market_session_holiday),
        ("Market phases", test_market_session_phases),
        ("Scheduler handler registration", test_scheduler_handler_registration),
        ("Market closed blocks trading", test_scheduler_market_closed),
        ("Priority ordering", test_priority_ordering),
        ("Trigger job", test_trigger_job),
        ("Holiday provider", test_holiday_provider),
        ("DB Job tracker", test_db_job_tracker),
        ("Worker job execution", test_worker_job_execution),
        ("Idempotency key", test_idempotency_key_generation),
    ]

    total_passed = 0
    total_failed = 0

    print("=" * 70)
    print("FAZ 5.2 — Unified Scheduler + Market Session + Worker")
    print("=" * 70)

    for name, test_fn in tests:
        print(f"\n▸ {name}")
        try:
            p, f = test_fn()
            total_passed += p
            total_failed += f
            if f > 0:
                print(f"  ⚠ {f} FAILED")
        except Exception as e:
            import traceback
            print(f"  ✗ EXCEPTION: {e}")
            traceback.print_exc()
            total_failed += 1

    print("\n" + "=" * 70)
    print(f"SONUÇ: {total_passed} passed, {total_failed} failed")
    print("=" * 70)

    return total_failed == 0


if __name__ == "__main__":
    success = run_all()
    sys.exit(0 if success else 1)
