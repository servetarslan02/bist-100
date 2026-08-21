#!/usr/bin/env python3
"""
Multi-Instance Race Condition Testleri

İki ayrı PortfolioService instance'ı aynı anda aynı hesaba işlem yapar.
Sonuçta equity, cash ve positions tutarlı kalmalı.
"""

import sys
import os

import asyncio
from services.portfolio.main import PortfolioService
from services.core.database_dev import dev_db


async def setup_db():
    """Test DB'sini hazırla."""
    dev_db._db = None
    await dev_db.init()
    from conftest import safe_cleanup_tables
    await safe_cleanup_tables(dev_db)
    # Instruments
    await dev_db.pg_execute("INSERT INTO sectors (code, name) VALUES ('T', 'T') ON CONFLICT (code) DO NOTHING")
    await dev_db.pg_execute("INSERT INTO companies (ticker, name, sector_id) SELECT 'THYAO', 'T', id FROM sectors WHERE code = 'T' ON CONFLICT (ticker) DO NOTHING")
    await dev_db.pg_execute("INSERT INTO companies (ticker, name, sector_id) SELECT 'GARAN', 'G', id FROM sectors WHERE code = 'T' ON CONFLICT (ticker) DO NOTHING")
    await dev_db.pg_execute("INSERT INTO instruments (company_id, symbol) SELECT id, 'THYAO' FROM companies WHERE ticker = 'THYAO' ON CONFLICT (symbol) DO NOTHING")
    await dev_db.pg_execute("INSERT INTO instruments (company_id, symbol) SELECT id, 'GARAN' FROM companies WHERE ticker = 'GARAN' ON CONFLICT (symbol) DO NOTHING")


async def get_iid(symbol: str) -> int:
    row = await dev_db.pg_fetchrow("SELECT id FROM instruments WHERE symbol = ?", symbol)
    return row["id"] if row else 0


async def test_parallel_buys():
    """İki instance paralel alım yapsın — toplam harcama tutarlı olmalı."""
    await setup_db()
    thyao_id = await get_iid("THYAO")
    issues = []

    svc1 = PortfolioService(initial_capital=100000)
    svc2 = PortfolioService(initial_capital=100000)
    await svc1.start()
    await svc2.start()

    # Paralel alım — aynı anda
    async def buy1():
        return await svc1.execute_buy("THYAO", 50, 100.0, instrument_id=thyao_id)

    async def buy2():
        return await svc2.execute_buy("THYAO", 50, 100.0, instrument_id=thyao_id)

    r1, r2 = await asyncio.gather(buy1(), buy2())

    # En az biri başarılı olmalı
    if not r1.get("success") and not r2.get("success"):
        issues.append("Her iki alım da başarısız")

    # DB'deki toplam pozisyon tutarlı olmalı
    pf_row = await dev_db.pg_fetchrow("SELECT cash_balance, initial_capital FROM portfolios WHERE id = ?", svc1._portfolio_id)
    if pf_row:
        cash = float(pf_row["cash_balance"])
        initial = float(pf_row["initial_capital"])
        # Toplam harcanan: her iki alımın toplamı
        # Ama sadece başarılı olanlar harcama yaptı
        positions = await dev_db.pg_fetch("SELECT SUM(quantity) as qty FROM positions WHERE portfolio_id = ? AND status = 'OPEN'", svc1._portfolio_id)
        total_qty = int(positions[0]["qty"] or 0) if positions else 0

        # Cash + pozisyon maliyeti = initial capital olmalı (komisyon hariç approximate)
        expected_cash = initial - total_qty * 100  # Yaklaşık
        if abs(cash - expected_cash) > 200:  # Komisyon toleransı
            issues.append(f"Cash tutarsız: {cash}, beklenen ~{expected_cash} (qty={total_qty})")

    await svc1.stop()
    await svc2.stop()
    return "Parallel Buys", len(issues) == 0, issues


async def test_concurrent_buy_sell():
    """Bir instance alırken diğeri satmaya çalışsın — tutarlılık korunmalı."""
    await setup_db()
    thyao_id = await get_iid("THYAO")
    issues = []

    svc1 = PortfolioService(initial_capital=100000)
    await svc1.start()

    # Önce al
    await svc1.execute_buy("THYAO", 100, 100.0, instrument_id=thyao_id)

    # Şimdi iki instance paralel satmaya çalışsın
    svc2 = PortfolioService(initial_capital=100000)
    await svc2.start()

    async def sell1():
        return await svc1.execute_sell("THYAO", 100, 110.0, instrument_id=thyao_id)

    async def sell2():
        return await svc2.execute_sell("THYAO", 100, 110.0, instrument_id=thyao_id)

    r1, r2 = await asyncio.gather(sell1(), sell2())

    # Sadece biri başarılı olmalı (diğeri oversell veya pozisyon yok)
    success_count = sum(1 for r in [r1, r2] if r.get("success"))
    if success_count > 1:
        issues.append(f"Her iki satış da başarılı oldu (oversell!): {success_count}")

    # Pozisyon kapanmış olmalı
    positions = await dev_db.pg_fetch(
        "SELECT * FROM positions WHERE portfolio_id = ? AND status = 'OPEN'",
        svc1._portfolio_id
    )
    total_qty = sum(int(p["quantity"]) for p in positions) if positions else 0
    if total_qty > 0:
        issues.append(f"Pozisyon kapanmamış: {total_qty} adet kaldı")

    await svc1.stop()
    await svc2.stop()
    return "Concurrent Buy/Sell", len(issues) == 0, issues


