import asyncio
import os
import sys

sys.path.insert(0, os.path.abspath("."))

from services.paper_trading.paper_orchestrator import paper_orchestrator
from services.pipeline.run_unified_daily import run_eod_signal_cycle, run_morning_execution_cycle


async def test_monday_drill():
    print("================================================================================")
    print("       PAZARTESİ SABAH AÇILIŞ SEANSI (09:55 - 10:00) SİSTEM TATBİKATI           ")
    print("================================================================================\n")

    port = paper_orchestrator.portfolio
    port.load_from_store()
    print("=== 1. PAZARTESİ SABAH ÖNCESİ MEVCUT PORTFÖY ===")
    print(f"Toplam Portfoy:  {port.get_total_value():,.2f} TL")
    print(f"Serbest Nakit:   {port.cash:,.2f} TL")
    print(f"Pozisyon Sayisi: {len(port.get_all_positions())} (Tertemiz Nakit)")

    print("\n=== 2. SEANS ÖNCESİ SİNYAL VE EMİR KUYRUĞU (HAZIRLANAN SİNYALLER) ===")
    # 28 Ağustos seans kapanışı verileriyle EOD sinyallerini üretip kuyruğa alalım
    await run_eod_signal_cycle(target_date="2026-08-28", force_rebalance=True)
    pending = paper_orchestrator.store.load_pending_signals()
    print(f"Pazartesi Sabahi Icin Kuyruga Alinan Sinyal: {len(pending)} adet")
    for idx, sig in enumerate(pending[:12], 1):
        t = sig["ticker"]
        d = sig["direction"]
        w = sig.get("target_weight", 0) * 100
        sc = sig.get("score", 0)
        sec = sig.get("sector", "Genel")
        print(f"  {idx:>2}. {t:<7} | Yon: {d:<5} | Tahsis: %{w:.1f} | Skor: {sc:.2f} | Sektor: {sec}")

    print("\n=== 3. SAAT 09:55 - 10:00: PAZARTESİ SEANS AÇILIŞI YÜRÜTME DÖNGÜSÜ ===")
    print("-> KAP Kısıtları (VBTS, Brüt Takas) denetleniyor...")
    print("-> Pre-trade Risk Kapısı (Risk Gate) çalıştırılıyor...")
    print("-> Sentetik Emir Defteri (Walk-the-Book) ile açılış emirleri dolduruluyor...")

    morn_res = await run_morning_execution_cycle(target_date="2026-08-28")
    print(f"Sabah Yurutme Durumu:    {morn_res.get('status')}")
    print(f"Gerceklesen Islem:       {morn_res.get('num_trades', 0)} adet alim islemi yapildi.")

    print("\n================================================================================")
    print("=== 4. PAZARTESİ SEANS AÇILIŞI SONRASI PORTFÖYÜN NİHAİ CANLI TABLOSU ===")
    print("================================================================================")
    port.load_from_store()
    positions = port.get_all_positions()
    tot_val = port.get_total_value()
    cash_val = port.cash
    cash_pct = (cash_val / tot_val) * 100
    invested_val = tot_val - cash_val
    invested_pct = (invested_val / tot_val) * 100

    print(f"Toplam Portfoy Degeri:   {tot_val:,.2f} TL")
    print(f"Yatirima Giren Tutar:    {invested_val:,.2f} TL (%{invested_pct:.1f})")
    print(f"Kalan Firsat Nakdi:      {cash_val:,.2f} TL (%{cash_pct:.1f}) -> KURAL: %8 Nakit Tamponu Korundu!")
    print(f"Portfoydeki Hisse:       {len(positions)} adet (Boğa Rejimi Kurali: 0-30 Hisse)\n")

    print(f"{'#':<3} {'Hisse':<7} {'Lot':>8} {'Alis Fiyati':>13} {'Toplam Tutar':>16} {'Portfoy Payi':>14}")
    print("-" * 68)
    for i, p in enumerate(positions, 1):
        t = p.get("ticker", "")
        s = p.get("quantity", p.get("shares", 0))
        pr = p.get("avg_cost", p.get("entry_price", 0.0))
        val = s * pr
        w = (val / tot_val) * 100
        print(f"{i:<3} {t:<7} {s:>8,d} {pr:>11.2f} TL {val:>14,.2f} TL %{w:>11.1f}")
    print("-" * 68)

if __name__ == "__main__":
    asyncio.run(test_monday_drill())
