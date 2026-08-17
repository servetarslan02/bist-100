# Learning Nihai Sistem Dokümanı — Kod Analizi + Araştırma Bazlı

**Tarih:** 2026-08-18
**Kaynaklar:** Aerospike Model Drift (2025), IBM Model Drift, ABaka AI Drift Monitoring (2025), arXiv Shadow Before Swap (2026), Databricks MLOps Workflow, ML4T GitHub (Stefan Jansen), Medium Continual Learning (2024)

---

## 1. Sektörde En İyi Uygulama Nedir?

### 1.1 Model Lifecycle (En İyi Uygulama)

```
TRAIN → VALIDATE → BACKTEST → WALK-FORWARD → SHADOW → CANARY → CHAMPION → MONITOR → RETIRE
```

**Her aşamada kalite kapısı:**
- Train: Veri kalitesi, feature validation
- Validate: Out-of-sample test, calibration check
- Backtest: Transaction cost, slippage, look-ahead bias kontrol
- Walk-forward: Rolling window, purge/embargo
- Shadow: Canlı veriyle eski modelle paralel çalıştır
- Canary: Küçük pozisyonlarla gerçek piyasada test
- Champion: Tam production'a al
- Monitor: Drift detection, performance tracking
- Retire: Performans düşünce kaldır

### 1.2 Drift Detection (En İyi Uygulama)

**3 Tür Drift:**

| Drift Türü | Ne | Tespit Yöntemi |
|------------|-----|----------------|
| **Data Drift** | Feature dağılımı değişti | KS test, PSI, Z-score |
| **Concept Drift** | Feature-target ilişki değişti | Performance decay, accuracy drop |
| **Prediction Drift** | Model çıktı dağılımı değişti | Output distribution monitoring |

**Tespit Eşikleri (Sektör Standardı):**
- PSI (Population Stability Index) > 0.2 → drift uyarısı
- PSI > 0.5 → kritik drift
- Accuracy drop > %10 → retrain tetikle
- Sharpe < 0.3 → retrain tetikle
- Win rate < %45 → retrain tetikle

### 1.3 Champion-Challenger (En İyi Uygulama)

```
Mevcut Champion Model (production)
         ↓
Yeni Challenger Model (eğitildi)
         ↓
Shadow Mode (paralel çalıştır, sonuçları kaydet)
         ↓
A/B Test (istatistiksel karşılaştırma)
         ↓
Challenger daha iyi mi? (p < 0.05)
         ↓
Evet → Challenger yeni Champion
Hayır → Challenger reddet, Champion devam
```

### 1.4 Calibration (En İyi Uygulama)

```
Model %90 confidence verdi
         ↓
Gerçekten %90 mı gerçekleşti?
         ↓
Calibration curve çiz
         ↓
Overconfident mi? Underconfident mi?
         ↓
Gerekirse confidence'ı ayarla
```

---

## 2. Bizde Şu An Ne Var?

### 2.1 Modül Özeti (7 dosya, 2,309 satır)

| Modül | Satır | Ne Yapıyor | Durum |
|-------|-------|------------|-------|
| `super_intelligence.py` | 621 | Self-healing, auto-retrain, A/B test, drift, meta-learning | ✅ En kapsamlı |
| `continuous_learning.py` | 386 | Günlük pipeline, drift check, retrain kararı | ✅ İyi |
| `main.py` | 346 | Learning service, training loop, outcome tracking | ✅ İyi |
| `integrated_learning.py` | 329 | Prediction/outcome tracking, regime accuracy | ✅ İyi |
| `attribution.py` | 274 | İşlem atfedilmesi (neden kazandı/kaybetti) | ✅ İyi |
| `outcome_tracker.py` | 181 | Otomatik outcome takibi | ✅ İyi |
| `learning_loop.py` | 172 | Otonom öğrenme döngüsü, model decay | ✅ İyi |

### 2.2 Mevcut Özellikler

