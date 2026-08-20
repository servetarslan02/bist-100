# Features Nihai Sistem Dokümanı — Kod Analizi + Araştırma Bazlı

**Tarih:** 2026-08-18 (Güncelleme: 2026-08-21 — ÇÖZÜLDÜ etiketleri eklendi)
**Kaynaklar:** ScienceDirect Feature Importance (2025), arXiv Sentiment-Aware Stock Prediction (2026), Springer Stock Market Forecasting (2025), MDPI Macroeconomic Features (2025), Atlan Feature Store (2026), Introl Feature Stores (2026)

---

## 1. Mevcut Durum (Kod Analizi)

### Modüller (17 dosya, toplam 5,802 satır)

| Modül | Satır | Class | Fonksiyon | Durum |
|-------|-------|-------|-----------|-------|
| `seven_motors.py` | 1,317 | 10 | 12 | ✅ En büyük modül |
| `calculator.py` | 559 | 1 | 24 | ✅ Ana hesaplayıcı |
| `data_adapter.py` | 633 | 1 | 15 | ✅ Veri adaptörü |
| `panel_engine.py` | 364 | 3 | 8 | ⚠️ Entegrasyon zayıf |
| `incremental_state.py` | 353 | 4 | 14 | ✅ Artımlı güncelleme |
| `fundamental.py` | 342 | 1 | 8 | ✅ Fundamental features |
| `cross_sectional.py` | 327 | 1 | 7 | ✅ Cross-sectional |
| `discovery.py` | 320 | 2 | 6 | ✅ Hisse keşfi |
| `sentiment.py` | 307 | 1 | 11 | ✅ Sentiment features |
| `macro.py` | 281 | 1 | 10 | ✅ Macro features |
| `extended_indicators.py` | 272 | 1 | 12 | ✅ Ek göstergeler |
| `bar_engine.py` | 213 | 4 | 13 | ✅ Bar oluşturma |
| `technical_features.py` | 188 | 1 | 7 | ✅ Teknik features |
| `main.py` | 194 | 1 | 3 | ⚠️ Pipeline eksik |
| `store.py` | 175 | 2 | 13 | ⚠️ Versioning yok |
| `feature_contract.py` | 162 | 3 | 12 | ✅ Contract validation |
| `feature_selector.py` | 107 | 1 | 3 | ⚠️ SHAP entegrasyonu yok |

### Sorunlar

1. **calculator.py**: 24 fonksiyon var ama çoğu mask-aware — mask=0 olan günlerde feature hesaplamıyor (iyi)
2. **seven_motors.py**: 10 motor var ama hangisi çalışıyor belirsiz
3. **store.py**: Feature store var ama versioning yok
4. **feature_selector.py**: SHAP entegrasyonu yok — sadece correlation ve variance filter
5. **panel_engine.py**: Panel features var ama entegrasyon zayıf
6. **main.py**: Pipeline orchestrator ama eksik bağlantılar
7. **Feature versioning** yok — eski backtest'ler bozulabilir
8. **Point-in-time validation** yok — data leakage riski
9. **Feature importance tracking** yok — hangi feature en önemli bilinmiyor
10. **Feature drift detection** yok — feature'lar zamanla bozulabilir

---

## 2. Feature Engineering Nedir? (Araştırma Bazlı)

### Tanım

Feature engineering, ham veriden makine öğrenmesi modeli için anlamlı özellikler çıkarma sürecidir. Hisse tahmininde:

- **Teknik features**: Fiyat, hacim, volatilite → trend, momentum, destek/direnç
- **Fundamental features**: Bilanço, gelir tablosu → değerleme, kârlılık, büyüme
- **Macro features**: Faiz, enflasyon, döviz → piyasa rejimi, sektör etkisi
- **Sentiment features**: Haber, KAP, sosyal medya → piyasa duyarlılığı
- **Cross-sectional features**: Sektör, peer, market → göreli performans

### En Önemli Feature Kategorileri (Araştırma Bazlı)

| Kategori | Feature Sayısı | Önem Sırası | BIST Kanıt |
|----------|---------------|-------------|-----------|
| **Momentum** | 10-15 | 🔴 En yüksek | ✅ BIST'te güçlü |
| **Value** | 8-12 | 🔴 Yüksek | ✅ BIST'te çalışıyor |
| **Volatility** | 5-8 | 🟡 Orta | ✅ BIST'te çalışıyor |
| **Quality** | 6-10 | 🟡 Orta | ✅ BIST'te çalışıyor |
| **Volume** | 5-8 | 🟡 Orta | ✅ BIST'te çalışıyor |
| **Sentiment** | 5-10 | 🟢 Düşük-orta | ⚠️ BIST'te sınırlı |
| **Macro** | 5-8 | 🟢 Düşük | ⚠️ BIST'te etkili |
| **Cross-sectional** | 5-10 | 🟡 Orta | ✅ BIST'te çalışıyor |

