# Dashboard Nihai Sistem Dokümanı — Kod Analizi + Araştırma Bazlı

**Tarih:** 2026-08-18
**Kaynaklar:** Bloomberg Terminal, Aladdin (BlackRock), Interactive Brokers TWS, Ed Chen Institutional Design System, Qlik Financial Dashboards

---

## 1. Sektörde En İyi Uygulama Nedir?

### 1.1 Bloomberg Terminal

**Temel prensip:** Tek ekranda tüm bilgi — piyasa, portföy, risk, haber, grafik.

```
BLOOMBERG TERMINAL ANA EKRANLAR
├── Market Monitor     ← Çoklu varlık takibi
├── Portfolio Analytics ← Pozisyon, P&L, risk
├── Risk Analytics     ← VaR, senaryo, stres test
├── News & Events      ← Haber akışı, KAP
├── Charting           ← Teknik grafik
├── Order Management   ← Emir yönetimi
├── Research           ← Analiz raporları
└── Alert System       ← Fiyat/siny alarmları
```

### 1.2 Aladdin (BlackRock)

```
ALADDIN DASHBOARD
├── Overview           ← Genel bakış
├── Portfolio          ← Pozisyon detay
├── Risk               ← Risk metrikleri
├── Market             ← Piyasa durumu
├── Analytics          ← İleri analiz
└── Compliance         ← Uyumluluk
```

### 1.3 Dashboard Temel Prensipleri

| Prensipler | Açıklama |
|------------|----------|
| **Real-time** | WebSocket ile anlık güncelleme |
| **Dark theme** | Göz yorgunluğunu azalt |
| **Responsive** | Farklı ekran boyutları |
| **Keyboard navigation** | Hızlı erişim |
| **Modüler** | Widget tabanlı, özelleştirilebilir |
| **Performant** | Büyük veri seti ile bile akıcı |
| **Accessible** | Renk körlüğü dostu |

---

## 2. Bizde Şu An Ne Var?

### 2.1 Next.js Dashboard (apps/web/)

| Dosya | Satır | Durum |
|-------|-------|-------|
| **Sayfalar (15)** | | |
| `page.tsx` (Overview) | — | ⚠️ Temel |
| `radar/page.tsx` | 157 | ✅ Market Radar |
| `asset/page.tsx` | 261 | ✅ Hisse detay |
| `portfolio/page.tsx` | 77 | ⚠️ Basit |
| `opportunities/page.tsx` | 132 | ✅ Fırsat terminali |
| `world/page.tsx` | 133 | ✅ World State |
| `events/page.tsx` | 134 | ✅ Event akışı |
| `research/page.tsx` | 108 | ✅ AI Research |
| `alerts/page.tsx` | 71 | ⚠️ Basit |
| `models/page.tsx` | 74 | ⚠️ Basit |
| `learning/page.tsx` | 43 | ⚠️ Placeholder |
| `system/page.tsx` | 116 | ✅ Sistem sağlık |
| `map/page.tsx` | 43 | ⚠️ Placeholder |
| `scenario/page.tsx` | 43 | ⚠️ Placeholder |
| `strategy/page.tsx` | 43 | ⚠️ Placeholder |
| `data/page.tsx` | 43 | ⚠️ Placeholder |
| **Components (7)** | | |
| `LiveChart.tsx` | 220 | ✅ Canlı grafik |
| `TradingViewChart.tsx` | 76 | ✅ TradingView |
| `Sidebar.tsx` | 108 | ✅ Yan menü |
| `AnimatedNumber.tsx` | 70 | ✅ Animasyonlu sayı |
| `LiveTicker.tsx` | 65 | ✅ Canlı ticker |
| `Sparkline.tsx` | 52 | ✅ Mini grafik |
| `StatCard.tsx` | 84 | ✅ İstatistik kartı |
| **Lib (2)** | | |
| `api.ts` | 186 | ✅ API istemcisi |
| `websocket.ts` | 199 | ✅ WebSocket istemcisi |

### 2.2 HTML Dashboard (server.py)

| Endpoint | İçerik | Durum |
|----------|--------|-------|
| `GET /` | Basit HTML dashboard | ⚠️ Çok basit |
| `GET /health/detailed` | Sağlık durumu | ✅ |
| `GET /metrics` | Prometheus metrics | ✅ |

---

## 3. Eksikler (Kritik)

