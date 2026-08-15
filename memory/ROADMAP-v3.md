# ALPHA BIST — ROADMAP v3.0

> **Felsefe:** "Yarın ne olacak?" değil → "Mevcut rejimde hangi risk-getiri profili avantajlı?"
> **Hedef:** Her gün BIST evrenini değerlendirip, risk-getiri açısından en avantajlı fırsatları sıralayan adaptif piyasa istihbarat sistemi.
> **Başlangıç:** 16 Ağustos 2026
> **Araştırma Kaynakları:**
> - Tan, Roberts, Zohren — Spatio-Temporal Momentum (Oxford-Man Institute, 2023)
> - Du — ML Enhanced Multi-Factor Trading (Chinese A-share, 2026)
> - Huang, Fan — Autonomous Factor Investing via Agentic AI (HKUST/Peking, 2026)
> - BIST'e özel: TMS 29 enflasyon muhasebesi, devre kesici, emir defteri manipülasyonu

---

## Temel Tasarım Kararları

Araştırma sonuçlarına göre sistemin temelini oluşturan 6 karar:

### 1. Mask-First Design (EN KRİTİK — +0.44 Sharpe etkisi)

**Problem:** Devre kesici, tavan/taban, halt edilmiş hisse fiyatları execute edilemez ama standart sistemler bu fiyatları kullanır. Bu, feature'ları, korelasyonları, rank'leri zehirler.

**Çözüm:** Veri yüklenirken Boolean tradability mask oluştur. Hiçbir hesaplama execute edilemeyen fiyat görmez.

**Etkilenen sistemler:**
- `services/features/calculator.py` — Tüm feature hesaplamaları mask-aware olmalı
- `services/features/extended_indicators.py` — Ichimoku, Fibonacci, VWAP dahil
- `services/ingestion/providers/yfinance_provider.py` — Veri çekerken mask oluştur
- `services/core/data_quality.py` — Tradability kontrolü ekle

### 2. Adjusted-MSE Loss (Yanlış yön 11× daha ağır ceza)

**Problem:** Model +5% tahmin ediyor ama gerçek -5% → normal MSE bunu hafif cezalandırır. Oysa yön yanlışlığı büyük kayıp demek.

**Çözüm:** Loss fonksiyonunda yanlış yönlü tahminleri 11× daha ağır cezalandır.

**Etkilenen sistemler:**
- `services/learning/integrated_learning.py` — Hata analizi bu loss'a göre olmalı
- `services/backtest/engine.py` — Backtest metrikleri yön doğruluğunu ayrı ölçmeli

### 3. Cross-Sectional + Temporal Birleşik Model

**Problem:** Mevcut sistemde momentum (temporal) ve relatif güç (cross-sectional) ayrı motorlar. Oxford araştırması gösteriyor ki bunları birleştiren tek model daha iyi performans veriyor.

**Çözüm:** 7 motorun çıktısını ayrı ayrı hesapla ama tek bir ranking modelinde birleştir.

**Etkilenen sistemler:**
- `services/scanner/opportunity_engine.py` — Mevcut 10-component scoring yerine learning-to-rank
- Yeni: `services/ml/ranking_model.py` — LightGBM Ranker

### 4. Learning-to-Rank (Regresyon değil, sıralama optimizasyonu)

**Problem:** "Bu hisse %5 yükselecek" diye tahmin etmek çok gürültülü. "Bu hisse BIST'in en iyi %10'unda olacak" demek daha güvenilir.

**Çözüm:** LightGBM Ranker ile doğrudan cross-sectional sıralama optimizasyonu.

**Etkilenen sistemler:**
- `services/ml/` — Yeni ranking modeli
- `services/learning/integrated_learning.py` — Label'lar ranking-based olmalı
- `services/backtest/engine.py` — Precision@K, IC metrikleri

### 5. Spatio-Temporal Feature Set

**Problem:** Her hisse bağımsız değerlendiriliyor. Oysa diğer hisselerin momentum'u da bilgi taşıyor.

**Çözüm:** Feature set'e cross-sectional features ekle (sektör ortalaması, BIST rank, peer korelasyon).

**Etkilenen sistemler:**
- `services/features/calculator.py` — Cross-sectional feature'lar ekle
- `services/features/store.py` — Feature'lar ticker bazlı değil, evren bazlı hesaplanmalı

### 6. Walk-Forward Validation (Zorunlu)

**Problem:** Backtest'te gelecek veriyi kullanma riski. Model geçmişi ezberleyebilir.

**Çözüm:** Her model değerlendirmesi walk-forward ile. Purge + embargo ile data leakage koruması.

