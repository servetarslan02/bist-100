# Bölüm 4 — Hisse Keşfi ve Ön Eleme

## Amaç

BIST'teki tüm hisseleri tek tek derin analiz etmek yerine, önce çok geniş havuzu sistematik biçimde daraltıp analiz edilmeye değer adayları bulmak.

**Kaynak:** J.P. Morgan Factor Views 3Q 2026, AlphaCrafter Multi-Agent Framework (arXiv 2026), Fama-French 5-Factor Model.

---

## Kullanılacak sistemler

- Stock Discovery Engine
- Liquidity Filter
- Technical Screener
- Fundamental Screener
- Factor Engine
  - Value
  - Momentum
  - Quality
  - Growth
  - Size
  - Low Volatility
- Relative Strength
- Sector Strength
- Anomaly Detection
- Market Regime bilgisi

---

## Çalışma mantığı

```
Tüm BIST Hisseleri
    ↓
Veri / kalite filtresi
    ↓
Likidite filtresi
    ↓
Riskli / uygunsuz hisseleri ele
    ↓
Fundamental ön filtre
    ↓
Technical ön filtre
    ↓
Momentum / Relative Strength
    ↓
Value / Quality / Growth
    ↓
Sektör + Market Regime uyumu
    ↓
Skorlama
    ↓
ADAY HİSSE HAVUZU
```

---

## 1. Likidite Filtresi

Düşük likiditeli hisseler elenir.

**Kriterler:**
- Günlük ortalama hacim > 100,000 lot
- Spread < %1
- Market cap > belirli eşik

### Örnek: Likidite skoru

```python
# services/ingestion/universe_enhancements.py
from services.ingestion.universe_enhancements import universe_enhancements

score = universe_enhancements.compute_liquidity_score(
    avg_volume=1000000,    # Günlük ortalama hacim
    avg_spread_pct=0.05,   # %0.05 spread
    market_cap=50_000_000_000,  # 50 milyar TL
)
# score = 90/100 (yüksek likidite)
```

---

## 2. Factor Engine

Çoklu faktör skorlaması.

**Araştırma bulgusu:**

**J.P. Morgan (2026):** Momentum ve Quality en tutarlı faktörler. Value ve Low Volatility döngüsel.

**Fama-French:** 5 faktör (Value, Size, Profitability, Investment, Momentum) getiri varyansının çoğunu açıklar.

### Örnek: Factor skorları

```python
# services/intelligence/factor_engine.py
from services.intelligence.factor_engine import factor_engine

score = factor_engine.compute_factor_scores(
    ticker="THYAO",
    fundamentals={
        "pe_ratio": 8.5,
        "roe": 0.15,
        "profit_margin": 0.10,
        "debt_to_equity": 0.45,
    },
    technicals={
        "roc_5d": 5.0,
        "momentum_20d": 12.0,
        "realized_vol_20d": 18,
    },
)

# score.value_score = 75 (düşük P/E, yüksek ROE)
# score.momentum_score = 82 (güçlü momentum)
# score.quality_score = 70 (iyi kârlılık)
# score.low_vol_score = 65 (düşük volatilite)
# score.composite_score = 74.5
```

---

## 3. Adaptif Eşik

Piyasa koşullarına göre fırsat eşiği değişir.

### Örnek: Adaptif eşik hesaplama

```python
# services/scanner/opportunity_engine.py
import numpy as np

all_scores = [72, 68, 65, 60, 55, 50, 48, 45, 42, 40]
median_score = np.median(all_scores)  # 52.5
std_score = np.std(all_scores)        # 10.2

# Eşik = medyan + 0.5 × std
adaptive_threshold = max(40, median_score + 0.5 * std_score)
# adaptive_threshold = 57.6

# Piyasa zorsa eşik düşer
# Piyasa iyiyse eşik yükselir
```

---

## 4. 7 Motor Feature Hesaplama

Her hisse için 7 ayrı perspektiften feature hesaplanır.

### Örnek: 7 Motor çalıştırma

```python
# services/features/seven_motors.py
from services.features.seven_motors import seven_motor_engine
import numpy as np

# Fiyat verileri
close = np.array([...])  # 130 günlük kapanış
high = close + 2
low = close - 2
open_ = close - 0.5
volume = np.random.randint(100000, 1000000, 130).astype(float)
benchmark = np.array([...])  # BIST100

features = seven_motor_engine.compute_all(
    ticker="THYAO",
    close=close, open_=open_, high=high, low=low, volume=volume,
    benchmark_close=benchmark,
    fundamentals={"pe_ratio": 8.5, "roe": 0.15, "free_cash_flow": 6800000},
    market_regime="BULL",
)

# features = {
#   "rs_vs_bist_5d": 2.3,        # Motor 1: Relatif güç
#   "trend_slope_20d": 0.5,       # Motor 2: Trend
#   "momentum_acceleration": 1.2,  # Motor 2: İvme
#   "tick_rule": 0.3,             # Motor 3: Mikroyapı
#   "raw_pe_ratio": 8.5,          # Motor 4: Fundamental
#   "kap_sentiment_avg": 0.6,     # Motor 5: KAP
#   "catalyst_importance": 0.7,   # Motor 6: Katalizör
#   "why_falling": 0,             # Motor 7: Neden düşüyor
#   ...
# }
```

---

## 5. Ranking Model

7 motorun çıktısını tek bir sıralama modelinde birleştirir.

**Araştırma bulgusu:**

**AlphaCrafter (arXiv 2026):** LLM-guided factor search + cross-sectional ranking. Factor pool sürekli genişler.

### Örnek: Ranking model

```python
# services/ml/ranking_model.py
from services.ml.ranking_model import ranking_model

features_list = [
    {**features_thyao, "ticker": "THYAO"},
    {**features_asels, "ticker": "ASELS"},
    {**features_garan, "ticker": "GARAN"},
]

predictions = ranking_model.predict(features_list, regime="BULL")

# predictions[0]: ticker="THYAO", rank_score=0.85, direction="LONG"
# predictions[1]: ticker="ASELS", rank_score=0.72, direction="LONG"
# predictions[2]: ticker="GARAN", rank_score=0.45, direction="NEUTRAL"
```

---

## Çıktı

```
600+ hisse
    ↓
250 uygun (likidite + veri kalitesi)
    ↓
100 kaliteli aday (factor engine)
    ↓
30 güçlü aday (7 motor + ranking)
    ↓
10-20 DERİN ANALİZ ADAYI
```

Her aday için:

```
THYAO
Quality:             82
Value:               76
Momentum:            91
Liquidity:           88
Sector Strength:     84
Market Regime Fit:   79
Discovery Score:     84/100
```

---

## Temel prensip

Bu bölüm **hızlı ve geniş tarama** yapar; **nihai hisse önerisini vermez**.
