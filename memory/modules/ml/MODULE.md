# ML — Makine Öğrenimi Servisi

## Giriş

ML servisi, ALPHA BIST sisteminin **tahmin motoru**dur. Ham piyasa verilerini alır, sıralanmış hisse fırsatlarına dönüştürür. Modülün temel sorumluluğu: **"En iyi %10'da mı?" sorusunu cevaplamak, fiyat tahmini yapmak değil.**

Sistem, birden fazla model mimarisini (LightGBM, CatBoost, XGBoost, LSTM, Transformer) destekler, bunları ensemble ile birleştirir ve champion-challenger mekanizmasıyla sürekli olarak en iyi modeli production'da tutar.

## Katman Haritası

```
┌─────────────────────────────────────────────────────────────────┐
│                    ML SERVİSİ KATMAN HARİTASI                    │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │  KATMAN 1: SIRALAMA (Ranking)                            │   │
│  │  ranker.py          — Learning-to-Rank v1 (LGBMRanker)   │   │
│  │  ranking_model.py   — LambdaRank + Adjusted-MSE + Rejim  │   │
│  └────────────────────────┬─────────────────────────────────┘   │
│                           │                                      │
│  ┌────────────────────────▼─────────────────────────────────┐   │
│  │  KATMAN 2: EĞİTİM (Training)                             │   │
│  │  lightgbm_trainer.py — Date-space purge, multi-horizon   │   │
│  │  catboost_model.py   — Custom loss, SHAP, multi-horizon  │   │
│  │  xgboost_model.py    — XGBoost entegrasyonu              │   │
│  │  lstm_model.py       — PyTorch LSTM + Attention           │   │
│  │  transformer_model.py — Transformer tabanlı model         │   │
│  │  train_all_models.py — Master training pipeline           │   │
│  └────────────────────────┬─────────────────────────────────┘   │
│                           │                                      │
│  ┌────────────────────────▼─────────────────────────────────┐   │
│  │  KATMAN 3: ENSEMBLE                                       │   │
│  │  ensemble.py           — Ağırlıklı ortalama + stacking    │   │
│  │  stacking_ensemble.py  — Ridge meta-learner, regime-aware │   │
│  │  adjusted_loss.py      — Yanlış yön 11x ceza             │   │
│  └────────────────────────┬─────────────────────────────────┘   │
│                           │                                      │
│  ┌────────────────────────▼─────────────────────────────────┐   │
│  │  KATMAN 4: YÖNETİM & GÖZETLEME                           │   │
│  │  champion_challenger.py — A/B test, auto-promote/reject   │   │
│  │  model_registry.py      — Versiyon takibi, lineage        │   │
│  │  model_monitor.py       — Decay tespiti, alerting          │   │
│  │  model_comparator.py    — IC, Sharpe, Precision@K          │   │
│  │  calibration.py         — Brier score, Platt scaling       │   │
│  │  feature_drift.py       — PSI, SHAP trend, drift alerting  │   │
│  │  hyperparameter_tuner.py — Optuna Bayesian optimization    │   │
│  └────────────────────────┬─────────────────────────────────┘   │
│                           │                                      │
│  ┌────────────────────────▼─────────────────────────────────┐   │
│  │  KATMAN 5: DOĞRULAMA & BACKTEST                           │   │
│  │  walk_forward.py        — Purge + embargo, expanding win  │   │
│  │  training_validator.py  — Dataset kalite kontrolü          │   │
│  │  ml_backtest.py         — Transaction cost dahil backtest  │   │
│  └──────────────────────────────────────────────────────────┘   │
│                                                                  │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │  KATMAN 6: ENTEGRASYON                                    │   │
│  │  qlib_integration.py   — Microsoft Qlib entegrasyonu      │   │
│  │  finrl_bist.py         — FinRL reinforcement learning      │   │
│  │  fingpt.py             — FinGPT sentiment analizi          │   │
│  │  hybrid_model.py       — Hibrit model tahmin               │   │
│  │  rl_agent.py           — Reinforcement learning agent      │   │
│  └──────────────────────────────────────────────────────────┘   │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

## Neden Bu Tasarım Seçimi?

| Karar | Neden | Alternatif | Neden Reddedildi |
|-------|-------|-----------|-----------------|
| **LambdaRank (regresyon değil sıralama)** | "En iyi hisseyi bul" sorusu regresyon gerektirmez; sıralama yeterli. +0.44 Sharpe katkısı. | Regresyon tabanlı model | Fiyat tahmini yapmak gereksiz karmaşıklık ve hata kaynağı |
| **Adjusted-MSE Loss (yanlış yön 11x ceza)** | Yanlış yönlü tahminlerin maliyeti çok yüksek; asimetrik loss bunu yakalar. | Standart MSE | Yanlış yön ve doğru yön eşit cezalandırılır |
| **Date-space purge gap** | Sample-space purge, tarih çakışmasına izin verir → look-ahead bias. | Sample-space purge | Data leakage riski |
| **Rejim-aware training** | BULL piyasada momentum, BEAR'da defansif feature'lar daha bilgilendirici. | Tek model tüm rejimlerde | Rejim değişince model bozulur |
| **Stacking ensemble (Ridge meta-learner)** | Nature (2026) metodolojisi; base model predictions'ı meta-feature olarak kullanır. | Basit ağırlıklı ortalama | Model çeşitliliğini kullanmaz |
| **Champion-challenger (statistical significance)** | Yeni model doğrudan production'a alınamaz; A/B test gerektirir. | Doğrudan deploy | Production riski |
| **Walk-forward validation** | Gelecekten bilgi sızıntısını önler; expanding window daha gerçekçi. | Basit train/test split | Zaman bağımlılığını ihmal eder |
| **Cross-sectional normalization (PIT-safe)** | Her tarihte feature'ları o günkü tüm ticker'lara göre normalize eder. | Global normalization | Look-ahead bias |
| **Multi-horizon targets (1d/5d/20d/60d)** | Farklı vadeler farklı sinyal kaliteleri sunar; ensemble'da birleştirilir. | Tek horizon | Bilgi kaybı |
| **Deterministic training (seed=42)** | Reproducibility kritik; aynı veri → aynı model. | Rastgele seed | Debug imkansız |

## Uçtan Uca Veri Akışı

```
Ham Piyasa Verisi (OHLCV, KAP, Haberler)
        │
        ▼
