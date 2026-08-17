# Intelligence Nihai Sistem Dokümanı — Kod Analizi + Araştırma Bazlı

**Tarih:** 2026-08-18
**Kaynaklar:** arXiv Agentic Trading (2026), MDPI Regime-Aware LightGBM (2026), ScienceDirect Non-stationarity Survey (2026), TradingAgents (TauricResearch 2025), Aladdin (BlackRock), ICUQF Monte Carlo Fusion (2026), ACM LLM Agents Investment (2026)

---

## 1. Mevcut Durum (Kod Analizi)

### Modüller (23 dosya, toplam 7,527 satır)

| Modül | Satır | Class | Fonksiyon | Durum |
|-------|-------|-------|-----------|-------|
| `pipeline.py` | 517 | 2 | 21 | ✅ Ana pipeline |
| `trade_planner.py` | 492 | 2 | 14 | ✅ İşlem planı |
| `main.py` | 465 | 1 | 2 | ✅ Intelligence service |
| `kap_llm_extractor.py` | 354 | 3 | 12 | ✅ KAP LLM analizi |
| `analysis_engines.py` | 358 | 11 | 12 | ✅ 11 analiz motoru |
| `regime.py` | 357 | 3 | 17 | ✅ Rejim tespiti |
| `spec_engine.py` | 341 | 3 | 11 | ✅ SPEC skor |
| `evidence_engine.py` | 336 | 6 | 8 | ✅ Kanıt doğrulama |
| `monte_carlo.py` | 320 | 3 | 3 | ✅ Monte Carlo |
| `scenario.py` | 313 | 6 | 4 | ✅ Senaryo analizi |
| `kap_extractor.py` | 296 | 3 | 7 | ✅ KAP çıkarma |
| `impact_engine.py` | 291 | 3 | 4 | ✅ Etki analizi |
| `world_state.py` | 294 | 2 | 10 | ✅ World state |
| `factor_engine.py` | 288 | 3 | 8 | ✅ Faktör motoru |
| `signal_fusion.py` | 281 | 2 | 6 | ✅ Sinyal birleştirme |
| `probability.py` | 272 | 4 | 4 | ✅ Olasılık motoru |
| `news_pipeline.py` | 254 | 2 | 7 | ✅ Haber pipeline |
| `forecasting.py` | 250 | 6 | 11 | ✅ Tahmin motoru |
| `macro_sensitivity.py` | 208 | 1 | 6 | ✅ Makro duyarlılık |
| `knowledge_graph.py` | 216 | 3 | 10 | ✅ Bilgi grafiği |
| `prediction_layer.py` | 165 | 1 | 3 | ⚠️ Basit |
| `research_memory.py` | 163 | 5 | 9 | ✅ Araştırma hafızası |
| `engine.py` | 351 | 5 | 5 | ✅ Valuation engine |

### Motor Dağılımı

| Motor | Modül | Durum |
|-------|-------|-------|
| **Regime Detection** | regime.py | ✅ 11 rejim, skor bazlı |
| **Signal Fusion** | signal_fusion.py | ✅ Rejime göre ağırlık |
| **SPEC Engine** | spec_engine.py | ✅ Anomaly, evidence, regime |
| **Monte Carlo** | monte_carlo.py | ✅ GBM simulation |
| **Forecasting** | forecasting.py | ✅ Multi-horizon |
| **Probability** | probability.py | ✅ Return distribution |
| **Scenario** | scenario.py | ✅ Macro shocks |
| **Trade Planner** | trade_planner.py | ✅ Entry/stop/target |
| **Evidence** | evidence_engine.py | ✅ Hallucination detection |
| **Knowledge Graph** | knowledge_graph.py | ✅ Entity/relation |
| **Research Memory** | research_memory.py | ✅ Lineage tracking |
| **Analysis Engines** | analysis_engines.py | ✅ 11 motor |
| **Impact Engine** | impact_engine.py | ✅ Event impact |
| **KAP Extractor** | kap_extractor.py | ✅ KAP parsing |
| **KAP LLM** | kap_llm_extractor.py | ✅ LLM destekli |
| **Macro Sensitivity** | macro_sensitivity.py | ✅ Sektör duyarlılık |
| **World State** | world_state.py | ✅ Factor bazlı decay |
| **Factor Engine** | factor_engine.py | ✅ Fama-French |
| **News Pipeline** | news_pipeline.py | ✅ Haber işleme |
| **Prediction Layer** | prediction_layer.py | ⚠️ Basit |
| **Pipeline** | pipeline.py | ✅ 21 modül orkestrasyon |

