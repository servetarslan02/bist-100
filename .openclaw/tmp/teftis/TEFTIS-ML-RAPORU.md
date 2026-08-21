# 🔬 BIST-100 ALPHA — ML Pipeline Tam Denetim Raporu

**Tarih:** 2026-08-21  
**Kapsam:** services/ml/, ml/, services/learning/, services/intelligence/  
**Toplam Taranan Dosya:** 32  
**Toplam Bulunan Hata:** 47  

---

## ÖZET

| Önem Seviyesi | Sayı |
|---|---|
| 🔴 KRİTİK | 12 |
| 🟠 YÜKSEK | 15 |
| 🟡 ORTA | 13 |
| 🟢 DÜŞÜK | 7 |

---

## 🔴 KRİTİK HATALAR (Data Leakage & Training Bias)

### HATA-01: Early Stopping'de Test Verisi Sızıntısı
**Dosya:** `ml/training.py` ~Satır 170  
**Seviye:** 🔴 KRİTİK  
**Kategori:** Data Leakage  

```python
model.fit(
    X_train, y_train,
    eval_set=[(X_test, y_test)],  # ← TEST VERİSİ EARLY STOPPING'DE KULLANILIYOR
    callbacks=[lgb.early_stopping(config.early_stopping_rounds, verbose=False)],
)
```

**Sorun:** Walk-forward validation'da test verisi early stopping için eval_set olarak kullanılıyor. Model, test verisini eğitim sırasında "görüyor" — bu klasik data leakage.  
**Etki:** Walk-forward metrikleri gerçek performansı olduğundan yüksek gösterir.  
**Düzeltme:** Early stopping için ayrı bir validation set ayır (train → train+purge → val → purge → test):
```python
val_size = len(X_train) // 5
X_val, y_val = X_train[-val_size:], y_train[-val_size:]
X_train, y_train = X_train[:-val_size], y_train[:-val_size]
model.fit(X_train, y_train, eval_set=[(X_val, y_val)], ...)
```

---

### HATA-02: Final Model Tüm Veriyle Eğitiliyor (Test Dönemleri Dahil)
**Dosya:** `ml/training.py` ~Satır 215  
**Seviye:** 🔴 KRİTİK  
**Kategori:** Data Leakage  

```python
# Train final model on all data
X_all, y_all, feat_names = self.prepare_dataset(
    data_sorted, config.feature_names, config.target  # ← TÜM VERİ (test dönemleri dahil)
)
final_model.fit(X_all, y_all)
```

**Sorun:** Walk-forward validation sonrası final model, test dönemlerini de içeren tüm veriyle eğitiliyor. Bu, gelecekteki veriyi geçmişe sızdırır.  
**Etki:** Production modeli gelecek bilgisiyle eğitilmiş olur.  
**Düzeltme:** Final modeli sadece son training window ile eğit veya tüm veriyi kullan ama walk-forward metriklerini bu modele uygula.

---

### HATA-03: KFold shuffle=True ile Zaman Serisi Verisi
**Dosya:** `services/ml/stacking_ensemble.py` ~Satır 80  
**Seviye:** 🔴 KRİTİK  
**Kategori:** Data Leakage / Cross-Validation  

```python
kf = KFold(n_splits=self._config.cv_folds, shuffle=True, random_state=42)
```

**Sorun:** Zaman serisi verisinde KFold ile shuffle=True kullanılıyor. Bu, gelecekteki verilerin eğitim fold'larına karışmasına neden olur.  
**Etki:** Stacking meta-learner gelecek bilgisiyle eğitilir.  
**Düzeltme:** `TimeSeriesSplit` kullan:
```python
from sklearn.model_selection import TimeSeriesSplit
kf = TimeSeriesSplit(n_splits=self._config.cv_folds)
```

---

### HATA-04: Hyperparameter Tuning'de KFold shuffle=True
**Dosya:** `services/ml/hyperparameter_tuner.py` ~Satır 100  
**Seviye:** 🔴 KRİTİK  
**Kategori:** Data Leakage / Cross-Validation  

```python
kf = KFold(n_splits=self.cv_folds, shuffle=True, random_state=42)
```

**Sorun:** Hiperparametre optimizasyonunda zaman serisi verisi shuffle ile cross-validation yapılıyor.  
**Etki:** Optuna en iyi parametreleri gelecek veri sızıntısıyla seçer.  
**Düzeltme:** `TimeSeriesSplit` kullan.

---

