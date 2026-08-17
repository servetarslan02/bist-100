# ML Nihai Sistem Dokümanı — Kod Analizi + Araştırma Bazlı

**Tarih:** 2026-08-18
**Kaynaklar:** Nature Stacked Gradient Boosting (2026), MDPI Regime-Aware LightGBM (2026), ResearchGate Explainable AI Ensemble (2026), MDPI ML Time Series Survey (2025), Springer SHAP Feature Importance (2026)

---

## 1. Sektörde En İyi Uygulama Nedir?

### 1.1 Model Karşılaştırması (Araştırma Bazlı)

| Model | Avantaj | Dezavantaj | BIST Performans | Kaynak |
|-------|---------|------------|-----------------|--------|
| **LightGBM** | Hızlı, büyük veri, kategorik feature | Overfitting riski | ✅ En iyi | MDPI (2026) |
| **XGBoost** | Güçlü, regularization | Yavaş eğitim | ✅ İyi | Nature (2026) |
| **CatBoost** | Kategorik handling, robust | Yavaş | ✅ İyi | MDPI (2025) |
| **LSTM** | Sequential patterns, temporal | Overfitting, yavaş | ⚠️ Orta | Nature (2026) |
| **Transformer** | Attention, long-range | Büyük veri gerekli | ⚠️ Orta | Nature (2026) |
| **Ensemble** | Diversifikasyon | Karmaşıklık | ✅ En iyi | ResearchGate (2026) |

### 1.2 En İyi Uygulama Prensipleri

| Prensipler | Açıklama | Kaynak |
|------------|----------|--------|
| **Walk-forward validation** | Rolling window ile OOS test | MDPI (2026) |
| **Feature importance (SHAP)** | Hangi feature önemli? | Springer (2026) |
| **Calibration** | Confidence gerçek olasılık mı? | MDPI (2026) |
| **Overfitting prevention** | Early stopping, regularization | Nature (2026) |
| **Ensemble** | Çoklu model birleşimi | ResearchGate (2026) |
| **Regime-aware** | Rejime göre model seçimi | MDPI (2026) |
| **Adjusted loss** | Yanlış yön cezası | Mevcut sistem |
| **Cross-sectional normalization** | Tarih bazlı normalize | Mevcut sistem |

---

## 2. Bizde Şu An Ne Var?

### 2.1 Modül Özeti (16 dosya, 3,052 satır)

| Modül | Satır | Ne Yapıyor | Durum |
|-------|-------|------------|-------|
| `training_validator.py` | 809 | Veri kalitesi, leakage, cross-sectional normalize | ✅ En kapsamlı |
| `lightgbm_trainer.py` | 746 | LightGBM eğitim, multi-horizon, NDCG | ✅ İyi |
| `ranking_model.py` | 532 | Ana ranking model, SHAP, rule-based fallback | ✅ İyi |
| `ranker.py` | 238 | Learning-to-rank model | ✅ İyi |
| `walk_forward.py` | 196 | Walk-forward validation | ✅ İyi |
| `adjusted_loss.py` | 111 | Yanlış yön cezası loss | ✅ İyi |
| `lstm_model.py` | 61 | LSTM model (PyTorch) | ⚠️ Basit |
| `finrl_bist.py` | 53 | FinRL trading environment | ⚠️ Basit |
| `transformer_model.py` | 52 | Transformer model (PyTorch) | ⚠️ Basit |
| `model_comparator.py` | 42 | Model karşılaştırma | ⚠️ Basit |
| `ensemble.py` | 37 | Ağırlıklı ensemble | ⚠️ Basit |
| `xgboost_model.py` | 32 | XGBoost model | ⚠️ Basit |
| `fingpt.py` | 21 | Türkçe sentiment (kelime tabanlı) | ⚠️ Çok basit |
| `hybrid_model.py` | 17 | FinGPT + RL birleşimi | ⚠️ Çok basit |
| `rl_agent.py` | 16 | RL agent (PPO) | ⚠️ Placeholder |
| `qlib_integration.py` | 16 | Qlib entegrasyonu | ⚠️ Placeholder |

### 2.2 Mevcut Özellikler

