#!/usr/bin/env python3
"""
Portfolio Manager v2.0 — Kurumsal Muhasebe Testleri
"""

import sys
import os

import numpy as np
from datetime import datetime, timezone
from services.portfolio.portfolio_manager import (
    PortfolioManager, Position, Trade, CommissionModel,
    CashLedgerEntry, EquitySnapshot, PositionHistoryEntry,
)


def test_commission_model():
    """Komisyon modeli testleri."""
    cm = CommissionModel()
    issues = []

    # Normal işlem
    c = cm.calculate(100000)
    if c <= 0:
        issues.append("Komisyon negatif veya sıfır")
    if c < 1.0:
        issues.append("Minimum komisyon uygulanmıyor")

    # Breakdown
    b = cm.breakdown(100000)
    if b["total_commission"] != c:
        issues.append(f"Breakdown tutarsız: {b['total_commission']} != {c}")
    if b["broker_commission"] <= 0:
        issues.append("Broker komisyonu sıfır")
    if b["bsmv"] <= 0:
        issues.append("BSMV sıfır")

    # Minimum komisyon
    c_small = cm.calculate(100)
    if c_small < 1.0:
        issues.append(f"Küçük işlem min komisyon: {c_small}")

    return "Commission Model", len(issues) == 0, issues


def test_cash_ledger():
    """Nakit hareket ledger testleri."""
    pm = PortfolioManager(initial_capital=100000)
    issues = []

    # Başlangıç kaydı
    ledger = pm.get_cash_ledger()
    if len(ledger) == 0:
        issues.append("Başlangıç nakit kaydı yok")
    elif ledger[0]["type"] != "DEPOSIT":
        issues.append(f"İlk kayıt DEPOSIT değil: {ledger[0]['type']}")

    # Alım sonrası nakit kaydı
    pm.open_position("THYAO", "LONG", 100, 250.0, commission=50)
    ledger = pm.get_cash_ledger()
    buy_entries = [e for e in ledger if e["type"] == "BUY"]
    if len(buy_entries) == 0:
        issues.append("Alım nakit kaydı yok")
    else:
        # 100 * 250 + 50 = 25050 düşülmeli
        if abs(buy_entries[0]["amount"] + 25050) > 1:
            issues.append(f"Alım nakit tutarı yanlış: {buy_entries[0]['amount']}")

    return "Cash Ledger", len(issues) == 0, issues


def test_position_history():
    """Pozisyon geçmişi audit trail testleri."""
    pm = PortfolioManager(initial_capital=100000)
    issues = []

    # Pozisyon aç
    pm.open_position("THYAO", "LONG", 100, 250.0, commission=50)
    hist = pm.get_position_history("THYAO")
    if len(hist) == 0:
        issues.append("Açılış kaydı yok")
    elif hist[0]["action"] != "OPEN":
        issues.append(f"İlk kayıt OPEN değil: {hist[0]['action']}")
    elif hist[0]["quantity_after"] != 100:
        issues.append(f"Miktar yanlış: {hist[0]['quantity_after']}")

    # Pozisyona ekle
    pm.open_position("THYAO", "LONG", 50, 260.0, commission=30)
    hist = pm.get_position_history("THYAO")
    add_entries = [e for e in hist if e["action"] == "ADD"]
    if len(add_entries) == 0:
        issues.append("ADD kaydı yok")
    else:
        if add_entries[0]["quantity_before"] != 100:
            issues.append(f"ADD öncesi miktar yanlış: {add_entries[0]['quantity_before']}")
        if add_entries[0]["quantity_after"] != 150:
            issues.append(f"ADD sonrası miktar yanlış: {add_entries[0]['quantity_after']}")

    # Kısmi kapat
    pm._positions["THYAO"].current_price = 270
    pm.close_position("THYAO", 270.0, commission=40)
    hist = pm.get_position_history("THYAO")
    close_entries = [e for e in hist if e["action"] == "CLOSE"]
    if len(close_entries) == 0:
        issues.append("CLOSE kaydı yok")
    else:
        if close_entries[0]["realized_pnl"] == 0:
            issues.append("Realized P&L sıfır")

    return "Position History", len(issues) == 0, issues


