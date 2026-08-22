# 02 — Scanner Modülü

## Rolü

Scanner modülü, ALPHA BIST sisteminin "fırsat keşif" katmanıdır. 800+ BIST hissesini gerçek zamanlı veya batch olarak tarayarak en güçlü alım-satım fırsatlarını bulur, risk-adjusted skorlar üretir ve sinyal oluşturur. Backtest ile aynı kod yolunu kullanarak "farklı kod = farklı sonuç" problemini çözer.

## Katman Haritası

```
┌─────────────────────────────────────────────────────────────────────┐
│                        SCANNER MODÜLÜ                               │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  ┌─────────────────────────────────────────────────────────────┐   │
│  │                    alpha_engine.py                           │   │
│  │  Ana motor — 3 katmanlı tarama orchestrator                 │   │
│  │  Layer 1: Live (tick) · Layer 2: Batch · Layer 3: Event     │   │
│  └────────┬──────────────────┬──────────────────┬──────────────┘   │
│           │                  │                  │                   │
│           ▼                  ▼                  ▼                   │
│  ┌────────────────┐ ┌────────────────┐ ┌─────────────────────┐    │
│  │ live_scanner.py│ │ alpha_scanner  │ │ event_scanner.py    │    │
│  │ (Tick bazlı)   │ │ .py            │ │ (KAP/Haber/Makro)   │    │
│  │ State tracking │ │ (Merkezi       │ │ Etkilenen hisseleri │    │
│  │ Hafif tarama   │ │  pipeline)     │ │ anında yeniden tara │    │
│  └────────────────┘ └───────┬────────┘ └─────────────────────┘    │
│                             │                                       │
│                             ▼                                       │
│  ┌─────────────────────────────────────────────────────────────┐   │
│  │              opportunity_engine.py                           │   │
│  │  Çok boyutlu fırsat skoru (10 bileşen)                      │   │
│  │  Rejime göre ağırlık · Risk-adjusted ranking                │   │
│  └─────────────────────────────────────────────────────────────┘   │
│                                                                     │
│  ┌─────────────────────────────────────────────────────────────┐   │
│  │              tiered_scanner.py                               │   │
│  │  Katmanlı filtreleme: Tier 0→5                              │   │
│  │  800→50→10→3-5→0-3 (ucuzdan pahalıya)                      │   │
│  │  Event escalation (Tier atla)                               │   │
│  └─────────────────────────────────────────────────────────────┘   │
│                                                                     │
│  ┌────────────────┐ ┌────────────────┐ ┌─────────────────────┐    │
│  │ dynamic_       │ │ scanner_       │ │ backtest_runner.py  │    │
│  │ opportunity_   │ │ interface.py   │ │                     │    │
│  │ scanner.py     │ │ (ABC)          │ │ (v3.0 Optimized)    │    │
│  │ (yfinance ile  │ │ ScanResult     │ │ Feature cache       │    │
│  │  gerçek tarama)│ │ standardı      │ │ Quality cache       │    │
│  └────────────────┘ └────────────────┘ └─────────────────────┘    │
│                                                                     │
│  ┌────────────────┐ ┌────────────────┐ ┌─────────────────────┐    │
│  │ deduplicator.py│ │ scan_scheduler │ │ event_queue.py      │    │
│  │ (Cooldown)     │ │ .py            │ │ (Priority Queue)    │    │
│  │ Force scan     │ │ (Adaptif       │ │ Paralel worker      │    │
│  │ (event bypass) │ │  zamanlama)    │ │ AsyncIO             │    │
│  └────────────────┘ └────────────────┘ └─────────────────────┘    │
│                                                                     │
│  ┌────────────────┐ ┌────────────────┐ ┌─────────────────────┐    │
│  │ custom_filters │ │ scan_alerts.py │ │ performance_tracker │    │
│  │ .py            │ │ (Alert kuralları│ │ .py                 │    │
│  │ BIST filtreleri│ │  Callback)     │ │ (Hit rate, regime,  │    │
│  │ Kullanıcı filt.│ │                │ │  signal accuracy)   │    │
│  └────────────────┘ └────────────────┘ └─────────────────────┘    │
│                                                                     │
│  ┌────────────────┐ ┌────────────────┐                              │
│  │ scan_          │ │ scan_api.py    │                              │
│  │ persistence.py │ │ (REST endpoint)│                              │
│  │ (SQLite)       │ │ Dashboard      │                              │
│  └────────────────┘ └────────────────┘                              │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

## Neden Bu Tasarım Seçimi?

| Karar | Neden |
|-------|-------|
| 3 katmanlı tarama (Live/Batch/Event) | Her tick'te 800 hisseyi taramak CPU israfı. Live sadece değişen hisseyi günceller; batch günde 5-6 kez tam tarama; event geldiğinde anında yeniden tarama. |
| Katmanlı filtreleme (Tier 0→5) | 800 hisseyi her seferinde derin analiz etmek pahalı. Ucuz filtrelerle 800→50→10→3-5→0-3 indirgeme. |
| ScannerInterface (ABC) | Backtest ve canlı tarama aynı interface'i implemente eder → kod tekrarı yok, parity garantisi. |
| Deduplicator + force scan | Aynı hisse 5 dakika içinde tekrar taranmaz (CPU tasarrufu). Ama event geldiğinde cooldown bypass edilir. |
| Adaptif scheduler | Volatilite artınca sık tarama (10sn), sakin piyasada seyrek (300sn). Piyasa kapalıyken duraklat. |
| Event priority queue | 50 hisseyi etkileyen makro olay ana döngüyü bloklamaz. AsyncIO paralel worker ile öncelik sırasıyla işlenir. |
| Custom filters | BIST'e özel filtreler (SPK %10 limit, minimum hacim/fiyat) ve kullanıcı tanımlı filtreler. |
| Alert manager | Skor > 80, yeni sinyal, tier değişimi, hacim anomalisi gibi durumlar için özelleştirilebilir alert kuralları. |

## Uçtan Uca Veri Akışı

```
1. Tetikleme:
   ├─ Tick geldi → live_scanner.process_tick()
   ├─ Zamanlayıcı → alpha_engine.run_batch_scan()
   └─ Event geldi → event_scanner.on_event() → alpha_engine.on_event()
         │
