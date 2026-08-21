#!/usr/bin/env python3
"""
Portfolio State Recovery Testi

Senaryo:
1. Portfolio oluştur, alım/satış yap
2. Durumu kaydet (stop)
3. Yeni instance ile başlat (restart)
4. Tüm durumun birebir eşleştiğini doğrula
"""

import sys
import os

import asyncio
from services.portfolio.main import PortfolioService
from services.portfolio.portfolio_manager import PortfolioManager
from services.core.database_dev import dev_db


async def reset_db():
    if dev_db._db is None:
        await dev_db.init()
    for tbl in ['daily_pnl', 'equity_snapshots', 'position_history', 'cash_ledger', 'positions', 'portfolios']:
        try:
            await dev_db.pg_execute(f"DELETE FROM {tbl}")
        except Exception:
            pass


async def seed_instruments():
    await dev_db.pg_execute("INSERT INTO sectors (code, name) VALUES ('AVIATION', 'H') ON CONFLICT (code) DO NOTHING")
    await dev_db.pg_execute("INSERT INTO sectors (code, name) VALUES ('BANK', 'B') ON CONFLICT (code) DO NOTHING")
    await dev_db.pg_execute("INSERT INTO companies (ticker, name, sector_id) SELECT 'THYAO', 'T', id FROM sectors WHERE code = 'AVIATION' ON CONFLICT (ticker) DO NOTHING")
    await dev_db.pg_execute("INSERT INTO companies (ticker, name, sector_id) SELECT 'GARAN', 'G', id FROM sectors WHERE code = 'BANK' ON CONFLICT (ticker) DO NOTHING")
    await dev_db.pg_execute("INSERT INTO instruments (company_id, symbol) SELECT id, 'THYAO' FROM companies WHERE ticker = 'THYAO' ON CONFLICT (symbol) DO NOTHING")
    await dev_db.pg_execute("INSERT INTO instruments (company_id, symbol) SELECT id, 'GARAN' FROM companies WHERE ticker = 'GARAN' ON CONFLICT (symbol) DO NOTHING")


async def get_iid(symbol: str) -> int:
    row = await dev_db.pg_fetchrow("SELECT id FROM instruments WHERE symbol = ?", symbol)
    return row["id"] if row else 0


async def test_restart_recovery():
    """Tam restart recovery testi."""
    issues = []

    # ========== PHASE 1: Portfolio oluştur ve işlem yap ==========
    await reset_db()
    await seed_instruments()
    thyao_id = await get_iid("THYAO")
    garan_id = await get_iid("GARAN")

    svc1 = PortfolioService(initial_capital=100000)
    await svc1.start()

    # Alım yap
    await svc1.execute_buy("THYAO", 100, 250.0, instrument_id=thyao_id)
    await svc1.execute_buy("GARAN", 200, 100.0, instrument_id=garan_id)

    # Fiyat güncelle
    await svc1.update_prices({"THYAO": 260, "GARAN": 95})

    # Kısmi sat
    await svc1.execute_sell("THYAO", 50, 270.0, instrument_id=thyao_id)

    # Durumu kaydet
    state_before = {
        "portfolio": await svc1.get_portfolio(),
        "accounting": await svc1.get_accounting(),
        "metrics": await svc1.get_metrics(),
        "cash_ledger": await svc1.get_cash_ledger(),
        "position_history": await svc1.get_position_history(),
        "equity_snapshots": await svc1.get_equity_snapshots(),
        "trade_history": await svc1.get_trade_history(),
    }

    # Sistemi kapat
    await svc1.stop()

    # ========== PHASE 2: Sistemi yeniden başlat ==========
    svc2 = PortfolioService(initial_capital=100000)
    await svc2.start()

    # Durumu yükle
    state_after = {
        "portfolio": await svc2.get_portfolio(),
        "accounting": await svc2.get_accounting(),
        "metrics": await svc2.get_metrics(),
        "cash_ledger": await svc2.get_cash_ledger(),
        "position_history": await svc2.get_position_history(),
        "equity_snapshots": await svc2.get_equity_snapshots(),
        "trade_history": await svc2.get_trade_history(),
    }

    # ========== PHASE 3: Karşılaştır ==========

    # Cash
    cash_before = state_before["portfolio"]["cash"]
    cash_after = state_after["portfolio"]["cash"]
    if abs(cash_before - cash_after) > 0.01:
        issues.append(f"Cash farklı: {cash_before} != {cash_after}")

    # Total value
    tv_before = state_before["portfolio"]["total_value"]
    tv_after = state_after["portfolio"]["total_value"]
    if abs(tv_before - tv_after) > 0.01:
        issues.append(f"Total value farklı: {tv_before} != {tv_after}")

    # Positions count
    pc_before = state_before["portfolio"]["positions_count"]
    pc_after = state_after["portfolio"]["positions_count"]
    if pc_before != pc_after:
        issues.append(f"Pozisyon sayısı farklı: {pc_before} != {pc_after}")

    # Position details
    pos_before = {p["ticker"]: p for p in state_before["portfolio"]["positions"]}
    pos_after = {p["ticker"]: p for p in state_after["portfolio"]["positions"]}
    for ticker in pos_before:
        if ticker not in pos_after:
            issues.append(f"Pozisyon eksik: {ticker}")
            continue
        pb = pos_before[ticker]
        pa = pos_after[ticker]
        if pb["quantity"] != pa["quantity"]:
            issues.append(f"{ticker} quantity: {pb['quantity']} != {pa['quantity']}")
        if abs(pb["entry_price"] - pa["entry_price"]) > 0.01:
            issues.append(f"{ticker} entry_price: {pb['entry_price']} != {pa['entry_price']}")

    # Realized P&L
    rp_before = state_before["accounting"]["realized_pnl_total"]
    rp_after = state_after["accounting"]["realized_pnl_total"]
    if abs(rp_before - rp_after) > 0.01:
        issues.append(f"Realized P&L farklı: {rp_before} != {rp_after}")

    # Commission total
    ct_before = state_before["accounting"]["commission_total"]
    ct_after = state_after["accounting"]["commission_total"]
    if abs(ct_before - ct_after) > 0.01:
        issues.append(f"Commission total farklı: {ct_before} != {ct_after}")

    # Invariant
    if not state_after["accounting"]["invariant_check"]:
        issues.append("Invariant bozuldu after restart")

    # Cash ledger count
    cl_before = len(state_before["cash_ledger"])
    cl_after = len(state_after["cash_ledger"])
    if cl_before != cl_after:
        issues.append(f"Cash ledger kayıt sayısı: {cl_before} != {cl_after}")

    # Position history count
    ph_before = len(state_before["position_history"])
    ph_after = len(state_after["position_history"])
    if ph_before != ph_after:
        issues.append(f"Position history kayıt sayısı: {ph_before} != {ph_after}")

    # Trade history (restore edilen)
    th_before = len(state_before["trade_history"])
    th_after = len(state_after["trade_history"])
    if th_before != th_after:
        issues.append(f"Trade history kayıt sayısı: {th_before} != {th_after}")

    # HWM
    hwm = svc2._pm.get_high_water_mark()
    if hwm < 100000:
        issues.append(f"HWM başlangıçtan düşük: {hwm}")

    # Equity curve points
    ec_after = await svc2.get_equity_snapshots()
    if len(ec_after) == 0:
        issues.append("Equity curve boş after restart")

    await svc2.stop()

    return "Restart Recovery", len(issues) == 0, issues


