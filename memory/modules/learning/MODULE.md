# LEARNING — Sürekli Öğrenme Servisi

## Giriş

Learning servisi, ALPHA BIST sisteminin **beyni**dir. ML servisinin ürettiği tahminleri izler, sonuçları kaydeder, model bozulmasını tespit eder ve otomatik olarak yeniden eğitim tetikler. Temel döngüsü: **Prediction → Outcome → Error → Attribution → Drift → Retrain → Champion/Reject.**

Sistem, insan müdahalesi olmadan 7/24 çalışacak şekilde tasarlanmıştır. Bir modül çökse bile diğerleri çalışmaya devam eder (cascade failure prevention).

## Katman Haritası

```
┌─────────────────────────────────────────────────────────────────┐
│                 LEARNING SERVİSİ KATMAN HARİTASI                 │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │  KATMAN 1: ÖĞRENME DÖNGÜSÜ (Core Loop)                   │   │
│  │  learning_loop.py        — Ana döngü: pred→outcome→decay  │   │
│  │  integrated_learning.py  — Prediction/outcome kaydı       │   │
│  │  continuous_learning.py  — Günlük pipeline (otomatik)     │   │
│  │  super_intelligence.py   — Self-healing, auto-retrain     │   │
│  └────────────────────────┬─────────────────────────────────┘   │
│                           │                                      │
│  ┌────────────────────────▼─────────────────────────────────┐   │
│  │  KATMAN 2: DRIFT & KALİBRASYON                           │   │
│  │  drift_detector.py       — PSI, KS, ADWIN, Page-Hinkley  │   │
│  │  calibration.py          — Brier, ECE, Platt scaling      │   │
│  │  feature_tracker.py      — SHAP-based feature importance  │   │
│  └────────────────────────┬─────────────────────────────────┘   │
│                           │                                      │
│  ┌────────────────────────▼─────────────────────────────────┐   │
│  │  KATMAN 3: MODEL YÖNETİMİ                                 │   │
│  │  champion_challenger.py  — Promote/reject, canary deploy  │   │
│  │  shadow_manager.py       — Paralel çalıştırma, A/B test   │   │
│  │  model_registry.py       — Versiyon takibi, rollback      │   │
│  │  meta_learner.py         — Rejim-specific model selection │   │
│  │  retrain_engine.py       — Walk-forward validated retrain  │   │
│  └────────────────────────┬─────────────────────────────────┘   │
│                           │                                      │
│  ┌────────────────────────▼─────────────────────────────────┐   │
│  │  KATMAN 4: TAKİP & RAPORLAMA                              │   │
│  │  outcome_tracker.py      — Otomatik outcome takibi         │   │
│  │  attribution.py          — İşlem atfedilmesi (neden?)      │   │
│  │  health_monitor.py       — Modül sağlık izleme             │   │
│  │  performance_reporter.py — Performans raporları             │   │
│  └────────────────────────┬─────────────────────────────────┘   │
│                           │                                      │
│  ┌────────────────────────▼─────────────────────────────────┐   │
│  │  KATMAN 5: ARAŞTIRMA & KEŞİF (Phase Scripts)              │   │
│  │  phase1-30_*.py          — Alpha keşfi, robustness test    │   │
│  │  alpha_engine_v2.py      — Alpha üretim motoru             │   │
│  │  alpha_hunt.py           — Alpha avcısı                    │   │
│  │  production_alpha_engine.py — Production alpha pipeline    │   │
│  └────────────────────────┬─────────────────────────────────┘   │
│                           │                                      │
│  ┌────────────────────────▼─────────────────────────────────┐   │
│  │  KATMAN 6: KONFİGÜRASYON & ARAÇLAR                        │   │
│  │  config/learning_config.py — Tüm eşikler tek merkezden    │   │
│  │  utils/statistical_tests.py — PSI, KS, ADWIN, PH, Welch  │   │
│  │  utils/shap_helpers.py     — SHAP hesaplama yardımcıları   │   │
│  └──────────────────────────────────────────────────────────┘   │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

## Neden Bu Tasarım Seçimi?

| Karar | Neden | Alternatif | Neden Reddedildi |
|-------|-------|-----------|-----------------|
| **Çoklu drift tespit yöntemi (PSI + KS + ADWIN + PH + Z-score)** | Tek yöntem yanıltıcı olabilir; en az 2 yöntem hemfikir olmalı. | Tek yöntem | False positive/negative riski |
| **Concept drift (performans bazlı)** | Feature dağılımı değişmese bile model performansı düşebilir. | Sadece feature drift | Concept drift'i kaçırır |
| **Walk-forward validated retrain** | Walk-forward başarısızsa retrain yapmak anlamsız. | Doğrudan retrain | Overfitting riski |
| **Deflated Sharpe correction** | Çoklu test düzeltmesi — birden fazla model denendiğinde Sharpe şişir. | Ham Sharpe | Multiple testing bias |
| **Shadow mode (paralel çalıştırma)** | Yeni model doğrudan production'a alınamaz; minimum observation süresi gerekli. | Doğrudan deploy | Production riski |
| **Canary deployment** | Küçük pozisyonlarla test — %10 allocation ile başla, başarılıysa artır. | Full deploy | Risk yönetimi |
| **Rejim-specific model selection** | Hangi model hangi rejimde daha iyi performans gösteriyor? | Tek model tüm rejimlerde | Rejim değişince bozulma |
| **Platt scaling ile confidence kalibrasyonu** | Model %90 confidence veriyorsa gerçekten %90 olmalı. | Ham confidence | Overconfidence riski |
| **İşlem atfedilmesi (attribution)** | "Neden kazandım/kaybettim?" sorusu kritik. | Sadece kazanç/kayıp | Öğrenme eksik |
| **Modül bazlı health check** | Bir modül çökse diğerleri çalışmalı. | Monolitik sağlık | Cascade failure |
| **Pydantic config** | Tüm eşikler tek merkezden, type-safe, env override destekli. | Hardcoded eşikler | Bakım imkansız |

## Uçtan Uca Veri Akışı

```
ML Servisi Tahmin Üretir
        │
        ▼