### 3.1 Placeholder Sayfalar (6)

| Sayfa | Durum | Ne Gerekli |
|-------|-------|------------|
| `learning/page.tsx` | ⚠️ 43 satır | Tahmin takibi, doğruluk, drift detection |
| `map/page.tsx` | ⚠️ 43 satır | Sektör heatmap, piyasa haritası |
| `scenario/page.tsx` | ⚠️ 43 satır | Senaryo analizi UI |
| `strategy/page.tsx` | ⚠️ 43 satır | Strateji yönetimi UI |
| `data/page.tsx` | ⚠️ 43 satır | Veri kaynakları UI |
| `alerts/page.tsx` | ⚠️ 71 satır | Gelişmiş alert yönetimi |

### 3.2 Eksik Sayfalar

| Sayfa | Açıklama |
|-------|----------|
| **Risk Dashboard** | VaR, CVaR, drawdown, konsantrasyon |
| **Backtest Results** | Backtest sonuçları, equity curve |
| **Agent Dashboard** | Agent durumu, debate sonuçları |
| **Macro Dashboard** | Makro göstergeler, rejim |
| **Factor Dashboard** | Faktör skorları, performans |
| **Event Study** | Event etki analizi |
| **VIOP Dashboard** | Opsiyon zinciri, Greeks |
| **Alternative Data** | Alternatif veri kaynakları |
| **Scheduler** | Job durumu, çalıştırma geçmişi |
| **Audit Log** | Denetim kayıtları |
| **Research & Documentation** | BIST kuralları, nihai spec'ler, tech stack, bağımlılık sırası, test beklentileri |

### 3.3 Eksik Component'lar

| Component | Açıklama |
|-----------|----------|
| **Heatmap** | Sektör/hisse heatmap |
| **Candlestick Chart** | Mum grafik |
| **Order Book** | Emir defteri |
| **Depth Chart** | Derinlik grafiği |
| **Gauge** | Risk/skor gösterge |
| **Timeline** | Event timeline |
| **Table (sortable)** | Sıralanabilir tablo |
| **Filter Panel** | Filtre paneli |
| **Search** | Arama |
| **Notification** | Bildirim |

### 3.4 Eksik Özellikler

| Özellik | Açıklama |
|---------|----------|
| **Dark theme** | Karanlık tema |
| **Responsive** | Mobil uyumluluk |
| **Keyboard shortcuts** | Kısayol tuşları |
| **Widget system** | Özelleştirilebilir widget |
| **Real-time updates** | WebSocket entegrasyonu tüm sayfalarda |
| **Export** | PDF/CSV dışa aktarma |
| **Multi-language** | Türkçe/İngilizce |

---

## 4. Nihai Dashboard Mimarisi

### 4.1 Sayfa Yapısı (Nihai)

