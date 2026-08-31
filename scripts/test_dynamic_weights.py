import os
import sys

sys.path.insert(0, os.path.abspath("."))

from services.risk.regime_limits import regime_limits

limits = regime_limits.get_limits("BULL")
investable_pool = max(0.10, 1.0 - limits.min_cash_pct)  # 0.92

# Simüle adaylar: Farklı skor, beklenen getiri ve güven
candidates = [
    {"ticker": "ASTOR", "score": 9.5, "expected_return_pct": 35.0, "confidence": 0.95},
    {"ticker": "GUBRF", "score": 9.1, "expected_return_pct": 30.0, "confidence": 0.92},
    {"ticker": "KRDMD", "score": 8.0, "expected_return_pct": 24.0, "confidence": 0.85},
    {"ticker": "TCELL", "score": 6.5, "expected_return_pct": 18.0, "confidence": 0.80},
    {"ticker": "BIMAS", "score": 5.0, "expected_return_pct": 14.0, "confidence": 0.75},
    {"ticker": "SISE",  "score": 3.5, "expected_return_pct": 10.0, "confidence": 0.70},
    {"ticker": "DUSUK", "score": 1.5, "expected_return_pct":  7.0, "confidence": 0.60},
]

raw_weights = []
for p in candidates:
    sc = max(0.1, float(p.get("score", 1.0)))
    exp_r = max(5.0, float(p.get("expected_return_pct", 15.0))) / 100.0
    conf = float(p.get("confidence", 0.85))
    factor = sc * (1.0 + exp_r) * conf
    raw_weights.append(factor)

tot_factor = sum(raw_weights)
max_pos_cap = min(0.10, limits.max_position_pct)
min_pos_floor = 0.02

print("=== DİNAMİK PORTFÖY AĞIRLIKLANDIRMA TESTİ ===")
print(f"Toplam Yatırıma Ayrılan Fon: %{investable_pool*100:.1f} (Nakit Tamponu: %{limits.min_cash_pct*100:.1f})")
print(f"{'Hisse':<7} {'Skor':>5} {'Beklenen Getiri':>16} {'Güven':>7} {'Tahsis Edilen Ağırlık':>22}")
print("-" * 62)

tot_w = 0.0
for p, rf in zip(candidates, raw_weights, strict=False):
    ideal_w = (rf / tot_factor) * investable_pool
    bounded_w = round(min(max_pos_cap, max(min_pos_floor, ideal_w)), 4)
    tot_w += bounded_w
    print(f"{p['ticker']:<7} {p['score']:>5.1f} +%{p['expected_return_pct']:>13.1f}% {p['confidence']:>7.2f} %{bounded_w*100:>20.1f}")

print("-" * 62)
print(f"Toplam Portföy Yatırım Oranı: %{tot_w*100:.1f} (Kalan Nakit: %{(1.0-tot_w)*100:.1f})")
