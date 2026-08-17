# scanner/alpha_engine

**Dosya:** `services/scanner/alpha_engine.py`
**Satır:** 361

## Açıklama

ALPHA BIST — Alpha Engine v2.0

3 katmanlı tarama:
Layer 1: Live Scanner    → her tick, çok ucuz
Layer 2: Batch Scanner   → belirli aralıklarla tam tarama
Layer 3: Event Scanner   → haber/KAP geldiğinde immediate

Tüm pipeline tek motor:
800 hisse → data → bars → features → regime → scanner → signals

## Sınıflar (1)

- `AlphaEngine`

## Fonksiyonlar (13)

- `__init__()`
- `load_universe()`
- `process_tick()`
- `on_event()`
- `_compute_all_features()`
- `_detect_regime()`
- `_compute_single_feature()`
- `_compute_ml_scores()`
- `get_last_summary()`
- `get_last_results()`
- `get_regime()`
- `get_live_candidates()`
- `get_event_candidates()`

## Bağlantılar

Bu modül şu modülleri kullanır:

- `features/calculator`