async def test_invariant_after_parallel_ops():
    """Paralel işlemler sonrası invariant korunmalı."""
    await setup_db()
    thyao_id = await get_iid("THYAO")
    garan_id = await get_iid("GARAN")
    issues = []

    svc1 = PortfolioService(initial_capital=100000)
    svc2 = PortfolioService(initial_capital=100000)
    await svc1.start()
    await svc2.start()

    # Paralel farklı hisse alımları
    async def ops1():
        await svc1.execute_buy("THYAO", 50, 250.0, instrument_id=thyao_id)
        await svc1.update_prices({"THYAO": 260})

    async def ops2():
        await svc2.execute_buy("GARAN", 100, 100.0, instrument_id=garan_id)
        await svc2.update_prices({"GARAN": 95})

    await asyncio.gather(ops1(), ops2())

    # Her iki instance'ın son durumunu kontrol et
    acc1 = await svc1.get_accounting()
    acc2 = await svc2.get_accounting()

    # Invariant kontrolü
    if not acc1.get("invariant_check", True):
        issues.append(f"SVC1 invariant bozuldu")
    if not acc2.get("invariant_check", True):
        issues.append(f"SVC2 invariant bozuldu")

    # Cash tutarlılığı
    pf_row = await dev_db.pg_fetchrow("SELECT cash_balance FROM portfolios WHERE id = ?", svc1._portfolio_id)
    if pf_row:
        cash = float(pf_row["cash_balance"])
        if cash < 0:
            issues.append(f"Negatif cash: {cash}")

    await svc1.stop()
    await svc2.stop()
    return "Invariant After Parallel Ops", len(issues) == 0, issues


async def test_restart_during_trade():
    """Bir instance işlem yaparken diğeri restart etsin — veri kaybı olmamalı."""
    await setup_db()
    thyao_id = await get_iid("THYAO")
    issues = []

    svc1 = PortfolioService(initial_capital=100000)
    await svc1.start()

    # Alım yap
    await svc1.execute_buy("THYAO", 100, 250.0, instrument_id=thyao_id)

    # svc1 durdur
    await svc1.stop()

    # Yeni instance başlat — state restore etmeli
    svc2 = PortfolioService(initial_capital=100000)
    await svc2.start()

    pf = await svc2.get_portfolio()
    if pf["positions_count"] != 1:
        issues.append(f"Pozisyon restore edilemedi: {pf['positions_count']}")

    if pf["positions"]:
        pos = pf["positions"][0]
        if pos["quantity"] != 100:
            issues.append(f"Quantity yanlış: {pos['quantity']}")
        if abs(pos["entry_price"] - 250.0) > 1:
            issues.append(f"Entry price yanlış: {pos['entry_price']}")

    # İkinci alım yapabilmeli
    result = await svc2.execute_buy("THYAO", 50, 260.0, instrument_id=thyao_id)
    if not result.get("success"):
        issues.append(f"Restart sonrası alım başarısız: {result}")

    await svc2.stop()
    return "Restart During Trade", len(issues) == 0, issues


async def test_cash_never_negative():
    """Hiçbir durumda cash negatif olmamalı."""
    await setup_db()
    thyao_id = await get_iid("THYAO")
    issues = []

    svc = PortfolioService(initial_capital=1000)  # Düşük sermaye
    await svc.start()

    # Çok büyük alım dene (başarısız olmalı)
    result = await svc.execute_buy("THYAO", 1000, 100.0, instrument_id=thyao_id)
    if result.get("success"):
        issues.append("Yetersiz nakit ile alım başarılı oldu")

    # Cash kontrolü
    pf = await svc.get_portfolio()
    if pf["cash"] < 0:
        issues.append(f"Negatif cash: {pf['cash']}")

    await svc.stop()
    return "Cash Never Negative", len(issues) == 0, issues


# ============================================================
# RUN
# ============================================================

async def run_all():
    print("=" * 60)
    print("MULTI-INSTANCE RACE CONDITION TESTLERİ")
    print("=" * 60)

    tests = [
        test_parallel_buys,
        test_concurrent_buy_sell,
        test_invariant_after_parallel_ops,
        test_restart_during_trade,
        test_cash_never_negative,
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
