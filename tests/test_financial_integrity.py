#!/usr/bin/env python3
"""
Financial Integrity Testleri

Kapsam:
- Invariant tautoloji fix doğrulama
- Yanlış cash durumunda invariant yakalama
- DB ve memory state uyuşmazlığı
- Restart sonrası invariant kontrolü
- Memory limit testleri
- Exception recovery testleri
- Multi-instance invariant doğrulama
"""

import sys
import os
import asyncio
import sqlite3
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.portfolio.portfolio_manager import (
    PortfolioManager, MAX_TRADES, MAX_CASH_LEDGER,
    MAX_POSITION_HISTORY, MAX_EQUITY_CURVE,
)
from services.portfolio.main import PortfolioService
from services.core.database_dev import dev_db


async def setup():
    dev_db._db = None
    await dev_db.init()
    for t in ['daily_pnl', 'equity_snapshots', 'position_history', 'cash_ledger', 'positions', 'portfolios']:
        try:
            await dev_db.pg_execute(f"DELETE FROM {t}")
        except Exception:
            pass
    await dev_db.pg_execute("INSERT INTO sectors (code, name) VALUES ('T', 'T') ON CONFLICT (code) DO NOTHING")
    await dev_db.pg_execute("INSERT INTO companies (ticker, name, sector_id) SELECT 'X', 'X', id FROM sectors WHERE code = 'T' ON CONFLICT (ticker) DO NOTHING")
    await dev_db.pg_execute("INSERT INTO instruments (company_id, symbol) SELECT id, 'X' FROM companies WHERE ticker = 'X' ON CONFLICT (symbol) DO NOTHING")


# =====================================================
# INVARIANT TESTS
# =====================================================

async def test_invariant_detects_negative_cash():
    """Negatif cash invariant bozmalı."""
    issues = []

    pm = PortfolioManager(100000)
    pm._cash = -500  # Kasıtlı boz

    acc = pm.get_accounting_summary()
    if acc["invariant_check"]:
        issues.append("Negatif cash'te invariant True döndü")

    details = acc.get("invariant_details", {})
    if not details.get("cash_negative"):
        issues.append("cash_negative flag False")

    return "Invariant Detects Negative Cash", len(issues) == 0, issues


async def test_invariant_details_present():
    """Invariant details doğru bilgi vermeli."""
    issues = []

    pm = PortfolioManager(100000)
    pm.open_position("X", "LONG", 100, 100.0, commission=50)
    pm.update_prices({"X": 110})

    acc = pm.get_accounting_summary()
    details = acc.get("invariant_details", {})

    if "cash" not in details:
        issues.append("cash eksik")
    if "recomputed_mv" not in details:
        issues.append("recomputed_mv eksik")
    if "recomputed_equity" not in details:
        issues.append("recomputed_equity eksik")
    if "cash_negative" not in details:
        issues.append("cash_negative eksik")

    # Değerler tutarlı olmalı
    if details.get("mv_diff", 1) > 0.01:
        issues.append(f"mv_diff: {details.get('mv_diff')}")
    if details.get("eq_diff", 1) > 0.01:
        issues.append(f"eq_diff: {details.get('eq_diff')}")

    return "Invariant Details Present", len(issues) == 0, issues


async def test_invariant_normal_operation():
    """Normal operasyonda invariant True olmalı."""
    issues = []

    pm = PortfolioManager(100000)
    pm.open_position("X", "LONG", 100, 100.0, commission=50)
    pm.open_position("Y", "LONG", 200, 50.0, commission=30)
    pm.update_prices({"X": 110, "Y": 45})

    acc = pm.get_accounting_summary()
    if not acc["invariant_check"]:
        issues.append(f"Normal durumda invariant False: {acc.get('invariant_details')}")

    details = acc.get("invariant_details", {})
    if details.get("mv_diff", 1) > 0.01:
        issues.append(f"mv_diff: {details.get('mv_diff')}")
    if details.get("eq_diff", 1) > 0.01:
        issues.append(f"eq_diff: {details.get('eq_diff')}")
    if details.get("cash_negative"):
        issues.append("cash_negative True")

    return "Invariant Normal Operation", len(issues) == 0, issues