def test_equity_curve():
    """Equity curve ve snapshot testleri."""
    pm = PortfolioManager(initial_capital=100000)
    issues = []

    # Pozisyon aç ve fiyat güncelle
    pm.open_position("THYAO", "LONG", 100, 250.0, commission=50)
    pm.update_prices({"THYAO": 260})

    # Equity curve
    ec = pm.get_equity_curve()
    if len(ec) == 0:
        issues.append("Equity curve boş")
    else:
        # equity = cash + market_value
        expected = pm._cash + 100 * 260
        if abs(ec[-1]["equity"] - expected) > 0.01:
            issues.append(f"Equity yanlış: {ec[-1]['equity']} != {expected}")

    # Snapshot'lar
    snapshots = pm.get_equity_snapshots()
    if len(snapshots) == 0:
        issues.append("Snapshot yok")

    # HWM
    hwm = pm.get_high_water_mark()
    if hwm < 100000:
        issues.append(f"HWM başlangıçtan düşük: {hwm}")

    # Drawdown
    pm.update_prices({"THYAO": 200})  # Düşüş
    dd = pm.get_drawdown()
    if dd <= 0:
        issues.append(f"Drawdown pozitif değil: {dd}")

    return "Equity Curve", len(issues) == 0, issues


def test_realized_pnl():
    """Realized P&L muhasebesi testleri."""
    pm = PortfolioManager(initial_capital=100000)
    issues = []

    # Al: 100 adet @ 250, komisyon 50
    pm.open_position("THYAO", "LONG", 100, 250.0, commission=50)
    cost_basis = 100 * 250 + 50  # 25050

    # Sat: 100 adet @ 270, komisyon 50
    result = pm.close_position("THYAO", 270.0, commission=50)

    # Realized P&L = (270-250)*100 - 50 - 50 = 2000 - 100 = 1900
    expected_pnl = (270 - 250) * 100 - 50 - 50
    actual_pnl = result.get("realized_pnl", 0)
    if abs(actual_pnl - expected_pnl) > 0.01:
        issues.append(f"Realized P&L yanlış: {actual_pnl} != {expected_pnl}")

    # Toplam realized P&L
    total = pm.get_realized_pnl_total()
    if abs(total - expected_pnl) > 0.01:
        issues.append(f"Toplam realized P&L yanlış: {total} != {expected_pnl}")

    # Komisyon toplamı
    comm = pm.get_commission_total()
    if abs(comm - 100) > 0.01:
        issues.append(f"Toplam komisyon yanlış: {comm} != 100")

    return "Realized P&L", len(issues) == 0, issues


def test_accounting_invariant():
    """EQUITY = CASH + MARKET_VALUE invariant testi."""
    pm = PortfolioManager(initial_capital=100000)
    issues = []

    # Birden fazla pozisyon
    pm.open_position("THYAO", "LONG", 100, 250.0, commission=50)
    pm.open_position("GARAN", "LONG", 200, 100.0, commission=30)
    pm.open_position("AKBNK", "LONG", 150, 80.0, commission=25)

    # Fiyat güncelle
    pm.update_prices({"THYAO": 260, "GARAN": 95, "AKBNK": 85})

    # Muhasebe özeti
    acc = pm.get_accounting_summary()

    # Invariant kontrolü
    if not acc["invariant_check"]:
        issues.append(f"EQUITY ≠ CASH + MARKET_VALUE: equity={acc['total_equity']}, cash={acc['cash']}, mv={acc['market_value']}")

    # Manuel doğrulama
    expected_cash = 100000 - (100*250 + 50) - (200*100 + 30) - (150*80 + 25)
    expected_mv = 100*260 + 200*95 + 150*85
    expected_equity = expected_cash + expected_mv

    if abs(acc["cash"] - expected_cash) > 0.01:
        issues.append(f"Cash yanlış: {acc['cash']} != {expected_cash}")
    if abs(acc["market_value"] - expected_mv) > 0.01:
        issues.append(f"Market value yanlış: {acc['market_value']} != {expected_mv}")
    if abs(acc["total_equity"] - expected_equity) > 0.01:
        issues.append(f"Total equity yanlış: {acc['total_equity']} != {expected_equity}")

    # Unrealized P&L = (current - entry) * qty — komisyon cost_basis'te
    # THYAO: (260-250)*100 = 1000
    # GARAN: (95-100)*200 = -1000
    # AKBNK: (85-80)*150 = 750
    # Net = 1000 - 1000 + 750 = 750
    expected_unrealized = (260-250)*100 + (95-100)*200 + (85-80)*150
    if abs(acc["unrealized_pnl"] - expected_unrealized) > 0.01:
        issues.append(f"Unrealized P&L yanlış: {acc['unrealized_pnl']} != {expected_unrealized}")

    return "Accounting Invariant", len(issues) == 0, issues


