"""
Test: PC Kapalı Kalma Senaryoları — Recovery Mechanism

Bu test şunları doğrular:
1. Gap detection (kaç gün geçtiğini hesaplama)
2. Multi-day T+2 settlement roll
3. Pending signal expiry (1 günden eski sinyaller temizlenir)
4. Kill switch auto-reset
5. Equity curve gap fill
6. Force price refresh
"""

import os
import sys
import json
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from services.paper_trading.state_store import PaperStateStore
from services.paper_trading.virtual_portfolio import VirtualPortfolio
from services.paper_trading.paper_risk_gate import PaperRiskGate
from services.paper_trading.paper_orchestrator import PaperTradingOrchestrator


def test_gap_detection():
    """Test 1: Gap detection doğru gün sayısını hesaplıyor mu?"""
    print("\n=== TEST 1: Gap Detection ===")
    
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        db_path = tmp.name
    
    try:
        store = PaperStateStore(db_path=db_path)
        store.set_config("last_cycle_date", "2026-08-20")
        
        orchestrator = PaperTradingOrchestrator(
            initial_capital=1_000_000,
            store=store,
        )
        
        result = orchestrator.recover_from_downtime("2026-08-25")
        
        assert result["status"] == "RECOVERED", f"Expected RECOVERED, got {result['status']}"
        assert result["gap_days"] == 5, f"Expected 5 gap days, got {result['gap_days']}"
        print(f"  ✅ Gap detection: {result['gap_days']} gün doğru tespit edildi")
        
    finally:
        os.unlink(db_path)


def test_multi_day_t2_roll():
    """Test 2: T+2 takas birden fazla gün için kaydırılıyor mu?"""
    print("\n=== TEST 2: Multi-Day T+2 Settlement Roll ===")
    
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        db_path = tmp.name
    
    try:
        store = PaperStateStore(db_path=db_path)
        portfolio = VirtualPortfolio(initial_capital=1_000_000, state_store=store)
        
        # Başlangıç durumu: Bir hisse satılmış, T+2'de para var
        portfolio.settled_cash = 500_000
        portfolio.unsettled_cash_t1 = 100_000
        portfolio.unsettled_cash_t2 = 200_000
        
        initial_settled = portfolio.settled_cash
        initial_t1 = portfolio.unsettled_cash_t1
        initial_t2 = portfolio.unsettled_cash_t2
        
        # 3 gün boyunca roll yap (PC 3 gün kapalı kalmış)
        for i in range(3):
            portfolio.roll_settlement_day()
        
        # 3 gün sonra: T+2 → T+1 → T+0 → settled'a düşmeli
        expected_settled = initial_settled + initial_t1 + initial_t2
        assert portfolio.settled_cash == expected_settled, \
            f"Expected settled={expected_settled}, got {portfolio.settled_cash}"
        assert portfolio.unsettled_cash_t1 == 0.0, \
            f"Expected t1=0, got {portfolio.unsettled_cash_t1}"
        assert portfolio.unsettled_cash_t2 == 0.0, \
            f"Expected t2=0, got {portfolio.unsettled_cash_t2}"
        
        print(f"  ✅ T+2 roll: 3 gün sonunda settled={portfolio.settled_cash:.0f}")
        print(f"     Başlangıç: settled={initial_settled:.0f}, t1={initial_t1:.0f}, t2={initial_t2:.0f}")
        
    finally:
        os.unlink(db_path)


def test_pending_signal_expiry():
    """Test 3: Süresi dolmuş sinyaller temizleniyor mu?"""
    print("\n=== TEST 3: Pending Signal Expiry ===")
    
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        db_path = tmp.name
    
    try:
        store = PaperStateStore(db_path=db_path)
        
        # 3 sinyal kaydet
        signals = [
            {"ticker": "THYAO", "direction": "LONG", "score": 85, "model_version": "test"},
            {"ticker": "GARAN", "direction": "LONG", "score": 78, "model_version": "test"},
            {"ticker": "ASELS", "direction": "SHORT", "score": 90, "model_version": "test"},
        ]
        store.save_pending_signals(signals, "2026-08-20")
        
        # Hemen yükle → 3 sinyal olmalı
        loaded = store.load_pending_signals()
        assert len(loaded) == 3, f"Expected 3 signals, got {len(loaded)}"
        print(f"  ✅ Taze sinyaller yüklendi: {len(loaded)} adet")
        
        # Süresi dolmuş sinyalleri temizle (max_age_days=0 → hepsini temizle)
        # Not: expires_at 1 gün sonra, bu yüzden 0 gün ile temizlemek için
        # doğrudan DB'yi manipüle edelim
        with store._connect() as conn:
            conn.execute(
                "UPDATE pending_signals SET expires_at = '2020-01-01T00:00:00'"
            )
            conn.commit()
        
        cleared = store.clear_stale_pending_signals(max_age_days=1)
        assert cleared == 3, f"Expected 3 cleared, got {cleared}"
        print(f"  ✅ Süresi dolmuş sinyaller temizlendi: {cleared} adet")
        
        # Yükle → 0 sinyal olmalı
        loaded_after = store.load_pending_signals()
        assert len(loaded_after) == 0, f"Expected 0 signals after clear, got {len(loaded_after)}"
        print(f"  ✅ Temizlik sonrası sinyal sayısı: {len(loaded_after)}")
        
    finally:
        os.unlink(db_path)


