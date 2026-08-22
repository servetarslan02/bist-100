# 03 — Factors Modülü

## Rolü

Factors modülü, ALPHA BIST sisteminin "çok boyutlu hisse değerlendirme" katmanıdır. Fama-French faktör modeli, Piotroski F-Score, Altman Z-Score, Beneish M-Score gibi akademik modelleri BIST'e uyarlayarak hisseleri çok boyutlu skorlar. Faktör rotasyonu, korelasyon analizi ve performans takibi ile strateji optimizasyonuna destek sağlar.

## Katman Haritası

```
┌─────────────────────────────────────────────────────────────────┐
│                       FACTORS MODÜLÜ                            │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │                    fama_french.py                        │   │
│  │  8 faktör: Value, Momentum, Quality, Size, Low Vol,     │   │
│  │  Dividend, Leverage, BIST-specific                      │   │
│  │  Cross-sectional z-score normalization                  │   │
│  │  Rejime göre ağırlık                                    │   │
│  └──────────────────────────┬──────────────────────────────┘   │
│                             │                                   │
│  ┌──────────────┐  ┌───────┴──────┐  ┌─────────────────────┐  │
│  │ piotroski.py │  │ ranking.py   │  │ factor_rotation.py  │  │
│  │ (F-Score)    │  │ (Multi-Factor│  │ (Rejim bazlı        │  │
│  │ 9 kriter     │  │  Sıralama)   │  │  rotasyon)          │  │
│  │ Ağırlıklı    │  │ Risk-adjusted│  │ Momentum-based      │  │
│  └──────────────┘  │ Sector-nötr  │  │ Dynamic weighting   │  │
│                    └──────────────┘  └─────────────────────┘  │
│                                                                 │
│  ┌──────────────┐  ┌──────────────┐  ┌─────────────────────┐  │
│  │ altman.py    │  │ beneish.py   │  │ bist_anomalies.py   │  │
│  │ (Z-Score)    │  │ (M-Score)    │  │ (BIST'e özgü        │  │
│  │ İflas tahmini│  │ Manipülasyon │  │  anomaliler)        │  │
│  │ TR düzeltmeli│  │ tespiti      │  │ 8+ anomaly/faktör   │  │
│  └──────────────┘  └──────────────┘  └─────────────────────┘  │
│                                                                 │
│  ┌──────────────────┐  ┌──────────────────┐                    │
│  │ factor_          │  │ factor_time_     │                    │
│  │ correlation.py   │  │ series.py        │                    │
│  │ (Korelasyon      │  │ (Trend analizi   │                    │
│  │  matrisi, VIF,   │  │  Momentum        │                    │
│  │  diversifikasyon)│  │  Mevsimsellik)   │                    │
│  └──────────────────┘  └──────────────────┘                    │
│                                                                 │
│  ┌──────────────────┐                                           │
│  │ performance.py   │                                           │
│  │ (Faktör          │                                           │
│  │  performans      │                                           │
│  │  metrikleri)     │                                           │
│  └──────────────────┘                                           │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

## Neden Bu Tasarım Seçimi?

| Karar | Neden |
|-------|-------|
| Fama-French 8 faktör | BIST'e özgü faktörler (FX sensitivity, inflation beta, foreign ownership) klasik 5 faktöre eklenmeli — Türkiye'de kur ve enflasyon kritik. |
| Cross-sectional z-score | Faktör skorları evren içi sıralamaya göre normalize edilir; mutlak değerden ziyade göreli konum önemli. |
| Piotroski F-Score (9 kriter) | Finansal sağlık değerlendirmesi için akademik kanıtlanmış model. Ağırlıklı ve detaylı — her kriter için değer, eşik ve sonuç döndürür. |
| Altman Z-Score (TR düzeltmeli) | Orijinal Altman (1968) Türkiye'ye uyarlanmalı — enflasyon, kur ve sektör düzeltmeleri kritik. |
| Beneish M-Score | Finansal manipülasyon tespiti. 8 değişken, orijinal Beneish (1999) katsayıları. Hem gerçek veriden hem raw index input'tan hesaplama desteği. |
| BIST anomalileri | Temettü, likidite, kur, enflasyon, faiz, sektör momentum, KAP sentiment, yabancı yatırımcı — BIST'e özgü anomaliler. |
| Faktör rotasyonu | Rejime göre faktör ağırlıkları değişmeli. BULL'da momentum, BEAR'da kalite/low-vol öne çıkar. |
| Sektör-nötr sıralama | Sektör etkisini ortadan kaldırarak saf faktör sinyali elde edilir. |

## Uçtan Uca Veri Akışı

```
1. Girdi: Universe (hisse listesi), finansal veriler, piyasa verileri
         │
