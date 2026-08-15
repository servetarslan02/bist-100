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

## 1. Likidite Filtresi

Düşük likiditeli hisseler elenir.

### Örnek: Likidite skoru

```python
# services/ingestion/universe_enhancements.py
from services.ingestion.universe_enhancements import universe_enhancements

score = universe_enhancements.compute_liquidity_score(
    avg_volume=1000000, avg_spread_pct=0.05, market_cap=50_000_000_000)
# score = 90/100 (yüksek likidite)
```

---

## 2. Factor Engine

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

## 5. Anomali Tespiti

Olağandışı fiyat/hacim hareketlerini tespit eder ve şüpheli hisseleri işaretler.

### Örnek: Anomali kontrolü

```python
# services/core/streaming_anomaly.py
from services.core.streaming_anomaly import streaming_anomaly_detector

result = streaming_anomaly_detector.check_all(
    ticker="THYAO", price=350.0, previous_price=305.0,
    volume=5000000, bid=349.5, ask=350.5, volatility=0.25)
# price anomaly: CRITICAL (ani sıçrama)
# volume anomaly: HIGH (anormal hacim)
# spread anomaly: LOW (normal spread)
```

---

## Çıktı

```
600+ hisse → 250 uygun → 100 kaliteli → 30 güçlü → 10-20 DERİN ANALİZ ADAYI
```

---

## Temel prensip

Bu bölüm **hızlı ve geniş tarama** yapar; **nihai hisse önerisini vermez**.

---

## Factor Investing Entegrasyonu

**Kaynak:** Bölüm 30 — BIST Alpha Anomalileri

Bu bölümün hisse keşfi, Bölüm 30'daki faktör skorlarını kullanır:

| Faktör | Bölüm 30 Motoru | Bölüm 4 Kullanımı |
|--------|----------------|-------------------|
| Piotroski F-Score | `factors/piotroski.py` | Şirket kalitesi filtresi |
| Beneish M-Score | `factors/beneish.py` | Dolandırıcılık filtresi |
| Altman Z-Score | `factors/altman.py` | İflas riski filtresi |
| Fama-French | `factors/fama_french.py` | Çok faktörlü sıralama |
| BIST Anomalileri | `factors/bist_anomalies.py` | Temettü, likidite, kur |

### Örnek: Faktör → Sıralama zinciri

```python
from services.factors.piotroski import calculate_f_score
from services.factors.beneish import calculate_m_score
from services.factors.altman import calculate_z_score
from services.factors.fama_french import calculate_factor_scores

f_score = calculate_f_score(financials)  # 0-9
m_score = calculate_m_score(financials)  # < -1.78 güvenli
z_score = calculate_z_score(financials)  # > 2.99 güvenli

# Filtreleme
if f_score >= 7 and m_score < -1.78 and z_score > 2.99:
    factor_scores = calculate_factor_scores(stock, universe)
    # Sıralamaya dahil et
```
