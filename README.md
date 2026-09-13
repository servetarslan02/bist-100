# 🚀 ALPHA BIST — Autonomous Market Intelligence & Quant Trading Platform

> **Borsa İstanbul (BIST)** pay piyasası için geliştirilmiş; 10 yıllık bölünme-düzeltilmiş (split-adjusted) takas ambarı, 70 kanonik kantitatif öznitelik ve ileriye yürüyen (Walk-Forward) makine öğrenmesi modelleri ile çalışan otonom piyasa zekâsı ve portföy yönetim platformu.

---

## 🏛️ Mimari ve Veri Akış Hattı

```
[ BIST Canlı Veri Akışları / KAP / TCMB / Makro Göstergeler ]
                         │
                         ▼
┌─────────────────────────────────────────────────────────────┐
│                 YÜKSEK HIZLI VERİ AMBARI                    │
│   • DuckDB (Yerel Analitik, 10 Yıllık 362K Bar Veri Deposu) │
│   • ClickHouse OLAP (Yüksek Hacimli Analitik & Tick Verisi) │
│   • PostgreSQL 17 + TimescaleDB (İşlemler & Portföy Kaydı)  │
│   • Redis 8.0 (Düşük Gecikmeli Önbellek & Durum Yönetimi)   │
│   • NATS + JetStream (Olay Akış Dağıtımı)                   │
└────────────────────────┬────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────┐
│               70 KANONİK KANTİTATİF ÖZNİTELİK               │
│   • Relatif Güç Motoru (RS vs BIST-100, RS vs Sektör)       │
│   • Momentum & Trend (ROC-5/20/60, SMA20/50/200 Sapmaları)  │
│   • Hacim & Mikroyapı (Volume Z-Score, OBV, VWAP Sapması)   │
│   • Temel Göstergeler (Sektörel F/K, PD/DD Normalizasyonu)  │
│   • Makro Piyasa Rejim Tespiti (Boğa, Ayı, Yatay, Volatil)  │
└────────────────────────┬────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────┐
│           MAKİNE ÖĞRENİMİ & STRATEJİ MOTORLARI              │
│   • Şampiyon Model: LightGBM LambdaRank (Sıralama Motoru)   │
│   • 20 Günlük Walk-Forward Retraining (5 Gün Purge+Embargo) │
│   • StrategyDiagnostician (Kendi Kendini Teşhis & Karantina)│
│   • Chandelier ATR Trailing Stop & Breakeven Kâr Koruması   │
│   • BIST %10 Tavan/Taban Devre Kesici & Dinamik Slippage    │
└────────────────────────┬────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────┐
│             MODERN WEB ARAYÜZÜ (NEXT.JS 15)                 │
│   • 17 Canlı ve Dinamik Ekran (Sıfır Statik/Sahte Veri)     │
│   • TradingView Lightweight Grafikleri                      │
│   • Gerçek Zamanlı Radar, Portföy, Strateji ve Alarmlar     │
└─────────────────────────────────────────────────────────────┘
```

---

## 🏆 10 Yıllık Tam BIST Otonom Sistem Doğrulama Raporu (2014-2023)

> **Doğrulama Koşulları:** 
> * **%0 Nema / Faiz:** Nakitte duran sermayeye faiz veya repo geliri eklenmemiştir (Saf borsa getirisi).
> * **173 BIST Hissesi:** 362,877 adet bölünme-düzeltilmiş gerçek seans mumu.
> * **Sıfır Geleceği Görme (Lookahead):** EOD sinyali (18:15) sonrası emirler T+1 seans açılışında (`Open * (1 + slippage)`) yürütülür.
> * **BIST Piyasa Kısıtları:** %10 tavan/taban kilitleri, işlem hacminin maks %10'u likidite tavanı, %0.15 komisyon.

