# Bölüm 32 — Options ve VIOP

## Amaç

BIST'in türev ürünler piyasası (VIOP) üzerinden opsiyon ve vadeli işlem stratejileri oluşturmak, korunma (hedging) yapmak.

**Kaynak:** Borsa İstanbul VIOP (borsaistanbul.com/en/markets/viop), Options pricing models.

---

## Kullanılacak sistemler

- VIOP Data Collector
- Options Pricing Engine (Black-Scholes)
- Greeks Calculator (Delta, Gamma, Theta, Vega)
- Hedging Engine
- Spread Strategy Builder
- Margin Calculator
- Put-Call Parity Checker

---

## Çalışma mantığı

```
Spot pozisyon → Korunma ihtiyacı → VIOP ürün seçimi →
Opsiyon/vadeli fiyatla → Greeks hesapla → Strateji oluştur →
Teminat kontrolü → Emir gönder
```

---

## 1. VIOP Ürünleri

### Vadeli İşlem (Futures):
```
Endeks Vadeli:    BIST-30 Endeks Vadeli (XU030)
Döviz Vadeli:     USDTRY Vadeli
Altın Vadeli:     Gram Altın Vadeli
Pay Vadeli:       Hisse senedi vadeli (THYAO, GARAN, vb.)
```

### Opsiyonlar:
```
Endeks Opsiyon:   BIST-30 Opsiyon
Pay Opsiyon:      Hisse senedi opsiyonu (THYAO, ASELS, vb.)
```

---

## 2. Black-Scholes Fiyatlama

### Formül:
```
C = S × N(d1) - K × e^(-rT) × N(d2)
P = K × e^(-rT) × N(-d2) - S × N(-d1)

d1 = [ln(S/K) + (r + σ²/2)T] / (σ√T)
d2 = d1 - σ√T

C: Call fiyatı
P: Put fiyatı
S: Spot fiyat
K: Kullanım fiyatı
r: Risksiz faiz
T: Vade (yıl)
σ: Volatilite
```

### Örnek: Opsiyon fiyatlama

```python
# services/viop/options_pricing.py
import numpy as np
from scipy.stats import norm


def black_scholes(S, K, T, r, sigma, option_type="call"):
    d1 = (np.log(S / K) + (r + sigma**2 / 2) * T) / (sigma * np.sqrt(T))
    d2 = d1 - sigma * np.sqrt(T)

    if option_type == "call":
        price = S * norm.cdf(d1) - K * np.exp(-r * T) * norm.cdf(d2)
    else:
        price = K * np.exp(-r * T) * norm.cdf(-d2) - S * norm.cdf(-d1)

    return price


# THYAO opsiyonu
call_price = black_scholes(S=305.25, K=310, T=30 / 365, r=0.42, sigma=0.25, option_type="call")
# call_price = 4.85 TL
```

---

## 3. Greeks (Opsiyon Yunan Harfleri)

### Delta (Δ):
```
Δ_call = N(d1)       → 0 ile 1 arası
Δ_put  = N(d1) - 1   → -1 ile 0 arası
Yorum: Fiyat 1 TL değişirse opsiyonun değeri Δ kadar değişir
```

### Gamma (Γ):
```
Γ = N'(d1) / (S × σ × √T)
Yorum: Delta'nın fiyata göre değişim hızı
```

### Theta (Θ):
```
Θ = -[S × N'(d1) × σ / (2√T)] - rKe^(-rT)N(d2)
Yorum: Zamanın opsiyona etkisi (zaman aşınması)
```

### Vega (ν):
```
ν = S × √T × N'(d1)
Yorum: Volatilite değişimine duyarlılık
```

### Örnek: Greeks hesaplama

```python
# services/viop/greeks.py
def calculate_greeks(S, K, T, r, sigma, option_type="call"):
    d1 = (np.log(S / K) + (r + sigma**2 / 2) * T) / (sigma * np.sqrt(T))
    d2 = d1 - sigma * np.sqrt(T)

    if option_type == "call":
        delta = norm.cdf(d1)
        theta = (-S * norm.pdf(d1) * sigma / (2 * np.sqrt(T))) - (r * K * np.exp(-r * T) * norm.cdf(d2))
    else:
        delta = norm.cdf(d1) - 1
        theta = (-S * norm.pdf(d1) * sigma / (2 * np.sqrt(T))) + (r * K * np.exp(-r * T) * norm.cdf(-d2))

    gamma = norm.pdf(d1) / (S * sigma * np.sqrt(T))
    vega = S * np.sqrt(T) * norm.pdf(d1)
    rho = K * T * np.exp(-r * T) * (norm.cdf(d2) if option_type == "call" else -norm.cdf(-d2))

    return {"delta": delta, "gamma": gamma, "theta": theta, "vega": vega, "rho": rho}
```

---

## 4. Stratejiler

