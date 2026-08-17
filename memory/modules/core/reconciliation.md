# core/reconciliation

**Dosya:** `services/core/reconciliation.py`
**Satır:** 268

## Açıklama

ALPHA BIST — Cross-Source Reconciliation v1.0

Aynı veri birden fazla kaynaktan geldiğinde:
- Fiyat uyuşmazlığı tespiti
- Kaynak güvenilirliği bazlı seçim
- Anomali tespiti (sahte veri)
- Quality score hesaplama

Kaynak: Monte Carlo Data Quality Testing, Confluent streaming quality

## Sınıflar (2)

- `ReconciledData`
- `CrossSourceReconciliation`

## Fonksiyonlar (6)

- `reconcile_price()`
- `reconcile_multi_field()`
- `_select_best_source()`
- `_compute_quality_score()`
- `_compute_confidence()`
- `detect_price_jump()`

