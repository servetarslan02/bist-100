# scanner/live_scanner

**Dosya:** `services/scanner/live_scanner.py`
**Satır:** 155

## Açıklama

ALPHA BIST — Live Scanner v1.0

Tick/event geldiğinde çalışan hafif tarayıcı.
800 hisseyi baştan indirmez.
Sadece değişen hisseyi günceller.

Pipeline:
  market.tick → state update → feature update → light scan → candidate?

## Sınıflar (1)

- `LiveScanner`

## Fonksiyonlar (7)

- `__init__()`
- `process_tick()`
- `_check_candidate()`
- `get_candidates()`
- `clear_candidate()`
- `get_state()`
- `get_stats()`

