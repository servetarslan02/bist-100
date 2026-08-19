# 🚀 Scanner System Nihai Mimari — Uygulama Planı

**Tarih:** 2026-08-20
**Hazırlayan:** AI Analiz (Kod Analizi + Araştırma)
**Kaynaklar:** Mometic Top 10 Scanners (2026), TradeAlgo Algorithm Guide (2026), TradingAgents (TauricResearch 2025), awesome-quant GitHub, Mevcut kod analizi

---

## 📋 İçindekiler

1. [Araştırma Bulguları](#1-araştırma-bulguları)
2. [Mevcut Sistem Analizi](#2-mevcut-sistem-analizi)
3. [Eksiklikler ve Nihai Hedef](#3-eksiklikler-ve-nihai-hedef)
4. [Genel Mimari Tasarım](#4-genel-mimari-tasarım)
5. [Faz Planı](#5-faz-planı)
6. [Test Stratejisi](#6-test-stratejisi)

---

## 1. Araştırma Bulguları

### 1.1 Mometic — Top 10 Stock Scanners (2026)

**En iyi uygulama:**
- **Real-time tick processing**: Her tick'te state güncelle, geçmiş veriyi baştan okuma
- **Multi-factor screening**: Momentum, value, quality, volume, volatilite birlikte
- **Custom filters**: Kullanıcı tanımlı filtreler (BIST'e özel kurallar)
- **Alert integration**: Kritik sinyal → anlık bildirim
- **Scan scheduling**: Piyasa saatlerinde otomatik tarama

### 1.2 TradeAlgo — Algorithm Guide (2026)

**En iyi uygulama:**
- **Tiered approach**: Ucuz filtrelerden pahalıya doğru katmanlı eleme
- **Algorithm-based screening**: Matematiksel formüllerle tutarlı tarama
- **Multi-factor ranking**: Birden fazla faktörün ağırlıklı sıralaması
- **Backtest integration**: Tarama stratejisinin tarihsel doğrulaması

### 1.3 TradingAgents — TauricResearch (2025)

**En iyi uygulama:**
- **Event-driven scanning**: KAP/haber geldiğinde anında tarama
- **Multi-agent scanning**: Farklı agent'lar farklı perspektiflerden tarar
- **Priority queue**: Önemli olaylar önce işlenir
- **Decision log**: Her tarama kararı kaydedilir

### 1.4 Genel En İyi Uygulamalar

| Özellik | Açıklama | Kaynak |
|---------|----------|--------|
| **Deduplication** | Aynı hisse cooldown süresince tekrar taranmaz | Endüstri standardı |
| **Adaptive scheduling** | Volatilite artınca tarama sıklığı artar | Mometic, TradeAlgo |
| **Scan persistence** | Tarama sonuçları DB'ye kaydedilir | TradingAgents |
| **Performance tracking** | Hit rate, duration, opportunity count takibi | Endüstri standardı |
| **Backtest-scanner parity** | Aynı kod hem backtest'te hem canlıda çalışır | awesome-quant |
| **Custom filters** | Kullanıcı tanımlı filtreler | Mometic |
| **Multi-asset** | Hisse + VIOP + opsiyon | Gelecek vizyonu |

---

## 2. Mevcut Sistem Analizi

### 2.1 Modül Özeti (8 dosya, 2,936 satır)

| Modül | Satır | Ne Yapıyor | Durum |
|-------|-------|------------|-------|
| `tiered_scanner.py` | 602 | 6 katmanlı tarama (Tier 0-5), regime-aware ağırlıklar | ✅ En kapsamlı |
| `backtest_runner.py` | 557 | Scanner backtest, portfolio simulator, feature cache | ✅ İyi |
| `opportunity_engine.py` | 499 | 10 bileşenli fırsat skoru, universe scan | ✅ İyi |
| `alpha_scanner.py` | 422 | Alpha tarama, breakout, volume acceleration, signal generation | ✅ İyi |
| `alpha_engine.py` | 361 | Ana motor, 3 katmanlı tarama (live/batch/event) | ✅ İyi |
| `event_scanner.py` | 203 | Event-driven tarama, KAP/haber/macro tepkisi | ✅ İyi |
| `live_scanner.py` | 155 | Gerçek zamanlı tick tarama, aday tespit | ✅ İyi |
| `event_queue.py` | 137 | Öncelikli event kuyruğu, async worker | ✅ İyi |

### 2.2 Mevcut Güçlü Yönler

1. **6 katmanlı tarama**: Tier 0-5 ile verimli eleme
2. **Regime-aware ağırlıklar**: Rejime göre tarama kriterleri değişiyor
3. **10 bileşenli fırsat skoru**: Teknik, momentum, hacim, volatilite, rejim, risk...
4. **Event-driven escalation**: KAP/haber/macro → tier atlama
5. **3 katmanlı motor**: Live (tick), Batch (periyodik), Event (anlık)
6. **Backtest entegrasyonu**: Scanner stratejisinin tarihsel doğrulaması
7. **Priority queue**: Önemli olaylar önce işleniyor
8. **Feature cache**: Hesaplanmış feature'lar tekrar hesaplanmıyor

### 2.3 Kritik Eksiklikler

| # | Eksiklik | Etki | Öncelik |
|---|----------|------|---------|
| 1 | **Deduplication yok** | Aynı hisse tekrar tekrar taranıyor, CPU israfı | 🔴 Kritik |
| 2 | **Scan scheduling yok** | Piyasa saatlerinde otomatik tarama yapılmıyor | 🔴 Kritik |
| 3 | **Scan persistence yok** | Tarama sonuçları kalıcı saklanmıyor | 🟡 Yüksek |
| 4 | **Performance tracking yok** | Hangi strateji daha iyi bilinmiyor | 🟡 Yüksek |
| 5 | **Alert integration zayıf** | Kritik fırsatlar bildirilmiyor | 🟡 Yüksek |
| 6 | **Backtest-scanner parity yok** | Backtest ile canlı farklı olabilir | 🟡 Yüksek |
| 7 | **Custom filters yok** | BIST'e özel filtreler eklenemiyor | 🟠 Orta |
| 8 | **Scan metrics API yok** | Tarama istatistikleri API'den alınamıyor | 🟠 Orta |

---

## 3. Nihai Hedef — Scanner Pipeline v2.0

```
┌─────────────────────────────────────────────────────────────┐
│                    SCANNER PIPELINE v2.0                      │
│                                                             │
│  ┌─────────────────────────────────────────────────────┐   │
│  │  TIER 0: CONTINUOUS WATCH (800 hisse)               │   │
│  │  ✅ Fiyat, hacim, bid/ask, spread                   │   │
│  │  ✅ Real-time tick processing                        │   │
│  │  🆕 Deduplication (cooldown kontrolü)               │   │
│  └─────────────────────────┬───────────────────────────┘   │
│                            ↓                                │
│  ┌─────────────────────────────────────────────────────┐   │
│  │  TIER 1: QUANT SCAN (800 → ~200)                    │   │
│  │  ✅ Momentum, volume anomaly, breakout, volatility  │   │
│  │  ✅ Relative strength, sector divergence             │   │
│  │  ✅ Regime-aware ağırlıklar                          │   │
│  └─────────────────────────┬───────────────────────────┘   │
│                            ↓                                │
│  ┌─────────────────────────────────────────────────────┐   │
│  │  TIER 2: OPPORTUNITY SCORE (200 → ~50)              │   │
│  │  ✅ 10 bileşenli fırsat skoru                        │   │
│  │  ✅ Risk-adjusted skor                               │   │
│  │  🆕 Custom filter desteği                            │   │
│  └─────────────────────────┬───────────────────────────┘   │
│                            ↓                                │
│  ┌─────────────────────────────────────────────────────┐   │
│  │  TIER 3: DEEP ANALYSIS (50 → ~10)                   │   │
│  │  ✅ ML model tahminleri                              │   │
│  │  ✅ Tarihsel analog arama                            │   │
│  │  ✅ Senaryo analizi                                  │   │
│  └─────────────────────────┬───────────────────────────┘   │
│                            ↓                                │
│  ┌─────────────────────────────────────────────────────┐   │
│  │  TIER 4: AI ASSESSMENT (10 → ~3-5)                  │   │
│  │  ✅ LLM analiz (Ollama)                              │   │
│  │  ✅ Sentiment, neden-sonuç, confidence               │   │
│  └─────────────────────────┬───────────────────────────┘   │
│                            ↓                                │
│  ┌─────────────────────────────────────────────────────┐   │
│  │  TIER 5: DECISION (3-5 → 0-3)                       │   │
│  │  ✅ BUY/SELL/HOLD                                    │   │
│  │  ✅ Pozisyon boyutu, stop/target                     │   │
│  └─────────────────────────┬───────────────────────────┘   │
│                            ↓                                │
│  ┌─────────────────────────────────────────────────────┐   │
│  │  EVENT-DRIVEN ESCALATION                             │   │
│  │  ✅ KAP/haber/macro → tier atlama                    │   │
│  │  ✅ Priority queue                                   │   │
│  └─────────────────────────┬───────────────────────────┘   │
│                            ↓                                │
│  ┌─────────────────────────────────────────────────────┐   │
│  │  🆕 SCAN SCHEDULER                                   │   │
│  │  - Piyasa saatlerinde otomatik tarama               │   │
│  │  - Volatilite artınca sık tarama                    │   │
│  │  - Event gelince acil tarama                        │   │
│  │  - Piyasa kapalıyken duraklat                       │   │
│  └─────────────────────────┬───────────────────────────┘   │
│                            ↓                                │
│  ┌─────────────────────────────────────────────────────┐   │
│  │  🆕 SCAN RESULT PERSISTENCE                          │   │
│  │  - Tarama sonuçları DB'ye kaydet                    │   │
│  │  - Geçmiş tarama analizi                            │   │
│  │  - Performance tracking                             │   │
│  └─────────────────────────┬───────────────────────────┘   │
│                            ↓                                │
│  ┌─────────────────────────────────────────────────────┐   │
│  │  🆕 ALERT INTEGRATION                                │   │
│  │  - Kritik fırsat → bildirim                         │   │
│  │  - Tier değişimi → bildirim                         │   │
│  │  - Anomaly → acil bildirim                          │   │
│  └─────────────────────────┬───────────────────────────┘   │
│                            ↓                                │
│  ┌─────────────────────────────────────────────────────┐   │
│  │  🆕 CUSTOM FILTERS                                   │   │
│  │  - BIST'e özel filtreler (SPK limitleri, vb.)       │   │
│  │  - Kullanıcı tanımlı kurallar                       │   │
│  └─────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────┘
```

---

## 4. Faz Planı

### FAZ 1: Deduplication (Hemen)

**Amaç:** Aynı hissenin gereksiz yere tekrar tekrar taranmasını önle.

```
Dosya: services/scanner/deduplicator.py
```
- [ ] `ScanDeduplicator` sınıfı
  - [ ] `should_scan(ticker)` — cooldown kontrolü
  - [ ] `force_scan(ticker)` — event-driven zorla tarama
  - [ ] `get_stats()` — istatistikler
  - [ ] Configurable cooldown (default 300 saniye)
  - [ ] Per-ticker cooldown (farklı hisseler için farklı süre)
  - [ ] Event-driven force scan (KAP/haber gelince cooldown bypass)

**Entegrasyon:**
- [ ] `tiered_scanner.py`'de `process_tick()`'e deduplication ekle
- [ ] `alpha_scanner.py`'de `scan()`'a deduplication ekle
- [ ] `event_scanner.py`'de `on_event()`'da force scan

**Teslimat:** `pytest tests/test_scanner_faz1.py`

---

### FAZ 2: Adaptive Scan Scheduler (1-2 gün)

**Amaç:** Piyasa koşullarına göre tarama sıklığını otomatik ayarla.

```
Dosya: services/scanner/scan_scheduler.py
```
- [ ] `AdaptiveScanScheduler` sınıfı
  - [ ] `get_scan_interval(volatility, regime, has_event)` — tarama aralığı
  - [ ] Volatilite bazlı: yüksek vol → 15 sn, düşük vol → 120 sn
  - [ ] Rejim bazlı: PANIC/RISK-OFF → 15 sn
  - [ ] Event bazlı: event varsa → 10 sn
  - [ ] Piyasa saatleri kontrolü (09:55 - 18:05 BIST)
  - [ ] `start()` / `stop()` — scheduler lifecycle

**Entegrasyon:**
- [ ] `alpha_engine.py`'de batch scan scheduler ile çalışsın
- [ ] Event geldiğinde scheduler'ı hızlandır

**Teslimat:** `pytest tests/test_scanner_faz2.py`

---

### FAZ 3: Scan Result Persistence (1-2 gün)

**Amaç:** Tarama sonuçlarını kalıcı olarak sakla, geçmiş analiz yap.

```
Dosya: services/scanner/scan_persistence.py
```
- [ ] `ScanPersistence` sınıfı
  - [ ] `save_scan_result(results, scan_type)` — DB'ye kaydet
  - [ ] `get_scan_history(ticker, days)` — geçmiş taramalar
  - [ ] `get_scan_stats(scan_type)` — tarama istatistikleri
  - [ ] `get_hit_rate(scan_type, days)` — isabet oranı
  - [ ] SQLite tablosu: `scan_results`
  - [ ] Tablo şeması: id, scan_type, ticker, score, signal, direction, confidence, regime, timestamp

**Entegrasyon:**
- [ ] `alpha_scanner.py`'de `scan()` sonucu persistence'a kaydet
- [ ] `opportunity_engine.py`'de `scan_universe()` sonucu kaydet

**Teslimat:** `pytest tests/test_scanner_faz3.py`

---

### FAZ 4: Performance Tracker (1 gün)

**Amaç:** Tarama performansını takip et, hangi strateji daha iyi öğren.

```
Dosya: services/scanner/performance_tracker.py
```
- [ ] `ScanPerformanceTracker` sınıfı
  - [ ] `record_scan(scan_type, tickers_scanned, opportunities, duration_ms)` — tarama kaydet
  - [ ] `get_stats(scan_type)` — istatistikler (avg duration, hit rate, avg opportunities)
  - [ ] `get_regime_performance(regime)` — rejim bazlı performans
  - [ ] `get_signal_accuracy(signal_type, days)` — sinyal doğruluğu
  - [ ] `get_top_performing_filters()` — en iyi filtreler

**Entegrasyon:**
- [ ] Tüm scanner modülleri performance tracker'a kayıt yapsın
- [ ] Backtest runner ile canlı performans karşılaştırması

**Teslimat:** `pytest tests/test_scanner_faz4.py`

---

### FAZ 5: Alert Integration (1 gün)

**Amaç:** Kritik tarama sonuçlarını bildirim sistemine bağla.

```
Dosya: services/scanner/scan_alerts.py
```
- [ ] `ScanAlertManager` sınıfı
  - [ ] `check_scan_results(results)` — sonuçları kontrol et
  - [ ] Alert kuralları:
    - [ ] Score > 80 → INFO
    - [ ] Score > 90 → WARNING
    - [ ] Tier değişimi (event escalation) → WARNING
    - [ ] Anomaly (volume_zscore > 4) → CRITICAL
    - [ ] Yeni sinyal (önceki taramada yoktu) → INFO
  - [ ] Cooldown: aynı hisse için 5 dakikada 1 alert
  - [ ] `register_callback(callback)` — alert callback

**Entegrasyon:**
- [ ] Risk monitoring alert sistemi ile entegrasyon
- [ ] Event bus ile alert publish

**Teslimat:** `pytest tests/test_scanner_faz5.py`

---

### FAZ 6: Custom Filters (1 gün)

**Amaç:** BIST'e özel ve kullanıcı tanımlı filtreler.

```
Dosya: services/scanner/custom_filters.py
```
- [ ] `CustomFilterEngine` sınıfı
  - [ ] `add_filter(name, condition, description)` — filtre ekle
  - [ ] `apply_filters(results)` — filtreleri uygula
  - [ ] BIST hazır filtreleri:
    - [ ] SPK %10 limit kontrolü
    - [ ] Minimum hacim filtresi (günlük 100K+ lot)
    - [ ] Minimum fiyat filtresi (1 TL altı hariç)
    - [ ] Sektör rotasyon filtresi
    - [ ]akış filtresi (son 5 günde yabancı alımı)
  - [ ] Kullanıcı tanımlı filtre DSL (basit if/then kuralları)

**Teslimat:** `pytest tests/test_scanner_faz6.py`

---

### FAZ 7: Scan Metrics API (1 gün)

**Amaç:** Tarama istatistiklerini API'den erişilebilir yap.

```
Dosya: services/scanner/scan_api.py
```
- [ ] `GET /api/scan/status` — tarama durumu
- [ ] `GET /api/scan/results` — son tarama sonuçları
- [ ] `GET /api/scan/history/{ticker}` — hisse tarama geçmişi
- [ ] `GET /api/scan/performance` — performans istatistikleri
- [ ] `GET /api/scan/alerts` — son alert'ler
- [ ] `GET /api/scan/tiers` — tier bazlı özet
- [ ] `POST /api/scan/trigger` — manuel tarama tetikle

**Teslimat:** `pytest tests/test_scanner_faz7.py`

---

### FAZ 8: Backtest-Scanner Parity (1 gün)

**Amaç:** Backtest ve canlı tarama aynı kod yolunu kullansın.

```
Dosya: services/scanner/scanner_interface.py
```
- [ ] `ScannerInterface` abstract class
  - [ ] `scan(universe, features, regime, ...)` → `List[ScannerResult]`
  - [ ] `get_opportunities(results, top_n)` → `List[Dict]`
  - [ ] `generate_signals(results)` → `List[Signal]`
- [ ] `AlphaScanner` bu interface'i implement etsin
- [ ] `BacktestRunner` aynı interface'i kullansın
- [ ] Feature cache paylaşımı

**Teslimat:** `pytest tests/test_scanner_faz8.py`

---

## 5. Test Stratejisi

| Faz | Test Dosyası | Min Test | Kritik Test |
|-----|-------------|----------|-------------|
| 1 | test_scanner_faz1.py | 8 | Deduplication cooldown |
| 2 | test_scanner_faz2.py | 6 | Adaptive interval |
| 3 | test_scanner_faz3.py | 8 | Persistence read/write |
| 4 | test_scanner_faz4.py | 6 | Performance stats |
| 5 | test_scanner_faz5.py | 6 | Alert triggering |
| 6 | test_scanner_faz6.py | 6 | Custom filter |
| 7 | test_scanner_faz7.py | 6 | API endpoints |
| 8 | test_scanner_faz8.py | 6 | Interface parity |

---

## 📊 Zaman Özeti

| Faz | Süre | Teslimat |
|-----|------|----------|
| **Faz 1** | 1 gün | Deduplication |
| **Faz 2** | 1-2 gün | Adaptive scheduler |
| **Faz 3** | 1-2 gün | Scan persistence |
| **Faz 4** | 1 gün | Performance tracker |
| **Faz 5** | 1 gün | Alert integration |
| **Faz 6** | 1 gün | Custom filters |
| **Faz 7** | 1 gün | Scan metrics API |
| **Faz 8** | 1 gün | Backtest-scanner parity |
| **TOPLAM** | **8-10 gün** | |

---

## 📚 Referanslar

1. Mometic — Top 10 Stock Scanners (2026)
2. TradeAlgo — Algorithm Guide (2026)
3. TradingAgents — TauricResearch (2025)
4. awesome-quant — GitHub
5. Mevcut kod analizi (8 dosya, 2,936 satır)
