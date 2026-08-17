# scanner/event_scanner

**Dosya:** `services/scanner/event_scanner.py`
**Satır:** 203

## Açıklama

ALPHA BIST — Event-Driven Scanner v1.0

Haber/KAP/makro geldiğinde → affected stocks → immediate rescan

Normal mod: 5 dakika beklemez.
Event geldiğinde Tier 0'dan Tier 3'e atlayabilir.

## Sınıflar (1)

- `EventScanner`

## Fonksiyonlar (9)

- `__init__()`
- `on_event()`
- `get_pending_rescans()`
- `clear_rescan()`
- `clear_all()`
- `should_rescan()`
- `_get_macro_affected_stocks()`
- `get_event_score()`
- `set_event_direction()`