---

## 3. Nihai Feature Mimarisi

### 3.1 Feature Pipeline

```
┌─────────────────────────────────────────────────────────────┐
│                    FEATURE PIPELINE                          │
│                                                             │
│  ┌───────────┐  ┌───────────┐  ┌───────────┐              │
│  │ Raw Data  │  │ OHLCV     │  │ Financials│              │
│  │ (Ingestion)│ │ (Market)  │  │ (KAP)     │              │
│  └─────┬─────┘  └─────┬─────┘  └─────┬─────┘              │
│        └───────────────┼──────────────┘                     │
│                        ↓                                    │
│  ┌─────────────────────────────────────────────────────┐   │
│  │              MASK-FIRST DESIGN                       │   │
│  │  - Tradability mask (işlem yapılabilirlik)           │   │
│  │  - Mask=0 olan günler feature hesaplamasında kullanılmaz │   │
│  │  - Data quality gate (geçersiz veri filtrelenir)     │   │
│  └─────────────────────────────────────────────────────┘   │
│                            ↓                                │
│  ┌─────────────────────────────────────────────────────┐   │
│  │              FEATURE COMPUTATION                     │   │
│  │                                                      │   │
│  │  ┌──────────┐  ┌──────────┐  ┌──────────┐          │   │
│  │  │ Technical │  │Fundament.│  │  Macro   │          │   │
│  │  │ Features  │  │ Features │  │ Features │          │   │
│  │  └──────────┘  └──────────┘  └──────────┘          │   │
│  │  ┌──────────┐  ┌──────────┐  ┌──────────┐          │   │
│  │  │Sentiment │  │  Cross-  │  │  Seven   │          │   │
│  │  │ Features │  │Sectional │  │  Motors  │          │   │
│  │  └──────────┘  └──────────┘  └──────────┘          │   │
│  └─────────────────────────────────────────────────────┘   │
│                            ↓                                │
│  ┌─────────────────────────────────────────────────────┐   │
│  │              FEATURE VALIDATION                      │   │
│  │  - NaN/Inf kontrolü                                  │   │
│  │  - Range validation                                  │   │
│  │  - Point-in-time check (look-ahead bias)             │   │
│  │  - Feature contract validation                       │   │
│  └─────────────────────────────────────────────────────┘   │
│                            ↓                                │
│  ┌─────────────────────────────────────────────────────┐   │
│  │              FEATURE STORE                           │   │
│  │  - Versioned features (v1, v2, v3)                   │   │
│  │  - Point-in-time correct joins                       │   │
│  │  - Feature metadata (timestamp, version, source)     │   │
│  │  - Feature lineage (raw → transformed → stored)      │   │
│  └─────────────────────────────────────────────────────┘   │
│                            ↓                                │
│  ┌─────────────────────────────────────────────────────┐   │
│  │              FEATURE SELECTION                       │   │
│  │  - SHAP importance                                   │   │
│  │  - Correlation filter                                │   │
│  │  - Variance threshold                                │   │
│  │  - Recursive feature elimination                     │   │
│  └─────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────┘
```

### 3.2 Feature Kategorileri (Detaylı)

#### 3.2.1 Teknik Features (25+ feature)

```python
class TechnicalFeatures:
    """Teknik gösterge feature'ları."""
    
    # Trend Features
    sma_5, sma_10, sma_20, sma_50, sma_100, sma_200
    ema_5, ema_10, ema_20, ema_50
    macd, macd_signal, macd_histogram
    adx, plus_di, minus-di
    trend_slope_20d, trend_slope_60d
    
    # Momentum Features
    rsi_7, rsi_14, rsi_21
    roc_1d, roc_5d, roc_10d, roc_20d
    momentum_5d, momentum_10d, momentum_20d
    stochastic_k, stochastic_d
    
    # Volatility Features
    atr_14, atr_20, atr_pct
    bollinger_upper, bollinger_lower, bollinger_width, bollinger_position
    realized_vol_5d, realized_vol_20d, realized_vol_60d
    volatility_ratio (5d/20d)
    
    # Volume Features
    volume_sma_20, volume_ratio, volume_zscore
    obv, obv_trend
    volume_acceleration
    vwap
    
    # Price Action Features
    higher_highs, lower_lows, inside_days
    support_distance, resistance_distance
    gap_up, gap_down
    candle_body_ratio
```

