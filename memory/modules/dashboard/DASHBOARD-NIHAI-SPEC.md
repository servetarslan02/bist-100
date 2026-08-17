# Dashboard Nihai Sistem Dokümanı — Premium Design Spec

**Tarih:** 2026-08-18
**Kaynaklar:** Ed Chen Institutional Finance Design System (251 kategori), Bloomberg Terminal, shadcn/ui, Colorlib Dark Mode (2026), TradingView Charting Library, AdminLTE (2026)

---

## 1. Tasarım Felsefesi

### 1.1 Ne Olacak?

**Bloomberg Terminal kalitesinde, modern dark theme, kurumsal yatırım terminali.**

```
PREMIUM TRADING TERMINAL
├── Gerçek zamanlı piyasa verisi
├── Profesyonel grafikler (candlestick, heatmap, depth)
├── Portföy yönetimi ve risk analizi
├── AI destekli araştırma ve karar destek
├── Tüm sistem dokümantasyonu içinde
└── Mobil uyumlu, keyboard shortcuts
```

### 1.2 Tasarım Prensipleri

| Prensipler | Açıklama |
|------------|----------|
| **Dark First** | Karanlık tema varsayılan, göz yorgunluğunu azalt |
| **Information Density** | Bloomberg gibi bilgi yoğun, boş alan minimal |
| **Glassmorphism** | Kartlarda cam efekti, derinlik hissi |
| **Micro-animations** | Sayılar animasyonlu, geçişler akıcı |
| **Color Coding** | Yeşil=kâr, kırmızı=zarar, sarı=uyarı, mavi=bilgi |
| **Typography** | MonoSpace sayılar, sans-serif metin |
| **Responsive** | Desktop-first, mobil uyumlu |
| **Accessible** | WCAG 2.1 AA, renk körlüğü dostu |

---

## 2. Renk Sistemi (Tokens)

### 2.1 Dark Theme Palette

```css
/* Ana renkler */
--bg-primary:      #0a0e17;     /* En koyu arka plan */
--bg-secondary:    #111827;     /* Kart arka planı */
--bg-tertiary:     #1a2035;     /* Panel arka planı */
--bg-hover:        #1e2a42;     /* Hover durumu */

/* Cam efekti */
--glass-bg:        rgba(17, 24, 39, 0.7);
--glass-border:    rgba(255, 255, 255, 0.08);
--glass-blur:      blur(12px);

/* Metin */
--text-primary:    #e8ecf1;     /* Ana metin */
--text-secondary:  #8b95a5;     /* İkincil metin */
--text-muted:      #4a5568;     /* Soluk metin */

/* Durum renkleri */
--color-profit:    #10b981;     /* Yeşil — kâr */
--color-loss:      #ef4444;     /* Kırmızı — zarar */
--color-warning:   #f59e0b;     /* Sarı — uyarı */
--color-info:      #3b82f6;     /* Mavi — bilgi */
--color-neutral:   #6b7280;     /* Gri — nötr */

/* Aksan renkleri */
--accent-primary:  #6366f1;     /* Ana aksan (indigo) */
--accent-success:  #10b981;     /* Başarı */
--accent-danger:   #ef4444;     /* Tehlike */
--accent-gold:     #f59e0b;     /* Altın — premium */

/* Gradient'ler */
--gradient-card:   linear-gradient(135deg, rgba(17,24,39,0.8), rgba(26,32,53,0.6));
--gradient-accent: linear-gradient(135deg, #6366f1, #8b5cf6);
--gradient-profit: linear-gradient(135deg, #10b981, #34d399);
```

### 2.2 Grafik Renkleri

```css
/* Candlestick */
--candle-up:       #10b981;     /* Yeşil mum */
--candle-down:     #ef4444;     /* Kırmızı mum */
--candle-wick:     #374151;     /* Fitil */

/* Heatmap */
--heat-cold:       #1e3a5f;     /* Soğuk (düşük) */
--heat-neutral:    #374151;     /* Nötr */
--heat-warm:       #f59e0b;     /* Sıcak (yüksek) */
--heat-hot:        #ef4444;     /* Çok sıcak (aşırı) */

/* Volume */
--volume-buy:      rgba(16, 185, 129, 0.6);
--volume-sell:     rgba(239, 68, 68, 0.6);
```