---

## 2. Sorunlar (Kod Analizi)

### 2.1 Regime Detection — HMM Yok

**Mevcut:** Skor bazlı rejim tespiti (11 rejim)
**Sorun:** HMM (Hidden Markov Model) yok — matematiksel rejim tespiti eksik
**Kaynak:** MDPI Regime-Aware LightGBM (2026) — Rolling HMM her 63 günde yeniden eğitiliyor

### 2.2 Signal Fusion — Sabit Ağırlıklar

**Mevcut:** Rejime göre ağırlık değişimi var ama çok basit
**Sorun:** ML-optimized ağırlık yok, factor-based weighting yok
**Kaynak:** TradingAgents — Research Manager agent'ları kendi aralarında tartışıp karar veriyor

### 2.3 Monte Carlo — Basit GBM

**Mevcut:** Geometric Brownian Motion ile simülasyon
**Sorun:** Jump-diffusion, stochastic volatility, fat tails yok
**Kaynak:** ICUQF (2026) — Monte Carlo + fuzzy logic + Bayesian inference birleşimi

### 2.4 Forecasting — Ensemble Zayıf

**Mevcut:** Tek model forecasting
**Sorun:** Gerçek ensemble (çoklu model birleşimi) eksik
**Kaynak:** Regime-Aware LightGBM — rejime göre model seçimi

### 2.5 Probability — Calibration Yok

**Mevcut:** Return distribution hesaplama var
**Sorun:** Confidence calibration yok — model %90 dese gerçek %60 olabilir
**Kaynak:** Wiley Probabilistic AI Forecasting (2025)

### 2.6 Evidence Engine — LLM Entegrasyonu Zayıf

**Mevcut:** Claim extraction ve verification var
**Sorun:** Gerçek LLM entegrasyonu yok (sadece kural tabanlı)
**Kaynak:** arXiv FinGround (2026) — Financial hallucination detection

### 2.7 Pipeline — Paralel Çalışma Yok

**Mevcut:** 21 modül sırasıyla çalıştırılıyor
**Sorun:** Paralel çalışma yok — bazı modüller birbirinden bağımsız çalışabilir
**Kaynak:** TradingAgents — agent'lar paralel çalışıp sonuçları birleştiriyor

### 2.8 Prediction Layer — Çok Basit

**Mevcut:** 165 satır, tek Prediction class
**Sorun:** Multi-horizon, multi-model prediction yok

---

## 3. Nihai Intelligence Mimarisi (Araştırma Bazlı)

### 3.1 Intelligence Pipeline (Nihai)

