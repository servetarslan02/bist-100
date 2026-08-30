# BIST-100 SSD Sürekli Yazma Analiz Raporu

**Tarih:** 2026-08-31  
**Kapsam:** 1250 dosya, tüm servisler, background task'lar, veritabanları, frontend polling

---

## 1. SÜREKLİ DÖNGÜDE OLAN YAZMA KAYNAKLARI

### 1.1 `radar_cache_refresher` — Her 2 Saniyede (Seans Açıkken)
**Dosya:** `services/api/background_tasks.py:22`  
**Döngü:** `while True` → `await asyncio.sleep(2)` → `_fetch_radar_fresh(limit=1000)`  
**Ne yazıyor:** Redis'e radar verisi (1000 hisse)  
**Süre:** Seans açıkken (10:00-18:00 TR) sürekli  
**Seans kapalı:** 60 saniyede bir boş döngü  
**Etki:** REDİS YAZMA + API log üretimi

### 1.2 `ml_learning_scheduler` — Her 4 Saatte Bir
**Dosya:** `services/api/background_tasks.py:65`  
**Döngü:** `while True` → `await asyncio.sleep(4 * 3600)` → `learning_loop.trigger_autonomous_retrain()` + `pipeline.run_learning_cycle()`  
**Ne yazıyor:** DuckDB (`data/model_memory.duckdb`), model pickle dosyaları, Redis  
**Başlangıçta:** `pipeline.check_and_catchup_if_needed()` — ilk açılışta eksik eğitimleri telafi eder  
**Etki:** DUCKDB + PICKLE + REDİS YAZMA

### 1.3 `paper_trading_scheduler` — Seans Takvimine Göre
**Dosya:** `services/api/background_tasks.py:120`  
**Döngü:** `while True` → seans saatine göre `await asyncio.sleep(sleep_seconds)`  
**Başlangıçta:** `master_catchup.execute_full_catchup()` — kaçırılan tüm seans günlerini telafi eder  
**Ne yazıyor:** PostgreSQL (trades, positions, portfolio), DuckDB, Redis  
**Etki:** POSTGRESQL + DUCKDB + REDİS YAZMA (başlangıçta yoğun)

### 1.4 `auto_storage_optimizer` — Her 12 Saatte Bir
**Dosya:** `services/api/background_tasks.py:94`  
**Döngü:** `while True` → `await asyncio.sleep(12 * 3600)` → `ch_execute("OPTIMIZE TABLE bist_ticks FINAL")`  
**Ne yazıyor:** ClickHouse data part merge  
**Etki:** CLICKHOUSE YAZMA (yoğun ama seyrek)

### 1.5 `cache_warmer.refresh_hot_keys` — Her 1 Saatte Bir
**Dosya:** `services/core/cache_warmer.py:192`  
**Döngü:** `while True` → `await asyncio.sleep(3600)` → fiyat/sinyal/portfolio/cache güncelleme  
**Ne yazıyor:** Redis  
**Etki:** REDİS YAZMA

### 1.6 `ConfigWatcher._watch_loop` — Her 5 Saniyede
**Dosya:** `services/core/config_watcher.py:129`  
**Döngü:** `while self._running` → `await asyncio.sleep(5)` → dosya mtime kontrolü  
**Ne yazıyor:** Disk okuma (mtime check), değişiklik varsa audit log  
**Etki:** MİNİMAL (sadece okuma, nadiren yazma)

### 1.7 `ConfigHotReload.start` — Her 5 Saniyede
**Dosya:** `services/core/config_hot_reload.py:136`  
**Döngü:** `while self._running` → `await asyncio.sleep(5)` → config hash kontrolü  
**Ne yazıyor:** Disk okuma, değişiklik varsa callback  
**Etki:** MİNİMAL

### 1.8 `AlertingEngine._escalation_loop` — Her 10 Saniyede
**Dosya:** `services/core/alerting.py:693`  
**Döngü:** `while True` → `await asyncio.sleep(10)` → alert escalation kontrolü  
**Ne yazıyor:** Alert durumu değişirse Redis  
**Etki:** MİNİMAL

### 1.9 `ConnectivityMonitor._monitor_loop` — Değişken Aralıklarla
**Dosya:** `services/core/connectivity.py:205`  
**Döngü:** `while self._running` → endpoint health check  
**Ne yazıyor:** Durum değişirse Redis  
**Etki:** MİNİMAL

---

## 2. FRONTEND POLLING (API LOG ÜRETİMİ)