```
========================================================================================
💰 Başlangıç Sermayesi:     ₺1,000,000.00 (1 Milyon TL)
💎 Bitiş Sermayesi:         ₺20,096,663.23 (Net Kâr: +₺19,096,663.23)
📈 Portföy Net Getirisi:    +%1,909.67 (BIST-100 Benchmark: +%726.88)
🚀 Alfa (Excess Return):    +%1,182.78 (BIST-100 Endeksini 2.63 Katlayan Net Performans)
🎯 Portföy Yıllık Bileşik:  %40.26 CAGR (BIST-100 CAGR: %23.51)
⚡ Sharpe Oranı:            1.45 (Saf hisse getirisi)
🛡️ Maksimum Drawdown (DD):  %40.56 (2018 Kur Şoku ve 2020 Covid Düşüşlerinde Koruma)
⚖️ Profit Factor:           2.08
📊 Toplam İşlem Sayısı:     1,347 Gerçekleşen İşlem
🔒 Nema / Repo Durumu:      %0.00 (Faizsiz, saf sermaye getirisi)
========================================================================================
```

### 📅 Yıllık Bazda Getiri ve Alfa Dağılımı

| Yıl | Portföy Getirisi | BIST-100 Getirisi | Üretilen Alfa | Yıl Sonu Portföy Değeri | Piyasa Rejimi & Davranış |
|:---:|:---:|:---:|:---:|:---:|---|
| **2015** | **-%7.35** | -%13.69 | **+%6.34** | ₺926,522 | Düşüş piyasasında sermaye koruma |
| **2016** | **+%21.40** | +%8.94 | **+%12.46** | ₺1,124,797 | Şok sonrası hızlı toparlanma |
| **2017** | **+%61.28** | +%47.60 | **+%13.68** | ₺1,814,073 | Boğa trendinde güçlü alfa üretimi |
| **2018** | **-%17.65** | -%20.86 | **+%3.21** | ₺1,493,889 | Rahip Brunson kur şokunda nakit kalkanı |
| **2019** | **+%36.14** | +%25.37 | **+%10.77** | ₺2,033,780 | Yataydan çıkışta momentum liderleri |
| **2020** | **+%68.91** | +%29.06 | **+%39.85** | ₺3,435,258 | Covid çöküşünde defans, rallide agresif katılım |
| **2021** | **+%44.08** | +%25.80 | **+%18.28** | ₺4,949,520 | Faiz indirimleri dalgasında alfa |
| **2022** | **+%285.34** | +%196.57 | **+%88.77** | ₺19,072,423 | Büyük enflasyon boğasında kârı sürme (ATR Trailing) |
| **2023** | **+%5.37** | +%35.60 | -%30.23 | ₺20,096,663 | Deprem ve seçim belirsizliğinde kontrollü tutum |

### 🛠️ Doğrulanmış Kurumsal Motor Kuralları

1. **Chandelier ATR Trailing Stop (Kârı Sürme):** Sabit kâr tavanı kaldırılmıştır. %12+ prim yapan hisselerde zirveden geriye doğru 2.5x ATR mesafe ile kâr trend boyunca sürülür.
2. **Breakeven Koruması (Sıfır Risk):** Hisse girişten itibaren %8 prim yapınca stop seviyesi maliyetin üzerine (+%1) çekilerek kâra geçmiş hissenin zararla kapanması engellenir.
3. **Rejim Tabanlı Sermaye Dağılımı:**
   * **Boğa Trendi (`BULL_TREND`):** Portföyün %85-%95'i sahada, maksimum 12 lider hisseye dengeli dağılım.
   * **Ayı Piyasası (`BEAR_MARKET`):** Portföyün %75'i nakitte koruma, en fazla 3 defansif hisse.
4. **BIST %10 Tavan/Taban Kilidi:** Tavan açmış hisseye alım, tabana kilitlenmiş hisseye satış ertelenir.
5. **Hayatta Kalma Yanlılığı Engeli:** Hisseler resmi BIST halka arz tarihinden (`ipo_dates`) önce evrene dahil edilemez.
6. **20 Günlük Walk-Forward Retraining:** Model 10 yılda 112 kez 5 günlük Purge + Embargo uygulanarak sıfırdan eğitilmiştir.
7. **StrategyDiagnostician Öz-Öğrenme:** Son 30 işlemi denetleyerek zarar eden sektörleri geçici karantinaya alır ve eşikleri günceller.

