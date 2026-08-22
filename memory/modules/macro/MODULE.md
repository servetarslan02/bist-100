# MACRO — Makro Ekonomik Analiz Motoru

## Giriş

Macro servisi, Türkiye ve küresel makro ekonomik verileri işleyerek BIST-100 üzerindeki etkilerini ölçen kapsamlı bir motorudur. TCMB faiz politikasından enflasyona, döviz kurundan CDS spread'ine kadar geniş bir makro değişken yelpazesini feature'lara dönüştürür. 18 Python modülünden oluşan bu servis, surprise modeli, rejim tespiti, şok etki analizi, stres testi, korelasyon takibi ve dinamik sektör hassasiyeti gibi ileri düzey analizleri içerir.

## Katman Haritası

```
┌─────────────────────────────────────────────────────────────────┐
│                      MACRO SERVICE                               │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │  config/macro_config.py — Merkezi Konfigürasyon           │   │
│  │  (Pydantic BaseModel, tüm eşikler ve parametreler)        │   │
│  │  • SurpriseConfig: small/medium/large threshold           │   │
│  │  • RegimeConfig: smoothing, min_duration, confidence      │   │
│  │  • SensitivityConfig: rolling_window, min_samples         │   │
│  │  • StressTestConfig: 7 predefined scenarios               │   │
│  │  • CorrelationConfig: tracked_pairs, breakdown_threshold  │   │
│  │  • DecayConfig: half_life_by_shock_type                   │   │
│  │  • CalendarConfig: pre_event_alert_days                   │   │
│  │  • HistoricalStoreConfig: max_history_days (5 yıl)        │   │
│  └──────────────────────────────────────────────────────────┘   │
│                                                                 │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │  FEATURE COMPUTATION LAYER (Ham Veri → Feature)           │   │
│  │                                                          │   │
│  │  ┌──────────────┐ ┌──────────────┐ ┌──────────────────┐ │   │
│  │  │ tcmb.py      │ │ inflation.py │ │ fx.py            │ │   │
│  │  │ • policy_rate│ │ • cpi_yoy    │ │ • usdtry_level   │ │   │
│  │  │ • real_rate  │ │ • ppi_yoy    │ │ • usdtry_zscore  │ │   │
│  │  │ • rate_      │ │ • core_cpi   │ │ • usdtry_momentum│ │   │
│  │  │   surprise   │ │ • cpi_ppi_   │ │ • usdtry_vol_20d │ │   │
│  │  │ • policy_    │ │   spread     │ │ • usdtry_regime  │ │   │
│  │  │   stance     │ │ • inflation_ │ │ • usdtry_        │ │   │
│  │  │ • rate_      │ │   regime     │ │   percentile     │ │   │
│  │  │   differential│ │ • inflation_ │ │ • eurtry_level   │ │   │
│  │  │ • wacf       │ │   surprise   │ │ • eurtry_usdtry  │ │   │
│  │  │ • corridor_  │ │ • inflation_ │ │   _ratio         │ │   │
│  │  │   width      │ │   trend      │ │                  │ │   │
│  │  └──────────────┘ └──────────────┘ └──────────────────┘ │   │
│  │  ┌──────────────┐ ┌──────────────┐ ┌──────────────────┐ │   │
│  │  │ cds.py       │ │ credit.py    │ │ current_account  │ │   │
│  │  │ • cds_5y     │ │ • credit_    │ │ .py              │ │   │
│  │  │ • cds_change │ │   growth_yoy │ │ • ca_balance     │ │   │
│  │  │ • cds_zscore │ │ • credit_    │ │ • ca_gdp_ratio   │ │   │
│  │  │ • cds_       │ │   gdp_ratio  │ │ • ca_trend       │ │   │
│  │  │   momentum   │ │ • credit_    │ │ • ca_improving   │ │   │
│  │  │ • cds_       │ │   regime     │ │ • ca_12m_avg     │ │   │
│  │  │   percentile │ │ • credit_    │ │                  │ │   │
│  │  │ • cds_risk_  │ │   trend      │ │                  │ │   │
│  │  │   level      │ │              │ │                  │ │   │
│  │  └──────────────┘ └──────────────┘ └──────────────────┘ │   │
│  └──────────────────────────────────────────────────────────┘   │
│                                                                 │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │  ANALYSIS LAYER (Feature → Analiz)                        │   │
│  │                                                          │   │
│  │  ┌──────────────────────────────────────────────────┐    │   │
│  │  │ surprise_model.py — Macro Surprise Model          │    │   │
│  │  │ • Beklenti vs gerçek sürpriz hesaplama            │    │   │
│  │  │ • Beklenti kaynakları: tcmb_survey, swap_pricing, │    │   │
│  │  │   consensus_forecast, trend_extrapolation          │    │   │
│  │  │ • Magnitude: NONE / SMALL / MEDIUM / LARGE        │    │   │
│  │  │ • Direction: IN_LINE / HIGHER / LOWER /           │    │   │
│  │  │              HAWKISH / DOVISH                      │    │   │
│  │  │ • Sektör-Macro surprise hassasiyet matrisi        │    │   │
│  │  │ • Decay modeli (half-life ile etki azalır)        │    │   │
│  │  │ • Birikimli surprise (son 3 ay)                   │    │   │
│  │  └──────────────────────────────────────────────────┘    │   │
│  │                                                          │   │
│  │  ┌──────────────────────────────────────────────────┐    │   │
│  │  │ regime_detector.py — Macro Regime Detector        │    │   │
│  │  │ • 6 Rejim:                                        │    │   │
│  │  │   EXPANSION: düşük faiz, düşük enflasyon          │    │   │
│  │  │   CONTRACTION: yüksek faiz, yüksek enflasyon      │    │   │
│  │  │   STAGFLATION: yüksek enflasyon, zayıf büyüme     │    │   │
│  │  │   REFLATION: düşük faiz, yükselen enflasyon       │    │   │
│  │  │   RISK_ON: düşük VIX, yükselen S&P500             │    │   │
│  │  │   RISK_OFF: yüksek VIX, düşen S&P500              │    │   │
│  │  │ • Skor bazlı tespit (her rejim için ağırlıklı)    │    │   │
│  │  │ • Smoothing: min_regime_duration_days (chatter     │    │   │
│  │  │   önleme)                                          │    │   │
│  │  │ • Rejim feature'ları üretme (dummy, composite)    │    │   │
│  │  └──────────────────────────────────────────────────┘    │   │
│  │                                                          │   │
│  │  ┌──────────────────────────────────────────────────┐    │   │
│  │  │ impact_analyzer.py — Macro Impact Analyzer        │    │   │
│  │  │ • Şok etkisi = magnitude × sensitivity            │    │   │
│  │  │ • Decay modeli: half-life ile etki zamanla azalır │    │   │
│  │  │ • Birikimli etki: birden fazla şokun toplamı      │    │   │
│  │  │ • Sektör ve şirket bazlı etki                     │    │   │
│  │  │ • Decay eğrisi görselleştirme                     │    │   │
│  │  └──────────────────────────────────────────────────┘    │   │
│  │                                                          │   │
│  │  ┌──────────────────────────────────────────────────┐    │   │
│  │  │ stress_test.py — Macro Stress Test                │    │   │
│  │  │ • 7 önceden tanımlı senaryo:                      │    │   │
│  │  │   USDTRY +10%, TCMB +500bp, VIX +50%,            │    │   │
│  │  │   Oil +20%, Global Risk-Off, Inflation +5%,       │    │   │
│  │  │   BIST -10%                                        │    │   │
│  │  │ • Özel senaryo desteği                            │    │   │
│  │  │ • Breaking point analizi (binary search)          │    │   │
│  │  │ • Pozisyon bazlı detay                            │    │   │
│  │  └──────────────────────────────────────────────────┘    │   │
│  │                                                          │   │
│  │  ┌──────────────────────────────────────────────────┐    │   │
│  │  │ correlation_tracker.py — Macro Correlation        │    │   │
│  │  │ • Rolling correlation matrix (60 gün)             │    │   │
│  │  │ • Korelasyon bozulma tespiti                      │    │   │
│  │  │ • Anlamlılık testi (p-value)                      │    │   │
│  │  │ • Takip edilen çiftler:                           │    │   │
│  │  │   usdtry-gold, rate-inflation, vix-bist100,       │    │   │
│  │  │   oil-energy, sp500-bist100, cds-usdtry           │    │   │
│  │  └──────────────────────────────────────────────────┘    │   │
│  │                                                          │   │
│  │  ┌──────────────────────────────────────────────────┐    │   │
│  │  │ factor_decomposition.py — Factor Decomposition    │    │   │
│  │  │ • Getiriyi makro faktörlere ayrıştırma            │    │   │
│  │  │ • 7 faktör: usdtry, rate, inflation, oil, gold,  │    │   │
│  │  │   global_market, vix                              │    │   │
│  │  │ • Residual (açıklanamayan kısım)                  │    │   │
│  │  │ • Top faktör tespiti                              │    │   │
│  │  └──────────────────────────────────────────────────┘    │   │
│  │                                                          │   │
│  │  ┌──────────────────────────────────────────────────┐    │   │
│  │  │ sensitivity_engine.py — Dynamic Sensitivity       │    │   │
│  │  │ • 60 günlük rolling korelasyon ile sektör-makro  │    │   │
│  │  │ • Sensitivity trend tracking (artıyor/azalıyor)   │    │   │
│  │  │ • Company-specific override (döviz borcu vb.)     │    │   │
│  │  │ • Factor decomposition entegrasyonu               │    │   │
│  │  │ • Anlamlılık testi (p-value)                      │    │   │
│  │  └──────────────────────────────────────────────────┘    │   │
│  └──────────────────────────────────────────────────────────┘   │
│                                                                 │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │  INFRASTRUCTURE LAYER                                     │   │
│  │                                                          │   │
│  │  ┌──────────────────────────────────────────────────┐    │   │
│  │  │ calendar_engine.py — Macro Calendar Engine        │    │   │
│  │  │ • TCMB PPK toplantı tarihleri (2026)              │    │   │
│  │  │ • TÜİK veri açıklama tarihleri                    │    │   │
│  │  │ • FOMC toplantı tarihleri                          │    │   │
│  │  │ • Olay öncesi hazırlık (beklenti toplama)         │    │   │
│  │  │ • Olay sonrası analiz tetikleme                    │    │   │
│  │  └──────────────────────────────────────────────────┘    │   │
│  │                                                          │   │
│  │  ┌──────────────────────────────────────────────────┐    │   │
│  │  │ calendar.py — Macro Calendar (Static)             │    │   │
│  │  │ • MACRO_EVENTS sabit olay listesi                  │    │   │
│  │  │ • get_upcoming_events()                            │    │   │
│  │  │ • get_event_impact()                               │    │   │
│  │  └──────────────────────────────────────────────────┘    │   │
│  │                                                          │   │
│  │  ┌──────────────────────────────────────────────────┐    │   │
│  │  │ historical_store.py — Macro Historical Store      │    │   │
│  │  │ • Point-in-time veri erişimi (look-ahead bias     │    │   │
│  │  │   yok)                                             │    │   │
│  │  │ • JSON-based storage                               │    │   │
│  │  │ • Backfill desteği                                 │    │   │
│  │  │ • 5 yıl maksimum geçmiş                           │    │   │
│  │  └──────────────────────────────────────────────────┘    │   │
│  └──────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────┘
```

