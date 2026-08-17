# Market State Nihai Sistem Dokümanı — Kod Analizi + Araştırma Bazlı

**Tarih:** 2026-08-18
**Kaynaklar:** Springer Regime-Aware Adaptive Forecasting (2026), arXiv Regime-Switching Models (2026), ScienceDirect Non-stationarity Survey (2026), Kaggle Market Regimes Clustering, Springer Risk Management HMM (2026)

---

## 1. Sektörde En İyi Uygulama Nedir?

### 1.1 Market State Engine (En İyi Uygulama)

**Temel prensip:** Piyasa durumu tek bir göstergeyle belirlenmez — çoklu sinyalin birleşimidir.

```
Market State = f(breadth, momentum, volatility, volume, RSI, regime, macro, sentiment)
```

**En İyi Uygulama Bileşenleri:**

| Bileşen | Ne | Nasıl |
|---------|-----|-------|
| **Market Breadth** | Yükselen/düşen hisse oranı | Advance-Decline Line |
| **Momentum** | Piyasa gücü | Ortalama momentum, ROC |
| **Volatility** | Piyasa stresi | Ortalama realized vol, VIX |
| **Volume** | Katılım seviyesi | Volume z-score, OBV |
| **RSI** | Aşırı alım/satım | Ortalama RSI |
| **Regime** | Piyasa rejimi | HMM, K-means, skor bazlı |
| **Macro** | Makro ortam | Faiz, enflasyon, döviz |
| **Sentiment** | Piyasa duyarlılığı | Haber, sosyal medya |

### 1.2 Regime Detection (En İyi Uygulama)

**3 Yaklaşım:**

| Yaklaşım | Avantaj | Dezavantaj | Kaynak |
|----------|---------|------------|--------|
| **HMM (Hidden Markov Model)** | Matematiksel, probabilistik | Parametre seçimi zor | Springer (2026) |
| **K-means Clustering** | Basit, hızlı | K seçimi subjective | Kaggle |
| **Skor Bazlı** | Yorumlanabilir, esnek | Eşikler subjective | Mevcut sistemimiz |

**En İyi Uygulama:** HMM + skor bazlı hibrit yaklaşım

### 1.3 Market State Bileşenleri (En İyi Uygulama)

```
MARKET STATE
├── Regime (BULL/BEAR/SIDEWAYS/HIGH_VOL/LOW_VOL/RISK_ON/RISK_OFF/CRISIS/RECOVERY)
├── Breadth (Advance-Decline Line, % advancing)
├── Momentum (Average momentum, ROC, trend strength)
├── Volatility (Average realized vol, VIX, vol regime)
├── Volume (Average volume z-score, participation)
├── RSI (Average RSI, overbought/oversold)
├── Liquidity (Spread, depth, market impact)
├── Sentiment (News sentiment, social sentiment, fear/greed)
├── Macro (Macro regime, macro sensitivity)
├── Anomaly (Anomaly count, anomaly severity)
└── Risk Appetite (Composite risk appetite score)
```

---

## 2. Bizde Şu An Ne Var?

### 2.1 services/market_state/main.py (354 satır) — MarketStateService

| Fonksiyon | Satır | Ne Yapıyor | Durum |
|-----------|-------|------------|-------|
| `__init__()` | 36-44 | Başlangıç state'i | ✅ |
| `start()` | 46-68 | Event consumer başlat | ✅ |
| `_load_instruments()` | 70-91 | BIST universe yükle | ✅ |
| `_on_tick()` | 93-118 | Tick event işle | ✅ |
| `_on_feature_update()` | 120-148 | Feature güncelleme | ✅ |
| `_compute_market_state()` | 150-219 | Market state hesapla | ⚠️ Basit |
| `_compute_risk_appetite()` | 221-255 | Risk appetite hesapla | ⚠️ Basit |
| `_detect_regime()` | 257-290 | Rejim tespiti | ⚠️ Basit |

### 2.2 intelligence/regime.py (357 satır) — RegimeEngine