| Özellik | Var mı? | Kalite |
|---------|---------|--------|
| LightGBM training | ✅ | İyi (multi-horizon, NDCG) |
| Walk-forward validation | ✅ | İyi |
| Feature importance (SHAP) | ✅ | İyi |
| Adjusted loss (yanlış yön cezası) | ✅ | İyi |
| Cross-sectional normalization | ✅ | İyi |
| Training data validation | ✅ | İyi (leakage detection) |
| Rule-based fallback | ✅ | İyi |
| Regime-based weights | ✅ | İyi |
| Multi-horizon prediction | ✅ | İyi |
| XGBoost | ⚠️ Basit | Placeholder |
| LSTM | ⚠️ Basit | Temel PyTorch |
| Transformer | ⚠️ Basit | Temel PyTorch |
| Ensemble | ⚠️ Basit | Sadece ağırlıklı ortalama |
| Model comparator | ⚠️ Basit | Sadece accuracy/F1 |
| FinGPT | ⚠️ Çok basit | Kelime tabanlı |
| RL Agent | ⚠️ Placeholder | Çalışmıyor |
| Qlib | ⚠️ Placeholder | Çalışmıyor |
| CatBoost | ❌ | Yok |
| Model registry | ❌ | Yok |
| Model versioning | ⚠️ Basit | lightgbm_trainer'da var |
| Champion-challenger | ❌ | Yok |
| Model calibration | ❌ | Yok |
| Hyperparameter tuning | ❌ | Yok |

---

## 3. Eksikler (Kritik)

### 3.1 CatBoost Yok

**Sorun:** LightGBM ve XGBoost var ama CatBoost yok
**Etki:** Kategorik feature handling eksik
**Kaynak:** MDPI (2025) — CatBoost en iyi performans gösteren modellerden
**Çözüm:** CatBoost entegrasyonu

### 3.2 Model Registry Yok

**Sorun:** Modeller versioned değil, hangi model hangi versiyon bilinmiyor
**Etki:** Model lifecycle yönetimi eksik
**Çözüm:** Model registry (version, metrics, status, lineage)

### 3.3 Champion-Challenger Yok

**Sorun:** Yeni model doğrudan production'a alınıyor
**Etki:** Yeni model kötüyse tüm sistem etkilenir
**Çözüm:** Shadow mode → A/B test → promote/reject

### 3.4 Model Calibration Yok

**Sorun:** Model %90 confidence veriyor ama gerçekten %90 mı bilinmiyor
**Etki:** Overconfident model → fazla risk
**Çözüm:** Calibration curve, Brier score

### 3.5 Hyperparameter Tuning Yok

**Sorun:** Parametreler manuel ayarlanıyor
**Etki:** Optimal parametreler bulunamıyor
**Çözüm:** Optuna/GridSearch entegrasyonu

### 3.6 Ensemble Basit

**Sorun:** Sadece ağırlıklı ortalama — stacking, blending yok
**Etki:** Ensemble gücü tam kullanılmıyor
**Çözüm:** Stacking ensemble, dynamic weights

### 3.7 LSTM/Transformer Basit

**Sorun:** Temel PyTorch implementasyonu — attention mechanism, positional encoding yok
**Etki:** Deep learning gücü tam kullanılmıyor
**Çözüm:** Gelişmiş architecture

### 3.8 Feature Importance Tracking Yok

**Sorun:** SHAP hesaplanıyor ama zaman içinde takip edilmiyor
**Etki:** Feature drift tespit edilemiyor
**Çözüm:** SHAP history, feature importance trends

---

## 4. Nihai ML Mimarisi

### 4.1 ML Pipeline (Nihai)

