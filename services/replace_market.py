import re
import sys

# GÜVENLİK: Bu dosya market.py'yi yeniden yazar. Yanlışlıkla çalıştırılmamalı.
if not sys.warnoptions:
    import warnings
    warnings.warn("replace_market.py çalıştırılıyor! Bu dosya market.py'yi yeniden yazar.", stacklevel=1)

# Kullanıcı etkileşimi için print() kullanılıyor (CLI script)
print("⚠️  UYARI: Bu script services/api/v1/market.py dosyasını yeniden yazacak!")  # noqa: T201
print("Devam etmek için 'YES' yazın:")  # noqa: T201
if input().strip() != "YES":
    print("İptal edildi.")  # noqa: T201
    sys.exit(0)

with open("services/api/v1/market.py", encoding="utf-8") as f:
    content = f.read()

# Replace from @router.get("/radar") to the end of _fetch_radar_fresh
new_radar = """
@router.get("/radar")
async def market_radar(limit: int = Query(1000, le=1000), user=Depends(get_current_user), _=Depends(check_rate_limit)):
    from ...core.redis_helper import get_cached
    import yfinance as yf
    from ...ingestion.bist_universe import BISTUniverse

    preds = get_cached("phase18:predictions")
    if not preds:
        return {"data": [], "count": 0, "status": "no_data"}

    uni = BISTUniverse()
    bist100 = set(getattr(uni, 'BIST_100_TICKERS', []))
    names = getattr(uni, 'COMPANY_NAMES', {})

    tickers = [p["ticker"] for p in preds][:limit]
    yf_tickers = [f"{t}.IS" for t in tickers]
    try:
        raw = yf.download(yf_tickers, period="5d", interval="1d", group_by="ticker", auto_adjust=True, progress=False)
    except Exception:
        raw = None

    radar_data = []
    for p in preds[:limit]:
        ticker = p["ticker"]
        score = p["score"]
        feats = p.get("features", {})
        price = 0.0
        change = 0.0
        volume = 0
        rsi = feats.get("rsi_14d", 50.0)

        if raw is not None and ticker + ".IS" in raw.columns.levels[0]:
            df = raw[ticker + ".IS"].dropna()
            if len(df) >= 2:
                price = float(df["Close"].iloc[-1])
                prev = float(df["Close"].iloc[-2])
                change = ((price - prev) / prev) * 100
                volume = int(df["Volume"].iloc[-1])

        action = "STRONG_BUY" if score > 0.02 else "BUY" if score > 0.01 else "HOLD" if score > -0.01 else "SELL"
        ui_score = min(100, max(0, int((score + 0.05) * 1000)))

        radar_data.append({
            "symbol": ticker,
            "name": names.get(ticker, ticker),
            "price": round(price, 2),
            "change": round(change, 2),
            "volume": volume,
            "isBist100": ticker in bist100,
            "score": ui_score,
            "raw_expected_return": round(score * 100, 2),
            "rsi": round(rsi, 2),
            "action": action
        })

    return {"data": radar_data, "count": len(radar_data), "status": "ok"}
"""

content = re.sub(r'@router\.get\("/radar"\).*?return radar_data', new_radar, content, flags=re.DOTALL)

with open("services/api/v1/market.py", "w", encoding="utf-8") as f:
    f.write(content)