async def test_restart_empty():
    """Boş portfolio restart testi."""
    issues = []

    await reset_db()
    await seed_instruments()

    # Oluştur ve hemen kapat
    svc1 = PortfolioService(initial_capital=50000)
    await svc1.start()
    state_before = {"portfolio": await svc1.get_portfolio()}
    await svc1.stop()

    # Restart
    svc2 = PortfolioService(initial_capital=50000)
    await svc2.start()
    state_after = {"portfolio": await svc2.get_portfolio()}

    if abs(state_before["portfolio"]["cash"] - state_after["portfolio"]["cash"]) > 0.01:
        issues.append(f"Cash farklı: {state_before['portfolio']['cash']} != {state_after['portfolio']['cash']}")

    if state_after["portfolio"]["positions_count"] != 0:
        issues.append(f"Pozisyon sayısı 0 değil: {state_after['portfolio']['positions_count']}")

    await svc2.stop()
    return "Restart Empty", len(issues) == 0, issues


async def test_restart_multiple_cycles():
    """Çoklu restart döngüsü testi."""
    issues = []

    await reset_db()
    await seed_instruments()
    thyao_id = await get_iid("THYAO")

    # Döngü 1: Al
    svc = PortfolioService(initial_capital=100000)
    await svc.start()
    await svc.execute_buy("THYAO", 100, 250.0, instrument_id=thyao_id)
    await svc.stop()

    # Döngü 2: Fiyat güncelle + yeni alım
    svc = PortfolioService(initial_capital=100000)
    await svc.start()
    pf = await svc.get_portfolio()
    if pf["positions_count"] != 1:
        issues.append(f"Döngü 2 pozisyon sayısı: {pf['positions_count']}")
    await svc.update_prices({"THYAO": 260})
    await svc.execute_buy("THYAO", 50, 260.0, instrument_id=thyao_id)
    await svc.stop()

    # Döngü 3: Kontrol + sat
    svc = PortfolioService(initial_capital=100000)
    await svc.start()
    pf = await svc.get_portfolio()
    if pf["positions_count"] != 1:
        issues.append(f"Döngü 3 pozisyon sayısı: {pf['positions_count']}")
    # 150 adet olmalı
    pos = pf["positions"][0] if pf["positions"] else None
    if pos and pos["quantity"] != 150:
        issues.append(f"Döngü 3 quantity: {pos['quantity']} != 150")
    await svc.execute_sell("THYAO", 150, 270.0, instrument_id=thyao_id)
    await svc.stop()

    # Döngü 4: Temiz portföy
    svc = PortfolioService(initial_capital=100000)
    await svc.start()
    pf = await svc.get_portfolio()
    if pf["positions_count"] != 0:
        issues.append(f"Döngü 4 pozisyon sayısı: {pf['positions_count']}")
    acc = await svc.get_accounting()
    if acc["realized_pnl_total"] <= 0:
        issues.append(f"Döngü 4 realized P&L: {acc['realized_pnl_total']}")
    await svc.stop()

    return "Multiple Restart Cycles", len(issues) == 0, issues


# ============================================================
# RUN
# ============================================================

async def run_all():
    print("=" * 60)
    print("PORTFOLIO STATE RECOVERY TESTLERİ")
    print("=" * 60)

    tests = [
        test_restart_recovery,
        test_restart_empty,
        test_restart_multiple_cycles,
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