```
┌─────────────────────────────────────────────────────────────┐
│                    ML PIPELINE                               │
│                                                             │
│  ┌─────────────────────────────────────────────────────┐   │
│  │              DATA PREPARATION                        │   │
│  │  - Feature matrix oluşturma                         │   │
│  │  - Cross-sectional normalization                    │   │
│  │  - Target label oluşturma (multi-horizon)           │   │
│  │  - Train/Validation/Test split (walk-forward)       │   │
│  │  - Data quality validation                          │   │
│  │  - Leakage detection                                │   │
│  └─────────────────────────┬───────────────────────────┘   │
│                            ↓                                │
│  ┌─────────────────────────────────────────────────────┐   │
│  │              MODEL TRAINING                          │   │
│  │                                                      │   │
│  │  ┌──────────┐  ┌──────────┐  ┌──────────┐          │   │
│  │  │ LightGBM │  │ XGBoost  │  │ CatBoost │          │   │
│  │  │ (primary)│  │          │  │ (yeni)   │          │   │
│  │  └──────────┘  └──────────┘  └──────────┘          │   │
│  │  ┌──────────┐  ┌──────────┐  ┌──────────┐          │   │
│  │  │  LSTM    │  │Transformer│  │  Linear  │          │   │
│  │  │          │  │          │  │  Models  │          │   │
│  │  └──────────┘  └──────────┘  └──────────┘          │   │
│  │                                                      │   │
│  │  - Early stopping                                    │   │
│  │  - Regularization (L1/L2)                            │   │
│  │  - Adjusted loss (yanlış yön cezası)                │   │
│  │  - Walk-forward validation                           │   │
│  └─────────────────────────┬───────────────────────────┘   │
│                            ↓                                │
│  ┌─────────────────────────────────────────────────────┐   │
│  │              HYPERPARAMETER TUNING                   │   │
│  │  - Optuna (Bayesian optimization)                    │   │
│  │  - Cross-validation ile tuning                       │   │
│  │  - Regime-specific tuning                            │   │
│  └─────────────────────────┬───────────────────────────┘   │
│                            ↓                                │
│  ┌─────────────────────────────────────────────────────┐   │
│  │              MODEL VALIDATION                        │   │
│  │  - Walk-forward OOS test                             │   │
│  │  - Deflated Sharpe ratio                             │   │
│  │  - Precision@K, IC, Hit Rate                         │   │
│  │  - Calibration check                                 │   │
│  │  - Feature importance (SHAP)                         │   │
│  └─────────────────────────┬───────────────────────────┘   │
│                            ↓                                │
│  ┌─────────────────────────────────────────────────────┐   │
│  │              ENSEMBLE                                │   │
│  │                                                      │   │
│  │  ┌──────────┐  ┌──────────┐  ┌──────────┐          │   │
│  │  │ Stacking │  │ Blending │  │ Weighted │          │   │
│  │  │ Ensemble │  │ Ensemble │  │ Average  │          │   │
│  │  └──────────┘  └──────────┘  └──────────┘          │   │
│  │                                                      │   │
│  │  - Regime-based dynamic weights                      │   │
│  │  - Model agreement confidence                        │   │
│  │  - Fallback chain (primary → secondary → rule-based) │   │
│  └─────────────────────────┬───────────────────────────┘   │
│                            ↓                                │
│  ┌─────────────────────────────────────────────────────┐   │
│  │              MODEL REGISTRY                          │   │
│  │  - Version tracking (v1, v2, v3)                     │   │
│  │  - Metrics storage (accuracy, Sharpe, IC)            │   │
│  │  - Status (CANDIDATE, CHAMPION, RETIRED)             │   │
│  │  - Lineage (training data, features, hyperparams)    │   │
│  └─────────────────────────┬───────────────────────────┘   │
│                            ↓                                │
│  ┌─────────────────────────────────────────────────────┐   │
│  │              CHAMPION-CHALLENGER                     │   │
│  │  - Shadow mode (paralel çalıştır)                    │   │
│  │  - A/B test (istatistiksel karşılaştırma)            │   │
│  │  - Auto-promote/reject                               │   │
│  │  - Rollback capability                               │   │
│  └─────────────────────────┬───────────────────────────┘   │
│                            ↓                                │
│  ┌─────────────────────────────────────────────────────┐   │
│  │              MONITORING                              │   │
│  │  - Performance tracking (Sharpe, IC, win rate)       │   │
│  │  - Feature drift detection                           │   │
│  │  - Prediction drift detection                        │   │
│  │  - Model decay detection                             │   │
│  │  - Auto-retrain trigger                              │   │
│  └─────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────┘
```

### 4.2 CatBoost Entegrasyonu (Nihai)

```python
class CatBoostModel:
    """CatBoost model — kategorik feature handling."""
    
    def __init__(self, params: Optional[Dict] = None):
        self._params = params or {
            "iterations": 500,
            "depth": 6,
            "learning_rate": 0.1,
            "loss_function": "Logloss",
            "eval_metric": "AUC",
            "cat_features": [],  # Kategorik feature indeksleri
            "verbose": 0,
        }
        self._model = None
    
    def train(self, X_train, y_train, X_val=None, y_val=None, cat_features=None):
        try:
            from catboost import CatBoostClassifier
            self._model = CatBoostClassifier(**self._params)
            if cat_features:
                self._model.set_params(cat_features=cat_features)
            eval_set = (X_val, y_val) if X_val is not None else None
            self._model.fit(X_train, y_train, eval_set=eval_set, early_stopping_rounds=50)
            logger.info("CatBoost trained", n_samples=len(X_train))
            return self._model
        except ImportError:
            logger.warning("catboost not installed")
            return None
    
    def predict(self, X):
        if self._model is None: return np.zeros(len(X))
        return self._model.predict_proba(X)[:, 1]
    
    def feature_importance(self):
        if self._model is None: return None
        return self._model.feature_importances_
```

