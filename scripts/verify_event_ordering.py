"""
ALPHA BIST — Temizlenmiş & Alakalı Makro Olay Doğrulama Testi
"""
import sys
import os
import requests

sys.path.insert(0, os.path.abspath("."))
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding='utf-8')

def test_events():
    r = requests.get("http://localhost:8000/api/v1/event-study/events").json()
    events = r.get("events", [])
    print("=" * 110)
    print(f"{'SIRA':<5} | {'ZAMAN':<12} | {'TİP':<6} | {'DUYGU':<8} | {'KAYNAK':<26} | {'BAŞLIK'}")
    print("=" * 110)
    for e in events[:12]:
        sent_str = f"{int(e['sentiment']*100):+d}%"
        print(f"{e['id']:<5} | {e['timestamp']:<12} | {e['type']:<6} | {sent_str:<8} | {e['source'][:24]:<26} | {e['title'][:55]}")

if __name__ == "__main__":
    test_events()