def test_kill_switch_auto_reset():
    """Test 4: Kill switch yeni günde otomatik resetleniyor mu?"""
    print("\n=== TEST 4: Kill Switch Auto-Reset ===")
    
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        db_path = tmp.name
    
    try:
        store = PaperStateStore(db_path=db_path)
        store.set_config("last_cycle_date", "2026-08-20")
        
        orchestrator = PaperTradingOrchestrator(
            initial_capital=1_000_000,
            store=store,
        )
        
        # Kill switch'i manuel aktif et
        orchestrator.risk_gate._kill_switch_active = True
        orchestrator.risk_gate._kill_switch_reason = "Test kill switch"
        
        assert orchestrator.risk_gate.is_kill_switch_active(), "Kill switch should be active"
        
        # Recovery çalıştır (yeni gün)
        result = orchestrator.recover_from_downtime("2026-08-25")
        
        assert not orchestrator.risk_gate.is_kill_switch_active(), \
            "Kill switch should be reset after recovery"
        
        print(f"  ✅ Kill switch otomatik resetlendi")
        print(f"     Gap gün sayısı: {result['gap_days']}")
        
    finally:
        os.unlink(db_path)


def test_equity_curve_gap_fill():
    """Test 5: Equity curve'deki boş günler dolduruluyor mu?"""
    print("\n=== TEST 5: Equity Curve Gap Fill ===")
    
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        db_path = tmp.name
    
    try:
        store = PaperStateStore(db_path=db_path)
        store.set_config("last_cycle_date", "2026-08-20")
        
        orchestrator = PaperTradingOrchestrator(
            initial_capital=1_000_000,
            store=store,
        )
        
        # Mevcut equity curve'e bir kayıt ekle
        orchestrator.portfolio._equity_curve = [
            {"date": "2026-08-20", "equity": 1_050_000, "cash": 500_000, 
             "settled_cash": 500_000, "invested": 550_000}
        ]
        
        # Recovery çalıştır (5 gün gap)
        result = orchestrator.recover_from_downtime("2026-08-25")
        
        # Equity curve'de 5 kayıt olmalı (1 orijinal + 4 fill)
        curve = orchestrator.portfolio._equity_curve
        assert len(curve) == 5, f"Expected 5 equity points, got {len(curve)}"
        
        # Tüm fill kayıtları aynı equity değerine sahip olmalı
        for pt in curve:
            assert pt["equity"] == 1_050_000, f"Fill equity mismatch: {pt['equity']}"
        
        print(f"  ✅ Equity curve gap fill: {len(curve)} kayıt")
        print(f"     Tarihler: {[pt['date'] for pt in curve]}")
        
    finally:
        os.unlink(db_path)


def test_no_gap_scenario():
    """Test 6: Gap yoksa recovery çalışmamalı."""
    print("\n=== TEST 6: No Gap Scenario ===")
    
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        db_path = tmp.name
    
    try:
        store = PaperStateStore(db_path=db_path)
        store.set_config("last_cycle_date", "2026-08-25")
        
        orchestrator = PaperTradingOrchestrator(
            initial_capital=1_000_000,
            store=store,
        )
        
        result = orchestrator.recover_from_downtime("2026-08-25")
        
        assert result["status"] == "NO_GAP", f"Expected NO_GAP, got {result['status']}"
        assert result["gap_days"] == 0
        
        print(f"  ✅ Gap yok: Recovery çalışmadı (status=NO_GAP)")
        
    finally:
        os.unlink(db_path)


