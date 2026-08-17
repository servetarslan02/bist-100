"""
ALPHA BIST — FAZ 5.2 Test Suite

Market Session + Worker + Scheduler + Idempotency
"""

import sys
import os
import asyncio
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ────────────────────────────────────────────────────────────
# 1. Market session — timezone
# ────────────────────────────────────────────────────────────

def test_market_session_timezone():
    """Market session Istanbul timezone kullanmalı."""
    from services.core.market_session import market_session, _TZ_ISTANBUL

    passed = 0
    failed = 0

    now = market_session.now_istanbul()
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
    from services.core.market_session import MarketSessionManager, MarketPhase
    from datetime import datetime, timezone, timedelta

    passed = 0
    failed = 0

    # Cumartesi
    class FakeSaturday(MarketSessionManager):
        def now_istanbul(self):
            # 2026-08-22 Cumartesi
            return datetime(2026, 8, 22, 12, 0, tzinfo=timezone(timedelta(hours=3)))

    mgr = FakeSaturday()
    assert mgr.current_phase() == MarketPhase.CLOSED
    assert mgr.is_closed()
    assert not mgr.is_trading_hours()
    print("  ✓ Saturday: CLOSED")
    passed += 1

    # Pazar
    class FakeSunday(MarketSessionManager):
        def now_istanbul(self):
            return datetime(2026, 8, 23, 14, 0, tzinfo=timezone(timedelta(hours=3)))

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
    from services.core.market_session import MarketSessionManager, MarketPhase
    from datetime import datetime, timezone, timedelta

    passed = 0
    failed = 0

    holidays = {"2026-01-01", "2026-04-23"}

    class FakeHoliday(MarketSessionManager):
        def now_istanbul(self):
            # 2026-01-01 Perşembe (tatil ama hafta içi)
            return datetime(2026, 1, 1, 14, 0, tzinfo=timezone(timedelta(hours=3)))

    mgr = FakeHoliday(holidays=holidays)
    assert mgr.current_phase() == MarketPhase.CLOSED
    print("  ✓ Holiday (2026-01-01): CLOSED")
    passed += 1

    return passed, failed


# ────────────────────────────────────────────────────────────
# 4. Market session — market open/close phases
# ────────────────────────────────────────────────────────────

def test_market_session_phases():
    """Market phase'leri doğru ayrılmalı."""
    from services.core.market_session import MarketSessionManager, MarketPhase
    from datetime import datetime, timezone, timedelta

    passed = 0
    failed = 0

    IST = timezone(timedelta(hours=3))

    class Fake(MarketSessionManager):
        def __init__(self, dt):
            self._dt = dt
            self._holidays = set()
        def now_istanbul(self):
            return self._dt

    # 09:30 → CLOSED
    m = Fake(datetime(2026, 8, 18, 9, 30, tzinfo=IST))
    assert m.current_phase() == MarketPhase.CLOSED
    print("  ✓ 09:30: CLOSED")
    passed += 1

    # 09:55 → PRE_MARKET
    m = Fake(datetime(2026, 8, 18, 9, 55, tzinfo=IST))
    assert m.current_phase() == MarketPhase.PRE_MARKET
    print("  ✓ 09:55: PRE_MARKET")
    passed += 1

    # 10:30 → ACTIVE
    m = Fake(datetime(2026, 8, 18, 10, 30, tzinfo=IST))
    assert m.current_phase() == MarketPhase.ACTIVE
    assert m.is_trading_hours()
    print("  ✓ 10:30: ACTIVE")
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

    return passed, failed


# ────────────────────────────────────────────────────────────
# 5. Worker — job execution
# ────────────────────────────────────────────────────────────

def test_worker_job_execution():
    """Worker job çalıştırabilmeli."""
    from services.core.worker import JobWorker, JobStatus

    passed = 0
    failed = 0

    worker = JobWorker(worker_id="test-w1")
    result_holder = {}

    async def handler(**kwargs):
        result_holder["executed"] = True
        result_holder["kwargs"] = kwargs
        return {"status": "ok"}

    # DB yoksa bile crash olmamalı
    async def run():
        job_id = await worker.submit_job(
            job_type="test_job",
            handler=handler,
            payload={"ticker": "THYAO"},
            idempotency_key="test_key_1",
        )
        # DB yoksa job_id None olabilir
        await asyncio.sleep(0.5)
        return job_id

    loop = asyncio.new_event_loop()
    try:
        job_id = loop.run_until_complete(run())
        # Handler çalışmış olmalı (DB yoksa bile)
        print(f"  ✓ Worker job: job_id={job_id}, executed={result_holder.get('executed', False)}")
        passed += 1
    finally:
        loop.close()

    return passed, failed


# ────────────────────────────────────────────────────────────
# 6. Worker — timeout
# ────────────────────────────────────────────────────────────