```
DASHBOARD SAYFALARI

├── Overview (Ana Sayfa)
│   ├── Market Regime kartı
│   ├── Risk Regime kartı
│   ├── Top Opportunities (5)
│   ├── Top Risks (5)
│   ├── Portfolio özeti
│   ├── P&L grafiği
│   ├── AI Confidence
│   ├── Recent Events (5)
│   └── System Health
│
├── Market Radar
│   ├── 800+ hisse tablosu (sortable, filterable)
│   ├── Filtreler: sektör, skor, risk, momentum, hacim
│   ├── Heatmap görünümü
│   └── Quick view: tıkla → detay
│
├── Market Map
│   ├── Sektör heatmap
│   ├── Fiyat/momentum haritası
│   ├── Volume haritası
│   └── Performans haritası
│
├── Asset Research
│   ├── Fiyat grafiği (TradingView)
│   ├── Teknik göstergeler
│   ├── Fundamental bilgiler
│   ├── Haber/KAP akışı
│   ├── Sentiment
│   ├── Macro sensitivity
│   ├── Risk metrikleri
│   ├── Geçmiş davranış
│   ├── Mevcut sinyal
│   └── Karar geçmişi
│
├── Opportunities
│   ├── Sıralama: skor, risk-adjusted, confidence
│   ├── Filtreler
│   ├── Detail: neden? evidence, risks, catalysts
│   └── Quick trade: BUY/SELL butonu
│
├── World State
│   ├── 10 latent factor kartı
│   ├── Regime durumu
│   ├── Factor trendleri
│   └── Regime geçmişi
│
├── Portfolio
│   ├── Toplam equity
│   ├── Cash, invested
│   ├── Daily/Total P&L
│   ├── Drawdown
│   ├── Pozisyonlar tablosu
│   ├── Sektör dağılımı
│   ├── Risk metrikleri
│   ├── Açık emirler
│   └── İşlem geçmişi
│
├── Risk Dashboard ← YENİ
│   ├── Portfolio risk (LOW/MEDIUM/HIGH)
│   ├── Konsantrasyon
│   ├── Likidite
│   ├── Korelasyon
│   ├── Drawdown
│   ├── VaR/CVaR
│   ├── Daily risk budget
│   └── Risk neden yükseldi?
│
├── Events
│   ├── Event stream (canlı)
│   ├── KAP açıklamaları
│   ├── Haberler
│   ├── Macro olaylar
│   └── Event etki analizi
│
├── AI Research
│   ├── Model bilgisi
│   ├── Version
│   ├── Input features
│   ├── Evidence
│   ├── Confidence
│   ├── Reasoning
│   ├── Decision
│   └── Risk decision
│
├── Alerts
│   ├── Aktif alarmlar
│   ├── Alarm kuralları
│   ├── Alarm geçmişi
│   └── Bildirim ayarları
│
├── Models
│   ├── Model listesi
│   ├── Performans metrikleri
│   ├── Feature importance
│   ├── Model karşılaştırma
│   └── Ensemble durumu
│
├── Learning ← GELİŞTİRİLECEK
│   ├── Tahmin takibi
│   ├── Doğruluk grafiği
│   ├── Confidence calibration
│   ├── Drift detection
│   ├── Attribution
│   └── Model evolution
│
├── Backtest Results ← YENİ
│   ├── Backtest listesi
│   ├── Equity curve
│   ├── Trade listesi
│   ├── Performans metrikleri
│   └── Walk-forward sonuçları
│
├── Agent Dashboard ← YENİ
│   ├── Agent listesi (10 rol)
│   ├── Her agent sonucu
│   ├── Debate sonuçları
│   ├── Agent performansı
│   └── Agent memory
│
├── Macro Dashboard ← YENİ
│   ├── Makro göstergeler
│   ├── TCMB faiz
│   ├── Enflasyon
│   ├── USDTRY
│   ├── CDS
│   ├── VIX
│   └── Regime durumu
│
├── Factor Dashboard ← YENİ
│   ├── Faktör skorları
│   ├── Piotroski F-Score
│   ├── Beneish M-Score
│   ├── Altman Z-Score
│   ├── Fama-French
│   └── Faktör performansı
│
├── Event Study ← YENİ
│   ├── Event analiz
│   ├── CAR grafiği
│   ├── Significance
│   └── Impact skoru
│
├── VIOP Dashboard ← YENİ
│   ├── Opsiyon zinciri
│   ├── Greeks
│   ├── Strateji analizi
│   └── Hedge önerisi
│
├── Alternative Data ← YENİ
│   ├── Veri kaynakları
│   ├── Social sentiment
│   ├── Job postings
│   ├── Credit card
│   ├── Google Trends
│   └── Satellite
│
├── Scenario
│   ├── Senaryo çalıştır
│   ├── Sonuçlar
│   ├── Stress test
│   └── Breaking point
│
├── System Health
│   ├── API durumu
│   ├── Database durumu
│   ├── Redis durumu
│   ├── Servis durumları
│   ├── CPU/Memory
│   └── Loglar
│
├── Scheduler ← YENİ
│   ├── Job listesi
│   ├── Çalıştırma geçmişi
│   ├── Job durumu
│   └── Retry logları
│
├── Audit Log ← YENİ
│   ├── Denetim kayıtları
│   ├── Karar zinciri
│   ├── Kim, ne zaman, ne yaptı
│   └── Filtreleme
│
├── Research & Documentation ← YENİ
│   ├── BIST Kuralları
│   │   ├── İşlem saatleri
│   │   ├── Fiyat limitleri (pazara göre)
│   │   ├── Açığa satış kuralları
│   │   ├── Komisyon yapısı
│   │   ├── Temettü stopajı
│   │   ├── SPK regülasyonları
│   │   └── VIOP kuralları
│   │
│   ├── Modül Nihai Spec'leri
│   │   ├── 22 katman detaylı doküman
│   │   ├── Kod analizi
│   │   ├── Sektör araştırması
│   │   ├── Eksikler listesi
│   │   └── Uygulama planı
│   │
│   ├── Tech Stack Karşılaştırması
│   │   ├── Mevcut teknolojiler
│   │   ├── Nihai seçimler
│   │   ├── Eksik teknolojiler
│   │   ├── Performans karşılaştırması
│   │   └── Bağımlılık ağacı
│   │
│   ├── Bağımlılık Sırası
│   │   ├── 15 seviye bağımlılık ağacı
│   │   ├── Hangi modül önce düzeltilmeli
│   │   └── Düzeltme sırası
│   │
│   ├── Test Beklentileri
│   │   ├── Her modül için test gereksinimleri
│   │   ├── Test çalıştırma komutları
│   │   └── Geçme/kalma kriterleri
│   │
│   └── Sistem Tanımı
│       ├── 32 bölüm detaylı doküman
│       ├── Hata raporu
│       ├── Çalışma şekli
│       └── Uygulama planları
│
└── Dashboard Settings
    ├── Tema seçimi (dark/light)
    ├── Widget özelleştirme
    ├── Bildirim ayarları
    ├── Dil seçimi (TR/EN)
    └── Export (PDF/CSV)
```

