# CORE — Servis Çekirdeği

> Bu belge hedef mimariyi tanımlar, bugün kodda gerçekte var olan/olmayan kısımlar için `CURRENT-STATE.md`'ye bakın.

## Katman Haritası

```
┌─────────────────────────────────────────────────────────────────┐
│                        CORE SERVICES                            │
├─────────────┬─────────────┬──────────────┬─────────────────────┤
│  Karar &    │  Risk &     │  Altyapı &   │  Gözlemlenebilirlik │
│  Skorlama   │  Uyumluluk  │  Dayanıklılık│  & Monitoring       │
├─────────────┼─────────────┼──────────────┼─────────────────────┤
│ decision_   │ risk_gate   │ config       │ monitoring          │
│ engine      │ compliance  │ database     │ audit_log           │
│ canonical_  │ short_      │ event_bus    │ observability       │
│ scoring     │ selling     │ event_schema │ production_metrics  │
│ orchestrator│ halt_monitor│ dead_letter_ │ grafana_provisioning│
│ regime_     │ price_limits│ queue        │ distributed_tracing │
│ detector    │ circuit_    │ recovery     │ alerting            │
│ data_quality│ breaker     │ state_       │ alert_policy        │
│ tradability_│ manipulation│ recovery     │ immutable_audit     │
│ mask        │ detector    │ worker       │                     │
│ feature_    │ insider_    │ system_      │                     │
│ store       │ detector    │ governor     │                     │
│ broker      │             │ security     │                     │
│             │             │ jwt_manager  │                     │
│             │             │ redis_helper │                     │
│             │             │ db_lock      │                     │
│             │             │ config_hot_  │                     │
│             │             │ reload       │                     │
└─────────────┴─────────────┴──────────────┴─────────────────────┘
```

## Neden Bu Teknoloji / Tasarım Seçimi?

| Karar | Neden |
|-------|-------|
| **Pydantic Settings** ile config yönetimi | Tip güvenliği, `.env` otomatik parse, production validation (`model_validator` ile insecure default engeli) |
| **Redis Pub/Sub** (push-based event bus) | Düşük latency, polling yok, in-memory fallback (Docker yokken) |
| **Kafka/Redpanda** opsiyonel transport | Yüksek volume senaryoları için hazır; mevcut volume'da Redis yeterli |
| **SQLite** (historical repository) | Hafif, dosya tabanlı, WAL modu ile concurrent okuma; PostgreSQL'e ihtiyaç duymadan PIT-safe veri |
| **asyncpg + ClickHouse + Redis** üçlü DB | PostgreSQL (transactional), ClickHouse (analytics/OLAP), Redis (cache/pubsub) — her biri farklı iş yükü için |
| **Circuit Breaker + Rate Limiter** | ProviderроссийскBaşarısızlıklarında cascade failure önleme; token bucket + exponential backoff |
| **Canonical Scoring Pipeline** | 9 motorun çıktısını tek bir `ScoreVector`'da birleştirir; rejime göre ağırlık değişimi |
| **Mask-First Design** | Execute edilemeyen fiyat (tavan/taban/halt/devre kesici) feature hesaplamasına girmez → +0.44 Sharpe katkısı (Du 2026) |
| **Singleton pattern** | Tüm servisler modül seviyesinde singleton; `from services.core.xxx import xxx` ile erişim |
| **structlog** | Yapılandırılmış loglama; JSON format, correlation ID desteği |

## Uçtan Uca Veri Akışı

```
1. Config yüklenir (config.py → Settings → Pydantic validation)
2. Veritabanları başlatılır (database.py → PostgreSQL + ClickHouse + Redis)
3. Event bus bağlanır (event_bus.py → Redis Pub/Sub + optional Kafka)
4. Orchestrator.initialize() tüm servisleri registry'den yükler
5. Orchestrator.run_pipeline(ticker, market_data) çalıştırılır:
   5a. Feature hesaplama (features.calculator)
   5b. Macro features (features.macro)
   5c. News/KAP sentiment (intelligence.news_pipeline)
   5d. World state (intelligence.world_state)
   5e. Regime detection (intelligence.regime)
   5f. Analysis engines (price_action, volume, sector, relative_strength)
   5g. Forecasting + Probability (intelligence.forecasting)
   5h. Monte Carlo simülasyonu (intelligence.monte_carlo)
   5i. Intelligence pipeline (fused direction + confidence)
   5j. Spec engine (değerleme)
   5k. Factor engine (finansal skorlar)
   5l. Agent pipeline (LLM agent + debate + synthesis)
   5m. Signal fusion (tüm sinyalleri birleştir)
   5n. Decision engine (karar üret)
   5o. Trade planner (plan oluştur)
   5p. Risk gate (risk kontrolü)
   5q. Compliance (SPK uyumluluk)
   5r. Learning feedback (prediction kaydet)
6. Event'ler publish edilir (DECISION_CREATED, AGENT_ANALYSIS_COMPLETED vb.)
7. Audit log'a kaydedilir
```

