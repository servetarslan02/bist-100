import json
import redis
from datetime import datetime

r = redis.Redis(host='redis', port=6379, db=0, password='alpha_secure_pass_123')

base_stocks = [
    {"ticker": "THYAO", "score": 92.5},
    {"ticker": "ASELS", "score": 88.4},
    {"ticker": "TUPRS", "score": 85.1},
    {"ticker": "FROTO", "score": 82.7},
    {"ticker": "KCHOL", "score": 81.3},
    {"ticker": "AKBNK", "score": 79.9},
    {"ticker": "GARAN", "score": 77.2},
    {"ticker": "BIMAS", "score": 75.8},
    {"ticker": "SAHOL", "score": 73.4},
    {"ticker": "SISE", "score": 72.0},
    {"ticker": "ENKAI", "score": 68.5},
    {"ticker": "EREGL", "score": 65.2},
    {"ticker": "ISCTR", "score": 63.8},
    {"ticker": "PGSUS", "score": 60.1},
    {"ticker": "TOASO", "score": 58.7}
]

preds = []
for idx, s in enumerate(base_stocks):
    preds.append({
        "ticker": s["ticker"],
        "score": s["score"] / 100.0,
        "direction": "BUY" if s["score"] > 60 else "SELL",
        "expected_return": (s["score"] - 50) / 100.0
    })

r.set("phase18:predictions", json.dumps(preds))
r.set("phase18:last_trained", datetime.now().isoformat())
print("Redis phase18:predictions mock basariyla yazildi!")
