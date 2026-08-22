# 04 — Event Study Modülü

## Rolü

Event Study modülü, ALPHA BIST sisteminin "olay etkisi analiz" katmanıdır. KAP açıklamaları, makro veri açıklamaları (TCMB faiz, enflasyon, GSYH) ve sektör olaylarının hisse fiyatları üzerindeki etkisini akademik metodolojiyle (MacKinlay, 1997) ölçer. Abnormal return, CAR, istatistiksel anlamlılık, etki skoru ve decay analizi ile olayların piyasa üzerindeki etkisini nicel olarak değerlendirir.

## Katman Haritası

```
┌─────────────────────────────────────────────────────────────────────┐
│                      EVENT STUDY MODÜLÜ                             │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  ┌─────────────────────────────────────────────────────────────┐   │
│  │                    kap_event.py                              │   │
│  │  KAP açıklamaları için detaylı event study                  │   │
│  │  Event type mapping · Window sizes · Clustering detection   │   │
│  └──────────────────────────┬──────────────────────────────────┘   │
│                             │                                       │
│  ┌──────────────────────────▼──────────────────────────────────┐   │
│  │              expected_return.py                              │   │
│  │  Market Model (OLS) · Fama-French 3/5 Factor               │   │
│  │  Newey-West HAC standard errors                             │   │
│  └──────────────────────────┬──────────────────────────────────┘   │
│                             │                                       │
│  ┌──────────────────────────▼──────────────────────────────────┐   │
│  │              abnormal_return.py                              │   │
│  │  AR = R_actual - E[R_expected]                              │   │
│  │  Market Model + Fama-French desteği                         │   │
│  └──────────────────────────┬──────────────────────────────────┘   │
│                             │                                       │
│  ┌──────────────────────────▼──────────────────────────────────┐   │
│  │                    car.py                                    │   │
│  │  CAR = Σ AR · Alt pencereler · CAR serisi · AAR · CAAR     │   │
│  └──────────────────────────┬──────────────────────────────────┘   │
│                             │                                       │
│  ┌──────────────────────────▼──────────────────────────────────┐   │
│  │              statistical_test.py                             │   │
│  │  t-test · Cross-sectional t-test · Bonferroni · BH FDR     │   │
│  │  Wilcoxon (non-parametrik)                                  │   │
│  └──────────────────────────┬──────────────────────────────────┘   │
│                             │                                       │
│  ┌──────────────────────────▼──────────────────────────────────┐   │
│  │                    impact.py                                 │   │
│  │  Event type'a göre özelleştirilmiş etki skoru (0-100)       │   │
│  │  Decay analizi entegrasyonu                                 │   │
│  └─────────────────────────────────────────────────────────────┘   │
│                                                                     │
│  ┌──────────────────┐  ┌──────────────────┐  ┌─────────────────┐  │
│  │ estimation_      │  │ event_window.py  │  │ trading_        │  │
│  │ window.py        │  │                  │  │ calendar.py     │  │
│  │ (Model param.    │  │ (Event window    │  │ (BIST iş günleri│  │
│  │  tahmini)        │  │  boyutları)      │  │  takvimi)       │  │
│  │ Trading day      │  │ Trading day      │  │ Tatil yönetimi  │  │
│  └──────────────────┘  └──────────────────┘  └─────────────────┘  │
│                                                                     │
│  ┌──────────────────┐  ┌──────────────────┐  ┌─────────────────┐  │
│  │ macro_event.py   │  │ sector_event.py  │  │ cross_          │  │
│  │ (TCMB, enflasyon │  │ (Sektör bazlı    │  │ sectional.py    │  │
│  │  GSYH, cari açık│  │  Peer comparison │  │ (Çoklu event    │  │
│  │  USDTRY reaksiyon│  │  Sektör rotasyon │  │  t-test,        │  │
│  │  )               │  │  )               │  │  regresyon)     │  │
│  └──────────────────┘  └──────────────────┘  └─────────────────┘  │
│                                                                     │
│  ┌──────────────────┐  ┌──────────────────┐  ┌─────────────────┐  │
│  │ event_decay.py   │  │ event_           │  │ multi_factor.py │  │
│  │ (Exponential     │  │ clustering.py    │  │ (Fama-French    │  │
│  │  decay, half-    │  │ (Yakın tarihli   │  │  3/5 Factor     │  │
│  │  life, pattern)  │  │  event           │  │  Model)         │  │
│  │                  │  │  etkileşimi)     │  │                 │  │
│  └──────────────────┘  └──────────────────┘  └─────────────────┘  │
│                                                                     │
│  ┌─────────────────────────────────────────────────────────────┐   │
│  │              fama_french_factors.py                          │   │
│  │  BIST için Fama-French factor return'leri (SMB, HML, RMW,  │   │
│  │  CMA) otomatik hesaplama. 2x3 sort, likidite filtresi.     │   │
│  └─────────────────────────────────────────────────────────────┘   │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

## Neden Bu Tasarım Seçimi?

| Karar | Neden |
|-------|-------|
| MacKinlay (1997) metodolojisi | Event study'nin akademik standardı. Estimation window ve event window ayrımı, abnormal return hesaplama, istatistiksel test — hepsi bu çerçevede. |
| Trading day kullanımı | Calendar day kullanmak hafta sonları/tatilleri window'a dahil eder → AR=0 günleri CAR bias'ı yaratır. BIST takvimi ile trading day dönüşümü kritik. |
| Estimation window gap | Event'ten 6 trading gün önce estimation window bitmeli — look-ahead bias'ı önler. |
| Fama-French 3/5 Factor desteği | Market Model tek faktörlü; Fama-French çok faktörlü model daha doğru expected return tahmini sağlar. Factor yoksa otomatik fallback. |
| Newey-West HAC | Otokorelasyon ve heteroskedastisitede OLS standard errors bias'lı. Newey-West düzeltmesi güvenilir t-statistic sağlar. |
| Event type mapping | Her KAP event tipi için farklı estimation window, event window ve ağırlık. FINANCIAL_RESULTS 120 gün estimation, MERGER ±10 gün event window. |
| Cross-sectional analysis | Birden fazla event için ortalama CAR, t-test, Wilcoxon, regresyon. Event type ve sektör bazlı breakdown. |
| Decay analizi | Event etkisinin zamanla nasıl azaldığını ölçer. Exponential decay modeli ile half-life hesaplama. Persistent vs fast decay pattern sınıflandırması. |
| Clustering detection | Yakın tarihli event'ler birbirini etkiler. Cluster tespiti ve CAR düzeltmesi (CAR / √cluster_size). |

## Uçtan Uca Veri Akışı

```
1. Girdi: KAP event (açıklama, tarih, ticker) veya makro event (tip, actual, expected)
         │
