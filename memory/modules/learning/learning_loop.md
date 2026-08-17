# learning/learning_loop

**Dosya:** `services/learning/learning_loop.py`
**Satır:** 172

## Açıklama

ALPHA BIST — Learning Loop v1.0

Kendi kendine öğrenme döngüsü:
Prediction → Outcome → Error → Attribution → Feature drift →
Regime drift → Model decay → Retrain → OOS → Champion/Reject

## Sınıflar (2)

- `LearningState`
- `LearningLoop`

## Fonksiyonlar (8)

- `__init__()`
- `record_prediction()`
- `record_outcome()`
- `_check_model_decay()`
- `get_state()`
- `get_worst_regimes()`
- `should_retrain()`
- `get_retrain_reason()`