### a) Covered Call (Korumalı Alım):
```
Spot hisse sat + Call opsiyon yaz
Amaç: Gelir artırımı
Risk: Sınırlı kazanç, sınırlı kayıp
```

### b) Protective Put (Koruyucu Satım):
```
Spot hisse al + Put opsiyon al
Amaç: Düşüşe karşı korunma
Risk: Sınırlı kayıp (opsiyon primi maliyet)
```

### c) Straddle:
```
Call al + Put al (aynak strike, aynı vade)
Amaç: Yüksek volatiliteden kazanç
Risk: Düşük volatilitede kayıp
```

### d) Iron Condor:
```
Call spread sat + Put spread sat
Amaç: Düşük volatiliteden kazanç
Risk: Sınırlı kazanç, sınırlı kayıp
```

### Örnek: Strateji oluştur

```python
# services/viop/strategies.py
def create_covered_call(spot_price, call_strike, call_premium, shares):
    max_profit = (call_strike - spot_price + call_premium) * shares
    max_loss = (spot_price - call_premium) * shares  # Hisse sıfır olursa
    breakeven = spot_price - call_premium

    return {
        "strategy": "Covered Call",
        "spot_price": spot_price,
        "call_strike": call_strike,
        "call_premium": call_premium,
        "max_profit": max_profit,
        "max_loss": max_loss,
        "breakeven": breakeven,
        "profit_zone": f"Spot > {breakeven} and Spot < {call_strike}",
    }


def create_protective_put(spot_price, put_strike, put_premium, shares):
    max_loss = (spot_price - put_strike + put_premium) * shares
    max_profit = float("inf")  # Yukarı potansiyel sınırsız
    breakeven = spot_price + put_premium

    return {
        "strategy": "Protective Put",
        "spot_price": spot_price,
        "put_strike": put_strike,
        "put_premium": put_premium,
        "max_loss": max_loss,
        "max_profit": max_profit,
        "breakeven": breakeven,
        "profit_zone": f"Spot > {breakeven}",
    }
```

---

## 5. Put-Call Parity

### Formül:
```
C - P = S - K × e^(-rT)

C: Call fiyatı
P: Put fiyatı
S: Spot fiyat
K: Kullanım fiyatı
r: Risksiz faiz
T: Vade
```

### Örnek: Parity kontrolü

```python
# services/viop/parity.py
def check_put_call_parity(call_price, put_price, spot_price, strike, r, T):
    lhs = call_price - put_price
    rhs = spot_price - strike * np.exp(-r * T)

    deviation = abs(lhs - rhs)

    return {
        "parity_holds": deviation < 0.01,
        "deviation": deviation,
        "lhs": lhs,
        "rhs": rhs,
        "arbitrage_opportunity": deviation > 0.05,
    }
```

---

## 6. Teminat Hesaplama (SPAN)

VIOP'ta teminat SPAN (Standard Portfolio Analysis of Risk) sistemi ile hesaplanır:

```python
# services/viop/margin.py
def calculate_span_margin(positions):
    total_margin = 0
    
    for pos in positions:
        # Hisse vadeli: %10-20 teminat
        if pos["type"] == "EQUITY_FUTURE":
            margin = pos["value"] * 0.15
        
        # Endeks vadeli: %10-15 teminat
        elif pos["type"] == "INDEX_FUTURE":
            margin = pos["value"] * 0.12
        
        # Opsiyon: Prim + ek teminat
        elif pos["type"] == "OPTION":
            margin = pos["premium"] + pos["value"] * 0.10
        
        total_margin += margin
    
    return total_margin
```

---

## 7. Hedging (Korunma)

### Portföy korunma:
```python
# services/viop/hedging.py
def hedge_portfolio(portfolio_value, beta, futures_price, multiplier=100):
    # Hedge ratio
    hedge_ratio = beta * portfolio_value / (futures_price * multiplier)

    # Kaç kontrat gerekli
    contracts_needed = round(hedge_ratio)

    return {
        "hedge_ratio": hedge_ratio,
        "contracts_needed": contracts_needed,
        "hedge_type": "SHORT" if beta > 0 else "LONG",
        "coverage": contracts_needed * futures_price * multiplier / portfolio_value,
    }
```

---

## Çıktı

```
VIOP Products:        Futures (4) + Options (2)
Black-Scholes Price:  4.85 TL (THYAO Call)
Delta:                0.55
Gamma:                0.02
Theta:                -0.15
Vega:                 1.20
Strategy:             Covered Call
Max Profit:           ₺6,850
Max Loss:             ₺24,150
Margin Required:      ₺15,000
```

---

## Temel prensip

VIOP, BIST'in türev ürünler piyasasıdır. **Opsiyonlar korunma, gelir artırımı ve spekülasyon için kullanılabilir.** Greeks, opsiyon riskini ölçmek için kritiktir.

> Kaynak: Borsa İstanbul VIOP (borsaistanbul.com), Black-Scholes Model
