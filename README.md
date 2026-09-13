# 🚀 ALPHA BIST — End-to-End Autonomous Market Intelligence & Quant Engine

> **BIST (Borsa İstanbul)** evrenindeki tüm hisseleri, makroekonomik verileri, KAP haber akışlarını ve derinlik mikro-yapısını 7/24 otonom olarak analiz eden; 30 yıllık veri ambarı ve hibrit yapay zekâ (XGBoost, LightGBM, CatBoost, Temporal Deep Learning) modelleri ile çalışan kurumsal seviye piyasa zekâsı ve portföy yönetim platformu.

---

## 🏛️ Mimari ve Veri Akış Hattı

```
[ BIST Canlı Veri Akışları / KAP / RSS / Makro Göstergeler ]
                         │
                         ▼
┌─────────────────────────────────────────────────────────────┐
│                 YÜKSEK HIZLI VERİ AMBARI                    │
│   • ClickHouse OLAP (30 Yıllık Tick & Bar Verileri)         │
│   • PostgreSQL 17 (İşlemsel Kayıtlar, Portföy & Modeller)   │
│   • Redis 8.0 (Sub-Millisecond Önbellek & Canlı Telemetri)  │
│   • NATS + JetStream (Yüksek Verimli Event Streaming)        │
└────────────────────────┬────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────┐
│                ÖZNİTELİK & ANALİZ MOTORLARI                 │
│   • 100+ Teknik, Temel & Mikro-Yapı İndikatörü              │
│   • Empirik Mum Formasyonu & Donchian Trend Takipçisi       │
│   • Makro Rejim Tespiti & Dinamik Sektör Isı Haritası       │
│   • Otonom Risk Parity Kalkanı & Kriz Savunma Motoru        │
└────────────────────────┬────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────┐
│              MAKİNE ÖĞRENİMİ & KARAR MOTORU                 │
│   • Ensemble Füzyon Modelleri (XGBoost + LightGBM + CatBoost)│
│   • Kapalı Devre Sürekli Öğrenme (Brier Skoru Optimizasyonu)│
│   • 60 FPS Donanım Hızlandırmalı Monte Carlo Simülatörü     │
│   • Seans Duyarlı Otonom Pozisyon ve Risk Kapısı            │
└────────────────────────┬────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────┐
│             MODERN WEB ARAYÜZÜ (NEXT.JS 15)                 │
│   • 17 Canlı, Tamamen Dinamik ve Sıfır Sahte Verili Sayfa   │
│   • TradingView Lightweight Entegrasyonu                    │
│   • Gerçek Zamanlı Alarm, Radar ve Araştırma Laboratuvarı   │
└─────────────────────────────────────────────────────────────┘
```

## 🏆 10 Yıllık Tam BIST Otonom Sistem Doğrulama Raporu (2014-2023)

> **Kural:** %0 Nema / Faiz. Tam BIST Evreni (173 Hisse, 362,877 Seans Barı). Sıfır Lookahead (T+1 Açılış Yürütümü). Dinamik Slippage + Komisyon. BIST Tavan/Taban Kilidi.

```
========================================================================================
💰 Başlangıç Sermayesi:     ₺1,000,000.00 (1 Milyon TL)
💎 Bitiş Sermayesi:         ₺20,096,663.23 (Net: +₺19,096,663.23)
📈 Portföy Net Getirisi:    +%1,909.67 (BIST-100 Benchmark: +%726.88)
🚀 Alfa (Excess Return):    +%1,182.78 (BIST-100 Endeksini 2.63 Katlayan Net Performans)
🎯 Portföy Yıllık Bileşik:  %40.26 CAGR (BIST-100 CAGR: %23.51)
⚡ Sharpe Oranı:            1.45 (Saf hisse getirisi, risksiz faiz katkısı sıfır)
🛡️ Maksimum Drawdown (DD):  %40.56 (2018 Kur Şoku ve 2020 Covid Düşüşlerinde Koruma)
⚖️ Profit Factor (Kâr Fak): 2.08
📊 Toplam İşlem:            1,347 Adet Gerçekleşen BIST Takas İşlemi
🔒 Nema / Repo Durumu:      %0.00 (Tamamen saf borsa sermaye kazancı/kaybı)
========================================================================================
```

### 📅 Yıllık Bazda Getiri ve Alfa Dağılımı

