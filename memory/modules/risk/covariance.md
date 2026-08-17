# risk/covariance

**Dosya:** `services/risk/covariance.py`
**Satır:** 153

## Açıklama

ALPHA BIST — Covariance Estimation v3.0

ROADMAP v3.0 FAZ 5:
- Ledoit-Wolf shrinkage (basit sample covariance yerine)
- Robust covariance estimation
- Factor model covariance (opsiyonel)

KURAL: Sample covariance = gürültü. Shrinkage = gerçek.

## Sınıflar (1)

- `CovarianceEstimator`

## Fonksiyonlar (5)

- `__init__()`
- `estimate()`
- `_compute_shrinkage_intensity()`
- `compute_portfolio_volatility()`
- `compute_diversification_ratio()`