┌─────────────────────┐
│ Prediction Kaydı    │  integrated_learning.py
│ - Ticker, yön,      │  learning_loop.py
│   confidence, rejim │
│ - Feature snapshot  │
└─────────┬───────────┘
          │
          ▼
┌─────────────────────┐
│ Outcome Takibi      │  outcome_tracker.py
│ - 5 gün bekle       │  (async price fetcher)
│ - Fiyat çek         │
│ - Sonuç kaydet      │
└─────────┬───────────┘
          │
          ▼
┌─────────────────────┐
│ Öğrenme Döngüsü     │  learning_loop.py
│ - Doğruluk hesapla  │  integrated_learning.py
│ - Regime accuracy   │
│ - Model decay check │
└─────────┬───────────┘
          │
          ▼
┌─────────────────────┐
│ Attribution         │  attribution.py
│ - Neden kazandım?   │  Macro, flow, momentum,
│ - Neden kaybettim?  │  event, regime, technical
│ - Dersler çıkar     │
└─────────┬───────────┘
          │
          ▼
┌─────────────────────┐
│ Drift Tespiti       │  drift_detector.py
│ - PSI (veri dağılımı)│  feature_tracker.py
│ - KS test           │
│ - ADWIN (adaptif)   │
│ - Page-Hinkley      │
│ - Concept drift     │
│ - Feature importance│
└─────────┬───────────┘
          │
          ▼
┌─────────────────────┐
│ Kalibrasyon         │  calibration.py
│ - Brier score       │
│ - ECE / MCE         │
│ - Overconfidence?   │
│ - Platt scaling     │
└─────────┬───────────┘
          │
          ▼
┌─────────────────────┐
│ Retrain Kararı      │  continuous_learning.py
│ - Sharpe < 0.3?     │  super_intelligence.py
│ - Win rate < 45%?   │
│ - Drift tespit?     │
│ - Max interval doldu?│
└─────────┬───────────┘
          │
          ▼
┌─────────────────────┐
│ Walk-Forward        │  retrain_engine.py
│ Validation          │
│ - Train/test split  │
│ - Purge + embargo   │
│ - Deflated Sharpe   │
│ - Kabul/red kararı  │
└─────────┬───────────┘
          │
          ▼
┌─────────────────────┐
│ Shadow Mode         │  shadow_manager.py
│ - Eski modelle      │  champion_challenger.py
│   paralel çalıştır  │
│ - Sonuçları kaydet  │
│ - Statistical test  │
└─────────┬───────────┘
          │
          ▼
┌─────────────────────┐
│ Champion/Reject     │  champion_challenger.py
│ - Promote: yeni     │  model_registry.py
│   champion yap      │
│ - Reject: reddet    │
│ - Canary deploy     │
│ - Rollback          │
└─────────┬───────────┘
          │
          ▼