### HATA-05: Impute Değerleri Tüm Veriden Hesaplanıyor
**Dosya:** `services/ml/lightgbm_trainer.py` ~Satır 250  
**Seviye:** 🔴 KRİTİK  
**Kategori:** Data Leakage  

```python
# Impute — tüm veriden hesaplanır ama sadece TRAIN'de kullanılır
impute_values = self._compute_impute_values(X, feature_names)  # ← TÜM X
X = self._impute(X, impute_values)
```

**Sorun:** Impute değerleri (median) train+val tüm veriden hesaplanıyor. Validation verisinin istatistikleri train'e sızıyor.  
**Etki:** Scaler ve impute bilgisi validation verisinden geliyor.  
**Düzeltme:** Impute ve scaler'ı sadece train split'inden öğren:
```python
# Split'ten SONRA
scaler_mean = np.mean(X_train_raw, axis=0)
impute_values = self._compute_impute_values(X_train_raw, feature_names)
```

---

### HATA-06: LambdaRank Label'ları Tüm Veriden Hesaplanıyor
**Dosya:** `services/ml/lightgbm_trainer.py` ~Satır 290  
**Seviye:** 🔴 KRİTİK  
**Kategori:** Data Leakage  

```python
# LambdaRank rank labels (sadece train için)
y_rank = np.zeros(len(y), dtype=int)
for d in unique_dates:
    indices = [i for i, t in enumerate(tickers) if date_groups.get(t) == d]
    if len(indices) > 1:
        group_returns = [y[i] for i in indices]
        sorted_indices = sorted(range(len(group_returns)), key=lambda k: -group_returns[k])
        for rank, idx in enumerate(sorted_indices):
            y_rank[indices[idx]] = rank
```

**Sorun:** Rank label'ları tüm veri (train+val) üzerinde hesaplanıyor. Validation verisinin rank'leri train verisine bağlı.  
**Etki:** Train ve val rank label'ları birbirine sızıyor.  
**Düzeltme:** Rank label'ları sadece kendi split'inde hesapla.

---

### HATA-07: Walk-Forward'da Model Yeniden Eğitilmiyor
**Dosya:** `services/ml/walk_forward.py` ~Satır 80  
**Seviye:** 🔴 KRİTİK  
**Kategori:** Walk-Forward  

```python
def evaluate(self, data, model_fn, feature_fn):
    for i, split in enumerate(splits):
        # ...
        model = model_fn()  # ← HER SPLIT'TE YENİ MODEL
        model.train(train_features)
        predictions = model.predict(test_features)
```

**Sorun:** `evaluate()` fonksiyonu her split'te yeni model oluşturup eğitiyor ama `model_fn` parametresi nasıl çağrılıyor belli değil. Eğer `model_fn` aynı model nesnesini döndürüyorsa, önceki eğitim kalıntıları kalabilir.  
**Etki:** Walk-forward sonuçları kontamine olabilir.  
**Düzeltme:** Her split'te tamamen yeni bir model kopyası oluştur.

---

### HATA-08: Platt Scaling Aynı Veriyle Fit ve Predict
**Dosya:** `services/ml/calibration.py` ~Satır 130  
**Seviye:** 🔴 KRİTİK  
**Kategori:** Calibration / Data Leakage  

```python
def calibrate_platt(self, y_true, y_prob, y_prob_val=None):
    calibrator = LogisticRegression(max_iter=1000)
    calibrator.fit(y_prob.reshape(-1, 1), y_true)
    if y_prob_val is not None:
        calibrated = calibrator.predict_proba(y_prob_val.reshape(-1, 1))[:, 1]
    else:
        calibrated = calibrator.predict_proba(y_prob.reshape(-1, 1))[:, 1]  # ← AYNI VERİ
```

**Sorun:** Validation verisi sağlanmazsa, Platt scaling eğitim verisiyle kalibrasyon yapıyor — bu overfitting.  
**Etki:** Kalibrasyon metrikleri yanıltıcı.  
**Düzeltme:** Her zaman train/val split yap veya cross-validation ile kalibre et.

---

### HATA-09: Ranking Model'de Validation Yok
**Dosya:** `services/ml/ranking_model.py` ~Satır 150  
**Seviye:** 🔴 KRİTİK  
**Kategori:** Overfitting  

```python
train_data = lgb.Dataset(X_weighted, label=y_rank, group=group_sizes,
                         feature_name=self._feature_names)
params = {"objective": "lambdarank", ...}
self._lgbm_model = lgb.train(params, train_data, num_boost_round=100)
# ← valid_sets YOK, early_stopping YOK
```