## Servis Sınırları ve Sorumlulukları

| Dosya | Sorumluluk | Katman |
|-------|-----------|--------|
| `services/core/orchestrator.py` | Tüm servisleri tek pipeline'da birleştirme, `run_pipeline()` ve `run_full_pipeline()` | Orkestrasyon |
| `services/core/decision_engine.py` | Karar üretimi: composite skor, yön belirleme, ATR bazlı stop/target, conviction | Karar |
| `services/core/canonical_scoring.py` | 9 motorun çıktısını `ScoreVector`'da birleştirme, rejime göre ağırlıklı skor | Skorlama |
| `services/core/risk_gate.py` | Merkezi risk kontrolü: pozisyon limiti, drawdown, günlük zarar, Monte Carlo VaR, macro stress | Risk |
| `services/core/compliance.py` | SPK uyumluluk: %5 bildirim, %10 zorunlu teklif, %20 engelleme azınlığı | Uyumluluk |
| `services/core/data_quality.py` | Veri kalitesi kontrolü + `TradabilityMask` (tavan/taban/halt/devre kesici tespiti) | Veri Kalitesi |
| `services/core/tradability_mask.py` | Vektörize tradability mask hesaplama (limit-up/down, circuit breaker, OHLC tutarlılığı) | Veri Kalitesi |
| `services/core/regime_detector.py` | Çok faktörlü piyasa rejimi tespiti (trend, volatilite, momentum, breadth, korelasyon) | Piyasa Durumu |
| `services/core/event_bus.py` | Push-based iç iletişim: Redis Pub/Sub + Stream (durable ledger) + Kafka opsiyonel | Altyapı |
| `services/core/event_schema.py` | Canonical event yapısı, `EventType` enum, payload validation, typed data schemas | Altyapı |
| `services/core/config.py` | Pydantic Settings: tüm konfigürasyon, production security validation | Altyapı |
| `services/core/database.py` | PostgreSQL (asyncpg), ClickHouse, Redis bağlantı yönetimi, retry, health check | Altyapı |
| `services/core/security.py` | Authentication (JWT), Authorization (RBAC), Secret Redaction, Safety Governance | Güvenlik |
| `services/core/circuit_breaker.py` | Circuit Breaker (CLOSED→OPEN→HALF_OPEN), Rate Limiter (token bucket), Retry Policy, Provider Reliability | Dayanıklılık |
| `services/core/recovery.py` | Event Replay, Graceful Shutdown, Startup Recovery, Failure Injector (test) | Dayanıklılık |
| `services/core/state_recovery.py` | Snapshot + Event Log ile restart sonrası state kurtarma (P0-7 düzeltmesi) | Dayanıklılık |
| `services/core/system_governor.py` | Sistem durum makinesi (FULL→DEGRADED→READ_ONLY→RECOVERY), feature flag'ler | Dayanıklılık |
| `services/core/dead_letter_queue.py` | Başarısız event'ler için kalıcı kuyruk, exponential backoff retry | Dayanıklılık |
| `services/core/worker.py` | Job execution: retry, timeout, idempotency, DB-backed state persistence | Altyapı |
| `services/core/feature_store.py` | Feature cache: in-memory LRU + Redis, TTL-based invalidation | Performans |
| `services/core/broker.py` | Broker abstraction: PaperBroker (simülasyon), idempotency, order lifecycle | Yürütme |
| `services/core/audit_log.py` | Immutable audit trail: decision lineage, risk checks, order/fill tracking | Gözlemlenebilirlik |
| `services/core/monitoring.py` | Portfolio + lock monitoring, Prometheus metrics, health endpoints | Gözlemlenebilirlik |
| `services/core/models.py` | Pydantic data models: MarketTick, AssetState, Signal, Portfolio, Prediction, Alert | Veri Modeli |
| `services/core/constants.py` | Global sabitler: BIST komisyon oranları, risk limitleri, feature engineering parametreleri | Sabitler |
| `services/core/short_selling.py` | Açığa satış kontrolü (BIST kuralları) | Uyumluluk |
| `services/core/halt_monitor.py` | Hisse işlem durdurma takibi | Uyumluluk |
| `services/core/price_limits.py` | Fiyat limiti kontrolü (tavan/taban) | Uyumluluk |
| `services/core/manipulation_detector.py` | Manipülasyon tespit | Uyumluluk |
| `services/core/insider_detector.py` | İçerden bilgi ticareti tespiti | Uyumluluk |

