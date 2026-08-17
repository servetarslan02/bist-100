# core/short_selling

**Dosya:** `services/core/short_selling.py`
**Satır:** 112

## Açıklama

ALPHA BIST — Short Selling Monitor

BIST açığa satış kuralları:
- Sadece BIST-30 hisseleri açığa satılabilir
- Uptick rule: son işlem fiyatından yüksek fiyatla açığa satış
- Brüt takaslı hisselerde açığa satış yasak
- SPK geçici yasak kontrolü

## Sınıflar (2)

- `ShortSellingDecision`
- `ShortSellingMonitor`

## Fonksiyonlar (6)

- `__post_init__()`
- `__init__()`
- `_get_bist30()`
- `set_gross_settlement()`
- `set_spk_banned()`
- `can_short_sell()`

## Bağlantılar

Bu modül şu modülleri kullanır:

- `ingestion/bist_universe`