| Fonksiyon | Satır | Ne Yapıyor | Durum |
|-----------|-------|------------|-------|
| `Regime` enum | 23-36 | 11 rejim tanımı | ✅ İyi |
| `RegimeState` | 38-45 | Rejim durumu | ✅ |
| `detect_regime()` | 70-145 | Skor bazlı rejim tespiti | ⚠️ HMM yok |
| `_score_bull()` | 147-163 | Bull skoru | ✅ |
| `_score_bear()` | 164-179 | Bear skoru | ✅ |
| `_score_sideways()` | 180-192 | Sideways skoru | ✅ |
| `_score_high_vol()` | 193-205 | High vol skoru | ✅ |
| `_score_low_vol()` | 206-217 | Low vol skoru | ✅ |
| `_score_risk_on()` | 218-230 | Risk-on skoru | ✅ |
| `_score_risk_off()` | 231-243 | Risk-off skoru | ✅ |
| `_score_crisis()` | 244-259 | Crisis skoru | ✅ |
| `_score_recovery()` | 260-275 | Recovery skoru | ✅ |
| `_score_momentum_expansion()` | 276-291 | Momentum expansion | ✅ |
| `_score_momentum_contraction()` | 292-308 | Momentum contraction | ✅ |
| `get_regime_weights()` | 313-332 | Rejime göre ağırlık | ✅ İyi |
| `get_transition_matrix()` | 333-341 | Geçiş matrisi | ✅ İyi |
| `get_history()` | 342-357 | Rejim geçmişi | ✅ |

### 2.3 intelligence/world_state.py (294 satır) — WorldStateManager

| Fonksiyon | Satır | Ne Yapıyor | Durum |
|-----------|-------|------------|-------|
| `WorldState` | 17-109 | 10 latent factor | ✅ İyi |
| `apply_decay()` | 94-109 | Factor bazlı decay | ✅ İyi |
| `update_from_event()` | 183-229 | Event güncelleme | ✅ İyi |
| `update_from_macro()` | 231-283 | Macro güncelleme | ✅ İyi |

### 2.4 API Endpoint'leri

| Endpoint | Modül | Durum |
|----------|-------|-------|
| `GET /api/market/state` | main.py → Redis → live compute | ✅ |
| `GET /api/regime` | server.py → regime_engine | ✅ |
| `GET /api/world/state` | main.py → world_state_manager | ✅ |

---

## 3. Eksikler (Kritik)

### 3.1 İki Ayrı Regime Detection Var

**Sorun:** `market_state/main.py`'de `_detect_regime()` ve `intelligence/regime.py`'de `RegimeEngine` — ikisi de rejim tespiti yapıyor ama farklı sonuçlar verebilir.
**Etki:** Tutarsız rejim tespiti
**Çözüm:** Tek canonical regime detection kaynağı

### 3.2 HMM Regime Detection Yok

**Sorun:** Sadece skor bazlı tespit — matematiksel HMM yok
**Etki:** Rejim geçişleri daha geç tespit edilir
**Kaynak:** Springer (2026) — Rolling HMM her 63 günde yeniden eğitim
**Çözüm:** HMM entegrasyonu

### 3.3 Market Breadth Basit

**Sorun:** Sadece advancing/declining oranı
**Etki:** Breadth derinliği eksik
**Çözüm:** Advance-Decline Line, New Highs-Lows, McClellan Oscillator

### 3.4 Liquidity State Yok

**Sorun:** Likidite durumu hesaplanmıyor
**Etki:** Likidite krizi geç tespit edilir
**Çözüm:** Spread, depth, market impact, volume participation

### 3.5 Sentiment State Yok

**Sorun:** Piyasa duyarlılığı market state'e dahil değil
**Etki:** Fear/greed indeksi yok
**Çözüm:** News sentiment, social sentiment, fear/greed composite

### 3.6 Macro State Entegrasyonu Zayıf

**Sorun:** World state var ama market state ile entegrasyon zayıf
**Etki:** Makro ortam market state'e yansımıyor
**Çözüm:** Macro state → market state entegrasyonu

### 3.7 Regime Transition Tracking Yok

**Sorun:** Rejim değişimi takip edilmiyor (ne zaman, ne sıklıkla)
**Etki:** Rejim kararlılığı bilinmiyor
**Çözüm:** Transition history, average duration, stability score

