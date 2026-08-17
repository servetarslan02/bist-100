# scheduler/main

**Dosya:** `services/scheduler/main.py`
**Satır:** 152

## Açıklama

ALPHA BIST — Scheduler v2.0

3 katmanlı tarama zamanlaması:
- Layer 1: Live Scanner → sürekli (tick bazlı)
- Layer 2: Batch Scanner → günde 5 kez (09:50, 12:00, 15:00, 17:50)
- Layer 3: Event Scanner → event geldiğinde immediate

## Sınıflar (1)

- `AlphaScheduler`

## Fonksiyonlar (1)

- `__init__()`

## Bağlantılar

Bu modül şu modülleri kullanır:

- `ingestion/bist_universe`
- `scanner/alpha_engine`