### 4.2 Component Mimarisi (Nihai)

```
COMPONENTS

├── Charts
│   ├── LiveChart.tsx          ✅ Canlı grafik
│   ├── TradingViewChart.tsx   ✅ TradingView
│   ├── CandlestickChart.tsx   ← YENİ (mum grafik)
│   ├── HeatmapChart.tsx       ← YENİ (sector/hisse heatmap)
│   ├── LineChart.tsx          ← YENİ (çizgi grafik)
│   ├── BarChart.tsx           ← YENİ (çubuk grafik)
│   ├── PieChart.tsx           ← YENİ (pasta grafik)
│   └── GaugeChart.tsx         ← YENİ (gösterge)
│
├── Tables
│   ├── DataTable.tsx          ← YENİ (sortable, filterable)
│   ├── PositionTable.tsx      ← YENİ (pozisyon tablosu)
│   ├── TradeTable.tsx         ← YENİ (işlem tablosu)
│   └── OrderBook.tsx          ← YENİ (emir defteri)
│
├── Cards
│   ├── StatCard.tsx           ✅ İstatistik kartı
│   ├── RegimeCard.tsx         ← YENİ (rejim kartı)
│   ├── RiskCard.tsx           ← YENİ (risk kartı)
│   └── AlertCard.tsx          ← YENİ (alarm kartı)
│
├── Layout
│   ├── Sidebar.tsx            ✅ Yan menü
│   ├── Header.tsx             ← YENİ (üst bar)
│   ├── Footer.tsx             ← YENİ (alt bar)
│   ├── WidgetGrid.tsx         ← YENİ (widget grid)
│   └── Panel.tsx              ← YENİ (panel)
│
├── UI
│   ├── AnimatedNumber.tsx     ✅ Animasyonlu sayı
│   ├── LiveTicker.tsx         ✅ Canlı ticker
│   ├── Sparkline.tsx          ✅ Mini grafik
│   ├── FilterPanel.tsx        ← YENİ (filtre)
│   ├── SearchBar.tsx          ← YENİ (arama)
│   ├── Notification.tsx       ← YENİ (bildirim)
│   ├── Timeline.tsx           ← YENİ (event timeline)
│   └── ProgressBar.tsx        ← YENİ (ilerleme)
│
└── Lib
    ├── api.ts                 ✅ API istemcisi
    ├── websocket.ts           ✅ WebSocket istemcisi
    ├── theme.ts               ← YENİ (tema)
    ├── i18n.ts                ← YENİ (çeviri)
    └── utils.ts               ← YENİ (yardımcı fonksiyonlar)
```

### 4.3 WebSocket Entegrasyonu (Nihai)

```
WEBSOCKET KANALLARI (Tüm sayfalarda)

/ws/market       → Market Radar, Asset Research
/ws/portfolio    → Portfolio
/ws/risk         → Risk Dashboard
/ws/signals      → Opportunities, Overview
/ws/decisions    → AI Research, Overview
/ws/agents       → Agent Dashboard
/ws/learning     → Learning
/ws/system       → System Health
/ws/events       → Events
/ws/backtest     → Backtest Results
```

### 4.4 Renk Paleti (Nihai)

