# risk/position_sizing

**Dosya:** `services/risk/position_sizing.py`
**Satır:** 335

## Açıklama

ALPHA BIST — Position Sizing v4.0 (Calibrated Kelly + Historical OOS)

Mimari:
1. Calibration: ranking score -> win_probability (Platt scaling)
2. Historical OOS: gecmis trades'ten avg_win, avg_loss
3. Fractional Kelly: f* = (p*b - q) / b, yarim Kelly uygula
4. Volatility Target: portfoy volatilitesini hedefle
5. Risk Limits: max position, max total exposure

KURAL: confidence != win_probability. Ayri degiskenler.

## Sınıflar (4)

- `PositionSize`
- `PositionSizer`
- `_CalcResult`
- `_PositionSizerCompat`

## Fonksiyonlar (6)

- `__init__()`
- `calculate_position_sizes()`
- `_fractional_kelly()`
- `_volatility_leverage()`
- `_is_valid()`
- `calculate()`