**Etkilenen sistemler:**
- `services/backtest/walk_forward.py` — Purge/embargo ekle
- `services/learning/integrated_learning.py` — Out-of-sample test zorunlu
- `services/ml/` — Eğitim pipeline'ı walk-forward ile

---

## Mimari (v3.0)

```
VERİ KATMANI (Mask-First)
    BIST 472+ hisse → Tradability Mask → Temiz veri
    ↓
FEATURE KATMANI (Spatio-Temporal)
    1. Teknik (RSI, MACD, BB, ATR, vb.) — mask-aware
    2. Cross-sectional (rank, sector relative, peer correlation)
    3. Fundamental (sektörel normalize, FCF merkezli, TMS29 düzeltmeli)
    4. Hacim-mikroyapı (tick rule, VWAP, hacim-fiyat ilişkisi)
    5. Makro (USDTRY, faiz, VIX, emtia — z-score ile normalize)
    6. KAP/haber (LLM extraction: etki, süre, belirsizlik)
    7. Katalizör (yaklaşan olaylar, beklenmediklik)
    ↓
MOTOR KATMANI (7 Ayrı Motor)
    1. Relatif Güç (1d/5d/20d/60d/120d vs BIST + sektör)
    2. Momentum + Trend (eğim, ivme, değişim yönü)
    3. Hacim + Mikroyapı (tick rule, VWAP sapma)
    4. Fundamental (sektörel normalize, bilanço kalitesi)
    5. KAP + Haber (yapılandırılmış extraction)
    6. Katalizör (yaklaşan olaylar)
    7. "Neden Düşüyor?" (market/sector/company/liquidity/panic)
    ↓
RANKING KATMANI (Learning-to-Rank)
    7 motorun çıktısı → LightGBM Ranker → Cross-sectional sıralama
    Target: P(5d relatif pozitif), P(20d > sektör), P(20d > +5%)
    Loss: Adjusted-MSE (yanlış yön 11× ağır)
    ↓
RİSK KATMANI
    Konsantrasyon, korelasyon, volatilite, likidite
    ↓
PORTFÖY KATMANI
    Pozisyon büyüklüğü, rebalance, işlem maliyeti
    ↓
DEĞERLENDİRME KATMANI
    Alpha, Precision@K, IC, Sharpe, Max DD, Turnover
    Walk-forward validation (purge + embargo)
    ↓
ÖĞRENME KATMANI
    Feature importance feedback → Feature ağırlıkları
    Regime accuracy → Confidence ayarlaması
    Drift detection → Model yeniden eğitim tetikleme
```

---

## Faz Planı

### FAZ 1: Veri Altyapısı & Mask-First Design ⬜
**Amaç:** Temiz, güvenilir, mask-aware veri pipeline'ı
**Süre:** ~1 hafta
**Araştırma gerekçesi:** Du (2026) — mask-first design tek başına +0.44 Sharpe katkısı

- [ ] **Tradability Mask** — Devre kesici, tavan/taban, halt, veri yok durumları için Boolean mask
  - Etkilenen: `calculator.py`, `extended_indicators.py`, `data_quality.py`
  - Kural: Hiçbir feature hesaplaması mask=0 olan fiyatı görmemeli
- [ ] **Cross-Sectional Rank Features** — Her gün tüm BIST'te sıralama
  - `rank_return_1d`, `rank_return_5d`, `rank_volume_zscore`, `rank_rsi`
  - Etkilenen: `calculator.py` — evren bazlı hesaplama gerekli
- [ ] **Sektör Relative Features** — Hisse vs sektör ortalaması
  - `sector_relative_return_5d`, `sector_relative_momentum`
  - Etkilenen: `calculator.py`, `bist_universe.py` (sektör mapping)
- [ ] **Label Generation Pipeline** — Gelecek getiri → target label
  - `y_5d = return_5d_beyond_t` (gelecek 5 gün getiri)
  - `y_20d_vs_sector = return_20d - sector_return_20d`
  - `y_rank = cross_sectional_rank(y_5d)` — percentile
  - Etkilenen: Yeni `services/labels/generator.py`
- [ ] **Walk-Forward Framework** — Purge + embargo ile data leakage koruması
  - Purge: train sonundan test başına kadar gap bırak
  - Embargo: test sonundan bir sonraki train başına kadar gap
  - Etkilenen: `services/backtest/walk_forward.py`

**Çıkış kriteri:** 472 hisse için mask-aware feature'lar hesaplanıyor, label'lar üretiliyor, walk-forward çalışıyor.

---