#### 3.2.2 Fundamental Features (20+ feature)

```python
class FundamentalFeatures:
    """Fundamental feature'ları."""
    
    # Valuation
    pe_ratio, pb_ratio, ps_ratio, ev_ebitda, fcf_yield
    pe_relative (vs sector), pb_relative (vs sector)
    
    # Profitability
    roe, roa, roic, gross_margin, ebitda_margin, net_margin
    margin_trend (artış/azalış)
    
    # Growth
    revenue_growth_yoy, revenue_growth_qoq
    earnings_growth_yoy, earnings_growth_qoq
    revenue_acceleration (büyüme hızlanıyor mu?)
    
    # Balance Sheet
    debt_equity, current_ratio, quick_ratio
    net_debt_ebitda, interest_coverage
    cash_ratio (nakit/borç)
    
    # Cash Flow
    operating_cf, fcf, cf_yield
    cf_conversion (CF/Net Income)
    capex_ratio (CAPEX/Revenue)
    
    # Quality
    piotroski_f_score, beneish_m_score, altman_z_score
    earnings_quality (accruals)
    dividend_payout_ratio
```

#### 3.2.3 Macro Features (15+ feature)

```python
class MacroFeatures:
    """Makro feature'ları."""
    
    # Currency
    usdtry, usdtry_change_1d, usdtry_change_20d
    usdtry_volatility, eurtry, eur_usd
    
    # Interest Rates
    policy_rate, real_rate (policy - inflation)
    rate_surprise (actual - expected)
    yield_curve_slope (10y - 2y)
    
    # Inflation
    cpi_yoy, ppi_yoy, core_cpi
    ppi_cpi_spread, inflation_expectation
    
    # Global
    vix, vix_change, vix_percentile
    sp500_return, nasdaq_return
    gold_price, oil_price
    
    # Turkey Specific
    cds_5y, cds_change
    bist_100_return, bist_30_return
    foreign_investor_ratio
```

#### 3.2.4 Sentiment Features (15+ feature)

```python
class SentimentFeatures:
    """Sentiment feature'ları."""
    
    # News Sentiment
    news_sentiment_score, news_volume_24h
    news_positive_ratio, news_negative_ratio
    news_freshness (son haber yaşı)
    
    # KAP Sentiment
    kap_sentiment_score, kap_event_count
    kap_event_type (financial, dividend, buyback, vb.)
    kap_impact_score
    
    # Social Sentiment
    social_sentiment_score, social_volume_24h
    social_engagement_avg, social_viral_score
    social_manipulation_score
    social_platform_breakdown (X, Ekşi, Reddit)
    
    # Aggregate
    overall_sentiment_score
    sentiment_momentum (sentiment artıyor mu?)
    sentiment_divergence (fiyat vs sentiment)
```

#### 3.2.5 Cross-Sectional Features (10+ feature)

```python
class CrossSectionalFeatures:
    """Cross-sectional feature'ları."""
    
    # Rank Features
    rank_return_20d (getiri sıralaması)
    rank_momentum (momentum sıralaması)
    rank_value (değer sıralaması)
    rank_quality (kalite sıralaması)
    rank_volatility (volatilite sıralaması)
    
    # Sector Relative
    sector_relative_return
    sector_relative_momentum
    sector_rank
    
    # Market Breadth
    advancing_declining_ratio
    new_highs_lows_ratio
    market_breadth_index
    
    # Peer Correlation
    peer_correlation_avg
    peer_beta
```

#### 3.2.6 BIST'e Özgü Features (10+ feature)

```python
class BISTSpecificFeatures:
    """BIST'e özgü feature'lar."""
    
    # Kur Hassasiyeti
    fx_sensitivity (USDTRY beta)
    fx_impact_on_revenue
    fx_impact_on_debt
    
    # Enflasyon Hassasiyeti
    inflation_sensitivity
    real_return_adjustment
    
    # Faiz Hassasiyeti
    rate_sensitivity
    debt_cost_impact
    
    # Sektör Momentum
    sector_momentum_20d
    sector_relative_strength
    
    # KAP Etkisi
    kap_event_frequency
    kap_sentiment_trend
    
    # Yabancı Yatırımcı
    foreign_ownership_pct
    foreign_flow_direction
```

---

## 4. Feature Store (Nihai)

### 4.1 Feature Versioning