### 2.1 `GlobalTelemetrySync` — 15 Endpoint Sürekli Polling
**Dosya:** `apps/web/src/components/providers/GlobalTelemetrySync.tsx`  
**Endpoint'ler ve aralıkları:**

| Endpoint | Interval | Etki |
|---|---|---|
| `/market/state` | 10s | Her istek → API log |
| `/system/status` | 10s | Her istek → API log |
| `/portfolio` | 10s | Her istek → API log |
| `/market/radar?limit=1000` | 25s | Her istek → API log + Redis okuma |
| `/portfolio/alpha-signals` | 15s | Her istek → API log |
| `/scanner/signals?limit=25` | 15s | Her istek → API log |
| `/event-study/events` | 15s | Her istek → API log |
| `/system/alerts` | 15s | Her istek → API log |
| `/models/list` | 30s | Her istek → API log |
| `/learning/performance-matrix` | 30s | Her istek → API log |
| `/learning/report` | 30s | Her istek → API log |
| `/system/databases` | 30s | Her istek → API log |
| `/macro/world` | 30s | Her istek → API log |
| `/market/heatmap` | 30s | Her istek → API log |

**Toplam:** ~15 endpoint × dakikada ~4 istek = **~60 API istek/dakika** → sürekli Docker log yazma

### 2.2 Sayfa Bazlı Ek Polling
**Dosyalar:** `apps/web/src/app/*/page.tsx`  
- `/portfolio` sayfası: 1.5s interval
- `/portfolio/orders`: 3s interval
- `/asset` sayfası: 1.5s interval
- `/data` sayfası: 5s interval
- `/learning` sayfası: 15s interval
- `/opportunities` sayfası: polling

---

## 3. VERİTABANI SÜREKLİ YAZMA KAYNAKLARI

### 3.1 PostgreSQL (TimescaleDB)
**Docker Compose Ayarları:**
- `fsync=on` → Her commit'te diske zorla flush
- `synchronous_commit=on` → Her transaction'da WAL yazma
- `full_page_writes=on` → Her checkpoint'te tam sayfa yazma
- `wal_level=replica` → Replikasyon WAL üretimi
- `max_wal_size=512MB` → WAL dosyası büyütme
- `checkpoint_completion_target=0.9` → Yavaş checkpoint (sürekli yazma)
- `autovacuum_max_workers=2` → Otomatik vacuum (sürekli yazma)
- `autovacuum_naptime=60` → Her 60 saniyede vacuum kontrolü

**Sürekli Yazma:** WAL, checkpoint, autovacuum, replikasyon stream

### 3.2 PostgreSQL Replica
**Ek yazma:** Primary'den replication WAL okuma + kendi WAL yazma

### 3.3 ClickHouse
**Docker Compose Ayarları:**
- `system_logs.xml` ile 8 log tablosu devre dışı bırakılmış (trace_log, metric_log, query_log, part_log vb.)
- Ama hâlâ aktif: `text_log` (warning seviyesi), data part merge, background mutation

**Sürekli Yazma:** Data part merge, background mutation, text_log

### 3.4 Redis
**Docker Compose Ayarları:**
- `--appendonly no` → AOF kapalı (iyi)
- `--save 900 1` → 900 saniyede 1 değişiklik varsa RDB snapshot
- `--save 300 10` → 300 saniyede 10 değişiklik varsa RDB snapshot
- `--maxmemory 192mb` → LRU eviction

**Sürekli Yazma:** RDB snapshot (periyodik), LRU eviction log

### 3.5 NATS JetStream
**Docker Compose Ayarları:**
- `-js` → JetStream aktif
- `-sd /data` → Stream data diske yazılıyor

**Sürekli Yazma:** Stream data, consumer state

### 3.6 Prometheus
**Docker Compose Ayarları:**
- TSDB verisi `/prometheus` volume'una yazılıyor
- Scrape interval: 15s (varsayılan)