### FAZ 2: 7 Motor — Feature Mühendisliği ⬜
**Amaç:** Her motor için temiz, anlamlı feature'lar
**Süre:** ~2 hafta
**Araştırma gerekçesi:** Spatio-temporal momentum (Oxford) — cross-sectional + temporal birleşik feature'lar

#### Motor 1: Relatif Güç
- [ ] 1d/5d/20d/60d/120d relatif getiri (vs BIST100)
- [ ] Sektör relatif gücü
- [ ] Peer relatif gücü (aynı sektördeki hisseler)
- [ ] Relatif güç trendi (güçlüyor mu zayıflıyor mı — son 5 gün vs önceki 5 gün)
- [ ] Cross-sectional rank (tüm BIST'te percentile)

#### Motor 2: Momentum + Trend
- [ ] Trend eğimi (20 günlük lineer regresyon slope + R²)
- [ ] Momentum ivmesi (roc_5d değişim yönü: -12% → -7% → -3% → +1% = pozitif ivme)
- [ ] Yeni yüksek/düşük tespiti (20d/60d/120d)
- [ ] Breakout başarısızlığı (kırılım sonrası geri dönüş)
- [ ] Drawdown + toparlanma gücü
- [ ] Hareketli ortalama konumu (SMA20/50/200'e göre mesafe)

#### Motor 3: Hacim + Mikroyapı
- [ ] Hacim percentile (z-score değil — daha robust)
- [ ] Hacim-fiyat yönü ilişkisi (yükseliş+patlama ≠ düşüş+patlama)
- [ ] Yükseliş günlerinde hacim vs düşüş günlerinde hacim (son 10 gün)
- [ ] Tick rule (yaklaşık: close > open → alış, close < open → satış)
- [ ] VWAP sapması (günlük VWAP'a göre fiyata mesafe)
- [ ] Turnover (hisse bazlı likidite)

#### Motor 4: Fundamental
- [ ] Sektörel normalize edilmiş çarpanlar (F/K, PD/DD, FD/FAVÖK — sektör medyanına göre)
- [ ] FCF yield (enflasyon muhasebesinden arındırılmış)
- [ ] Bilanço kalitesi skoru (nakit/borç, FCF tutarlılığı, marj trendi)
- [ ] TMS 29 düzeltmesi (parasal pozisyon kâr/zarar arındırması)
- [ ] Kârlılık trendi (marj genişliyor/daralıyor — son 4 çeyrek)

#### Motor 5: KAP + Haber
- [ ] KAP olay sınıflandırması (temettü, bedelsiz, ihale, yatırım, dava, vb.)
- [ ] Beklenmediklik skoru (tarihsel ortalamaya göre ne kadar farklı)
- [ ] Etki yönü + büyüklüğü + süresi + belirsizliği
- [ ] Sentiment momentum (son 3 gün vs önceki 3 gün)

#### Motor 6: Katalizör
- [ ] Yaklaşan bilanço tarihi
- [ ] Yaklaşan temettü tarihi
- [ ] Yaklaşan bedelsiz/bedelli
- [ ] Yaklaşan genel kurul
- [ ] Beklenmediklik + belirsizlik skoru

#### Motor 7: "Neden Düşüyor?"
- [ ] Market selloff tespiti (BIST genel %3+ düşüş)
- [ ] Sector selloff tespiti (sektör %5+ düşüş)
- [ ] Company-specific (KAP/haber)
- [ ] Liquidity event (hacim patlaması + fiyat düşüşü)
- [ ] Technical breakdown (destek kırılımı)
- [ ] Temporary panic (hızlı düşüş + hızlı toparlanma)
- [ ] Düşüş nedeni geçici mi kalıcı mı olasılığı

**Çıkış kriteri:** 472 hisse için 7 motorun tümü çalışıyor, ~100+ feature hesaplanıyor.

---

### FAZ 3: Ranking Modeli ⬜
**Amaç:** 7 motorun çıktısını tek bir sıralama modelinde birleştir
**Süre:** ~1 hafta
**Araştırma gerekçesi:** Oxford — spatio-temporal birleşik model; Du — LightGBM Ranker; Huang — non-linear factor aggregation

- [ ] **LightGBM Ranker** — Doğrudan sıralama optimizasyonu (regresyon değil)
  - Input: 7 motorun tüm feature'ları (~100+)
  - Target: Cross-sectional rank (gelecek 5 gün getiri percentile'ı)
  - Objective: `lambdarank` veya `rank_xendcg`
  - Etkilenen: Yeni `services/ml/ranking_model.py`
- [ ] **Adjusted-MSE Loss** — Yanlış yön cezası
  - Model +5% tahmin edip gerçek -5% ise → 11× ceza
  - Etkilenen: `services/ml/ranking_model.py`
- [ ] **Rejim-Aware Training** — Farklı rejimlerde ayrı ağırlıklar
  - BULL rejimde momentum ağırlığı yüksek
  - BEAR rejimde defensif ağırlığı yüksek
  - Etkilenen: `services/ml/ranking_model.py`, `services/intelligence/regime.py`
- [ ] **Feature Importance Tracking** — Hangi feature gerçekten katkı sağlıyor
  - SHAP values per feature
  - Permutation importance
  - Regime-conditioned importance (farklı rejimlerde farklı feature'lar önemli)
  - Etkilenen: `services/learning/integrated_learning.py`
- [ ] **Ensemble** — Birden fazla model (LightGBM + kurallı fallback)
  - LightGBM başarısız olursa kural tabanlı sistem devreye girer
  - Etkilenen: `services/ml/ranking_model.py`

**Çıkış kriteri:** Model walk-forward ile eğitiliyor, Precision@K hesaplanıyor, feature importance raporu çıkıyor.

---

### FAZ 4: Backtest & Değerlendirme ⬜
**Amaç:** Modeli doğru ölçmek, overfitting tespit etmek
**Süre:** ~1 hafta
**Araştırma gerekçesi:** Du — mask-first backtest; Huang — strict out-of-sample; Oxford — walk-forward

- [ ] **Walk-Forward Backtest** — Purge + embargo ile
  - Train: 252 gün, Test: 63 gün, Step: 21 gün
  - Purge: 5 gün (train sonu → test arası gap)
  - Embargo: 5 gün (test sonu → bir sonraki train arası gap)
  - Etkilenen: `services/backtest/walk_forward.py`
- [ ] **Değerlendirme Metrikleri**
  - Alpha (BIST'e göre fazla getiri)
  - Precision@K (ilk 5/10/20 hisseden kaç tanesi iyi)
  - Information Coefficient (IC — model skoru ile gelecek getiri korelasyonu)
  - Hit rate (yön doğruluğu)
  - Sharpe ratio (risk-adjusted)
  - Max drawdown
  - Turnover (işlem sıklığı)
  - Etkilenen: `services/backtest/engine.py`
- [ ] **Data Augmentation** — Block-bootstrap GBM
  - Sentetik fiyat yolları üret → eğitim verisini çoğalt
  - Etkilenen: `services/ml/augmentation.py` [YENİ]
- [ ] **Overfitting Tespiti** — Deflated Sharpe Ratio
  - Backtest sayısı arttıkça Sharpe'ın güvenilirliği düşer
  - Multiple testing düzeltmesi
  - Etkilenen: `services/backtest/engine.py`

**Çıkış kriteri:** Walk-forward backtest çalışıyor, metrikler hesaplanıyor, overfitting kontrolü yapılıyor.

---

### FAZ 5: Risk & Portföy ⬜
**Amaç:** Kurumsal kalite risk yönetimi
**Süre:** ~1 hafta
**Araştırma gerekçesi:** Du — Ledoit-Wolf covariance; Oxford — volatility targeting

- [ ] **Kovaryans Tahmini** — Ledoit-Wolf shrinkage
  - Basit sample covariance yerine regularized tahmin
  - Etkilenen: `services/risk/covariance.py` [YENİ]
- [ ] **Volatility Targeting** — Portföy volatilitesini hedefle
  - Düşük volatilite → kaldıraç artır
  - Yüksek volatilite → pozisyon küçült
  - Etkilenen: `services/risk/position_sizing.py`
- [ ] **Portföy Optimizasyonu** — Markowitz + transaction cost
  - Minimum variance değil, risk-adjusted return最大化
  - İşlem maliyetini dahil et
  - Etkilenen: `services/portfolio/optimization.py` [YENİ]
- [ ] **Rebalance Kuralları** — Ne zaman portföyü yeniden dengeler
  - Turnover constraint (maksimum işlem sıklığı)
  - Threshold-based rebalance (pozisyon sapması belirli eşiği aşınca)
  - Etkilenen: `services/portfolio/main.py`
- [ ] **Pozisyon Büyüklüğü** — Kelly criterion benzeri
  - Win rate × average win / average loss
  - Etkilenen: `services/risk/position_sizing.py`

**Çıkış kriteri:** Portföy optimizasyonu çalışıyor, volatility targeting aktif, rebalance kuralları tanımlı.

---

### FAZ 6: KAP + Haber Motoru (LLM) ⬜
**Amaç:** Basit pozitif/negatif değil, yapılandırılmış extraction
**Süre:** ~1 hafta
**Araştırma gerekçesi:** Huang — agentic AI factor discovery; BIST'e özel KAP yapısı

- [ ] **KAP Metin Çıkarma** — LLM ile yapılandırılmış
  - Olay türü (temettü, bedelsiz, ihale, yatırım, dava, vb.)
  - Finansal etki yönü + büyüklüğü
  - Beklenmediklik (tarihsel ortalamaya göre)
  - Belirsizlik (bilgi eksikliği)
  - Etkilenen: `services/intelligence/kap_extractor.py` [YENİ]
- [ ] **Sektör Zincirleme Etkisi** — Knowledge graph üzerinden
  - Petrol↑ → Energy sector → TUPRS cost impact
  - Etkilenen: `services/intelligence/knowledge_graph.py`
- [ ] **Agentic Factor Discovery** (opsiyonel) — LLM ile yeni factor keşfi
  - LLM'e sor: "BIST'te hangi feature'lar getiri tahmininde işe yarayabilir?"
  - Ekonomik gerekçe şart (data mining koruması)
  - Etkilenen: `services/agents/research_agent.py`

**Çıkış kriteri:** KAP'tan gelen bildirimler yapılandırılmış olarak çıkarılıyor, sektör zincirleme etkisi çalışıyor.

---

### FAZ 7: Dashboard & API ⬜
**Amaç:** Kullanılabilir arayüz
**Süre:** ~1 hafta

- [ ] **Overview** — Rejim, breadth, fırsatlar, portföy, learning durumu
- [ ] **Market Radar** — 472+ hisse tarama, filtreleme, sıralama
- [ ] **Fırsat Detayı** — 7 motor skoru + neden + güven + risk profili
- [ ] **Portföy** — Pozisyonlar, P&L, drawdown, risk metrikleri
- [ ] **Backtest** — Strateji performansı, walk-forward sonuçları
- [ ] **Learning** — Model doğruluk, feature importance, drift
- [ ] **API** — Tüm endpoint'ler

**Çıkış kriteri:** Dashboard çalışıyor, tüm sayfalar veri gösteriyor, API endpoint'leri çalışıyor.

---

## Etkilenen Sistemler Özeti

| Sistem | FAZ | Değişiklik |
|--------|-----|-----------|
| `calculator.py` | 1, 2 | Mask-aware, cross-sectional features |
| `extended_indicators.py` | 1 | Mask-aware |
| `data_quality.py` | 1 | Tradability kontrolü |
| `yfinance_provider.py` | 1 | Mask oluştur |
| `bist_universe.py` | 2 | Sektör mapping güçlendir |
| `walk_forward.py` | 1, 4 | Purge + embargo |
| `engine.py` (backtest) | 4 | Precision@K, IC, Deflated Sharpe |
| `position_sizing.py` | 5 | Volatility targeting, Kelly |
| `portfolio/main.py` | 5 | Rebalance kuralları |
| `opportunity_engine.py` | 3 | Learning-to-rank ile değişecek |
| `regime.py` | 3 | Rejim-aware training |
| `integrated_learning.py` | 3, 4 | Adjusted-MSE, feature importance |
| `knowledge_graph.py` | 6 | Sektör zincirleme etkisi |
| `risk/main.py` | 5 | Ledoit-Wolf covariance |
| Yeni: `ml/ranking_model.py` | 3 | LightGBM Ranker |
| Yeni: `labels/generator.py` | 1 | Label generation |
| Yeni: `ml/augmentation.py` | 4 | Block-bootstrap GBM |
| Yeni: `risk/covariance.py` | 5 | Ledoit-Wolf |
| Yeni: `portfolio/optimization.py` | 5 | Markowitz + transaction cost |
| Yeni: `intelligence/kap_extractor.py` | 6 | LLM KAP extraction |

---

## Temel Prensipler

1. **Mask-first** — Execute edilemeyen fiyat kullanma
2. **Ranking, not prediction** — "En iyi %10'da mı?" sor, "yükselir mi?" sorma
3. **Adjusted loss** — Yanlış yön ağır ceza
4. **Walk-forward zorunlu** — Out-of-sample test yapmadan model kullanma
5. **Rejime göre değiş** — Ağırlıklar rejime göre adapte olsun
6. **Cross-sectional** — Hisseyi tek başına değil, evren içinde değerlendir
7. **Önce nedeni sor** — Düşeni almadan önce neden düştüğünü anla
8. **Ölç ve öğren** — Feature importance feedback ile kendini geliştir
