# Bölüm 8 — Gelecek Tahmini ve Olasılık Motoru

## Amaç

Hissenin geleceğini tek bir fiyatla tahmin etmek yerine, olası sonuçları ve bunların gerçekleşme ihtimallerini hesaplamak.

**Kaynak:** Nature (2026) FusionLSTM-CNF confidence calibration, Wiley (2025) Probabilistic AI Forecasting, ScienceDirect (2026) Bayesian uncertainty.

---

## Kullanılacak sistemler

- Forecasting Engine (Time-Series, Fundamental, Technical, Macro, AI)
- Probability Engine (Confidence Calibration, Uncertainty Analysis)

---

## Çalışma mantığı

```
Geçmiş + Fundamental + Technical + Makro + Haber/KAP + Değerleme →
Forecasting Engine → Bull/Base/Bear → Olasılık Dağılımı →
Beklenen Getiri → Confidence + Uncertainty
```

---

## 1. Forecasting

**Araştırma bulgusu:** Nature (2026) — "Confidence-calibrated multi-modal late fusion for stock movement prediction under uncertainty."

### Örnek: Multi-horizon forecasting

```python
# services/intelligence/forecasting.py
from services.intelligence.forecasting import forecasting_engine

features = {"momentum_20d": 5, "realized_vol_20d": 20, "rsi_14": 60}
forecasts = forecasting_engine.compute_forecasts("THYAO", features, [1, 2, -1])
# 1d: +0.5%, 5d: +1.2%, 20d: +3.5%, 60d: +8.0%, 120d: +12.0%
```

---

## 2. Probability Engine

### Örnek: Olasılık hesaplama

```python
# services/intelligence/probability.py
from services.intelligence.probability import probability_engine

prob = probability_engine.compute_probability_from_features(
    {"roc_5d": 5, "momentum_20d": 10, "rsi_14": 60})
# probability_positive: 0.68, confidence: 0.36
```

---

## 3. Ensemble Forecasting

Tek model yerine birden fazla modelin sonuçlarını birleştirir.

### Örnek: Ensemble

```python
from services.intelligence.forecasting import ensemble_forecasting

# Farklı modellerden gelen tahminler
forecasts = [
    Forecast(ticker="THYAO", horizon_days=5, predicted_return=1.2, probability_positive=0.6, confidence=0.8, model_source="technical"),
    Forecast(ticker="THYAO", horizon_days=5, predicted_return=0.8, probability_positive=0.55, confidence=0.7, model_source="ml"),
    Forecast(ticker="THYAO", horizon_days=5, predicted_return=1.5, probability_positive=0.65, confidence=0.6, model_source="fundamental"),
]

combined = ensemble_forecasting.combine_forecasts(forecasts)
# combined.predicted_return = 1.17 (ağırlıklı ortalama)
# combined.confidence = 0.71
```

Her modelin kendi güçlü ve zayıf yönleri var; ensemble bunları dengeler.

---

## 4. Confidence Calibration

**Araştırma bulgusu:** ScienceDirect (2026) — "Quantifying uncertainty in financial forecasting: deterministic models often fail under market volatility."

Model: "145 TL olacak" demek yerine "145 TL civarı için %X güvenim var; belirsizliğin ana kaynağı Y." diyebilmeli.

---

## Çıktı

```
Expected Price:    145 TL
Expected Return:   +31%
Bull Probability:  %25
Base Probability:  %50
Bear Probability:  %25
Confidence:        %82
Uncertainty:       Orta
```

---

## Temel prensip

Sistem geleceği "bilmiş gibi" davranmaz; **olasılık dağılımı + belirsizlik + güven seviyesi** üretir.

---

## ML Model Seçimi Entegrasyonu

**Kaynak:** Bölüm 25 — ML Model Seçimi ve Karşılaştırması

Bu bölümün tahmin motoru, Bölüm 25'teki modellerden girdi alır:

| Model | Bölüm 25 Motoru | Bölüm 8 Kullanımı |
|-------|----------------|-------------------|
| XGBoost | `ml/xgboost_model.py` | Hızlı tahmin |
| LightGBM | `ml/lightgbm_model.py` | Hızlı tahmin |
| LSTM | `ml/lstm_model.py` | Zaman serisi |
| Transformer | `ml/transformer_model.py` | Uzun vadeli |
| Ensemble | `ml/ensemble.py` | Birleşik tahmin |
| Karşılaştırma | `ml/model_comparator.py` | En iyi model seçimi |

### Örnek: Model → Tahmin zinciri

```python
from services.ml.model_comparator import compare_models
from services.ml.ensemble import ensemble_predict

# Modelleri karşılaştır
results = compare_models(models, X_train, y_train, X_test, y_test)
best_model = max(results, key=lambda k: results[k]["ic"])

# Ensemble tahmin
weights = {"xgboost": 0.4, "lightgbm": 0.3, "lstm": 0.3}
prediction = ensemble_predict(models, weights, X)
```

### FinRL/FinGPT Entegrasyonu

**Kaynak:** Bölüm 29 — FinRL ve FinGPT

Ayrıca Bölüm 29'daki RL agent ve LLM sentiment de bu bölüme entegre edilir:

| Motor | Bölüm 29 | Bölüm 8 Kullanımı |
|-------|----------|-------------------|
| BISTTradingEnv | `ml/finrl_bist.py` | RL ortamı |
| FinGPTSentiment | `ml/fingpt.py` | Haber sentiment |
| Hybrid Model | `ml/hybrid_model.py` | RL + LLM birleşik |
| RL Agent | `ml/rl_agent.py` | PPO agent |
