# features/seven_motors

**Dosya:** `services/features/seven_motors.py`
**Satır:** 1317

## Açıklama

ALPHA BIST — 7 Motor Feature Engine v3.0

ROADMAP v3.0 FAZ 2:
- 100+ feature hesaplama
- Mask-aware hesaplama
- Yeni motorlar: Mean Reversion, Seasonality, Options Flow
- Cross-sectional entegrasyon

Her motor bağımsız çalışır, birbirinin sonucunu etkilemez.
Motor çıktıları ranking modeline girdi olarak kullanılır.

## Sınıflar (10)

- `RelativeStrengthMotor`
- `MomentumTrendMotor`
- `VolumeMicrostructureMotor`
- `FundamentalMotor`
- `KAPNewsMotor`
- `CatalystMotor`
- `WhyFallingMotor`
- `MeanReversionMotor`
- `SeasonalityMotor`
- `SevenMotorEngine`

## Fonksiyonlar (12)

- `compute()`
- `compute()`
- `compute()`
- `compute()`
- `compute()`
- `_is_recent()`
- `compute()`
- `compute()`
- `compute()`
- `compute()`
- `__init__()`
- `compute_all()`

