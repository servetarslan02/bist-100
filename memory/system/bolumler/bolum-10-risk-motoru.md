# Bölüm 10 — Risk Motoru

## Amaç

Bir hissenin sadece ne kadar kazandırabileceğini değil, ne kadar ve hangi koşullarda kaybettirebileceğini belirlemek.

**Kaynak:** Du (2026) Ledoit-Wolf covariance, Oxford (2023) volatility targeting, Kelly criterion.

---

## Kullanılacak sistemler

- Risk Engine
- VaR / CVaR
- Maximum Drawdown
- Volatility
- Liquidity Risk
- Concentration Risk
- Factor Exposure
- Stress Test sonuçları
- Monte Carlo sonuçları
- Position Sizing

## Çalışma mantığı

```
Hisse + Monte Carlo + Volatilite + Market Regime + Fundamental Risk + Liquidity + Portfolio →
RISK ENGINE → Risk Score + Maximum Loss + Drawdown + Position Limit + Risk/Reward
```

---

## 1. Ledoit-Wolf Kovaryans

### Örnek: Regularized kovaryans

```python
# services/risk/enhanced_risk.py
from services.risk.enhanced_risk import ledoit_wolf
import numpy as np

returns = np.random.randn(100, 5) * 0.02
cov = ledoit_wolf.estimate(returns)
# 5x5 kovaryans matrisi (shrinkage uygulanmış)
```

---

## 2. Kelly Criterion

### Örnek: Pozisyon boyutu

```python
from services.risk.enhanced_risk import position_sizer

kelly = position_sizer.kelly_criterion(0.6, 2.0, 1.0, fraction=0.5)
# kelly = 0.20 (yarım Kelly)

size = position_sizer.compute_position_size(100000, kelly, 305.25, 15.26)
# size = 131 lot
```

---

## 3. Volatility Targeting

### Örnek: Kaldıraç hesaplama

```python
from services.risk.enhanced_risk import volatility_targeter

leverage = volatility_targeter.compute_leverage(0.10, 0.20)
# leverage = 2.0 (düşük vol → yüksek kaldıraç)

leverage = volatility_targeter.compute_leverage(0.40, 0.20)
# leverage = 0.5 (yüksek vol → düşük kaldıraç)
```

---

## Çıktı

```
Risk Score:     34/100
Risk Level:     Orta
VaR:            -8.2%
Max Drawdown:   -12%
Position Limit: %5
Risk/Reward:    2.8
```

---

## Temel prensip

"Bu hisse iyi mi?" sorusundan önce "bu fırsatı hangi riskle ve portföyün ne kadarını kullanarak değerlendirmeliyiz?" sorusunu cevaplar.

## 5. Türkiye'ye Özgü Riskler

### Ülke riski (CDS):
```python
def compute_country_risk(cds_5y):
    if cds_5y > 400:
        return {"level": "HIGH", "impact": "Yabancı çıkış, kur baskısı"}
    elif cds_5y > 250:
        return {"level": "MEDIUM", "impact": "Sınırlı yabancı ilgisi"}
    else:
        return {"level": "LOW", "impact": "Yabancı giriş destekli"}
```

### Kur riski:
```python
def compute_fx_risk(portfolio, usdtry_change):
    fx_exposure = sum(pos["value"] * pos.get("fx_beta", 0) for pos in portfolio)
    fx_impact = fx_exposure * usdtry_change

    return {
        "fx_exposure": fx_exposure,
        "fx_impact": fx_impact,
        "hedge_needed": abs(fx_impact) > portfolio.total_value * 0.02,
    }
```

### Siyasi risk:
```python
def compute_political_risk(events):
    risk_score = 0
    
    for event in events:
        if event["type"] == "ELECTION":
            risk_score += 20
        elif event["type"] == "POLICY_CHANGE":
            risk_score += 15
        elif event["type"] == "GEOPOLITICAL":
            risk_score += 25
    
    return min(risk_score, 100)
```

---

## Options/VIOP Entegrasyonu

**Kaynak:** Bölüm 32 — Options ve VIOP

Bu bölümün risk motoru, Bölüm 32'deki türev araçlarla genişler:

| Risk Ölçümü | Bölüm 32 Motoru | Bölüm 10 Kullanımı |
|-------------|----------------|-------------------|
| Greeks | `viop/greeks.py` | Delta, Gamma, Vega riski |
| Options Pricing | `viop/options_pricing.py` | Opsiyon değerleme |
| Hedging | `viop/hedging.py` | Portföy korunma |
| Margin | `viop/margin.py` | Teminat hesaplama |

### Örnek: Greeks → Risk skoru

```python
from services.viop.greeks import calculate_greeks

greeks = calculate_greeks(S=305.25, K=310, T=30 / 365, r=0.42, sigma=0.25)
# delta: 0.55 → fiyat riski
# gamma: 0.02 → delta değişimi
# theta: -0.15 → zaman aşınması
# vega: 1.20 → volatilite riski

# Risk skoruna ekle
portfolio_risk["options_delta"] = greeks["delta"]
portfolio_risk["options_vega"] = greeks["vega"]
```

### UYARI: Black-Scholes sınırlamaları

Bölüm 32'deki Black-Scholes formülü varsayımları:
- Sabit volatilite (gerçek: volatilite yüzeyi)
- Sürekli trading (gerçek: BIST seans saatleri)
- Sabit faiz (gerçek: TCMB değişken)

Production'da volatilite yüzeyi ve gerçek VIOP sözleşme özellikleri kullanılmalı.