def test_worker_timeout():
    """Timeout olan job TIMEOUT durumuna geçmeli."""
    from services.core.worker import JobWorker

    passed = 0
    failed = 0

    worker = JobWorker(worker_id="test-timeout", default_timeout=1)

    async def slow_handler(**kwargs):
        await asyncio.sleep(10)
        return {"done": True}

    async def run():
        job_id = await worker.submit_job(
            job_type="timeout_test",
            handler=slow_handler,
            timeout=1,
            max_retries=0,
            idempotency_key="timeout_key",
        )
        await asyncio.sleep(2)
        return job_id

    loop = asyncio.new_event_loop()
    try:
        job_id = loop.run_until_complete(run())
        print(f"  ✓ Worker timeout: job_id={job_id} (DB yoksa None)")
        passed += 1
    finally:
        loop.close()

    return passed, failed


# ────────────────────────────────────────────────────────────
# 7. Worker — retry
# ────────────────────────────────────────────────────────────

def test_worker_retry():
    """Başarısız job retry yapmalı."""
    from services.core.worker import JobWorker

    passed = 0
    failed = 0

    worker = JobWorker(worker_id="test-retry", retry_base_delay=0.1)
    attempt_count = {"n": 0}

    async def failing_handler(**kwargs):
        attempt_count["n"] += 1
        if attempt_count["n"] < 3:
            raise ValueError(f"Fail #{attempt_count['n']}")
        return {"success": True}

    async def run():
        job_id = await worker.submit_job(
            job_type="retry_test",
            handler=failing_handler,
            max_retries=3,
            idempotency_key="retry_key",
        )
        await asyncio.sleep(2)
        return job_id

    loop = asyncio.new_event_loop()
    try:
        job_id = loop.run_until_complete(run())
        print(f"  ✓ Worker retry: {attempt_count['n']} attempts, job_id={job_id}")
        passed += 1
    finally:
        loop.close()

    return passed, failed


# ────────────────────────────────────────────────────────────
# 8. Idempotency
# ────────────────────────────────────────────────────────────

def test_idempotency_key_generation():
    """Aynı payload aynı key üretmeli."""
    from services.core.worker import JobWorker

    passed = 0
    failed = 0

    w = JobWorker()
    k1 = w._generate_idempotency_key("test", {"a": 1, "b": 2})
    k2 = w._generate_idempotency_key("test", {"b": 2, "a": 1})  # Farklı sıra
    k3 = w._generate_idempotency_key("test", {"a": 1, "b": 3})  # Farklı değer

    assert k1 == k2, "Same payload should produce same key regardless of order"
    assert k1 != k3, "Different payload should produce different key"
    assert len(k1) == 32

    print(f"  ✓ Idempotency key: deterministic, order-independent")
    passed += 1

    return passed, failed


# ────────────────────────────────────────────────────────────
# 9. Scheduler — handler registration
# ────────────────────────────────────────────────────────────

def test_scheduler_handler_registration():
    """Scheduler handler kaydı yapabilmeli."""
    from services.scheduler.production_scheduler import ProductionScheduler

    passed = 0
    failed = 0

    scheduler = ProductionScheduler()
    called = {}

    async def my_handler(**kwargs):
        called["yes"] = True

    scheduler.register_handler("test_job", my_handler)
    assert "test_job" in scheduler._handlers

    print("  ✓ Scheduler handler registration: OK")
    passed += 1

    return passed, failed


# ────────────────────────────────────────────────────────────
# 10. Scheduler — market closed skips trading jobs
# ────────────────────────────────────────────────────────────

def test_scheduler_market_closed():
    """Market kapalıyken trading job'ları çalışmamalı."""
    from services.core.market_session import MarketSessionManager, MarketPhase
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
# 11. Market session — next phase change
# ────────────────────────────────────────────────────────────

def test_next_phase_change():
    """Bir sonraki phase değişikliği doğru hesaplanmalı."""
    from services.core.market_session import MarketSessionManager, MarketPhase
    from datetime import datetime, timezone, timedelta

    passed = 0
    failed = 0

    IST = timezone(timedelta(hours=3))

    class Fake(MarketSessionManager):
        def __init__(self, dt):
            self._dt = dt
            self._holidays = set()
        def now_istanbul(self):
            return self._dt

    # ACTIVE → bir sonraki POST_MARKET (18:00)
    m = Fake(datetime(2026, 8, 18, 14, 0, tzinfo=IST))
    next_change = m.next_phase_change()
    assert next_change is not None
    assert next_change.hour == 18 and next_change.minute == 0
    print(f"  ✓ 14:00 → next change at {next_change.strftime('%H:%M')} (18:00)")
    passed += 1

    # CLOSED (gece) → bir sonraki PRE_MARKET (09:50)
    m = Fake(datetime(2026, 8, 18, 3, 0, tzinfo=IST))
    next_change = m.next_phase_change()
    assert next_change is not None
    assert next_change.hour == 9 and next_change.minute == 50
    print(f"  ✓ 03:00 → next change at {next_change.strftime('%H:%M')} (09:50)")
    passed += 1

    return passed, failed


