# intelligence/spec_engine

**Dosya:** `services/intelligence/spec_engine.py`
**Satır:** 341

## Açıklama

ALPHA BIST - SPEC Engine v1.2

SPEC = Anormal davranış + Kanıt birleşimi + Rejim uyumu + Beklenen değer
        + Risk/asimetri + İstatistiksel benzerlik - Penalty

v1.2: NaN/None güvenli, _safe_float ile tüm değerler korumalı.

## Sınıflar (3)

- `SPECConfig`
- `SPECResult`
- `SPECEngine`

## Fonksiyonlar (10)

- `__init__()`
- `compute_spec()`
- `_compute_anomaly()`
- `_compute_evidence()`
- `_compute_regime_compatibility()`
- `_compute_expected_value()`
- `_compute_risk_asymmetry()`
- `_compute_historical_similarity()`
- `_compute_penalties()`
- `_categorize()`