```
┌─────────────────────────────────────────────────────────────┐
│                    INTELLIGENCE PIPELINE                     │
│                                                             │
│  ┌─────────────────────────────────────────────────────┐   │
│  │              DATA LAYER                              │   │
│  │  Features + Market Data + News + KAP + Macro         │   │
│  └─────────────────────────┬───────────────────────────┘   │
│                            ↓                                │
│  ┌─────────────────────────────────────────────────────┐   │
│  │              PARALLEL ANALYSIS                       │   │
│  │                                                      │   │
│  │  ┌──────────┐  ┌──────────┐  ┌──────────┐          │   │
│  │  │ Regime   │  │ World    │  │ Macro    │          │   │
│  │  │ Detection│  │ State    │  │ Sensitiv.│          │   │
│  │  │ (HMM)    │  │ Manager  │  │ Engine   │          │   │
│  │  └──────────┘  └──────────┘  └──────────┘          │   │
│  │                                                      │   │
│  │  ┌──────────┐  ┌──────────┐  ┌──────────┐          │   │
│  │  │ Technical│  │Fundament.│  │ Sentiment│          │   │
│  │  │ Analysis │  │ Analysis │  │ Analysis │          │   │
│  │  └──────────┘  └──────────┘  └──────────┘          │   │
│  │                                                      │   │
│  │  ┌──────────┐  ┌──────────┐  ┌──────────┐          │   │
│  │  │ KAP/News │  │ Factor   │  │ Evidence │          │   │
│  │  │ Analysis │  │ Engine   │  │ Verify   │          │   │
│  │  └──────────┘  └──────────┘  └──────────┘          │   │
│  └─────────────────────────┬───────────────────────────┘   │
│                            ↓                                │
│  ┌─────────────────────────────────────────────────────┐   │
│  │              ENSEMBLE FORECASTING                    │   │
│  │                                                      │   │
│  │  ┌──────────┐  ┌──────────┐  ┌──────────┐          │   │
│  │  │LightGBM  │  │XGBoost   │  │ LSTM     │          │   │
│  │  │Forecast  │  │Forecast  │  │ Forecast │          │   │
│  │  └──────────┘  └──────────┘  └──────────┘          │   │
│  │                                                      │   │
│  │  ┌──────────┐  ┌──────────┐  ┌──────────┐          │   │
│  │  │Statistical│ │ LLM      │  │ Monte    │          │   │
│  │  │Forecast  │  │ Analysis │  │ Carlo    │          │   │
│  │  └──────────┘  └──────────┘  └──────────┘          │   │
│  │                                                      │   │
│  │  → Ensemble Weighting (rejime göre)                  │   │
│  └─────────────────────────┬───────────────────────────┘   │
│                            ↓                                │
│  ┌─────────────────────────────────────────────────────┐   │
│  │              PROBABILITY & CALIBRATION               │   │
│  │  - Return distribution                               │   │
│  │  - Confidence calibration                            │   │
│  │  - Hit rate tracking                                 │   │
│  │  - Brier score                                       │   │
│  └─────────────────────────┬───────────────────────────┘   │
│                            ↓                                │
│  ┌─────────────────────────────────────────────────────┐   │
│  │              SCENARIO & STRESS TEST                  │   │
│  │  - Macro shock scenarios                             │   │
│  │  - Breaking point analysis                           │   │
│  │  - Portfolio impact                                  │   │
│  └─────────────────────────┬───────────────────────────┘   │
│                            ↓                                │
│  ┌─────────────────────────────────────────────────────┐   │
│  │              SIGNAL FUSION (Nihai)                   │   │
│  │                                                      │   │
│  │  ┌──────────────────────────────────────────────┐   │   │
│  │  │ Conflict Detection                            │   │   │
│  │  │ - Technical: LONG, Fundamental: SHORT → ALERT │   │   │
│  │  └──────────────────────────────────────────────┘   │   │
│  │                                                      │   │
│  │  ┌──────────────────────────────────────────────┐   │   │
│  │  │ Regime-Based Weighting                        │   │   │
│  │  │ - BULL: momentum=0.30, value=0.10             │   │   │
│  │  │ - BEAR: quality=0.30, low_vol=0.20            │   │   │
│  │  └──────────────────────────────────────────────┘   │   │
│  │                                                      │   │
│  │  ┌──────────────────────────────────────────────┐   │   │
│  │  │ ML-Optimized Weights                          │   │   │
│  │  │ - SHAP importance → dynamic weights           │   │   │
│  │  │ - Regime-specific optimization                │   │   │
│  │  └──────────────────────────────────────────────┘   │   │
│  │                                                      │   │
│  │  ┌──────────────────────────────────────────────┐   │   │
│  │  │ Self-Check                                    │   │   │
│  │  │ - Confidence too high? → reduce               │   │   │
│  │  │ - Data stale? → reduce                        │   │   │
│  │  │ - Sources conflicting? → flag                 │   │   │
│  │  └──────────────────────────────────────────────┘   │   │
│  └─────────────────────────┬───────────────────────────┘   │
│                            ↓                                │
│  ┌─────────────────────────────────────────────────────┐   │
│  │              SPEC ENGINE (Nihai)                     │   │
│  │  - Anomaly score                                     │   │
│  │  - Evidence consensus                                │   │
│  │  - Regime compatibility                              │   │
│  │  - Expected value                                    │   │
│  │  - Risk asymmetry                                    │   │
│  │  - Historical similarity                             │   │
│  │  - Penalty factors                                   │   │
│  │  → Final SPEC score (0-100)                          │   │
│  └─────────────────────────┬───────────────────────────┘   │
│                            ↓                                │
│  ┌─────────────────────────────────────────────────────┐   │
│  │              TRADE PLANNER                           │   │
│  │  - Action (BUY/SELL/HOLD/NO_TRADE)                   │   │
│  │  - Entry price & type                                │   │
│  │  - Stop loss                                         │   │
│  │  - Target prices (3 seviye)                          │   │
│  │  - Position size                                     │   │
│  │  - Holding period                                    │   │
│  │  - Risk/reward ratio                                 │   │
│  │  - Bull/Base/Bear scenarios                          │   │
│  └─────────────────────────┬───────────────────────────┘   │
│                            ↓                                │
│  ┌─────────────────────────────────────────────────────┐   │
│  │              KNOWLEDGE GRAPH + MEMORY                │   │
│  │  - Entity relationships                              │   │
│  │  - Impact propagation                                │   │
│  │  - Research history                                  │   │
│  │  - Data lineage                                      │   │
│  └─────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────┘
```

