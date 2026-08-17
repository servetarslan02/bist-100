# Scanner Nihai Sistem Dokümanı — Kod Analizi + Araştırma Bazlı

**Tarih:** 2026-08-18
**Kaynaklar:** Mometic Top 10 Scanners (2026), TradeAlgo Algorithm Guide (2026), awesome-quant GitHub, TradingAgents (TauricResearch 2025), Mevcut kod analizi

---

## 1. Sektörde En İyi Uygulama Nedir?

### 1.1 Scanner Architecture (En İyi Uygulama)

**Temel prensip:** 800+ hisseyi tek tek analiz etmek verimsiz — katmanlı filtreleme ile hızla daralt.

```
SCANNER PIPELINE (En İyi Uygulama)

800+ hisse
    ↓
TIER 0: Continuous Watch (ucuz state — fiyat, hacim)
    ↓
TIER 1: Quant Scan (matematiksel filtre — momentum, volatilite, hacim)
    ↓  800 → ~200
TIER 2: Opportunity Score (çoklu faktör skorlama)
    ↓  200 → ~50
TIER 3: Deep Analysis (ML model, tarihsel analog, senaryo)
    ↓  50 → ~10
TIER 4: AI Assessment (LLM analiz, sentez)
    ↓  10 → ~3-5
TIER 5: Decision (BUY/SELL/HOLD, pozisyon boyutu, stop/target)
    ↓  3-5 → 0-3
RISK GATE → PORTFOLIO
```

### 1.2 Scanner Özellikleri (En İyi Uygulama)

| Özellik | Açıklama | Kaynak |
|---------|----------|--------|
| **Real-time tick processing** | Her tick'te state güncelle | Mometic (2026) |
| **Multi-factor scoring** | Momentum, value, quality, volume, volatilite | TradeAlgo (2026) |
| **Regime-aware** | Rejime göre ağırlık değişimi | awesome-quant |
| **Event-driven escalation** | KAP/haber gelince tarama tetikle | TradingAgents |
| **Backtest integration** | Tarama stratejisi backtest ile doğrula | awesome-quant |
| **Deduplication** | Aynı hisseyi tekrar tekrar tarama | En iyi uygulama |
| **Priority queue** | Önemli olaylar önce işlenir | En iyi uygulama |

---

## 2. Bizde Şu An Ne Var?

### 2.1 Modül Özeti (8 dosya, 2,936 satır)

| Modül | Satır | Ne Yapıyor | Durum |
|-------|-------|------------|-------|
| `tiered_scanner.py` | 602 | 6 katmanlı tarama (Tier 0-5), regime-aware ağırlıklar | ✅ En kapsamlı |
| `backtest_runner.py` | 557 | Scanner backtest runner, portfolio simulator, feature cache | ✅ İyi |
| `opportunity_engine.py` | 499 | Fırsat skoru (10 bileşen), universe scan, risk-adjusted | ✅ İyi |
| `alpha_scanner.py` | 422 | Alpha tarama, breakout, volume acceleration, regime fit | ✅ İyi |
| `alpha_engine.py` | 361 | Alpha motoru, tick processing, feature computation, ML scores | ✅ İyi |
| `event_scanner.py` | 203 | Event-driven tarama, KAP/haber/macro event tepkisi | ✅ İyi |
| `live_scanner.py` | 155 | Gerçek zamanlı tick tarama, aday tespit | ✅ İyi |
| `event_queue.py` | 137 | Öncelikli event kuyruğu, async handler | ✅ İyi |

### 2.2 tiered_scanner.py (602 satır) — Detaylı