**Sorun:** LambdaRank modeli validation set olmadan ve early stopping olmadan eğitiliyor.  
**Etki:** Model overfit olabilir, 100 iteration yetersiz veya fazla olabilir.  
**Düzeltme:** Validation set ekle ve early stopping kullan.

---

### HATA-10: Continuous Learning Retrain Tek Gün Verisiyle
**Dosya:** `services/learning/continuous_learning.py` ~Satır 170  
**Seviye:** 🔴 KRİTİK  
**Kategori:** Training  

```python
def _execute_retrain(self, features_map, actual_returns, regime):
    result = ranking_model.train(
        features_map=features_map,
        returns=actual_returns,
        date_groups={t: datetime.now(timezone.utc).strftime("%Y-%m-%d") for t in features_map},
        regime=regime,
    )
```

**Sorun:** Retrain sadece o günkü verilerle yapılıyor. Tüm hisseler aynı tarih atanıyor.  
**Etki:** Model tek günlük veriyle eğitiliyor — yetersiz ve noisy.  
**Düzeltme:** Son N günün verilerini biriktirip eğitimde kullan.

---

### HATA-11: Validation Metrikleri Rank vs Return Karşılaştırması
**Dosya:** `services/ml/lightgbm_trainer.py` ~Satır 310  
**Seviye:** 🔴 KRİTİK  
**Kategori:** Metric Mismatch  

```python
val_pred = model.predict(X_val_scaled)  # ← Rank prediction
val_score = self._compute_ndcg(y_val, val_pred, val_groups)  # ← y_val = actual return
validation_metrics = compute_comprehensive_metrics(y_val, val_pred)  # ← MAE, RMSE vs
```

**Sorun:** Model rank prediction yapıyor ama metrikler actual return ile karşılaştırılıyor. MAE ve RMSE rank-return karşılaştırmasında anlamsız.  
**Etki:** Metrikler yanıltıcı.  
**Düzeltme:** Rank metrikleri (NDCG, MAP) veya return prediction modeli kullan.

---

### HATA-12: CatBoost Custom Loss Uygulanmıyor
**Dosya:** `services/ml/catboost_model.py` ~Satır 140  
**Seviye:** 🔴 KRİTİK  
**Kategori:** Loss Function  

```python
if self._config.use_adjusted_loss and not self._is_classifier:
    try:
        custom_loss = CatBoostAdjustedLoss(self._config.wrong_direction_penalty)
        fit_params["eval_metric"] = "RMSE"
    except Exception as e:
        pass
# ...
model.fit(train_pool, eval_set=eval_pool, ...)  # ← custom_loss KULLANILMIYOR
```

**Sorun:** `CatBoostAdjustedLoss` oluşturuluyor ama `model.fit()`'e parametre olarak verilmiyor.  
**Etki:** Adjusted loss hiç uygulanmıyor, varsayılan RMSE kullanılıyor.  
**Düzeltme:** CatBoost custom loss'u doğru şekilde entegre et.

---

## 🟠 YÜKSEK HATALAR

### HATA-13: Ensemble Ağırlıkları Feature Importance Ortalaması
**Dosya:** `ml/models.py` ~Satır 180  
**Seviye:** 🟠 YÜKSEK  
**Kategori:** Ensemble Weights  

```python
# Confidence from feature importance
importance = model.get_feature_importance()
confidences[name] = np.mean(list(importance.values())) if importance else 0.5
```

**Sorun:** Ensemble ağırlıkları feature importance ortalamasına dayanıyor. Farklı model türlerinin importance değerleri karşılaştırılamaz.  
**Düzeltme:** Validation performansına dayalı ağırlık kullan.

---

### HATA-14: Classification Tespiti Yanlış
**Dosya:** `ml/models.py` ~Satır 130  
**Seviye:** 🟠 YÜKSEK  
**Kategori:** Model Configuration  

```python
is_classification = len(np.unique(y)) <= 10 and all(v in [0, 1] for v in np.unique(y))
```

**Sorun:** Bu heuristic, sürekli hedef değişkenlerini yanlış sınıflandırabilir. Ayrıca `all(v in [0, 1]` float karşılaştırması sorunlu.  
**Düzeltme:** Label spec'ten `is_classification` bilgisini kullan.

---