## Neden Bu Tasarım Seçimi?

| Karar | Neden |
|-------|-------|
| **Feature-based mimari** | Ham makro veri (TCMB faiz, CPI, USDTRY) doğrudan kullanılmaz; z-score, momentum, percentile, regime gibi feature'lara dönüştürülür. Bu, ML modellerinin daha iyi öğrenmesini sağlar. |
| **Surprise Modeli** | Beklenti vs gerçek sürpriz, ham veriden daha bilgilendirici. TCMB faiz kararı piyasayı faiz seviyesi değil, sürpriz yönünde etkiler. |
| **6 Makro Rejim** | Klasik bull/bear yetersiz. STAGFLATION ve REFLATION gibi rejimler Türkiye ekonomisi için kritik. Skor bazlı + smoothing ile chatter önlenir. |
| **Decay Modeli (Half-Life)** | Şok etkisi zamanla azalır. Para politikası sürprizi 10 gün, global risk-off 3 gün half-life'a sahip. Bu, eski şokların ağırlığını doğru ayarlar. |
| **Dinamik Sensitivity** | Sabit sektör hassasiyeti yanıltıcı. 60 günlük rolling korelasyon ile hassasiyet zamanla değişir. Company-specific override ile döviz borcu gibi faktörler eklenir. |
| **7 Stres Testi Senaryosu** | "USDTRY +10% olursa portföy ne olur?" sorusunu cevaplar. Binary search ile breaking point bulunur. |
| **Korelasyon Takibi** | Korelasyon zamanla değişir. USDTRY-Gold ilişkisinin bozulması önemli bir sinyaldir. |
| **Factor Decomposition** | Toplam getiri = Σ(faktör katkısı) + residual. Hangi faktörün ne kadar katkı yaptığını bilmek risk yönetimi için kritik. |
| **Point-in-Time Store** | Backtest'te look-ahead bias'ı önlemek için sadece o tarihte bilinen veri kullanılır. |
| **Pydantic Config** | Tüm eşikler ve parametreler tek merkezden yönetilir. Hardcoded değerler yasaktır. |