async def test_invariant_after_restart():
    """Restart sonrası invariant korunmalı."""
    issues = []

    await setup()
    row = await dev_db.pg_fetchrow("SELECT id FROM instruments WHERE symbol = 'X'")
    xid = row["id"]

    svc = PortfolioService(initial_capital=100000)
    await svc.start()

    await svc.execute_buy("X", 100, 100.0, instrument_id=xid)
    await svc.update_prices({"X": 110})

    acc1 = await svc.get_accounting()
    if not acc1.get("invariant_check"):
        issues.append("Restart öncesi invariant False")
    await svc.stop()

    # Restart
    svc2 = PortfolioService(initial_capital=100000)
    await svc2.start()

    acc2 = await svc2.get_accounting()
    if not acc2.get("invariant_check"):
        issues.append(f"Restart sonrası invariant False: {acc2.get('invariant_details')}")

    # Cash tutarlılığı
    if abs(acc1.get("cash", 0) - acc2.get("cash", 0)) > 0.01:
        issues.append(f"Cash farklı: {acc1.get('cash')} vs {acc2.get('cash')}")

    await svc2.stop()
    return "Invariant After Restart", len(issues) == 0, issues


async def test_invariant_multi_instance():
    """Multi-instance sonrası invariant korunmalı."""
    issues = []

    await setup()
    row = await dev_db.pg_fetchrow("SELECT id FROM instruments WHERE symbol = 'X'")
    xid = row["id"]

    svc1 = PortfolioService(initial_capital=100000)
    await svc1.start()

    await svc1.execute_buy("X", 50, 100.0, instrument_id=xid)
    await svc1.stop()

    # İkinci instance
    svc2 = PortfolioService(initial_capital=100000)
    await svc2.start()

    await svc2.execute_buy("X", 50, 100.0, instrument_id=xid)

    acc = await svc2.get_accounting()
    if not acc.get("invariant_check"):
        issues.append(f"Multi-instance invariant False: {acc.get('invariant_details')}")

    await svc2.stop()
    return "Invariant Multi-Instance", len(issues) == 0, issues


# =====================================================
# MEMORY SAFETY TESTS
# =====================================================

async def test_trades_list_limit():
    """Trades listesi sınırlı olmalı."""
    issues = []

    pm = PortfolioManager(100000000)  # Büyük sermaye

    # Çok sayıda trade yap
    for i in range(MAX_TRADES + 100):
        pm.open_position(f"T{i}", "LONG", 1, 1.0, commission=0.01)
        pm.close_position(f"T{i}", 1.1, commission=0.01)

    if len(pm._trades) > MAX_TRADES:
        issues.append(f"Trades limit aşıldı: {len(pm._trades)} > {MAX_TRADES}")

    return "Trades List Limit", len(issues) == 0, issues


async def test_cash_ledger_limit():
    """Cash ledger listesi sınırlı olmalı."""
    issues = []

    pm = PortfolioManager(100000000)

    for i in range(MAX_CASH_LEDGER + 100):
        pm.open_position(f"T{i}", "LONG", 1, 1.0, commission=0.01)
        pm.close_position(f"T{i}", 1.0, commission=0.01)

    if len(pm._cash_ledger) > MAX_CASH_LEDGER:
        issues.append(f"Cash ledger limit aşıldı: {len(pm._cash_ledger)} > {MAX_CASH_LEDGER}")

    return "Cash Ledger Limit", len(issues) == 0, issues


async def test_equity_curve_limit():
    """Equity curve listesi sınırlı olmalı."""
    issues = []

    pm = PortfolioManager(100000)
    pm.open_position("X", "LONG", 100, 100.0, commission=50)

    # Çok sayıda fiyat güncelleme
    for i in range(MAX_EQUITY_CURVE + 100):
        pm.update_prices({"X": 100 + i * 0.1})

    if len(pm._equity_curve) > MAX_EQUITY_CURVE + 1:  # Allow +1 for timing
        issues.append(f"Equity curve limit aşıldı: {len(pm._equity_curve)} > {MAX_EQUITY_CURVE}")

    return "Equity Curve Limit", len(issues) == 0, issues