┌─────────────────────┐
│ Feature Engineering │  (services/features/)
│ 148+ feature hesapla│
└─────────┬───────────┘
          │
          ▼
┌─────────────────────┐
│ Cross-Sectional     │  training_validator.py
│ Normalization       │  PIT-safe z-score by date
│ (PIT-safe)          │
└─────────┬───────────┘
          │
          ▼
┌─────────────────────┐
│ Training Pipeline   │  lightgbm_trainer.py / catboost_model.py / ...
│ Date-space purge    │  Scaler sadece TRAIN'den öğrenilir
│ Multi-horizon target│  Horizon-aware purge gap
└─────────┬───────────┘
          │
          ▼
┌─────────────────────┐
│ Validation          │  training_validator.py + walk_forward.py
│ - Dataset quality   │  NaN/inf/outlier tespiti
│ - Walk-forward      │  Purge + embargo
│ - Deflated Sharpe   │  Multiple testing correction
└─────────┬───────────┘
          │
          ▼
┌─────────────────────┐
│ Ensemble            │  stacking_ensemble.py
│ - Base model preds  │  Ridge meta-learner
│ - Regime weights    │  BULL/BEAR/SIDEWAYS/HIGH_VOL
│ - Diversity check   │  Model agreement confidence
└─────────┬───────────┘
          │
          ▼
┌─────────────────────┐
│ Ranking             │  ranking_model.py
│ - LambdaRank        │  Sıralama (regresyon değil)
│ - Regime weights    │  Rejime göre feature ağırlıkları
│ - Rule-based fallback│ Model yoksa kural tabanlı
└─────────┬───────────┘
          │
          ▼