### 3.8 Multi-Timeframe State Yok

**Sorun:** Sadece anlık state — günlük, haftalık, aylık state yok
**Etki:** Farklı zaman ufuklarında farklı state olabilir
**Çözüm:** Intraday, daily, weekly, monthly state

---

## 4. Nihai Market State Mimarisi

### 4.1 Market State Pipeline (Nihai)

```
┌─────────────────────────────────────────────────────────────┐
│                    MARKET STATE PIPELINE                     │
│                                                             │
│  ┌─────────────────────────────────────────────────────┐   │
│  │              DATA INPUTS                             │   │
│  │                                                      │   │
│  │  ┌──────────┐  ┌──────────┐  ┌──────────┐          │   │
│  │  │  Ticks   │  │ Features │  │  Macro   │          │   │
│  │  │ (800+    │  │ (63+     │  │ (15+     │          │   │
│  │  │  hisse)  │  │ feature) │  │ değişken)│          │   │
│  │  └──────────┘  └──────────┘  └──────────┘          │   │
│  │  ┌──────────┐  ┌──────────┐  ┌──────────┐          │   │
│  │  │  News    │  │  Social  │  │  KAP     │          │   │
│  │  │ Sentiment│  │ Sentiment│  │ Events   │          │   │
│  │  └──────────┘  └──────────┘  └──────────┘          │   │
│  └─────────────────────────┬───────────────────────────┘   │
│                            ↓                                │
│  ┌─────────────────────────────────────────────────────┐   │
│  │              MARKET BREADTH                          │   │
│  │  - Advance-Decline Line                             │   │
│  │  - % Advancing / Declining                          │   │
│  │  - New Highs - New Lows                             │   │
│  │  - McClellan Oscillator                             │   │
│  │  - Arms Index (TRIN)                                │   │
│  └─────────────────────────┬───────────────────────────┘   │
│                            ↓                                │
│  ┌─────────────────────────────────────────────────────┐   │
│  │              MOMENTUM STATE                          │   │
│  │  - Average momentum (20d)                           │   │
│  │  - Average ROC (5d, 20d)                            │   │
│  │  - Trend strength (ADX)                             │   │
│  │  - Momentum breadth (% with positive momentum)      │   │
│  └─────────────────────────┬───────────────────────────┘   │
│                            ↓                                │
│  ┌─────────────────────────────────────────────────────┐   │
│  │              VOLATILITY STATE                        │   │
│  │  - Average realized volatility                      │   │
│  │  - VIX level + regime                               │   │
│  │  - Volatility regime (LOW/NORMAL/HIGH/EXTREME)      │   │
│  │  - Volatility trend (expanding/contracting)         │   │
│  └─────────────────────────┬───────────────────────────┘   │
│                            ↓                                │
│  ┌─────────────────────────────────────────────────────┐   │
│  │              VOLUME STATE                            │   │
│  │  - Average volume z-score                           │   │
│  │  - Volume trend (increasing/decreasing)             │   │
│  │  - Volume breadth (% with above-average volume)     │   │
│  │  - OBV trend                                        │   │
│  └─────────────────────────┬───────────────────────────┘   │
│                            ↓                                │
│  ┌─────────────────────────────────────────────────────┐   │
│  │              RSI STATE                               │   │
│  │  - Average RSI                                      │   │
│  │  - % Overbought (RSI > 70)                          │   │
│  │  - % Oversold (RSI < 30)                            │   │
│  │  - RSI breadth                                      │   │
│  └─────────────────────────┬───────────────────────────┘   │
│                            ↓                                │
│  ┌─────────────────────────────────────────────────────┐   │
│  │              LIQUIDITY STATE                         │   │
│  │  - Average spread                                   │   │
│  │  - Market depth                                     │   │
│  │  - Volume participation                             │   │
│  │  - Liquidity regime (TIGHT/NORMAL/LOOSE)            │   │
│  └─────────────────────────┬───────────────────────────┘   │
│                            ↓                                │
│  ┌─────────────────────────────────────────────────────┐   │
│  │              SENTIMENT STATE                         │   │
│  │  - News sentiment score                             │   │
│  │  - Social sentiment score                           │   │
│  │  - Fear/Greed index                                 │   │
│  │  - Put/Call ratio (opsiyon)                         │   │
│  └─────────────────────────┬───────────────────────────┘   │
│                            ↓                                │
│  ┌─────────────────────────────────────────────────────┐   │
│  │              MACRO STATE (World State entegrasyonu)  │   │
│  │  - Macro regime (EXPANSION/CONTRACTION/STAGFLATION) │   │
│  │  - Macro risk appetite                              │   │
│  │  - Macro stability                                  │   │
│  └─────────────────────────┬───────────────────────────┘   │
│                            ↓                                │
│  ┌─────────────────────────────────────────────────────┐   │
│  │              REGIME DETECTION (Nihai)               │   │
│  │                                                      │   │
│  │  ┌──────────┐  ┌──────────┐  ┌──────────┐          │   │
│  │  │  HMM     │  │  Skor    │  │  K-means │          │   │
│  │  │  Model   │  │  Bazlı   │  │ Clustering│         │   │
│  │  └──────────┘  └──────────┘  └──────────┘          │   │
│  │       ↓              ↓              ↓               │   │
│  │  ┌──────────────────────────────────────────────┐  │   │
│  │  │  Ensemble Regime (çoğunluk oyu)              │  │   │
│  │  └──────────────────────────────────────────────┘  │   │
│  │                                                      │   │
│  │  Rejimler:                                           │   │
│  │  - BULL, BEAR, SIDEWAYS                             │   │
│  │  - HIGH_VOLATILITY, LOW_VOLATILITY                  │   │
│  │  - RISK_ON, RISK_OFF                                │   │
│  │  - CRISIS, RECOVERY                                 │   │
│  │  - MOMENTUM_EXPANSION, MOMENTUM_CONTRACTION         │   │
│  └─────────────────────────┬───────────────────────────┘   │
│                            ↓                                │
│  ┌─────────────────────────────────────────────────────┐   │
│  │              RISK APPETITE (Nihai)                   │   │
│  │  - Breadth katkısı (0.35)                           │   │
│  │  - Momentum katkısı (0.25)                          │   │
│  │  - Volatility katkısı (0.25)                        │   │
│  │  - RSI katkısı (0.15)                               │   │
│  │  - Sentiment katkısı (0.10) ← YENİ                 │   │
│  │  - Macro katkısı (0.10) ← YENİ                     │   │
│  └─────────────────────────┬───────────────────────────┘   │
│                            ↓                                │
│  ┌─────────────────────────────────────────────────────┐   │
│  │              ANOMALY STATE                           │   │
│  │  - Anomaly count (şirket bazlı)                     │   │
│  │  - Anomaly severity                                 │   │
│  │  - Sector anomaly clustering                        │   │
│  │  - Market-wide anomaly alert                        │   │
│  └─────────────────────────┬───────────────────────────┘   │
│                            ↓                                │
│  ┌─────────────────────────────────────────────────────┐   │
│  │              REGIME TRANSITION TRACKING              │   │
│  │  - Transition history (ne zaman değişti)            │   │
│  │  - Average duration (ortalama süre)                 │   │
│  │  - Stability score (kararlılık skoru)               │   │
│  │  - Transition probability matrix                    │   │
│  └─────────────────────────┬───────────────────────────┘   │
│                            ↓                                │
│  ┌─────────────────────────────────────────────────────┐   │
│  │              MULTI-TIMEFRAME STATE                   │   │
│  │  - Intraday state (gün içi)                         │   │
│  │  - Daily state (günlük)                             │   │
│  │  - Weekly state (haftalık)                          │   │
│  │  - Monthly state (aylık)                            │   │
│  └─────────────────────────┬───────────────────────────┘   │
│                            ↓                                │
│  ┌─────────────────────────────────────────────────────┐   │
│  │              MARKET STATE OUTPUT                     │   │
│  │                                                      │   │
│  │  {                                                   │   │
│  │    "regime": "BULL",                                │   │
│  │    "regime_confidence": 0.78,                       │   │
│  │    "breadth_pct": 68.5,                             │   │
│  │    "momentum_state": "POSITIVE",                    │   │
│  │    "volatility_state": "NORMAL",                    │   │
│  │    "volume_state": "ABOVE_AVERAGE",                 │   │
│  │    "rsi_state": "NEUTRAL",                          │   │
│  │    "liquidity_state": "NORMAL",                     │   │
│  │    "sentiment_state": "POSITIVE",                   │   │
│  │    "macro_state": "EXPANSION",                      │   │
│  │    "risk_appetite": 0.72,                           │   │
│  │    "anomaly_count": 3,                              │   │
│  │    "regime_duration_days": 15,                      │   │
│  │    "regime_stability": 0.85,                        │   │
│  │    "daily_state": {...},                            │   │
│  │    "weekly_state": {...},                           │   │
│  │  }                                                   │   │
│  └─────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────┘
```