| Yıl | Portföy Getirisi | BIST-100 Getirisi | Üretilen Alfa | Yıl Sonu Portföy Değeri | Piyasa Rejimi & Davranış |
|---|---|---|---|---|---|
| **2015** | **-%7.35** | -%13.69 | **+%6.34** | ₺926,522 | Düşüş piyasasında defansif koruma |
| **2016** | **+%21.40** | +%8.94 | **+%12.46** | ₺1,124,797 | Darbe girişimi ve şok sonrası hızlı toparlanma |
| **2017** | **+%61.28** | +%47.60 | **+%13.68** | ₺1,814,073 | KGF boğa trendinde güçlü alfa |
| **2018** | **-%17.65** | -%20.86 | **+%3.21** | ₺1,493,889 | Rahip Brunson kur şokunda nakit kalkanı |
| **2019** | **+%36.14** | +%25.37 | **+%10.77** | ₺2,033,780 | Yataydan çıkışta momentum liderleri |
| **2020** | **+%68.91** | +%29.06 | **+%39.85** | ₺3,435,258 | Covid dibinde nakit koruması, rallide agresif katılım |
| **2021** | **+%44.08** | +%25.80 | **+%18.28** | ₺4,949,520 | TCMB faiz indirimleri dalgasında alfa |
| **2022** | **+%285.34** | +%196.57 | **+%88.77** | ₺19,072,423 | Büyük enflasyon boğasında Chandelier ATR ile kârı sürme |
| **2023** | **+%5.37** | +%35.60 | -%30.23 | ₺20,096,663 | Deprem ve seçim belirsizliğinde sermaye koruma |

### 🛠️ Doğrulanmış Kurumsal Şampiyon Mimari Kuralları
1. **Chandelier ATR Trailing Stop (Kârı Sürme):** Sabit %10 kâr tavanı kaldırılmıştır. %12+ prim yapan hisselerde zirveden geriye doğru 2.5x ATR mesafe ile kâr trend boyunca taşınır.
2. **Breakeven Maliyet Koruması (Sıfır Risk):** Hisse girişten itibaren %8 prim yapınca stop seviyesi maliyetin üzerine (+%1) kilitlenir.
3. **Rejim Tabanlı Sermaye Yangını:**
   * **Boğa Trendi (`BULL_TREND`):** Portföyün %85-%95'i sahada, maksimum 12 lider hisseye dengeli dağılım.
   * **Ayı Piyasası (`BEAR_MARKET`):** Portföyün %75'i nakitte savunma, azami 3 defansif hisse.
4. **BIST %10 Tavan/Taban Kilidi:** Tavan açmış hisseye alım, tabana kilitlenmiş hisseye satış emri ertelenir.
5. **Hayatta Kalma Yanlılığı Engeli:** Hisseler ancak resmi BIST halka arz tarihinden (`ipo_dates`) itibaren taranabilir.
6. **Walk-Forward Retraining:** Model her 20 seans gününde bir 5 günlük Purge + Embargo uygulanarak sıfırdan eğitilir (10 yılda 112 kez yeniden eğitim).
7. **StrategyDiagnostician Öz-Öğrenme:** Her 30 işlemde bir zarar eden sektörleri geçici karantinaya alır ve dinamik parametre optimizasyonu yapar.

---

## 🌟 Öne Çıkan Özellikler

### 1. ⚡ 30 Yıllık BIST Deposu ve Stres Testi Laboratuvarı
* **Tarihsel Kriz Senaryoları:** 2008 Lehman Çöküşü, 2018 Kur/Faiz Şoku, 2020 Pandemi Karantinası ve 2022 Enflasyon Boğası üzerinde test edilmiş otonom savunma mekanizmaları.
* **60 FPS Donanım Hızlandırmalı Kanvas:** HTML5 Canvas üzerinde çalışan, kaydırıcılar oynatılırken **0 ms anlık tepki veren** stokastik Monte Carlo güven konileri ($p05 - p95$) ve kuyruk riski dağılım histogramı.
* **Matematiksel Risk:** Parametrik ve Tarihsel %95 VaR (Value at Risk) ve CVaR (Expected Shortfall).

### 2. 🧠 Kapalı Devre Sürekli Öğrenme Döngüsü (Continuous Learning Lab)
* **Otonom Model Değerlendirmesi:** Yapılan her alım/satım tahmini gerçekleşen piyasa sonucuyla eşleştirilir.
* **Dinamik Füzyon Ağırlıklandırması:** Modellerin tahmin güveni Brier Skoruna ve Yön Doğruluğuna (Directional Accuracy) göre otomatik olarak yeniden ağırlıklandırılır.
* **Geriye Dönük İzlenebilirlik:** Tüm öğrenme döngüleri PostgreSQL ve Redis üzerinde kayıt altındadır.