---

## 3. Tipografi Sistemi

### 3.1 Font Ailesi

```css
/* Sayılar — monospace (hizalı) */
--font-mono:       'JetBrains Mono', 'Fira Code', 'SF Mono', monospace;

/* Metin — sans-serif (okunabilir) */
--font-sans:       'Inter', 'SF Pro Display', -apple-system, sans-serif;

/* Başlıklar */
--font-display:    'Inter', sans-serif;
```

### 3.2 Font Boyutları

```css
--text-xs:    0.75rem;    /* 12px — küçük etiketler */
--text-sm:    0.875rem;   /* 14px — tablo metin */
--text-base:  1rem;       /* 16px — normal metin */
--text-lg:    1.125rem;   /* 18px — kart başlığı */
--text-xl:    1.25rem;    /* 20px — bölüm başlığı */
--text-2xl:   1.5rem;     /* 24px — sayfa başlığı */
--text-3xl:   1.875rem;   /* 30px — büyük başlık */

/* Sayılar için */
--text-mono-sm:  0.8125rem;  /* 13px — tablo sayıları */
--text-mono-md:  1rem;       /* 16px — kart sayıları */
--text-mono-lg:  1.5rem;     /* 24px — büyük sayılar */
--text-mono-xl:  2.25rem;    /* 36px — hero sayılar */
```

---

## 4. Spacing & Layout

### 4.1 Grid Sistemi

```css
/* Ana layout */
--grid-columns:    12;
--grid-gap:        16px;

/* Sidebar */
--sidebar-width:   240px;
--sidebar-collapsed: 64px;

/* Header */
--header-height:   56px;

/* Kart */
--card-padding:    20px;
--card-radius:     12px;
--card-border:     1px solid var(--glass-border);
```

### 4.2 Responsive Breakpoints

```css
--breakpoint-sm:   640px;    /* Mobil */
--breakpoint-md:   768px;    /* Tablet */
--breakpoint-lg:   1024px;   /* Küçük desktop */
--breakpoint-xl:   1280px;   /* Normal desktop */
--breakpoint-2xl:  1536px;   /* Büyük desktop */
```

---

## 5. Component Kütüphanesi (Ed Chen Bazlı)

### 5.1 Financial Components

| Component | Açıklama | Kaynak |
|-----------|----------|--------|
| **PriceDisplay** | Fiyat gösterimi (animasyonlu) | Ed Chen |
| **OrderEntry** | Emir girişi | Ed Chen |
| **PositionCard** | Pozisyon kartı | Ed Chen |
| **TradeTicket** | İşlem bileti | Ed Chen |
| **P&LDisplay** | Kâr/zarar gösterimi | Ed Chen |
| **WatchlistRow** | İzleme listesi satırı | Ed Chen |
| **Sparkline** | Mini grafik | Ed Chen |
| **DepthIndicator** | Derinlik göstergesi | Ed Chen |
| **HeatmapCell** | Heatmap hücresi | Ed Chen |
| **OrderBook** | Emir defteri | Ed Chen |
| **InstrumentHeader** | Hisse başlığı | Ed Chen |
| **MarginPanel** | Teminat paneli | Ed Chen |
| **OrderStatus** | Emir durumu | Ed Chen |
| **SLTPConfig** | Stop/Target ayarı | Ed Chen |
| **VolumeBar** | Hacim çubuğu | Ed Chen |
| **TimeAndSales** | Zaman ve satış | Ed Chen |
| **EconomicCalendar** | Ekonomik takvim | Ed Chen |
| **SessionClock** | Seans saati | Ed Chen |
| **Allocation** | Dağılım | Ed Chen |
| **SpreadDisplay** | Spread gösterimi | Ed Chen |
| **RiskMatrix** | Risk matrisi | Ed Chen |
| **AlertConfig** | Alarm ayarı | Ed Chen |
| **TradeHistory** | İşlem geçmişi | Ed Chen |
| **Candlestick** | Mum grafik | Ed Chen |
| **Screener** | Tarama | Ed Chen |

### 5.2 AI & ML Components