### 4.2 HMM Regime Detection (Nihai)

```python
class HMMRegimeDetector:
    """Hidden Markov Model ile rejim tespiti."""
    
    def __init__(self, n_regimes: int = 4):
        self.n_regimes = n_regimes
        self._model = None
        self._regime_names = ["BULL", "BEAR", "HIGH_VOL", "LOW_VOL"]
    
    def fit(self, returns: np.ndarray, volatility: np.ndarray):
        """HMM modelini eğit (rolling window)."""
        try:
            from hmmlearn.hmm import GaussianHMM
            X = np.column_stack([returns, volatility])
            self._model = GaussianHMM(
                n_components=self.n_regimes,
                covariance_type="full",
                n_iter=100,
            )
            self._model.fit(X)
        except ImportError:
            logger.warning("hmmlearn not installed")
    
    def predict_regime(self, returns: np.ndarray, volatility: np.ndarray) -> Dict:
        """Mevcut rejimi tahmin et."""
        if self._model is None:
            return {"regime": "UNKNOWN", "confidence": 0, "method": "none"}
        
        X = np.array([[returns[-1], volatility[-1]]])
        regime = self._model.predict(X)[0]
        probs = self._model.predict_proba(X)[0]
        
        return {
            "regime": self._regime_names[regime],
            "confidence": round(float(probs[regime]), 4),
            "probabilities": {
                name: round(float(prob), 4)
                for name, prob in zip(self._regime_names, probs)
            },
            "method": "hmm",
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

### 4.3 Ensemble Regime Detection (Nihai)

```python
class EnsembleRegimeDetector:
    """Çoklu yöntem ensemble rejim tespiti."""
    
    def __init__(self):
        self._hmm_detector = HMMRegimeDetector()
        self._score_detector = RegimeEngine()  # Mevcut skor bazlı
    
    def detect_regime(self, features: Dict, returns: np.ndarray = None,
                      volatility: np.ndarray = None) -> Dict:
        """Ensemble rejim tespiti."""
        results = {}
        
        # 1. Skor bazlı (mevcut)
        score_result = self._score_detector.detect_regime(features)
        results["score_based"] = {
            "regime": score_result.regime.value,
            "confidence": score_result.confidence,
        }
        
        # 2. HMM (yeni)
        if returns is not None and volatility is not None and len(returns) >= 63:
            hmm_result = self._hmm_detector.predict_regime(returns, volatility)
            results["hmm"] = hmm_result
        
        # 3. Ensemble kararı (çoğunluk oyu)
        regimes = [r["regime"] for r in results.values() if r.get("regime") != "UNKNOWN"]
        if regimes:
            from collections import Counter
            regime_counts = Counter(regimes)
            ensemble_regime = regime_counts.most_common(1)[0][0]
            ensemble_confidence = regime_counts[ensemble_regime] / len(regimes)
        else:
            ensemble_regime = "UNKNOWN"
            ensemble_confidence = 0
        
        return {
            "regime": ensemble_regime,
            "confidence": round(ensemble_confidence, 4),
            "methods": results,
            "method_count": len(results),
        }