## Tasarım İlkeleri ve Kırmızı Çizgiler

### İlkeler

1. **Fail-Closed**: Risk gate, compliance, circuit breaker — hata durumunda engelle, izin verme
2. **Mask-First**: Execute edilemeyen fiyat hiçbir feature hesaplamasına giremez
3. **PIT-Safe**: Gelecek veri kullanma (look-ahead bias = ölüm)
4. **Push-Based**: Sürekli API isteği yok; veri olduğunda push ile gelir
5. **Singleton**: Tüm servisler modül seviyesinde singleton; global state tutarlı
6. **Idempotent**: Aynı event/job tekrar tekrar işlenmez
7. **Graceful Degradation**: Sistem durumu makinesi ile kademeli bozulma

### Kırmızı Çizgiler

- ❌ Risk gate bypass edilemez (AI dahil)
- ❌ Audit log silinemez veya değiştirilemez
- ❌ Production'da insecure secret key ile çalışılamaz (`config.py` → `sys.exit(1)`)
- ❌ Mask=0 olan fiyat feature hesaplamasına giremez
- ❌ `max()` ile optimistic bias yaratılamaz (v2.1 düzeltmesi: güven-ağırlıklı ortalama)
- ❌ Asimetrik eşikler kullanılamaz (BUY bias yaratır; v2.1: simetrik eşikler)

## Bilinen Sınırlamalar

1. **In-memory state**: Çoğu servis (audit_log, DLQ, regime_detector, feature_store) in-memory state tutar; restart sonrası kaybolur (state_recovery.py kısmi çözüm)
2. **PaperBroker**: Gerçek broker henüz bağlanmadı; sadece simülasyon
3. **SQLite historical repository**: Production'da PostgreSQL/ClickHouse'a geçiş gerekebilir
4. **Kafka opsiyonel**: REDPANDA_BROKERS tanımlı değilse Kafka kullanılmaz; Redis Pub/Sub yeterli
5. **LLM agent**: Ollama/Gemini bağımlı; LLM yoksa agent pipeline devre dışı kalır
6. **Regime detector**: Basit Markov geçiş matrisi; gerçek veri ile güncellenmeli
7. **Feature store**: LRU eviction; çok büyük universe'de cache thrashing olabilir
8. **Worker**: DB-backed idempotency; DB yoksa idempotency kontrolü atlanır

## Cross-Reference

| Modül | Bağlantı |
|-------|----------|
| **data** | `data_source.py` → ham veri çeker; `orchestrator.py` → `features.calculator` ile feature üretir |
| **events** | `event_bus.py` + `event_schema.py` → tüm modüller arası iletişim; `dead_letter_queue.py` → başarısız event'ler |
| **labels** | `label_generator.py` → gelecek getiri label'ları; `canonical_scoring.py` → skorlama pipeline'ı |
| **features** | `orchestrator.py` → `features.calculator` ve `features.macro` çağırır |
| **intelligence** | `orchestrator.py` → regime, forecasting, monte_carlo, signal_fusion, agent_pipeline çağırır |
| **risk** | `orchestrator.py` → `risk.position_sizing` çağırır; `risk_gate.py` → merkezi risk kontrolü |
| **portfolio** | `orchestrator.py` → `portfolio.portfolio_manager` çağırır |
| **learning** | `orchestrator.py` → `learning.outcome_tracker` ve `learning.integrated_learning` çağırır |
| **agents** | `orchestrator.py` → `agents.agent_pipeline` çağırır (LLM agent + debate + synthesis) |
