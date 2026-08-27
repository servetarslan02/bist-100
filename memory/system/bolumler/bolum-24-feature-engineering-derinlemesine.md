# Bölüm 24 — Feature Engineering Derinlemesine

## Amaç

Ham veriden en bilgilendirici feature'ları üretmek. Hangi teknik göstergeler BIST'te çalışıyor? Hangileri gürültü?

**Kaynak:** ScienceDirect (2025) Key Technical Indicators for Stock Market Prediction, MDPI (2026) Regime-Aware LightGBM — 63 normalized features across five categories, arXiv (2026) Sentiment-Aware Stock Price Prediction with Transformer.

---

## Kullanılacak sistemler

- Feature Calculator
- Technical Indicator Engine
- Fundamental Feature Engine
- Sentiment Feature Engine
- Macro Feature Engine
- Feature Selector (SHAP, importance)
- Feature Store
- Feature Validator

---

## Çalışma mantığı

```
Ham OHLCV + Fundamental + News + Macro →
Feature Groups (5 kategori) →
Normalization → Feature Selection →
Feature Store → Model input
```

---

## 1. Feature Kategorileri

**Araştırma bulgusu:** MDPI (2026) — "A total of 63 normalized features were engineered across five categories, following the established technical analysis literature."

### 5 ana kategori:

```
1. Trend Features (yön belirleme)
2. Momentum Features (hız ölçme)
3. Volatility Features (dalgalanma ölçme)
4. Volume Features (hacim analizi)
5. Fundamental Features (şirket verileri)
```

---

## 2. Trend Features

### Moving Averages:
```
SMA  (Simple Moving Average)     → Basit ortalama
EMA  (Exponential Moving Average) → Ağırlıklı ortalama
WMA  (Weighted Moving Average)   → Lineer ağırlıklı
DEMA (Double EMA)                → Gecikmeyi azaltır
TEMA (Triple EMA)                → Daha da az gecikme
```

### Crossover sinyalleri:
```
Golden Cross: SMA50 > SMA200 → Yükseliş sinyali
Death Cross:  SMA50 < SMA200 → Düşüş sinyali
MACD Cross:   MACD > Signal  → Alım sinyali
```

### Örnek: Trend feature'ları

```python
# services/features/technical_features.py
def compute_trend_features(prices):
    features = {}
    
    # Moving averages
    features["sma_20"] = prices.rolling(20).mean()
    features["sma_50"] = prices.rolling(50).mean()
    features["sma_200"] = prices.rolling(200).mean()
    features["ema_12"] = prices.ewm(span=12).mean()
    features["ema_26"] = prices.ewm(span=26).mean()
    
    # MACD
    features["macd"] = features["ema_12"] - features["ema_26"]
    features["macd_signal"] = features["macd"].ewm(span=9).mean()
    features["macd_histogram"] = features["macd"] - features["macd_signal"]
    
    # Crossover
    features["golden_cross"] = (features["sma_50"] > features["sma_200"]).astype(int)
    features["death_cross"] = (features["sma_50"] < features["sma_200"]).astype(int)
    
    # Price position
    features["price_vs_sma20"] = (prices - features["sma_20"]) / features["sma_20"]
    features["price_vs_sma50"] = (prices - features["sma_50"]) / features["sma_50"]
    
    return features
```

---

## 3. Momentum Features

### RSI (Relative Strength Index):
```
RSI = 100 - (100 / (1 + RS))
RS  = Ortalama kazanç / Ortalama kayıp
Aşırı alım: > 70
Aşırı satım: < 30
```

### ROC (Rate of Change):
```
ROC = (Fiyat - n gün önceki fiyat) / n gün önceki fiyat × 100
```

### Stochastic:
```
%K = (Kapanış - En düşük) / (En yüksek - En düşük) × 100
%D = %K'nın 3 günlük hareketli ortalaması
```

### Örnek: Momentum feature'ları

```python
def compute_momentum_features(prices, highs, lows):
    features = {}
    
    # RSI
    delta = prices.diff()
    gain = delta.where(delta > 0, 0).rolling(14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
    rs = gain / loss
    features["rsi_14"] = 100 - (100 / (1 + rs))
    
    # ROC
    features["roc_5"] = prices.pct_change(5) * 100
    features["roc_10"] = prices.pct_change(10) * 100
    features["roc_20"] = prices.pct_change(20) * 100
    
    # Stochastic
    low_14 = lows.rolling(14).min()
    high_14 = highs.rolling(14).max()
    features["stoch_k"] = (prices - low_14) / (high_14 - low_14) * 100
    features["stoch_d"] = features["stoch_k"].rolling(3).mean()
    
    # Williams %R
    features["williams_r"] = (high_14 - prices) / (high_14 - low_14) * -100
    
    return features
```