| Component | Açıklama | Kaynak |
|-----------|----------|--------|
| **CalibratedConfidence** | Kalibre edilmiş güven | Ed Chen |
| **ReasoningChain** | Akıl zinciri | Ed Chen |
| **AutonomyTierSelector** | Otonomluk seviyesi | Ed Chen |
| **HumanSignOffGate** | İnsan onay kapısı | Ed Chen |
| **AISuggestionCard** | AI öneri kartı | Ed Chen |
| **StreamingResponse** | Canlı yanıt | Ed Chen |
| **PromptComposer** | Prompt oluşturucu | Ed Chen |
| **ModelFallbackChain** | Model fallback zinciri | Ed Chen |
| **AgentToolCallTrace** | Agent tool çağrı izi | Ed Chen |
| **GroundingIndicator** | Grounding göstergesi | Ed Chen |
| **SafetyGuardrails** | Güvenlik bariyerleri | Ed Chen |
| **RAGCitationMap** | RAG kaynak haritası | Ed Chen |
| **CostTokenBudget** | Maliyet/token bütçesi | Ed Chen |
| **AgentLoopExecution** | Agent döngü çalıştırma | Ed Chen |
| **UncertaintyHeatmap** | Belirsizlik heatmap | Ed Chen |

### 5.3 ML Components

| Component | Açıklama | Kaynak |
|-----------|----------|--------|
| **ModelCard** | Model kartı | Ed Chen |
| **ConfusionMatrix** | Karışıklık matrisi | Ed Chen |
| **FeatureImportance** | Feature önem sırası | Ed Chen |
| **DriftMonitor** | Drift izleme | Ed Chen |
| **ExperimentTracker** | Deney takibi | Ed Chen |
| **ChampionChallenger** | Champion-challenger | Ed Chen |

### 5.4 Data Display Components

| Component | Açıklama | Kaynak |
|-----------|----------|--------|
| **DataGrid** | Veri ızgarası (sortable, filterable) | shadcn/ui |
| **TreeView** | Ağaç görünümü | shadcn/ui |
| **KanbanBoard** | Kanban tahtası | shadcn/ui |
| **CalendarView** | Takvim görünümü | shadcn/ui |
| **Timeline** | Zaman çizelgesi | Ed Chen |
| **StatMetric** | İstatistik metrik | Ed Chen |
| **KeyValue** | Anahtar-değer | Ed Chen |

### 5.5 Interaction Components

| Component | Açıklama | Kaynak |
|-----------|----------|--------|
| **CommandPalette** | Komut paleti (Ctrl+K) | shadcn/ui |
| **NotificationCenter** | Bildirim merkezi | shadcn/ui |
| **ContextMenu** | Sağ tık menüsü | shadcn/ui |
| **KeyboardShortcuts** | Kısayol tuşları | shadcn/ui |
| **ResizablePanel** | Yeniden boyutlandırılabilir panel | shadcn/ui |
| **Drawer** | Çekmece | shadcn/ui |

---

## 6. Sayfa Tasarımları (Detaylı)

### 6.1 Overview (Ana Sayfa)

```
┌─────────────────────────────────────────────────────────────┐
│  HEADER: ALPHA BIST | 14:32:15 | BIST 100: 9,842 (+1.2%)  │
├────────┬────────────────────────────────────────────────────┤
│        │ ┌──────────┐ ┌──────────┐ ┌──────────┐           │
│        │ │ REGIME   │ │ RISK     │ │ AI       │           │
│ SIDE   │ │ BULL     │ │ LOW      │ │ 78%      │           │
│ BAR    │ │ ↑ Trend  │ │ VaR: 2%  │ │ LONG     │           │
│        │ └──────────┘ └──────────┘ └──────────┘           │
│        │ ┌──────────────────────────────────────┐         │
│        │ │ TOP OPPORTUNITIES                    │         │
│        │ │ #1 THYAO  Score:91  LONG  +8.2%      │         │
│        │ │ #2 GARAN  Score:87  LONG  +6.1%      │         │
│        │ │ #3 ASELS  Score:84  LONG  +5.8%      │         │
│        │ └──────────────────────────────────────┘         │
│        │ ┌──────────────────────────────────────┐         │
│        │ │ PORTFOLIO SUMMARY                    │         │
│        │ │ Equity: ₺108,542  Cash: ₺23,418     │         │
│        │ │ Daily P&L: +₺1,234 (+1.15%)         │         │
│        │ │ [P&L GRAFİK]                         │         │
│        │ └──────────────────────────────────────┘         │
│        │ ┌──────────────────┐ ┌──────────────────┐       │
│        │ │ RECENT EVENTS    │ │ SYSTEM HEALTH    │       │
│        │ │ • KAP: THYAO...  │ │ API: ✅          │       │
│        │ │ • Macro: TCMB... │ │ DB: ✅           │       │
│        │ └──────────────────┘ └──────────────────┘       │
└────────┴────────────────────────────────────────────────────┘
```