---

## 📊 Web Arayüzü Modülleri (Next.js 15)

| Sayfa | Rota | Açıklama |
|---|---|---|
| **Ana Dashboard** | `/` | Piyasa özeti, model sinyalleri, son alarmlar ve canlı telemetri |
| **Portföy** | `/portfolio` | Otonom pozisyonlar, nakit kalkanı, getiri eğrisi ve emir defteri |
| **Pazar Radarı** | `/radar` | BIST genelindeki fırsatların çok boyutlu quant skorlaması |
| **Fırsatlar** | `/opportunities` | Yüksek güven skorlu katalizör ve momentum kırılımları |
| **Varlık Analizi** | `/asset` | TradingView grafiği, teknik indikatörler ve derinlik analizi |
| **Strateji Lab** | `/strategy` | Backtest motoru, walk-forward analizi ve performans matrisi |
| **Senaryo Lab** | `/scenario` | Monte Carlo simülasyonları ve tarihsel stres testleri |
| **Sektör Haritası** | `/map` | BIST sektör göreceli güç ısı haritası |
| **Model Merkezi** | `/models` | Yapay zekâ modellerinin canlı doğruluk ve ağırlık matrisi |
| **Öğrenme Lab** | `/learning` | Kapalı devre öğrenme metrikleri ve Brier skoru grafikleri |
| **Küresel Makro** | `/world` | Emtialar, pariteler, tahvil faizleri ve makro göstergeler |
| **Haber & KAP** | `/events` | Canlı KAP bildirim akışı ve olay analizi |
| **Araştırma** | `/research` | Otonom üretilen hisse ve piyasa analiz raporları |
| **Canlı Alarmlar**| `/alerts` | Fiyat, hacim ve teknik kırılım uyarıları |
| **Veri Merkezi** | `/data` | Depolama ve veri akış sağlık telemetrisi |
| **Sistem Durumu** | `/system` | Servis sağlık monitörü, bellek kullanımı ve gecikme takibi |

---

## 🛠️ Kurulum ve Çalıştırma

### Gereksinimler
* Python `>= 3.12`
* `uv` paket yöneticisi
* Docker & Docker Compose
* Node.js `>= 20.0` (Web arayüzü için)

### Docker ile Başlatma (Tavsiye Edilen)

Tüm servisleri (Web Arayüzü, API, ClickHouse, PostgreSQL, Redis) tek komutla ayağa kaldırmak için:

```bash
docker compose up -d --build
```

Servis Adresleri:
* **Web Arayüzü:** [http://localhost:3000](http://localhost:3000)
* **FastAPI Backend:** [http://localhost:8000](http://localhost:8000)
* **API Swagger:** [http://localhost:8000/docs](http://localhost:8000/docs)
* **ClickHouse HTTP:** `http://localhost:8123`
* **PostgreSQL:** `localhost:5432`
* **Redis:** `localhost:6379`

### Yerel Ortamda Çalıştırma

```bash
# Bağımlılıkları yükle
uv sync

# 10 Yıllık Tam BIST Simülasyonunu Çalıştır
uv run python scripts/run_10year_all_bist_simulation.py

# Günlük Otonom Seans Döngüsünü Çalıştır
uv run python services/pipeline/run_unified_daily.py

# Web Arayüzünü Başlat
cd web && npm run dev
```

---

## 🔒 Mühendislik ve Veri Prensipleri

* **Sıfır Sahte / Mock Veri:** Tüm ekranlar ve analizler doğrudan PostgreSQL, DuckDB, ClickHouse ve FastAPI uçlarından gelen gerçek verilerle beslenir.
* **Fail-Closed Güvenlik:** Beklenmeyen veri veya ağ kopmalarında sistem güvenli duruma (nakde) geçer.
* **Yüksek Performans:** Yüksek hacimli veri hesaplamaları için `polars`, serileştirme için `orjson` ve yerel analitik için `duckdb` kullanılır.
