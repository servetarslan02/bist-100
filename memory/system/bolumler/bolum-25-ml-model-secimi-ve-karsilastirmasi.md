# Bölüm 25 — ML Model Seçimi ve Karşılaştırması

## Amaç

Hangi makine öğrenmesi modeli hangi koşulda daha iyi çalışıyor? BIST 100 hissesiyle hangisi daha uyumlu?

**Kaynak:** Springer (2026) Attention-Based Autoencoder with GRU, MDPI (2026) Regime-Aware LightGBM, ResearchGate (2025) Bibliometric Review — From Statistical Model to Deep Learning.

---

## Kullanılacak sistemler

- Model Registry
- Model Trainer
- Model Evaluator
- Hyperparameter Tuner
- Model Selector
- Ensemble Manager
- Model Drift Detector

---

## Çalışma mantığı

```
Veri → Feature'lar → Birden fazla model eğit →
Karşılaştır (accuracy, Sharpe, drawdown) →
En iyi modeli seç → Ensemble → Production
```

---

## 1. Model Aileleri

### Geleneksel ML:
```
Linear Regression    → Basit, yorumlanabilir, düşük performans
Ridge/Lasso          → Regularized, overfitting azaltır
Random Forest        → Ensemble, feature importance
XGBoost/LightGBM     → Gradient boosting, genelde en iyi
```

### Derin Öğrenme:
```
LSTM                 → Zaman serisi için tasarlanmış
GRU                  → LSTM'den daha hafif
Transformer          → Attention mekanizması, paralel
CNN-1D               → Lokal pattern tespiti
```

### Hibrit:
```
LSTM + XGBoost       → LSTM feature çıkarır, XGBoost sınıflandırır
Transformer + RL     → Transformer analiz, RL aksiyon
```

---

## 2. Karşılaştırma Matrisi

| Model | Accuracy | Hız | Yorumlanabilirlik | Overfitting | BIST Uyumu |
|-------|----------|-----|-------------------|-------------|------------|
| Linear | Düşük | Çok hızlı | Yüksek | Düşük | Düşük |
| Random Forest | Orta | Hızlı | Orta | Orta | Orta |
| XGBoost | Yüksek | Hızlı | Orta | Orta | Yüksek |
| LightGBM | Yüksek | Çok hızlı | Orta | Orta | Yüksek |
| LSTM | Yüksek | Yavaş | Düşük | Yüksek | Orta |
| GRU | Yüksek | Orta | Düşük | Yüksek | Orta |
| Transformer | Çok yüksek | Yavaş | Düşük | Yüksek | Yüksek |

---

## 3. XGBoost / LightGBM

**Araştırma bulgusu:** MDPI (2026) — "Regime-Aware LightGBM with 63 features outperforms static models in walk-forward validation."

### Neden BIST için iyi?
```
- Küçük-orta veri setiyle çalışır (BIST'te ~100 hisse)
- Feature importance sağlar (hangi gösterge önemli?)
- Hızlı eğitim ve inference
- Regularization ile overfitting kontrolü
- Kategorik feature desteği
```

### Örnek: XGBoost eğitimi

```python
# services/ml/xgboost_model.py
import xgboost as xgb
from sklearn.model_selection import TimeSeriesSplit


def train_xgboost(X_train, y_train, X_val, y_val):
    model = xgb.XGBClassifier(
        n_estimators=500,
        max_depth=6,
        learning_rate=0.01,
        subsample=0.8,
        colsample_bytree=0.8,
        reg_alpha=0.1,
        reg_lambda=1.0,
        eval_metric="logloss",
        early_stopping_rounds=50,
    )

    model.fit(
        X_train,
        y_train,
        eval_set=[(X_val, y_val)],
        verbose=False,
    )

    return model
```

### Örnek: LightGBM eğitimi

```python
# services/ml/lightgbm_model.py
import lightgbm as lgb


def train_lightgbm(X_train, y_train, X_val, y_val):
    model = lgb.LGBMClassifier(
        n_estimators=1000,
        max_depth=7,
        learning_rate=0.01,
        num_leaves=31,
        subsample=0.8,
        colsample_bytree=0.8,
        reg_alpha=0.1,
        reg_lambda=1.0,
        min_child_samples=20,
    )

    model.fit(
        X_train,
        y_train,
        eval_set=[(X_val, y_val)],
        callbacks=[lgb.early_stopping(50)],
    )

    return model
```

---

## 4. LSTM / GRU

**Araştırma bulgusu:** Springer (2026) — "Attention-Based Autoencoder with GRU outperforms single deep learning models in prediction accuracy."

### Neden BIST için sınırlı?
```
- Küçük veri setiyle overfitting riski yüksek
- Uzun eğitim süresi
- Yorumlanabilirlik düşük
- BIST'te veri sayısı az (~2500 gün)
```