def test_weighted_average_cost():
    """Weighted average cost basis testi."""
    pm = PortfolioManager(initial_capital=100000)
    issues = []

    # İlk alım: 100 adet @ 250, komisyon 50 → avg = (25000+50)/100 = 250.50
    pm.open_position("THYAO", "LONG", 100, 250.0, commission=50)
    pos = pm._positions.get("THYAO")
    if not pos:
        issues.append("Pozisyon açılmadı")
        return "Weighted Avg Cost", False, issues

    # entry_price = komisyonsuz fiyat = 250
    if abs(pos.entry_price - 250.0) > 0.01:
        issues.append(f"İlk entry_price yanlış: {pos.entry_price} != 250.0")
    # cost_basis = 250*100 + 50 = 25050
    if abs(pos.cost_basis - 25050) > 0.01:
        issues.append(f"İlk cost_basis yanlış: {pos.cost_basis} != 25050")

    # İkinci alım: 50 adet @ 260, komisyon 30
    pm.open_position("THYAO", "LONG", 50, 260.0, commission=30)
    pos = pm._positions.get("THYAO")
    # weighted avg price = (250*100 + 260*50) / 150 = 253.33
    expected_avg_2 = (250 * 100 + 260 * 50) / 150
    if abs(pos.entry_price - expected_avg_2) > 0.01:
        issues.append(f"İkinci entry_price yanlış: {pos.entry_price} != {expected_avg_2}")
    # cost_basis = 253.33*150 + 50 + 30 = 38080
    expected_cost = expected_avg_2 * 150 + 50 + 30
    if abs(pos.cost_basis - expected_cost) > 0.01:
        issues.append(f"İkinci cost_basis yanlış: {pos.cost_basis} != {expected_cost}")

    if pos.quantity != 150:
        issues.append(f"Miktar yanlış: {pos.quantity} != 150")

    return "Weighted Avg Cost", len(issues) == 0, issues


def test_short_position():
    """Short pozisyon P&L testi."""
    pm = PortfolioManager(initial_capital=100000)
    issues = []

    # Short aç: 100 adet @ 250, komisyon 50
    pm.open_position("THYAO", "SHORT", 100, 250.0, commission=50)

    # Fiyat düşünce kapat: 100 adet @ 230, komisyon 50
    pm._positions["THYAO"].current_price = 230
    result = pm.close_position("THYAO", 230.0, commission=50)

    # Short P&L = (250-230)*100 - 50 - 50 = 2000 - 100 = 1900
    expected_pnl = (250 - 230) * 100 - 50 - 50
    actual_pnl = result.get("realized_pnl", 0)
    if abs(actual_pnl - expected_pnl) > 0.01:
        issues.append(f"Short P&L yanlış: {actual_pnl} != {expected_pnl}")

    return "Short Position", len(issues) == 0, issues


def test_no_negative_weight():
    """Negatif weight/senaryo testleri."""
    pm = PortfolioManager(initial_capital=100000)
    issues = []

    # Yetersiz nakit
    result = pm.open_position("THYAO", "LONG", 10000, 250.0)
    if result.get("success"):
        issues.append("Yetersiz nakit ile pozisyon açıldı")

    # Olmayan pozisyonu kapat
    result = pm.close_position("MAYBE", 100.0)
    if result.get("success"):
        issues.append("Olmayan pozisyon kapatıldı")

    # NaN fiyat
    pm2 = PortfolioManager(initial_capital=100000)
    result = pm2.open_position("TEST", "LONG", 100, float('nan'))
    if result.get("success"):
        issues.append("NaN fiyat ile pozisyon açıldı")

    # Negatif fiyat
    result = pm2.open_position("TEST2", "LONG", 100, -10.0)
    if result.get("success"):
        issues.append("Negatif fiyat ile pozisyon açıldı")

    # Sıfır miktar
    result = pm2.open_position("TEST3", "LONG", 0, 100.0)
    if result.get("success"):
        issues.append("Sıfır miktar ile pozisyon açıldı")

    return "Edge Cases", len(issues) == 0, issues


# ============================================================
# RUN ALL TESTS
# ============================================================

def main():
    print("=" * 60)
    print("PORTFOLIO MANAGER v2.0 — KURUMSAL MUHASEBE TESTLERİ")
    print("=" * 60)

    tests = [
        test_commission_model,
        test_cash_ledger,
        test_position_history,
        test_equity_curve,
        test_realized_pnl,
        test_accounting_invariant,
        test_weighted_average_cost,
        test_short_position,
        test_no_negative_weight,
    ]

    total_pass = 0
    total_fail = 0
    all_issues = []

    for test_func in tests:
        name, passed, issues = test_func()
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


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