## Uçtan Uca Veri Akışı

```
┌─────────────┐    ┌─────────────┐    ┌─────────────┐
│ TCMB Data   │    │ TÜİK Data   │    │ Market Data │
│ (faiz, WACF)│    │ (CPI, PPI)  │    │ (USDTRY,    │
│             │    │             │    │  VIX, CDS)  │
└──────┬──────┘    └──────┬──────┘    └──────┬──────┘
       │                  │                  │
       ▼                  ▼                  ▼
┌──────────────┐  ┌──────────────┐  ┌──────────────┐
│ tcmb.py      │  │ inflation.py │  │ fx.py / cds.py│
│ compute_     │  │ compute_     │  │ compute_     │
│ tcmb_features│  │ inflation_   │  │ fx_features /│
│              │  │ features     │  │ cds_features │
└──────┬───────┘  └──────┬───────┘  └──────┬───────┘
       │                 │                  │
       └────────────┬────┘──────────────────┘
                    │
                    ▼
┌──────────────────────────────────────────────────┐
│ Macro Feature Vector (tüm feature'lar birleşik)  │
│ • tcmb_policy_rate, tcmb_real_rate, tcmb_stance  │
│ • inf_cpi_level, inf_regime, inf_surprise        │
│ • fx_usdtry_zscore, fx_usdtry_momentum_20d       │
│ • cds_5y, cds_risk_level                         │
│ • credit_growth_yoy, ca_balance                  │
└──────────────────────┬───────────────────────────┘
                       │
          ┌────────────┼────────────┐
          │            │            │
          ▼            ▼            ▼
┌──────────────┐ ┌──────────────┐ ┌──────────────┐
│ surprise_    │ │ regime_      │ │ impact_      │
│ model.py     │ │ detector.py  │ │ analyzer.py  │
│              │ │              │ │              │
│ Beklenti vs  │ │ 6 Rejim:     │ │ Şok etkisi = │
│ gerçek       │ │ EXPANSION    │ │ magnitude ×  │
│ sürpriz      │ │ CONTRACTION  │ │ sensitivity  │
│ hesapla      │ │ STAGFLATION  │ │              │
│              │ │ REFLATION    │ │ Decay:       │
│ Magnitude:   │ │ RISK_ON      │ │ half-life    │
│ NONE/SMALL/  │ │ RISK_OFF     │ │ ile azalır   │
│ MEDIUM/LARGE │ │              │ │              │
│              │ │ Smoothing:   │ │ Birikimli    │
│ Sektör       │ │ min_duration │ │ etki:        │
│ hassasiyet   │ │ ile chatter  │ │ tüm şokların│
│ matrisi      │ │ önleme       │ │ toplamı      │
└──────┬───────┘ └──────┬───────┘ └──────┬───────┘
       │                │                │
       └────────────────┼────────────────┘
                        │
                        ▼
┌──────────────────────────────────────────────────┐
│ Macro Feature Output                              │
│ • surprise_tcmb_rate, surprise_cpi               │
│ • macro_regime_expansion_score, macro_regime_... │
│ • macro_regime_composite, macro_regime_duration  │
│ • impact_cumulative, impact_decay_factor         │
└──────────────────────┬───────────────────────────┘
                       │
          ┌────────────┼────────────┐
          │            │            │
          ▼            ▼            ▼
┌──────────────┐ ┌──────────────┐ ┌──────────────┐
│ stress_test  │ │ correlation_ │ │ sensitivity_ │
│ .py          │ │ tracker.py   │ │ engine.py    │
│              │ │              │ │              │
│ 7 senaryo:   │ │ Rolling 60g  │ │ Rolling 60g  │
│ USDTRY+10%   │ │ korelasyon   │ │ sektör-makro │
│ TCMB+500bp   │ │ matrisi      │ │ korelasyon   │
│ VIX+50%      │ │              │ │              │
│ Oil+20%      │ │ Bozulma      │ │ Company      │
│ Global RiskOff│ │ tespiti      │ │ override     │
│ Inflation+5% │ │              │ │ (döviz borcu)│
│ BIST-10%     │ │ Anlamlılık   │ │              │
│              │ │ testi        │ │ Factor       │
│ Breaking     │ │              │ │ decomposition│
│ point        │ │              │ │              │
└──────────────┘ └──────────────┘ └──────────────┘
                       │
                       ▼
┌──────────────────────────────────────────────────┐
│ Tüketici Servisler                                │
│ • Intelligence: macro_sensitivity.py → sektör     │
│   hassasiyet matrisi                               │
│ • Intelligence: regime.py → macro regime skorları  │
│   (%15 ağırlıkla intelligence rejimine katılır)    │
│ • Market State: component_states.py → macro_score  │
│ • Orchestrator: stres testi sonuçları              │
└──────────────────────────────────────────────────┘
```