### 3. 🛡️ Otonom Risk Parity ve Seans Kural Kapısı
* BIST seans saatlerine duyarlı (%100 nakit ve kriz teyit filtreleri).
* Tek hisse tavanı (%10), sektör yoğunlaşma kalkanı ve volatilite eşitleme.
* Dışarıdan manuel manipülasyona kapalı, tamamen otonom quant kurallarıyla çalışan portföy koruması.

### 4. 📊 17 Tam Dinamik Ekran (Next.js 15 Standalone)
| Sayfa | Rota | Açıklama |
|---|---|---|
| **Ana Dashboard** | `/` | Piyasa özeti, model sinyalleri, son alarmlar ve canlı telemetri |
| **Portföy** | `/portfolio` | Otonom pozisyonlar, nakit kalkanı, getiri eğrisi ve emir defteri |
| **Pazar Radarı** | `/radar` | BIST genelindeki fırsatların çok boyutlu quant skorlaması |
| **Fırsatlar** | `/opportunities` | Yüksek güven skorlu katalizör ve momentum kırılımları |
| **Varlık Analizi** | `/asset` | TradingView grafiği, teknik indikatörler ve derinlik analizi |
| **Strateji Lab** | `/strategy` | Backtest motoru, walk-forward analizi ve performans matrisi |
| **Senaryo Lab** | `/scenario` | Donanım hızlandırmalı Monte Carlo ve tarihsel kriz testleri |
| **Sektör Haritası** | `/map` | 100% otomatik BIST evren keşifli sektör göreceli güç ısı haritası |
| **Model Merkezi** | `/models` | Yapay zekâ modellerinin canlı doğruluk ve ağırlık matrisi |
| **Öğrenme Lab** | `/learning` | Kapalı devre öğrenme metrikleri ve Brier skoru grafikleri |
| **Küresel Makro** | `/world` | Emtialar, pariteler, tahvil faizleri ve küresel risk göstergeleri |
| **Haber & KAP** | `/events` | Canlı duyuru akışı, duygu analizi ve olay etkisi |
| **Araştırma** | `/research` | Model tarafından otomatik üretilen analist raporları |
| **Canlı Alarmlar**| `/alerts` | Fiyat, hacim ve anomali uyarıları |
| **Veri Merkezi** | `/data` | ClickHouse ve PostgreSQL depolama sağlık telemetrisi |
| **Sistem Durumu** | `/system` | Servis sağlık monitörü, bellek kullanımı ve gecikme takibi |

---

## 🛠️ Kurulum ve Çalıştırma

### Docker ile Tek Komutla Başlatma (Tavsiye Edilen)

Tüm servisleri (Next.js Web UI, FastAPI Backend, ClickHouse, PostgreSQL, Redis, NATS) ayağa kaldırmak için:

```bash
docker compose up -d --build
```

Servis Portları:
* **Web Arayüzü:** [http://localhost:3000](http://localhost:3000)
* **REST API:** [http://localhost:8000](http://localhost:8000)
* **API Swagger Dokümantasyonu:** [http://localhost:8000/docs](http://localhost:8000/docs)
* **ClickHouse HTTP:** `http://localhost:8123`
* **PostgreSQL:** `localhost:5432`
* **Redis:** `localhost:6379`

---

## 🧪 Sistem Doğrulama ve Test Komutları

Sistemin tüm katmanlarının (17 sayfa, API uç noktaları, öğrenme döngüsü ve veri akışları) canlılığını test etmek için hazır scriptler mevcuttur:

```bash
# Tüm 17 sayfanın ve API'lerin canlı telemetrisini doğrula
python scripts/verify_all_17_pages_live.py

# Kapalı devre öğrenme döngüsünü ve model ağırlıklandırmasını test et
python scripts/verify_learning_and_models_cycle.py

# Veri tabanı ve sistem kaynak durumunu denetle
python scripts/audit_data_and_system_pages.py
```

---

## 🔒 Güvenlik ve Mimari Prensipler
* **Sıfır Statik / Sahte Veri:** Tüm ekranlar ve analizler doğrudan canlı PostgreSQL, ClickHouse, Redis ve FastAPI telemetrilerinden beslenir.
* **Otonomluk:** Sistem insan müdahalesi gerektirmeden bağımsız karar ve risk mekanizmalarıyla çalışır.
* **Katı Tip Güvenliği:** Pydantic v2 modelleri, FastAPI ve TypeScript arayüzleri ile uçtan uca tip koruması.

---
*Geliştirici & Model:* **ALPHA BIST Quantitative Intelligence Team**