### 4.3 Model Registry (Nihai)

```python
class ModelRegistry:
    """Model kayıt defteri — version, metrics, status, lineage."""
    
    def __init__(self):
        self._models = {}  # model_id → {version, metrics, status, lineage}
    
    def register(self, model_id: str, version: str, model, metrics: Dict,
                 training_data: Dict, features: List[str], hyperparams: Dict):
        """Model kaydet."""
        self._models[f"{model_id}:{version}"] = {
            "model_id": model_id,
            "version": version,
            "model": model,
            "metrics": metrics,
            "status": "CANDIDATE",
            "training_data": training_data,
            "features": features,
            "hyperparams": hyperparams,
            "created_at": datetime.now().isoformat(),
            "promoted_at": None,
            "retired_at": None,
        }
    
    def promote(self, model_id: str, version: str):
        """Model'i champion yap."""
        key = f"{model_id}:{version}"
        if key in self._models:
            # Mevcut champion'ı retire et
            for k, v in self._models.items():
                if v["model_id"] == model_id and v["status"] == "CHAMPION":
                    v["status"] = "RETIRED"
                    v["retired_at"] = datetime.now().isoformat()
            
            # Yeni champion
            self._models[key]["status"] = "CHAMPION"
            self._models[key]["promoted_at"] = datetime.now().isoformat()
    
    def get_champion(self, model_id: str) -> Optional[Dict]:
        """Champion model'i getir."""
        for v in self._models.values():
            if v["model_id"] == model_id and v["status"] == "CHAMPION":
                return v
        return None
    
    def list_models(self, model_id: str = None) -> List[Dict]:
        """Modelleri listele."""
        results = []
        for v in self._models.values():
            if model_id is None or v["model_id"] == model_id:
                results.append({
                    "model_id": v["model_id"],
                    "version": v["version"],
                    "status": v["status"],
                    "metrics": v["metrics"],
                    "created_at": v["created_at"],
                })
        return results
```

### 4.4 Stacking Ensemble (Nihai)

```python
class StackingEnsemble:
    """Stacking ensemble — meta-learner ile model birleştirme."""
    
    def __init__(self):
        self._base_models = {}  # name → model
        self._meta_learner = None  # Meta-learner (LogisticRegression, vb.)
    
    def fit(self, X_train, y_train, X_val, y_val):
        """Base modelleri eğit, meta-learner'ı eğit."""
        base_predictions = []
        
        # 1. Base modelleri eğit
        for name, model in self._base_models.items():
            model.fit(X_train, y_train)
            val_pred = model.predict(X_val)
            base_predictions.append(val_pred)
        
        # 2. Meta-learner'ı eğit (base predictions → final prediction)
        meta_X = np.column_stack(base_predictions)
        from sklearn.linear_model import LogisticRegression
        self._meta_learner = LogisticRegression()
        self._meta_learner.fit(meta_X, y_val)
    
    def predict(self, X):
        """Stacking prediction."""
        base_predictions = []
        for name, model in self._base_models.items():
            pred = model.predict(X)
            base_predictions.append(pred)
        
        meta_X = np.column_stack(base_predictions)
        return self._meta_learner.predict_proba(meta_X)[:, 1]
```

### 4.5 Hyperparameter Tuning (Nihai)

```python
class HyperparameterTuner:
    """Optuna ile hyperparameter tuning."""
    
    def tune_lightgbm(self, X_train, y_train, X_val, y_val, n_trials: int = 50) -> Dict:
        """LightGBM hyperparameter tuning."""
        try:
            import optuna
            import lightgbm as lgb
            
            def objective(trial):
                params = {
                    "n_estimators": trial.suggest_int("n_estimators", 100, 1000),
                    "max_depth": trial.suggest_int("max_depth", 3, 10),
                    "learning_rate": trial.suggest_float("learning_rate", 0.01, 0.3, log=True),
                    "num_leaves": trial.suggest_int("num_leaves", 20, 100),
                    "min_child_samples": trial.suggest_int("min_child_samples", 5, 50),
                    "subsample": trial.suggest_float("subsample", 0.5, 1.0),
                    "colsample_bytree": trial.suggest_float("colsample_bytree", 0.5, 1.0),
                    "reg_alpha": trial.suggest_float("reg_alpha", 1e-8, 10.0, log=True),
                    "reg_lambda": trial.suggest_float("reg_lambda", 1e-8, 10.0, log=True),
                }
                
                model = lgb.LGBMRegressor(**params)
                model.fit(X_train, y_train)
                preds = model.predict(X_val)
                
                # IC (Information Coefficient) kullan
                ic = np.corrcoef(preds, y_val)[0, 1]
                return ic if not np.isnan(ic) else 0
            
            study = optuna.create_study(direction="maximize")
            study.optimize(objective, n_trials=n_trials)
            
            return {
                "best_params": study.best_params,
                "best_ic": study.best_value,
                "n_trials": n_trials,
            }
        except ImportError:
            logger.warning("optuna not installed")
            return {"error": "optuna not installed"}
```

