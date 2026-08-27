import sys

import requests

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding='utf-8')

def test_tradingview_turkey_scanner():
    url = "https://scanner.tradingview.com/turkey/scan"
    payload = {
        "filter": [],
        "options": {"lang": "tr"},
        "symbols": {"query": {"types": []}, "tickers": []},
        "columns": [
            "name",
            "description",
            "close",
            "change",
            "change_abs",
            "volume",
            "high",
            "low",
            "open",
            "RSI",
            "Recommend.All"
        ],
        "sort": {"sortBy": "volume", "sortOrder": "desc"},
        "range": [0, 650]
    }
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    try:
        r = requests.post(url, json=payload, headers=headers, timeout=5)
        print(f"TradingView Scanner Status: {r.status_code}")
        if r.status_code == 200:
            data = r.json()
            total = data.get("totalCount", 0)
            rows = data.get("data", [])
            print(f"Total BIST Stocks Found: {total}")
            print("Sample Top 5 Live Stocks:")
            for item in rows[:5]:
                sym = item.get("s", "")
                d = item.get("d", [])
                d[0] if len(d) > 0 else ""
                d[1] if len(d) > 1 else ""
                close = d[2] if len(d) > 2 else 0
                chg = d[3] if len(d) > 3 else 0
                vol = d[5] if len(d) > 5 else 0
                rsi = d[9] if len(d) > 9 else 0
                print(f"  • {sym:<12} | Fiyat: {close:>8.2f} ₺ | Değişim: %{chg:>+6.2f} | Hacim: {vol:>12,.0f} | RSI: {rsi}")
            return True
    except Exception as e:
        print(f"TradingView Error: {e}")
    return False

def test_bigpara():
    url = "https://bigpara.hurriyet.com.tr/api/v1/hisse/list"
    try:
        r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=5)
        print(f"Bigpara Status: {r.status_code}")
        if r.status_code == 200:
            data = r.json()
            print(f"Bigpara Sample: {str(data)[:200]}")
    except Exception as e:
        print(f"Bigpara Error: {e}")

if __name__ == "__main__":
    print("Testing Live BIST Data Feeds...")
    test_tradingview_turkey_scanner()
