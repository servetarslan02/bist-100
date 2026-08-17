# core/regime_detector

**Dosya:** `services/core/regime_detector.py`
**Satır:** 270

## Açıklama

ALPHA BIST — Regime Detector v3.0

ROADMAP v3.0:
- Multi-factor regime detection (trend, volatilite, korelasyon, breadth)
- Regime transition probability
- Regime duration tracking
- Forward-looking regime prediction

KURAL: BULL'da momentum, BEAR'da quality, SIDEWAYS'da mean reversion.

## Sınıflar (2)

- `RegimeState`
- `RegimeDetector`

## Fonksiyonlar (4)

- `__init__()`
- `detect_regime()`
- `_estimate_transition_probability()`
- `get_regime_history()`