| Sınıf/Fonksiyon | Satır | Ne Yapıyor | Durum |
|-----------------|-------|------------|-------|
| `Tier` | 32-42 | 6 tier tanımı (CONTINUOUS_WATCH → DECISION) | ✅ |
| `AssetTierState` | 43-113 | Her hissenin tier durumu (fiat, hacim, skorlar, AI) | ✅ İyi |
| `MarketRegime` | 115-170 | Rejime göre ağırlık güncelleme | ✅ İyi |
| `TieredScanner` | 172-602 | Ana scanner sınıfı | ✅ |
| `process_tick()` | 197-230 | Tick processing (state güncelleme) | ✅ |
| `run_quant_scan()` | 227-267 | Tier 1: Quant skor hesaplama | ✅ |
| `select_opportunities()` | 269-293 | Tier 2: Top 50 fırsat seçimi | ✅ |
| `run_deep_analysis()` | 294-342 | Tier 3: ML, tarihsel analog, senaryo | ✅ |
| `select_for_gemma()` | 343-365 | Tier 4: AI assessment için seçim | ✅ |
| `make_decisions()` | 366-394 | Tier 5: BUY/SELL/HOLD kararı | ✅ |
| `escalate_by_event()` | 395-425 | Event-driven tier yükseltme | ✅ İyi |
| `update_regime()` | 426-440 | Rejim güncelleme | ✅ |
| `_score_momentum()` | 441-462 | Momentum skoru | ✅ |
| `_score_volume_anomaly()` | 463-478 | Hacim anomalisi skoru | ✅ |
| `_score_breakout()` | 479-497 | Breakout skoru | ✅ |
| `_score_volatility()` | 498-515 | Volatilite skoru | ✅ |
| `_score_relative_strength()` | 516-530 | Göreceli güç skoru | ✅ |

### 2.3 opportunity_engine.py (499 satır) — Detaylı

| Sınıf/Fonksiyon | Satır | Ne Yapıyor | Durum |
|-----------------|-------|------------|-------|
| `OpportunityScore` | 28-63 | Fırsat skoru modeli (10 bileşen) | ✅ İyi |
| `OpportunityDiscoveryEngine` | 65-499 | Ana fırsat keşif motoru | ✅ |
| `compute_opportunity_score()` | 96-175 | 10 bileşenli fırsat skoru | ✅ İyi |
| `_compute_technical_score()` | 177-209 | Teknik skor | ✅ |
| `_compute_momentum_score()` | 211-235 | Momentum skoru | ✅ |
| `_compute_volume_score()` | 237-258 | Hacim skoru | ✅ |
| `_compute_volatility_score()` | 260-280 | Volatilite skoru | ✅ |
| `_compute_regime_fit()` | 282-302 | Rejim uyumu skoru | ✅ |
| `_compute_risk_score()` | 304-326 | Risk skoru | ✅ |
| `_determine_signal()` | 328-349 | Sinyal belirleme | ✅ |
| `_generate_evidence()` | 351-369 | Evidence üretimi | ✅ |
| `_generate_risks()` | 371-386 | Risk üretimi | ✅ |
| `scan_universe()` | 388-431 | Tüm BIST tarama | ✅ İyi |

### 2.4 alpha_engine.py (361 satır)

| Fonksiyon | Satır | Ne Yapıyor | Durum |
|-----------|-------|------------|-------|
| `load_universe()` | 48-60 | BIST universe yükle | ✅ |
| `process_tick()` | 61-147 | Tick processing + aday tespit | ✅ İyi |
| `on_event()` | 148-219 | Event tepkisi | ✅ |
| `_compute_all_features()` | 220-244 | Feature hesaplama | ✅ |
| `_detect_regime()` | 245-275 | Rejim tespiti | ✅ |
| `_compute_ml_scores()` | 305-338 | ML skor hesaplama | ✅ |

### 2.5 alpha_scanner.py (422 satır)

| Sınıf/Fonksiyon | Satır | Ne Yapıyor | Durum |
|-----------------|-------|------------|-------|
| `SignalType` | 25-40 | Sinyal türleri (BREAKOUT, VOLUME_SPIKE, vb.) | ✅ |
| `ScannerResult` | 42-86 | Tarama sonucu modeli | ✅ İyi |
| `AlphaScanner` | 88-422 | Ana scanner | ✅ |
| `scan()` | 101-155 | Toplu tarama | ✅ |
| `_scan_single()` | 157-188 | Tek hisse tarama | ✅ |
| `_calc_breakout()` | 190-208 | Breakout hesaplama | ✅ |
| `_calc_volume_acceleration()` | 210-214 | Hacim ivme hesaplama | ✅ |
| `_calc_opportunity_score()` | 242-303 | Fırsat skoru (çoklu bileşen) | ✅ İyi |