### HATA-15: Feature Drift Severity String Karşılaştırması
**Dosya:** `services/ml/feature_drift.py` ~Satır 180  
**Seviye:** 🟠 YÜKSEK  
**Kategori:** Bug  

```python
elif severity == HIGH:  # ← HIGH tanımsız değişken, "HIGH" string olmalı
    return f"'{feature}' feature'ını izle — drift artarsa retrain gerekebilir"
```

**Sorun:** `HIGH` değişkeni tanımlanmamış → `NameError` fırlatır.  
**Düzeltme:** `"HIGH"` string olarak değiştir.

---

### HATA-16: Model Monitor'da Tuple Import Eksik
**Dosya:** `services/ml/model_monitor.py` ~Satır 1  
**Seviye:** 🟠 YÜKSEK  
**Kategori:** Bug  

```python
# Kullanılıyor ama import edilmemiş:
self._metric_history: Dict[str, List[Tuple[str, float]]] = {}
```

**Sorun:** `Tuple` typing modülünden import edilmemiş.  
**Düzeltme:** `from typing import Dict, Any, Optional, List, Tuple` ekle.

---

### HATA-17: CatBoost Overfitting Tespiti Eksik
**Dosya:** `services/ml/catboost_model.py` ~Satır 350  
**Seviye:** 🟠 YÜKSEK  
**Kategori:** Overfitting Detection  

```python
def _check_overfitting(self, metrics, horizon):
    if "val_auc" in metrics and "train_auc" in metrics:  # ← train_auc HİÇ HESAPLANMIYOR
        gap = metrics["train_auc"] - metrics["val_auc"]
```

**Sorun:** `train_auc` metrikleri hiç hesaplanmadığı için overfitting kontrolü asla çalışmaz.  
**Düzeltme:** Train metriklerini de hesapla.

---

### HATA-18: Champion-Challenger Canary Attribute'ları Init Edilmemiş
**Dosya:** `services/learning/champion_challenger.py` ~Satır 30  
**Seviye:** 🟠 YÜKSEK  
**Kategori:** Bug  

```python
def __init__(self):
    self._current_champion = None
    self._champion_history = []
    self._rejected_challengers = []
    # ← _canary_active, _canary_model, vb. TANIMLANMAMIŞ
```

**Sorun:** `evaluate_canary()` çağrıldığında `_canary_active` attribute'u yok → `AttributeError`.  
**Düzeltme:** `__init__`'e tüm canary attribute'larını ekle.

---

### HATA-19: Signal Fusion'da "news" Weights'de Yok
**Dosya:** `services/intelligence/signal_fusion.py` ~Satır 100  
**Seviye:** 🟠 YÜKSEK  
**Kategori:** Feature-Target  

```python
for component in ["technical", "fundamental", "momentum", "sentiment", "news", "macro", "valuation", "ai"]:
    # ...
for component, weight in weights.items():  # ← "news" weights'de yok
    score = getattr(result, f"{component}_score", 50)
```

**Sorun:** "news" bileşeni döngüde var ama `DEFAULT_WEIGHTS`'te yok. News skoru ağırlıklı hesaba katılmıyor.  
**Düzeltme:** `DEFAULT_WEIGHTS`'e `"news": 0.05` ekle veya döngüden çıkar.

---

### HATA-20: ML Signal Fusion Yön Belirlemede Score Kullanıyor
**Dosya:** `services/intelligence/ml_signal_fusion.py` ~Satır 120  
**Seviye:** 🟠 YÜKSEK  
**Kategori:** Inconsistency  

```python
for comp in self.COMPONENTS:
    direction = result.component_directions.get(comp, "NEUTRAL")
    score = result.component_scores.get(comp, 50)
    w = weights.get(comp, 0) * (score / 100)  # ← score/100 çarpılıyor
```

**Sorun:** `signal_fusion.py`'de v2.1 düzeltmesi ile score/100 kaldırılmış ama `ml_signal_fusion.py`'de hala kullanılıyor. İki sistem farklı sonuç verir.  
**Düzeltme:** Tutarlılık için aynı mantığı kullan.

---

### HATA-21: Champion-Challenger Singleton Çift Atama
**Dosya:** `services/learning/champion_challenger.py` ~Satır 150  
**Seviye:** 🟠 YÜKSEK  
**Kategori:** Bug  

```python
# Singleton
champion_challenger = ChampionChallengerEngine()

# Singleton  ← İKİNCİ KEZ
champion_challenger = ChampionChallengerEngine()
```

