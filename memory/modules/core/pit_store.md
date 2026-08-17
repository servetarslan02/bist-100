# core/pit_store

**Dosya:** `services/core/pit_store.py`
**Satır:** 160

## Açıklama

ALPHA BIST — Point-in-Time Store v1.0

Geleceğe sızıntıyı (look-ahead bias) engelleyen veri deposu.

Her veri kaydı:
- O tarihte bilinen versiyon olarak saklanır
- Sonradan düzeltmeler yeni kayıt olarak eklenir (eski kayıt silinmez)
- Backtest sadece o tarihte bilinen veriyi görür

Kaynak: Quant research — pandas index alignment ile gelecek veri sızıntısı

## Sınıflar (2)

- `PITRecord`
- `PointInTimeStore`

## Fonksiyonlar (8)

- `__init__()`
- `insert()`
- `get_as_of()`
- `get_latest()`
- `get_history()`
- `get_revisions()`
- `bulk_insert()`
- `get_stats()`