### 2.6 event_scanner.py (203 satır)

| Fonksiyon | Satır | Ne Yapıyor | Durum |
|-----------|-------|------------|-------|
| `on_event()` | 27-92 | Event tepkisi (KAP, haber, macro) | ✅ İyi |
| `get_pending_rescans()` | 94-97 | Bekleyen taramalar | ✅ |
| `should_rescan()` | 107-117 | Yeniden tarama gerekli mi? | ✅ |
| `_get_macro_affected_stocks()` | 119-170 | Macro etkilenen hisseler | ✅ İyi |
| `get_event_score()` | 172-194 | Event skoru | ✅ |

### 2.7 live_scanner.py (155 satır)

| Fonksiyon | Satır | Ne Yapıyor | Durum |
|-----------|-------|------------|-------|
| `process_tick()` | 30-87 | Gerçek zamanlı tick processing | ✅ |
| `_check_candidate()` | 89-131 | Aday kontrolü | ✅ |
| `get_candidates()` | 133-136 | Aday listesi | ✅ |

### 2.8 backtest_runner.py (557 satır)

| Sınıf/Fonksiyon | Satır | Ne Yapıyor | Durum |
|-----------------|-------|------------|-------|
| `BacktestTrade` | 36-54 | Trade modeli | ✅ |
| `BacktestSignal` | 56-66 | Sinyal modeli | ✅ |
| `DailySnapshot` | 68-87 | Günlük snapshot | ✅ |
| `BacktestResult` | 89-121 | Backtest sonucu | ✅ İyi |
| `FeatureCache` | 123-165 | Feature cache | ✅ İyi |
| `QualityCache` | 148-165 | Kalite cache | ✅ |
| `PortfolioSimulator` | 168-351 | Portföy simülasyonu | ✅ İyi |
| `ScannerBacktestRunner` | 353-557 | Scanner backtest runner | ✅ İyi |

---

## 3. Eksikler (Kritik)

### 3.1 Deduplication Yok

**Sorun:** Aynı hisse tekrar tekrar taranabiliyor
**Etki:** Gereksiz CPU kullanımı, duplicate sinyal
**Çözüm:** Son tarama zamanı kontrolü, dedup cache

### 3.2 Scan Scheduling Yok

**Sorun:** Tarama zamanlaması manuel
**Etki:** Piyasa açıkken sürekli tarama yapılmıyor
**Çözüm:** Otomatik scan scheduling (piyasa saatlerinde)

### 3.3 Scan Performance Tracking Yok

**Sorun:** Tarama performansı takip edilmiyor
**Etki:** Hangi tarama stratejisi daha iyi bilinmiyor
**Çözüm:** Scan performance metrics

### 3.4 Alert Integration Zayıf

**Sorun:** Tarama sonuçları alert sistemine bağlı değil
**Etki:** Kritik fırsatlar bildirilmiyor
**Çözüm:** Scanner → alert entegrasyonu

### 3.5 Backtest-Scanner Parity Yok

**Sorun:** Backtest'te kullanılan tarama stratejisi ile canlı tarama farklı olabilir
**Etki:** Backtest sonuçları canlıya uymayabilir
**Çözüm:** Same code path for backtest and live

### 3.6 Multi-Asset Scanner Yok

**Sorun:** Sadece hisse — VIOP, opsiyon taranmıyor
**Etki:** Türev ürünler tarama dışı
**Çözüm:** Multi-asset scanner

### 3.7 Scan Result Persistence Yok

**Sorun:** Tarama sonuçları kalıcı olarak saklanmıyor
**Etki:** Geçmiş tarama analizi yapılamıyor
**Çözüm:** Scan result database

