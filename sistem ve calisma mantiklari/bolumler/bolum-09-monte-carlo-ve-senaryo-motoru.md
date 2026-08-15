# Bölüm 9 — Monte Carlo ve Senaryo Motoru

## Amaç

Tek bir tahmin yerine, binlerce farklı olası piyasa geleceğini simüle ederek getiri ve kayıp dağılımını görmek.

**Kaynak:** GBM (Geometric Brownian Motion), VaR/CVaR risk measurement, tail risk analysis.

---

## Çalışma mantığı

```
Bölüm 8 Tahminleri + Getiri Geçmişi + Volatilite + Korelasyon + Makro →
Monte Carlo → Binlerce Olası Gelecek → Fiyat Dağılımı → Getiri Dağılımı → Risk
```

---

## 1. Monte Carlo Simülasyonu

### Örnek: Fiyat yolu simülasyonu

```python
# services/intelligence/monte_carlo.py
from services.intelligence.monte_carlo import monte_carlo_engine

result = monte_carlo_engine.simulate_price_paths(
    ticker="THYAO", current_price=305.25,
    expected_return_annual=0.15, volatility_annual=0.25,
    horizon_days=20, num_simulations=10000,
)
# P10: 280.50, P50: 315.20, P90: 355.80
# P(pozitif): 62%, P(+5%): 41%, P(-5%): 18%
# VaR 95%: -8.2%, CVaR: -11.5%
```

---

## 2. Stress Test

### Örnek: Stres senaryoları

```python
# services/intelligence/scenario.py
from services.intelligence.scenario import scenario_engine, PREDEFINED_SCENARIOS

positions = [{"ticker": "THYAO", "sector": "AVIATION", "value": 10000, "price": 305}]
result = scenario_engine.run_scenario(
    PREDEFINED_SCENARIOS["USDTRY_10_PCT"], positions)
# portfolio_impact_pct: -5.78%
```

---

## Temel prensip

Monte Carlo geleceği tahmin ettiğini iddia etmez; mevcut varsayımlar altında mümkün geleceklerin dağılımını ve kuyruk risklerini ölçer.