2. Faktör skoru hesaplama:
   ├─ fama_french.calculate_factor_scores_batch()
   │   ├─ Her metrik için evren istatistikleri (median, std, percentiles)
   │   ├─ Percentile skor (z → CDF)
   │   └─ Yön düzeltmesi (düşük P/B = yüksek value skor)
   │
   ├─ piotroski.calculate_f_score()
   │   ├─ 9 kriter (kârlılık, nakit akışı, borç, likidite, verimlilik)
   │   └─ Kategori: STRONG (7-9), MODERATE (4-6), WEAK (0-3)
   │
   ├─ altman.calculate_z_score()
   │   ├─ 5 bileşen (WC/TA, RE/TA, EBIT/TA, Equity/Debt, Sales/TA)
   │   └─ Türkiye düzeltmesi (enflasyon × kur × sektör)
   │
   ├─ beneish.calculate_m_score()
   │   ├─ 8 index (DSRI, GMI, AQI, SGI, DEPI, SGAI, TATA, LVGI)
   │   └─ Manipülasyon riski: HIGH_RISK / MODERATE_RISK / LOW_RISK
   │
   └─ bist_anomalies.calculate_bist_anomalies_batch()
       ├─ 8 anomaly (temettü, likidite, kur, enflasyon, faiz, sektör, KAP, yabancı)
       └─ Ağırlıklı anomaly skoru (0-100)
         │
3. Çok faktörlü sıralama:
   └─ ranking.rank_stocks()
       ├─ Rejime göre ağırlık (BULL/BEAR/SIDEWAYS/HIGH_VOL)
       ├─ Sektör-nötr düzeltme (opsiyonel)
       ├─ Risk ayarlaması (risk_penalty)
       └─ Sıralama + factor_contributions
         │
4. Faktör rotasyonu:
   └─ factor_rotation.get_rotation_weights()
       ├─ Rejim tespiti (detect_regime)
       ├─ Hedef ağırlıklar (rejim → preferred/avoid faktörler)
       └─ Rotasyon gücüne göre ağırlık karışımı
         │
5. Analiz:
   ├─ factor_correlation.calculate_factor_correlation()
   │   ├─ Korelasyon matrisi, VIF uyarıları
   │   └─ Diversifikasyon skoru
   │
   ├─ factor_time_series.analyze_factor_trend()
   │   ├─ Trend yönü + gücü (lineer regresyon)
   │   └─ Mevsimsellik analizi
   │
   └─ performance.track_factor_performance()
       ├─ 10+ metrik (Sharpe, Sortino, Calmar, Max DD, Win Rate, ...)
       └─ Benchmark karşılaştırma (alpha, beta, IR, Treynor)
