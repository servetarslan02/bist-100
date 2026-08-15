"""
ALPHA BIST — FAZ 1 Test Suite

Market Calendar, Corporate Actions, Circuit Breaker, Rate Limiter testleri.

Kullanım:
  python3 -m pytest tests/test_phase1.py -v
  veya
  python3 tests/test_phase1.py
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import datetime, date, time, timedelta


def test_market_calendar():
    """Market Calendar testleri."""
    from services.core.market_calendar import MarketCalendar, MarketSession, MarketStatus

    cal = MarketCalendar()
    passed = 0
    failed = 0

    # Test 1: Hafta içi tatil değilse işlem günü
    # 2026-08-18 Pazartesi
    d = date(2026, 8, 18)
    if cal.is_trading_day(d):
        print(f"  ✓ Pazartesi işlem günü: {d}")
        passed += 1
    else:
        print(f"  ✗ Pazartesi işlem günü olmalı: {d}")
        failed += 1

    # Test 2: Cumartesi işlem günü değil
    d = date(2026, 8, 15)
    if not cal.is_trading_day(d):
        print(f"  ✓ Cumartesi işlem günü değil: {d}")
        passed += 1
    else:
        print(f"  ✗ Cumartesi işlem günü olmamalı: {d}")
        failed += 1

    # Test 3: Pazar işlem günü değil
    d = date(2026, 8, 16)
    if not cal.is_trading_day(d):
        print(f"  ✓ Pazar işlem günü değil: {d}")
        passed += 1
    else:
        print(f"  ✗ Pazar işlem günü olmamalı: {d}")
        failed += 1

    # Test 4: Resmi tatil
    d = date(2026, 1, 1)  # Yılbaşı
    if not cal.is_trading_day(d):
        print(f"  ✓ Yılbaşı tatil: {d}")
        passed += 1
    else:
        print(f"  ✗ Yılbaşı tatil olmalı: {d}")
        failed += 1

    # Test 5: Market açık (Pazartesi 11:00)
    dt = datetime(2026, 8, 18, 11, 0)
    if cal.is_market_open(dt):
        print(f"  ✓ Pazar 11:00 market açık")
        passed += 1
    else:
        print(f"  ✗ Pazar 11:00 market açık olmalı")
        failed += 1

    # Test 6: Market kapalı (gece)
    dt = datetime(2026, 8, 18, 23, 0)
    if not cal.is_market_open(dt):
        print(f"  ✓ Gece 23:00 market kapalı")
        passed += 1
    else:
        print(f"  ✗ Gece 23:00 market kapalı olmalı")
        failed += 1

    # Test 7: Öğle arası
    dt = datetime(2026, 8, 18, 13, 30)
    if not cal.is_market_open(dt):
        print(f"  ✓ Öğle arası market kapalı")
        passed += 1
    else:
        print(f"  ✗ Öğle arası market kapalı olmalı")
        failed += 1

    # Test 8: Pre-market
    dt = datetime(2026, 8, 18, 9, 50)
    session = cal.get_session(dt)
    if session == MarketSession.PRE_MARKET:
        print(f"  ✓ 09:50 pre-market")
        passed += 1
    else:
        print(f"  ✗ 09:50 pre-market olmalı, {session}")
        failed += 1

    # Test 9: Morning session
    dt = datetime(2026, 8, 18, 10, 30)
    session = cal.get_session(dt)
    if session == MarketSession.MORNING:
        print(f"  ✓ 10:30 morning session")
        passed += 1
    else:
        print(f"  ✗ 10:30 morning olmalı, {session}")
        failed += 1

    # Test 10: next_open
    dt = datetime(2026, 8, 15, 20, 0)  # Cumartesi akşam
    next_o = cal.next_open(dt)
    if next_o.weekday() == 0:  # Pazartesi
        print(f"  ✓ Cumartesi akşamı next_open: {next_o}")
        passed += 1
    else:
        print(f"  ✗ next_open Pazartesi olmalı: {next_o}")
        failed += 1

    # Test 11: trading_days_between
    start = date(2026, 8, 10)  # Pazartesi
    end = date(2026, 8, 15)    # Cumartesi
    days = cal.trading_days_between(start, end)
    if days == 5:
        print(f"  ✓ 5 işlem günü (Pzt-Cuma)")
        passed += 1
    else:
        print(f"  ✗ 5 işlem günü olmalı, {days}")
        failed += 1

    # Test 12: Devre kesici
    from datetime import time as t
    cal.add_halt(date(2026, 8, 18), t(11, 0), t(11, 30))
    dt = datetime(2026, 8, 18, 11, 15)
    if cal.get_status(dt) == MarketStatus.HALT:
        print(f"  ✓ Devre kesici 11:15")
        passed += 1
    else:
        print(f"  ✗ Devre kesici olmalı 11:15")
        failed += 1

    return passed, failed


def test_corporate_actions():
    """Corporate Actions testleri."""
    from services.ingestion.corporate_actions import (
        CorporateActionsHandler, CorporateAction, ActionType
    )

    handler = CorporateActionsHandler()
    passed = 0
    failed = 0

    # Test 1: Temettü fiyat düzeltmesi
    handler.add_action(CorporateAction(
        action_id="DIV-001",
        ticker="THYAO",
        action_type=ActionType.DIVIDEND,
        ex_date=date(2026, 6, 1),
        dividend_per_share=5.25,
    ))

    # Ex-date'ten önceki fiyat düzeltilmeli
    adjusted = handler.adjust_price("THYAO", 300.0, date(2026, 6, 2))
    if abs(adjusted - 294.75) < 0.01:
        print(f"  ✓ Temettü düzeltme: 300 → {adjusted}")
        passed += 1
    else:
        print(f"  ✗ Temettü düzeltme: 294.75 bekleniyor, {adjusted}")
        failed += 1

    # Ex-date'ten sonraki fiyat düzeltilmemeli
    adjusted = handler.adjust_price("THYAO", 300.0, date(2026, 6, 1))
    if abs(adjusted - 300.0) < 0.01:
        print(f"  ✓ Ex-date düzeltme yok: {adjusted}")
        passed += 1
    else:
        print(f"  ✗ Ex-date'te düzeltme olmamalı: {adjusted}")
        failed += 1

    # Test 2: Bölünme fiyat düzeltmesi
    handler.add_action(CorporateAction(
        action_id="SPLIT-001",
        ticker="ASELS",
        action_type=ActionType.STOCK_SPLIT,
        ex_date=date(2026, 7, 1),
        split_ratio=10.0,
    ))

    adjusted = handler.adjust_price("ASELS", 500.0, date(2026, 7, 2))
    if abs(adjusted - 50.0) < 0.01:
        print(f"  ✓ Bölünme düzeltme: 500 → {adjusted}")
        passed += 1
    else:
        print(f"  ✗ Bölünme düzeltme: 50 bekleniyor, {adjusted}")
        failed += 1

    # Test 3: Bölünme pozisyon düzeltmesi
    new_qty = handler.adjust_position("ASELS", 100, CorporateAction(
        action_id="SPLIT-001",
        ticker="ASELS",
        action_type=ActionType.STOCK_SPLIT,
        ex_date=date(2026, 7, 1),
        split_ratio=10.0,
    ))
    if new_qty == 1000:
        print(f"  ✓ Bölünme pozisyon: 100 → {new_qty}")
        passed += 1
    else:
        print(f"  ✗ Bölünme pozisyon: 1000 bekleniyor, {new_qty}")
        failed += 1

    # Test 4: Bedelsiz pozisyon düzeltmesi
    new_qty = handler.adjust_position("THYAO", 100, CorporateAction(
        action_id="BONUS-001",
        ticker="THYAO",
        action_type=ActionType.BONUS_SHARE,
        ex_date=date(2026, 7, 1),
        bonus_ratio=0.5,
    ))
    if new_qty == 150:
        print(f"  ✓ Bedelsiz pozisyon: 100 → {new_qty}")
        passed += 1
    else:
        print(f"  ✗ Bedelsiz pozisyon: 150 bekleniyor, {new_qty}")
        failed += 1

    # Test 5: Temettü geliri
    income = handler.compute_dividend_income("THYAO", 100, CorporateAction(
        action_id="DIV-001",
        ticker="THYAO",
        action_type=ActionType.DIVIDEND,
        ex_date=date(2026, 6, 1),
        dividend_per_share=5.25,
    ))
    if abs(income - 525.0) < 0.01:
        print(f"  ✓ Temettü geliri: {income}")
        passed += 1
    else:
        print(f"  ✗ Temettü geliri: 525 bekleniyor, {income}")
        failed += 1

    # Test 6: Bedelli fiyat düzeltmesi
    handler.add_action(CorporateAction(
        action_id="RIGHTS-001",
        ticker="GARAN",
        action_type=ActionType.RIGHTS_ISSUE,
        ex_date=date(2026, 8, 1),
        rights_ratio=0.2,   # her 5 hisseye 1 yeni
        rights_price=20.0,  # 20 TL'den
    ))

    adjusted = handler.adjust_price("GARAN", 100.0, date(2026, 8, 2))
    # (100 + 20×0.2) / (1+0.2) = (100+4)/1.2 = 86.67
    if abs(adjusted - 86.6667) < 0.1:
        print(f"  ✓ Bedelli düzeltme: 100 → {adjusted}")
        passed += 1
    else:
        print(f"  ✗ Bedelli düzeltme: ~86.67 bekleniyor, {adjusted}")
        failed += 1

    # Test 7: KAP olay sınıflandırma
    event = {"title": "Şirketimiz 2026 yılı kar payı dağıtımı hakkında", "summary": ""}
    action_type = handler._classify_kap_event(event)
    if action_type == ActionType.DIVIDEND:
        print(f"  ✓ KAP sınıflandırma: temettü")
        passed += 1
    else:
        print(f"  ✗ KAP sınıflandırma: DIVIDEND bekleniyor, {action_type}")
        failed += 1

    return passed, failed


def test_circuit_breaker():
    """Circuit Breaker testleri."""
    from services.core.circuit_breaker import CircuitBreaker, CircuitState

    passed = 0
    failed = 0

    # Test 1: Başlangıçta CLOSED
    cb = CircuitBreaker(name="test", failure_threshold=3)
    if cb.state == CircuitState.CLOSED and cb.can_execute():
        print(f"  ✓ Başlangıçta CLOSED")
        passed += 1
    else:
        print(f"  ✗ Başlangıçta CLOSED olmalı")
        failed += 1

    # Test 2: 3 failure → OPEN
    cb.record_failure()
    cb.record_failure()
    cb.record_failure()
    if cb.state == CircuitState.OPEN:
        print(f"  ✓ 3 failure → OPEN")
        passed += 1
    else:
        print(f"  ✗ OPEN olmalı, {cb.state}")
        failed += 1

    # Test 3: OPEN iken çağrı yapılamaz
    if not cb.can_execute():
        print(f"  ✓ OPEN iken çağrı yok")
        passed += 1
    else:
        print(f"  ✗ OPEN iken çağrı olmamalı")
        failed += 1

    # Test 4: Recovery timeout sonrası HALF_OPEN
    cb.last_failure_time = datetime.utcnow() - timedelta(seconds=61)
    if cb.can_execute() and cb.state == CircuitState.HALF_OPEN:
        print(f"  ✓ Timeout sonrası HALF_OPEN")
        passed += 1
    else:
        print(f"  ✗ HALF_OPEN olmalı, {cb.state}")
        failed += 1

    # Test 5: HALF_OPEN'da başarı → CLOSED
    cb.record_success()
    if cb.state == CircuitState.CLOSED:
        print(f"  ✓ HALF_OPEN success → CLOSED")
        passed += 1
    else:
        print(f"  ✗ CLOSED olmalı, {cb.state}")
        failed += 1

    # Test 6: HALF_OPEN'da failure → OPEN
    cb = CircuitBreaker(name="test2", failure_threshold=2)
    cb.record_failure()
    cb.record_failure()
    cb.last_failure_time = datetime.utcnow() - timedelta(seconds=61)
    cb.can_execute()  # → HALF_OPEN
    cb.record_failure()
    if cb.state == CircuitState.OPEN:
        print(f"  ✓ HALF_OPEN failure → OPEN")
        passed += 1
    else:
        print(f"  ✗ OPEN olmalı, {cb.state}")
        failed += 1

    return passed, failed


def test_rate_limiter():
    """Rate Limiter testleri."""
    from services.core.circuit_breaker import RateLimiter
    import asyncio

    passed = 0
    failed = 0

    # Test 1: İlk çağrılar hemen yapılmalı
    rl = RateLimiter(name="test", max_tokens=5, refill_rate=1.0)
    for i in range(5):
        wait = rl.acquire()
        if wait == 0.0:
            passed += 1
        else:
            failed += 1

    if passed == 5:
        print(f"  ✓ 5 token → 5 çağrı hemen")
    else:
        print(f"  ✗ 5 çağrı hemen olmalı, {failed} başarısız")

    # Test 2: 6. çağrı beklemeli
    wait = rl.acquire()
    if wait > 0:
        print(f"  ✓ 6. çağrı beklemeli: {wait:.2f}s")
        passed += 1
    else:
        print(f"  ✗ 6. çağrı beklemeli")
        failed += 1

    return passed, failed


def test_provider_reliability():
    """Provider Reliability testleri."""
    from services.core.circuit_breaker import ProviderReliability

    passed = 0
    failed = 0

    # Test 1: Başlangıçta skor 1.0
    pr = ProviderReliability(name="test")
    if pr.get_score() == 1.0:
        print(f"  ✓ Başlangıç skoru: 1.0")
        passed += 1
    else:
        print(f"  ✗ Başlangıç skoru 1.0 olmalı: {pr.get_score()}")
        failed += 1

    # Test 2: Tüm başarılı → yüksek skor
    for _ in range(100):
        pr.record(True, 50.0)
    score = pr.get_score()
    if score > 0.9:
        print(f"  ✓ %100 başarı skoru: {score}")
        passed += 1
    else:
        print(f"  ✗ Yüksek skor bekleniyor: {score}")
        failed += 1

    # Test 3: Tüm başarısız → düşük skor
    pr2 = ProviderReliability(name="test2")
    for _ in range(100):
        pr2.record(False, 5000.0)
    score = pr2.get_score()
    # success_rate=0, latency_factor=0, freshness=0 → skor ≈ 0
    if score <= 0.15:
        print(f"  ✓ %100 failure skoru: {score}")
        passed += 1
    else:
        print(f"  ✗ Düşük skor bekleniyor: {score}")
        failed += 1

    # Test 4: Karışık sonuçlar
    pr3 = ProviderReliability(name="test3")
    for _ in range(80):
        pr3.record(True, 100.0)
    for _ in range(20):
        pr3.record(False, 2000.0)
    score = pr3.get_score()
    # success_rate=0.8×0.6 + latency=0.98×0.2 + freshness=1.0×0.2 ≈ 0.68
    if 0.5 < score < 1.0:
        print(f"  ✓ %80 başarı skoru: {score}")
        passed += 1
    else:
        print(f"  ✗ Orta-yüksek skor bekleniyor: {score}")
        failed += 1

    return passed, failed


def main():
    print("=" * 60)
    print("  FAZ 1 — Test Suite")
    print("=" * 60)

    total_passed = 0
    total_failed = 0

    tests = [
        ("Market Calendar", test_market_calendar),
        ("Corporate Actions", test_corporate_actions),
        ("Circuit Breaker", test_circuit_breaker),
        ("Rate Limiter", test_rate_limiter),
        ("Provider Reliability", test_provider_reliability),
    ]

    for name, test_func in tests:
        print(f"\n--- {name} ---")
        try:
            p, f = test_func()
            total_passed += p
            total_failed += f
        except Exception as e:
            print(f"  ✗ Test crashed: {e}")
            import traceback
            traceback.print_exc()
            total_failed += 1

    print(f"\n{'=' * 60}")
    print(f"  SONUÇ: {total_passed} passed, {total_failed} failed")
    print(f"{'=' * 60}")

    return total_failed == 0


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