```python
class FeatureStore:
    """Versioned feature store."""
    
    def save(self, ticker: str, date: str, features: Dict, version: str = "v1"):
        """Feature'ları version ile kaydet."""
        key = f"{ticker}:{date}:{version}"
        self._store[key] = {
            "features": features,
            "version": version,
            "timestamp": datetime.now().isoformat(),
            "ticker": ticker,
            "date": date,
        }
    
    def get(self, ticker: str, date: str, version: str = "v1") -> Optional[Dict]:
        """Feature'ları version ile getir."""
        key = f"{ticker}:{date}:{version}"
        return self._store.get(key)
    
    def get_range(self, ticker: str, start_date: str, end_date: str, version: str = "v1") -> List[Dict]:
        """Tarih aralığındaki feature'ları getir."""
        results = []
        for key, value in self._store.items():
            if key.startswith(f"{ticker}:") and key.endswith(f":{version}"):
                date = key.split(":")[1]
                if start_date <= date <= end_date:
                    results.append(value)
        return sorted(results, key=lambda x: x["date"])
```

### 4.2 Point-in-Time Validation

```python
class PointInTimeValidator:
    """Look-ahead bias kontrolü."""
    
    def validate(self, feature_date: str, data_timestamp: str) -> bool:
        """Feature tarihi veri timestamp'inden önce mi?"""
        return feature_date <= data_timestamp
    
    def validate_batch(self, features: List[Dict]) -> List[Dict]:
        """Toplu validation."""
        valid = []
        for f in features:
            if self.validate(f["date"], f["data_timestamp"]):
                valid.append(f)
            else:
                logger.warning("Look-ahead bias detected", feature=f)
        return valid
```

### 4.3 Feature Drift Detection

```python
class FeatureDriftDetector:
    """Feature dağılım değişikliği tespiti."""
    
    def detect_drift(self, historical_values: List[float], current_values: List[float]) -> Dict:
        """Feature drift tespiti."""
        hist_mean = np.mean(historical_values)
        hist_std = np.std(historical_values)
        curr_mean = np.mean(current_values)
        
        # Z-score
        z_score = abs(curr_mean - hist_mean) / max(hist_std, 0.001)
        
        # KS test
        from scipy import stats
        ks_stat, ks_p = stats.ks_2samp(historical_values, current_values)
        
        return {
            "drift_detected": z_score > 2.0 or ks_p < 0.05,
            "z_score": round(z_score, 4),
            "ks_statistic": round(ks_stat, 4),
            "ks_p_value": round(ks_p, 4),
            "historical_mean": round(hist_mean, 4),
            "current_mean": round(curr_mean, 4),
        }
```

---

## 5. Feature Importance Tracking

```python
class FeatureImportanceTracker:
    """Feature önem takibi."""
    
    def track(self, model, feature_names: List[str], X: np.ndarray) -> Dict:
        """SHAP ile feature importance hesapla."""
        try:
            import shap
            explainer = shap.TreeExplainer(model)
            shap_values = explainer.shap_values(X)
            importance = np.abs(shap_values).mean(axis=0)
        except:
            # Fallback: model.feature_importances_
            importance = model.feature_importances_
        
        # Sırala
        paired = list(zip(feature_names, importance))
        paired.sort(key=lambda x: x[1], reverse=True)
        
        return {
            "top_features": paired[:20],
            "total_features": len(feature_names),
            "importance_concentration": sum(p[1] for p in paired[:10]) / sum(p[1] for p in paired),
        }
```

---

## 6. Uygulama Planı

### Faz 1: Feature Versioning (Hemen)
1. Feature store'a versioning ekle
2. Point-in-time validation ekle
3. Feature metadata (timestamp, version, source)

### Faz 2: Feature Drift Detection (1 hafta)
1. Feature dağılım değişikliği tespiti
2. Z-score ve KS test
3. Drift alert'leri

### Faz 3: Feature Importance (1 hafta)
1. SHAP entegrasyonu
2. Feature importance tracking
3. Feature selection improvements

### Faz 4: BIST Features (1 hafta)
1. BIST'e özgü feature'ları detaylandır
2. FX/inflasyon/faiz hassasiyeti
3. KAP sentiment trend
4. Yabancı yatırımcı akışı

### Faz 5: Feature Pipeline (1 hafta)
1. main.py pipeline'ı tamamla
2. Tüm modülleri bağla
3. Feature contract validation
4. Feature lineage tracking

---

## 7. Mevcut Sistem vs Nihai Vizyon