### 6.2 Market Radar

```
┌─────────────────────────────────────────────────────────────┐
│  MARKET RADAR  | Filtreler: [Sektör▼] [Skor▼] [Risk▼]    │
├────────────────────────────────────────────────────────────┤
│  ┌─────────────────────────────────────────────────────┐  │
│  │ HEATMAP (Sektör bazlı)                              │  │
│  │ ┌─────┐ ┌─────┐ ┌─────┐ ┌─────┐ ┌─────┐          │  │
│  │ │BANK │ │SANAY│ │TEKNO│ │PERAK│ │ENERJ│          │  │
│  │ │+2.1%│ │+1.5%│ │+3.2%│ │-0.5%│ │+0.8%│          │  │
│  │ └─────┘ └─────┘ └─────┘ └─────┘ └─────┘          │  │
│  └─────────────────────────────────────────────────────┘  │
│  ┌─────────────────────────────────────────────────────┐  │
│  │ TABLO (sortable, filterable)                        │  │
│  │ Hisse  | Fiyat  | Değişim | Skor | Risk | Momentum │  │
│  │ THYAO  | 320.50 | +2.1%   | 91   | LOW  | ↑↑      │  │
│  │ GARAN  | 98.20  | +1.8%   | 87   | MED  | ↑       │  │
│  │ ASELS  | 62.40  | +3.5%   | 84   | LOW  | ↑↑↑     │  │
│  └─────────────────────────────────────────────────────┘  │
└────────────────────────────────────────────────────────────┘
```

### 6.3 Asset Research

```
┌─────────────────────────────────────────────────────────────┐
│  THYAO | Türk Hava Yolları | BIST 30 | Ulaştırma          │
├────────┬────────────────────────────────────────────────────┤
│        │ ┌─────────────────────────────────────────────┐  │
│        │ │ TRADINGVIEW GRAFİK (candlestick + volume)   │  │
│        │ │ [1G] [1H] [15D] [1A] [3A] [1Y]             │  │
│        │ └─────────────────────────────────────────────┘  │
│        │ ┌──────────┐ ┌──────────┐ ┌──────────┐          │
│ FİYAT  │ │ TEKNİK   │ │ FUNDAM.  │ │ SENTIMENT│          │
│ 320.50 │ │ RSI: 62  │ │ P/E: 8.5 │ │ +0.72    │          │
│ +2.1%  │ │ MACD: ↑  │ │ P/B: 1.2 │ │ Volume: ↑│          │
│        │ │ Trend: ↑ │ │ ROE: 18% │ │ KAP: +   │          │
│        │ └──────────┘ └──────────┘ └──────────┘          │
│        │ ┌──────────┐ ┌──────────┐ ┌──────────┐          │
│ SKOR   │ │ SPEC: 78 │ │ F-Score: │ │ Risk:    │          │
│ 91     │ │ ↑        │ │ 7/9      │ │ LOW      │          │
│        │ └──────────┘ └──────────┘ └──────────┘          │
│        │ ┌─────────────────────────────────────────────┐  │
│        │ │ HABER/KAP AKIŞI                             │  │
│        │ │ • THYAO: Q3 sonuçları beklentileri aştı...  │  │
│        │ │ • THYAO: Yeni hat açılışı...                 │  │
│        │ └─────────────────────────────────────────────┘  │
│        │ ┌─────────────────────────────────────────────┐  │
│        │ │ KARAR: BUY | Confidence: 78% | Entry: 318   │  │
│        │ │ Stop: 305 | Target 1: 340 | Target 2: 360   │  │
│        │ └─────────────────────────────────────────────┘  │
└────────┴────────────────────────────────────────────────────┘
```

### 6.4 Risk Dashboard