┌─────────────────────┐
│ Health Monitor      │  health_monitor.py
│ - Modül bazlı check │
│ - Auto-heal         │
│ - Alerting          │
│ - Cascade prevention│
└─────────┬───────────┘
          │
          ▼
    ML Servisi'ne Bildirim (retrain tetikleme)
```

## Dosya Bazlı Sorumluluk Tablosu

| Dosya | Sorumluluk | Kritiklik |
|-------|-----------|-----------|
| `integrated_learning.py` | Prediction/outcome kaydı, regime accuracy, feature importance güncelleme, model drift kontrolü | ⭐⭐⭐⭐⭐ |
| `continuous_learning.py` | Günlük pipeline — performans kaydetme, drift kontrolü, retrain kararı, A/B test, registry güncelleme | ⭐⭐⭐⭐⭐ |
| `learning_loop.py` | Ana öğrenme döngüsü — prediction→outcome→decay→retrain tetikleme | ⭐⭐⭐⭐⭐ |
| `drift_detector.py` | Çoklu drift tespit — PSI, KS, ADWIN, Page-Hinkley, Z-score, concept drift; en az 2 yöntem anlaşmalı | ⭐⭐⭐⭐⭐ |
| `champion_challenger.py` | Champion-challenger motoru — promote/reject, canary deployment, rollback | ⭐⭐⭐⭐⭐ |
| `calibration.py` | Confidence kalibrasyonu — Brier score, ECE, Platt scaling, rejim-specific calibration | ⭐⭐⭐⭐⭐ |
| `attribution.py` | İşlem atfedilmesi — macro, flow, momentum, event, regime, technical katkı; ders çıkarma | ⭐⭐⭐⭐⭐ |
| `feature_tracker.py` | SHAP-based feature importance tracking — trend analizi, rejim-specific, feature selection önerisi | ⭐⭐⭐⭐ |
| `health_monitor.py` | Modül sağlık izleme — prediction, outcome, calibration, drift, model, feature pipeline; auto-heal | ⭐⭐⭐⭐⭐ |
| `outcome_tracker.py` | Otomatik outcome takibi — 5 gün bekle, fiyat çek, learning system'a bildir | ⭐⭐⭐⭐⭐ |
| `shadow_manager.py` | Shadow mode — paralel çalıştırma, minimum observation, statistical significance, promote/reject | ⭐⭐⭐⭐⭐ |
| `retrain_engine.py` | Walk-forward validated retrain — deflated Sharpe, model kabul/red, shadow mode tetikleme | ⭐⭐⭐⭐⭐ |
| `model_registry.py` | Model versiyon kayıt defteri — version tracking, rollback, auto-cleanup | ⭐⭐⭐⭐ |
| `meta_learner.py` | Rejim-specific model selection — hangi model hangi rejimde iyi, dynamic ensemble weights, decay prediction | ⭐⭐⭐⭐ |
| `super_intelligence.py` | Self-healing, auto-retrain, A/B test, drift detection, meta-learning, cascade failure prevention | ⭐⭐⭐⭐⭐ |
| `performance_reporter.py` | Performans raporları | ⭐⭐⭐ |
| `model_memory_store.py` | Model bellek deposu | ⭐⭐⭐ |
| `model_performance_engine.py` | Model performans motoru | ⭐⭐⭐ |
| `model_trust_engine.py` | Model güven motoru | ⭐⭐⭐ |
| `learning_pipeline.py` | Learning pipeline | ⭐⭐⭐ |
| `frozen_strategy_engine.py` | Donmuş strateji motoru | ⭐⭐⭐ |
| `config/learning_config.py` | Tüm eşikler ve parametreler — Pydantic, env override destekli | ⭐⭐⭐⭐⭐ |
| `utils/statistical_tests.py` | İstatistiksel testler — PSI, KS, ADWIN, Page-Hinkley, Welch t-test, deflated Sharpe | ⭐⭐⭐⭐⭐ |
| `utils/shap_helpers.py` | SHAP hesaplama yardımcıları | ⭐⭐⭐ |
| `phase1-30_*.py` | Araştırma scriptleri — alpha keşfi, robustness test, forensics | ⭐⭐ |
| `alpha_engine_v2.py` | Alpha üretim motoru v2 | ⭐⭐⭐ |
| `alpha_hunt.py` | Alpha avcısı | ⭐⭐⭐ |
| `production_alpha_engine.py` | Production alpha pipeline | ⭐⭐⭐ |
| `institutional_walkforward_engine.py` | Kurumsal walk-forward motoru | ⭐⭐⭐ |
| `train_val_multi_fold_optimizer.py` | Çoklu fold optimizasyonu | ⭐⭐⭐ |
| `real_bist_walkforward_backtest.py` | Gerçek BIST walk-forward backtest | ⭐⭐⭐ |

## Tasarım İlkeleri ve Kırmızı Çizgiler

### İlkeler

1. **Kendi kendini yöneten sistem**: İnsan müdahalesi olmadan 7/24 çalışmalı. Self-healing, auto-retrain, cascade failure prevention.
2. **Çoklu yöntem anlaşması**: Drift kararı için en az 2 yöntem hemfikir olmalı. Tek yöntem yanıltıcı olabilir.
3. **Walk-forward zorunlu**: Walk-forward başarısızsa retrain yapma. Overfitting riski çok yüksek.
4. **Statistical significance**: Champion değişikliği p-value < 0.05 gerektirir. "Daha iyi görünüyor" yeterli değil.
5. **Shadow mode**: Yeni model doğrudan production'a alınamaz. Minimum observation süresi + statistical test.
6. **Modül izolasyonu**: Bir modül çökse diğerleri çalışmalı. Cascade failure prevention.
7. **Merkezi konfigürasyon**: Tüm eşikler `learning_config.py`'den okunur. Hardcoded değerler yasak.
8. **Attribution**: "Neden kazandım/kaybettim?" sorusu kritik. Sadece kazanç/kayıp yeterli değil.

### Kırmızı Çizgiler

- ❌ **Walk-forward başarısızken retrain** — overfitting garantisi.
- ❌ **Shadow mode olmadan champion değişikliği** — production riski.
- ❌ **Tek yöntem drift kararı** — false positive/negative riski.
- ❌ **Hardcoded eşikler** — `learning_config.py` dışında eşik tanımlanamaz.
- ❌ **Modül arası doğrudan bağımlılık** — event bus veya try/except ile gevşek bağlantı.
- ❌ **Confidence kalibrasyonu yapılmadan production** — overconfidence riski.
- ❌ **Outcome kaydetmeden model decay kontrolü** — eksik veri → yanlış karar.

## Bilinen Sınırlamalar

1. **Phase scriptleri araştırma amaçlı**: `phase1-30_*.py` dosyaları production pipeline'ın parçası değil; araştırma ve keşif amaçlı.
2. **Super Intelligence karmaşıklığı**: `super_intelligence.py` çok fazla sorumluluk taşıyor; gelecekte parçalanması gerekebilir.
3. **Outcome takibi asenkron**: `outcome_tracker.py` async price fetcher gerektirir; fiyat kaynağı yoksa outcome kaydedilemez.
4. **Regime bağımlılığı**: Drift detection ve model selection rejim etiketine bağımlı; yanlış etiket tüm sistemi etkiler.
5. **SHAP maliyeti**: Feature importance tracking SHAP hesaplama gerektirir; büyük dataset'lerde yavaş.
6. **Config override sınırlı**: `from_env()` sadece iki seviye nested config'i destekliyor.
7. **Model memory store**: `model_memory_store.py` henüz tam entegre değil.
8. **Kurumsal modüller**: `institutional_walkforward_engine.py`, `institutional_portfolio_optimizer.py` deneysel aşamada.

## Cross-Reference

- **ML servisi** → `services/ml/`: Model eğitimi ve tahmin üretimi. Learning servisi ne zaman eğitileceğine karar verir, ML servisi eğitir.
- **Feature servisi** → `services/features/`: Feature drift tespiti bu servisin ürettiği feature'lara bakar.
- **Macro servisi** → `services/macro/`: Rejim tespiti. Learning servisi rejim bilgisini model selection ve drift detection'da kullanır.
- **Core servisi** → `services/core/`: Event bus (PREDICTION_CREATED, OUTCOME_CREATED), metrics math (Sharpe, IC, win rate).
- **Config** → `config/learning_config.py`: Tüm eşikler tek merkezden. Pydantic ile type-safe, env override destekli.
- **ML modülleri** → `services/ml/ranking_model.py`, `services/ml/lightgbm_trainer.py`: Retrain tetiklendiğinde bu modüller eğitilir.