## Dosya Bazlı Sorumluluk Tablosu

| Dosya | Sorumluluk | Feature Çıktısı |
|-------|-----------|-----------------|
| `config/macro_config.py` | Merkezi Pydantic konfigürasyonu — tüm eşikler ve parametreler | `MacroConfig` singleton |
| `tcmb.py` | TCMB faiz features: policy_rate, real_rate, rate_surprise, policy_stance, rate_differential, wacf | 10+ feature |
| `inflation.py` | Enflasyon features: cpi_yoy, ppi_yoy, core_cpi, cpi_ppi_spread, inflation_regime, surprise, trend | 12+ feature |
| `fx.py` | Döviz features: usdtry_level, zscore, momentum_20d, volatility_20d, percentile, regime, eurtry | 12+ feature |
| `cds.py` | CDS features: cds_5y, change_pct, zscore, momentum_20d, percentile, risk_level | 7+ feature |
| `credit.py` | Kredi features: credit_growth_yoy, credit_gdp_ratio, credit_regime, credit_trend | 5+ feature |
| `current_account.py` | Cari açık features: ca_balance, ca_gdp_ratio, ca_trend, ca_improving, ca_12m_avg | 5+ feature |
| `surprise_model.py` | Beklenti vs gerçek sürpriz, magnitude/direction, sektör hassasiyet matrisi, decay, birikimli surprise | `SurpriseResult`, `SurpriseImpact` |
| `regime_detector.py` | 6 makro rejim skor bazlı tespit, smoothing, rejim feature'ları üretme | `RegimeResult`, 15+ feature |
| `impact_analyzer.py` | Şok etkisi = magnitude × sensitivity, decay modeli, birikimli etki, decay eğrisi | `ImpactResult` |
| `stress_test.py` | 7 önceden tanımlı senaryo, özel senaryo, breaking point (binary search), pozisyon bazlı detay | `StressTestResult` |
| `correlation_tracker.py` | Rolling 60g korelasyon matrisi, bozulma tespiti, p-value, korelasyon feature'ları | `CorrelationResult`, 15+ feature |
| `calendar_engine.py` | TCMB PPK/FOMC tarihleri, olay öncesi beklenti toplama, olay sonrası surprise tetikleme | `MacroEvent` |
| `calendar.py` | Sabit makro olay listesi, yaklaşan olaylar, sektör etki haritası | `MACRO_EVENTS` dict |
| `historical_store.py` | Point-in-time veri deposu (JSON), backfill, look-ahead bias önleme | `MacroDataPoint` |
| `factor_decomposition.py` | Getiriyi 7 makro faktöre ayrıştırma, residual, top factor, explained ratio | `DecompositionResult` |
| `sensitivity_engine.py` | Rolling korelasyon ile dinamik sektör-makro hassasiyet, company override, factor decomposition | `SensitivityResult`, `CompanySensitivity` |