| Özellik | Mevcut | Hedef |
|---------|--------|-------|
| Modül sayısı | 17 | 22 |
| Toplam satır | 5,802 | ~8,000 |
| Teknik features | ✅ 25+ | ✅ 30+ |
| Fundamental features | ✅ 20+ | ✅ 25+ |
| Macro features | ✅ 15+ | ✅ 20+ |
| Sentiment features | ✅ 15+ | ✅ 20+ |
| Cross-sectional features | ✅ 10+ | ✅ 15+ |
| BIST-specific features | ⚠️ 4 | ✅ 10+ |
| Feature versioning | ❌ | ✅ |
| Point-in-time validation | ❌ | ✅ |
| Feature drift detection | ❌ | ✅ |
| SHAP importance | ❌ | ✅ |
| Feature lineage | ❌ | ✅ |
| Feature contract | ✅ | ✅ |
| Mask-first design | ✅ | ✅ |
| Incremental state | ✅ | ✅ |

---

## 8. Düzeltme Kayıtları (2026-08-21)

### ÇÖZÜLDÜ — RSI Tutarlılığı (technical_features.py ↔ incremental_state.py)
- **Sorun:** technical_features.py basit mean RSI kullanıyordu, incremental_state.py Wilder's smoothing. İki farklı sonuç.
- **Çözüm:** Her iki modül de artık Wilder's smoothing kullanıyor. Fark: 0.0000 (aynı veri ile).
- **Dosya:** `services/features/technical_features.py` — `_rsi()` metodu yeniden yazıldı.

### ÇÖZÜLDÜ — MACD Signal Line (technical_features.py)
- **Sorun:** `macd_signal = macd` (kendisi) — signal line hesaplanmıyordu.
- **Çözüm:** MACD serisinin 9-period EMA'sı artık gerçek signal line olarak hesaplanıyor.
- **Dosya:** `services/features/technical_features.py` — `compute_trend_features()`

### ÇÖZÜLDÜ — Incremental RSI Sıfır Değer Sorunu (incremental_state.py)
- **Sorun:** `_update_rsi()` çağrısından önce `previous_price` güncellendiği için change her zaman 0 oluyordu. RSI 50.0'da kalıyordu.
- **Çözüm:** `_last_bar_close` eklendi. RSI artık bar'lar arası değişimi kullanıyor.
- **Dosya:** `services/features/incremental_state.py` — `process_tick()` ve `_update_rsi()`

### ÇÖZÜLDÜ — BIST sector_rank Placeholder (bist_features.py)
- **Sorun:** `sector_rank = 1` hardcoded placeholder.
- **Çözüm:** `sector_stock_returns` map'inden gerçek sıralama hesaplanıyor.
- **Dosya:** `services/features/bist_features.py` — `_compute_sector_features()`

### ÇÖZÜLDÜ — Feature Selector VIF Placeholder (feature_selector.py)
- **Sorun:** `_compute_vif()` her zaman `[1.0] * n` döndürüyordu.
- **Çözüm:** Korelasyon matrisinin tersinden gerçek VIF hesaplanıyor.
- **Dosya:** `services/features/feature_selector.py` — `_compute_vif()`

### ÇÖZÜLDÜ — Macro Percentile Look-Ahead Bias (macro.py)
- **Sorun:** Percentile hesaplaması current value'yu dahil ediyordu. Ayrıca `len(history)>=20` bloğu içindeydi, 10-19 arası veride çalışmıyordu.
- **Çözüm:** Current value hariç tutuldu. Percentile check bağımsız `len(history)>=10` koşuluna taşındı.
- **Dosya:** `services/features/macro.py` — `compute_currency_features()`

### ÇÖZÜLDÜ — Fundamental %1 Heuristic (fundamental.py)
- **Sorun:** `abs(val) < 1` kontrolü küçük ama geçerli yüzde değerlerini (ör. %0.5 marj) yanlışlıkla %50'ye çeviriyordu.
- **Çözüm:** Otomatik dönüşüm kaldırıldı. Kaynak veri formatı bilinmiyorsa dokunulmuyor.
- **Dosya:** `services/features/fundamental.py` — `compute_profitability_features()`, `compute_growth_features()`, `compute_quality_features()`

### ÇÖZÜLDÜ — Pipeline Singleton (pipeline.py)
- **Sorun:** `FeaturePipelineOrchestrator` kendi `FeatureStore()` instance'ını oluşturuyordu. Global singleton ile farklı state.
- **Çözüm:** Artık `feature_store` singleton'ını kullanıyor.
- **Dosya:** `services/features/pipeline.py` — `store` property

### ÇÖZÜLDÜ — calculator.py Sessiz Except Blokları
- **Sorun:** `compute_extended_features()` içinde 4 boş `try/except` bloğu (bar engine, discovery, store, selector). Import başarısızlıklarını sessizce yutuyordu.
- **Çözüm:** Gereksiz import blokları kaldırıldı. Bu modüller ayrı pipeline'larda kullanılıyor.
- **Dosya:** `services/features/calculator.py` — `compute_extended_features()`