**Sürekli Yazma:** Metrics TSDB (her scrape'de)

### 3.7 Grafana
**Sürekli Yazma:** Dashboard state, session data

### 3.8 MLflow
**Sürekli Yazma:** Experiment tracking, artifact logging

### 3.9 QuestDB
**Sürekli Yazma:** Time-series data ingestion

### 3.10 Zookeeper
**Sürekli Yazma:** Transaction log, snapshot

### 3.11 PgBouncer
**Sürekli Yazma:** Log (connections, disconnections, pooler errors)

---

## 4. UYGULAMA SEVİYESİNDE YAZMA KAYNAKLARI

### 4.1 `SSDThrottledWriter` (Donanım Orkestratörü)
**Dosya:** `services/core/hardware_orchestrator.py:56`  
**Mekanizma:** RAM kuyruğunda biriktir, her 3 saniyede flush  
**Durum:** Singleton olarak her container'da实例化 ama `enqueue_write()` hiçbir yerden çağrılmıyor  
**Etki:** YOK (ölü kod)

### 4.2 `StateStore` (DuckDB Buffered Write)
**Dosya:** `services/core/state_store.py:243`  
**Mekanizma:** `_buffered_write()` → buffer dolunca `_flush_buffer()`  
**Ne yazıyor:** Circuit state, provider reliability, rate limiter, learning state, predictions, fusion weights  
**Etki:** DUCKDB YAZMA (periyodik)

### 4.3 `PaperTradingStateStore` (DuckDB)
**Dosya:** `services/paper_trading/state_store.py`  
**Ne yazıyor:** Portfolio state, positions, trades, orders, daily performance, equity points, pending signals  
**Etki:** DUCKDB YAZMA (her işlem sonrası)

### 4.4 `ModelMemoryStore` (DuckDB)
**Dosya:** `services/learning/model_memory_store.py`  
**Ne yazıyor:** Predictions, outcomes, metrics, fusion weights  
**Etki:** DUCKDB YAZMA (her tahmin/sonuç)

### 4.5 `ImmutableAuditLog`
**Dosya:** `services/core/immutable_audit.py:314`  
**Ne yazıyor:** `open(path, "a")` ile append-only audit log  
**Etki:** DOSYA YAZMA (her audit entry)

### 4.6 `AlertPolicy._save_to_file()`
**Dosya:** `services/core/alert_policy.py:893`  
**Ne yazıyor:** Alert policy JSON dosyası  
**Etki:** DOSYA YAZMA (her policy değişikliği)

### 4.7 `HolidayManager`
**Dosya:** `services/core/holiday_manager.py:905,932`  
**Ne yazıyor:** `config/holidays.json` ve audit dosyası  
**Etki:** DOSYA YAZMA (periyodik)

### 4.8 `HistoricalStore` (Makro Veri)
**Dosya:** `services/macro/historical_store.py:235`  
**Ne yazıyor:** Makro veri JSON dosyası  
**Etki:** DOSYA YAZMA (veri güncelleme)

### 4.9 `UniverseProvider` (BIST Evren Cache)
**Dosya:** `services/ingestion/providers/universe_provider.py:451`  
**Ne yazıyor:** `data/bist_universe_cache.json`  
**Etki:** DOSYA YAZMA (evren güncelleme)

### 4.10 `AgentMemory.save()`
**Dosya:** `services/agents/agent_memory.py:443`  
**Ne yazıyor:** Agent hafıza JSON dosyası  
**Etki:** DOSYA YAZMA

### 4.11 `FeatureStore.save()`
**Dosya:** `services/alternative/feature_store.py:204`  
**Ne yazıyor:** Feature store JSON dosyası  
**Etki:** DOSYA YAZMA

### 4.12 `KnowledgeGraph`
**Dosya:** `services/intelligence/knowledge_graph.py:260`  
**Ne yazıyor:** Knowledge graph JSON dosyası  
**Etki:** DOSYA YAZMA

### 4.13 `ResearchMemory`
**Dosya:** `services/intelligence/research_memory.py:170`  
**Ne yazıyor:** Research memory JSON dosyası  
**Etki:** DOSYA YAZMA

### 4.14 `VectorMemory`
**Dosya:** `services/intelligence/vector_memory.py:86`  
**Ne yazıyor:** Vector memory dump dosyası  
**Etki:** DOSYA YAZMA

### 4.15 `FeatureTracker`
**Dosya:** `services/learning/feature_tracker.py:373`  
**Ne yazıyor:** Feature tracker JSON dosyası  
**Etki:** DOSYA YAZMA

### 4.16 `IntegratedLearning`
**Dosya:** `services/learning/integrated_learning.py:427`  
**Ne yazıyor:** Learning state JSON dosyası  
**Etki:** DOSYA YAZMA

### 4.17 `ModelRegistry`
**Dosya:** `services/ml/model_registry.py:391`  
**Ne yazıyor:** Model registry JSON dosyası  
**Etki:** DOSYA YAZMA

### 4.18 `TrainAllModels` (Optuna Cache)
**Dosya:** `services/ml/train_all_models.py:140`  
**Ne yazıyor:** Optimal hyperparams cache dosyası  
**Etki:** DOSYA YAZMA

### 4.19 ML Model Kaydetme
**Dosyalar:** `ml/models.py:215`, `ml/training.py:368`, `services/ml/lstm_model.py:310`, `services/ml/transformer_model.py:280`  
**Ne yazıyor:** Model pickle, config JSON, PyTorch checkpoint  
**Etki:** DOSYA YAZMA (eğitim sonrası)

---

## 5. DOCKER LOG YAZMA

### 5.1 JSON File Log Driver
**Docker Compose:** `logging: *id003` → `driver: json-file, max-size: 1m, max-file: '1'`  
**20+ container** × her API isteği/log satırı = sürekli log dosyası yazma  
**Her container'ın log dosyası:** `/var/lib/docker/containers/<id>/<id>-json.log`

### 5.2 Log Üreten Kaynaklar
- Her API endpoint isteği (structlog JSON formatında)
- Her background task log satırı
- Her Redis/PostgreSQL/ClickHouse bağlantı logu
- Her healthcheck logu
- Her OpenTelemetry span (eğer console exporter aktifse)

---

## 6. ÖNCELİK SIRASINA GÖRE ETKİ ANALİZİ

### 🔴 YÜKSEK ETKİ (Sürekli, Yoğun Yazma)
1. **Docker JSON log** — 20+ container, ~60 API istek/dakika + background task logları
2. **PostgreSQL WAL** — fsync=on, synchronous_commit=on, autovacuum
3. **ClickHouse data part merge** — Background merge işlemi
4. **Redis RDB snapshot** — Periyodik snapshot
5. **NATS JetStream** — Stream data yazma
6. **Prometheus TSDB** — Her scrape'de metrics yazma

### 🟡 ORTA ETKİ (Periyodik Yazma)
7. **DuckDB** — State store, paper trading, model memory (buffered write)
8. **ML model kaydetme** — Eğitim sonrası pickle/checkpoint
9. **master_catchup** — Başlangıçta yoğun, sonra durur
10. **radar_cache_refresher** — Seans açıkken her 2 saniyede Redis yazma

### 🟢 DÜŞÜK ETKİ (Nadiren Yazma)
11. **JSON config dosyaları** — Holiday, alert policy, feature store
12. **Audit log** — Append-only, nadiren
13. **Agent memory** — Nadiren
14. **Knowledge graph** — Nadiren

---

## 7. TESPİT EDİLEN SORUNLAR

### 7.1 `SSDThrottledWriter` Ölü Kod
`hardware_orchestrator.py`'daki `SSDThrottledWriter` sınıfı tanımlanmış ama hiçbir yerden `enqueue_write()` çağrılmıyor. SSD koruma mekanizması çalışmıyor.

### 7.2 `apply_ssd_write_limit()` Boş Fonksiyon
`start.py`'deki `apply_ssd_write_limit()` fonksiyonu sadece `return True` yapıyor. cgroup v2 ile SSD yazma limiti uygulanmıyor.

### 7.3 Docker Memory Limitleri Kaldırılmış
`docker-compose.yml`'de hiçbir container'da `mem_limit` yok. Container'lar sınırsız RAM kullanabiliyor.

### 7.4 PostgreSQL Aşırı Koruma
`fsync=on` + `synchronous_commit=on` + `full_page_writes=on` = her transaction'da diske zorla flush. Kişisel PC için aşırı.

### 7.5 Frontend Aşırı Polling
15 endpoint × 10-30s interval = sürekli API istek üretimi → Docker log yazma.

---

## 8. DÜZELTME ÖNERİLERİ

### 8.1 Docker Log Azaltma
```yaml
logging: &id003
  driver: none  # veya json-file ile max-size: 500k, max-file: '1'
```

### 8.2 PostgreSQL WAL Azaltma
```
-c fsync=off  (Kişisel PC, veri kaybı kabul edilebilir)
-c synchronous_commit=off
-c full_page_writes=off
-c wal_level=minimal
-c max_wal_size=256MB
```

### 8.3 Redis Snapshot Azaltma
```
--save 3600 1  (1 saatte bir)
```

### 8.4 Frontend Polling Azaltma
GlobalTelemetrySync interval'larını 2-3x artır.

### 8.5 SSD Write Limit Uygula
`start.py`'deki `apply_ssd_write_limit()` fonksiyonunu onar.

### 8.6 Docker Memory Limitleri Geri Ekle
Her container'a uygun `mem_limit` ekle.