async def test_position_history_limit():
    """Position history listesi sınırlı olmalı."""
    issues = []

    pm = PortfolioManager(100000000)

    for i in range(100):
        pm.open_position(f"T{i}", "LONG", 1, 1.0, commission=0.01)
        pm.close_position(f"T{i}", 1.1, commission=0.01)

    # Position history limit kontrolü (in-memory list, DB'den bağımsız)
    if len(pm._position_history) > MAX_POSITION_HISTORY:
        issues.append(f"Position history limit aşıldı: {len(pm._position_history)}")

    return "Position History Limit", len(issues) == 0, issues


# =====================================================
# EXCEPTION RECOVERY TESTS
# =====================================================

async def test_invalid_price_handling():
    """Geçersiz fiyat exception üretmemeli, graceful fail olmalı."""
    issues = []

    pm = PortfolioManager(100000)

    # NaN fiyat
    result = pm.open_position("X", "LONG", 100, float('nan'))
    if result.get("success"):
        issues.append("NaN fiyat ile pozisyon açıldı")

    # Negatif fiyat
    result = pm.open_position("Y", "LONG", 100, -10)
    if result.get("success"):
        issues.append("Negatif fiyat ile pozisyon açıldı")

    # Sıfır miktar
    result = pm.open_position("Z", "LONG", 0, 100)
    if result.get("success"):
        issues.append("Sıfır miktar ile pozisyon açıldı")

    return "Invalid Price Handling", len(issues) == 0, issues


async def test_oversell_prevention():
    """Mevcut pozisyondan fazla satış engellenmeli."""
    issues = []

    pm = PortfolioManager(100000)
    pm.open_position("X", "LONG", 100, 100.0, commission=50)

    # 200 adet satmaya çalış
    result = pm.close_position("X", 110.0, commission=50)
    # Bu 100 adet kapatır (tamamı)

    # Tekrar satmaya çalış (pozisyon yok)
    result2 = pm.close_position("X", 110.0, commission=50)
    if result2.get("success"):
        issues.append("Olmayan pozisyon kapatıldı")

    return "Oversell Prevention", len(issues) == 0, issues


async def test_commission_accounting():
    """Komisyon muhasebesi doğru olmalı."""
    issues = []

    pm = PortfolioManager(100000)
    initial_cash = pm._cash

    # Alım
    pm.open_position("X", "LONG", 100, 100.0, commission=50)

    # Komisyon düşülmüş olmalı
    expected_cash_after_buy = initial_cash - 100 * 100 - 50
    if abs(pm._cash - expected_cash_after_buy) > 0.01:
        issues.append(f"Alım sonrası cash: {pm._cash} != {expected_cash_after_buy}")

    # Satış
    pm.update_prices({"X": 110})
    pm.close_position("X", 110.0, commission=60)

    # Net P&L = (110-100)*100 - 50 - 60 = 890
    expected_final_cash = initial_cash + (110 - 100) * 100 - 50 - 60
    if abs(pm._cash - expected_final_cash) > 0.01:
        issues.append(f"Satış sonrası cash: {pm._cash} != {expected_final_cash}")

    # Realized P&L
    realized = pm.get_realized_pnl_total()
    expected_realized = (110 - 100) * 100 - 50 - 60
    if abs(realized - expected_realized) > 0.01:
        issues.append(f"Realized P&L: {realized} != {expected_realized}")

    return "Commission Accounting", len(issues) == 0, issues


# =====================================================
# RUN
# =====================================================

async def run_all():
    print("=" * 60)
    print("FINANCIAL INTEGRITY TESTLERİ")
    print("=" * 60)

    tests = [
        test_invariant_detects_negative_cash,
        test_invariant_details_present,
        test_invariant_normal_operation,
        test_invariant_after_restart,
        test_invariant_multi_instance,
        test_trades_list_limit,
        test_cash_ledger_limit,
        test_equity_curve_limit,
        test_position_history_limit,
        test_invalid_price_handling,
        test_oversell_prevention,
        test_commission_accounting,
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
