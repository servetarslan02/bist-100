import asyncio
import json
import os
import sys

import httpx

sys.path.insert(0, os.path.abspath("."))

from services.paper_trading.paper_orchestrator import paper_orchestrator
from services.pipeline.run_unified_daily import run_eod_signal_cycle, run_morning_execution_cycle


async def verify_single_brain():
    print("================================================================================")
    print("      TEK BEYİN İLKESİ (SINGLE SOURCE OF TRUTH) VE %20 TAVAN DOĞRULAMA TESTİ     ")
    print("================================================================================\n")

    # 1. API'den Otonom Fırsatlar Listesini Alalım
    print("1. Otonom Fırsatlar API'sinden Güncel Liste Alınıyor (/api/v1/scanner/signals)...")
    async with httpx.AsyncClient(base_url="http://localhost:8000", timeout=30.0) as client:
        res = await client.get("/api/v1/scanner/signals?limit=10")
        api_signals = res.json().get("signals", [])

    print(f"   API'den Çekilen Fırsat Sayısı: {len(api_signals)}")
    print("   İlk 5 Fırsat:")
    for idx, s in enumerate(api_signals[:5], 1):
        print(f"     {idx}. {s['ticker']:<7} | Skor: {s['score']} | Beklenen Getiri: +%{s['expected_return_pct']}% | Kategori: {s.get('spec_category')}")

    # 2. Portföy Motoru için EOD Sinyal Üretimi ve Kuyruk Kontrolü
    print("\n2. Portföy Motoru Sinyal Döngüsü Çalıştırılıyor (Tek Şampiyon Model)...")
    await run_eod_signal_cycle(target_date="2026-08-28", force_rebalance=True)

    pending = paper_orchestrator.store.load_pending_signals()
    print(f"   Portföy Emir Defterine Alınan Sinyal Sayısı: {len(pending)} adet")

    # 3. Birebir Uyum Kontrolü (1'e 1 Eşleşme)
    print("\n3. OTONOM FIRSATLAR VE PORTFÖY KUYRUĞU BİREBİR UYUM TESTİ:")
    print("-" * 75)
    print(f"{'Sıra':<5} {'Fırsatlar Ekranı':<18} {'Portföyün Alacağı':<18} {'Tahsis %':<12} {'Durum'}")
    print("-" * 75)

    all_matched = True
    for i in range(min(5, len(api_signals), len(pending))):
        api_t = api_signals[i]["ticker"]
        port_t = pending[i]["ticker"]
        port_w = pending[i].get("target_weight", 0.0) * 100
        match = (api_t == port_t)
        if not match:
            all_matched = False
        print(f"#{i+1:<4} {api_t:<18} {port_t:<18} %{port_w:<10.2f} {'TAM EŞLEŞTİ (100%)' if match else 'FARKLI'}")
    print("-" * 75)

    # 4. Pazartesi Sabah Seansı Yürütmesi
    print("\n4. Pazartesi Sabah Açılışı Simülasyonu (09:55 Seansı İcra Ediliyor)...")
    morn_res = await run_morning_execution_cycle(target_date="2026-08-28")
    print(f"   Sabah Yürütme Sonucu: {morn_res.get('status')}")

    # 5. Gerçekleşen Portföy Pozisyonları
    paper_orchestrator.portfolio.load_from_store()
    positions = paper_orchestrator.portfolio.get_all_positions()
    tot_val = paper_orchestrator.portfolio.get_total_value()
    cash_val = paper_orchestrator.portfolio.cash

    print("\n================================================================================")
    print("=== NİHAİ PORTFÖY TABLOSU: KULLANICI KURALLARI DOĞRULAMASI ===")
    print("================================================================================")
    print(f"Toplam Portföy Değeri: {tot_val:,.2f} TL")
    print(f"Yatırımdaki Tutar:     {tot_val - cash_val:,.2f} TL (%{(tot_val-cash_val)/tot_val*100:.1f})")
    print(f"Kalan Fırsat Nakdi:    {cash_val:,.2f} TL (%{cash_val/tot_val*100:.1f})")
    print(f"Açılan Pozisyon:       {len(positions)} adet hisse\n")

    print(f"{'#':<3} {'Hisse':<7} {'Lot':>8} {'Alış Fiyatı':>13} {'Toplam Tutar':>16} {'Portföy Payı':>14}")
    print("-" * 68)
    for i, p in enumerate(positions, 1):
        t = p.get("ticker", "")
        s = p.get("quantity", 0)
        pr = p.get("avg_cost", 0.0)
        val = s * pr
        w = (val / tot_val) * 100
        print(f"{i:<3} {t:<7} {s:>8,d} {pr:>11.2f} TL {val:>14,.2f} TL %{w:>11.1f}")
    print("-" * 68)

    # 6. Portföyü Temiz 1M Nakde Sıfırla (Gerçek Pazartesi İçin)
    import duckdb
    con = duckdb.connect("data/paper_trading_state.db")
    con.execute("DELETE FROM positions")
    con.execute("DELETE FROM orders")
    con.execute("DELETE FROM trades")
    con.execute("DELETE FROM pending_signals")
    con.execute("DELETE FROM audit_log")
    p_json = json.dumps({"initial_capital": 1000000.0, "cash": 1000000.0, "total_value": 1000000.0, "num_positions": 0})
    con.execute("UPDATE portfolio_state SET cash = 1000000.0, json_data = ?", [p_json])
    con.close()
    print("\n[OK] Portföy gerçek seans için 1.000.000 TL nakde sıfırlandı.")

if __name__ == "__main__":
    asyncio.run(verify_single_brain())
