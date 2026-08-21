#!/usr/bin/env python3
"""
Portfolio Service v2.0 — Async DB-backed Testleri
"""

import sys
import os

import asyncio
from services.portfolio.main import PortfolioService
from services.core.database_dev import dev_db


async def reset_test_db():
    """Test DB'sini sıfırla."""
    if dev_db._db is None:
        await dev_db.init()
    for tbl in ['daily_pnl', 'equity_snapshots', 'position_history', 'cash_ledger', 'positions', 'portfolios']:
        try:
            await dev_db.pg_execute(f"DELETE FROM {tbl}")
        except Exception:
            pass


async def seed_test_instruments():
    """Test için şirket ve enstrüman oluştur."""
    await dev_db.pg_execute("INSERT INTO sectors (code, name) VALUES ('AVIATION', 'H') ON CONFLICT (code) DO NOTHING")
    await dev_db.pg_execute("INSERT INTO sectors (code, name) VALUES ('BANK', 'B') ON CONFLICT (code) DO NOTHING")
    await dev_db.pg_execute(
        "INSERT INTO companies (ticker, name, sector_id) SELECT 'THYAO', 'T', id FROM sectors WHERE code = 'AVIATION' ON CONFLICT (ticker) DO NOTHING"
    )
    await dev_db.pg_execute(
        "INSERT INTO companies (ticker, name, sector_id) SELECT 'GARAN', 'G', id FROM sectors WHERE code = 'BANK' ON CONFLICT (ticker) DO NOTHING"
    )
    await dev_db.pg_execute(
        "INSERT INTO instruments (company_id, symbol) SELECT id, 'THYAO' FROM companies WHERE ticker = 'THYAO' ON CONFLICT (symbol) DO NOTHING"
    )
    await dev_db.pg_execute(
        "INSERT INTO instruments (company_id, symbol) SELECT id, 'GARAN' FROM companies WHERE ticker = 'GARAN' ON CONFLICT (symbol) DO NOTHING"
    )


async def get_instrument_id(symbol: str) -> int:
    row = await dev_db.pg_fetchrow("SELECT id FROM instruments WHERE symbol = ?", symbol)
    return row["id"] if row else 0


async def make_service(capital: float = 100000) -> PortfolioService:
    """Temiz bir PortfolioService oluştur."""
    await reset_test_db()
    await seed_test_instruments()
    svc = PortfolioService(initial_capital=capital)
    await svc.start()
    return svc


# ============================================================
# TESTS
# ============================================================

async def test_service_lifecycle():
    svc = await make_service()
    issues = []

    if not svc._running:
        issues.append("Servis başlatılamadı")
    if svc._portfolio_id is None:
        issues.append("Portfolio ID yok")

    await svc.stop()
    if svc._running:
        issues.append("Servis durdurulamadı")

    return "Service Lifecycle", len(issues) == 0, issues


async def test_execute_buy():
    svc = await make_service()
    issues = []

    thyao_id = await get_instrument_id("THYAO")
    result = await svc.execute_buy("THYAO", 100, 250.0, instrument_id=thyao_id)
    if not result.get("success"):
        issues.append(f"Alım başarısız: {result}")

    pf = await svc.get_portfolio()
    if pf["positions_count"] != 1:
        issues.append(f"Pozisyon sayısı yanlış: {pf['positions_count']}")

    acc = await svc.get_accounting()
    if not acc["invariant_check"]:
        issues.append(f"Invariant bozuldu")

    # DB kontrolü
    positions = await dev_db.pg_fetch("SELECT * FROM positions WHERE status = 'OPEN'")
    if len(positions) != 1:
        issues.append(f"DB pozisyon sayısı: {len(positions)}")

    cash = await dev_db.pg_fetch("SELECT * FROM cash_ledger")
    if len(cash) < 1:
        issues.append("DB cash ledger boş")

    await svc.stop()
    return "Execute Buy", len(issues) == 0, issues


async def test_execute_sell():
    svc = await make_service()
    issues = []

    thyao_id = await get_instrument_id("THYAO")
    await svc.execute_buy("THYAO", 100, 250.0, instrument_id=thyao_id)
    await svc.update_prices({"THYAO": 270})

    result = await svc.execute_sell("THYAO", 100, 270.0, instrument_id=thyao_id)
    if not result.get("success"):
        issues.append(f"Satış başarısız: {result}")

    realized = result.get("realized_pnl", 0)
    if realized <= 0:
        issues.append(f"Realized P&L negatif: {realized}")

    pf = await svc.get_portfolio()
    if pf["positions_count"] != 0:
        issues.append(f"Pozisyon kapanmamış: {pf['positions_count']}")

    # DB kontrolü
    positions = await dev_db.pg_fetch("SELECT * FROM positions WHERE status = 'OPEN'")
    if len(positions) != 0:
        issues.append(f"DB pozisyon kapanmamış: {len(positions)}")

    await svc.stop()
    return "Execute Sell", len(issues) == 0, issues


async def test_equity_invariant():
    svc = await make_service()
    issues = []

    thyao_id = await get_instrument_id("THYAO")
    garan_id = await get_instrument_id("GARAN")

    await svc.execute_buy("THYAO", 100, 250.0, instrument_id=thyao_id)
    await svc.execute_buy("GARAN", 200, 100.0, instrument_id=garan_id)
    await svc.update_prices({"THYAO": 260, "GARAN": 95})

    acc = await svc.get_accounting()
    if not acc["invariant_check"]:
        issues.append(f"Invariant bozuldu: {acc['total_equity']} != {acc['cash']} + {acc['market_value']}")

    await svc.stop()
    return "Equity Invariant", len(issues) == 0, issues


