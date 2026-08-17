# features/feature_contract

**Dosya:** `services/features/feature_contract.py`
**Satır:** 162

## Açıklama

ALPHA BIST — Feature Data Contract v1.0

Her feature için:
- value: sayısal değer (float veya None)
- availability_ts: bu bilginin gerçek dünyada kullanılabildiği timestamp
- source: veri kaynağı (calculator, motor1, kap, yfinance, vb.)
- status: MISSING | UNKNOWN | STALE | FRESH

Kurallar:
- MISSING: veri hiç çekilmedi veya provider yok
- UNKNOWN: veri çekildi ama bu ticker için mevcut değil
- STALE: veri var ama belirli bir eşiğin eski
- FRESH: veri güncel ve kullanılabilir

Point-in-time güve

## Sınıflar (3)

- `FeatureStatus`
- `FeatureDataPoint`
- `TickerFeatureContract`

## Fonksiyonlar (6)

- `to_value()`
- `is_usable()`
- `get_value()`
- `get_raw_dict()`
- `get_usable_dict()`
- `get_availability_report()`

