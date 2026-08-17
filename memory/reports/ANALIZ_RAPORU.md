# ALPHA BIST — Mevcut Durum Analizi
**Tarih:** 2026-08-17
**Kapsam:** Feature Engine, Ranking, Intelligence/Regime, Risk, Backtest, Scanner
**Not:** Kod değişikliği yapılmadı. Sadece gözlem.

---

## 1. MEVCUT DURUM — Modül Bazlı Analiz

### 1.1 Feature Engine ✅ GÜÇLÜ (en olgun modül)

**Mevcut durum:**
- `calculator.py`: Mask-aware teknik feature'lar (SMA, EMA, RSI, MACD, Bollinger, ATR, ADX, OBV, Volume Profile) — **çalışıyor**
- `seven_motors.py`: 9 motor (RS, Momentum+Trend, Volume+Mikroyapı, Fundamental, KAP+Haber, Katalizör, Neden Düşüyor?, Mean Reversion, Seasonality) — **çalışıyor**
- `cross_sectional.py`: Cross-sectional rank, sector relative, market breadth — **çalışıyor**
- `fundamental.py`, `macro.py`, `sentiment.py`, `extended_indicators.py`: Ek feature modülleri — **var ama entegrasyon durumu belirsiz**

**Güçlü yönler:**
- Mask-first design prensibi doğru uygulanmış
- 100+ feature hesaplanıyor
- 9 motor bağımsız çalışıyor, birbirinin sonucunu etkilemiyor
- NaN/Inf temizliği yapılıyor

**Zayıf yönler:**
- `seven_motors.py`'de Motor 1 (RS) ve Motor 4 (Fundamental) orchestrator'dan çağrılmıyor → `compute_all()`'da `benchmark_close`, `fundamentals`, `kap_events`, `news_events`, `upcoming_events` parametreleri hep `None` geliyor
- `calculator.py` ve `seven_motors.py` arasında feature isim çakışmaları var (örn: `rsi_14` vs `rsi_14d`, `momentum_20d` vs `roc_20d`)
- Seasonality motoru 252 gün veri istiyor, BIST verisiyle nadiren çalışır
- Fundamental veri akışı yok — Motor 4 çoğu zaman boş dönüyor

### 1.2 Ranking Model ⚠️ YÜZEYSEL

**Mevcut durum:**
- `ranking_model.py`: LambdaRank + Adjusted-MSE + Rejim-Aware + Ensemble tanımı var
- `_is_trained = False` → **LightGBM modeli eğitilmemiş**
- Ranklama tamamen `_rule_based_score()`'a dayanıyor
- Feature vektörü 60+ feature bekliyor ama çoğu zaman eksik geliyor

**Güçlü yönler:**
- Mimari tasarım doğru: LambdaRank + rule-based ensemble
- Rejim bazlı feature ağırlıkları tanımlı
- SHAP importance entegrasyonu planlanmış

**Zayıf yönler:**
- **Model hiç eğitilmemiş** — `_is_trained = False`
- `_prepare_training_data()` fonksiyonu `groups` parametresini boş döndürüyor → LambdaRank group bilgisi yok
- Confidence hesaplama: rank percentile'dan keyfi üretiliyor (`0.5 + percentile * 0.5`)
- Score semantığı tutarsız: `_rule_based_score()` yüksek = iyi, ama LambdaRank label'ı negatif getiri (düşük = iyi)
- `_feature_vector()` eksik feature'ları 0 ile dolduruyor → model boş feature'larla besleniyor
- Ensemble ağırlıkları sabit (0.7/0.3), kalibrasyon yok

### 1.3 Intelligence / Regime ⚠️ İKİ AYRI SİSTEM, BİRBİRİNE BAĞLANMAMIŞ

**Mevcut durum:**
- `regime_detector.py` (services/core/): Benchmark (XU100) bazlı, 5 faktör (trend, volatilite, momentum, breadth, korelasyon) — **çalışıyor**
- `regime.py` (services/intelligence/): Feature-based, 11 rejim tipi, 8 skor fonksiyonu — **çalışıyor**
- `signal_fusion.py`: 7 bileşen sinyal birleştirme — **çalışıyor ama orchestrator tarafından çağrılmıyor**
- `forecasting.py`: Heuristic tahmin (momentum + RSI bazlı) — **çok basit**
- `probability_engine.py`: Return distribution, hit rate, calibration — **çalışıyor ama entegre değil**