---

## 4. Volatility Features

### ATR (Average True Range):
```
TR = max(High-Low, |High-Previous Close|, |Low-Previous Close|)
ATR = TR'nin 14 günlük hareketli ortalaması
```

### Bollinger Bands:
```
Upper = SMA20 + 2 × StdDev
Lower = SMA20 - 2 × StdDev
Bandwidth = (Upper - Lower) / SMA20
%B = (Fiyat - Lower) / (Upper - Lower)
```

### Örnek: Volatility feature'ları

```python
def compute_volatility_features(prices, highs, lows, closes):
    features = {}

    # ATR
    tr1 = highs - lows
    tr2 = abs(highs - closes.shift(1))
    tr3 = abs(lows - closes.shift(1))
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    features["atr_14"] = tr.rolling(14).mean()
    features["atr_pct"] = features["atr_14"] / prices * 100

    # Bollinger Bands
    sma20 = prices.rolling(20).mean()
    std20 = prices.rolling(20).std()
    features["bb_upper"] = sma20 + 2 * std20
    features["bb_lower"] = sma20 - 2 * std20
    features["bb_bandwidth"] = (features["bb_upper"] - features["bb_lower"]) / sma20
    features["bb_pct"] = (prices - features["bb_lower"]) / (features["bb_upper"] - features["bb_lower"])

    # Historical volatility
    returns = prices.pct_change()
    features["volatility_20"] = returns.rolling(20).std() * (252**0.5)
    features["volatility_60"] = returns.rolling(60).std() * (252**0.5)

    # Volatility ratio
    features["vol_ratio"] = features["volatility_20"] / features["volatility_60"]

    return features
```

---

## 5. Volume Features

### OBV (On-Balance Volume):
```
OBV = Önceki OBV + Volume (kapanış yükseldiyse)
OBV = Önceki OBV - Volume (kapanış düştüyse)
```

### VWAP (Volume Weighted Average Price):
```
VWAP = Σ(Hacim × Fiyat) / Σ(Hacim)
```

### Örnek: Volume feature'ları

```python
def compute_volume_features(prices, volumes):
    features = {}
    
    # OBV
    obv = (np.sign(prices.diff()) * volumes).cumsum()
    features["obv"] = obv
    features["obv_sma20"] = obv.rolling(20).mean()
    features["obv_trend"] = obv - features["obv_sma20"]
    
    # VWAP (günlük)
    typical_price = prices  # Simplified
    features["vwap"] = (typical_price * volumes).cumsum() / volumes.cumsum()
    features["price_vs_vwap"] = (prices - features["vwap"]) / features["vwap"]
    
    # Volume anomaly
    vol_sma = volumes.rolling(20).mean()
    vol_std = volumes.rolling(20).std()
    features["volume_zscore"] = (volumes - vol_sma) / vol_std
    features["volume_ratio"] = volumes / vol_sma
    
    # MFI (Money Flow Index)
    typical_price = (prices + prices.shift(1)) / 2
    money_flow = typical_price * volumes
    positive_flow = money_flow.where(typical_price > typical_price.shift(1), 0).rolling(14).sum()
    negative_flow = money_flow.where(typical_price < typical_price.shift(1), 0).rolling(14).sum()
    mfi = 100 - (100 / (1 + positive_flow / negative_flow))
    features["mfi_14"] = mfi
    
    return features
```

---

## 6. Fundamental Features

### Değerleme ratios:
```
P/E, P/B, EV/EBITDA, P/S, P/CF
Dividend Yield, FCF Yield
ROE, ROA, ROIC
Debt/Equity, Current Ratio, Quick Ratio
Revenue Growth, Earnings Growth, FCF Growth
```

### Örnek: Fundamental feature'lar

```python
def compute_fundamental_features(fundamentals):
    features = {}
    
    # Değerleme
    features["pe_ratio"] = fundamentals["price"] / fundamentals["eps"]
    features["pb_ratio"] = fundamentals["price"] / fundamentals["bvps"]
    features["ev_ebitda"] = fundamentals["enterprise_value"] / fundamentals["ebitda"]
    features["dividend_yield"] = fundamentals["dps"] / fundamentals["price"]
    features["fcf_yield"] = fundamentals["fcf"] / fundamentals["market_cap"]
    
    # Kârlılık
    features["roe"] = fundamentals["net_income"] / fundamentals["equity"]
    features["roa"] = fundamentals["net_income"] / fundamentals["total_assets"]
    features["gross_margin"] = fundamentals["gross_profit"] / fundamentals["revenue"]
    features["net_margin"] = fundamentals["net_income"] / fundamentals["revenue"]
    
    # Büyüme
    features["revenue_growth"] = fundamentals["revenue_growth_yoy"]
    features["earnings_growth"] = fundamentals["earnings_growth_yoy"]
    
    # Sağlık
    features["debt_equity"] = fundamentals["total_debt"] / fundamentals["equity"]
    features["current_ratio"] = fundamentals["current_assets"] / fundamentals["current_liabilities"]
    
    # Enflasyon düzeltmesi (TMS 29)
    if fundamentals.get("inflation_adjusted"):
        features["real_roe"] = features["roe"] - fundamentals["inflation_rate"]
    
    return features
```