### Örnek: LSTM modeli

```python
# services/ml/lstm_model.py
import torch
import torch.nn as nn


class StockLSTM(nn.Module):
    def __init__(self, input_size, hidden_size=64, num_layers=2):
        super().__init__()
        self.lstm = nn.LSTM(input_size, hidden_size, num_layers, batch_first=True, dropout=0.2)
        self.fc = nn.Linear(hidden_size, 3)  # BUY, HOLD, SELL

    def forward(self, x):
        lstm_out, _ = self.lstm(x)
        out = self.fc(lstm_out[:, -1, :])
        return out
```

---

## 5. Transformer

**Araştırma bulgusu:** arXiv (2026) — "Sentiment-Aware Stock Price Prediction with Transformer and LLM."

### Neden BIST için potansiyelli?
```
- Attention mekanizması hangi günlerin önemli olduğunu öğrenir
- Uzun vadeli bağımlılıkları yakalar
- LLM ile entegrasyon mümkün
- Ama: Daha fazla veri gerektirir
```

### Örnek: Transformer modeli

```python
# services/ml/transformer_model.py
import torch
import torch.nn as nn


class StockTransformer(nn.Module):
    def __init__(self, input_size, d_model=64, nhead=4, num_layers=2):
        super().__init__()
        self.embedding = nn.Linear(input_size, d_model)
        encoder_layer = nn.TransformerEncoderLayer(d_model=d_model, nhead=nhead)
        self.transformer = nn.TransformerEncoder(encoder_layer, num_layers=num_layers)
        self.fc = nn.Linear(d_model, 3)

    def forward(self, x):
        x = self.embedding(x)
        x = self.transformer(x)
        out = self.fc(x[:, -1, :])
        return out
```

---

## 6. Walk-Forward Validation ile Karşılaştırma

**Araştırma bulgusu:** MDPI (2026) — "Walk-Forward Validation with Purge and Embargo."

### Karşılaştırma protokolü:
```
1. Aynı veri seti üzerinde tüm modelleri eğit
2. Walk-forward ile test et (purge + embargo)
3. Metrikleri karşılaştır:
   - Precision@K
   - Information Coefficient (IC)
   - Sharpe Ratio
   - Maximum Drawdown
   - Stability Score
```

### Örnek: Model karşılaştırma

```python
# services/ml/model_comparator.py
def compare_models(models, X_train, y_train, X_test, y_test):
    results = {}
    
    for name, model in models.items():
        model.fit(X_train, y_train)
        predictions = model.predict(X_test)
        probas = model.predict_proba(X_test)[:, 1]
        
        results[name] = {
            "accuracy": accuracy_score(y_test, predictions),
            "precision": precision_score(y_test, predictions),
            "recall": recall_score(y_test, predictions),
            "f1": f1_score(y_test, predictions),
            "ic": np.corrcoef(probas, y_test)[0, 1],
        }
    
    return results
```

---

## 7. Model Seçim Kararı

### Hangi durumda hangi model?

```
Veri az (<1000 gün):     XGBoost / LightGBM
Veri bol (>5000 gün):    Transformer / LSTM
Hız gerekli:             LightGBM / XGBoost
Yorumlanabilirlik gerekli: XGBoost + SHAP
Ensemble:                XGBoost + LSTM + Transformer
```

### BIST için önerilen:
```
Ana model:       LightGBM (hızlı, accurate, yorumlanabilir)
Yedek model:     XGBoost (karşılaştırma için)
Ensemble:        LightGBM + XGBoost ağırlıklı ortalama
Gelecek:         Transformer (veri arttığında)
```

---

## 8. Ensemble (Model Birleştirme)

```python
# services/ml/ensemble.py
def ensemble_predict(models, weights, X):
    predictions = {}

    for name, model in models.items():
        predictions[name] = model.predict_proba(X)[:, 1]

    # Ağırlıklı ortalama
    ensemble_proba = sum(predictions[name] * weights[name] for name in models)

    return ensemble_proba
```

---

## Çıktı

```
Models Compared:     6 (Linear, RF, XGBoost, LightGBM, LSTM, Transformer)
Best Model:          LightGBM
Accuracy:            0.67
IC:                  0.15
Sharpe:              1.45
Ensemble:            LightGBM (0.6) + XGBoost (0.4)
Training Time:       2.3 seconds (LightGBM)
Inference Time:      0.8ms per prediction
```

---

## Temel prensip

> "Hybrid techniques have significantly increased prediction accuracy." — Springer (2026)

Tek bir model en iyi değildir. **BIST için LightGBM + XGBoost ensemble, hem hız hem accuracy dengesi sağlar.** Veri arttıkça Transformer eklenmeli.

> Kaynak: Springer (2026), MDPI (2026) LightGBM, ResearchGate (2025) Bibliometric Review
