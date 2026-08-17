# Bölüm 30 — BIST Alpha Anomalileri ve Factor Investing

## Amaç

BIST'te hangi faktörler çalışıyor? Piotroski F-Score, Beneish M-Score, Fama-French faktörleri BIST'te işe yarıyor mu?

**Kaynak:** SAGE Journals (2025) Financial Fraud Detection with Altman Z-Score and Beneish M-Score, Fama-French Factor Model.

---

## Kullanılacak sistemler

- Factor Calculator
- F-Score Calculator
- M-Score Calculator
- Z-Score Calculator
- Factor Performance Tracker
- Anomaly Detector
- Cross-Sectional Ranker

---

## Çalışma mantığı

```
Şirket Finansalları → F-Score, M-Score, Z-Score hesapla →
Cross-sectional ranking → Faktör performansı → Portföy oluştur
```

---

## 1. Piotroski F-Score

### 9 kriter (her biri 0 veya 1):

```
Kârlılık (4 kriter):
1. ROA > 0
2. Operating Cash Flow > 0
3. ROA artıyor
4. Cash Flow > Net Income (accrual quality)

Leverage (3 kriter):
5. Debt ratio azalıyor
6. Current ratio artıyor
7. Hisse senedi ihraç edilmedi

Verimlilik (2 kriter):
8. Gross margin artıyor
9. Asset turnover artıyor
```

### Toplam skor: 0-9
```
8-9: Güçlü alım sinyali
0-2: Güçlü satım sinyali
```

### Örnek: F-Score hesaplama

```python
# services/factors/piotroski.py
def calculate_f_score(financials):
    score = 0
    
    # Kârlılık
    if financials["roa"] > 0:
        score += 1
    if financials["operating_cash_flow"] > 0:
        score += 1
    if financials["roa"] > financials["roa_prev"]:
        score += 1
    if financials["operating_cash_flow"] > financials["net_income"]:
        score += 1
    
    # Leverage
    if financials["debt_ratio"] < financials["debt_ratio_prev"]:
        score += 1
    if financials["current_ratio"] > financials["current_ratio_prev"]:
        score += 1
    if financials["shares_outstanding"] <= financials["shares_outstanding_prev"]:
        score += 1
    
    # Verimlilik
    if financials["gross_margin"] > financials["gross_margin_prev"]:
        score += 1
    if financials["asset_turnover"] > financials["asset_turnover_prev"]:
        score += 1
    
    return score
```

---

## 2. Beneish M-Score

### 8 değişken (dolandırıcılık tespiti):

```
M-Score = -4.84 + 0.92×DSRI + 0.528×GMI + 0.404×AQI + 0.892×SGI
          + 0.115×DEPI - 0.172×SGAI + 4.679×TATA - 0.327×LVGI

DSRI: Days Sales in Receivables Index
GMI: Gross Margin Index
AQI: Asset Quality Index
SGI: Sales Growth Index
DEPI: Depreciation Index
SGAI: SGA Expense Index
TATA: Total Accruals to Total Assets
LVGI: Leverage Index
```

### Eşik:
```
M-Score > -1.78 → Manipülasyon olasılığı yüksek
M-Score < -1.78 → Manipülasyon olasılığı düşük
```

### Örnek: M-Score hesaplama

```python
# services/factors/beneish.py
def calculate_m_score(financials):
    # DSRI
    dsri = (financials["receivables"] / financials["revenue"]) / \
           (financials["receivables_prev"] / financials["revenue_prev"])
    
    # GMI
    gmi = financials["gross_margin_prev"] / financials["gross_margin"]
    
    # AQI
    aqi = (1 - (financials["current_assets"] + financials["ppe"]) / financials["total_assets"]) / \
          (1 - (financials["current_assets_prev"] + financials["ppe_prev"]) / financials["total_assets_prev"])
    
    # SGI
    sgi = financials["revenue"] / financials["revenue_prev"]
    
    # DEPI
    depi = (financials["depreciation_prev"] / (financials["ppe_prev"] + financials["depreciation_prev"])) / \
           (financials["depreciation"] / (financials["ppe"] + financials["depreciation"]))
    
    # SGAI
    sgai = (financials["sga_expense"] / financials["revenue"]) / \
           (financials["sga_expense_prev"] / financials["revenue_prev"])
    
    # TATA
    tata = (financials["net_income"] - financials["operating_cash_flow"]) / financials["total_assets"]
    
    # LVGI
    lvgi = (financials["total_debt"] / financials["total_assets"]) / \
           (financials["total_debt_prev"] / financials["total_assets_prev"])
    
    # M-Score
    m_score = -4.84 + 0.92*dsri + 0.528*gmi + 0.404*aqi + 0.892*sgi + \
              0.115*depi - 0.172*sgai + 4.679*tata - 0.327*lvgi
    
    return m_score
```

---

## 3. Altman Z-Score

### iflas tahmini:

```
Z = 1.2×X1 + 1.4×X2 + 3.3×X3 + 0.6×X4 + 1.0×X5

X1 = Working Capital / Total Assets
X2 = Retained Earnings / Total Assets
X3 = EBIT / Total Assets
X4 = Market Cap / Total Liabilities
X5 = Revenue / Total Assets
```

### Eşik:
```
Z > 2.99 → Güvenli bölge
1.81 < Z < 2.99 → Gri bölge
Z < 1.81 → Tehlikeli bölge (iflas riski)
```

### Örnek: Z-Score hesaplama

