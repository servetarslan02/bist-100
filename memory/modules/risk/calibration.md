# risk/calibration

**Dosya:** `services/risk/calibration.py`
**Satır:** 122

## Açıklama

ALPHA BIST — Score Calibration v1.0

Ranking model skorunu gercek win_probability'ye donusturur.
Platt Scaling (logistic regression) veya Isotonic Regression kullanir.

KURAL: Score != win_probability. Calibration gerekli.

## Sınıflar (2)

- `CalibrationParams`
- `ScoreCalibrator`

## Fonksiyonlar (5)

- `__init__()`
- `fit_from_trades()`
- `calibrate()`
- `add_trade()`
- `get_avg_win_loss()`