**Sorun:** Singleton iki kez atanıyor. İkinci atama birincisinin üzerine yazar.  
**Düzeltme:** Tek atama bırak.

---

### HATA-22: Adjusted Loss Hiçbir Model Tarafından Kullanılmıyor
**Dosya:** `services/ml/adjusted_loss.py`  
**Seviye:** 🟠 YÜKSEK  
**Kategori:** Integration  

**Sorun:** `AdjustedMSELoss` sınıfı tanımlanmış ama hiçbir model (LightGBM, XGBoost, CatBoost) tarafından eğitimde kullanılmıyor. XGBoost ve CatBoost'ta kendi adjusted loss sınıfları var ama onlar da uygulanmıyor (HATA-12).  
**Düzeltme:** Model eğitim pipeline'larına adjusted loss entegre et.

---

### HATA-23: Walk-Forward Purge Gap Sample-Space'de
**Dosya:** `services/ml/walk_forward.py` ~Satır 40  
**Seviye:** 🟠 YÜKSEK  
**Kategori:** Purge/Embargo  

```python
def __init__(self, train_size=252, test_size=21, purge_size=5, ...):
    self._purge_size = purge_size  # Sample index olarak kullanılıyor
```

**Sorun:** Purge gap sample indeksi olarak uygulanıyor, tarih gününde değil. Eğer veri seyrekse (eksik günler), purge yetersiz kalır.  
**Düzeltme:** `lightgbm_trainer.py`'deki gibi date-space purge kullan.

---

### HATA-24: Retrain Engine Feature Preparation Hatası
**Dosya:** `services/learning/retrain_engine.py` ~Satır 200  
**Seviye:** 🟠 YÜKSEK  
**Kategori:** Data Preparation  

```python
def _prepare_features(self, features_map, feature_fn):
    if feature_fn:
        return feature_fn(features_map)
    arrays = []
    for name, values in features_map.items():
        if isinstance(values, np.ndarray) and values.ndim == 1:
            arrays.append(values)
    min_len = min(len(a) for a in arrays)
    return np.column_stack([a[:min_len] for a in arrays])
```

**Sorun:** Feature map dict'inin values'ları farklı uzunlukta olabilir ve truncation veri kaybına neden olur. Ayrıca dict key'leri feature adı değil ticker adı olabilir.  
**Düzeltme:** Feature map yapısını standartlaştır.

---

### HATA-25: Stacking Meta-Learner Minimum Sample Çok Düşük
**Dosya:** `services/ml/stacking_ensemble.py` ~Satır 200  
**Seviye:** 🟠 YÜKSEK  
**Kategori:** Overfitting  

```python
if np.sum(mask) < 10:  # Minimum sample
    continue
```

**Sorun:** Rejim-specific meta-learner için minimum 10 sample yetersiz.  
**Düzeltme:** En az 50 sample gerektir.

---

### HATA-26: Forecasting Engine Sadece Heuristic
**Dosya:** `services/intelligence/forecasting.py` ~Satır 30  
**Seviye:** 🟠 YÜKSEK  
**Kategori:** Model Quality  

```python
def _forecast_horizon(self, ticker, features, returns, horizon):
    momentum = features.get("momentum_20d", 0)
    base_return = momentum * 0.3  # ← Basit heuristic
```

**Sorun:** Forecasting motoru sadece basit heuristic kullanıyor, gerçek ML modeli yok.  
**Düzeltme:** ML modellerini forecasting pipeline'a entegre et.

---

### HATA-27: Probability Engine Heuristic Ağırlıkları Sabit
**Dosya:** `services/intelligence/probability.py` ~Satır 120  
**Seviye:** 🟠 YÜKSEK  
**Kategori:** Model Quality  

```python
model_weights = {
    "momentum": 0.25,
    "volume": 0.20,
    "volatility": 0.15,
    "trend": 0.20,
    "rsi": 0.20,
}
```

**Sorun:** Olasılık tahmini sabit heuristic ağırlıklarla yapılıyor. Ağırlıklar optimize edilmemiş.  
**Düzeltme:** Logistic regression veya kalibre edilmiş ML modeli kullan.

---

## 🟡 ORTA HATALAR

### HATA-28: Feature Importance Training Data Üzerinde Hesaplanıyor
**Dosya:** `ml/feature_discovery.py` ~Satır 130  
**Seviye:** 🟡 ORTA  
**Kategori:** Feature Importance  