| Özellik | Var mı? | Kalite |
|---------|---------|--------|
| Prediction tracking | ✅ | İyi |
| Outcome tracking | ✅ | İyi |
| Regime-based accuracy | ✅ | İyi |
| Attribution (neden kazandı/kaybetti) | ✅ | İyi |
| Drift detection | ✅ | ⚠️ Basit (Z-score) |
| Auto-retrain | ✅ | ⚠️ Tetikleme var, implementasyon eksik |
| A/B test | ✅ | ⚠️ Yapı var, gerçek test yok |
| Champion-challenger | ✅ | ⚠️ Yapı var, otomatik yok |
| Meta-learning | ✅ | ⚠️ Basit |
| Self-healing | ✅ | ⚠️ Yapı var, gerçek healing yok |
| Calibration | ❌ | Yok |
| Walk-forward validation | ❌ | Yok |
| Shadow mode | ❌ | Yok |
| Feature importance tracking | ❌ | Yok |
| Model versioning (detaylı) | ⚠️ | Basit |
| Performance attribution (detaylı) | ⚠️ | Basit |

---

## 3. Eksikler (Kritik)

### 3.1 Calibration Yok

**Sorun:** Model %90 confidence veriyor ama gerçekten %90 mı gerçekleşiyor bilinmiyor.
**Etki:** Overconfident model → fazla risk → büyük kayıp
**Çözüm:** Calibration curve, Brier score, overconfidence detection

### 3.2 Walk-Forward Validation Yok

**Sorun:** Model eğitiliyor ama walk-forward ile doğrulanmıyor.
**Etki:** Overfitting riski → canlıda başarısızlık
**Çözüm:** Rolling window walk-forward, purge/embargo

### 3.3 Shadow Mode Yok

**Sorun:** Yeni model doğrudan production'a alınıyor.
**Etki:** Yeni model kötüyse → tüm portföy etkilenir
**Çözüm:** Shadow mode (paralel çalıştır, sonuçları karşılaştır)

### 3.4 Drift Detection Basit

**Sorun:** Sadece Z-score ile drift tespiti — PSI, KS test yok
**Etki:** Drift geç tespit edilir
**Çözüm:** PSI, KS test, Page-Hinkley test, ADWIN

### 3.5 Auto-Retrain Implementasyonu Eksik

**Sorun:** Retrain tetikleme var ama gerçek eğitim yok
**Etki:** Model güncellenmiyor
**Çözüm:** Ranking model ile entegre auto-retrain

### 3.6 Feature Importance Tracking Yok

**Sorun:** Hangi feature'ın en önemli olduğu takip edilmiyor
**Etki:** Gereksiz feature'lar kullanılıyor, önemli olanlar kaçırılıyor
**Çözüm:** SHAP-based feature importance tracking

### 3.7 Performance Attribution (Detaylı) Yok

**Sorun:** Sadece basit attribution — factor-based attribution yok
**Etki:** Neden kazandı/kaybetti detaylı anlaşılamıyor
**Çözüm:** Factor-based attribution (momentum, value, quality, macro katkısı)

---

## 4. Nihai Learning Mimarisi

### 4.1 Learning Pipeline (Nihai)

