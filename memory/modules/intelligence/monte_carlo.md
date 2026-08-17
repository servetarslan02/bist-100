# intelligence/monte_carlo

**Dosya:** `services/intelligence/monte_carlo.py`
**Satır:** 320

## Açıklama

ALPHA BIST — Monte Carlo Engine v1.0

Fiyat yolu simülasyonu:
- Binlerce olası gelecek yol
- Percentile dağılımları (P10, P25, P50, P75, P90)
- Olasılık hesaplamaları (P(+10%), P(-5%), vb.)
- Portfolio-level Monte Carlo (korelasyon matrisi ile)
- VaR / CVaR

FAZ 5.1-5.2: Monte Carlo Engine

## Sınıflar (3)

- `MonteCarloResult`
- `PortfolioMonteCarloResult`
- `MonteCarloEngine`

## Fonksiyonlar (3)

- `simulate_price_paths()`
- `simulate_portfolio()`
- `compute_dynamic_scenario_count()`

