# core/decision_engine

**Dosya:** `services/core/decision_engine.py`
**Satır:** 471

## Açıklama

ALPHA BIST — Decision Engine v2.0 (Düzeltilmiş)

ATR field'ı eklendi.
Stop-loss ve target hesaplaması ATR bazlı.

FAZ 8: Decision Engine

## Sınıflar (4)

- `Action`
- `DecisionInput`
- `Decision`
- `DecisionEngine`

## Fonksiyonlar (15)

- `__init__()`
- `decide()`
- `_calculate_composite_score()`
- `_technical_score()`
- `_fundamental_score()`
- `_sentiment_score()`
- `_regime_score()`
- `_risk_score()`
- `_determine_direction()`
- `_determine_action()`
- `_calculate_stop_and_target()`
- `_assess_risks()`
- `_generate_reasons()`
- `_calculate_expected_return()`
- `decide_from_canonical()`

## Bağlantılar

Bu modül şu modülleri kullanır:

- `core/canonical_scoring`

