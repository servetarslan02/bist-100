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
- Factor Engine (Value, Momentum, Quality, Growth, Size, Low Volatility)
- Relative Strength
- Sector Strength
- Anomaly Detection
- Market Regime bilgisi

---

## Çalışma mantığı

```
Tüm BIST → Veri/kalite filtresi → Likidite filtresi →
Riskli hisseleri ele → Fundamental ön filtre → Technical ön filtre →
Momentum/RS → Value/Quality/Growth → Sektör+Regime uyumu →
Skorlama → ADAY HİSSE HAVUZU
```

---

## 1. Factor Engine

**Araştırma bulguları:**

**J.P. Morgan (2026):** Momentum ve Quality en tutarlı faktörler. Value ve Low Volatility döngüsel.

**AlphaCrafter (arXiv 2026):** "Continuous coupling of factor discovery, regime-adaptive selection, and risk management."

**Fama-French:** 5 faktör (Value, Size, Profitability, Investment, Momentum) getiri varyansının çoğunu açıklar.

### Örnek: Factor skorları

```python
# services/intelligence/factor_engine.py
from services.intelligence.factor_engine import factor_engine

score = factor_engine.compute_factor_scores(
    ticker="THYAO",
    fundamentals={"pe_ratio": 8.5, "roe": 0.15, "profit_margin": 0.10},
    technicals={"roc_5d": 5.0, "momentum_20d": 12.0, "realized_vol_20d": 18},
)
# value_score: 75, momentum_score: 82, quality_score: 70, composite: 74.5
```

---

## 2. 7 Motor

Her hisse 7 ayrı perspektiften analiz edilir.

### Örnek: 7 Motor çalıştırma

```python
# services/features/seven_motors.py
from services.features.seven_motors import seven_motor_engine

features = seven_motor_engine.compute_all(
    ticker="THYAO", close=close, open_=open_, high=high, low=low,
    volume=volume, benchmark_close=benchmark,
    fundamentals={"pe_ratio": 8.5, "roe": 0.15},
    market_regime="BULL",
)
# 47+ feature: rs_vs_bist, trend_slope, tick_rule, raw_pe, kap_sentiment, ...
```

---

## 3. Ranking Model

### Örnek: Ranking

```python
# services/ml/ranking_model.py
from services.ml.ranking_model import ranking_model

predictions = ranking_model.predict(features_list, regime="BULL")
# predictions[0]: ticker="THYAO", rank_score=0.85, direction="LONG"
```

---

## 4. Adaptif Eşik

### Örnek: Adaptif eşik

```python
import numpy as np
all_scores = [72, 68, 65, 60, 55, 50, 48, 45, 42, 40]
median_score = np.median(all_scores)  # 52.5
std_score = np.std(all_scores)        # 10.2
adaptive_threshold = max(40, median_score + 0.5 * std_score)  # 57.6
```

---

## Çıktı

```
600+ hisse → 250 uygun → 100 kaliteli → 30 güçlü → 10-20 DERİN ANALİZ ADAYI
```

---

## Temel prensip

Bu bölüm **hızlı ve geniş tarama** yapar; **nihai hisse önerisini vermez**.
