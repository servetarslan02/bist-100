# core/streaming_anomaly

**Dosya:** `services/core/streaming_anomaly.py`
**Satır:** 204

## Açıklama

ALPHA BIST — Streaming Anomaly Detector v1.0

Veri ingestion anında anomali tespiti:
- Fiyat anomalisi (ani sıçrama)
- Hacim anomalisi (anormal hacim)
- Spread anomalisi (aşırı spread)
- Kaynak anomalisi (sahte veri)

Kaynak: Confluent streaming quality, Monte Carlo anomaly detection

## Sınıflar (2)

- `AnomalyResult`
- `StreamingAnomalyDetector`

## Fonksiyonlar (6)

- `__init__()`
- `check_price()`
- `check_volume()`
- `check_spread()`
- `check_all()`
- `get_stats()`

