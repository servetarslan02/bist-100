import urllib.request

import orjson

tests = [
    (
        "1. Otonom Firsatlar (ML Scanner)",
        "http://localhost:8000/api/v1/scanner/opportunities?limit=5",
        lambda d: (
            f"{len(d.get('signals', []))} Dinamik Sinyal | En Yuksek: {d.get('signals', [{}])[0].get('ticker')} (Skor: {d.get('signals', [{}])[0].get('score')})"
        ),
    ),
    (
        "2. Kuresel Makro & Dunya",
        "http://localhost:8000/api/v1/macro/world",
        lambda d: (
            f"CDS: {d.get('turkey_cds_5y')} bps | Rejim: {d.get('bist_macro_bias')} | Yorum: {d.get('macro_commentary', '')[:45]}..."
        ),
    ),
    (
        "3. Canli Alarmlar",
        "http://localhost:8000/api/v1/system/alerts",
        lambda d: f"{d.get('count')} Canli Alarm Mevcut | Ilk Alarm: {d.get('alerts', [{}])[0].get('title')}",
    ),
    (
        "4. Varlik Analizi THYAO",
        "http://localhost:8000/api/v1/market/instruments/THYAO/live_intel?period=6mo&interval=1d",
        lambda d: f"Fiyat: {d.get('price')} TL | Gercek Mum: {len(d.get('candles', []))} | RSI: {d.get('rsi_14')}",
    ),
    (
        "6. 30Y Strateji & Kriz Karnesi",
        "http://localhost:8000/api/v1/backtests/history_30y",
        lambda d: (
            f"OOS CAGR: %{d.get('summary', {}).get('oos_cagr_pct')} | PF: {d.get('summary', {}).get('oos_profit_factor')} | Max DD: %{d.get('summary', {}).get('oos_max_drawdown_pct')}"
        ),
    ),
    (
        "7. Model Kayit Defteri",
        "http://localhost:8000/api/v1/models/list",
        lambda d: f"{d.get('count')} Model Kayitli | Champion: {d.get('models', [{}])[0].get('id')}",
    ),
    (
        "8. Ogrenme Performans Matrisi",
        "http://localhost:8000/api/v1/learning/performance-matrix",
        lambda d: (
            f"{len(d.get('models', []))} Model Guven Skoru | LightGBM Trust: %{d.get('trust_scores', [{}])[0].get('trust_score')}"
        ),
    ),
    (
        "9. Senaryo Stres Testi",
        "http://localhost:8000/api/v1/risk/stress-test",
        lambda d: f"VaR %95: %{d.get('var_95')} | CVaR %95: %{d.get('cvar_95')} | Senaryo Sayisi: {d.get('total')}",
    ),
]

print("=== 9 KRİTİK ENDPOINT DOĞRULAMA TESTİ ===")
for name, url, fmt in tests:
    try:
        resp = urllib.request.urlopen(url, timeout=5)
        data = orjson.loads(resp.read().decode("utf-8"))
        print(f"[BASARILI] {name:<35} -> {fmt(data)}")
    except Exception as e:
        print(f"[HATA]     {name:<35} -> {e}")