### 3.2 Regime Detection (Nihai — HMM)

```python
class HMMRegimeDetector:
    """Hidden Markov Model ile rejim tespiti."""
    
    def __init__(self, n_regimes: int = 4):
        self.n_regimes = n_regimes
        self._model = None
    
    def fit(self, returns: np.ndarray, volatility: np.ndarray):
        """HMM modelini eğit (rolling window)."""
        try:
            from hmmlearn.hmm import GaussianHMM
            X = np.column_stack([returns, volatility])
            self._model = GaussianHMM(n_components=self.n_regimes, covariance_type="full")
            self._model.fit(X)
        except ImportError:
            logger.warning("hmmlearn not installed, using rule-based detection")
    
    def predict_regime(self, returns: np.ndarray, volatility: np.ndarray) -> Dict:
        """Mevcut rejimi tahmin et."""
        if self._model is None:
            return {"regime": "UNKNOWN", "confidence": 0}
        
        X = np.array([[returns[-1], volatility[-1]]])
        regime = self._model.predict(X)[0]
        probs = self._model.predict_proba(X)[0]
        
        regime_names = ["BULL", "BEAR", "HIGH_VOL", "LOW_VOL"]
        return {
            "regime": regime_names[regime] if regime < len(regime_names) else "UNKNOWN",
            "confidence": float(probs[regime]),
            "probabilities": {name: float(prob) for name, prob in zip(regime_names, probs)},
        }
    
    def rolling_detect(self, returns: np.ndarray, volatility: np.ndarray,
                       window: int = 63) -> List[Dict]:
        """Rolling rejim tespiti (her 63 günde yeniden eğit)."""
        results = []
        for i in range(window, len(returns)):
            train_returns = returns[i-window:i]
            train_vol = volatility[i-window:i]
            self.fit(train_returns, train_vol)
            result = self.predict_regime(
                returns[i-window:i+1],
                volatility[i-window:i+1]
            )
            results.append(result)
        return results
```

### 3.3 Signal Fusion (Nihai — ML-Optimized)