```
┌─────────────────────────────────────────────────────────────┐
│  RISK DASHBOARD                                             │
├────────────────────────────────────────────────────────────┤
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐     │
│  │ PORTFOLIO│ │ CONCEN-  │ │ LIQUIDITY│ │ DRAWDOWN │     │
│  │ RISK     │ │ TRATION  │ │          │ │          │     │
│  │ LOW      │ │ MEDIUM   │ │ GOOD     │ │ 2.1%     │     │
│  │ VaR: 2%  │ │ HHI: 0.15│ │ Score:85 │ │ Max: 5%  │     │
│  └──────────┘ └──────────┘ └──────────┘ └──────────┘     │
│  ┌─────────────────────────────────────────────────────┐  │
│  │ RISK MATRIX (Heatmap)                               │  │
│  │ Sector    | Exposure | VaR  | Correlation           │  │
│  │ Bankacılık| 25%      | 1.2% | 0.65                  │  │
│  │ Sanayi    | 20%      | 1.8% | 0.45                  │  │
│  │ Teknoloji | 15%      | 2.1% | 0.35                  │  │
│  └─────────────────────────────────────────────────────┘  │
│  ┌─────────────────────────────────────────────────────┐  │
│  │ NEDEN YÜKSELDİ?                                     │  │
│  │ • Bankacılık sektörü konsantrasyonu arttı           │  │
│  │ • USDTRY volatilitesi yükseldi                      │  │
│  └─────────────────────────────────────────────────────┘  │
└────────────────────────────────────────────────────────────┘
```

### 6.5 Research & Documentation

```
┌─────────────────────────────────────────────────────────────┐
│  RESEARCH & DOCUMENTATION                                   │
├────────┬────────────────────────────────────────────────────┤
│        │ ┌─────────────────────────────────────────────┐  │
│ BIST   │ │ BIST KURALLARI                              │  │
│ Kurall.│ │ İşlem saatleri: 10:00-18:00 (tek seans)    │  │
│        │ │ Fiyat limitleri: Yıldız ±%20, Ana ±%15     │  │
│ Modül  │ │ Açığa satış: BIST-50, yukarı adım kuralı   │  │
│ Spec'ler│ │ Komisyon: Broker %0.03-0.2 + BIST %0.0056 │  │
│        │ │ Temettü stopajı: %15 (2025)                │  │
│ Tech   │ └─────────────────────────────────────────────┘  │
│ Stack  │ ┌─────────────────────────────────────────────┐  │
│        │ │ MODÜL NİHAİ SPEC'LERİ                       │  │
│ Bağım- │ │ [agents] [alternative] [api] [backtest]     │  │
│ lılık  │ │ [core] [dashboard] [event_study] [factors]  │  │
│        │ │ [features] [ingestion] [intelligence]       │  │
│ Test   │ │ [learning] [macro] [market_state] [ml]      │  │
│ Beklent│ │ [portfolio] [risk] [scanner] [scheduler]    │  │
│        │ │ [simulation] [techstack] [viop]             │  │
│ Sistem │ └─────────────────────────────────────────────┘  │
│ Tanımı │ ┌─────────────────────────────────────────────┐  │
│        │ │ TECH STACK                                  │  │
│        │ │ ✅ FastAPI, PostgreSQL, ClickHouse, Redis   │  │
│        │ │ ✅ LightGBM, XGBoost, scikit-learn          │  │
│        │ │ ❌ CatBoost, Optuna, SHAP, MLflow, Grafana  │  │
│        │ └─────────────────────────────────────────────┘  │
└────────┴────────────────────────────────────────────────────┘
```

---

## 7. Micro-Interactions

### 7.1 Animasyonlar

| Animasyon | Kullanım | Süre |
|-----------|----------|------|
| **CountUp** | Sayı değişimi | 300ms |
| **FadeIn** | Kart açılma | 200ms |
| **SlideIn** | Panel kayma | 250ms |
| **Pulse** | Canlı indicator | 2s loop |
| **Shimmer** | Yükleme durumu | 1.5s loop |
| **Glow** | Kâr/zarar vurgusu | 500ms |
| **Blink** | Alarm uyarısı | 1s loop |

### 7.2 Hover Efektleri