---

## 5. Rakip Karşılaştırması

### 5.1 MDPI Regime-Aware LightGBM (2026)

| Özellik | MDPI | Bizim Sistem | Fark |
|---------|------|-------------|------|
| LightGBM | ✅ | ✅ | ✅ Aynı |
| Walk-forward | ✅ Expanding window | ✅ | ✅ Aynı |
| Regime-aware | ✅ Rolling HMM | ⚠️ Basit | ⚠️ |
| Feature selection | ✅ SHAP | ✅ | ✅ Aynı |
| Multi-horizon | ✅ | ✅ | ✅ Aynı |

### 5.2 Nature Stacked Ensemble (2026)

| Özellik | Nature | Bizim Sistem | Fark |
|---------|--------|-------------|------|
| Stacking ensemble | ✅ | ❌ | ❌ |
| XGBoost + LightGBM | ✅ | ✅ | ✅ Aynı |
| Ridge meta-learner | ✅ | ❌ | ❌ |
| Feature importance | ✅ SHAP | ✅ | ✅ Aynı |

### 5.3 ResearchGate Explainable AI (2026)

| Özellik | ResearchGate | Bizim Sistem | Fark |
|---------|-------------|-------------|------|
| Ensemble (RF + GBM + XGB) | ✅ | ⚠️ Basit | ⚠️ |
| SHAP explanation | ✅ | ✅ | ✅ Aynı |
| Model interpretability | ✅ | ⚠️ Basit | ⚠️ |

---

## 6. Uygulama Planı

### Faz 1: CatBoost Entegrasyonu (Hemen)
1. CatBoost model class
2. LightGBM trainer'a entegre et
3. Feature importance comparison

### Faz 2: Model Registry (1 hafta)
1. Version tracking
2. Metrics storage
3. Status management (CANDIDATE/CHAMPION/RETIRED)
4. Lineage tracking

### Faz 3: Stacking Ensemble (1 hafta)
1. Base models (LightGBM, XGBoost, CatBoost)
2. Meta-learner (Ridge/LogisticRegression)
3. Regime-based dynamic weights

### Faz 4: Hyperparameter Tuning (1 hafta)
1. Optuna entegrasyonu
2. IC-based objective
3. Regime-specific tuning
4. Cross-validation ile tuning

### Faz 5: Champion-Challenger (1 hafta)
1. Shadow mode
2. A/B test
3. Auto-promote/reject
4. Rollback capability

### Faz 6: Model Monitoring (1 hafta)
1. Performance tracking
2. Feature drift detection
3. Prediction drift detection
4. Auto-retrain trigger

---

## 7. Mevcut Sistem vs Nihai Vizyon

| Özellik | Mevcut | Hedef |
|---------|--------|-------|
| Modül sayısı | 16 | 22 |
| Toplam satır | 3,052 | ~5,000 |
| LightGBM | ✅ İyi | ✅ |
| XGBoost | ⚠️ Basit | ✅ Gelişmiş |
| CatBoost | ❌ | ✅ |
| LSTM | ⚠️ Basit | ✅ Gelişmiş |
| Transformer | ⚠️ Basit | ✅ Gelişmiş |
| Ensemble | ⚠️ Basit | ✅ Stacking |
| Model registry | ❌ | ✅ |
| Champion-challenger | ❌ | ✅ |
| Hyperparameter tuning | ❌ | ✅ Optuna |
| Calibration | ❌ | ✅ |
| Feature importance tracking | ⚠️ Basit | ✅ SHAP history |
| Walk-forward | ✅ İyi | ✅ |
| Adjusted loss | ✅ İyi | ✅ |
| Cross-sectional normalization | ✅ İyi | ✅ |
| Training validation | ✅ İyi | ✅ |
| Rule-based fallback | ✅ İyi | ✅ |
