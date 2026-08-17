# features/fundamental

**Dosya:** `services/features/fundamental.py`
**Satır:** 342

## Açıklama

ALPHA BIST — Fundamental Feature Engine v1.0

Finansal verilerden feature üretir:
- Değerleme (P/E, P/B, EV/EBITDA, FCF Yield)
- Kârlılık (ROE, ROA, ROIC, margins)
- Büyüme (revenue growth, earnings growth, CAGR)
- Bilanço (debt/equity, current ratio, net debt/EBITDA)
- Kalite (earnings quality, cash conversion)
- Trend (margin trend, growth acceleration)

FAZ 2.2: Fundamental Features

## Sınıflar (1)

- `FundamentalFeatureEngine`

## Fonksiyonlar (8)

- `compute_valuation_features()`
- `compute_profitability_features()`
- `compute_growth_features()`
- `compute_balance_sheet_features()`
- `compute_cash_flow_features()`
- `compute_quality_features()`
- `compute_all_fundamental_features()`
- `compute_trend_features()`