```python
class MLSignalFusion:
    """ML-optimized sinyal birleştirme."""
    
    def __init__(self):
        self._weight_models = {}  # regime → model
    
    def optimize_weights(self, historical_signals: List[Dict],
                         historical_outcomes: List[float],
                         regime: str) -> Dict[str, float]:
        """SHAP importance ile optimal ağırlıkları bul."""
        try:
            import shap
            from sklearn.ensemble import GradientBoostingRegressor
            
            # Feature matrix: her sinyal bir feature
            X = np.array([[s.get(component, 0) for component in [
                "technical", "fundamental", "momentum", "sentiment",
                "macro", "valuation", "ai"
            ]] for s in historical_signals])
            y = np.array(historical_outcomes)
            
            # Model eğit
            model = GradientBoostingRegressor(n_estimators=100)
            model.fit(X, y)
            
            # SHAP ile ağırlıkları çıkar
            explainer = shap.TreeExplainer(model)
            shap_values = explainer.shap_values(X)
            importance = np.abs(shap_values).mean(axis=0)
            
            # Normalize et
            total = importance.sum()
            weights = {
                component: float(imp / total)
                for component, imp in zip(
                    ["technical", "fundamental", "momentum", "sentiment",
                     "macro", "valuation", "ai"],
                    importance
                )
            }
            
            self._weight_models[regime] = weights
            return weights
            
        except ImportError:
            logger.warning("SHAP not installed, using default weights")
            return self.DEFAULT_WEIGHTS
```

### 3.4 Ensemble Forecasting (Nihai)

```python
class EnsembleForecast:
    """Çoklu model ensemble forecasting."""
    
    def __init__(self):
        self._models = {}
        self._performance = {}  # model → {accuracy, sharpe, ic}
    
    def register_model(self, name: str, model_fn: Callable):
        """Model kaydet."""
        self._models[name] = model_fn
    
    def forecast(self, features: Dict, horizon: int,
                 regime: str = "NORMAL") -> Dict:
        """Ensemble forecast."""
        forecasts = {}
        for name, model_fn in self._models.items():
            try:
                pred = model_fn(features, horizon)
                forecasts[name] = pred
            except Exception as e:
                logger.warning("Model failed", model=name, error=str(e))
        
        if not forecasts:
            return {"error": "All models failed"}
        
        # Rejime göre ağırlık
        weights = self._get_regime_weights(regime)
        
        # Ağırlıklı ortalama
        weighted_pred = 0
        total_weight = 0
        for name, pred in forecasts.items():
            w = weights.get(name, 1.0 / len(forecasts))
            weighted_pred += pred * w
            total_weight += w
        
        ensemble_pred = weighted_pred / total_weight if total_weight > 0 else 0
        
        # Model agreement (confidence)
        preds = list(forecasts.values())
        agreement = 1.0 - np.std(preds) / max(np.mean(np.abs(preds)), 0.001)
        
        return {
            "ensemble_prediction": round(ensemble_pred, 4),
            "model_predictions": forecasts,
            "agreement": round(max(min(agreement, 1.0), 0.0), 4),
            "n_models": len(forecasts),
            "regime": regime,
        }
```

### 3.5 Confidence Calibration (Nihai)

```python
class ConfidenceCalibrator:
    """Model confidence kalibrasyonu."""
    
    def calibrate(self, predictions: List[float], outcomes: List[float],
                  n_bins: int = 10) -> Dict:
        """Calibration curve hesapla."""
        bins = np.linspace(0, 1, n_bins + 1)
        calibration = []
        
        for i in range(n_bins):
            mask = (np.array(predictions) >= bins[i]) & (np.array(predictions) < bins[i+1])
            if mask.sum() > 0:
                bin_mean_pred = np.mean(np.array(predictions)[mask])
                bin_mean_actual = np.mean(np.array(outcomes)[mask])
                calibration.append({
                    "bin": f"{bins[i]:.1f}-{bins[i+1]:.1f}",
                    "mean_prediction": round(bin_mean_pred, 4),
                    "mean_actual": round(bin_mean_actual, 4),
                    "count": int(mask.sum()),
                    "miscalibration": round(abs(bin_mean_pred - bin_mean_actual), 4),
                })
        
        # Brier score
        brier = np.mean((np.array(predictions) - np.array(outcomes)) ** 2)
        
        return {
            "calibration": calibration,
            "brier_score": round(float(brier), 4),
            "overconfident": any(c["miscalibration"] > 0.1 for c in calibration),
            "n_samples": len(predictions),
        }
```

---

## 4. Rakip Karşılaştırması

### 4.1 TradingAgents (TauricResearch)

