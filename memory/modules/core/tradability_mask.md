# core/tradability_mask

**Dosya:** `services/core/tradability_mask.py`
**Satır:** 210

## Açıklama

ALPHA BIST — Tradability Mask v1.0

Mask-First Design: Hiçbir feature hesaplaması execute edilemeyen fiyat görmemeli.

BIST'te execute edilemeyen fiyatlar:
- Devre kesici (circuit breaker) — işlem durdurulmuş
- Tavan fiyat (limit-up) — fiyat tavana ulaşmış, alım yapılamıyor
- Taban fiyat (limit-down) — fiyat tabana ulaşmış, satım yapılamaz
- Halt — işlem askıya alınmış
- Sıfır hacim — işlem gerçekleşmemiş
- Eksik veri — veri yok

Mask = 1 → Fiyat güvenilir, kullanılabilir
Mask = 0 → Fiyat güveni

## Sınıflar (2)

- `MaskResult`
- `TradabilityMask`

## Fonksiyonlar (4)

- `compute_mask()`
- `apply_mask_to_features()`
- `apply_mask_to_prices()`
- `get_mask_stats()`