### 3.8 Adaptive Scanning Yok

**Sorun:** Tarama sıklığı sabit — volatilite artınca sıklaşmalı
**Etki:** Önemli hareketler kaçırılabilir
**Çözüm:** Volatilite/event bazlı adaptif tarama

---

## 4. Nihai Scanner Mimarisi

### 4.1 Scanner Pipeline (Nihai)

```
┌─────────────────────────────────────────────────────────────┐
│                    SCANNER PIPELINE                          │
│                                                             │
│  ┌─────────────────────────────────────────────────────┐   │
│  │              TIER 0: CONTINUOUS WATCH                │   │
│  │  - 800+ hisse, ucuz state                           │   │
│  │  - Fiyat, hacim, bid/ask, spread                    │   │
│  │  - Real-time tick processing                        │   │
│  │  - Deduplication ← YENİ                             │   │
│  │  - Adaptive scheduling ← YENİ                       │   │
│  └─────────────────────────┬───────────────────────────┘   │
│                            ↓                                │
│  ┌─────────────────────────────────────────────────────┐   │
│  │              TIER 1: QUANT SCAN                     │   │
│  │  - 800 → ~200                                       │   │
│  │  - Momentum score                                   │   │
│  │  - Volume anomaly score                             │   │
│  │  - Breakout score                                   │   │
│  │  - Volatility score                                 │   │
│  │  - Relative strength score                          │   │
│  │  - Sector divergence score                          │   │
│  │  - Regime-aware ağırlıklar                          │   │
│  └─────────────────────────┬───────────────────────────┘   │
│                            ↓                                │
│  ┌─────────────────────────────────────────────────────┐   │
│  │              TIER 2: OPPORTUNITY SCORE               │   │
│  │  - 200 → ~50                                        │   │
│  │  - 10 bileşenli fırsat skoru                        │   │
│  │  - Technical, fundamental, momentum, volume,        │   │
│  │    volatility, sentiment, valuation, macro,         │   │
│  │    regime, risk                                     │   │
│  │  - Risk-adjusted skor                               │   │
│  │  - Decomposition (hangi bileşen ne kadar katkı)     │   │
│  └─────────────────────────┬───────────────────────────┘   │
│                            ↓                                │
│  ┌─────────────────────────────────────────────────────┐   │
│  │              TIER 3: DEEP ANALYSIS                  │   │
│  │  - 50 → ~10                                         │   │
│  │  - ML model tahminleri (5D, 20D)                    │   │
│  │  - Tarihsel analog arama                            │   │
│  │  - Senaryo analizi                                  │   │
│  │  - Risk/reward oranı                                │   │
│  └─────────────────────────┬───────────────────────────┘   │
│                            ↓                                │
│  ┌─────────────────────────────────────────────────────┐   │
│  │              TIER 4: AI ASSESSMENT                  │   │
│  │  - 10 → ~3-5                                        │   │
│  │  - LLM analiz (Ollama)                              │   │
│  │  - Sentiment analizi                                │   │
│  │  - Neden-sonuç analizi                              │   │
│  │  - Confidence scoring                               │   │
│  └─────────────────────────┬───────────────────────────┘   │
│                            ↓                                │
│  ┌─────────────────────────────────────────────────────┐   │
│  │              TIER 5: DECISION                       │   │
│  │  - 3-5 → 0-3                                        │   │
│  │  - BUY/SELL/HOLD kararı                             │   │
│  │  - Pozisyon boyutu                                  │   │
│  │  - Stop loss / target fiyat                         │   │
│  │  - Entry stratejisi                                 │   │
│  └─────────────────────────┬───────────────────────────┘   │
│                            ↓                                │
│  ┌─────────────────────────────────────────────────────┐   │
│  │              EVENT-DRIVEN ESCALATION                │   │
│  │  - KAP açıklaması → tier yükselt                    │   │
│  │  - Haber → tier yükselt                             │   │
│  │  - Macro event → toplu tarama                       │   │
│  │  - Anomaly → acil tarama                            │   │
│  └─────────────────────────┬───────────────────────────┘   │
│                            ↓                                │
│  ┌─────────────────────────────────────────────────────┐   │
│  │              SCAN SCHEDULING ← YENİ                 │   │
│  │  - Piyasa saatlerinde sürekli tarama                │   │
│  │  - Volatilite artınca sık tarama                    │   │
│  │  - Event gelince acil tarama                        │   │
│  │  - Piyasa kapalıyken duraklat                       │   │
│  └─────────────────────────┬───────────────────────────┘   │
│                            ↓                                │
│  ┌─────────────────────────────────────────────────────┐   │
│  │              SCAN RESULT PERSISTENCE ← YENİ         │   │
│  │  - Tarama sonuçları DB'ye kaydet                    │   │
│  │  - Geçmiş tarama analizi                            │   │
│  │  - Performance tracking                             │   │
│  └─────────────────────────┬───────────────────────────┘   │
│                            ↓                                │
│  ┌─────────────────────────────────────────────────────┐   │
│  │              ALERT INTEGRATION ← YENİ               │   │
│  │  - Kritik fırsat → bildirim                         │   │
│  │  - Tier değişimi → bildirim                         │   │
│  │  - Anomaly → acil bildirim                          │   │
│  └─────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────┘
```

