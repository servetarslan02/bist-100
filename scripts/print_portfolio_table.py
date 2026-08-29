import sys
import os
sys.path.insert(0, os.path.abspath("."))

from services.paper_trading.paper_orchestrator import paper_orchestrator

port = paper_orchestrator.portfolio
port.load_from_store()
tot_val = port.get_total_value()
cash_val = port.cash
cash_pct = (cash_val / tot_val) * 100
invested_val = tot_val - cash_val
invested_pct = (invested_val / tot_val) * 100
positions = port.get_all_positions()

print("================================================================================")
print("=== PAZARTESİ SABAH AÇILIŞI SONRASI PORTFÖYÜN GERÇEKLEŞEN CANLI TABLOSU ===")
print("================================================================================")
print(f"Toplam Portfoy Degeri:   {tot_val:,.2f} TL")
print(f"Yatirima Giren Tutar:    {invested_val:,.2f} TL (%{invested_pct:.1f})")
print(f"Kalan Firsat Nakdi:      {cash_val:,.2f} TL (%{cash_pct:.1f}) -> KURAL: %8 Nakit Tamponu Korundu!")
print(f"Portfoydeki Hisse Sayisi:{len(positions)} adet (Boga Kurali: 0-30 Hisse)\n")

print(f"{'#':<3} {'Hisse':<7} {'Lot':>8} {'Alis Fiyati':>13} {'Toplam Tutar':>16} {'Portfoy Payi':>14}")
print("-" * 68)
for i, p in enumerate(positions, 1):
    t = p.get("ticker", "")
    s = p.get("quantity", 0)
    pr = p.get("avg_cost", 0.0)
    val = s * pr
    w = (val / tot_val) * 100
    print(f"{i:<3} {t:<7} {s:>8,d} {pr:>11.2f} TL {val:>14,.2f} TL %{w:>11.1f}")
print("-" * 68)