```

### 4.4 Market Breadth (Nihai — Genişletilmiş)

```python
class MarketBreadthEngine:
    """Piyasa genişliği hesaplama."""
    
    def compute(self, instrument_states: List[Dict]) -> Dict:
        """Detaylı breadth hesaplama."""
        total = len(instrument_states)
        if total == 0:
            return {"error": "No instruments"}
        
        advancing = sum(1 for s in instrument_states if s.get("change_pct", 0) > 0)
        declining = sum(1 for s in instrument_states if s.get("change_pct", 0) < 0)
        unchanged = total - advancing - declining
        
        # Advance-Decline Line
        ad_line = advancing - declining
        
        # Advance-Decline Ratio
        ad_ratio = advancing / max(declining, 1)
        
        # % Advancing
        pct_advancing = advancing / total * 100
        
        # McClellan Oscillator (basitleştirilmiş)
        # EMA(19) of (advancing - declining) - EMA(39) of (advancing - declining)
        mcclellan = ad_line  # Basitleştirilmiş
        
        # Arms Index (TRIN)
        # (advancing / declining) / (advancing_volume / declining_volume)
        advancing_vol = sum(s.get("volume", 0) for s in instrument_states if s.get("change_pct", 0) > 0)
        declining_vol = sum(s.get("volume", 0) for s in instrument_states if s.get("change_pct", 0) < 0)
        trin = (advancing / max(declining, 1)) / (advancing_vol / max(declining_vol, 1))
        
        return {
            "advancing": advancing,
            "declining": declining,
            "unchanged": unchanged,
            "total": total,
            "ad_line": ad_line,
            "ad_ratio": round(ad_ratio, 4),
            "pct_advancing": round(pct_advancing, 2),
            "mcclellan": round(mcclellan, 2),
            "trin": round(trin, 4),
            "breadth_state": "BROAD" if pct_advancing > 60 else ("NARROW" if pct_advancing < 40 else "NEUTRAL"),
        }