```
┌─────────────────────────────────────────────────────────────┐
│                    LEARNING PIPELINE                         │
│                                                             │
│  ┌─────────────────────────────────────────────────────┐   │
│  │              PREDICTION TRACKING                     │   │
│  │  - Her tahmin kaydedilir                             │   │
│  │  - Ticker, direction, confidence, regime, features   │   │
│  │  - Horizon: 1D, 5D, 20D, 60D                        │   │
│  └─────────────────────────┬───────────────────────────┘   │
│                            ↓                                │
│  ┌─────────────────────────────────────────────────────┐   │
│  │              OUTCOME TRACKING                        │   │
│  │  - Otomatik fiyat takibi                             │   │
│  │  - Horizon dolduğunda outcome kaydet                 │   │
│  │  - TP/SL/EXPIRED sınıflandırma                      │   │
│  └─────────────────────────┬───────────────────────────┘   │
│                            ↓                                │
│  ┌─────────────────────────────────────────────────────┐   │
│  │              ATTRIBUTION                             │   │
│  │  - Neden kazandı/kaybetti?                           │   │
│  │  - Macro, momentum, event, regime, technical katkı   │   │
│  │  - Residual (açıklanamayan kısım)                    │   │
│  │  - Dersler (what worked, what failed)                │   │
│  └─────────────────────────┬───────────────────────────┘   │
│                            ↓                                │
│  ┌─────────────────────────────────────────────────────┐   │
│  │              PERFORMANCE MONITORING                  │   │
│  │  - Regime bazlı doğruluk                             │   │
│  │  - Feature importance tracking                       │   │
│  │  - Model decay detection                             │   │
│  │  - Calibration curve                                 │   │
│  │  - Brier score                                       │   │
│  └─────────────────────────┬───────────────────────────┘   │
│                            ↓                                │
│  ┌─────────────────────────────────────────────────────┐   │
│  │              DRIFT DETECTION                         │   │
│  │  - Data drift (feature dağılımı değişti)             │   │
│  │  - Concept drift (feature-target ilişki değişti)     │   │
│  │  - Prediction drift (model çıktı dağılımı değişti)   │   │
│  │  - PSI, KS test, Z-score, Page-Hinkley              │   │
│  └─────────────────────────┬───────────────────────────┘   │
│                            ↓                                │
│  ┌─────────────────────────────────────────────────────┐   │
│  │              RETRAIN DECISION                        │   │
│  │  - Sharpe < 0.3 → retrain                            │   │
│  │  - Win rate < 45% → retrain                          │   │
│  │  - Drift detected → retrain                          │   │
│  │  - Max interval exceeded → retrain                   │   │
│  │  - Manual trigger → retrain                          │   │
│  └─────────────────────────┬───────────────────────────┘   │
│                            ↓                                │
│  ┌─────────────────────────────────────────────────────┐   │
│  │              MODEL LIFECYCLE                         │   │
│  │                                                      │   │
│  │  ┌──────────┐  ┌──────────┐  ┌──────────┐          │   │
│  │  │  TRAIN   │→ │ VALIDATE │→ │ BACKTEST │          │   │
│  │  └──────────┘  └──────────┘  └──────────┘          │   │
│  │       ↓                                              │   │
│  │  ┌──────────┐  ┌──────────┐  ┌──────────┐          │   │
│  │  │WALK-FWD  │→ │  SHADOW  │→ │  CANARY  │          │   │
│  │  └──────────┘  └──────────┘  └──────────┘          │   │
│  │       ↓                                              │   │
│  │  ┌──────────┐  ┌──────────┐                         │   │
│  │  │ CHAMPION │→ │  MONITOR │                         │   │
│  │  └──────────┘  └──────────┘                         │   │
│  └─────────────────────────┬───────────────────────────┘   │
│                            ↓                                │
│  ┌─────────────────────────────────────────────────────┐   │
│  │              A/B TESTING                             │   │
│  │  - Champion vs Challenger                            │   │
│  │  - Welch's t-test (p < 0.05)                        │   │
│  │  - Sharpe comparison                                 │   │
│  │  - IC comparison                                     │   │
│  │  - Automatic promotion/rejection                     │   │
│  └─────────────────────────┬───────────────────────────┘   │
│                            ↓                                │
│  ┌─────────────────────────────────────────────────────┐   │
│  │              META-LEARNING                           │   │
│  │  - Hangi model hangi rejimde daha iyi?              │   │
│  │  - Rejim değişince model seçimi                      │   │
│  │  - Feature importance trendleri                      │   │
│  │  - Regime-specific model selection                   │   │
│  └─────────────────────────┬───────────────────────────┘   │
│                            ↓                                │
│  ┌─────────────────────────────────────────────────────┐   │
│  │              SELF-HEALING                            │   │
│  │  - Hata tespit → otomatik onarım                    │   │
│  │  - Model çöktü → fallback                           │   │
│  │  - Veri bozuldu → refresh                           │   │
│  │  - Timeout → retry with backoff                     │   │
│  └─────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────┘
```

### 4.2 Calibration (Nihai)

