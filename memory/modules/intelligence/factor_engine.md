# intelligence/factor_engine

**Dosya:** `services/intelligence/factor_engine.py`
**Satır:** 288

## Açıklama

ALPHA BIST — Factor Engine v1.0

Faktör bazlı analiz:
- Value (P/E, P/B, FCF Yield)
- Momentum (ROC, relative strength)
- Quality (ROE, margins, cash flow)
- Size (market cap)
- Low Volatility
- Factor Exposure

FAZ 10.8: Factor Engine

## Sınıflar (3)

- `FactorScore`
- `FactorExposure`
- `FactorEngine`

## Fonksiyonlar (7)

- `compute_factor_scores()`
- `_compute_value()`
- `_compute_momentum()`
- `_compute_quality()`
- `_compute_size()`
- `_compute_low_vol()`
- `compute_portfolio_exposure()`

## Bağlantılar

Bu modül şu modülleri kullanır:

- `factors/piotroski`
- `factors/altman`
- `factors/beneish`