### 4.2 Deduplication (Nihai)

```python
class ScanDeduplicator:
    """Tarama deduplication — aynı hisseyi tekrar tarama."""
    
    def __init__(self, cooldown_seconds: int = 300):
        self._last_scan = {}  # ticker → timestamp
        self._cooldown = cooldown_seconds
    
    def should_scan(self, ticker: str) -> bool:
        """Tarama gerekli mi?"""
        now = time.time()
        last = self._last_scan.get(ticker, 0)
        if now - last < self._cooldown:
            return False
        self._last_scan[ticker] = now
        return True
    
    def force_scan(self, ticker: str):
        """Zorla tarama (event-driven)."""
        self._last_scan[ticker] = 0
    
    def get_stats(self) -> Dict:
        return {
            "tracked_tickers": len(self._last_scan),
            "cooldown_seconds": self._cooldown,
        }
```

### 4.3 Adaptive Scanning (Nihai)

```python
class AdaptiveScanScheduler:
    """Volatilite/event bazlı adaptif tarama sıklığı."""
    
    BASE_INTERVAL_SECONDS = 60  # 1 dakika
    
    def get_scan_interval(self, volatility: float, regime: str,
                          has_recent_event: bool = False) -> int:
        """Tarama aralığını belirle."""
        interval = self.BASE_INTERVAL_SECONDS
        
        # Volatilite artınca sık tarama
        if volatility > 0.30:
            interval = 15  # 15 saniye
        elif volatility > 0.20:
            interval = 30
        elif volatility > 0.10:
            interval = 60
        else:
            interval = 120  # Düşük volatilite → 2 dakika
        
        # Rejim bazlı
        if regime in ["PANIC", "RISK-OFF"]:
            interval = min(interval, 15)
        elif regime in ["HIGH-VOLATILITY"]:
            interval = min(interval, 30)
        
        # Event varsa sık tarama
        if has_recent_event:
            interval = min(interval, 10)
        
        return interval
```

### 4.4 Scan Performance Tracking (Nihai)

```python
class ScanPerformanceTracker:
    """Tarama performans takibi."""
    
    def __init__(self):
        self._scan_history = []
    
    def record_scan(self, scan_type: str, tickers_scanned: int,
                    opportunities_found: int, duration_ms: float):
        """Tarama kaydet."""
        self._scan_history.append({
            "timestamp": datetime.now().isoformat(),
            "scan_type": scan_type,
            "tickers_scanned": tickers_scanned,
            "opportunities_found": opportunities_found,
            "duration_ms": duration_ms,
            "hit_rate": opportunities_found / max(tickers_scanned, 1),
        })
    
    def get_stats(self) -> Dict:
        """Tarama istatistikleri."""
        if not self._scan_history:
            return {"total_scans": 0}
        
        recent = self._scan_history[-100:]
        return {
            "total_scans": len(self._scan_history),
            "avg_duration_ms": round(np.mean([s["duration_ms"] for s in recent]), 2),
            "avg_hit_rate": round(np.mean([s["hit_rate"] for s in recent]), 4),
            "avg_opportunities": round(np.mean([s["opportunities_found"] for s in recent]), 1),
        }
```