```python
def _permutation_importance(self, data, target, feature_names):
    model = lgb.LGBMRegressor(...)
    model.fit(X, y)
    result = permutation_importance(model, X, y, ...)  # ← AYNI VERİ
```

**Sorun:** Permutation importance eğitim verisi üzerinde hesaplanıyor.  
**Düzeltme:** Hold-out set üzerinde hesapla.

---

### HATA-29: Leakage Detection Yetersiz
**Dosya:** `ml/feature_discovery.py` ~Satır 200  
**Seviye:** 🟡 ORTA  
**Kategori:** Data Leakage  

```python
def _detect_leakage(self, data, target, feature_names):
    # Sadece temporal correlation stability kontrolü
    if max_corr > 0.95 and stability < 0.5:
        leakage[f] = True
```

**Sorun:** Leakage detection sadece korelasyon stabilitesini kontrol ediyor. Target'tan türetilmiş feature'ları tespit edemiyor.  
**Düzeltme:** Feature'ların target ile korelasyonunu da kontrol et (corr > 0.99 → şüpheli).

---

### HATA-30: LSTM/Transformer Best State Tanımsız
**Dosya:** `services/ml/lstm_model.py` ~Satır 150  
**Seviye:** 🟡 ORTA  
**Kategori:** Bug  

```python
for epoch in range(self._config.epochs):
    # ...
    if val_loss < best_val_loss:
        best_state = {k: v.clone() for k, v in self._model.state_dict().items()}
# ...
if 'best_state' in locals():  # ← Eğer val_loss hiç iyileşmezse best_state yok
    self._model.load_state_dict(best_state)
```

**Sorun:** İlk epoch'ta bile val_loss < inf olacağı için genellikle çalışır ama garanti yok.  
**Düzeltme:** `best_state`'i döngüden önce başlat.

---

### HATA-31: LSTM Predict Dummy Target Oluşturuyor
**Dosya:** `services/ml/lstm_model.py` ~Satır 170  
**Seviye:** 🟡 ORTA  
**Kategori:** Prediction Pipeline  

```python
def predict(self, X):
    X_seq, _ = self._create_sequences(X, np.zeros(len(X)))  # ← Dummy target
```

**Sorun:** Prediction sırasında gereksiz dummy target oluşturuluyor.  
**Düzeltme:** Sadece X sequence oluşturan ayrı bir fonksiyon yaz.

---

### HATA-32: XGBoost DMatrix Oluşturulup Kullanılmıyor
**Dosya:** `services/ml/xgboost_model.py` ~Satır 120  
**Seviye:** 🟡 ORTA  
**Kategori:** Code Quality  

```python
dtrain = xgb.DMatrix(X_train, label=y_train, ...)  # ← Oluşturuldu
dval = xgb.DMatrix(X_val, label=y_val, ...) if X_val is not None else None
# ...
model.fit(X_train, y_train, **fit_params)  # ← sklearn API, DMatrix kullanılmıyor
```

**Sorun:** DMatrix oluşturuluyor ama sklearn API kullanıldığı için gereksiz.  
**Düzeltme:** Ya native API kullan ya da DMatrix oluşturma.

---

### HATA-33: CatBoost Kategorik Feature Tespiti Sorunlu
**Dosya:** `services/ml/catboost_model.py` ~Satır 300  
**Seviye:** 🟡 ORTA  
**Kategori:** Feature Engineering  

```python
if col.dtype.kind in ('i', 'u'):
    unique_count = len(np.unique(col[~np.isnan(col.astype(float))]))
    if unique_count < 20:
        cat_indices.append(i)
```

**Sorun:** Integer sütunlar otomatik kategorik olarak atanıyor. Bu, continuous integer feature'ları (ör. volume) kategorik yapabilir.  
**Düzeltme:** Domain knowledge ile kategorik feature'ları manuel belirle.

---

### HATA-34: Ensemble Confidence Negatif Olabilir
**Dosya:** `services/ml/ensemble.py` ~Satır 70  
**Seviye:** 🟡 ORTA  
**Kategori:** Confidence  

```python
confidence = 1.0 - np.std(preds_matrix, axis=0)
```

**Sorun:** `std > 1` olursa confidence negatif olur.  
**Düzeltme:** `np.clip(confidence, 0, 1)` ekle (zaten yapılıyor ama açıklama yok).

---

### HATA-35: Hyperparameter Tuner Pearson Kullanıyor
**Dosya:** `services/ml/hyperparameter_tuner.py` ~Satır 200  
**Seviye:** 🟡 ORTA  
**Kategori:** Metric  

