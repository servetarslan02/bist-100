# 🚀 Ingestion Nihai Mimari — Uygulama Planı

**Tarih:** 2026-08-19
**Hazırlayan:** AI Analiz (Kod Analizi + İnternet Araştırması)
**Kaynaklar:** Apache Kafka Architecture (Instaclustr 2025), Event-Driven Architecture Patterns (Solace), arXiv Look-Ahead Bias Mitigation (2026), S&P DJI Corporate Actions Methodology, PyResilience (2026), Reddit AlgoTrading Best Practices (2025)

---

## 📋 İçindekiler

1. [Araştırma Bulguları](#1-araştırma-bulguları)
2. [Mevcut Sistem Analizi](#2-mevcut-sistem-analizi)
3. [Entegrasyon Noktaları](#3-entegrasyon-noktaları)
4. [Genel Mimari Tasarım](#4-genel-mimari-tasarım)
5. [Faz Planı](#5-faz-planı)
6. [Test Stratejisi](#6-test-stratejisi)
7. [Risk ve Azaltma](#7-risk-ve-azaltma)

---

## 1. Araştırma Bulguları

### 1.1 Resilience Patterns (PyResilience 2026, BirJob 2025)

**Kaynak:** https://github.com/AhsanSheraz/pyresilience, levelup.gitconnected.com/PyResilience

**7 Temel Pattern (tek decorator'da):**
- **Retry** — exponential backoff + jitter (tenacity tabanlı)
- **Circuit Breaker** — CLOSED → OPEN → HALF_OPEN state machine
- **Timeout** — operation-level deadline
- **Fallback** — degraded response
- **Bulkhead** — concurrent request limiting (Semaphore)
- **Rate Limiter** — token bucket / sliding window
- **Cache** — stale-while-revalidate

**Kritik Dersler:**
- ✅ Jitter olmadan retry → thundering herd (tüm istekler aynı anda tekrar dener)
- ✅ Circuit breaker OPEN iken fallback çağırmalı, exception fırlatmamalı
- ✅ Rate limiter sliding window > token bucket (daha adil)
- ✅ Bulkhead: her provider için ayrı semaphore (bir provider diğerini bloklamamalı)

### 1.2 Look-Ahead Bias Prevention (arXiv 2026, Reddit 2025)

**Kaynak:** arXiv 2512.12924, Reddit r/algotrading

**Point-in-Time Validation:**
- Backtest'te sadece o anda bilinen veriyi kullan
- KAP açıklaması → publish_date'e kadar beklemek gerekir
- Bilanço verisi → report_date'ten önce bilinemez
- Corporate actions → ex_date'ten önce fiyatlanmaz

**Uygulama:**
```python
class PointInTimeValidator:
    def is_data_available(self, data_timestamp: datetime, query_timestamp: datetime) -> bool:
        """Veri query_timestamp'te biliniyor muydu?"""
        return data_timestamp <= query_timestamp

    def filter_available(self, data: List[Dict], query_date: datetime, timestamp_field: str = "publish_date") -> List[Dict]:
        """Sadece o tarihte bilinen veriyi döndür."""
        return [d for d in data if self.is_data_available(
            datetime.fromisoformat(d[timestamp_field]), query_date
        )]
```

### 1.3 Data Pipeline Best Practices (Instaclustr 2025, Solace)

**Event-Driven Ingestion:**
- Veri çekme → event publish → downstream tüketimi
- Idempotency: aynı veri iki kez işlenmemeli (dedup key)
- Incremental updates: tam çekme yerine sadece delta
- Dead letter queue: başarısız mesajlar tekrar denenmeli

**Multi-Source Reconciliation:**
- Kaynaklar arası fiyat farkı > %0.5 → DATA_QUALITY_WARNING
- Ağırlıklı canonical price (güvenilir kaynak yüksek ağırlık)
- Conflict varsa: en güvenilir kaynağı tercih et, ama uyarı üret

---

## 2. Mevcut Sistem Analizi

### 2.1 Dosya Yapısı (21 dosya, ~5,278 satır)

```
services/ingestion/
├── __init__.py                    # 1 satır
├── bist_universe.py               # 309 satır — BIST evreni (✅ iyi)
├── corporate_actions.py           # 350 satır — Şirket olayları (✅ iyi)
├── data_pipeline.py               # 204 satır — Quality gate (✅ iyi)
├── main.py                        # 428 satır — Ingestion service (⚠️ monolitik)
├── realtime.py                    # 142 satır — Gerçek zamanlı (✅ iyi)
├── universe_enhancements.py       # 204 satır — Evren geliştirmeleri (✅ iyi)
└── providers/
    ├── __init__.py
    ├── bist_provider.py           # 87 satır — BIST resmi (⚠️ basit)
    ├── bist_stream.py             # 261 satır — Streaming (✅ iyi)
    ├── data_validator.py          # 183 satır — Cross-validation (✅ iyi)
    ├── fundamental_provider.py    # 293 satır — Bilanço (✅ iyi)
    ├── kap_provider.py            # 111 satır — KAP (⚠️ basit)
    ├── macro_provider.py          # 139 satır — Makro (⚠️ basit)
    ├── matriks_provider.py        # 62 satır — Matriks (⚠️ çok basit)
    ├── news_credibility.py        # 124 satır — Kaynak güvenilirliği (✅ iyi)
    ├── news_provider.py           # 258 satır — RSS haber (✅ iyi)
    ├── provider_manager.py        # 131 satır — Provider yönetimi (⚠️ eksik)
    ├── realtime_provider.py       # 319 satır — Gerçek zamanlı (✅ iyi)
    ├── social_provider.py         # 130 satır — Sosyal medya (⚠️ basit)
    ├── tcmb_provider.py           # 104 satır — TCMB EVDS (⚠️ basit)
    ├── universe_provider.py       # 806 satır — KAP, yfinance, BIST (✅ iyi)
    └── yfinance_provider.py       # 264 satır — OHLCV (✅ iyi)
```

### 2.2 Mevcut Provider Manager — Güçlü ve Zayıf Yönler

**✅ Sağlam Temel:**
- `ProviderHealth` dataclass — success_rate, avg_latency, consecutive_failures
- `ProviderManager.register_provider()` — data_type + name + priority
- `ProviderManager.fetch()` — failover ile sırayla deneme
- `get_health()` — tüm provider'ların sağlık durumu

**❌ Kritik Eksiklikler:**
1. **Circuit Breaker yok** — sürekli hata veren provider'ı durdurmuyor (sadece consecutive_failures > 5'te atlıyor)
2. **Rate Limiter yok** — API limit aşılabilir
3. **Retry policy yok** — geçici hatalarda yeniden deneme yok
4. **Async değil** — `func(**kwargs)` blocking çağrılıyor
5. **Timeout yok** — provider asılırsa sonsuz bekler
6. **Cross-source reconciliation yok** — sadece tek provider'dan veri alıyor
7. **Idempotency yok** — aynı veri iki kez işlenebilir
8. **Metrics yok** — Prometheus/monitoring entegrasyonu eksik

### 2.3 Mevcut Data Validator — Güçlü ve Zayıf Yönler

**✅ Sağlam Temel:**
- `SOURCE_WEIGHTS` — kaynak güvenilirlik ağırlıkları
- `validate_price()` — ağırlıklı canonical price hesaplama
- `validate_batch()` — toplu doğrulama
- `get_quality_report()` — kalite raporu

**❌ Kritik Eksiklikler:**
1. **Point-in-time validation yok** — gelecekteki veriyi kullanabilir (look-ahead bias!)
2. **Volume validation yok** — sadece fiyat doğruluyor
3. **Historical data validation yok** — anomali tespiti yok
4. **Corporate actions integration yok** — fiyat düzeltmesi sonrası doğrulama yok
5. **Async değil** — blocking

### 2.4 Mevcut Ingestion Service (main.py) — Güçlü ve Zayıf Yönler

**✅ Sağlam Temel:**
- 5 loop: market_data, kap, macro, news, social
- Event publishing (CanonicalEvent + Redis Pub/Sub)
- Universe auto-refresh
- Instrument map seeding

**❌ Kritik Eksiklikler:**
1. **Hata yönetimi zayıf** — `except Exception: pass` (silent failure)
2. **Retry yok** — bir hata döngüyü bozabilir
3. **Rate limiting yok** — tüm hisseleri aynı anda çekiyor
4. **Circuit breaker yok** — provider çökünce döngü devam eder ama boşuna
5. **Incremental updates yok** — her seferinde tam veri çekiyor
6. **Corporate actions otomatik değil** — KAP'tan gelen olayları işlemiyor
7. **Cross-source reconciliation yok** — sadece yfinance'dan fiyat çekiyor
8. **Deduplication yok** — aynı event iki kez publish edilebilir
9. **Metrics/monitoring yok** — performans takibi yok

### 2.5 Mevcut Entegrasyon Noktaları

| Nokta | Dosya | Ne Yapıyor | Ingestion Entegrasyonu |
|-------|-------|------------|------------------------|
| `InternalEventBus` | event_bus.py | Redis Pub/Sub | Provider sonuçları event olarak publish edilmeli |
| `CanonicalEvent` | event_schema.py | Standart event formatı | Tüm provider'lar bu formatı kullanmalı |
| `DataQualityChecker` | data_quality.py | Veri kalite kontrolü | Provider çıkışında kalite kapısı |
| `TradabilityMask` | tradability_mask.py | İşlem yapılabilirlik | Corporate actions sonrası güncellenmeli |
| `FeatureCalculator` | calculator.py | Feature hesaplama | Ingestion sonrası feature pipeline |

---

## 3. Entegrasyon Noktaları

### 3.1 Pipeline Entegrasyonu

```
MEVCUT:
  yfinance → data_pipeline → feature_engine → scanner

HEDEF:
  [PROVIDER MANAGER] → [CIRCUIT BREAKER] → [RATE LIMITER] → [RETRY]
  → [VALIDATOR] → [RECONCILIATION] → [CORPORATE ACTIONS] → [POINT-IN-TIME]
  → [DEDUP] → [EVENT PUBLISH] → data_pipeline → feature_engine → scanner
```

### 3.2 Event Bus Entegrasyonu

```python
# Provider sonuçları event olarak publish edilmeli
event_bus.publish("ingestion.market_data.completed", CanonicalEvent(
    event_type="ingestion.market_data.completed",
    payload={
        "ticker": ticker,
        "price": validated_price,
        "source": provider_name,
        "quality_score": quality_score,
        "reconciliation": reconciliation_result,
    }
))

# Downstream servisler bu event'i dinleyebilir
@event_bus.subscribe("ingestion.market_data.completed")
async def on_market_data(event):
    # Feature engine'e besle
    pass
```

### 3.3 Config Entegrasyonu

```python
# services/core/config.py'ya eklenecek
class IngestionSettings(BaseModel):
    # Provider Manager
    provider_max_concurrent: int = 10
    provider_timeout_seconds: int = 30

    # Circuit Breaker
    circuit_breaker_failure_threshold: int = 5
    circuit_breaker_recovery_timeout_s: int = 60
    circuit_breaker_half_open_max_calls: int = 3

    # Rate Limiting
    rate_limit_yfinance_rpm: int = 60      # yfinance: 60 istek/dakika
    rate_limit_kap_rpm: int = 30            # KAP: 30 istek/dakika
    rate_limit_tcmb_rpm: int = 20           # TCMB: 20 istek/dakika
    rate_limit_social_rpm: int = 15         # Social: 15 istek/dakika

    # Retry
    retry_max_attempts: int = 3
    retry_base_delay_s: float = 1.0
    retry_max_delay_s: float = 30.0
    retry_jitter: bool = True

    # Data Quality
    quality_min_score: float = 70.0
    quality_max_deviation_pct: float = 0.5
    quality_require_cross_validation: bool = False

    # Point-in-Time
    pit_enabled: bool = True
    pit_default_delay_minutes: int = 15

    # Deduplication
    dedup_window_hours: int = 24

    # Incremental
    incremental_enabled: bool = True
    incremental_lookback_hours: int = 1
```

---

## 4. Genel Mimari Tasarım

### 4.1 Nihai Pipeline

```
┌─────────────────────────────────────────────────────────────────────┐
│                ALPHA BIST — INGESTION PIPELINE v2.0                  │
│                                                                     │
│  ┌──────────────────────────────────────────────────────────────┐   │
│  │  PHASE 1: PROVIDER MANAGER (Failover + Priority)             │   │
│  │                                                              │   │
│  │  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐       │   │
│  │  │yfinance  │ │ BIST     │ │ Matriks  │ │ KAP      │       │   │
│  │  │(primary) │ │(secondary│ │(tertiary)│ │(official)│       │   │
│  │  └────┬─────┘ └────┬─────┘ └────┬─────┘ └────┬─────┘       │   │
│  │       └─────────────┴────────────┴─────────────┘             │   │
│  │                          ↓                                    │   │
│  │  ProviderManager.fetch() — priority sırasıyla dene            │   │
│  └──────────────────────────────┬───────────────────────────────┘   │
│                                 ↓                                    │
│  ┌──────────────────────────────────────────────────────────────┐   │
│  │  PHASE 2: RESILIENCE LAYER                                   │   │
│  │                                                              │   │
│  │  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐       │   │
│  │  │ Circuit  │ │  Rate    │ │  Retry   │ │ Timeout  │       │   │
│  │  │ Breaker  │ │ Limiter  │ │ (backoff)│ │          │       │   │
│  │  └──────────┘ └──────────┘ └──────────┘ └──────────┘       │   │
│  │                                                              │   │
│  │  Her provider için ayrı circuit breaker + rate limiter       │   │
│  └──────────────────────────────┬───────────────────────────────┘   │
│                                 ↓                                    │
│  ┌──────────────────────────────────────────────────────────────┐   │
│  │  PHASE 3: VALIDATION & RECONCILIATION                        │   │
│  │                                                              │   │
│  │  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐       │   │
│  │  │  Price   │ │  Volume  │ │  Cross-  │ │ Anomaly  │       │   │
│  │  │ Validate │ │ Validate │ │ Source   │ │ Detect   │       │   │
│  │  └──────────┘ └──────────┘ └──────────┘ └──────────┘       │   │
│  └──────────────────────────────┬───────────────────────────────┘   │
│                                 ↓                                    │
│  ┌──────────────────────────────────────────────────────────────┐   │
│  │  PHASE 4: CORPORATE ACTIONS                                  │   │
│  │                                                              │   │
│  │  KAP olayları → otomatik sınıflandırma → fiyat düzeltmesi   │   │
│  │  Temettü, bölünme, bedelsiz, bedelli → pozisyon düzeltmesi  │   │
│  └──────────────────────────────┬───────────────────────────────┘   │
│                                 ↓                                    │
│  ┌──────────────────────────────────────────────────────────────┐   │
│  │  PHASE 5: POINT-IN-TIME & DEDUP                              │   │
│  │                                                              │   │
│  │  ┌──────────┐ ┌──────────┐ ┌──────────┐                    │   │
│  │  │ PIT      │ │  Dedup   │ │ Incremental│                  │   │
│  │  │ Validate │ │  Window  │ │  Updates   │                   │   │
│  │  └──────────┘ └──────────┘ └──────────┘                    │   │
│  └──────────────────────────────┬───────────────────────────────┘   │
│                                 ↓                                    │
│  ┌──────────────────────────────────────────────────────────────┐   │
│  │  PHASE 6: EVENT PUBLISH & METRICS                            │   │
│  │                                                              │   │
│  │  CanonicalEvent → Redis Pub/Sub → downstream servisler       │   │
│  │  Prometheus metrics → monitoring                             │   │
│  │  Audit trail → database                                      │   │
│  └──────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────┘
```

### 4.2 Dosya Yapısı (Hedef)

```
services/ingestion/
├── __init__.py
├── main.py                      # REFACTOR — modüler loop'lar
├── bist_universe.py             # MEVCUT — değişiklik yok
├── corporate_actions.py         # MEVCUT — KAP entegrasyonu ekle
├── data_pipeline.py             # MEVCUT — async entegrasyon
├── realtime.py                  # MEVCUT — değişiklik yok
├── universe_enhancements.py     # MEVCUT — değişiklik yok
├── provider_manager.py          # YENİ — gelişmiş provider manager
├── circuit_breaker.py           # YENİ — circuit breaker
├── rate_limiter.py              # YENİ — rate limiter
├── retry_policy.py              # YENİ — retry with backoff
├── reconciliation.py            # YENİ — cross-source reconciliation
├── point_in_time.py             # YENİ — point-in-time validation
├── deduplication.py             # YENİ — event deduplication
├── incremental.py               # YENİ — incremental updates
├── ingestion_metrics.py         # YENİ — Prometheus metrics
├── providers/
│   ├── __init__.py
│   ├── bist_provider.py         # REFACTOR — async
│   ├── bist_stream.py           # MEVCUT
│   ├── data_validator.py        # REFACTOR — async + PIT + volume
│   ├── fundamental_provider.py  # REFACTOR — async
│   ├── kap_provider.py          # REFACTOR — detaylı KAP çekme
│   ├── macro_provider.py        # REFACTOR — async + detaylı
│   ├── matriks_provider.py      # REFACTOR — async
│   ├── news_credibility.py      # MEVCUT
│   ├── news_provider.py         # MEVCUT
│   ├── realtime_provider.py     # MEVCUT
│   ├── social_provider.py       # REFACTOR — async + Ekşi + Reddit
│   ├── tcmb_provider.py         # REFACTOR — detaylı EVDS
│   ├── universe_provider.py     # MEVCUT
│   └── yfinance_provider.py     # MEVCUT — async wrapper ekle
└── tests/                       # YENİ — test suite
    ├── __init__.py
    ├── test_circuit_breaker.py
    ├── test_rate_limiter.py
    ├── test_retry_policy.py
    ├── test_reconciliation.py
    ├── test_point_in_time.py
    ├── test_deduplication.py
    ├── test_provider_manager.py
    └── test_integration.py
```

---

## 5. Faz Planı

### FAZ 0: Temel Altyapı (1-2 gün)

**Amaç:** Resilience katmanlarını oluştur, mevcut kodu refactor et.

#### 0.1 — Circuit Breaker
```
Dosya: services/ingestion/circuit_breaker.py
```
- [ ] `CircuitState` enum: CLOSED, OPEN, HALF_OPEN
- [ ] `CircuitBreaker` class: failure_threshold, recovery_timeout, half_open_max_calls
- [ ] `call()` decorator — async fonksiyonları sarar
- [ ] `record_success()`, `record_failure()` — state geçişleri
- [ ] `get_state()` — monitoring için
- [ ] BIST'e özgü: mesai saatleri dışında OPEN'a geçme

**State Machine:**
```
CLOSED → (failure_threshold aşıldı) → OPEN
OPEN → (recovery_timeout doldu) → HALF_OPEN
HALF_OPEN → (success) → CLOSED
HALF_OPEN → (failure) → OPEN
```

#### 0.2 — Rate Limiter
```
Dosya: services/ingestion/rate_limiter.py
```
- [ ] `SlidingWindowRateLimiter` — token bucket yerine sliding window (daha adil)
- [ ] `acquire(provider)` — async, limit aşılırsa bekle
- [ ] `set_limit(provider, max_requests, window_seconds)` — per-provider limit
- [ ] `get_stats(provider)` — monitoring için
- [ ] BIST'e özgü: yfinance 60/dk, KAP 30/dk, TCMB 20/dk

#### 0.3 — Retry Policy
```
Dosya: services/ingestion/retry_policy.py
```
- [ ] `RetryPolicy` class: max_attempts, base_delay, max_delay, jitter
- [ ] `execute_with_retry(fn, *args)` — async retry wrapper
- [ ] Exponential backoff: 1s → 2s → 4s → 8s → 16s (max 30s)
- [ ] Jitter: ±%20 random ekle (thundering herd önleme)
- [ ] Retryable exceptions: TimeoutError, ConnectionError, 429, 500, 502, 503
- [ ] Non-retryable exceptions: 400, 401, 403, 404

#### 0.4 — Mevcut Provider Manager Refactor
```
Dosya: services/ingestion/provider_manager.py (değişiklik)
```
- [ ] `fetch()`'i async yap
- [ ] Circuit breaker entegrasyonu
- [ ] Rate limiter entegrasyonu
- [ ] Retry policy entegrasyonu
- [ ] Per-provider timeout (`asyncio.wait_for`)
- [ ] `fetch_with_reconciliation()` — çoklu kaynaktan çek, doğrula
- [ ] Prometheus metrics ekle

**Teslimat:** `pytest tests/test_ingestion_faz0.py` — tüm testler yeşil

---

### FAZ 1: Data Quality & Reconciliation (2-3 gün)

**Amaç:** Veri kalitesini artır, kaynaklar arası doğrulama yap.

#### 1.1 — Gelişmiş Data Validator
```
Dosya: services/ingestion/providers/data_validator.py (değişiklik)
```
- [ ] `validate_volume()` — hacim doğrulama (negatif, anormal spike)
- [ ] `validate_ohlc_consistency()` — High >= Low, Open/Close aralıkta
- [ ] `detect_anomaly()` — Z-score > 3 → anomali
- [ ] `validate_timestamp()` — gelecek tarih kontrolü
- [ ] Async yap

#### 1.2 — Cross-Source Reconciliation
```
Dosya: services/ingestion/reconciliation.py
```
```python
class SourceReconciler:
    """Kaynaklar arası fiyat uzlaştırma."""

    async def reconcile_price(
        self,
        ticker: str,
        sources: Dict[str, float],  # source → price
        weights: Dict[str, float],  # source → weight
        max_deviation_pct: float = 0.5,
    ) -> ReconciliationResult:
        """Çoklu kaynaktan fiyatı uzlaştır."""
        if len(sources) == 1:
            return ReconciliationResult(
                canonical_price=list(sources.values())[0],
                source=list(sources.keys())[0],
                conflict=False,
                quality_score=0.6,  # Tek kaynak = düşük güven
            )

        # Ağırlıklı ortalama
        total_weight = sum(weights.get(s, 0.5) for s in sources)
        canonical = sum(
            p * weights.get(s, 0.5) for s, p in sources.items()
        ) / total_weight

        # Sapma kontrolü
        deviations = {s: abs(p - canonical) / canonical * 100 for s, p in sources.items()}
        max_dev = max(deviations.values())
        conflict = max_dev > max_deviation_pct

        # Kalite skoru
        quality = 1.0
        if len(sources) < 2:
            quality *= 0.6
        if conflict:
            quality *= 0.5

        return ReconciliationResult(
            canonical_price=round(canonical, 2),
            source="reconciled",
            conflict=conflict,
            quality_score=round(quality, 3),
            deviations=deviations,
        )
```

#### 1.3 — Anomaly Detection
```
Dosya: services/ingestion/providers/data_validator.py (içinde)
```
- [ ] Z-score tabanlı anomali tespiti
- [ ] Fiyat: son 20 gün ortalamasından > 3 std sapma
- [ ] Hacim: son 20 gün ortalamasından > 5 std sapma
- [ ] Anomali varsa → DATA_QUALITY_WARNING event publish

**Teslimat:** `pytest tests/test_ingestion_faz1.py` — reconciliation + anomaly

---

### FAZ 2: Point-in-Time & Deduplication (2-3 gün)

**Amaç:** Look-ahead bias'i önle, tekrarlanan veriyi filtrele.

#### 2.1 — Point-in-Time Validator
```
Dosya: services/ingestion/point_in_time.py
```
```python
class PointInTimeValidator:
    """Look-ahead bias önleme."""

    # Veri tipleri için gecikme süreleri
    DATA_DELAYS = {
        "market_price": timedelta(minutes=15),    # yfinance: 15dk gecikmeli
        "market_realtime": timedelta(seconds=0),   # Matriks realtime
        "kap_disclosure": timedelta(seconds=0),     # KAP: anında
        "fundamental": timedelta(days=1),           # Bilanço: ertesi gün
        "macro_tcmb": timedelta(hours=1),           # TCMB: 1 saat gecikmeli
        "news": timedelta(minutes=5),               # Haberler: 5 dakika
        "social": timedelta(minutes=10),            # Sosyal: 10 dakika
    }

    def is_available_at(
        self,
        data_type: str,
        data_timestamp: datetime,
        query_timestamp: datetime,
    ) -> bool:
        """Veri query_timestamp'te biliniyor muydu?"""
        delay = self.DATA_DELAYS.get(data_type, timedelta(0))
        earliest_available = data_timestamp + delay
        return query_timestamp >= earliest_available

    def filter_available(
        self,
        data: List[Dict],
        data_type: str,
        query_timestamp: datetime,
        timestamp_field: str = "timestamp",
    ) -> List[Dict]:
        """Sadece o tarihte bilinen veriyi döndür."""
        return [
            d for d in data
            if self.is_available_at(
                data_type,
                datetime.fromisoformat(d[timestamp_field]),
                query_timestamp,
            )
        ]
```

#### 2.2 — Event Deduplication
```
Dosya: services/ingestion/deduplication.py
```
```python
class EventDeduplicator:
    """Event deduplication — aynı veri iki kez işlenmesin."""

    def __init__(self, window_hours: int = 24):
        self._seen: Dict[str, datetime] = {}  # hash → timestamp
        self._window = timedelta(hours=window_hours)

    def _compute_hash(self, event: CanonicalEvent) -> str:
        """Event hash'i oluştur."""
        import hashlib
        key_parts = [
            event.event_type,
            event.source,
            str(event.data.get("ticker", "")),
            str(event.data.get("price", "")),
            str(event.data.get("timestamp", "")),
        ]
        key = "|".join(key_parts)
        return hashlib.md5(key.encode()).hexdigest()

    def is_duplicate(self, event: CanonicalEvent) -> bool:
        """Bu event daha önce işlendi mi?"""
        self._cleanup()
        event_hash = self._compute_hash(event)
        return event_hash in self._seen

    def mark_seen(self, event: CanonicalEvent):
        """Event'i işlenmiş olarak işaretle."""
        event_hash = self._compute_hash(event)
        self._seen[event_hash] = datetime.now(timezone.utc)

    def _cleanup(self):
        """Eski hash'leri temizle."""
        cutoff = datetime.now(timezone.utc) - self._window
        self._seen = {h: t for h, t in self._seen.items() if t > cutoff}
```

#### 2.3 — Incremental Updates
```
Dosya: services/ingestion/incremental.py
```
```python
class IncrementalFetcher:
    """Sadece yeni veriyi çek — tam çekme yerine delta."""

    def __init__(self):
        self._last_fetch: Dict[str, datetime] = {}  # ticker → last_fetch_time

    def get_since(self, ticker: str, default_lookback_hours: int = 1) -> datetime:
        """Bu ticker için son çekme zamanını döndür."""
        if ticker in self._last_fetch:
            return self._last_fetch[ticker]
        return datetime.now(timezone.utc) - timedelta(hours=default_lookback_hours)

    def mark_fetched(self, ticker: str):
        """Çekme zamanını güncelle."""
        self._last_fetch[ticker] = datetime.now(timezone.utc)

    def should_fetch(self, ticker: str, min_interval_seconds: int = 60) -> bool:
        """Bu ticker'ı şimdi çekmeli mi?"""
        if ticker not in self._last_fetch:
            return True
        elapsed = (datetime.now(timezone.utc) - self._last_fetch[ticker]).total_seconds()
        return elapsed >= min_interval_seconds
```

**Teslimat:** `pytest tests/test_ingestion_faz2.py` — PIT + dedup + incremental

---

### FAZ 3: Provider Refactor & Yeni Provider'lar (3-4 gün)

**Amaç:** Tüm provider'ları async yap, yeni kaynaklar ekle.

#### 3.1 — Provider Refactor (Async)
```
Dosya: services/ingestion/providers/ (tümü)
```
- [ ] `fundamental_provider.py` → async (yfinance blocking → async wrapper)
- [ ] `macro_provider.py` → async + detaylı EVDS entegrasyonu
- [ ] `bist_provider.py` → async
- [ ] `matriks_provider.py` → async
- [ ] `social_provider.py` → async + Ekşi Sözlük + Reddit
- [ ] `kap_provider.py` → detaylı KAP çekme (finansal tablolar, KAP bildirimleri)

#### 3.2 — Ekşi Sözlük Provider
```
Dosya: services/ingestion/providers/social_provider.py (içinde)
```
- [ ] `fetch_eksi_topic(ticker)` — Ekşi Sözlük başlığı çek
- [ ] Sentiment analysis (Türkçe keyword-based)
- [ ] Rate limiting: 30 istek/dakika

#### 3.3 — Reddit Provider
```
Dosya: services/ingestion/providers/social_provider.py (içinde)
```
- [ ] `fetch_reddit_mentions(ticker)` — Reddit/Turkey subreddit
- [ ] Rate limiting: 60 istek/dakika

#### 3.4 — Google Trends Provider (Opsiyonel)
```
Dosya: services/ingestion/providers/google_trends_provider.py
```
- [ ] `fetch_search_interest(ticker)` — Google Trends arama ilgisi
- [ ] Trend verisi → sentiment göstergesi

**Teslimat:** `pytest tests/test_ingestion_faz3.py` — async refactor + yeni provider'lar

---

### FAZ 4: Orchestrator Entegrasyonu (2-3 gün)

**Amaç:** Ingestion pipeline'ını mevcut orchestrator'a tam entegre et.

#### 4.1 — Main.py Refactor
```
Dosya: services/ingestion/main.py (değişiklik)
```
- [ ] Loop'ları modüler yap (her loop ayrı class)
- [ ] `MarketDataLoop`, `KAPLoop`, `MacroLoop`, `NewsLoop`, `SocialLoop`
- [ ] Her loop: provider_manager + circuit_breaker + rate_limiter + retry
- [ ] Her loop: dedup + PIT validation
- [ ] Her loop: metrics publish

#### 4.2 — Corporate Actions Otomatik Entegrasyon
```
Dosya: services/ingestion/main.py (içinde)
```
- [ ] KAP loop'tan gelen olayları `corporate_actions.load_from_kap()`'a besle
- [ ] Corporate actions event publish
- [ ] Fiyat düzeltmesi otomatik tetikleme

#### 4.3 — Orchestrator Entegrasyonu
```
Dosya: services/core/orchestrator.py (değişiklik)
```
- [ ] `MasterOrchestrator.run_full_pipeline()`'a ingestion pipeline ekle
- [ ] Ingestion → Data Pipeline → Feature Engine akışı
- [ ] Pipeline metrics toplama

#### 4.4 — Event Schema Genişletme
```
Dosya: services/core/event_schema.py (değişiklik)
```
```python
# Yeni event type'ları
INGESTION_MARKET_DATA = "ingestion.market_data.completed"
INGESTION_KAP_EVENT = "ingestion.kap_event.completed"
INGESTION_MACRO_DATA = "ingestion.macro_data.completed"
INGESTION_NEWS = "ingestion.news.completed"
INGESTION_SOCIAL = "ingestion.social.completed"
INGESTION_QUALITY_WARNING = "ingestion.quality.warning"
INGESTION_ANOMALY_DETECTED = "ingestion.anomaly.detected"
INGESTION_CIRCUIT_BREAKER_OPEN = "ingestion.circuit_breaker.open"
INGESTION_RATE_LIMITED = "ingestion.rate_limited"
```

**Teslimat:** `pytest tests/test_ingestion_faz4.py` — orchestrator entegrasyonu

---

### FAZ 5: Metrics, Monitoring & Production (2-3 gün)

**Amaç:** Production-ready monitoring ve alerting.

#### 5.1 — Prometheus Metrics
```
Dosya: services/ingestion/ingestion_metrics.py
```
```python
from prometheus_client import Counter, Histogram, Gauge

# Provider metrics
provider_requests_total = Counter(
    'ingestion_provider_requests_total',
    'Total provider requests',
    ['provider', 'data_type', 'status']
)

provider_latency_seconds = Histogram(
    'ingestion_provider_latency_seconds',
    'Provider request latency',
    ['provider', 'data_type']
)

# Circuit breaker metrics
circuit_breaker_state = Gauge(
    'ingestion_circuit_breaker_state',
    'Circuit breaker state (0=closed, 1=open, 2=half_open)',
    ['provider']
)

# Data quality metrics
data_quality_score = Histogram(
    'ingestion_data_quality_score',
    'Data quality score distribution',
    ['ticker', 'source']
)

# Reconciliation metrics
reconciliation_conflicts_total = Counter(
    'ingestion_reconciliation_conflicts_total',
    'Total reconciliation conflicts',
    ['ticker']
)

# Dedup metrics
dedup_duplicates_total = Counter(
    'ingestion_dedup_duplicates_total',
    'Total duplicate events filtered',
    ['event_type']
)

# Rate limiter metrics
rate_limiter_wait_seconds = Histogram(
    'ingestion_rate_limiter_wait_seconds',
    'Rate limiter wait time',
    ['provider']
)
```

#### 5.2 — Health Check Endpoint
```
Dosya: services/ingestion/main.py (içinde)
```
- [ ] `/health` — tüm provider'ların sağlık durumu
- [ ] `/metrics` — Prometheus metrics
- [ ] `/providers` — provider durumları
- [ ] `/circuit-breakers` — circuit breaker durumları

#### 5.3 — Alert Rules
```
Dosya: config/alert_policy.json (değişiklik)
```
- [ ] Circuit breaker OPEN > 5 dakika → ALERT
- [ ] Quality score < 50 → ALERT
- [ ] Reconciliation conflict rate > %10 → ALERT
- [ ] Provider latency > 30 saniye → ALERT
- [ ] Dedup rate > %50 → ALERT (veri kalitesi sorunu)

#### 5.4 — Dokümantasyon
- [ ] Ingestion system README güncelle
- [ ] Her modül için docstring
- [ ] Runbook: troubleshooting
- [ ] Provider ekleme rehberi

**Teslimat:** `pytest tests/test_ingestion_faz5.py` — metrics + monitoring

---

### FAZ 6: Test, Backtest & Production Hazırlığı (3-4 gün)

**Amaç:** Sistemi production-ready yap.

#### 6.1 — Kapsamlı Test Suite
```
Dosya: tests/test_ingestion_system.py (genişletme)
```
- [ ] Unit test'ler: her modül için
- [ ] Integration test'ler: pipeline akışı
- [ ] Circuit breaker test'leri: state geçişleri
- [ ] Rate limiter test'leri: limit aşımı, bekleme
- [ ] Retry test'leri: exponential backoff, jitter
- [ ] Reconciliation test'leri: çakışma, uzlaştırma
- [ ] PIT test'leri: look-ahead bias tespiti
- [ ] Dedup test'leri: tekrar filtreleme
- [ ] Edge case test'leri: tüm provider başarısız, timeout, network error
- [ ] Performance test'leri: throughput, latency

#### 6.2 — Backtest Entegrasyonu
- [ ] PIT validation'ı backtest engine'e ekle
- [ ] Corporate actions düzeltmesini backtest'te doğrula
- [ ] Look-ahead bias test'leri

#### 6.3 — Load Testing
- [ ] 100+ hisse aynı anda çekme
- [ ] Rate limit senaryoları
- [ ] Circuit breaker stress test

#### 6.4 — Production Checklist
- [ ] Tüm config değerleri environment variable'dan okunuyor mu?
- [ ] API key'ler güvenli mi? (hardcoded değil)
- [ ] Logging yeterli mi?
- [ ] Metrics exposed mı?
- [ ] Alert'ler tanımlı mı?
- [ ] Dokümantasyon güncel mi?

**Teslimat:** `pytest tests/test_ingestion_faz6.py` — tüm testler yeşil, backtest raporu

---

## 6. Test Stratejisi

### Test Piramidi

```
         ┌─────────────┐
         │  E2E Tests   │  ← 5 test (tam pipeline)
         ├─────────────┤
         │ Integration  │  ← 20 test (modül arası)
         ├─────────────┤
         │   Unit Tests │  ← 60+ test (her fonksiyon)
         └─────────────┘
```

### Her Faz İçin Test Kriterleri

| Faz | Test Dosyası | Min Test Sayısı | Kritik Test |
|-----|-------------|-----------------|-------------|
| 0 | test_ingestion_faz0.py | 15 | Circuit breaker state machine |
| 1 | test_ingestion_faz1.py | 12 | Cross-source reconciliation |
| 2 | test_ingestion_faz2.py | 10 | PIT validation + dedup |
| 3 | test_ingestion_faz3.py | 10 | Async refactor + yeni provider'lar |
| 4 | test_ingestion_faz4.py | 12 | Orchestrator entegrasyonu |
| 5 | test_ingestion_faz5.py | 8 | Metrics + monitoring |
| 6 | test_ingestion_faz6.py | 15 | Backtest + load test |

---

## 7. Risk ve Azaltma

| Risk | Olasılık | Etki | Azaltma |
|------|----------|------|---------|
| yfinance rate limit | Yüksek | Yüksek | Rate limiter + circuit breaker + fallback |
| KAP API değişikliği | Orta | Yüksek | Scraper + regex fallback, düzenli test |
| TCMB EVDS API key yok | Orta | Orta | yfinance fallback (USD/TRY, altın) |
| Look-ahead bias | Yüksek | Kritik | PIT validator + backtest entegrasyonu |
| Network timeout | Yüksek | Orta | Retry + timeout + circuit breaker |
| Duplicate events | Orta | Orta | Deduplication window |
| Providerdług | Düşük | Yüksek | Rate limiter + backoff |
| Data quality drop | Orta | Yüksek | Anomaly detection + alert |
| Silent failure | Yüksek | Kritik | Structured logging + metrics + alert |

---

## 📊 Zaman Özeti

| Faz | Süre | Bağımlılık | Teslimat |
|-----|------|------------|----------|
| **Faz 0** | 1-2 gün | Yok | Circuit breaker, rate limiter, retry, refactor |
| **Faz 1** | 2-3 gün | Faz 0 | Data quality, reconciliation, anomaly |
| **Faz 2** | 2-3 gün | Faz 0 | PIT validation, dedup, incremental |
| **Faz 3** | 3-4 gün | Faz 0 | Async refactor, yeni provider'lar |
| **Faz 4** | 2-3 gün | Faz 1+2+3 | Orchestrator entegrasyonu |
| **Faz 5** | 2-3 gün | Faz 4 | Metrics, monitoring, alerting |
| **Faz 6** | 3-4 gün | Faz 5 | Test, backtest, production |
| **TOPLAM** | **15-22 gün** | | |

**Not:** Faz 1, Faz 2 ve Faz 3 paralel geliştirilebilir (bağımsız). Bu durumda toplam süre **12-16 gün**'e düşer.

---

## 🔑 Kritik Tasarım Kararları

1. **Sliding window rate limiter** — token bucket'tan daha adil (PyResilience deneyimi)
2. **Jitter'lı retry** — thundering herd önleme (tüm istekler aynı anda tekrar denemesin)
3. **Per-provider circuit breaker** — bir provider diğerini etkilemesin
4. **Point-in-time validation** — look-ahead bias kritik risk (arXiv 2026)
5. **Ağırlıklı canonical price** — güvenilir kaynak yüksek ağırlık (S&P DJI methodology)
6. **Deduplication window** — 24 saat pencere, MD5 hash
7. **Incremental updates** — bandwidth ve API limit tasarrufu
8. **Async refactor** — mevcut blocking kod → async (aiohttp tabanlı)
9. **Structured logging** — tüm hatalar JSON formatında (structlog)
10. **Prometheus metrics** — production monitoring için standart

---

## 📚 Referanslar

1. PyResilience — https://github.com/AhsanSheraz/pyresilience (2026)
2. Rate Limiting, Circuit Breakers, Backpressure — BirJob (2025)
3. Look-Ahead Bias Prevention — arXiv 2512.12924 (2025)
4. Walk-Forward Validation — arXiv 2512.12924v1 (2025)
5. S&P DJI Corporate Actions Methodology
6. Apache Kafka Architecture — Instaclustr (2025)
7. Event-Driven Architecture Patterns — Solace
8. Reddit AlgoTrading Best Practices (2025)
9. Python Async for Real-World API Load — Medium (2025)
10. Building Bulletproof LLM Applications — Google Cloud (2025)