**Güçlü yönler:**
- İki farklı regime detection yaklaşımı var (benchmark-based vs feature-based)
- Signal fusion mimarisi doğru: çelişki tespiti, self-check, invalidation
- Probability engine calibration ve Brier score hesaplıyor

**Zayıf yönler:**
- **İki regime sistemi birbiriyle konuşmuyor** — orchestrator sadece `regime_detector.py`'yi kullanıyor, `regime.py` hiç çağrılmıyor
- Regime tespiti sadece XU100'e bakıyor, sektör/hisse bazlı regime yok
- Signal fusion orchestrator'a entegre edilmemiş — hiçbir pipeline'da kullanılmıyor
- Forecasting tamamen heuristic, ML modeli yok
- Monte Carlo motoru (`monte_carlo.py`) var ama entegrasyon durumu belirsiz
- Regime transition probability sabit matris, veri ile güncellenmemiş

### 1.4 Risk Engine ⚠️ İKİ AYRI YAPI

**Mevcut durum:**
- `risk/main.py`: Async event-driven risk engine (DB bağımlı, PostgreSQL) — **production-ready görünüyor ama DB yoksa çalışmaz**
- `risk/position_sizing.py`: Calibrated Kelly + Vol Targeting — **çalışıyor**
- `risk/calibration.py`: Score → win_prob kalibrasyonu — **var ama `_fitted` False**
- `risk/covariance.py`: Kovaryans tahmini — **var ama entegrasyon belirsiz**
- `risk/enhanced_risk.py`: Ek risk metrikleri — **var**

**Güçlü yönler:**
- Position sizing doğru tasarlanmış: Fractional Kelly + Vol Targeting + Regime adjustment
- Fail-closed prensibi risk/main.py'de uygulanmış
- ATR bazlı stop-loss hesaplama decision_engine'da var