```

### 4.5 Regime Transition Tracker (Nihai)

```python
class RegimeTransitionTracker:
    """Rejim geçiş takibi."""
    
    def __init__(self):
        self._history = []  # [{timestamp, regime, confidence}]
        self._transitions = []  # [{from, to, timestamp, duration}]
    
    def record(self, regime: str, confidence: float, timestamp: str = None):
        """Rejim kaydet."""
        if timestamp is None:
            timestamp = datetime.now(timezone.utc).isoformat()
        
        # Geçiş tespit et
        if self._history and self._history[-1]["regime"] != regime:
            from_regime = self._history[-1]["regime"]
            duration = self._calculate_duration(self._history[-1]["timestamp"], timestamp)
            
            self._transitions.append({
                "from": from_regime,
                "to": regime,
                "timestamp": timestamp,
                "duration_days": duration,
            })
        
        self._history.append({
            "timestamp": timestamp,
            "regime": regime,
            "confidence": confidence,
        })
    
    def get_stats(self) -> Dict:
        """Rejim istatistikleri."""
        if not self._history:
            return {"error": "No history"}
        
        # Rejim dağılımı
        from collections import Counter
        regime_counts = Counter(h["regime"] for h in self._history)
        
        # Ortalama süre
        durations = [t["duration_days"] for t in self._transitions if t["duration_days"]]
        avg_duration = np.mean(durations) if durations else 0
        
        # Kararlılık skoru (sık geçiş = düşük kararlılık)
        transition_rate = len(self._transitions) / max(len(self._history), 1)
        stability = max(0, 1 - transition_rate)
        
        return {
            "total_observations": len(self._history),
            "total_transitions": len(self._transitions),
            "regime_distribution": dict(regime_counts),
            "avg_duration_days": round(avg_duration, 1),
            "stability_score": round(stability, 4),
            "current_regime": self._history[-1]["regime"],
            "current_duration_days": self._calculate_duration(
                self._history[-1]["timestamp"],
                datetime.now(timezone.utc).isoformat()
            ),
        }
    
    def _calculate_duration(self, start: str, end: str) -> float:
        """Süre hesapla (gün)."""
        try:
            s = datetime.fromisoformat(start)
            e = datetime.fromisoformat(end)
            if s.tzinfo is None:
                s = s.replace(tzinfo=timezone.utc)
            if e.tzinfo is None:
                e = e.replace(tzinfo=timezone.utc)
            return (e - s).total_seconds() / 86400
        except:
            return 0
