# learning/attribution

**Dosya:** `services/learning/attribution.py`
**Satır:** 274

## Açıklama

ALPHA BIST — Attribution Engine v1.0

Bir işlem kazandı/kaybetti → NEDEN?

Bu feedback olmadan model sadece "kazandım/kaybettim" öğrenir.
Bizim istediğimiz: "Neden kazandım/kaybettim?"

Attribution:
  - Macro contribution
  - Flow contribution
  - Momentum contribution
  - KAP/Event contribution
  - Regime contribution
  - Technical contribution

## Sınıflar (2)

- `TradeAttribution`
- `AttributionEngine`

## Fonksiyonlar (9)

- `attribute()`
- `_calc_macro_contribution()`
- `_calc_flow_contribution()`
- `_calc_momentum_contribution()`
- `_calc_event_contribution()`
- `_calc_regime_contribution()`
- `_calc_technical_contribution()`
- `_extract_lessons()`
- `generate_report()`

