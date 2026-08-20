# Event Study Modülü — Güncel Durum Raporu

**Tarih:** 2026-08-21
**Analiz:** EVENT-STUDY-NIHAI-SPEC.md vs Gerçek Kod Karşılaştırması

---

## Modül Yapısı (14 dosya, 2,825 satır)

| Modül | Satır | Sınıf/Fonksiyon | Amaç |
|-------|-------|-----------------|------|
| `kap_event.py` | 376 | 5 | KAP açıklaması event study |
| `macro_event.py` | 338 | 5 | TCMB, enflasyon, GSYH event study |
| `cross_sectional.py` | 246 | 1 | Cross-sectional analysis + regresyon |
| `expected_return.py` | 238 | 7 | Multi-factor expected return (Market, FF3, FF5) |
| `statistical_test.py` | 223 | 5 | t-distribution, Bonferroni, BH, Wilcoxon |
| `sector_event.py` | 205 | 1 | Sektör bazlı event study + peer comparison |
| `impact.py` | 144 | 2 | Event-specific etki skoru (0-100) |
| `event_clustering.py` | 165 | 1 | Event clustering tespiti + düzeltme |
| `multi_factor.py` | 164 | 2 | Fama-French factor hesaplama |
| `event_decay.py` | 163 | 1 | Exponential decay + half-life |
| `event_window.py` | 141 | 1 | Event window yönetimi |
| `estimation_window.py` | 130 | 1 | Estimation window (look-ahead bias önleme) |
| `car.py` | 102 | 6 | CAR, sub-windows, AAR, CAAR |
| `__init__.py` | 101 | 0 | Package exports |
| `abnormal_return.py` | 89 | 2 | AR hesaplama (single + batch) |

---

## Spec Uyumluluk Özeti

| # | Madde | Durum | Not |
|---|-------|-------|-----|
| **Metodoloji (MacKinlay 1997)** | | | |
| 1 | Estimation window [t-120, t-6] | ✅ TAM | `EstimationWindowManager` — event type'a göre değişken |
| 2 | Event window [t-5, t+5] | ✅ TAM | `EventWindowManager` — 12 event type için farklı pencereler |
| 3 | Expected return (Market Model) | ✅ TAM | OLS: E[R] = α + β × R_m |
| 4 | Expected return (Fama-French 3) | ✅ TAM | E[R] = α + β_m×R_m + β_smb×SMB + β_hml×HML |
| 5 | Expected return (Fama-French 5) | ✅ TAM | + β_rmw×RMW + β_cma×CMA |
| 6 | Abnormal return | ✅ TAM | AR = R_actual - E[R_expected] |
| 7 | Cumulative AR | ✅ TAM | CAR = Σ AR + sub-windows + series |
| 8 | Statistical test (t-distribution) | ✅ TAM | scipy.stats.t, df = n - n_params |
| 9 | Confidence interval | ✅ TAM | %95 GA: CAR ± t_crit × σ(CAR) |
| 10 | Multiple testing (Bonferroni) | ✅ TAM | Adjusted α = α / n_tests |
| 11 | Multiple testing (BH FDR) | ✅ TAM | Benjamini-Hochberg düzeltmesi |
| 12 | Non-parametrik (Wilcoxon) | ✅ TAM | Normal dağılmayan CAR'lar için |
| **KAP Event** | | | |
| 13 | Event type mapping (9 tip) | ✅ TAM | FINANCIAL_RESULTS, DIVIDEND, BUYBACK, vb. |
| 14 | Keyword-based classification | ✅ TAM | `classify_kap_event()` |
| 15 | Event-specific windows | ✅ TAM | Her tip için farklı estimation/event window |
| 16 | Batch analysis | ✅ TAM | `analyze_kap_events_batch()` |
| **Macro Event** | | | |
| 17 | TCMB faiz kararı | ✅ TAM | Surprise, direction, BIST CAR, FX reaction |
| 18 | Enflasyon (TÜFE) | ✅ TAM | `analyze_macro_event()` |
| 19 | GSYH | ✅ TAM | |
| 20 | Cari açık | ✅ TAM | |
| 21 | PPI | ✅ TAM | |
| 22 | USDTRY reaksiyonu | ✅ TAM | |
| 23 | Sektör breakdown | ✅ TAM | |
| 24 | Faiz-enflasyon tutarlılığı | ✅ TAM | TIGHT/NEUTRAL/LOOSE/VERY_LOOSE |
| **İleri Analiz** | | | |
| 25 | Cross-sectional analysis | ✅ TAM | Ortalama CAR, t-test, breakdown |
| 26 | Regression (CAR = f(features)) | ✅ TAM | OLS regresyon + p-values |
| 27 | Event clustering | ✅ TAM | Cluster tespit + CAR düzeltmesi |
| 28 | Event decay | ✅ TAM | Exponential decay + half-life |
| 29 | Sector analysis | ✅ TAM | Peer comparison + rotation detection |
| 30 | AAR/CAAR | ✅ TAM | Average ve Cumulative Average AR |

---

## Matematiksel Kontrol

| Formül | Uygulama | Durum |
|--------|----------|-------|
| E[R] = α + β×R_m (Market Model) | `expected_return.py:_market_model()` | ✅ OLS lstsq |
| E[R] = α + β_m×R_m + β_smb×SMB + β_hml×HML | `expected_return.py:_fama_french_3()` | ✅ |
| AR = R_stock - E[R] | `abnormal_return.py:calculate_abnormal_return()` | ✅ |
| CAR = Σ AR | `car.py:calculate_car()` | ✅ |
| t = CAR / (σ(AR) × √n) | `statistical_test.py:test_significance()` | ✅ |
| p = 2×(1 - T_cdf(\|t\|, df)) | `statistical_test.py` | ✅ scipy.stats.t |
| BH: p_adj(i) = p(i) × n / rank(i) | `statistical_test.py:benjamini_hochberg_correction()` | ✅ |
| Decay: \|AR\| = A×exp(-λ×t) | `event_decay.py` | ✅ log-linear fit |
| Half-life: t½ = ln(2)/λ | `event_decay.py` | ✅ |

---

## Açık Kararlar

### 1. Fama-French Factor Verisi
BIST için SMB/HML/RMW/CMA factor'leri harici veri kaynağından gelmeli. Mevcut kod factor'leri parametre olarak alıyor ama otomatik hesaplama yok.

**Seçenekler:**
- A) BIST hisselerinden otomatik factor hesapla (FamaFrenchFactors.classify_stocks ile)
- B) Harici API'den çek (AKSHARE, Matriks)
- C) Mevcut parametrik yapı yeterli

### 2. Event Window → Trading Day Dönüştürme
Mevcut kod calendar day kullanıyor. BIST'te trading day farkı var (hafta sonu, tatiller).

**Seçenekler:**
- A) Trading calendar entegrasyonu (market_calendar.py ile)
- B) Calendar day approximation yeterli

---

## Test Sonuçları

```
tests/test_event_study_nihai.py — 72 passed, 0 failed (3.51s)
```
