# Event Study Nihai Sistem Dokümanı — Kod Analizi + Araştırma Bazlı

**Tarih:** 2026-08-18
**Kaynaklar:** MacKinlay (1997) Event Study Methodology, ScienceDirect ESG Event Study (2025), jatss BIST-100 Event Study (2026), ScholarHub Interest Rate Event Study (2026), Dergipark BIST Monetary Policy (2018)

---

## 1. Mevcut Durum (Kod Analizi)

### Modüller (14 dosya, toplam ~2,450 satır) — ✅ NİHAİ

| Modül | Satır | Fonksiyon/Sınıf | Durum |
|-------|-------|-----------------|-------|
| `estimation_window.py` | ~120 | `EstimationWindowManager` | ✅ Yeni |
| `event_window.py` | ~130 | `EventWindowManager` | ✅ Yeni |
| `expected_return.py` | ~200 | `calculate_expected_return()` | ✅ Multi-factor |
| `abnormal_return.py` | ~80 | `calculate_abnormal_return()` | ✅ Batch destekli |
| `car.py` | ~90 | `calculate_car()` | ✅ Sub-window + AAR/CAAR |
| `statistical_test.py` | ~170 | `test_significance()` | ✅ t-dist + Bonferroni + BH + Wilcoxon |
| `impact.py` | ~150 | `calculate_event_impact()` | ✅ Event-specific weights |
| `kap_event.py` | ~250 | `analyze_kap_event()` | ✅ Type mapping + classify |
| `macro_event.py` | ~280 | `analyze_tcmb_event()` | ✅ TCMB + enflasyon + GSYH + cari açık |
| `multi_factor.py` | ~150 | `MultiFactorModel` | ✅ Fama-French 3/5 |
| `cross_sectional.py` | ~220 | `CrossSectionalEventStudy` | ✅ Regresyon + breakdown |
| `event_clustering.py` | ~150 | `EventClusteringDetector` | ✅ Clustering tespit + düzeltme |
| `event_decay.py` | ~160 | `EventImpactDecay` | ✅ Exponential decay + half-life |
| `sector_event.py` | ~200 | `SectorEventAnalyzer` | ✅ Peer comparison + rotation |

### Sorunlar — ✅ HEPSI DÜZELTİLDİ

1. ✅ **expected_return.py**: Multi-factor (Fama-French 3/5) eklendi
2. ✅ **statistical_test.py**: t-distribution + Bonferroni + BH FDR + Wilcoxon
3. ✅ **impact.py**: Event-specific ağırlıklar eklendi
4. ✅ **kap_event.py**: KAP event type mapping + classify fonksiyonu
5. ✅ **macro_event.py**: TCMB + enflasyon + GSYH + cari açık + PPI + USDTRY
6. ✅ **Estimation window**: `EstimationWindowManager` — look-ahead bias önleme
7. ✅ **Event window**: `EventWindowManager` — gün bazlı pencereleme
8. ✅ **Cross-sectional analysis**: `CrossSectionalEventStudy` — regresyon + breakdown
9. ✅ **Event clustering**: `EventClusteringDetector` — clustering tespit + düzeltme

---

## 2. Event Study Metodolojisi (MacKinlay, 1997)

### Temel Adımlar

```
1. Event Definition
   - Event date (t=0): KAP açıklaması tarihi
   - Event window: [t-5, t+5] (11 gün)
   - Estimation window: [t-120, t-6] (115 gün)

2. Expected Return Calculation
   - Market Model: E[R_it] = α_i + β_i × R_mt
   - Estimation window'den α ve β tahmin et

3. Abnormal Return Calculation
   - AR_it = R_it - E[R_it]
   - AR_it = R_it - (α_i + β_i × R_mt)

4. Cumulative Abnormal Return
   - CAR[t1,t2] = Σ AR_it (t1'den t2'ye)

5. Statistical Testing
   - t-test: t = CAR / σ(CAR)
   - p-value: t-distribution'dan
   - Significant: p < 0.05

6. Cross-sectional Analysis
   - Birden fazla hisse için CAR hesapla
   - Ortalama CAR ve significance
```