```python
# services/factors/altman.py
def calculate_z_score(financials):
    x1 = financials["working_capital"] / financials["total_assets"]
    x2 = financials["retained_earnings"] / financials["total_assets"]
    x3 = financials["ebit"] / financials["total_assets"]
    x4 = financials["market_cap"] / financials["total_liabilities"]
    x5 = financials["revenue"] / financials["total_assets"]
    
    z = 1.2*x1 + 1.4*x2 + 3.3*x3 + 0.6*x4 + 1.0*x5
    
    return z
```

---

## 4. Fama-French Faktörleri

### 5 faktör:
```
SMB (Small Minus Big):      Küçük şirketler büyük şirketlerden iyi performans
HML (High Minus Low):       Değer şirketleri büyüme şirketlerden iyi
RMW (Robust Minus Weak):    Güçlü kârlılık zayıf kârlılıktan iyi
CMA (Conservative Minus Aggressive): Tutucu şirketler agresif şirketlerden iyi
MOM (Momentum):             Son 12 ay kazananlar kaybedenlerden iyi
```

### BIST'te faktör performansı:
```
Value (HML):     BIST'te güçlü çalışıyor (düşük P/E premium)
Momentum (MOM):  BIST'te değişken (kur volatilitesi etkisi)
Size (SMB):      BIST'te zayıf (likidite farkı)
Quality (RMW):   BIST'te orta çalışıyor
```

### Örnek: Faktör skoru

```python
# services/factors/fama_french.py
def calculate_factor_scores(stock, universe):
    scores = {}
    
    # Value
    scores["value"] = 1 / stock["pe_ratio"]  # Düşük P/E = yüksek değer
    
    # Momentum
    scores["momentum"] = stock["return_12m"] - stock["return_1m"]
    
    # Quality
    scores["quality"] = stock["roe"] * (1 - stock["debt_ratio"])
    
    # Size
    scores["size"] = -np.log(stock["market_cap"])  # Küçük = yüksek skor
    
    # Low volatility
    scores["low_vol"] = -stock["volatility_60d"]
    
    return scores
```

---

## 5. BIST'e Özel Anomaliler

### a) Temettü anomalisi:
```
BIST'te yüksek temettü veren hisseler uzun vadede daha iyi performans gösteriyor
Neden: Türk yatırımcılar temettüye değer veriyor
```

### b) Likidite anomalisi:
```
Düşük likiditeli hisseler daha yüksek getiri sağlıyor
Neden: Likidite riski primi
```

### c) Kur etkisi anomalisi:
```
USDTRY artışından sonra ihracatçı hisseler ertesi gün yükseliyor
Neden: Gecikmeli fiyatlanma
```

### Örnek: BIST anomalileri

```python
# services/factors/bist_anomalies.py
def calculate_bist_anomalies(stock, market_data):
    anomalies = {}
    
    # Temettü anomalisi
    anomalies["dividend_yield"] = stock["dividend_yield"]
    anomalies["dividend_premium"] = stock["dividend_yield"] - market_data["avg_dividend_yield"]
    
    # Likidite anomalisi
    anomalies["illiquidity"] = stock["avg_volume"] / market_data["avg_market_volume"]
    anomalies["illiquidity_premium"] = 1 / anomalies["illiquidity"]  # Düşük likidite = yüksek premium
    
    # Kur etkisi
    anomalies["fx_sensitivity"] = stock["usdtry_beta"]
    anomalies["fx_impact_today"] = market_data["usdtry_change_1d"] * stock["usdtry_beta"]
    
    return anomalies
```

---

## 6. Cross-Sectional Ranking

### Faktör bazlı sıralama:

```python
# services/factors/ranking.py
def rank_stocks(universe, factors):
    scores = {}
    
    for stock in universe:
        score = 0
        for factor, weight in factors.items():
            score += stock[factor] * weight
        scores[stock["ticker"]] = score
    
    # Sırala
    ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    
    return ranked
```

### Örnek: Çok faktörlü sıralama

```python
factors = {
    "value": 0.25,
    "momentum": 0.25,
    "quality": 0.20,
    "low_vol": 0.15,
    "dividend_yield": 0.15,
}

ranked = rank_stocks(bist100, factors)
# [("THYAO", 0.85), ("ASELS", 0.82), ("GARAN", 0.79), ...]
```

---

## 7. Faktör Performans Takibi

```python
# services/factors/performance.py
def track_factor_performance(factor_returns, benchmark_returns):
    results = {}
    
    # Faktör getirisi
    results["factor_return"] = factor_returns.mean() * 252
    results["benchmark_return"] = benchmark_returns.mean() * 252
    results["alpha"] = results["factor_return"] - results["benchmark_return"]
    
    # Faktör Sharpe
    results["factor_sharpe"] = results["factor_return"] / (factor_returns.std() * (252 ** 0.5))
    
    # Faktör drawdown
    cumulative = (1 + factor_returns).cumprod()
    drawdown = (cumulative / cumulative.cummax() - 1).min()
    results["max_drawdown"] = drawdown
    
    return results
```

---

## Çıktı

```
F-Score (THYAO):      7/9 (Güçlü)
M-Score (THYAO):      -2.15 (Güvenli)
Z-Score (THYAO):      3.42 (Güvenli)
Factor Ranking:        THYAO #3, ASELS #7, GARAN #12
Value Premium:         +4.2% annual
Momentum Premium:      +2.8% annual
Quality Premium:       +3.1% annual
```

---

## Temel prensip

BIST'te faktör investing çalışıyor ama her faktör eşit değil. **Value ve Quality faktörleri BIST'te güçlü çalışıyor, Momentum değişken, Size zayıf.** F-Score ve Z-Score BIST şirketleri için güvenilir filtreler.

> Kaynak: SAGE Journals (2025) Financial Fraud Detection, Fama-French Factor Model
