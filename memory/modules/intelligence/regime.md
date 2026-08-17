# intelligence/regime

**Dosya:** `services/intelligence/regime.py`
**Satır:** 357

## Açıklama

ALPHA BIST — Regime Engine v1.0

Piyasa rejimlerini feature-based olarak tespit eder:
- Threshold-based değil, çoklu feature'dan karar verir
- Regime transition probability matrix
- Regime-conditioned model weights
- Regime duration tracking

FAZ 3.2: Regime Engine

## Sınıflar (3)

- `Regime`
- `RegimeState`
- `RegimeEngine`

## Fonksiyonlar (17)

- `__init__()`
- `detect_regime()`
- `_score_bull()`
- `_score_bear()`
- `_score_sideways()`
- `_score_high_vol()`
- `_score_low_vol()`
- `_score_risk_on()`
- `_score_risk_off()`
- `_score_crisis()`
- `_score_recovery()`
- `_score_momentum_expansion()`
- `_score_momentum_contraction()`
- `current_regime()`
- `get_regime_weights()`
- `get_transition_matrix()`
- `get_history()`