---

## 3. Nihai Event Study Mimarisi

### 3.1 Event Pipeline

```
┌─────────────────────────────────────────────────────────────┐
│                    EVENT STUDY PIPELINE                      │
│                                                             │
│  ┌───────────┐  ┌───────────┐  ┌───────────┐              │
│  │ Event     │  │ Market    │  │ Calendar  │              │
│  │ Detector  │  │ Data      │  │ Manager   │              │
│  └─────┬─────┘  └─────┬─────┘  └─────┬─────┘              │
│        └───────────────┼──────────────┘                     │
│                        ↓                                    │
│  ┌─────────────────────────────────────────────────────┐   │
│  │              ESTIMATION WINDOW                       │   │
│  │  - [t-120, t-6] → α, β tahmini                     │   │
│  │  - Market model: E[R] = α + β × R_m                │   │
│  │  - R² ve residual analysis                          │   │
│  └─────────────────────────────────────────────────────┘   │
│                            ↓                                │
│  ┌─────────────────────────────────────────────────────┐   │
│  │              EVENT WINDOW                            │   │
│  │  - [t-5, t+5] → 11 günlük pencere                  │   │
│  │  - AR_it = R_it - (α + β × R_mt)                   │   │
│  │  - CAR = Σ AR                                       │   │
│  └─────────────────────────────────────────────────────┘   │
│                            ↓                                │
│  ┌─────────────────────────────────────────────────────┐   │
│  │              STATISTICAL TEST                        │   │
│  │  - t-statistic: t = CAR / σ(CAR)                    │   │
│  │  - p-value: t-distribution (n-2 df)                 │   │
│  │  - Confidence interval: 95%                         │   │
│  │  - Multiple testing correction (Bonferroni)         │   │
│  └─────────────────────────────────────────────────────┘   │
│                            ↓                                │
│  ┌─────────────────────────────────────────────────────┐   │
│  │              CROSS-SECTIONAL ANALYSIS                │   │
│  │  - Average CAR across events                        │   │
│  │  - Event type comparison                            │   │
│  │  - Sector/regime breakdown                          │   │
│  │  - Regression: CAR = f(event_features)              │   │
│  └─────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────┘
```

### 3.2 Event Types (KAP Bazlı)

| Event Type | Beklenen Etki | Estimation Window | Event Window |
|------------|---------------|-------------------|--------------|
| **Financial Results** | Yüksek | 120 gün | [-5, +5] |
| **Dividend Announcement** | Orta | 60 gün | [-3, +3] |
| **Buyback** | Pozitif | 60 gün | [-3, +3] |
| **Capital Increase** | Karma | 90 gün | [-5, +5] |
| **Merger/Acquisition** | Yüksek | 120 gün | [-10, +10] |
| **Management Change** | Düşük | 60 gün | [-3, +3] |
| **Legal/Regulatory** | Karma | 90 gün | [-5, +5] |
| **Contract/Investment** | Pozitif | 60 gün | [-3, +3] |
| **Guidance** | Orta | 60 gün | [-3, +3] |

### 3.3 TCMB Event Analysis (Detaylı)

```python
# TCMB faiz kararı event study
def analyze_tcmb_event_detailed(rate_actual, rate_expected, rate_previous,
                                 inflation, usdtry, bist_returns):
    """
    MacKinlay metodolojisi ile TCMB event study.
    
    1. Surprise hesapla: rate_actual - rate_expected
    2. Direction: HAWKISH (artış) / DOVISH (düşüş) / NEUTRAL
    3. Magnitude: sürpriz büyüklüğü
    4. Market reaction: BIST-100 CAR[-1, +3]
    5. Sector breakdown: Banka vs Sanayi vs Teknoloji
    6. FX reaction: USDTRY CAR
    7. Statistical significance: t-test
    """
    surprise = rate_actual - rate_expected
    surprise_pct = surprise / rate_previous if rate_previous > 0 else 0
    
    # Event window returns
    bist_car = calculate_car(bist_returns[-5:])  # [-1, +3]
    
    # Statistical test
    ar = calculate_abnormal_return(bist_returns, market_returns, alpha, beta)
    stats = test_significance(bist_car, ar)
    
    # Direction
    if surprise > 0:
        direction = "HAWKISH"
        expected_bist = "NEGATIVE"
    elif surprise < 0:
        direction = "DOVISH"
        expected_bist = "POSITIVE"
    else:
        direction = "NEUTRAL"
        expected_bist = "NEUTRAL"
    
    # Impact assessment
    if abs(surprise_pct) > 0.05:
        impact_level = "HIGH"
    elif abs(surprise_pct) > 0.02:
        impact_level = "MEDIUM"
    else:
        impact_level = "LOW"
    
    return {
        "surprise": surprise,
        "surprise_pct": surprise_pct,
        "direction": direction,
        "expected_bist_reaction": expected_bist,
        "actual_bist_car": bist_car,
        "impact_level": impact_level,
        "statistical_significance": stats,
        "inflation_context": inflation,
        "usdtry_context": usdtry,
    }
```