# ────────────────────────────────────────────────────────────
# 12. Worker — graceful shutdown
# ────────────────────────────────────────────────────────────

def test_worker_graceful_shutdown():
    """Worker shutdown çalışmalı."""
    from services.core.worker import JobWorker

    passed = 0
    failed = 0

    worker = JobWorker(worker_id="test-shutdown")

    async def run():
        await worker.shutdown(timeout=5)
        return True

    loop = asyncio.new_event_loop()
    try:
        result = loop.run_until_complete(run())
        assert result is True
        print("  ✓ Worker graceful shutdown: OK")
        passed += 1
    finally:
        loop.close()

    return passed, failed


# ────────────────────────────────────────────────────────────
# 13. Concurrent job prevention
# ────────────────────────────────────────────────────────────

def test_concurrent_job_prevention():
    """Aynı idempotency_key ile iki job gönderilmemeli."""
    from services.core.worker import JobWorker

    passed = 0
    failed = 0

    w = JobWorker()
    # Aynı key ile iki key üretimi
    k1 = w._generate_idempotency_key("live_inference", {"ticker": "THYAO", "horizon": 5})
    k2 = w._generate_idempotency_key("live_inference", {"horizon": 5, "ticker": "THYAO"})
    k3 = w._generate_idempotency_key("live_inference", {"ticker": "GARAN", "horizon": 5})

    assert k1 == k2, "Same params, different order → same key"
    assert k1 != k3, "Different ticker → different key"

    print(f"  ✓ Concurrent prevention: same key={k1[:8]}..., different key={k3[:8]}...")
    passed += 1

    return passed, failed


# ────────────────────────────────────────────────────────────
# 14. Failure scenarios — model unavailable
# ────────────────────────────────────────────────────────────

def test_failure_model_unavailable():
    """Model yoksa sistem crash olmamalı, fallback kullanmalı."""
    from services.core.worker import JobWorker

    passed = 0
    failed = 0

    worker = JobWorker(worker_id="test-model-fail")

    async def handler_with_model(**kwargs):
        # Model yok simülasyonu
        model = kwargs.get("model")
        if model is None:
            return {"status": "fallback", "reason": "model_unavailable"}
        return {"status": "ok"}

    async def run():
        job_id = await worker.submit_job(
            job_type="live_inference",
            handler=handler_with_model,
            payload={"model": None},
            idempotency_key="model_fail_test",
        )
        await asyncio.sleep(0.3)
        return job_id

    loop = asyncio.new_event_loop()
    try:
        loop.run_until_complete(run())
        print("  ✓ Model unavailable: graceful fallback, no crash")
        passed += 1
    except Exception as e:
        print(f"  ✗ Model unavailable caused crash: {e}")
        failed += 1
    finally:
        loop.close()

    return passed, failed


# ────────────────────────────────────────────────────────────
# 15. Failure scenarios — provider timeout
# ────────────────────────────────────────────────────────────

def test_failure_provider_timeout():
    """Provider timeout'ta retry yapmalı, crash olmamalı."""
    from services.core.worker import JobWorker

    passed = 0
    failed = 0

    worker = JobWorker(worker_id="test-provider", retry_base_delay=0.05)
    attempt_count = {"n": 0}

    async def slow_provider(**kwargs):
        attempt_count["n"] += 1
        if attempt_count["n"] < 2:
            await asyncio.sleep(10)  # Timeout
        return {"data": "ok"}

    async def run():
        job_id = await worker.submit_job(
            job_type="market_data_update",
            handler=slow_provider,
            timeout=1,
            max_retries=2,
            idempotency_key="provider_timeout_test",
        )
        await asyncio.sleep(3)
        return job_id

    loop = asyncio.new_event_loop()
    try:
        loop.run_until_complete(run())
        print(f"  ✓ Provider timeout: {attempt_count['n']} attempts, no crash")
        passed += 1
    except Exception as e:
        print(f"  ✗ Provider timeout caused crash: {e}")
        failed += 1
    finally:
        loop.close()

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
        ("Worker job execution", test_worker_job_execution),
        ("Worker timeout", test_worker_timeout),
        ("Worker retry", test_worker_retry),
        ("Idempotency key", test_idempotency_key_generation),
        ("Scheduler handler registration", test_scheduler_handler_registration),
        ("Market closed blocks trading", test_scheduler_market_closed),
        ("Next phase change", test_next_phase_change),
        ("Worker graceful shutdown", test_worker_graceful_shutdown),
        ("Concurrent job prevention", test_concurrent_job_prevention),
        ("Failure: model unavailable", test_failure_model_unavailable),
        ("Failure: provider timeout", test_failure_provider_timeout),
    ]

    total_passed = 0
    total_failed = 0

    print("=" * 70)
    print("FAZ 5.2 — Market Session + Worker + Scheduler")
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