---

## 5. Rakip Karşılaştırması

### 5.1 Mometic Top 10 Scanners (2026)

| Özellik | Mometic | Bizim Sistem | Fark |
|---------|---------|-------------|------|
| Real-time scanning | ✅ | ✅ | ✅ Aynı |
| Multi-factor screening | ✅ | ✅ | ✅ Aynı |
| Custom filters | ✅ | ⚠️ Basit | ⚠️ |
| Alert integration | ✅ | ⚠️ Zayıf | ⚠️ |
| Backtest integration | ❌ | ✅ | ✅ Biz daha iyi |

### 5.2 TradeAlgo (2026)

| Özellik | TradeAlgo | Bizim Sistem | Fark |
|---------|-----------|-------------|------|
| Algorithm-based screening | ✅ | ✅ | ✅ Aynı |
| Multi-factor ranking | ✅ | ✅ | ✅ Aynı |
| Real-time processing | ✅ | ✅ | ✅ Aynı |
| Tiered approach | ❌ | ✅ | ✅ Biz daha iyi |
| Event-driven | ❌ | ✅ | ✅ Biz daha iyi |

### 5.3 TradingAgents (TauricResearch 2025)

| Özellik | TradingAgents | Bizim Sistem | Fark |
|---------|---------------|-------------|------|
| Research Manager | ✅ Agent debate | ⚠️ Basit | ⚠️ |
| Multi-agent scanning | ✅ | ⚠️ Single scanner | ⚠️ |
| Event-driven | ✅ | ✅ | ✅ Aynı |
| Backtest integration | ✅ | ✅ | ✅ Aynı |

---

## 6. Uygulama Planı

### Faz 1: Deduplication (Hemen)
1. Scan deduplicator ekle
2. Cooldown kontrolü
3. Force scan (event-driven)

### Faz 2: Adaptive Scanning (1 hafta)
1. Volatilite bazlı sıklık
2. Rejim bazlı sıklık
3. Event bazlı acil tarama

### Faz 3: Scan Result Persistence (1 hafta)
1. Tarama sonuçları DB'ye kaydet
2. Geçmiş tarama analizi
3. Performance tracking

### Faz 4: Alert Integration (1 hafta)
1. Kritik fırsat → bildirim
2. Tier değişimi → bildirim
3. Anomaly → acil bildirim

### Faz 5: Backtest-Scanner Parity (1 hafta)
1. Same code path
2. Feature cache sharing
3. Result comparison

---

## 7. Mevcut Sistem vs Nihai Vizyon

| Özellik | Mevcut | Hedef |
|---------|--------|-------|
| Modül sayısı | 8 | 11 |
| Toplam satır | 2,936 | ~4,000 |
| Tiered scanning | ✅ İyi | ✅ |
| Opportunity scoring | ✅ İyi (10 bileşen) | ✅ |
| Alpha scanning | ✅ İyi | ✅ |
| Event-driven escalation | ✅ İyi | ✅ |
| Backtest integration | ✅ İyi | ✅ |
| Live scanning | ✅ İyi | ✅ |
| Deduplication | ❌ | ✅ |
| Adaptive scanning | ❌ | ✅ |
| Scan result persistence | ❌ | ✅ |
| Alert integration | ⚠️ Zayıf | ✅ |
| Backtest-scanner parity | ❌ | ✅ |
| Multi-asset scanner | ❌ | ⚠️ Future |
| Custom filters | ⚠️ Basit | ✅ |