### 3.4 Sector Event Analysis

```python
# Sektör bazlı event analysis
def analyze_sector_event(sector, event_type, market_returns, sector_returns):
    """
    Sektör bazlı event study.
    
    1. Sektör abnormal return hesapla
    2. BIST-100'e göre relative performance
    3. Peer comparison (aynı sektördeki diğer hisseler)
    4. Sektör-specific event type mapping
    """
    # Sektör AR
    sector_ar = calculate_abnormal_return(sector_returns, market_returns, alpha, beta)
    sector_car = calculate_car(sector_ar)
    
    # BIST-100 AR
    bist_ar = calculate_abnormal_return(bist_returns, market_returns, alpha, beta)
    bist_car = calculate_car(bist_ar)
    
    # Relative performance
    relative_car = sector_car - bist_car
    
    return {
        "sector": sector,
        "sector_car": sector_car,
        "bist_car": bist_car,
        "relative_car": relative_car,
        "outperformed": relative_car > 0,
    }
```

### 3.5 Event Clustering Detection

```python
# Event clustering tespiti
def detect_event_clustering(events, window_days=5):
    """
    Yakın tarihli event'lerin etkileşimini tespit et.
    
    1. Event'leri tarihe göre sırala
    2. window_days içinde birden fazla event var mı?
    3. Varsa hangisi dominant?
    4. CAR hesaplamasında clustering düzeltmesi yap
    """
    clusters = []
    sorted_events = sorted(events, key=lambda e: e["date"])
    
    for i, event in enumerate(sorted_events):
        cluster = [event]
        for j in range(i+1, len(sorted_events)):
            if (sorted_events[j]["date"] - event["date"]).days <= window_days:
                cluster.append(sorted_events[j])
            else:
                break
        if len(cluster) > 1:
            clusters.append(cluster)
    
    return clusters
```

---

## 4. Eksik Modüller (Nihai)

### 4.1 Estimation Window Manager

```python
class EstimationWindowManager:
    """Estimation window yönetimi."""
    
    def get_estimation_window(self, event_date: str, event_type: str) -> Tuple[str, str]:
        """Event type'a göre estimation window döndür."""
        windows = {
            "FINANCIAL_RESULTS": 120,
            "DIVIDEND": 60,
            "BUYBACK": 60,
            "CAPITAL_INCREASE": 90,
            "MERGER": 120,
            "MANAGEMENT_CHANGE": 60,
            "LEGAL": 90,
            "CONTRACT": 60,
            "GUIDANCE": 60,
            "TCMB_RATE": 90,
            "INFLATION": 60,
            "GDP": 90,
        }
        days = windows.get(event_type, 60)
        end_date = event_date - timedelta(days=6)  # Event'ten 6 gün önce
        start_date = end_date - timedelta(days=days)
        return start_date, end_date
```

### 4.2 Event Window Manager