async def test_cash_ledger_db():
    svc = await make_service()
    issues = []

    thyao_id = await get_instrument_id("THYAO")
    await svc.execute_buy("THYAO", 100, 250.0, instrument_id=thyao_id)
    await svc.execute_sell("THYAO", 100, 270.0, instrument_id=thyao_id)

    ledger = await svc.get_cash_ledger()
    if len(ledger) < 2:
        issues.append(f"Cash ledger eksik: {len(ledger)} kayıt")

    buy_entries = [e for e in ledger if e["entry_type"] == "BUY"]
    sell_entries = [e for e in ledger if e["entry_type"] == "SELL"]

    if len(buy_entries) == 0:
        issues.append("BUY cash ledger kaydı yok")
    if len(sell_entries) == 0:
        issues.append("SELL cash ledger kaydı yok")

    await svc.stop()
    return "Cash Ledger DB", len(issues) == 0, issues


async def test_position_history_db():
    svc = await make_service()
    issues = []

    thyao_id = await get_instrument_id("THYAO")
    await svc.execute_buy("THYAO", 100, 250.0, instrument_id=thyao_id)
    await svc.execute_sell("THYAO", 50, 260.0, instrument_id=thyao_id)

    hist = await svc.get_position_history("THYAO")
    if len(hist) < 2:
        issues.append(f"Position history eksik: {len(hist)} kayıt")

    open_entries = [e for e in hist if e["action"] == "OPEN"]
    reduce_entries = [e for e in hist if e["action"] in ("REDUCE", "CLOSE")]

    if len(open_entries) == 0:
        issues.append("OPEN position history kaydı yok")
    if len(reduce_entries) == 0:
        issues.append("REDUCE/CLOSE position history kaydı yok")

    await svc.stop()
    return "Position History DB", len(issues) == 0, issues


async def test_equity_snapshots_db():
    svc = await make_service()
    issues = []

    thyao_id = await get_instrument_id("THYAO")
    await svc.execute_buy("THYAO", 100, 250.0, instrument_id=thyao_id)
    await svc.update_prices({"THYAO": 260})

    snapshots = await svc.get_equity_snapshots()
    if len(snapshots) == 0:
        issues.append("Equity snapshot yok")

    await svc.stop()
    return "Equity Snapshots DB", len(issues) == 0, issues


async def test_weighted_avg_cost_db():
    svc = await make_service()
    issues = []

    thyao_id = await get_instrument_id("THYAO")
    await svc.execute_buy("THYAO", 100, 250.0, instrument_id=thyao_id)
    await svc.execute_buy("THYAO", 50, 260.0, instrument_id=thyao_id)

    pf = await svc.get_portfolio()
    pos = None
    for p in pf["positions"]:
        if p["ticker"] == "THYAO":
            pos = p
            break

    if not pos:
        issues.append("THYAO pozisyonu bulunamadı")
    else:
        expected_avg = (250 * 100 + 260 * 50) / 150
        if abs(pos["entry_price"] - expected_avg) > 0.1:
            issues.append(f"Weighted avg yanlış: {pos['entry_price']} != {expected_avg}")
        if pos["quantity"] != 150:
            issues.append(f"Miktar yanlış: {pos['quantity']} != 150")

    await svc.stop()
    return "Weighted Avg Cost DB", len(issues) == 0, issues


async def test_commission_accounting():
    svc = await make_service()
    issues = []

    thyao_id = await get_instrument_id("THYAO")
    await svc.execute_buy("THYAO", 100, 250.0, instrument_id=thyao_id)
    await svc.execute_sell("THYAO", 100, 250.0, instrument_id=thyao_id)

    acc = await svc.get_accounting()
    if acc["net_pnl"] >= 0:
        issues.append(f"Komisyon düşülmemiş: net_pnl={acc['net_pnl']}")

    ledger = await svc.get_cash_ledger()
    non_deposit = [e for e in ledger if e["entry_type"] != "DEPOSIT"]
    if len(non_deposit) < 2:
        issues.append(f"Cash ledger eksik: {len(non_deposit)} hareket")

    await svc.stop()
    return "Commission Accounting", len(issues) == 0, issues


# ============================================================
# RUN ALL TESTS
# ============================================================

async def run_all_tests():
    print("=" * 60)
    print("PORTFOLIO SERVICE v2.0 — ASYNC DB TESTLERİ")
    print("=" * 60)

    tests = [
        test_service_lifecycle,
        test_execute_buy,
        test_execute_sell,
        test_equity_invariant,
        test_cash_ledger_db,
        test_position_history_db,
        test_equity_snapshots_db,
        test_weighted_avg_cost_db,
        test_commission_accounting,
    ]

    total_pass = 0
    total_fail = 0
    all_issues = []

    for test_func in tests:
        try:
            name, passed, issues = await test_func()
        except Exception as e:
            name = test_func.__name__
            passed = False
            issues = [f"Exception: {e}"]

        icon = "✅" if passed else "❌"
        print(f"\n{icon} {name}")
        if passed:
            total_pass += 1
            print(f"   PASSED")
        else:
            total_fail += 1
            for issue in issues:
                print(f"   ❌ {issue}")
                all_issues.append(f"{name}: {issue}")

    print(f"\n{'=' * 60}")
    print(f"SONUÇ: {total_pass}/{total_pass + total_fail} geçti")
    if all_issues:
        print(f"\nTÜM HATALAR:")
        for i, issue in enumerate(all_issues, 1):
            print(f"  {i}. {issue}")
    print("=" * 60)

    return total_fail == 0


def main():
    success = asyncio.run(run_all_tests())
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