| Bileşen | TradingAgents | Bizim Sistem | Fark |
|---------|---------------|-------------|------|
| Research Manager | ✅ Agent debate | ✅ Signal fusion | Bizde debate yok |
| Trader | ✅ Structured output | ✅ Trade planner | ✅ Aynı |
| Risk Management | ✅ Risk guardians | ✅ Risk gate | ✅ Aynı |
| Portfolio Manager | ✅ Portfolio decisions | ✅ Portfolio service | ✅ Aynı |
| LangGraph Workflow | ✅ | ❌ Pipeline var | ⚠️ Basit |
| Checkpoint Resume | ✅ | ✅ Event replay | ✅ Aynı |

### 4.2 Aladdin (BlackRock)

| Bileşen | Aladdin | Bizim Sistem | Fark |
|---------|---------|-------------|------|
| Risk Analytics | ✅ VaR, stress test | ✅ Monte Carlo, scenario | ✅ Aynı |
| Portfolio Management | ✅ Real-time | ✅ Virtual portfolio | ⚠️ Paper only |
| Compliance | ✅ Automated | ✅ Compliance checker | ✅ Aynı |
| Data Management | ✅ Multi-source | ✅ Multi-provider | ✅ Aynı |
| AI/ML Layer | ✅ Proprietary | ✅ Multiple models | ✅ Aynı |
| Real-time | ✅ | ⚠️ Event-driven | ⚠️ Kısmen |

### 4.3 Regime-Aware LightGBM (MDPI, 2026)

| Bileşen | MDPI | Bizim Sistem | Fark |
|---------|------|-------------|------|
| Rolling HMM | ✅ 63 gün | ❌ | ❌ Eksik |
| Regime-aware model | ✅ | ⚠️ Basit | ⚠️ |
| Walk-forward | ✅ | ✅ | ✅ Aynı |
| Feature selection | ✅ SHAP | ⚠️ Basit | ⚠️ |

---

## 5. Uygulama Planı

### Faz 1: HMM Regime Detection (Hemen)
1. `hmmlearn` entegrasyonu
2. Rolling HMM (63 günde yeniden eğitim)
3. Regime probability outputs
4. Regime transition matrix

### Faz 2: ML Signal Fusion (1 hafta)
1. SHAP-based weight optimization
2. Regime-specific weights
3. Conflict detection improvements
4. Self-check mechanism

### Faz 3: Ensemble Forecasting (1 hafta)
1. Multi-model ensemble (LightGBM, XGBoost, LSTM)
2. Regime-based model selection
3. Model agreement scoring
4. Dynamic weight adjustment

### Faz 4: Confidence Calibration (1 hafta)
1. Calibration curve
2. Brier score
3. Overconfidence detection
4. Automatic confidence adjustment

### Faz 5: Parallel Pipeline (1 hafta)
1. asyncio.gather ile paralel çalışma
2. Bağımsız modülleri paralel çalıştır
3. Timeout management
4. Partial failure handling

### Faz 6: Advanced Monte Carlo (1 hafta)
1. Jump-diffusion model
2. Stochastic volatility
3. Fat tails (Student-t distribution)
4. Correlated paths

---

## 6. Mevcut Sistem vs Nihai Vizyon

| Özellik | Mevcut | Hedef |
|---------|--------|-------|
| Modül sayısı | 23 | 28 |
| Toplam satır | 7,527 | ~10,000 |
| Regime detection | ⚠️ Skor bazlı | ✅ HMM + skor |
| Signal fusion | ⚠️ Sabit ağırlık | ✅ ML-optimized |
| Monte Carlo | ⚠️ Basit GBM | ✅ Jump-diffusion |
| Forecasting | ⚠️ Tek model | ✅ Ensemble |
| Probability | ⚠️ Calibration yok | ✅ Calibration var |
| Evidence | ⚠️ Kural tabanlı | ✅ LLM destekli |
| Pipeline | ⚠️ Sıralı | ✅ Paralel |
| Prediction layer | ⚠️ Basit | ✅ Multi-horizon |
| Confidence | ⚠️ Sabit | ✅ Calibrated |
| Model agreement | ❌ | ✅ |
| Drift detection | ❌ | ✅ |
| Regime transition | ❌ | ✅ HMM-based |