**Zayıf yönler:**
- **İki risk sistemi var**: `risk/main.py` (async, DB bağımlı) ve `position_sizing.py` (sync, DB yok)
- `calibrator._fitted = False` → Kelly devre dışı, cold-start policy aktif
- Kovaryans/portföy optimizasyonu yok (sadece tek hisse bazlı sizing)
- Drawdown hesabı basit (initial capital'dan), peak-to-trough yok
- `risk/main.py`'deki drawdown hesabında hata var: `initial - current` kullanıyor, peak-to-trough değil

### 1.5 Backtest ⚠️ YÜZEYSEL

**Mevcut durum:**
- `backtest/engine.py`: Basit sinyal simülasyonu — **çalışıyor ama yüzeysel**
- `backtest/walk_forward.py`: Walk-forward fold'lar — **çalışıyor**
- `backtest/enhanced_walk_forward.py`: Enhanced walk-forward — **var ama fold içinde training yok**
- `main.py`'deki `run_backtest()`: Ana backtest akışı — **çalışıyor**

**Güçlü yönler:**
- Walk-forward yapısı doğru: train/test/purge/embargo
- Point-in-time universe kontrolü var
- Look-ahead bias ve data leakage kontrolleri var
- Calibration: fold'lar arası trade history transferi var

**Zayıf yönler:**
- **BacktestEngine çok basit**: holding_days=1 sabit, mark-to-market yok, intraday simulation yok
- `main.py`'deki backtest: sadece entry ve exit fiyatı kullanıyor, ara fiyat hareketi yok
- CAGR = total_return / years basitleştirmesi
- Drawdown duration = 0
- Exposure = 0 (pozisyon yönetimi yok)
- Walk-forward fold'lar içinde model yeniden eğitilmiyor (sadece prediction transferi)
- Transaction cost sabit (%0.1), slippage sabit (%0.05)
- Portfolio-level backtest yok (sadece tek hisse bazlı)

### 1.6 Scanner ✅ MİMARİ DOĞRU AMA EKSİK

**Mevcut durum:**
- `alpha_scanner.py`: 4 tier'lı tarama (State → Quant → Ranking → Signal) — **çalışıyor**
- `alpha_engine.py`: Ek motor — **var**
- `opportunity_engine.py`: Fırsat motoru — **var**
- `event_scanner.py`, `live_scanner.py`, `tiered_scanner.py`: Ek scanner'lar — **var**

**Güçlü yönler:**
- Scanner mimarisi doğru: tier'lı filtreleme
- Signal türleri iyi tanımlanmış (MOMENTUM, BREAKOUT, ACCUMULATION, EVENT, SPEC, REVERSAL)
- SPEC sinyali: diğer modellerin açıklayamadığı anomalileri yakalıyor

**Zayıf yönler:**
- Scanner sonuçları orchestrator'a bağlanmıyor — farklı pipeline'larda farklı sonuçlar üretilebilir
- ML skorları hep 50.0 varsayılan değerle geliyor (`ml_scores` parametresi hep `None`)
- Event skorları hep 50.0
- Regime fit hesaplama basit: sadece momentum ve volatilite bakıyor

---

## 2. KRİTİK EKSİKLER

| # | Eksik | Etki | Öncelik |
|---|-------|------|---------|
| 1 | **Ranking modeli eğitilmemiş** | Tüm pipeline rule-based'e mahkum | 🔴 Kritik |
| 2 | **İki regime sistemi entegre değil** | Kararlar tutarsız regime bilgisiyle alınıyor | 🔴 Kritik |
| 3 | **Signal fusion entegre değil** | Çoklu sinyal birleştirme kullanılmıyor | 🔴 Kritik |
| 4 | **Fundamental veri akışı yok** | Motor 4 (Fundamental) boş dönüyor | 🟡 Yüksek |
| 5 | **KAP/Haber veri akışı yok** | Motor 5 (KAP+Haber) boş dönüyor | 🟡 Yüksek |
| 6 | **Backtest engine yüzeysel** | Metrikler güvenilir değil | 🟡 Yüksek |
| 7 | **Calibrasyon eğitilmemiş** | Kelly devre dışı, cold-start policy | 🟡 Yüksek |
| 8 | **Kovaryans/portföy optimizasyonu yok** | Sadece tek hisse bazlı sizing | 🟡 Yüksek |
| 9 | **Label → Prediction contract yok** | Feature engineering ile label üretimi arasındaki contract belirsiz | 🟡 Yüksek |
| 10 | **Honest baseline yok** | Random/benchmark karşılaştırması yapılmamış | 🟠 Orta |

---

## 3. MEVCUT MİMARİDE YENİDEN KULLANILABİLİR PARÇALAR

| Modül | Yeniden Kullanılabilirlik | Not |
|-------|--------------------------|-----|
| `calculator.py` | ✅ Yüksek | Mask-aware teknik feature'lar sağlam |
| `seven_motors.py` | ✅ Yüksek | 9 motor tasarımı doğru, entegrasyon eksik |
| `cross_sectional.py` | ✅ Yüksek | Cross-sectional rank feature'lar doğru |
| `regime_detector.py` | ⚠️ Orta | Benchmark-based, feature-based ile birleştirilmeli |
| `regime.py` (intelligence) | ✅ Yüksek | 11 rejim tipi, skor fonksiyonları iyi |
| `signal_fusion.py` | ✅ Yüksek | Mimari doğru, entegrasyon eksik |
| `position_sizing.py` | ✅ Yüksek | Kelly + Vol Targeting doğru |
| `probability_engine.py` | ✅ Yüksek | Calibration + Brier score doğru |
| `trade_planner.py` | ✅ Yüksek | Trade plan yapısı doğru |
| `label_generator.py` | ✅ Yüksek | Label'lar doğru üretiliyor |
| `backtest/engine.py` | ⚠️ Düşük | Çok basit, yeniden yazılmalı |
| `ranking_model.py` | ⚠️ Orta | Mimari doğru, model eğitilmemiş |
| `decision_engine.py` | ⚠️ Orta | Composite skor mantığı basit |
| `alpha_scanner.py` | ✅ Yüksek | Tier'lı tarama doğru |

---

## 4. YENİ PREDICTION/LABEL YAPILARINA İHTİYAÇ

Hedeflenen çok katmanlı karar motoru için mevcut olmayan yapılar:

### 4.1 Yön Tahmini (Direction Prediction)
- **Mevcut:** Sadece momentum bazlı LONG/SHORT kararı
- **Gerekli:** P(direction=UP | features, regime) → probability distribution
- **Implementasyon:** Classification model (binary: UP/DOWN) veya quantile regression

### 4.2 Beklenen Getiri (Expected Return)
- **Mevcut:** `_calculate_expected_return()` = (momentum + ROC) / 2 → çok basit
- **Gerekli:** E[return | features, regime, horizon] → point estimate + confidence interval
- **Implementasyon:** Regresyon modeli (LightGBM/XGBoost) + conformal prediction

### 4.3 Zaman Ufku (Time Horizon)
- **Mevcut:** Sabit "1-5D" veya "1-4W"
- **Gerekli:** Hisse bazlı optimal holding period
- **Implementasyon:** Volatility-adjusted horizon, katalizör zamanlaması

### 4.4 Confidence (Güven)
- **Mevcut:** Rank percentile'dan keyfi üretim
- **Gerekli:** Model calibration'dan gelen gerçek güven
- **Implementasyon:** Platt scaling, isotonic regression

### 4.5 Risk/Reward
- **Mevcut:** ATR bazlı stop/target (decision_engine)
- **Gerekli:** Asimetrik risk/getiri profili (upside/downside ratio)
- **Implementasyon:** Return distribution percentiles (P10/P25/P75/P90)

### 4.6 Destek/Direnç
- **Mevcut:** Yok (sadece Bollinger bandı referansı)
- **Gerekli:** Yapısal destek/direnç seviyeleri
- **Implementasyon:** Volume profile, pivot points, historical S/R clustering

### 4.7 Yatırım Kalitesi Sınıfları (A+/A/B)
- **Mevcut:** Yok
- **Gerekli:** Çok boyutlu skor → tek sınıf
- **Implementasyon:** Composite scoring: direction conviction × expected return × risk/reward × regime fit → A+/A/B/C/D

---

## 5. ÖNERİLEN GELİŞTİRME SIRASI

### Faz 1: Temel Altyapı (2-3 hafta)
1. **Feature pipeline entegrasyonu** — 9 motorun tamamını orchestrator'a bağla (benchmark, fundamental, KAP, haber veri akışlarını düzelt)
2. **Regime sistemi birleştirme** — İki regime dedektörünü tek bir unified regime engine'de birleştir
3. **Label contract** — Feature engineering ile label üretimi arasındaki contract'ı tanımla ve doğrula
4. **Honest baseline** — Random/benchmark (XU100 buy-and-hold) karşılaştırması

### Faz 2: Prediction Layer (2-3 hafta)
5. **Direction model** — Binary classification (UP/DOWN) eğitimi
6. **Return model** — Regresyon modeli (5d, 20d forward return)
7. **Calibration** — Platt scaling ile score → probability dönüşümü
8. **Ensemble** — LightGBM + rule-based ağırlık optimizasyonu

### Faz 3: Decision Layer (2 hafta)
9. **Signal fusion entegrasyonu** — Orchestrator'a bağla
10. **Çok katmanlı skor** — Direction + Return + Confidence + Risk/Reward → A+/A/B/C/D
11. **Destek/direnç** — Volume profile + pivot points + historical clustering
12. **Trade plan otomasyonu** — Trade planner'ı orchestrator'a bağla

### Faz 4: Validation (2 hafta)
13. **Walk-forward improvement** — Fold içinde model yeniden eğitimi
14. **Backtest engine upgrade** — Mark-to-market, intraday, portfolio-level
15. **Calibration validation** — Brier score, calibration curve
16. **Paper trading** — Champion/challenger lifecycle

### Faz 5: Intelligence Layer (sürekli)
17. **KAP/haber entegrasyonu** — Gerçek veri akışı
18. **Monte Carlo** — Senaryo simülasyonu
19. **Learning loop** — Outcome tracking → retraining
20. **Knowledge graph** — Entity relationships

---

## 6. İLK İMPLEMENTASYON AŞAMASI KAPSAMI (Faz 1)

**Hedef:** Feature pipeline'ı düzgün çalışır hale getir + honest baseline

**Sprint 1 (1 hafta):**
- [ ] `seven_motors.py`'deki Motor 1, 4, 5, 6, 9 parametrelerini orchestrator'dan besle
- [ ] Feature isim çakışmalarını çöz (`rsi_14` vs `rsi_14d` standardizasyonu)
- [ ] Orchestrator'da regime detection'ı unified hale getir

**Sprint 2 (1 hafta):**
- [ ] Label generator'ı orchestrator pipeline'ına entegre et
- [ ] Feature → Label contract testi yaz
- [ ] Honest baseline: random selection vs XU100 buy-and-hold karşılaştırması

**Sprint 3 (1 hafta):**
- [ ] Signal fusion'ı orchestrator'a bağla
- [ ] Basit direction model (logistic regression) eğitimi
- [ ] Walk-forward validation raporu

**Çıktı:** Çalışan bir pipeline: data → features → regime → ranking → risk → backtest → learning
