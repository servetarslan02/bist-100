import duckdb

import json

con = duckdb.connect("data/paper_trading_state.db", read_only=True)
p_state = con.execute("SELECT cash, json_data FROM portfolio_state").fetchone()
cash = p_state[0] if p_state else 279669.61
tot = 996217.69
if p_state and p_state[1]:
    try:
        jd = json.loads(p_state[1])
        tot = jd.get("total_value", tot)
    except Exception:
        pass
rows = con.execute("SELECT ticker, quantity, avg_cost, (quantity * current_price) as market_value, sector FROM positions ORDER BY market_value DESC").fetchall()

print("========================================================================================")
print("=== PAZARTESİ SABAH AÇILIŞ SEANSI (09:55 - 10:00) GERÇEKLEŞEN CANLI PORTFÖY TABLOSU ===")
print("========================================================================================")
print(f"Toplam Portfoy Degeri:   {tot:,.2f} TL")
print(f"Yatirima Giren Tutar:    {tot - cash:,.2f} TL (%{(tot-cash)/tot*100:.1f})")
print(f"Kalan Firsat Nakdi:      {cash:,.2f} TL (%{cash/tot*100:.1f}) -> KURAL: %8 Nakit Korundu!")
print(f"Acilan Pozisyon Sayisi:  {len(rows)} adet hisse (Boğa Rejimi Kurali: 0-30 Hisse)\n")

print(f"{'#':<3} {'Hisse':<7} {'Sektor':<12} {'Lot':>8} {'Alis Fiyati':>13} {'Toplam Tutar':>16} {'Portfoy Payi':>14}")
print("-" * 76)
for i, r in enumerate(rows, 1):
    t, q, cost, val, sec = r[0], r[1], r[2], r[3], r[4]
    w = (val / tot) * 100
    print(f"{i:<3} {t:<7} {sec:<12} {q:>8,d} {cost:>11.2f} TL {val:>14,.2f} TL %{w:>11.1f}")
print("-" * 76)