```python
class ConfidenceCalibrator:
    """Model confidence kalibrasyonu."""
    
    def calibrate(self, predictions: List[Dict], outcomes: List[Dict]) -> Dict:
        """Calibration curve hesapla."""
        # Prediction'ları confidence'a göre grupla
        bins = np.linspace(0, 1, 11)
        calibration = []
        
        for i in range(len(bins) - 1):
            mask = (pred_confidence >= bins[i]) & (pred_confidence < bins[i+1])
            if mask.sum() > 0:
                bin_mean_pred = pred_confidence[mask].mean()
                bin_mean_actual = outcomes[mask].mean()
                calibration.append({
                    "bin": f"{bins[i]:.1f}-{bins[i+1]:.1f}",
                    "predicted": round(bin_mean_pred, 4),
                    "actual": round(bin_mean_actual, 4),
                    "count": int(mask.sum()),
                    "miscalibration": round(abs(bin_mean_pred - bin_mean_actual), 4),
                })
        
        # Brier score
        brier = np.mean((pred_confidence - outcomes) ** 2)
        
        # Overconfidence tespit
        overconfident = any(c["miscalibration"] > 0.1 for c in calibration)
        
        return {
            "calibration": calibration,
            "brier_score": round(float(brier), 4),
            "overconfident": overconfident,
            "suggested_adjustment": self._suggest_adjustment(calibration),
        }
    
    def _suggest_adjustment(self, calibration: List[Dict]) -> float:
        """Confidence ayarlaması öner."""
        # Overconfident ise confidence'ı düşür
        avg_miscal = np.mean([c["miscalibration"] for c in calibration])
        if avg_miscal > 0.1:
            return -avg_miscal  # Confidence'ı düşür
        return 0
```

### 4.3 Drift Detection (Nihai — Çoklu Yöntem)

```python
class AdvancedDriftDetector:
    """Gelişmiş drift tespiti — çoklu yöntem."""
    
    def detect_all_drift(self, historical: np.ndarray, current: np.ndarray) -> Dict:
        """Tüm drift türlerini tespit et."""
        results = {}
        
        # 1. PSI (Population Stability Index)
        results["psi"] = self._compute_psi(historical, current)
        
        # 2. KS Test (Kolmogorov-Smirnov)
        from scipy import stats
        ks_stat, ks_p = stats.ks_2samp(historical, current)
        results["ks_statistic"] = round(float(ks_stat), 4)
        results["ks_p_value"] = round(float(ks_p), 4)
        
        # 3. Z-score
        hist_mean = np.mean(historical)
        hist_std = np.std(historical)
        curr_mean = np.mean(current)
        z_score = abs(curr_mean - hist_mean) / max(hist_std, 0.001)
        results["z_score"] = round(float(z_score), 4)
        
        # 4. Page-Hinkley test
        results["page_hinkley"] = self._page_hinkley_test(historical, current)
        
        # 5. ADWIN (Adaptive Windowing)
        results["adwin"] = self._adwin_test(historical, current)
        
        # Genel drift kararı
        drift_detected = (
            results["psi"] > 0.2 or
            results["ks_p_value"] < 0.05 or
            results["z_score"] > 3.0 or
            results["page_hinkley"]["drift"] or
            results["adwin"]["drift"]
        )
        
        results["drift_detected"] = drift_detected
        results["drift_type"] = self._classify_drift(results)
        
        return results
    
    def _compute_psi(self, expected: np.ndarray, actual: np.ndarray, bins: int = 10) -> float:
        """Population Stability Index."""
        # Histogram hesapla
        breakpoints = np.percentile(expected, np.linspace(0, 100, bins + 1))
        expected_counts = np.histogram(expected, breakpoints)[0] / len(expected)
        actual_counts = np.histogram(actual, breakpoints)[0] / len(actual)
        
        # Sıfır bölme önleme
        expected_counts = np.clip(expected_counts, 0.001, None)
        actual_counts = np.clip(actual_counts, 0.001, None)
        
        # PSI hesapla
        psi = np.sum((actual_counts - expected_counts) * np.log(actual_counts / expected_counts))
        return round(float(psi), 4)
    
    def _page_hinkley_test(self, historical: np.ndarray, current: np.ndarray) -> Dict:
        """Page-Hinkley drift testi."""
        # Kümülatif sapma hesapla
        all_data = np.concatenate([historical, current])
        mean_all = np.mean(all_data)
        cumulative = np.cumsum(all_data - mean_all)
        
        # En büyük sapma
        max_deviation = np.max(np.abs(cumulative))
        threshold = len(all_data) * 0.5  # Basit eşik
        
        return {
            "drift": max_deviation > threshold,
            "max_deviation": round(float(max_deviation), 4),
            "threshold": round(float(threshold), 4),
        }
    
    def _adwin_test(self, historical: np.ndarray, current: np.ndarray) -> Dict:
        """ADWIN (Adaptive Windowing) drift testi."""
        # Pencere boyutu adaptif olarak değişir
        window_size = max(len(current) // 4, 10)
        
        if len(current) < window_size * 2:
            return {"drift": False, "reason": "Insufficient data"}
        
        # İlk ve son pencere karşılaştır
        first_window = current[:window_size]
        last_window = current[-window_size:]
        
        from scipy import stats
        t_stat, p_value = stats.ttest_ind(first_window, last_window)
        
        return {
            "drift": p_value < 0.05,
            "t_statistic": round(float(t_stat), 4),
            "p_value": round(float(p_value), 4),
            "window_size": window_size,
        }
    
    def _classify_drift(self, results: Dict) -> str:
        """Drift türünü sınıflandır."""
        if results["psi"] > 0.5:
            return "MAJOR_DATA_DRIFT"
        elif results["ks_p_value"] < 0.01:
            return "SIGNIFICANT_DISTRIBUTION_SHIFT"
        elif results["z_score"] > 5:
            return "EXTREME_OUTLIER"
        elif results["page_hinkley"]["drift"]:
            return "GRADUAL_DRIFT"
        elif results["adwin"]["drift"]:
            return "SUDDEN_SHIFT"
        else:
            return "MINOR_DRIFT"
```