```css
/* Kart hover */
.card:hover {
  transform: translateY(-2px);
  box-shadow: 0 8px 32px rgba(0, 0, 0, 0.3);
  border-color: var(--accent-primary);
}

/* Buton hover */
.btn:hover {
  background: var(--gradient-accent);
  transform: scale(1.02);
}

/* Tablo satır hover */
.row:hover {
  background: var(--bg-hover);
}
```

---

## 8. Keyboard Shortcuts

| Kısayol | Aksiyon |
|---------|---------|
| `Ctrl+K` | Command palette aç |
| `Ctrl+/` | Arama |
| `Ctrl+B` | Sidebar toggle |
| `Ctrl+1-9` | Sayfa geçiş |
| `↑↓` | Tablo satır seçimi |
| `Enter` | Seçili detay |
| `Esc` | Modal kapat |
| `R` | Refresh |
| `?` | Kısayol listesi |

---

## 9. Responsive Tasarım

### 9.1 Breakpoint'ler

```
Desktop (1280px+):  12 sütun grid, sidebar açık
Tablet (768-1279px): 8 sütun grid, sidebar collapsed
Mobil (< 768px):    4 sütun grid, sidebar hidden, bottom nav
```

### 9.2 Mobil Düzen

```
┌─────────────────────┐
│ ALPHA BIST   ≡     │
├─────────────────────┤
│ ┌─────────────────┐ │
│ │ BIST 100        │ │
│ │ 9,842 (+1.2%)   │ │
│ └─────────────────┘ │
│ ┌─────────────────┐ │
│ │ Portfolio        │ │
│ │ ₺108,542        │ │
│ └─────────────────┘ │
│ ┌─────────────────┐ │
│ │ Opportunities    │ │
│ │ THYAO: 91       │ │
│ └─────────────────┘ │
├─────────────────────┤
│ 🏠 📊 💼 ⚙️ 🔔    │
└─────────────────────┘
```

---

## 10. Rakip Karşılaştırma

### 10.1 Ed Chen Institutional Finance Design System

| Özellik | Ed Chen | Bizim Sistem | Fark |
|---------|---------|-------------|------|
| Financial components | 25+ | 0 | ❌ |
| AI/ML components | 15+ | 0 | ❌ |
| Compliance components | 10+ | 0 | ⚠️ |
| Design tokens | ✅ | ❌ | ❌ |
| Accessibility | ✅ WCAG 2.1 AA | ❌ | ❌ |

### 10.2 Bloomberg Terminal

| Özellik | Bloomberg | Bizim Sistem | Fark |
|---------|-----------|-------------|------|
| Information density | ⭐⭐⭐⭐⭐ | ⭐⭐ | ⚠️ |
| Real-time data | ⭐⭐⭐⭐⭐ | ⭐⭐⭐ | ⚠️ |
| Charting | ⭐⭐⭐⭐⭐ | ⭐⭐ | ⚠️ |
| Keyboard navigation | ⭐⭐⭐⭐⭐ | ⭐ | ❌ |
| Dark theme | ⭐⭐⭐⭐⭐ | ⭐⭐ | ⚠️ |

---

## 11. Uygulama Planı

### Faz 1: Design System (Hemen)
1. Renk token'ları
2. Tipografi sistemi
3. Spacing sistemi
4. shadcn/ui entegrasyonu

### Faz 2: Core Components (1 hafta)
1. PriceDisplay, P&LDisplay, StatMetric
2. Candlestick, Heatmap, Sparkline
3. DataGrid (sortable, filterable)
4. OrderBook, DepthIndicator

### Faz 3: Financial Components (1 hafta)
1. PositionCard, TradeTicket, WatchlistRow
2. RiskMatrix, AlertConfig
3. SessionClock, EconomicCalendar
4. Allocation, SpreadDisplay

### Faz 4: AI/ML Components (1 hafta)
1. CalibratedConfidence, ReasoningChain
2. ModelCard, FeatureImportance, DriftMonitor
3. ChampionChallenger, ExperimentTracker
4. AgentToolCallTrace, SafetyGuardrails

### Faz 5: Pages (2 hafta)
1. Overview, Market Radar, Asset Research
2. Portfolio, Risk Dashboard
3. Research & Documentation
4. Learning, Backtest, Agent Dashboard

### Faz 6: Interactions (1 hafta)
1. Keyboard shortcuts
2. Command palette
3. Notification center
4. Micro-animations