┌─────────────────────┐
│ Champion-Challenger │  champion_challenger.py
│ - Shadow mode       │  Paralel çalıştır, kaydet
│ - A/B test          │  t-test + effect size
│ - Auto-promote      │  Statistical significance
└─────────┬───────────┘
          │
          ▼
┌─────────────────────┐
│ Monitoring          │  model_monitor.py + feature_drift.py
│ - Decay detection   │  Z-score based
│ - Feature drift     │  PSI + SHAP trend
│ - Alerting          │  WARNING / CRITICAL
│ - Auto-retrain      │  Decay eşiği aşılınca
└─────────┬───────────┘
          │
          ▼
    Sıralanmış Fıfırsatlar (Top-K hisse listesi)
```

## Dosya Bazlı Sorumluluk Tablosu

| Dosya | Sorumluluk | Kritiklik |
|-------|-----------|-----------|
| `ranker.py` | Learning-to-Rank v1 — LGBMRanker ile hisse sıralama, rule-based fallback | ⭐⭐⭐⭐⭐ |
| `ranking_model.py` | LambdaRank + Adjusted-MSE + Rejim-aware + Ensemble — 7 motorlu sıralama sistemi | ⭐⭐⭐⭐⭐ |
| `lightgbm_trainer.py` | LightGBM eğitim pipeline — date-space purge, multi-horizon, confidence scoring | ⭐⭐⭐⭐⭐ |
| `catboost_model.py` | CatBoost entegrasyonu — custom loss, SHAP, multi-horizon, kategorik feature handling | ⭐⭐⭐⭐⭐ |
| `ensemble.py` | Ağırlıklı ensemble prediction + confidence (model agreement) | ⭐⭐⭐⭐ |
| `stacking_ensemble.py` | Stacking ensemble — Ridge meta-learner, regime-specific meta-learner, diversity scoring | ⭐⭐⭐⭐⭐ |
| `champion_challenger.py` | A/B test motoru — shadow mode, multi-metric comparison, auto-promote/reject, rollback | ⭐⭐⭐⭐⭐ |
| `calibration.py` | Model confidence kalibrasyonu — Brier score, ECE, Platt scaling, isotonic regression | ⭐⭐⭐⭐⭐ |
| `feature_drift.py` | Feature drift tespiti — SHAP history, PSI, importance trend, severity scoring | ⭐⭐⭐⭐⭐ |
| `model_registry.py` | Model kayıt defteri — version tracking, lineage, metrics, snapshot/restore | ⭐⭐⭐⭐⭐ |
| `hyperparameter_tuner.py` | Optuna Bayesian optimization — IC-based objective, regime-specific tuning, convergence | ⭐⭐⭐⭐ |
| `lstm_model.py` | PyTorch LSTM — multi-layer, bidirectional, attention, multi-horizon, early stopping | ⭐⭐⭐⭐ |
| `model_monitor.py` | Performans monitoring — decay detection, prediction drift, health score, alerting | ⭐⭐⭐⭐⭐ |
| `model_comparator.py` | Model karşılaştırma — IC, Precision@K, Sharpe, Max Drawdown, calibration score | ⭐⭐⭐⭐ |
| `walk_forward.py` | Walk-forward validation — purge, embargo, expanding window | ⭐⭐⭐⭐⭐ |
| `training_validator.py` | Dataset kalite kontrolü — NaN/inf/outlier, leakage tespiti, CS normalization | ⭐⭐⭐⭐⭐ |
| `ml_backtest.py` | ML backtest engine — transaction cost, regime-based performans, equity curve | ⭐⭐⭐⭐ |
| `adjusted_loss.py` | Asimetrik MSE loss — yanlış yön 11x ceza, gradient hesaplama | ⭐⭐⭐⭐ |
| `train_all_models.py` | Master training pipeline — tüm modelleri eğit, serialize et | ⭐⭐⭐⭐ |
| `xgboost_model.py` | XGBoost entegrasyonu | ⭐⭐⭐ |
| `transformer_model.py` | Transformer tabanlı model | ⭐⭐⭐ |
| `hybrid_model.py` | Hibrit model tahmin | ⭐⭐⭐ |
| `rl_agent.py` | Reinforcement learning agent | ⭐⭐⭐ |
| `finrl_bist.py` | FinRL entegrasyonu | ⭐⭐ |
| `fingpt.py` | FinGPT sentiment | ⭐⭐ |
| `qlib_integration.py` | Microsoft Qlib entegrasyonu | ⭐⭐ |
| `cross_sectional/` | Cross-sectional normalization alt modülü | ⭐⭐⭐ |

## Tasarım İlkeleri ve Kırmızı Çizgiler

### İlkeler

1. **Sıralama > Regresyon**: Model fiyat tahmini yapmaz, hisseleri sıralar. "En iyi %10'da mı?" sorusu kritiktir.
2. **Yön doğruluğu her şeyden önemli**: Yanlış yön tahmini 11x cezalandırılır (Adjusted-MSE).
3. **Rejim farkındalığı**: BULL/BEAR/SIDEWAYS/HIGH_VOL rejimlerinde farklı feature ağırlıkları ve model seçimleri.
4. **PIT (Point-in-Time) güvenliği**: Cross-sectional normalization sadece o tarihe kadar bilinen verileri kullanır.
5. **Date-space purge**: Train/test arasında gerçek tarih gününde boşluk bırakılır, sample sayısında değil.
6. **Deterministic**: seed=42, deterministic=True — aynı veri → aynı model.
7. **Confidence kalibrasyonu**: Model %90 confidence veriyorsa, gerçekten %90 olmalı.

### Kırmızı Çizgiler

- ❌ **Scaler/impute tüm veriden öğrenilemez** — sadece TRAIN split'inden.
- ❌ **Train/test tarih çakışması** — data leakage, kalite skorunu 0.5'in altına düşürür.
- ❌ **Walk-forward başarısızsa model production'a alınamaz** — retrain yapma.
- ❌ **Yeni model doğrudan production'a alınamaz** — shadow mode + statistical significance gerekli.
- ❌ **Feature isim uyuşmazlığı** — fallback mekanizması ile tolere edilir ama loglanır.
- ❌ **NaN/inf feature değerleri** — impute edilir ama raporlanır.

## Bilinen Sınırlamalar

1. **Sentetik veri ile eğitim**: `train_all_models.py` hâlâ sentetik veri kullanıyor; gerçek BIST verisiyle eğitim pipeline'ı henüz tam entegre değil.
2. **LSTM/Transformer sınırlı kullanım**: Production'da ağırlıklı LightGBM/CatBoost kullanılıyor; deep learning modelleri deneysel aşamada.
3. **Feature sayısı**: 148+ feature var ama cross-sectional normalization sadece temel feature'lara uygulanıyor.
4. **Regime tespiti**: Rejim etiketleri harici bir modülden geliyor (services/macro/); yanlış regime etiketi tüm sistemi etkiler.
5. **SHAP hesaplama maliyeti**: Büyük dataset'lerde SHAP hesaplama yavaş; sample_size ile sınırlanıyor.
6. **CatBoost custom loss**: `CatBoostAdjustedLoss` henüz production'da tam test edilmedi.
7. **Reinforcement learning**: `rl_agent.py` ve `finrl_bist.py` deneysel; production'da aktif değil.

## Cross-Reference

- **Learning servisi** → `services/learning/`: ML modellerinin sürekli öğrenme döngüsünü yönetir. ML servisi model eğitir, Learning servisi ne zaman eğitileceğine karar verir.
- **Feature servisi** → `services/features/`: Ham piyasa verilerini 148+ feature'a dönüştürür. ML servisi bu feature'ları tüketir.
- **Macro servisi** → `services/macro/`: Rejim tespiti yapar. ML servisi rejim bilgisini feature ağırlıkları ve model seçiminde kullanır.
- **Core servisi** → `services/core/`: Event bus, metrics math, pipeline orchestrator. ML servisi event publish eder ve metrics hesaplar.
- **Config** → `services/learning/config/learning_config.py`: Tüm eşikler ve parametreler tek merkezden yönetilir.