```

---

## 5. Rakip Karşılaştırması

### 5.1 Springer Regime-Aware (2026)

| Özellik | Springer | Bizim Sistem | Fark |
|---------|----------|-------------|------|
| Rolling HMM | ✅ 63 gün | ❌ | ❌ |
| Regime-aware model | ✅ | ⚠️ Basit | ⚠️ |
| Multi-factor regime | ✅ | ⚠️ Skor bazlı | ⚠️ |
| Transition tracking | ✅ | ❌ | ❌ |

### 5.2 Kaggle Market Regimes

| Özellik | Kaggle | Bizim Sistem | Fark |
|---------|--------|-------------|------|
| K-means clustering | ✅ | ❌ | ❌ |
| HMM | ✅ | ❌ | ❌ |
| Feature-based regime | ✅ | ✅ | ✅ |
| Visualization | ✅ | ❌ | ❌ |

### 5.3 Mevcut Sistem

| Özellik | Mevcut | Nihai |
|---------|--------|-------|
| Regime detection | ⚠️ 2 ayrı sistem | ✅ Tek canonical |
| HMM | ❌ | ✅ |
| Ensemble | ❌ | ✅ |
| Market breadth | ⚠️ Basit | ✅ Detaylı |
| Liquidity state | ❌ | ✅ |
| Sentiment state | ❌ | ✅ |
| Macro state entegrasyonu | ⚠️ Zayıf | ✅ |
| Transition tracking | ❌ | ✅ |
| Multi-timeframe | ❌ | ✅ |
| Anomaly state | ⚠️ Basit | ✅ Detaylı |

---

## 6. Uygulama Planı

### Faz 1: Tek Canonical Regime (Hemen)
1. market_state/main.py'deki `_detect_regime()`'yi kaldır
2. intelligence/regime.py'yi canonical yap
3. API endpoint'lerini tek kaynağa bağla

### Faz 2: HMM Regime Detection (1 hafta)
1. `hmmlearn` entegrasyonu
2. Rolling HMM (63 günde yeniden eğitim)
3. Regime probability outputs
4. Ensemble (HMM + skor bazlı)

### Faz 3: Market Breadth Genişletme (1 hafta)
1. Advance-Decline Line
2. New Highs-Lows
3. McClellan Oscillator
4. Arms Index (TRIN)

### Faz 4: Liquidity + Sentiment State (1 hafta)
1. Liquidity state (spread, depth, participation)
2. Sentiment state (news, social, fear/greed)
3. Risk appetite'a entegre et

### Faz 5: Regime Transition Tracking (1 hafta)
1. Transition history
2. Average duration
3. Stability score
4. Transition probability matrix

### Faz 6: Multi-Timeframe (1 hafta)
1. Intraday, daily, weekly, monthly state
2. Cross-timeframe regime comparison
3. Timeframe-specific strategy

---

## 7. Mevcut Sistem vs Nihai Vizyon

| Özellik | Mevcut | Hedef |
|---------|--------|-------|
| Modül sayısı | 3 | 8 |
| Toplam satır | ~800 | ~1,500 |
| Regime detection | ⚠️ 2 ayrı sistem | ✅ Tek canonical + HMM |
| HMM | ❌ | ✅ |
| Ensemble regime | ❌ | ✅ |
| Market breadth | ⚠️ Basit (advancing/declining) | ✅ Detaylı (AD Line, McClellan, TRIN) |
| Liquidity state | ❌ | ✅ |
| Sentiment state | ❌ | ✅ |
| Macro state | ⚠️ Zayıf | ✅ Entegre |
| Transition tracking | ❌ | ✅ |
| Multi-timeframe | ❌ | ✅ |
| Anomaly state | ⚠️ Basit | ✅ Detaylı |
| Risk appetite | ⚠️ 4 faktör | ✅ 6 faktör |
