# ALPHA BIST — Mimari Gap Analysis
**Tarih:** 2026-08-17
**Kapsam:** Feature → Ranking → Risk → Karar pipeline'ının gerçek bağlantı durumu
**Kural:** "Dosya var" ile "sistem kararında kullanılıyor" ayrımı

---

## 1. Şu An Gerçekten Çalışan Yapı

### Pipeline akışı (orchestrator.py):

```
market_data → tradability_mask → feature_calculator → seven_motor_engine
    → cross_sectional → regime_detector → ranking_model → position_sizing → rapor
```

### Gerçekten aktif olan ve veri üreten modüller:

| Modül | Ne üretiyor | Gerçekten çalışıyor mu? |
|-------|-------------|------------------------|
| `calculator.py` | rsi_14, momentum_20d, roc_5d, volume_zscore, atr_pct, volatility_20d, bb_position, macd, sma, ema, obv | ✅ Evet — mask-aware, 30+ feature |
| `seven_motors.py` Motor 2 (MomentumTrend) | roc_Xd, trend_slope, momentum_acceleration, price_vs_sma, near_Xd_high, drawdown | ✅ Evet — ama sadece OHLCV'den |
| `seven_motors.py` Motor 3 (Volume) | volume_zscore_Xd, volume_trend, obv, volume_up_down_ratio | ✅ Evet |
| `seven_motors.py` Motor 7 (Neden Düşüyor?) | falling_is_temporary, fall_severity | ⚠️ Kısmen — market/sector return hep 0 |
| `seven_motors.py` Motor 8 (Mean Reversion) | bb_position, bb_zscore, rsi_Xd, williams_r, cci | ✅ Evet |
| `seven_motors.py` Motor 9 (Seasonality) | seasonality_* | ❌ Hayır — 252 gün veri gerektirir, nadiren çalışır |
| `cross_sectional.py` | rank_return_5d/20d, sector_rel_return, market_breadth | ✅ Evet |
| `regime_detector.py` | BULL/BEAR/SIDEWAYS/HIGH_VOL | ✅ Evet — XU100 bazlı |
| `position_sizing.py` | Kelly + vol targeting | ✅ Evet — ama calibrator._fitted=False |

### Scoring mekanizmaları (iki ayrı yerde):

**A) `engine_v4._compute_score()` (backtest için):**
```python
score = 50.0
if rsi > 60: score += 10 elif rsi < 40: score -= 10
score += momentum_20d * 100   # ← AGRESİF: %1 momentum = +100 skor
score += roc_5d * 2
score += volume_zscore * 5
# 4 feature kullanıyor
```

**B) `ranking_model._rule_based_score()` (günlük pipeline için):**
```python
score = 50.0
score += momentum_20d * 0.15
score += roc_5d * 0.10
score += rs_vs_bist_5d * 0.08    # ← HEP 0 (Motor 1 çalışmıyor)
score += volume_zscore * 0.06
score += sector_rel_return_5d * 0.08
score -= atr_pct * 0.03
score -= drawdown_20d * 0.02
score += fcf_yield_pct * 0.05    # ← HEP 0 (Motor 4 çalışmıyor)
score += balance_sheet_quality * 0.02  # ← HEP 0 (Motor 4 çalışmıyor)
# 9 feature'dan 3'ü hep 0 → %22 ağırlık çöp
```

---

## 2. Çalışıyor Görünen Ama Pipeline'a Bağlı Olmayan Yapılar

### 2.1 Intelligence modüllerinin TAMAMI bağlı değil

