"""
Verify live zero-delay BIST radar and stock feed
"""
import sys
import requests
import json

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding='utf-8')

r = requests.get('http://localhost:8000/api/v1/market/radar?limit=10')
data = r.json()
print("=" * 70)
print(f"CANLI 0-GECİKMELİ BIST RADAR DURUMU: {data.get('status')} | Toplam: {data.get('count')} Hisse")
print("=" * 70)
for x in data.get('data', [])[:8]:
    sym = x.get('symbol')
    price = x.get('price')
    chg = x.get('change')
    vol = x.get('volume', 0)
    score = x.get('score', 0)
    rsi = x.get('rsi', 0)
    print(f"  • {sym:<8} | Fiyat: {price:>7.2f} ₺ | Değişim: %{chg:>+5.2f} | Hacim: {vol:>12,} | RSI: {rsi:<4} | Skor: {score}")
print("=" * 70)
