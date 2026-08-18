# Event Study Nihai Sistem

**Modül sayısı:** 14 | **Test sayısı:** 71 | **Metodoloji:** MacKinlay (1997)

## Modüller

| # | Modül | Satır | Fonksiyon/Sınıf | Açıklama |
|---|-------|-------|-----------------|----------|
| 1 | `estimation_window.py` | ~120 | `EstimationWindowManager` | Look-ahead bias önleme, estimation window yönetimi |
| 2 | `event_window.py` | ~130 | `EventWindowManager` | Gün bazlı pencereleme, alt pencereler |
| 3 | `expected_return.py` | ~200 | `calculate_expected_return()` | Market Model, Fama-French 3/5 factor |
| 4 | `abnormal_return.py` | ~80 | `calculate_abnormal_return()` | AR hesaplama, batch destekli |
| 5 | `car.py` | ~90 | `calculate_car()` | CAR, AAR, CAAR, sub-window CAR |
| 6 | `statistical_test.py` | ~170 | `test_significance()` | t-distribution, Bonferroni, BH FDR, Wilcoxon |
| 7 | `impact.py` | ~150 | `calculate_event_impact()` | Event-specific ağırlıklar, etki skoru (0-100) |
| 8 | `kap_event.py` | ~250 | `analyze_kap_event()` | KAP event sınıflandırma ve analiz |
| 9 | `macro_event.py` | ~280 | `analyze_tcmb_event()` | TCMB, enflasyon, GSYH, cari açık |
| 10 | `multi_factor.py` | ~150 | `MultiFactorModel` | Fama-French 3/5 factor model |
| 11 | `cross_sectional.py` | ~220 | `CrossSectionalEventStudy` | Cross-sectional analysis, regresyon |
| 12 | `event_clustering.py` | ~150 | `EventClusteringDetector` | Event clustering tespiti ve düzeltmesi |
| 13 | `event_decay.py` | ~160 | `EventImpactDecay` | Exponential decay, half-life hesaplama |
| 14 | `sector_event.py` | ~200 | `SectorEventAnalyzer` | Sektör bazlı analysis, peer comparison |

**Toplam:** ~2,450 satır, 14 modül, 71 test

## Pipeline

```
Event Detection → Estimation Window → Expected Return Model
    → Abnormal Return → CAR → Statistical Test → Impact Score
    → Cross-Sectional → Sector Analysis → Decay Analysis
```

## Kullanım

```python
from services.event_study import (
    # Managers
    EstimationWindowManager,
    EventWindowManager,
    MultiFactorModel,
    CrossSectionalEventStudy,
    EventClusteringDetector,
    EventImpactDecay,
    SectorEventAnalyzer,
    # Core functions
    calculate_expected_return,
    calculate_abnormal_return,
    calculate_car,
    test_significance,
    calculate_event_impact,
    analyze_kap_event,
    analyze_tcmb_event,
    analyze_macro_event,
)
```

## Event Types (KAP)

| Event Type | Estimation Window | Event Window | Beklenen Etki |
|------------|-------------------|--------------|---------------|
| FINANCIAL_RESULTS | 120 gün | [-5, +5] | HIGH |
| DIVIDEND | 60 gün | [-3, +3] | MEDIUM |
| BUYBACK | 60 gün | [-3, +3] | MEDIUM |
| CAPITAL_INCREASE | 90 gün | [-5, +5] | HIGH |
| MERGER | 120 gün | [-10, +10] | VERY_HIGH |
| MANAGEMENT_CHANGE | 60 gün | [-3, +3] | LOW |
| LEGAL | 90 gün | [-5, +5] | MEDIUM |
| CONTRACT | 60 gün | [-3, +3] | MEDIUM |
| GUIDANCE | 60 gün | [-3, +3] | MEDIUM |

## Makro Event Types

| Event Type | Açıklama | Estimation Window | Event Window |
|------------|----------|-------------------|--------------|
| TCMB_RATE | TCMB Faiz Kararı | 90 gün | [-1, +3] |
| INFLATION | Enflasyon (TÜFE) | 60 gün | [-1, +3] |
| GDP | GSYH Verisi | 90 gün | [-1, +3] |
| CPI | Tüketici Fiyat Endeksi | 60 gün | [-1, +3] |
| PPI | Üretici Fiyat Endeksi | 60 gün | [-1, +2] |
| CURRENT_ACCOUNT | Cari Açık | 60 gün | [-1, +3] |

## İstatistiksel Testler

- **t-test**: t-distribution (n-2 df), %95 güven aralığı
- **Cross-sectional t-test**: Birden fazla event için ortalam CAR testi
- **Bonferroni**: Multiple testing düzeltmesi (muhafazakâr)
- **Benjamini-Hochberg**: FDR düzeltmesi (daha az muhafazakâr)
- **Wilcoxon**: Non-parametrik alternatif

## Kaynaklar

- MacKinlay, A. C. (1997). Event Studies in Economics and Finance. Journal of Economic Literature.
- Fama, E. F., & French, K. R. (1993). Common Risk Factors in the Returns on Stocks and Bonds.
- ScienceDirect ESG Event Study (2025)
- jatss BIST-100 Event Study (2026)
- ScholarHub Interest Rate Event Study (2026)