| Modül | Dosya var | Orchestrator'da çağrılıyor mu | API'de çağrılıyor mu |
|-------|-----------|-------------------------------|---------------------|
| `signal_fusion.py` | ✅ | ❌ | server.py'de var |
| `trade_planner.py` | ✅ | ❌ | Bağımsız modül |
| `forecasting.py` | ✅ | ❌ | Bağımsız modül |
| `probability.py` | ✅ | ❌ | Bağımsız modül |
| `monte_carlo.py` | ✅ | ❌ | Bağımsız modül |
| `spec_engine.py` | ✅ | ❌ | intelligence/main.py |
| `evidence_engine.py` | ✅ | ❌ | Bağımsız modül |
| `factor_engine.py` | ✅ | ❌ | Bağımsız modül |
| `knowledge_graph.py` | ✅ | ❌ | Bağımsız modül |
| `impact_engine.py` | ✅ | ❌ | intelligence/main.py |
| `kap_extractor.py` | ✅ | ❌ | Bağımsız modül |
| `analysis_engines.py` | ✅ | ❌ | Bağımsız modül |
| `macro_sensitivity.py` | ✅ | ❌ | Bağımsız modül |
| `research_memory.py` | ✅ | ❌ | Bağımsız modül |
| `scenario.py` | ✅ | ❌ | Bağımsız modül |
| `valuation/engine.py` | ✅ | ❌ | Bağımsız modül |
| `world_state.py` | ✅ | ❌ | intelligence/main.py |

**Sonuç:** 17 intelligence modülü var, 0'ı orchestrator pipeline'ına bağlı.

### 2.2 Feature motorlarının veri beslemesi kesik

`seven_motor_engine.compute_all()` çağrısı:
```python
motor_features = seven_motor_engine.compute_all(ticker, df, mask)
```

Fonksiyon imzası 17 parametre alıyor, orchestrator sadece 3'ünü gönderiyor:

| Parametre | Gönderiliyor mu? | Etki |
|-----------|-----------------|------|
| ticker | ✅ | — |
| df | ✅ | — |
| mask | ✅ | — |
| benchmark_close | ❌ None | Motor 1 (RS) → boş dönüyor |
| sector_close | ❌ None | Motor 1 → sektör karşılaştırması yok |
| peer_closes | ❌ None | Motor 1 → peer karşılaştırması yok |
| fundamentals | ❌ None | Motor 4 (Fundamental) → boş dönüyor |
| sector_medians | ❌ None | Motor 4 → normalize yok |
| kap_events | ❌ None | Motor 5 (KAP+Haber) → boş dönüyor |
| news_events | ❌ None | Motor 5 → haber analizi yok |
| upcoming_events | ❌ None | Motor 6 (Katalizör) → boş dönüyor |
| llm_analysis | ❌ None | Motor 5 → LLM entegrasyonu yok |
| market_return_5d | ❌ 0 | Motor 7 → market selloff tespiti yok |
| market_return_20d | ❌ 0 | Motor 7 → market selloff tespiti yok |
| sector_return_5d | ❌ 0 | Motor 7 → sector selloff tespiti yok |
| sector_return_20d | ❌ 0 | Motor 7 → sector selloff tespiti yok |
| market_regime | ❌ "UNKNOWN" | Motor 7 → rejim bilgisi yok |

**Sonuç:** 9 motordan 5'i (Motor 1, 4, 5, 6, 9) hiç veri alamıyor → feature üretmiyor.

### 2.3 Ranking modeli eğitilmemiş

```python
class RankingModel:
    def __init__(self):
        self._lgbm_model = None
        self._is_trained = False  # ← HİÇ EĞİTİLMEMİŞ
```

`rank()` metodunda:
- `_is_trained = False` → LightGBM skoru hep 0
- Ensemble ağırlığı: `lgbm: 0.7, rule_based: 0.3`
- Ama lgbm_norm hep 0 → ensemble = `0.7 * 0 + 0.3 * rule_norm`
- **Sonuç:** Ranking tamamen rule-based'e mahkum

### 2.4 Regime bilgisi ranking'i etkilemiyor

```python
# orchestrator.py
regime_str = self._current_regime.regime  # "BULL", "BEAR", vb.

# ranking_model.py
ranking_result = ranking_model.rank(features_map=all_features, regime=regime_str)
```