```
DARK THEME
├── Background:    #0d1117 (koyu gri)
├── Surface:       #161b22 (kart arka planı)
├── Border:        #30363d (kenarlık)
├── Text:          #e6edf3 (ana metin)
├── Text Secondary: #8b949f (ikincil metin)
├── Primary:       #58a6ff (ana renk — mavi)
├── Success:       #3fb950 (yeşil — pozitif)
├── Danger:        #f85149 (kırmızı — negatif)
├── Warning:       #d29922 (sarı — uyarı)
└── Info:          #58a6ff (bilgi)
```

---

## 5. Rakip Karşılaştırması

### 5.1 Bloomberg Terminal

| Özellik | Bloomberg | Bizim Sistem | Fark |
|---------|-----------|-------------|------|
| Market Monitor | ✅ Çoklu varlık | ✅ Radar | ✅ Aynı |
| Portfolio Analytics | ✅ | ⚠️ Basit | ⚠️ |
| Risk Analytics | ✅ MARS | ⚠️ Basit | ⚠️ |
| Charting | ✅ Profesyonel | ⚠️ TradingView | ⚠️ |
| News | ✅ Bloomberg News | ⚠️ RSS | ⚠️ |
| Alerts | ✅ Gelişmiş | ⚠️ Basit | ⚠️ |
| Keyboard | ✅ | ❌ | ❌ |

### 5.2 Aladdin

| Özellik | Aladdin | Bizim Sistem | Fark |
|---------|---------|-------------|------|
| Overview | ✅ | ✅ | ✅ Aynı |
| Portfolio | ✅ | ⚠️ Basit | ⚠️ |
| Risk | ✅ | ⚠️ Basit | ⚠️ |
| Analytics | ✅ Gelişmiş | ⚠️ Basit | ⚠️ |
| Compliance | ✅ | ⚠️ Basit | ⚠️ |

---

## 6. Uygulama Planı

### Faz 1: Placeholder Sayfaları Doldur (Hemen)
1. Learning sayfası (tahmin takibi, doğruluk, drift)
2. Map sayfası (sector heatmap)
3. Scenario sayfası (senaryo çalıştırma)
4. Strategy sayfası (strateji yönetimi)
5. Data sayfası (veri kaynakları)
6. Alerts sayfası (gelişmiş alert yönetimi)

### Faz 2: Yeni Sayfalar (1 hafta)
1. Risk Dashboard
2. Backtest Results
3. Agent Dashboard
4. Macro Dashboard
5. Factor Dashboard
6. Event Study
7. VIOP Dashboard
8. Alternative Data
9. Scheduler
10. Audit Log

### Faz 3: Yeni Component'lar (1 hafta)
1. HeatmapChart
2. CandlestickChart
3. DataTable (sortable, filterable)
4. GaugeChart
5. FilterPanel
6. SearchBar
7. Notification
8. Timeline

### Faz 4: Tema ve UX (1 hafta)
1. Dark theme
2. Responsive design
3. Keyboard shortcuts
4. Widget system
5. Export (PDF/CSV)

### Faz 5: WebSocket Entegrasyonu (1 hafta)
1. Tüm sayfalarda real-time updates
2. Connection management
3. Reconnection logic
4. Data buffering

---

## 7. Mevcut Sistem vs Nihai Vizyon

| Özellik | Mevcut | Hedef |
|---------|--------|-------|
| Sayfa sayısı | 15 (6 placeholder) | 25 |
| Component sayısı | 7 | 20 |
| WebSocket kanalı | 7 | 10 |
| Dark theme | ❌ | ✅ |
| Responsive | ❌ | ✅ |
| Keyboard shortcuts | ❌ | ✅ |
| Widget system | ❌ | ✅ |
| Export | ❌ | ✅ |
| Heatmap | ❌ | ✅ |
| Candlestick | ❌ | ✅ |
| DataTable | ❌ | ✅ |
| Risk Dashboard | ❌ | ✅ |
| Backtest Results | ❌ | ✅ |
| Agent Dashboard | ❌ | ✅ |
| Macro Dashboard | ❌ | ✅ |
| Factor Dashboard | ❌ | ✅ |
| Event Study | ❌ | ✅ |
| VIOP Dashboard | ❌ | ✅ |
| Alternative Data | ❌ | ✅ |
| Scheduler | ❌ | ✅ |
| Audit Log | ❌ | ✅ |