## Tasarım İlkeleri ve Kırmızı Çizgiler

### İlkeler
1. **Config-Driven**: Hardcoded eşik yok. Tüm parametreler `MacroConfig` Pydantic modelinden okunur.
2. **Point-in-Time**: Backtest'te sadece o tarihte bilinen veri kullanılır — look-ahead bias yasak.
3. **Decay Modeli**: Şok etkisi zamanla azalır. Half-life şok türüne göre değişir (monetary_policy: 10 gün, global_risk_off: 3 gün).
4. **Graceful Fallback**: Beklenti verisi yoksa surprise = 0 kabul edilir (belirsizlik = etki yok).
5. **Dinamik > Statik**: Sabit sektör hassasiyeti yerine 60 günlük rolling korelasyon.
6. **Smoothing**: Rejim geçişleri minimum süre filtresi ile düzeltilir (chatter önleme).

### Kırmızı Çizgiler
- ❌ Beklenti verisi yoksa surprise hesaplanmaz — 0 kabul edilir, uydurma yapılmaz.
- ❌ Rejim değişimi minimum `min_regime_duration_days` süresi dolmadan gerçekleşmez.
- ❌ Korelasyon anlamlı değilse (p-value > 0.05) kullanılmaz.
- ❌ Decay modelinde half-life × 5 gün geçmiş şoklar ihmal edilir.
- ❌ Historical store'da gelecek tarihli veri kaydedilemez.