`rank()` içinde:
```python
# Rejim ağırlıkları sadece LightGBM input'una uygulanıyor
X_weighted = self._apply_regime_weights(X_arr, regime)

# Ama LightGBM eğitilmediği için bu ağırlıklar HİÇBİR ŞEYE etki etmiyor
predictions = self._lgbm_model.predict(X_weighted)  # ← model yok, bu satır atlanıyor
```

Rule-based skorda rejim ağırlığı var mı? **Hayır.** `_rule_based_score()` rejim parametresi alıyor ama sadece `momentum_weight`'i değiştiriyor — ki o da çok küçük bir etki.

### 2.5 Calibrasyon eğitilmemiş

```python
# position_sizing.py
has_history = calibrator is not None and calibrator._fitted
# _fitted = False → cold-start policy aktif
# Kelly devre dışı → score-based weight kullanılıyor
```

### 2.6 İki ayrı regime sistemi

| Sistem | Konum | Kullanım |
|--------|-------|----------|
| `regime_detector.py` | services/core/ | Orchestrator tarafından çağrılıyor |
| `regime.py` | services/intelligence/ | Hiçbir yerde çağrılmıyor |

İkisi farklı rejim tipleri üretiyor:
- `regime_detector`: BULL, BEAR, SIDEWAYS, HIGH_VOL, LOW_VOL
- `regime.py`: BULL, BEAR, SIDEWAYS, HIGH-VOLATILITY, LOW-VOLATILITY, RISK-ON, RISK-OFF, CRISIS, RECOVERY, MOMENTUM-EXPANSION, MOMENTUM-CONTRACTION

---

## 3. Kritik Mimari Eksikler

### 3.1 Feature-Label Contract Yok

Ranking modeli 65 feature bekliyor ama:
- 37'si hep 0 (motor bağlantıları kesik)
- Feature isimleri tutarsız (calculator: `rsi_14`, motors: `rsi_14d`)
- Label üretimi (generator.py) ile feature üretimi arasında contract yok

### 3.2 Prediction Layer Yok

Mevcut sistem sadece "skor" üretiyor. Şu katmanlar hiç yok:

| Katman | Mevcut durum | Gerekli |
|--------|-------------|---------|
| Yön tahmini (UP/DOWN) | momentum bazlı heuristic | Classification model |
| Beklenen getiri | score * 0.01 | Regresyon modeli + CI |
| Zaman ufku | sabit "1-5D" | Katalizör + volatilite bazlı |
| Confidence | rank percentile | Calibration'dan |
| Risk/Reward | ATR bazlı | Distribution percentiles |
| Destek/Direnç | yok | Volume profile + clustering |
| Kalite sınıfı | yok | A+/A/B/C/D composite |

### 3.3 Signal-to-Decision Pipeline Kopuk

```
Mevcut:    features → ranking → top_20 → rapor
Hedef:     features → ranking → direction → expected_return → confidence
           → risk/reward → support/resistance → time_horizon
           → quality_grade → trade_plan → rapor
```

Aradaki bağlantılar:
- `signal_fusion.py`: Var ama bağlı değil
- `trade_planner.py`: Var ama bağlı değil
- `probability.py`: Var ama bağlı değil
- `forecasting.py`: Var ama bağlı değil

### 3.4 Multi-Horizon Ranking Yok

Mevcut: Tek skor, tek zaman ufku.
Hedef: 1d, 5d, 20d, 60d için ayrı sıralama.

`forecasting.py`'de `HORIZONS = [1, 5, 20, 60, 120]` tanımlı ama hiç kullanılmıyor.

### 3.5 Cross-Sectional Standardizasyon Eksik

Motor 2, 3, 7, 8, 9 feature'ları üretiyor ama bunlar cross-sectional olarak normalize edilmiyor. `cross_sectional.py` sadece calculator.py çıktılarını işliyor.

---