def test_first_run_scenario():
    """Test 7: İlk çalıştırmada recovery atlanmalı."""
    print("\n=== TEST 7: First Run Scenario ===")
    
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        db_path = tmp.name
    
    try:
        store = PaperStateStore(db_path=db_path)
        # last_cycle_date ayarlanmamış
        
        orchestrator = PaperTradingOrchestrator(
            initial_capital=1_000_000,
            store=store,
        )
        
        result = orchestrator.recover_from_downtime("2026-08-25")
        
        assert result["status"] == "FIRST_RUN", f"Expected FIRST_RUN, got {result['status']}"
        
        print(f"  ✅ İlk çalıştırma: Recovery atlandı (status=FIRST_RUN)")
        
    finally:
        os.unlink(db_path)


def test_docker_restart_policy():
    """Test 8: Docker restart policy 'always' olarak ayarlanmış mı?"""
    print("\n=== TEST 8: Docker Restart Policy ===")
    
    compose_path = Path(__file__).parent.parent / "docker-compose.yml"
    content = compose_path.read_text()
    
    assert "restart: always" in content, "restart: always not found in docker-compose.yml"
    assert "restart: unless-stopped" not in content, "Old restart policy still present"
    
    print(f"  ✅ Docker restart policy: 'always'")


def test_holiday_calendar_extended():
    """Test 9: Holiday takvimi 2028+ yılları içeriyor mu?"""
    print("\n=== TEST 9: Holiday Calendar Extended ===")
    
    from services.scheduler.unified_scheduler import HolidayProvider
    from datetime import date
    
    provider = HolidayProvider()
    holidays = provider.get_holidays()
    
    # 2028 tatilleri var mı?
    has_2028 = any(d.year == 2028 for d in holidays)
    has_2029 = any(d.year == 2029 for d in holidays)
    has_2030 = any(d.year == 2030 for d in holidays)
    
    assert has_2028, "2028 holidays missing"
    assert has_2029, "2029 holidays missing"
    assert has_2030, "2030 holidays missing"
    
    print(f"  ✅ Holiday takvimi: 2026-2030 arası {len(holidays)} tatil günü")
    print(f"     2028: {sum(1 for d in holidays if d.year == 2028)} gün")
    print(f"     2029: {sum(1 for d in holidays if d.year == 2029)} gün")
    print(f"     2030: {sum(1 for d in holidays if d.year == 2030)} gün")


def test_force_price_refresh():
    """Test 10: Force price refresh metodu çalışıyor mu?"""
    print("\n=== TEST 10: Force Price Refresh ===")
    
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        db_path = tmp.name
    
    try:
        store = PaperStateStore(db_path=db_path)
        portfolio = VirtualPortfolio(initial_capital=1_000_000, state_store=store)
        
        # Pozisyon ekle
        portfolio._positions = {
            "THYAO": {
                "ticker": "THYAO", "quantity": 100, "avg_cost": 280.0,
                "current_price": 280.0, "market_value": 28000, "sector": "ULAŞTIRMA"
            },
            "GARAN": {
                "ticker": "GARAN", "quantity": 200, "avg_cost": 120.0,
                "current_price": 120.0, "market_value": 24000, "sector": "BANKA"
            }
        }
        
        # Force refresh (Redis yoksa mevcut fiyatları korumalı)
        updated = portfolio.force_refresh_prices("2026-08-25")
        
        # Redis yoksa güncelleme olmaz ama crash de olmaz
        print(f"  ✅ Force price refresh: {len(updated)} fiyat güncellendi")
        print(f"     Pozisyon sayısı: {len(portfolio._positions)}")
        print(f"     Crash yok, graceful degradation")
        
    finally:
        os.unlink(db_path)


if __name__ == "__main__":
    print("╔══════════════════════════════════════════════════════════╗")
    print("║   PC KAPALI KALMA SENARYOLARI — RECOVERY TEST SUITE    ║")
    print("╚══════════════════════════════════════════════════════════╝")
    
    tests = [
        test_gap_detection,
        test_multi_day_t2_roll,
        test_pending_signal_expiry,
        test_kill_switch_auto_reset,
        test_equity_curve_gap_fill,
        test_no_gap_scenario,
        test_first_run_scenario,
        test_docker_restart_policy,
        test_holiday_calendar_extended,
        test_force_price_refresh,
    ]
    
    passed = 0
    failed = 0
    
    for test in tests:
        try:
            test()
            passed += 1
        except Exception as e:
            print(f"  ❌ FAILED: {e}")
            failed += 1
    
    print("\n" + "=" * 60)
    print(f"SONUÇ: {passed} passed, {failed} failed, {len(tests)} total")
    print("=" * 60)
    
    sys.exit(1 if failed > 0 else 0)