## Bilinen Sınırlamalar

| Sınırlama | Açıklama |
|-----------|---------|
| **Beklenti verisi manuel** | TCMB faiz beklentisi otomatik çekilemez — manuel veya swap pricing'den gelmeli. |
| **Calendar tarihleri sabit** | TCMB PPK ve FOMC tarihleri hardcoded — yıl başında güncellenmeli. |
| **JSON storage** | `historical_store.py` JSON dosyası kullanır — büyük veri setlerinde performans sorunlu olabilir. |
| **Sektör hassasiyeti 10 sektör** | Varsayılan matris 10 sektör kapsar — daha detaylı sektör ayrımı gerekli olabilir. |
| **Scipy bağımlılığı** | `correlation_tracker.py` ve `sensitivity_engine.py` p-value hesaplaması için scipy gerektirir. |
| **CDS verisi dış kaynak** | CDS verisi dış API'den gelmeli — otomatik çekme mekanizması henüz yok. |
| **In-memory surprise history** | `_surprise_history` restart sonrası sıfırlanır. |

## Cross-Reference

- **Intelligence** → `macro_sensitivity.py` → `SECTOR_MACRO_SENSITIVITY` matrisi bu servisteki `sensitivity_engine.py` ile paylaşılır.
- **Intelligence** → `regime.py` → `macro_regime_detector.detect_regime()` çağrılır; macro regime skorları intelligence rejim skorlarına %15 ağırlıkla katılır.
- **Intelligence** → `world_state.py` → `WorldStateManager.update_from_macro()` macro verilerden world state günceller.
- **Market State** → `component_states.py` → `_compute_macro_state()` world_state dict'inden macro state belirler.
- **Orchestrator** → Stres testi sonuçları portföy risk yönetimi için kullanılır.
- **Config** → `MacroConfig` → Tüm alt modüller bu config'den parametre okur.
- **Event Bus** → `surprise_model.py` → Büyük surprise tespit edildiğinde event publish edilebilir.