## 4. Bir Sonraki Implementasyon Sırası

### Faz 1: Mevcut Motorları Besle (1-2 hafta)

**Hedef:** 9 motorun tamamını çalışır hale getir, feature isim çakışmalarını çöz.

1. Orchestrator'da `seven_motor_engine.compute_all()` çağrısına benchmark_close, market_return parametrelerini ekle
2. Feature isim standardizasyonu: `rsi_14` vs `rsi_14d` → tek isim
3. Cross-sectional engine'i tüm motor çıktılarını kapsayacak şekilde genişlet
4. Regime bilgisini ranking'e gerçekten etki ettir (rejim bazlı ağırlıkları rule-based score'a uygula)

### Faz 2: Prediction Layer (2-3 hafta)

**Hedef:** Skor yerine çok boyutlu tahmin.

5. Direction model: binary classification (UP/DOWN) eğitimi
6. Return model: LightGBM regresyon (5d, 20d forward return)
7. Calibration: Platt scaling → score → probability
8. Forecasting engine'i orchestrator'a bağla

### Faz 3: Decision Layer (1-2 hafta)

**Hedef:** Tahmin → Karar dönüşümü.

9. Signal fusion'ı orchestrator'a bağla
10. Trade planner'ı orchestrator'a bağla
11. Quality grade sistemi (A+/A/B/C/D)
12. Multi-horizon ranking (1d, 5d, 20d ayrı)

### Faz 4: Intelligence Layer (sürekli)

13. KAP/haber veri akışını başlat
14. Fundamental veri akışını başlat
15. Monte Carlo senaryo simülasyonu
16. Learning loop → outcome tracking → retraining

---

## ÖZET TABLO

| Bileşen | Dosya var | Pipeline'da | Veri akıyor | Sonuç üretiyor |
|---------|-----------|-------------|-------------|----------------|
| calculator.py | ✅ | ✅ | ✅ | ✅ |
| Motor 2 (Momentum) | ✅ | ✅ | ✅ | ✅ |
| Motor 3 (Volume) | ✅ | ✅ | ✅ | ✅ |
| Motor 7 (Neden Düşüyor) | ✅ | ✅ | ⚠️ Kısmen | ⚠️ |
| Motor 8 (Mean Reversion) | ✅ | ✅ | ✅ | ✅ |
| Motor 1 (RS) | ✅ | ✅ | ❌ | ❌ |
| Motor 4 (Fundamental) | ✅ | ✅ | ❌ | ❌ |
| Motor 5 (KAP/Haber) | ✅ | ✅ | ❌ | ❌ |
| Motor 6 (Katalizör) | ✅ | ✅ | ❌ | ❌ |
| Motor 9 (Seasonality) | ✅ | ✅ | ❌ | ❌ |
| cross_sectional.py | ✅ | ✅ | ✅ | ✅ |
| regime_detector.py | ✅ | ✅ | ✅ | ✅ |
| regime.py (intelligence) | ✅ | ❌ | ❌ | ❌ |
| ranking_model.py (LightGBM) | ✅ | ✅ | ❌ Eğitilmedi | ❌ |
| ranking_model.py (rule-based) | ✅ | ✅ | ✅ | ✅ |
| position_sizing.py | ✅ | ✅ | ✅ | ⚠️ Kelly devre dışı |
| calibrator | ✅ | ✅ | ❌ Eğitilmedi | ❌ |
| signal_fusion.py | ✅ | ❌ | ❌ | ❌ |
| trade_planner.py | ✅ | ❌ | ❌ | ❌ |
| forecasting.py | ✅ | ❌ | ❌ | ❌ |
| probability.py | ✅ | ❌ | ❌ | ❌ |
| monte_carlo.py | ✅ | ❌ | ❌ | ❌ |
| spec_engine.py | ✅ | ❌ | ❌ | ❌ |
| valuation/engine.py | ✅ | ❌ | ❌ | ❌ |