```python
def _compute_objective(self, preds, y_true, objective_type):
    if objective_type == "ic":
        ic = np.corrcoef(preds, y_true)[0, 1]  # ← Pearson
```

**Sorun:** IC (Information Coefficient) genellikle Spearman rank correlation olarak hesaplanır. Pearson outlier'lara duyarlı.  
**Düzeltme:** `scipy.stats.spearmanr` kullan.

---

### HATA-36: Continuous Learning Drift Kontrolü Her Gün
**Dosya:** `services/learning/continuous_learning.py` ~Satır 130  
**Seviye:** 🟡 ORTA  
**Kategori:** Performance  

```python
def _should_check_drift(self, date):
    return True  # ← Her gün
```

**Sorun:** Drift kontrolü her gün yapılıyor ama `drift_check_interval` config'de tanımlı.  
**Düzeltme:** Config'e göre interval uygula.

---

### HATA-37: Walk-Forward Metrik Hesaplaması Basit
**Dosya:** `services/ml/walk_forward.py` ~Satır 120  
**Seviye:** 🟡 ORTA  
**Kategori:** Metrics  

```python
def _calculate_metrics(self, predictions, actuals):
    pred_values = [p.get("score", 0) for p in predictions]
    corr = np.corrcoef(pred_values, actuals)[0, 1]
```

**Sorun:** Predictions dict listesi ama actuals float listesi. `pred_values` ve `actuals` uzunlukları farklı olabilir.  
**Düzeltme:** Uzunluk kontrolü ekle.

---

### HATA-38: Model Confidence Narrow Prediction Penalty
**Dosya:** `services/ml/lightgbm_trainer.py` ~Satır 200  
**Seviye:** 🟡 ORTA  
**Kategori:** Confidence  

```python
if target_std > 0 and pred_std / target_std < 0.1:
    confidence *= 0.6
```

**Sorun:** Narrow prediction (düşük pred_std) cezalandırılıyor ama bu iyi kalibre bir model için normal olabilir.  
**Düzeltme:** Narrow prediction'ı sadece target_std yüksekse cezalandır.

---

### HATA-39: Feature Stability 3 Periyoda Bölünüyor
**Dosya:** `ml/feature_discovery.py` ~Satır 180  
**Seviye:** 🟡 ORTA  
**Kategori:** Feature Engineering  

```python
n = len(X)
third = n // 3
for i in range(3):
    start = i * third
    end = (i + 1) * third if i < 2 else n
```

**Sorun:** Veri 3 eşit parçaya bölünüyor ama zaman sırası korunmuyor (data zaten sıralı olmalı). Ayrıca 3 periyot yetersiz olabilir.  
**Düzeltme:** Daha fazla periyot kullan veya expanding window.

---

### HATA-40: Regime-Specific Calibration Minimum Sample Düşük
**Dosya:** `services/ml/calibration.py` ~Satır 180  
**Seviye:** 🟡 ORTA  
**Kategori:** Calibration  

```python
if np.sum(mask) < 20:
    continue
```

**Sorun:** Rejim-specific kalibrasyon için 20 sample yetersiz.  
**Düzeltme:** En az 50 sample gerektir.

---

## 🟢 DÜŞÜK HATALAR

### HATA-41: Confidence Hesaplaması Basit
**Dosya:** `ml/training.py` ~Satır 230  
**Seviye:** 🟢 DÜŞÜK  
**Kategori:** Confidence  

```python
confidence = accuracy * 0.6 + consistency * 0.4
```

**Sorun:** Confidence hesaplaması çok basit. Calibration, Brier score gibi metrikler dahil değil.  
**Düzeltme:** Calibration-based confidence kullan.

---

### HATA-42: Model Ensemble Ağırlık Normalizasyonu
**Dosya:** `ml/models.py` ~Satır 200  
**Seviye:** 🟢 DÜŞÜK  
**Kategori:** Ensemble  

```python
weights = weights / weights.sum() if weights.sum() > 0 else np.ones(len(weights)) / len(weights)
```