---

## 7. Feature Selection (Özellik Seçimi)

**Araştırma bulgusu:** ScienceDirect (2025) — "Feature selection enhances the accuracy of machine learning predictions and saves time."

### Yöntemler:

```
1. SHAP (SHapley Additive exPlanations)
2. Mutual Information
3. Recursive Feature Elimination (RFE)
4. L1 Regularization (Lasso)
5. Correlation Filter
```

### Örnek: SHAP ile feature importance

```python
# services/features/feature_selector.py
import shap


def select_features_shap(model, X_train, y_train, top_n=20):
    explainer = shap.TreeExplainer(model)
    shap_values = explainer.shap_values(X_train)

    importance = pd.DataFrame({"feature": X_train.columns, "importance": np.abs(shap_values).mean(axis=0)}).sort_values(
        "importance", ascending=False
    )

    return importance.head(top_n)["feature"].tolist()
```

### Örnek: Korelasyon filtresi

```python
def filter_correlated_features(X, threshold=0.95):
    corr_matrix = X.corr().abs()
    upper = corr_matrix.where(np.triu(np.ones(corr_matrix.shape), k=1).astype(bool))
    
    to_drop = [col for col in upper.columns if any(upper[col] > threshold)]
    
    return X.drop(columns=to_drop), to_drop
```

---

## 8. Feature Store

Feature'ları tekrar tekrar hesaplamak yerine saklar:

```python
# services/features/feature_store.py
from services.features.feature_store import feature_store

# Feature kaydet
feature_store.save(
    "THYAO",
    "2026-08-16",
    {
        "rsi_14": 55.3,
        "macd_histogram": 1.2,
        "bb_pct": 0.65,
        "volume_zscore": 2.1,
    },
)

# Feature oku
features = feature_store.get("THYAO", "2026-08-16")
# features["rsi_14"] = 55.3
```

---

## 9. BIST'e Özel Feature'lar

BIST'te diğer piyasalarda olmayan feature'lar:

```
USDTRY_change:    Döviz kuru değişimi (BIST ile ters korelasyon)
TCMB_rate_change: Merkez bankası faiz kararı
CDS_spread:       Ülke risk primi
Inflation_rate:   TÜFE/ÜFE (enflasyon muhasebesi için)
KAP_event:        KAP açıklaması var/yok
```

### Örnek: BIST-specific feature'lar

```python
def compute_bist_specific_features(market_data):
    features = {}
    
    # USDTRY etkisi
    features["usdtry_change_1d"] = market_data["usdtry"].pct_change(1)
    features["usdtry_change_5d"] = market_data["usdtry"].pct_change(5)
    features["usdtry_vs_bist_corr"] = market_data["usdtry"].rolling(20).corr(market_data["bist100"])
    
    # TCMB faiz etkisi
    features["rate_change"] = market_data["tcmb_rate"].diff()
    features["real_rate"] = market_data["tcmb_rate"] - market_data["inflation"]
    
    # CDS
    features["cds_level"] = market_data["cds_5y"]
    features["cds_change"] = market_data["cds_5y"].pct_change(5)
    
    # KAP event
    features["kap_event_today"] = market_data["kap_count_today"]
    features["kap_event_5d"] = market_data["kap_count_today"].rolling(5).sum()
    
    return features
```

---

## Çıktı

```
Feature Groups:       5 (Trend, Momentum, Vol, Volume, Fundamental)
Total Features:       63
Selected Features:    25 (SHAP ile)
Top 5 Features:       rsi_14, macd_histogram, volume_zscore, bb_pct, atr_pct
BIST-specific:        5 (USDTRY, TCMB, CDS, Inflation, KAP)
Feature Store:        Active
```

---

## Temel prensip

> "This not only enhances the accuracy of machine learning predictions but also saves time and reduces risks." — ScienceDirect (2025)

Feature engineering, model seçiminden daha önemlidir. **BIST'e özel feature'lar (USDTRY, TCMB, CDS) diğer piyasalarda kullanılmayan ama BIST'te kritik olan bilgileri taşır.**

> Kaynak: ScienceDirect (2025), MDPI (2026) 63 Features, arXiv (2026) Transformer Features