2. Event sınıflandırma:
   ├─ kap_event.classify_kap_event()
   │   ├─ Keyword matching (finansal, temettü, geri alım, birleşme, ...)
   │   └─ Event type + confidence + config (window sizes, weights)
   │
   └─ macro_event → MACRO_EVENT_TYPES config (TCMB, enflasyon, GSYH, ...)
         │
3. Window yönetimi:
   ├─ estimation_window.get_window()
   │   ├─ Trading calendar ile tarih hesaplama
   │   ├─ Event type'a göre uzunluk (60-120 trading gün)
   │   └─ Gap: event'ten 6 trading gün önce bitiş
   │
   └─ event_window.get_window()
       ├─ Event type'a göre offset (-10,+10) arası
       └─ Trading calendar ile tarih dönüşümü
         │
4. Expected return modeli:
   └─ expected_return.calculate_expected_return()
       ├─ Market Model: E[R] = α + β × R_market (OLS)
       ├─ Fama-French 3: + SMB + HML
       ├─ Fama-French 5: + RMW + CMA
       └─ Newey-West HAC standard errors (opsiyonel)
         │
5. Abnormal return:
   └─ abnormal_return.calculate_abnormal_return()
       ├─ AR = R_stock - (α + β×R_m + β_smb×SMB + β_hml×HML)
       └─ Batch: birden fazla hisse için toplu hesaplama
         │
6. CAR hesaplama:
   └─ car.calculate_car() + calculate_car_sub_windows()
       ├─ CAR = Σ AR (full window)
       ├─ Alt pencereler: pre-event, event-day, post-event
       ├─ CAR serisi (kümülatif)
       └─ AAR / CAAR (çoklu event ortalaması)
         │