**Sorun:** Ağırlıklar normalize ediliyor ama negatif olabilir (feature importance'dan geliyor).  
**Düzeltme:** `np.abs(weights)` kullan.

---

### HATA-43: Forecasting Horizon Factor
**Dosya:** `services/intelligence/forecasting.py` ~Satır 50  
**Seviye:** 🟢 DÜŞÜK  
**Kategori:** Model Quality  

```python
horizon_factor = np.sqrt(horizon / 20)
```

**Sorun:** Square root of time scaling sadece volatilite için geçerli, getiri tahmini için değil.  
**Düzeltme:** Horizon-specific model kullan.

---

### HATA-44: Probability Engine Sigmoid Scaling
**Dosya:** `services/intelligence/probability.py` ~Satır 170  
**Seviye:** 🟢 DÜŞÜK  
**Kategori:** Calibration  

```python
probability = 1 / (1 + np.exp(-(final_score - 50) / 15))
```

**Sorun:** Sigmoid scaling sabit (15) — kalibre edilmemiş.  
**Düzeltme:** Platt scaling veya isotonic regression kullan.

---

### HATA-45: Ensemble Forecaster Model Registration
**Dosya:** `services/intelligence/ensemble_forecast.py` ~Satır 200  
**Seviye:** 🟢 DÜŞÜK  
**Kategori:** Architecture  

```python
ensemble_forecaster.register_model("heuristic", heuristic_model)
ensemble_forecaster.register_model("momentum", momentum_model)
ensemble_forecaster.register_model("statistical", statistical_model)
```

**Sorun:** Modül yüklendiğinde heuristic modeller kaydediliyor. Gerçek ML modelleri runtime'da eklenmeli.  
**Düzeltme:** ML model registration'ı lazy yap.

---

### HATA-46: CatBoost Feature Interaction Sınırlı
**Dosya:** `services/ml/catboost_model.py` ~Satır 320  
**Seviye:** 🟢 DÜŞÜK  
**Kategori:** Feature Engineering  

```python
for f1_idx, f2_idx, score in interactions[:20]:  # Top 20
```

**Sorun:** Sadece top 20 interaction gösteriliyor ama tüm interaction'lar hesaplanıyor.  
**Düzeltme:** Threshold bazlı filtreleme kullan.

---

### HATA-47: Drift Detector PSI Hesaplaması Basitleştirilmiş
**Dosya:** `services/ml/feature_drift.py` ~Satır 100  
**Seviye:** 🟢 DÜŞÜK  
**Kategori:** Drift Detection  

```python
psi = abs(current_imp - hist_mean) / max(hist_std, 0.01)
```

**Sorun:** Bu gerçek PSI değil, sadece z-score benzeri bir metrik. Gerçek PSI dağılım karşılaştırması gerektirir.  
**Düzeltme:** `_calculate_psi` fonksiyonunu kullan (zaten mevcut).

---

## 📋 DÜZELTME ÖNCELİK SIRASI

### Acil (Hemen)
1. HATA-01: Early stopping data leakage
2. HATA-03/04: KFold shuffle=True
3. HATA-05/06: Impute/rank data leakage
4. HATA-12: CatBoost custom loss
5. HATA-15: Feature drift NameError

### Yüksek (1 Hafta)
6. HATA-02: Final model data leakage
7. HATA-09: Ranking model validation
8. HATA-10: Continuous learning retrain
9. HATA-11: Metric mismatch
10. HATA-17: CatBoost overfitting detection

### Orta (2 Hafta)
11. HATA-13/14: Ensemble weights & classification
12. HATA-18: Champion-challenger init
13. HATA-19/20: Signal fusion consistency
14. HATA-28/29: Feature importance & leakage detection

### Düşük (1 Ay)
15. HATA-41-47: Confidence, calibration, heuristic improvements

---

## 🔧 GENEL ÖNERİLER

1. **TimeSeriesSplit Zorunlu:** Tüm cross-validation'larda `TimeSeriesSplit` kullan, `KFold(shuffle=True)` yasakla.

2. **Purge/Embargo Standardı:** Tüm walk-forward validation'larda date-space purge uygula (min: target horizon).

3. **Feature Pipeline Parity:** Training ve inference'da aynı feature pipeline kullan (scaler, impute, CS normalization).

4. **Adjusted Loss Entegrasyonu:** `AdjustedMSELoss`'u tüm modellere entegre et — yanlış yön cezası kritik.

5. **Confidence Calibration:** Tüm confidence skorlarını Platt scaling ile kalibre et.

6. **Model Registry:** Tüm modelleri versioned registry'de sakla, champion-challenger ile yönet.

7. **Automated Testing:** ML pipeline için unit test yaz — data leakage, metric range, feature contract.

---

*Rapor otomatik olarak oluşturulmuştur. Tüm hatalar kod incelemesi ile tespit edilmiştir.*