### 4.4 Shadow Mode (Nihai)

```python
class ShadowModeManager:
    """Shadow mode — yeni model eski modelle paralel çalışır."""
    
    def __init__(self):
        self._shadow_active = False
        self._champion_model = None
        self._challenger_model = None
        self._champion_predictions = []
        self._challenger_predictions = []
    
    def start_shadow(self, champion, challenger, duration_days: int = 21):
        """Shadow mode başlat."""
        self._shadow_active = True
        self._champion_model = champion
        self._challenger_model = challenger
        self._champion_predictions = []
        self._challenger_predictions = []
        
        logger.info("Shadow mode started", duration=duration_days)
    
    def record_prediction(self, features: Dict, ticker: str):
        """Her iki modelden prediction kaydet."""
        if not self._shadow_active:
            return
        
        champion_pred = self._champion_model.predict(features)
        challenger_pred = self._challenger_model.predict(features)
        
        self._champion_predictions.append({
            "ticker": ticker,
            "prediction": champion_pred,
            "timestamp": datetime.now().isoformat(),
        })
        self._challenger_predictions.append({
            "ticker": ticker,
            "prediction": challenger_pred,
            "timestamp": datetime.now().isoformat(),
        })
    
    def evaluate(self, actual_returns: Dict[str, float]) -> Dict:
        """Shadow mode sonuçlarını değerlendir."""
        champion_metrics = self._calculate_metrics(self._champion_predictions, actual_returns)
        challenger_metrics = self._calculate_metrics(self._challenger_predictions, actual_returns)
        
        improvement = (challenger_metrics["sharpe"] - champion_metrics["sharpe"]) / max(abs(champion_metrics["sharpe"]), 0.001)
        
        return {
            "champion": champion_metrics,
            "challenger": challenger_metrics,
            "improvement_pct": round(improvement * 100, 2),
            "recommendation": "PROMOTE" if improvement > 0.1 else "REJECT",
        }
```

### 4.5 Feature Importance Tracking (Nihai)

```python
class FeatureImportanceTracker:
    """Feature importance zaman içinde takip et."""
    
    def __init__(self):
        self._history = []  # {date, feature, importance, model_version}
    
    def track(self, model, feature_names: List[str], X: np.ndarray, date: str):
        """Feature importance kaydet."""
        try:
            import shap
            explainer = shap.TreeExplainer(model)
            shap_values = explainer.shap_values(X)
            importance = np.abs(shap_values).mean(axis=0)
        except:
            importance = model.feature_importances_
        
        for name, imp in zip(feature_names, importance):
            self._history.append({
                "date": date,
                "feature": name,
                "importance": round(float(imp), 6),
            })
    
    def get_trends(self, top_n: int = 20) -> Dict:
        """Feature importance trendleri."""
        # Son 30 günün ortalaması
        recent = [h for h in self._history if h["date"] > (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")]
        
        feature_avg = {}
        for h in recent:
            if h["feature"] not in feature_avg:
                feature_avg[h["feature"]] = []
            feature_avg[h["feature"]].append(h["importance"])
        
        trends = {}
        for feature, values in feature_avg.items():
            trends[feature] = {
                "avg_importance": round(np.mean(values), 6),
                "trend": "increasing" if len(values) > 1 and values[-1] > values[0] else "decreasing",
            }
        
        return dict(sorted(trends.items(), key=lambda x: x[1]["avg_importance"], reverse=True)[:top_n])
```