2. Batch Scan Pipeline:
   ├─ Veri çek (yfinance)
   ├─ Feature hesapla (feature_calculator)
   ├─ Market regime tespit (breadth + volatility + momentum)
   ├─ ML skorları (ml_model_loader → ensemble veya quant proxy)
   ├─ Event skorları (event_scanner.get_event_score)
   ├─ Deduplication kontrolü (scan_deduplicator.should_scan)
   ├─ AlphaScanner.scan() → her hisse için quant skor
   │   ├─ Momentum, volume anomaly, breakout, volatility
   │   ├─ Relative strength, sector divergence, flow correlation
   │   └─ Opportunity score = ağırlıklı toplam
   ├─ Custom filters uygula
   ├─ Alert kontrolü
   ├─ Persistence (SQLite)
   ├─ Performance tracking
   └─ Özet döndür
         │
3. Event-driven Pipeline:
   ├─ KAP/haber/makro event → etkilenen hisseleri bul
   ├─ Dedup force scan (cooldown bypass)
   ├─ Her etkilenen hisse için derin analiz
   ├─ Sinyal üret + alert kontrolü
   └─ Persistence + performance tracking
```

## Dosya Bazlı Sorumluluk Tablosu

| Dosya | Sorumluluk |
|-------|-----------|
| `alpha_engine.py` | Ana orchestrator. 3 katmanlı tarama (live/batch/event). Universe yönetimi, regime tespiti, ML skor entegrasyonu, dedup, persistence, alert, performance tracking entegrasyonu. Singleton: `alpha_engine`. |
| `alpha_scanner.py` | Merkezi tarama motoru. 800 hisse → quant scan → opportunity ranking → signal generation. ScannerInterface implementasyonu. Skor bileşenleri: momentum %20, relative_strength %15, volume_anomaly %15, breakout %10, volatility %10, regime_fit %10, event %10, ML %10. Singleton: `alpha_scanner`. |
| `opportunity_engine.py` | Çok boyutlu fırsat skoru. 10 bileşen (technical, fundamental, momentum, volume, volatility, sentiment, valuation, macro, regime, risk). Rejime göre ağırlık değişimi. Evidence ve risk üretimi. Singleton: `opportunity_engine`. |
| `tiered_scanner.py` | Katmanlı filtreleme motoru. Tier 0 (continuous watch) → Tier 1 (quant scan) → Tier 2 (opportunity) → Tier 3 (deep analysis) → Tier 4 (Gemma LLM) → Tier 5 (decision). Event escalation ile tier atlama. Rejime göre ağırlık değişimi. Paralel ThreadPoolExecutor. Singleton: `tiered_scanner`. |
| `live_scanner.py` | Tick bazlı hafif tarayıcı. State update → volume z-score → tick momentum → candidate check (volume anomaly, price shock, momentum build). 100 tick sliding window. Singleton: `live_scanner`. |
| `event_scanner.py` | Event-driven scanner. KAP, haber, makro event → etkilenen hisseleri bul. Sektör exposure graph ile makro etki haritalama. Event skoru (0-100). Cooldown yönetimi. Singleton: `event_scanner`. |
| `dynamic_opportunity_scanner.py` | yfinance ile gerçek piyasa verisi tarama. 4 sinyal türü: VOLUME_BREAKOUT, MOMENTUM_LEADER, PULLBACK_BOUNCE, GOLDEN_CROSS. RSI, SMA20/50, momentum 1M/3M, hacim oranı. Singleton: `dynamic_scanner`. |
| `scanner_interface.py` | Abstract scanner interface (ABC). ScanResult dataclass standardı. scan(), get_opportunities(), generate_signals() metotları. scan_and_rank() convenience metodu. |
| `backtest_runner.py` | ScannerBacktestRunner v3.0. Feature cache, quality cache, portfolio simulator v2.0. AlphaScanner ile aynı skor mantığı. Optimizasyon: pre-compute quality cache, batch trade execution. |
| `deduplicator.py` | Tarama deduplication. Cooldown süresince aynı hisse tekrar taranmaz. Event-driven force scan ile cooldown bypass. LRU eviction (max 1000 ticker). Singleton: `scan_deduplicator`. |
| `scan_scheduler.py` | Adaptif tarama zamanlayıcısı. Volatilite ve rejime göre interval ayarı (10sn-300sn). BIST piyasa saatleri kontrolü (10:00-18:00 UTC+3). Event-driven mod (10sn interval). AsyncIO ana döngü. Singleton: `scan_scheduler`. |
| `event_queue.py` | Event priority queue. AsyncIO PriorityQueue + paralel worker (max 5). Öncelik: kritik=1, yüksek=2, orta=3, düşük=4. KAP her zaman yüksek öncelik. Singleton: `event_queue`. |
| `custom_filters.py` | BIST'e özel filtreler. Minimum hacim (100K lot), minimum fiyat (1 TL), maksimum spread (%5), aşırı alım (RSI>80), düşük volatilite bonusu. Kullanıcı tanımlı filtre ekleme/çıkarma. Singleton: `custom_filter_engine`. |
| `scan_alerts.py` | Alert yöneticisi. Kurallar: score>80 INFO, score>90 WARNING, yeni sinyal, tier değişimi, hacim anomalisi (4σ+), kırılım skoru. Cooldown, callback, severity (INFO/WARNING/BLOCK/CRITICAL). Singleton: `scan_alert_manager`. |
| `performance_tracker.py` | Tarama performans takibi. Scan duration, hit rate, signal accuracy, regime-based performance, top performing filters, hourly distribution. SignalOutcome geriye dönük doğrulama. Singleton: `performance_tracker`. |
| `scan_persistence.py` | SQLite persistence. scan_results tablosu (scan_id, ticker, score, signal, direction, confidence, tier, regime, features). Ticker history, scan stats, hit rate, top scanned tickers. Singleton: `scan_persistence`. |
| `scan_api.py` | REST API endpoint'leri. Status, results, ticker history, performance, alerts, tiers, filters, dedup stats, scheduler stats, full dashboard. Singleton: `scan_api`. |

## Tasarım İlkeleri ve Kırmızı Çizgiler

1. **800 hisseyi her saniye baştan analiz etme.** Katmanlı filtreleme (Tier 0→5) ve deduplication ile CPU verimli kullanılır.
2. **Backtest ile aynı kod yolu.** ScannerInterface (ABC) ve canonical_adapter ile parity garantisi.
3. **Event geldiğinde bekleme.** Event priority queue ile ana döngü bloklanmaz; paralel worker ile anında işlenir.
4. **Rejime göre adaptif.** Ağırlıklar, tarama sıklığı ve filtreler piyasa rejimine göre otomatik ayarlanır.
5. **Cooldown bypass sadece event için.** Normal taramada 5 dakika cooldown; sadece KAP/haber/makro event force scan yapabilir.
6. **Alert spam yok.** Her alert kuralının kendi cooldown süresi var; aynı alert 5-10 dakika içinde tekrar tetiklenmez.

## Bilinen Sınırlamalar

- `dynamic_opportunity_scanner.py` → yfinance ile çalışır; gerçek zamanlı veri akışı yoktur, gecikmeli veri kullanır.
- `alpha_engine.py` → `_compute_ml_scores()` henüz gerçek model yerine quant proxy kullanıyor (ml_model_loader entegrasyonu tamamlanmalı).
- `tiered_scanner.py` → Tier 4 (Gemma LLM) ve Tier 5 (Decision) henüz tam implemente edilmemiş; sadece kriter filtresi var.
- `backtest_runner.py` → v3.0 optimize edilmiş ama canonical scoring desteği yok; sadece legacy skor mantığı.
- `event_scanner.py` → `_get_macro_affected_stocks()` hard-coded sektör-stok eşleştirmesi kullanır; dinamik sektör graph entegrasyonu gerekli.

## Cross-Reference

- **Backtest modülü** → `scanner_parity.py` ve `canonical_adapter.py` aracılığıyla aynı scoring fonksiyonunu kullanır. `backtest_runner.py` doğrudan backtest motoru olarak çalışır.
- **Factors modülü** → `opportunity_engine.py` fundamental_score ve valuation_score parametreleri olarak factor skorlarını tüketir.
- **Event Study modülü** → `event_scanner.py` KAP event verilerini tüketir; event skoru hesaplamasında event study sonuçlarını kullanabilir.
- **Features katmanı** → `alpha_scanner.py` ve `backtest_runner.py` feature_calculator modülünü tüketir.
- **ML katmanı** → `alpha_engine.py` ml_model_loader ile ML ensemble skorları alır.