7. İstatistiksel test:
   └─ statistical_test.test_significance()
       ├─ t-test: t = CAR / (σ(AR) × √n)
       ├─ %95 güven aralığı
       ├─ Cross-sectional t-test (çoklu event)
       ├─ Bonferroni düzeltmesi (multiple testing)
       ├─ Benjamini-Hochberg FDR (daha az muhafazakâr)
       └─ Wilcoxon signed-rank (non-parametrik)
         │
8. Etki skoru:
   └─ impact.calculate_event_impact()
       ├─ Event type'a göre ağırlıklar (significance, volume, statistical, magnitude)
       ├─ Etki seviyesi: VERY_HIGH / HIGH / MEDIUM / LOW
       └─ Decay analizi (AR serisi varsa)
         │
9. Ek analizler:
   ├─ event_decay → Exponential decay, half-life, pattern (PERSISTENT/SLOW/MODERATE/FAST)
   ├─ event_clustering → Cluster tespiti, CAR düzeltmesi
   ├─ cross_sectional → Ortalama CAR, t-test, regresyon, event type/sector breakdown
   ├─ sector_event → Peer comparison, sektör rotasyonu tespiti
   └─ macro_event → TCMB surprise, USDTRY reaksiyon, sektör breakdown
```

## Dosya Bazlı Sorumluluk Tablosu

| Dosya | Sorumluluk |
|-------|-----------|
| `abnormal_return.py` | Abnormal return hesaplama. AR = R_actual - E[R_expected]. Market Model ve Fama-French desteği. Toplu hesaplama (batch). |
| `car.py` | Cumulative Abnormal Return. CAR = Σ AR. Alt pencereler (pre/event/post). CAR serisi. AAR (Average Abnormal Return). CAAR (Cumulative Average Abnormal Return). |
| `kap_event.py` | KAP açıklamaları için detaylı event study. 9 event type mapping (FINANCIAL_RESULTS, DIVIDEND, BUYBACK, CAPITAL_INCREASE, MERGER, MANAGEMENT_CHANGE, LEGAL, CONTRACT, GUIDANCE). Keyword-based sınıflandırma. Estimation + event window ayrımı. Hacim analizi. Toplu analiz + cross-sectional entegrasyonu. |
| `statistical_test.py` | İstatistiksel anlamlılık testleri. t-distribution test (CAR=0 hipotezi). Cross-sectional t-test. Bonferroni multiple testing düzeltmesi. Benjamini-Hochberg FDR. Wilcoxon signed-rank (non-parametrik). |
| `estimation_window.py` | Estimation window yönetimi. Trading day bazlı (MacKinlay 1997). Event type'a göre uzunluk (60-120 trading gün). Gap: event'ten 6 trading gün önce bitiş. BIST takvimi entegrasyonu. Veri kalite kontrolü (min coverage %70). |
| `event_window.py` | Event window yönetimi. Trading day bazlı offset'ler. Event type'a göre pencere boyutları (±3, ±5, ±10). BIST takvimi ile tarih dönüşümü. Alt pencereler (pre/event/post). Event günlerine hizalama. |
| `expected_return.py` | Expected return modeli. Market Model (OLS). Fama-French 3-Factor. Fama-French 5-Factor. Newey-West HAC standard errors (otokorelasyon düzeltmesi). Factor yoksa otomatik fallback. |
| `impact.py` | Event etki skoru (0-100). Event type'a göre ağırlıklar (significance, volume, statistical, magnitude). Etki seviyesi sınıflandırması. Decay analizi entegrasyonu. Toplu etki analizi. |
| `cross_sectional.py` | Cross-sectional event study. Birden fazla event için ortalama CAR, t-test, Wilcoxon. Event type ve sektör bazlı breakdown. CAR'ı event features'a karşı regresyon analizi. |
| `event_decay.py` | Event etkisi decay analizi. Exponential decay modeli (|AR(t)| = A × exp(-λ×t)). Half-life hesaplama (ln(2)/λ). Pattern sınıflandırması: PERSISTENT, SLOW_DECAY, MODERATE_DECAY, FAST_DECAY. Toplu decay analizi. |
| `event_clustering.py` | Event clustering tespiti. Yakın tarihli event'leri tarihe göre cluster'lara ayırma. Cluster boyutuna göre CAR düzeltmesi (CAR / √cluster_size). Cluster istatistikleri. |
| `macro_event.py` | Makro event analizi. TCMB faiz kararı (surprise, direction, USDTRY reaksiyonu, sektör breakdown). Genel makro event (enflasyon, GSYH, CPI, PPI, cari açık, işsizlik, sanayi üretimi). Faiz-enflasyon tutarlılık kontrolü. |
| `sector_event.py` | Sektör bazlı event study. Peer comparison (aynı sektördeki hisseleri karşılaştırma). Sektör-relative CAR. Sektör rotasyonu tespiti (inflow/outflow sektörler). BIST sektör-stok eşleştirmesi. |
| `multi_factor.py` | Fama-French Multi-Factor Model. fit() ile estimation window'dan parametre tahmini. predict() ile expected return. FamaFrenchFactors: SMB, HML, RMW, CMA hesaplama. Hisse sınıflandırma (small/big, value/growth). |
| `fama_french_factors.py` | BIST için Fama-French factor return builder. 2x3 sort metodolojisi. SMB, HML, RMW, CMA günlük hesaplama. Likidite filtresi (min 100K TL hacim, min 50M TL piyasa değeri). yfinance ile veri çekme. Factor series → numpy array dönüşümü. |
| `trading_calendar.py` | BIST iş günleri takvimi. Sabit tatiller (Yılbaşı, 23 Nisan, 1 Mayıs, 19 Temmuz, 15 Temmuz, 30 Ağustos, 29 Ekim). Değişken tatiller (Ramazan/Kurban Bayramı — holidays.json). Calendar ↔ Trading day dönüşümü. Event window ve estimation window tarih hesaplama. |

## Tasarım İlkeleri ve Kırmızı Çizgiler

1. **Estimation window ve event window AYRI olmalı.** Estimation window event'ten önce bitmeli (gap = 6 trading gün). Aksi halde look-ahead bias.
2. **Trading day, calendar day değil.** Hafta sonları ve tatiller window'a dahil edilmemeli. BIST takvimi ile otomatik dönüşüm.
3. **Factor verisi yoksa fallback.** Fama-French factor'leri mevcut değilse Market Model'e otomatik düşülür; hata ile durdurulmaz.
4. **Multiple testing düzeltmesi.** Birden fazla hipotez testi yapıldığında Bonferroni veya BH FDR uygulanmalı; aksi halde false positive oranı artar.
5. **Cluster tespiti zorunlu.** Yakın tarihli event'ler birbirini etkiler; CAR düzeltmesi uygulanmazsa etki abartılır.
6. **Türkiye'ye özgü düzeltmeler.** TCMB faiz kararı, USDTRY reaksiyonu, enflasyon etkisi — bunlar BIST'e özgü ve dikkate alınmalı.

## Bilinen Sınırlamalar

- `trading_calendar.py` → holidays.json dosyası manuel güncellenmeli; Ramazan/Kurban Bayramı tarihleri her yıl değişir.
- `fama_french_factors.py` → yfinance ile çalışır; gerçek zamanlı veri akışı yoktur. Fundamental veriler (book_value, ROE) yfinance'dan gelir; BIST'e özgü veri kaynakları (KAP, Finnet) entegre edilmeli.
- `expected_return.py` → Newey-West HAC lag sayısı manuel belirlenmeli; otomatik lag seçimi (BIC/AIC) yok.
- `kap_event.py` → Keyword-based sınıflandırma; NLP tabanlı daha gelişmiş sınıflandırma gerekli.
- `macro_event.py` → Sektör-stok eşleştirmesi hard-coded; dinamik sektör graph entegrasyonu gerekli.
- `event_decay.py` → Sadece exponential decay modeli; power law veya diğer decay modelleri desteklenmiyor.
- `cross_sectional.py` → Regresyon analizi için minimum veri kontrolü zayıf; küçük sample'larda sonuçlar güvenilir olmayabilir.

## Cross-Reference

- **Scanner modülü** → `event_scanner.py` KAP event verilerini tüketir; event skoru hesaplamasında event study sonuçlarını kullanabilir.
- **Backtest modülü** → `event_replay.py` event study mantığını kullanır; KAP event verileri backtest'te event-driven sinyal üretimi için beslenir.
- **Factors modülü** → `fama_french_factors.py` event study'de expected return modeli için Fama-French factor return'leri üretir. `fama_french.py` factor skorları ile çapraz referans.
- **Features katmanı** → Event window verileri feature olarak backtest ve scanner'a beslenebilir.
- **ML katmanı** → Event etki skorları ML modeli için feature olarak kullanılabilir.