---

## 5. Rakip Karşılaştırması

### 5.1 MLOps Best Practices (Databricks)

| Özellik | Databricks | Bizim Sistem | Fark |
|---------|-----------|-------------|------|
| Model Registry | ✅ MLflow | ⚠️ Basit | ⚠️ |
| Feature Store | ✅ Feature Store | ⚠️ Basit | ⚠️ |
| Model Monitoring | ✅ Auto | ⚠️ Manuel | ⚠️ |
| A/B Testing | ✅ Built-in | ⚠️ Yapı var | ⚠️ |
| Drift Detection | ✅ Auto | ⚠️ Basit | ⚠️ |
| Auto-retrain | ✅ Pipeline | ⚠️ Tetikleme var | ⚠️ |

### 5.2 Aerospike Model Drift (2025)

| Özellik | Aerospike Önerisi | Bizim Sistem | Fark |
|---------|-------------------|-------------|------|
| PSI monitoring | ✅ | ❌ | ❌ |
| KS test | ✅ | ❌ | ❌ |
| Concept drift | ✅ | ⚠️ Basit | ⚠️ |
| Retrain strategy | ✅ Scheduled + triggered | ⚠️ Triggered only | ⚠️ |
| Shadow deployment | ✅ | ❌ | ❌ |

### 5.3 Shadow Before Swap (arXiv, 2026)

| Özellik | SBS Önerisi | Bizim Sistem | Fark |
|---------|-------------|-------------|------|
| Shadow mode | ✅ Warm-refit | ❌ | ❌ |
| Canary deployment | ✅ Küçük pozisyon | ❌ | ❌ |
| Automatic rollback | ✅ | ❌ | ❌ |
| Performance gate | ✅ Statistical test | ⚠️ Basit | ⚠️ |

---

## 6. Uygulama Planı

### Faz 1: Calibration (Hemen)
1. Confidence calibration curve
2. Brier score hesaplama
3. Overconfidence detection
4. Otomatik confidence ayarlama

### Faz 2: Gelişmiş Drift Detection (1 hafta)
1. PSI entegrasyonu
2. KS test entegrasyonu
3. Page-Hinkley test
4. ADWIN test
5. Drift type sınıflandırma

### Faz 3: Shadow Mode (1 hafta)
1. Shadow mode manager
2. Paralel prediction kaydetme
3. Otomatik karşılaştırma
4. Promote/reject kararı

### Faz 4: Walk-Forward Validation (1 hafta)
1. Rolling window walk-forward
2. Purge/embargo entegrasyonu
3. Out-of-sample test
4. Deflated Sharpe hesaplama

### Faz 5: Feature Importance Tracking (1 hafta)
1. SHAP-based tracking
2. Zaman içinde trend
3. Regime bazlı importance
4. Feature selection improvements

### Faz 6: Meta-Learning Enhancement (1 hafta)
1. Regime-specific model selection
2. Factor-based model routing
3. Dynamic ensemble weights
4. Performance decay prediction

---

## 7. Mevcut Sistem vs Nihai Vizyon

| Özellik | Mevcut | Hedef |
|---------|--------|-------|
| Modül sayısı | 7 | 12 |
| Toplam satır | 2,309 | ~4,000 |
| Prediction tracking | ✅ | ✅ |
| Outcome tracking | ✅ | ✅ |
| Attribution | ✅ | ✅ Detaylı |
| Drift detection | ⚠️ Basit | ✅ PSI+KS+PH+ADWIN |
| Calibration | ❌ | ✅ |
| Shadow mode | ❌ | ✅ |
| Walk-forward validation | ❌ | ✅ |
| A/B test | ⚠️ Yapı var | ✅ Otomatik |
| Champion-challenger | ⚠️ Yapı var | ✅ Otomatik |
| Auto-retrain | ⚠️ Tetikleme var | ✅ Tam otomatik |
| Feature importance | ❌ | ✅ SHAP tracking |
| Meta-learning | ⚠️ Basit | ✅ Regime-specific |
| Self-healing | ⚠️ Yapı var | ✅ Gerçek healing |
| Model versioning | ⚠️ Basit | ✅ Detaylı |
| Performance decay | ❌ | ✅ |
| Confidence adjustment | ❌ | ✅ Otomatik |