```

## Dosya Bazlı Sorumluluk Tablosu

| Dosya | Sorumluluk |
|-------|-----------|
| `fama_french.py` | Fama-French faktör skorları. 8 faktör tanımı (value, momentum, quality, size, low_vol, dividend, leverage, bist_specific). Cross-sectional percentile normalization. Rejime göre ağırlık (BULL, BEAR, SIDEWAYS, HIGH_VOL). Toplu hesaplama (batch). |
| `piotroski.py` | Piotroski F-Score. 9 kriter: net income > 0, operating CF > 0, ROA artıyor, CF > NI, leverage azalıyor, current ratio artıyor, seyreltme yok, gross margin artıyor, asset turnover artıyor. Ağırlıklı, detaylı (her kriter için değer/eşik/sonuç). Alt skorlar: kârlılık (4), borç/likidite (3), verimlilik (2). |
| `altman.py` | Altman Z-Score. Orijinal katsayılar (1.2, 1.4, 3.3, 0.6, 1.0). Türkiye düzeltmeleri: enflasyon (×0.85), kur (×0.90), sektör (BANKA ×1.10, ENERJI ×0.90, vb.). Bölge eşikleri: SAFE > 2.99, GREY > 1.81, DISTRESS. |
| `beneish.py` | Beneish M-Score. Orijinal katsayılar (1999). 8 bileşen: DSRI, GMI, AQI, SGI, DEPI, SGAI, TATA, LVGI. Hem gerçek veriden (current + previous) hem raw index input'tan hesaplama. Eşik: HIGH_RISK > -1.78, MODERATE_RISK > -2.22. |
| `bist_anomalies.py` | BIST'e özgü anomaliler. 8 anomaly: dividend_yield, liquidity_premium, fx_sensitivity, inflation_sensitivity, rate_sensitivity, sector_momentum, kap_sentiment, foreign_ownership. Ağırlıklı anomaly skoru (0-100). Yön düzeltmesi (v2.1: abs() kaldırıldı). |
| `factor_rotation.py` | Faktör rotasyonu stratejisi. Rejim tespiti (volatilite + trend + drawdown). Rejim-faktör eşleştirmesi (BULL → momentum, BEAR → quality/low_vol). Rotasyon gücüne göre ağırlık karışımı. Faktör momentum sinyali (top/bottom faktörler). |
| `ranking.py` | Çok faktörlü hisse sıralaması. Rejime göre ağırlık. Sektör-nötr düzeltme (sektör ortalaması çıkarma). Risk ayarlaması (risk_penalty = risk_score × risk_aversion). Factor contributions detayı. |
| `factor_correlation.py` | Faktörler arası korelasyon analizi. Korelasyon matrisi, ortalama korelasyon, diversifikasyon skoru. Yüksek korelasyonlu çiftler tespiti. VIF (Variance Inflation Factor) çoklu doğrusallık uyarısı. Rolling korelasyon serisi. |
| `factor_time_series.py` | Faktör zaman serisi analizi. Long-short faktör getirisi. Trend analizi (lineer regresyon, R², p-value). Faktör momentum (1d, 5d, 20d, 60d, 120d). Mevsimsellik analizi (aylık ortalama getiri). |
| `performance.py` | Faktör performans takibi. 10+ metrik: total return, annual return, volatility, Sharpe, Sortino, Calmar, max drawdown, win rate, best/worst day, skewness, kurtosis. Benchmark karşılaştırma: alpha, beta, tracking error, information ratio, Treynor ratio. Toplu analiz (batch). |

## Tasarım İlkeleri ve Kırmızı Çizgiler

1. **Yön düzeltmesi kritik.** Düşük P/B yüksek value skor, yüksek borç düşük leverage skor üretmeli. `abs()` kullanmak ihracatçı/ithalatçı şirketleri aynı skorlar (v2.1'de düzeltildi).
2. **Sahte veri uydurmak yasaktır.** Faktör hesaplama için gerekli veri yoksa varsayılan değer kullanılır ama sonuç "yetersiz veri" olarak işaretlenir.
3. **Cross-sectional normalization.** Faktör skorları evren içi sıralamaya göre normalize edilir; mutlak değer tek başına anlamsız.
4. **Rejime göre ağırlık.** BULL'da momentum %30, BEAR'da quality %30 — sabit ağırlık rejim değişimlerinde performans kaybına neden olur.
5. **Sektör-nötr opsiyonel.** Sektör etkisini ortadan kaldırmak için sektör ortalaması çıkarma; ama sektör rotasyonu stratejisi için sektör maruziyeti gerekli.
6. **Risk cezası doğru yön.** risk_score yüksek = yüksek risk = düşük skor olmalı. Eski formül (total_score × risk_score/100) risk_score=50'de skoru yarıya indiriyordu; yeni formül (1 - risk_score/100 × risk_aversion) daha doğru.

## Bilinen Sınırlamalar

- `fama_french.py` → Factor skorları statik ağırlık kullanır; dinamik ağırlık optimizasyonu (Black-Litterman vb.) yok.
- `altman.py` → Türkiye düzeltme katsayıları sabit; enflasyon ve kur değişimine göre dinamik ayarlama gerekli.
- `beneish.py` → Sadece 2 dönem karşılaştırması yapar; çok dönemli trend analizi yok.
- `bist_anomalies.py` → FX/inflation/rate beta hesaplama için piyasa verisi gerekir; veri yoksa varsayılan 0 kullanılır.
- `factor_rotation.py` → Rejim tespiti basit (volatilite + trend + drawdown); daha gelişmiş HMM veya ML tabanlı rejim tespiti gerekli.
- `ranking.py` → Risk aversion sabit (0.5); yatırımcı tercihine göre dinamik ayarlama yok.
- `performance.py` → Treynor ratio beta ~0 olduğunda None döndürür; bu durum UI'da gösterilmeli.

## Cross-Reference

- **Scanner modülü** → `opportunity_engine.py` fundamental_score ve valuation_score parametreleri olarak factor skorlarını tüketir. `alpha_scanner.py` momentum ve volume anomaly skorlarını kullanır.
- **Backtest modülü** → `engine_v4.py` canonical scoring modunda fundamental feature'ları (Motor4) factor modülünden alır.
- **Event Study modülü** → `fama_french_factors.py` event study'de expected return modeli için Fama-French factor return'leri üretir.
- **Features katmanı** → Factor skorları feature olarak backtest ve scanner'a beslenir.
