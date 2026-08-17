# ml/adjusted_loss

**Dosya:** `services/ml/adjusted_loss.py`
**Satır:** 111

## Açıklama

ALPHA BIST — Adjusted MSE Loss v1.0

ROADMAP v3.0: Yanlış yön tahminleri 11x ceza
- Asimetrik loss: Yanlış yön tahminler 11x daha ağır cezalandırılır
- Bu tek başına +0.44 Sharpe katkısı

KURAL: Yanlış yön tahminler çok pahalı!

## Sınıflar (1)

- `AdjustedMSELoss`

## Fonksiyonlar (4)

- `__init__()`
- `calculate()`
- `calculate_per_sample()`
- `get_gradient()`

