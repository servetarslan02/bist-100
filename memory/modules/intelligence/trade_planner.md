# intelligence/trade_planner

**Dosya:** `services/intelligence/trade_planner.py`
**Satır:** 492

## Açıklama

ALPHA BIST - Trade Planner v1.0

Bulunan hisseler için:
- Al/Sat/Karar
- Giriş noktası
- Hedef fiyat
- Stop loss
- Kar/zarar beklentisi
- Risk/getiri oranı
- Senaryo planları (Bull/Base/Bear)
- Pozisyon büyüklüğü

## Sınıflar (2)

- `TradePlan`
- `TradePlanner`

## Fonksiyonlar (13)

- `create_plan()`
- `_determine_action()`
- `_determine_entry()`
- `_determine_targets()`
- `_determine_stop_loss()`
- `_calculate_expectations()`
- `_scenario_bull()`
- `_scenario_base()`
- `_scenario_bear()`
- `_calculate_position_size()`
- `_generate_reasons()`
- `_generate_risks()`
- `_determine_horizon()`