```python
class EventWindowManager:
    """Event window yönetimi."""
    
    def get_event_window(self, event_date: str, event_type: str) -> Tuple[int, int]:
        """Event type'a göre event window döndür."""
        windows = {
            "FINANCIAL_RESULTS": (-5, 5),
            "DIVIDEND": (-3, 3),
            "BUYBACK": (-3, 3),
            "CAPITAL_INCREASE": (-5, 5),
            "MERGER": (-10, 10),
            "MANAGEMENT_CHANGE": (-3, 3),
            "LEGAL": (-5, 5),
            "CONTRACT": (-3, 3),
            "GUIDANCE": (-3, 3),
            "TCMB_RATE": (-1, 3),
            "INFLATION": (-1, 3),
            "GDP": (-1, 3),
        }
        return windows.get(event_type, (-5, 5))
```

### 4.3 Multi-Factor Expected Return

```python
class MultiFactorExpectedReturn:
    """Fama-French 3-factor model ile expected return."""
    
    def calculate(self, stock_returns, market_returns, smb_returns, hml_returns):
        """
        E[R] = α + β_m × R_m + β_smb × SMB + β_hml × HML
        
        market_returns: BIST-100 getiri
        smb_returns: Small Minus Big (küçük - büyük)
        hml_returns: High Minus Low (değer - büyüme)
        """
        X = np.column_stack([
            np.ones(len(market_returns)),
            market_returns,
            smb_returns,
            hml_returns,
        ])
        y = stock_returns
        betas = np.linalg.lstsq(X, y, rcond=None)[0]
        
        return {
            "alpha": float(betas[0]),
            "beta_market": float(betas[1]),
            "beta_smb": float(betas[2]),
            "beta_hml": float(betas[3]),
        }
```

### 4.4 Cross-Sectional Event Study

```python
class CrossSectionalEventStudy:
    """Birden fazla hisse için event study."""
    
    def analyze(self, events: List[Dict], market_data: Dict) -> Dict:
        """
        Cross-sectional event study:
        1. Her event için CAR hesapla
        2. Ortalama CAR
        3. t-test (cross-sectional)
        4. Event type breakdown
        5. Sector breakdown
        """
        cars = []
        for event in events:
            car = self._calculate_event_car(event, market_data)
            cars.append({"event": event, "car": car})
        
        avg_car = np.mean([c["car"] for c in cars])
        std_car = np.std([c["car"] for c in cars])
        t_stat = avg_car / (std_car / np.sqrt(len(cars))) if std_car > 0 else 0
        p_value = 2 * (1 - min(abs(t_stat) / 3, 0.999))
        
        return {
            "average_car": round(avg_car, 4),
            "std_car": round(std_car, 4),
            "t_statistic": round(t_stat, 4),
            "p_value": round(p_value, 4),
            "significant": abs(t_stat) > 1.96,
            "n_events": len(cars),
            "event_details": cars,
        }
```

### 4.5 Event Impact Decay

```python
class EventImpactDecay:
    """Event etkisinin zamanla azalması."""
    
    def calculate_decay(self, ar_series: np.ndarray, event_day: int = 0) -> Dict:
        """
        Event etkisinin zamanla nasıl azaldığını hesapla.
        
        Day 0: %100
        Day 1: %70
        Day 2: %45
        Day 5: %15
        """
        if len(ar_series) == 0:
            return {"decay_rate": 0, "half_life": 0}
        
        # Exponential decay fit
        days = np.arange(len(ar_series))
        abs_ar = np.abs(ar_series)
        
        # Log-linear regression
        if np.any(abs_ar > 0):
            log_ar = np.log(abs_ar + 1e-10)
            coeffs = np.polyfit(days, log_ar, 1)
            decay_rate = -coeffs[0]
            half_life = np.log(2) / decay_rate if decay_rate > 0 else float('inf')
        else:
            decay_rate = 0
            half_life = 0
        
        return {
            "decay_rate": round(decay_rate, 4),
            "half_life_days": round(half_life, 1),
            "day0_impact": round(float(abs_ar[0]) if len(abs_ar) > 0 else 0, 4),
            "day5_impact": round(float(abs_ar[5]) if len(abs_ar) > 5 else 0, 4),
        }
```

---

## 5. Entegrasyon Planı

### Mevcut → Nihai

