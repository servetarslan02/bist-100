# ingestion/corporate_actions

**Dosya:** `services/ingestion/corporate_actions.py`
**Satır:** 350

## Açıklama

ALPHA BIST — Corporate Actions Handler v1.0

Temettü, bölünme, bedelsiz, bedelli, birleşme gibi şirket olaylarını
fiyat ve portföy geçmişine doğru şekilde yansıtır.

FAZ 1.5: Corporate Actions

## Sınıflar (3)

- `ActionType`
- `CorporateAction`
- `CorporateActionsHandler`

## Fonksiyonlar (13)

- `__init__()`
- `add_action()`
- `get_actions()`
- `adjust_price()`
- `adjust_position()`
- `compute_dividend_income()`
- `adjust_historical_prices()`
- `_adjust_single_price()`
- `load_from_kap()`
- `_classify_kap_event()`
- `_extract_dividend_amount()`
- `_extract_split_ratio()`
- `_parse_date()`

