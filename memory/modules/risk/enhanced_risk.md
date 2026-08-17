# risk/enhanced_risk

**Dosya:** `services/risk/enhanced_risk.py`
**Satır:** 318

## Açıklama

ALPHA BIST — Enhanced Risk & Portfolio Engine v1.0

Risk:
- Ledoit-Wolf covariance estimation
- Volatility targeting
- Correlation risk
- Concentration risk

Portfolio:
- Markowitz optimization with transaction costs
- Kelly criterion position sizing
- Rebalance rules

Kaynak: Du (2026) — Ledoit-Wolf; Oxford — volatility targeting

## Sınıflar (7)

- `PortfolioWeights`
- `RiskMetrics`
- `LedoitWolfCovariance`
- `VolatilityTargeter`
- `PositionSizer`
- `RebalanceEngine`
- `ConcentrationRisk`

## Fonksiyonlar (12)

- `estimate()`
- `_estimate_shrinkage()`
- `compute_leverage()`
- `adjust_weights()`
- `kelly_criterion()`
- `compute_position_size()`
- `__init__()`
- `compute_rebalance()`
- `compute_next_rebalance()`
- `compute_hhi()`
- `compute_sector_concentration()`
- `compute_max_concentration()`

## Bağlantılar

Bu modül şu modülleri kullanır:

- `viop/strategies`
- `viop/hedging`