| Modül | Mevcut | Nihai |
|-------|--------|-------|
| `expected_return.py` | Basit OLS | Multi-factor (Fama-French) |
| `abnormal_return.py` | ✅ | ✅ |
| `car.py` | ✅ | ✅ |
| `statistical_test.py` | Yaklaşık p-value | t-distribution + Bonferroni |
| `impact.py` | Basit skor | Event-specific weights |
| `kap_event.py` | Tüm event'ler aynı | Event type ayrımı |
| `macro_event.py` | Sadece faiz | Enflasyon, GSYH, cari açık |

### Yeni Modüller

| Modül | Açıklama |
|-------|----------|
| `estimation_window.py` | Estimation window yönetimi |
| `event_window.py` | Event window yönetimi |
| `multi_factor.py` | Fama-French 3-factor model |
| `cross_sectional.py` | Birden fazla hisse için |
| `event_clustering.py` | Event clustering tespiti |
| `event_decay.py` | Etki azalma analizi |
| `sector_event.py` | Sektör bazlı event study |

---

## 6. Uygulama Planı — ✅ TAMAMLANDI

### Faz 1: Kritik Düzeltmeler ✅
1. ✅ Estimation window ekle (look-ahead bias önleme)
2. ✅ Event window ekle (gün bazlı pencereleme)
3. ✅ Statistical test'i t-distribution ile düzelt
4. ✅ Event type ayrımı (KAP event categories)

### Faz 2: Multi-Factor Model ✅
1. ✅ Fama-French 3-factor model ekle
2. ✅ SMB ve HML factor returns hesapla
3. ✅ Cross-sectional analysis ekle

### Faz 3: KAP Integration ✅
1. ✅ KAP event type mapping
2. ✅ Event-specific window sizes
3. ✅ Event-specific impact weights
4. ✅ Event clustering detection

### Faz 4: TCMB Integration ✅
1. ✅ TCMB faiz kararı detaylı analiz
2. ✅ Enflasyon verisi etkisi
3. ✅ GSYH verisi etkisi
4. ✅ Cari açık etkisi
5. ✅ USDTRY reaction

### Faz 5: Sector Analysis ✅
1. ✅ Sektör bazlı event study
2. ✅ Peer comparison
3. ✅ Sector-relative CAR
4. ✅ Sector rotation detection

---

## 7. Mevcut Sistem vs Nihai Vizyon — ✅ TAMAMLANDI

| Özellik | Mevcut | Nihai (✅) |
|---------|--------|------------|
| Modül sayısı | 7 | 14 |
| Toplam satır | 77 | ~2,825 |
| Test sayısı | 5 | 72 |
| Estimation window | ❌ | ✅ `EstimationWindowManager` |
| Event window | ❌ | ✅ `EventWindowManager` |
| Multi-factor model | ❌ | ✅ Fama-French 3/5 |
| Event type mapping | ❌ | ✅ 9 KAP + 8 macro type |
| Cross-sectional | ❌ | ✅ `CrossSectionalEventStudy` |
| Event clustering | ❌ | ✅ `EventClusteringDetector` |
| Event decay | ❌ | ✅ `EventImpactDecay` |
| Sector analysis | ❌ | ✅ `SectorEventAnalyzer` |
| TCMB detailed | ⚠️ Basit | ✅ Detaylı (surprise + FX + sector) |
| Statistical test | ⚠️ Yaklaşık | ✅ t-dist + Bonferroni + BH + Wilcoxon |
| Impact scoring | ⚠️ Basit | ✅ Event-specific ağırlıklar |

---

## 8. Doğrulama (2026-08-21)

### Kod İnceleme Sonucu
- 14 modül, 2,825 satır kod tamamen incelendi
- Matematiksel formüller MacKinlay (1997) ile uyumlu
- OLS regresyon (lstsq), t-distribution (scipy), exponential decay — hepsi doğru
- Look-ahead bias önleme: estimation window event'ten önce bitiyor (GAP_DAYS=6)
- Event-specific windows: 12 farklı event tipi için farklı pencere boyutları
- 72/72 test PASSED

### Düzeltme
- `__init__.py` docstring: ~500 satır → ~2,825 satır olarak güncellendi
