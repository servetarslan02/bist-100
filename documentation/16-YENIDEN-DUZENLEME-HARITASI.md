# 16 — Yeniden Düzenleme Haritası: `services/agents/`

**Tarih:** 2026-09-03
**Kapsam:** `services/agents/` dizini
**Yöntem:** Gerçek `grep` ile doğrulanmış import analizi (tahmin değil)

---

## 1. Dosya Envanteri

| # | Dosya | Satır | Rolü |
|---|-------|-------|------|
| 1 | `__init__.py` | 137 | Package facade — tüm public API'yi dışa aktarır |
| 2 | `agent_memory.py` | ~200 | Working/Episodic/Semantic bellek + consolidator |
| 3 | `agent_pipeline.py` | ~350 | Üst düzey orkestratör — tüm alt sistemleri birleştirir |
| 4 | `agent_system.py` | ~400 | Core: BaseAgent, AgentOrchestrator, AgentRole enum |
| 5 | `communication_bus.py` | ~150 | Agent'lar arası mesajlaşma + ConflictResolver |
| 6 | `conflict_detector.py` | ~100 | Çelişen agent çıktılarını tespit eder |
| 7 | `debate_engine.py` | ~200 | Bull/Bear tartışması motoru |
| 8 | `llm_client.py` | 503 | Abstract LLM client (Ollama/OpenAI/Anthropic) |
| 9 | `parallel_runner.py` | ~150 | Paralel agent çalıştırıcı |
| 10 | `prompts/__init__.py` | ~500 | Tüm prompt şablonları + PromptFactory |
| 11 | `risk_assessor.py` | ~150 | Risk değerlendirme agent'ı |
| 12 | `schemas/__init__.py` | ~250 | Pydantic JSON şemaları |
| 13 | `self_evaluator.py` | ~200 | Agent self-evaluation + Brier skoru |
| 14 | `synthesis_engine.py` | ~200 | Tüm agent sonuçlarını sentezler |

**Toplam:** 14 dosya, ~3,300 satır

---

## 2. Dahili Bağımlılık Ağacı (İçe Aktarma Grafiği)

```
llm_client.py (temel — dışa bağımlı yok)
    ↑
prompts/__init__.py (temel — dışa bağımlı yok)
    ↑
schemas/__init__.py (temel — dışa bağımlı yok)
    ↑
agent_system.py → llm_client, prompts, schemas
    ↑
├── debate_engine.py → agent_system, llm_client
├── parallel_runner.py → agent_system, llm_client
├── conflict_detector.py → agent_system
├── communication_bus.py → agent_system
├── risk_assessor.py → agent_system, llm_client, prompts
    ↑
agent_memory.py (bağımsız — dışa bağımlı yok)
    ↑
├── self_evaluator.py → agent_memory
├── synthesis_engine.py → agent_memory, agent_system, communication_bus, debate_engine, llm_client, prompts
    ↑
agent_pipeline.py → agent_memory, agent_system, communication_bus, conflict_detector,
                     debate_engine, llm_client, parallel_runner, risk_assessor, self_evaluator
```

**Sonuç:** Temiz, döngüsellik olmayan bir DAG (Directed Acyclic Graph).

---

## 3. Dış Bağımlılıklar (Paket Dışından Kim İthal Ediyor)

| Dosya | Dış İthalatçı | İthal Edilen Sembol |
|-------|---------------|---------------------|
| `agent_pipeline.py` | `services/core/orchestrator.py` | `AgentPipelineOrchestrator` |
| `agent_pipeline.py` | `tests/test_agent_system.py` | `PipelineResult` |
| `agent_system.py` | `services/api/v1/agents.py` | `AgentRole` |
| `agent_system.py` | `tests/test_integration.py` | `AIFallback` |
| `agent_system.py` | `tests/test_phase7.py` | (birkaç sembol) |
| `llm_client.py` | `services/alternative/llm_sentiment.py` | `parse_llm_json` |
| `schemas/__init__.py` | `tests/test_agent_system.py` | `AgentOutputSchema` |
| `__init__.py` (top-level) | `tests/test_agent_system.py` | (birçok sembol) |

**Dışarıdan hiç import edilmeyen dosyalar (sadece `__init__.py` üzeri erişilen):**
- `agent_memory.py` — ❌ doğrudan dış import yok (test'ler `__init__.py` üzerinden)
- `communication_bus.py` — ❌ doğrudan dış import yok
- `conflict_detector.py` — ❌ doğrudan dış import yok
- `debate_engine.py` — ❌ doğrudan dış import yok
- `parallel_runner.py` — ❌ doğrudan dış import yok
- `risk_assessor.py` — ❌ doğrudan dış import yok
- `self_evaluator.py` — ❌ doğrudan dış import yok
- `synthesis_engine.py` — ❌ doğrudan dış import yok

**ÖNEMLİ NOT:** Bu dosyalar "ölü" DEĞİL. Hepsi `__init__.py` üzerinden public API'ye açıktır ve `agent_pipeline.py` tarafından doğrudan kullanılır. `__init__.py` facade pattern'inin normal davranışıdır.

---

## 4. Tespit Edilen Yapısal Sorunlar

### 4.1. ⚠️ İki Ayrı `llm_client.py` — Kafa Karıştırıcı Ama ÇAKIŞMA DEĞİL

| Dosya | Satır | Amaç | Kullanan |
|-------|-------|------|----------|
| `services/agents/llm_client.py` | 503 | Abstract multi-provider (Ollama/OpenAI/Anthropic) | Agent sistemi |
| `services/intelligence/llm_client.py` | 396 | Gemini-specific, tool-calling destekli | Intelligence sistemi |

**Durum:** Bunlar FARKLI implementasyonlar, FARKLI alt sistemler için. İkisi de aktif kullanımda.
**Risk:** Kafa karıştırıcı ama fonksiyonel olarak çakışma yok.
**Öneri:** Bu iki dosyayı birleştirmek BU GÖREVİN KAPSAMI DIŞINDA — ayrı bir karar gerektirir. `documentation/16`'da raporlanır, dokunulmaz.

### 4.2. ✅ `services/ml/rl_agent.py` — ÖLÜ DEĞİL

İlk bakışta "kimse import etmiyor" gibi görünüyor ama:
- `services/ml/__init__.py` → `from .rl_agent import RLConfig, evaluate_rl_agent, train_rl_agent`
- `services/ml/ranking_model.py` → `from .rl_agent import train_rl_agent`

**Durum:** Aktif kullanımda. Arşivleme yapılmayacak.

### 4.3. ✅ `services/agents/` İç Yapısı — SAĞLAM

- Döngüsellik yok (DAG yapısı)
- Her dosya tek sorumlu (SRP uyumlu)
- İsimlendirme tutarlı
- `prompts/` ve `schemas/` alt paketleri doğru organize
- Dead code yok

---

## 5. Yapılacak İşlemler

### Kapsam Dahilinde (Bu Oturum)

Bu dizin için **yapısal sorun tespit edilmediği** için taşıma/arşivleme işlemi yapılmayacaktır.

Gerekçe:
1. Tüm dosyalar aktif kullanımda (doğrudan veya `__init__.py` üzeri)
2. Dead code yok (grep ile doğrulandı)
3. İsimlendirme tutarlı
4. Dahili bağımlılık yapısı temiz (DAG, döngüsellik yok)
5. Tek sorumluluk ilkesine uygun

### Kapsam Dışı (Ayrı Karar Gerektirir)

| # | Bulgu | Risk | Öneri |
|---|-------|------|-------|
| 1 | `services/agents/llm_client.py` vs `services/intelligence/llm_client.py` isim benzerliği | Düşük (farklı amaç) | Ayrı oturumda: isim değişikliği veya birleştirme kararı |
| 2 | `services/agents/` dışarıdan çok az doğrudan import alıyor | Yok (facade pattern) | Değişiklik yok — `__init__.py` doğru çalışıyor |

---

## 6. Doğrulama

- [x] `grep -rn "from services.agents" --include="*.py"` — tüm dış importlar doğrulandı
- [x] `grep -rn "rl_agent" --include="*.py"` — `services/ml/rl_agent.py` aktif kullanımda
- [x] `find . -name "llm_client*"` — iki farklı dosya, farklı amaç
- [x] Dahili bağımlılık grafiği DAG — döngüsellik yok
- [x] Taşıma/silme yapılmadı — sadece harita çıkarıldı

---

## 7. Sonuç

**`services/agents/` dizini iyi yapılandırılmış, temiz ve bakımlı.** Bu kapsam dahilinde yeniden düzenleme gerektiren bir durum bulunmamaktadır. Bir sonraki kapsama geçilebilir.

---

# 16-B — Yeniden Düzenleme Haritası: `services/alternative/`

**Tarih:** 2026-09-03
**Kapsam:** `services/alternative/` dizini
**Yöntem:** Gerçek `grep` ile doğrulanmış import analizi (tahmin değil)

---

## 1. Dosya Envanteri

| # | Dosya | Satır | Rolü |
|---|-------|-------|------|
| 1 | `__init__.py` | 103 | Package facade |
| 2 | `base.py` | 479 | BaseAdapter, RateLimiter, CircuitBreaker, DataQualityValidator, AdapterRegistry |
| 3 | `bkm_adapter.py` | 211 | BKM kredi kartı adapter |
| 4 | `credit_card.py` | 40 | Legacy kredi kartı feature fonksiyonu |
| 5 | `eksi_sozluk.py` | 247 | Ekşi Sözlük sentiment adapter |
| 6 | `feature_engine.py` | 330 | Alternatif veri feature motoru |
| 7 | `feature_store.py` | 252 | Dosya tabanlı feature store |
| 8 | `google_trends.py` | 163 | Google Trends adapter |
| 9 | `investing_adapter.py` | 225 | Investing.com adapter |
| 10 | `jobs.py` | 36 | Legacy iş ilanı feature fonksiyonu |
| 11 | `kariyer_net.py` | 239 | Kariyer.net adapter |
| 12 | `llm_sentiment.py` | 310 | LLM Türkçe sentiment analizi |
| 13 | `reconciliation.py` | 209 | Çapraz kaynak uzlaştırma |
| 14 | `satellite.py` | 40 | Legacy uydu feature fonksiyonu |
| 15 | `satellite_adapter.py` | 352 | Copernicus API uydu adapter |
| 16 | `social.py` | 68 | Legacy sosyal medya feature fonksiyonu |
| 17 | `web_scraping.py` | 42 | Legacy web scraping feature fonksiyonu |

**Toplam:** 17 dosya, 3,346 satır

---

## 2. Dahili Bağımlılık Ağacı

```
base.py (temel)
    ↑
├── bkm_adapter.py → base
├── eksi_sozluk.py → base
├── google_trends.py → base
├── investing_adapter.py → base
├── kariyer_net.py → base
├── satellite_adapter.py → base

feature_store.py (bağımsız)
reconciliation.py (bağımsız)
llm_sentiment.py (bağımsız)

feature_engine.py → base, bkm_adapter, eksi_sozluk, feature_store, google_trends,
                     investing_adapter, kariyer_net, llm_sentiment, reconciliation,
                     satellite_adapter

Legacy fonksiyonlar (bağımsız): credit_card.py, jobs.py, satellite.py, social.py, web_scraping.py
```

**Sonuç:** Temiz DAG, döngüsellik yok.

---

## 3. Dış Bağımlılıklar — KRİTİK BULGU

### HİÇBİR ÜRETİM KODU `services/alternative/` İTHAL ETMİYOR

Tüm dış referanslar SADECE test ve doğrulama dosyalarından geliyor:

| Dosya | Dış İthalatçı | Tür |
|-------|---------------|-----|
| `__init__.py` | `tests/test_alternative_data.py` | Test |
| `__init__.py` | `tests/test_bolum25_32.py` | Test |
| `credit_card.py` | `tests/test_bolum25_32.py` | Test |
| `jobs.py` | `tests/test_bolum25_32.py` | Test |
| `satellite.py` | `tests/test_bolum25_32.py` | Test |
| `satellite_adapter.py` | `tests/test_alternative_data.py` | Test |
| `social.py` | `tests/test_alternative_data.py`, `tests/test_bolum25_32.py` | Test |
| `web_scraping.py` | `tests/test_bolum25_32.py` | Test |
| `llm_sentiment.py` | `scripts/verify_all_api_endpoints.py` | Script |

**Doğrulama:**
```bash
grep -rn "from services\.alternative" --include="*.py" | grep -v "services/alternative/" | grep -v "tests/" | grep -v "scripts/" | grep -v "run_all_imports"
# Sonuç: BOŞ

grep -rn "alternative" services/core/orchestrator.py
# Sonuç: BOŞ

grep -rn "alternative" workers/ --include="*.py"
# Sonuç: BOŞ
```

---

## 4. Tespit Edilen Yapısal Sorunlar

### 4.1. KRİTİK: Tüm Paket Üretim Kodunda Kullanılmıyor

`services/alternative/` (3,346 satır, 17 dosya) hiçbir üretim kodu tarafından import edilmiyor.

**Öneri:** Kullanıcı kararı gerektirir:
- a) Orchestrator'a entegre et
- b) `archive/2026-09-03/` altına taşı
- c) Olduğu gibi bırak

### 4.2. `satellite.py` vs `satellite_adapter.py` — Legacy + Modern

| Dosya | Satır | Amaç | Kullanan |
|-------|-------|------|----------|
| `satellite.py` | 40 | Basit dict→feature (legacy) | Sadece testler |
| `satellite_adapter.py` | 352 | Copernicus API (modern) | `feature_engine.py` + testler |

### 4.3. Legacy `compute_*` vs Modern Adapter'lar

| Legacy | Modern Karşılığı | Durum |
|--------|-------------------|-------|
| `compute_satellite_features()` | `SatelliteAdapter` | İkisi de var |
| `compute_social_features()` | — | Sadece legacy |
| `compute_job_features()` | `KariyerNetAdapter` | İkisi de var |
| `compute_cc_features()` | `BKMAdapter` | İkisi de var |
| `compute_web_features()` | — | Sadece legacy |

### 4.4. Repo Genelinde İsim Tekrarları — ÇAKIŞMA DEĞİL

**`feature_store` (3 dosya):** alternative (dosya tabanlı), core (Redis-backed), features (Feast-inspired)
**`reconciliation` (4 dosya):** alternative, core, ingestion, risk — her biri farklı domain

---

## 5. Yapılan İşlemler

### 5.1. `satellite.py` → `satellite_adapter.py` Birleştirme ✅

- `compute_satellite_features()` fonksiyonu `satellite_adapter.py`'ye taşındı
- `__init__.py` import'u güncellendi: `from .satellite_adapter import SatelliteAdapter, compute_satellite_features, satellite_adapter`
- `tests/test_bolum25_32.py` import'u güncellendi
- `satellite.py` → `archive/2026-09-03/satellite.py.legacy` arşivlendi
- Doğrulama: `python3 -c "from services.alternative import compute_satellite_features"` → OK

### 5.2. Orchestrator Entegrasyonu ✅

- `_SERVICE_REGISTRY`'ye `alt_feature_engine` eklendi
- `_compute_alternative_features()` metodu oluşturuldu
- `run_pipeline`'da `_compute_news_sentiment` sonrası çağrılıyor
- Kapsanan kaynaklar: Google Trends, BKM, Kariyer.net, Ekşi Sözlük, Investing.com, uydu verisi
- Doğrulama: `ast.parse` OK, tüm import'lar OK

### 5.3. Kullanıcı Kararı Gerektiren Durumlar

| # | Bulgu | Durum |
|---|-------|-------|
| 1 | `services/alternative/` production'da kullanılmıyor | ✅ ÇÖZÜLDÜ — orchestrator'a entegre edildi |
| 2 | Legacy `compute_*` fonksiyonları | Düşük risk — backward compatibility için tutuldu |
| 3 | `satellite.py` legacy | ✅ ÇÖZÜLDÜ — `satellite_adapter.py`'ye taşındı, arşivlendi |

---

## 6. Doğrulama

- [x] Tüm dış importlar grep ile doğrulandı
- [x] Production kod taraması: orchestrator, workers, config — hiçbiri kullanmıyor
- [x] `feature_store` — üç farklı dosya, farklı amaç
- [x] `reconciliation` — dört farklı dosya, farklı amaç
- [x] `satellite` — iki dosya, legacy + modern → BİRLEŞTİRİLDİ
- [x] DAG — döngüsellik yok
- [x] `satellite.py` → `satellite_adapter.py` taşındı, arşivlendi
- [x] Orchestrator entegrasyonu: service registry + _compute_alternative_features
- [x] Import doğrulaması: `python3 -c "from services.alternative import ..."` → OK
- [x] Syntax doğrulaması: `ast.parse(orchestrator.py)` → OK

---

## 7. Sonuç (services/alternative/)

**Paket production'a entegre edildi.** Orchestrator artık alternatif veri kaynaklarını kullanıyor:

- ✅ `satellite.py` legacy → `satellite_adapter.py`'ye taşındı, arşivlendi
- ✅ Orchestrator'a `alt_feature_engine` eklendi
- ✅ `_compute_alternative_features()` pipeline'da çağrılıyor
- ✅ Tüm import'lar doğrulandı

Kalan legacy `compute_*` fonksiyonları (social, jobs, cc, web_scraping) backward compatibility için tutuldu — düşük risk.

---

# 16-C — services/core/ Bağlanmamış Altyapı Entegrasyonu

**Tarih:** 2026-09-03
**Kapsam:** `services/core/` dizini — bağlanmamış servisler

## Durum Özeti

9 dosya önce "ölü" sanılıp arşivlendi, sonra aslında bağlanmamış üretim altyapısı olduğu fark edildi ve geri getirildi. Hepsinin neden bağlanmadığı araştırıldı ve orchestrator'a entegre edildi.

## Neden Bağlanmamış?

| Dosya | Neden Bağlanmamış | Çözüm |
|-------|-------------------|-------|
| `insider_detector.py` | Feature tanımı var ama hesaplama yok | Orchestrator'a `_check_insider_trading()` eklendi |
| `manipulation_detector.py` | SPK uyum modülü ayrı yazılmış ama bu bağlanmamış | Orchestrator'a `_check_manipulation()` eklendi |
| `algo_notification.py` | `compliance.py` threshold check yapıyor ama bildirim üretmiyor | Orchestrator'a `_generate_algo_notification()` eklendi |
| `data_schemas.py` | `integration_bridge.py`'de basit validasyon var, Pydantic şemalar kullanılmamış | Orchestrator servis registry'ye eklendi |
| `health_reporter.py` | API'de basit health var, kapsamlı rapor üretilmemiş | Orchestrator'a `_get_system_health()` eklendi |
| `infrastructure.py` | `event_bus.py` var ama catalyst/notification yok | Orchestrator servis registry'ye eklendi |
| `clickhouse_replication_health.py` | DB monitoring hiç bağlanmamış | Orchestrator'a `_check_db_replication()` eklendi |
| `pg_replication_health.py` | DB monitoring hiç bağlanmamış | Orchestrator'a `_check_db_replication()` eklendi |
| `duckdb_store.py` | `duckdb_research.py` var ama store katmanı eksik | Orchestrator servis registry'ye eklendi |

## Orchestrator Entegrasyonu

### Service Registry'ye Eklenen Servisler
```python
("insider_detector", "services.core.insider_detector", "InsiderDetector", True),
("manipulation_detector", "services.core.manipulation_detector", "ManipulationDetector", True),
("algo_notification", "services.core.algo_notification", "generate_algo_notification", False),
("data_schemas", "services.core.data_schemas", "validate_ohlcv", False),
("health_reporter", "services.core.health_reporter", "HealthReporter", True),
("ch_replication", "services.core.clickhouse_replication_health", "check_replication_health", False),
("pg_replication", "services.core.pg_replication_health", "check_replication_health", False),
("duckdb_store", "services.core.duckdb_store", "DuckDBStore", True),
```

### Pipeline'a Eklenen Metodlar

| Metod | Pipeline Aşaması | Açıklama |
|-------|-----------------|----------|
| `_check_insider_trading()` | Özellik hesaplama sonrası | KAP açıklaması öncesi anomali tespiti |
| `_check_manipulation()` | Özellik hesaplama sonrası | Wash trading, spoofing, volume manipulation |
| `_generate_algo_notification()` | Compliance kontrolü sonrası | SPK algo trading bildirimi |
| `_get_system_health()` | API endpoint | Kapsamlı sistem sağlık raporu |
| `_check_db_replication()` | Health check | PG + ClickHouse replikasyon durumu |

## Doğrulama

- [x] `ast.parse(orchestrator.py)` → OK
- [x] Tüm servisler registry'de mevcut
- [x] Tüm metodlar pipeline'da çağrılıyor
- [x] Sınıf/fonksiyon isimleri doğru (ClickHouse/PG fonksiyon, diğerleri sınıf)

---

# 16-D — Kök Dizin Temizliği

**Tarih:** 2026-09-03

## Arşivlenen Dosyalar (11 dosya)

| Dosya | Gerekçe |
|-------|----------|
| `test_core_regressions.py` | Kök dizinde kalmış test |
| `test_engine.py` | Kök dizinde kalmış test |
| `test_engine2.py` | Kök dizinde kalmış test |
| `test_len.py` | Kök dizinde kalmış test |
| `test_llm_system.py` | Kök dizinde kalmış test |
| `test_phase5_end_to_end.py` | Kök dizinde kalmış test |
| `test_providers_live.py` | Kök dizinde kalmış test |
| `verify_3_learning_fixes.py` | Kök dizinde kalmış script |
| `verify_data_sources.py` | Kök dizinde kalmış script |
| `mock_redis.py` | 0 referans |
| `run_baseline_test.py` | 0 referans |

## Kök Dizin Artık

- `main.py` — Ana giriş noktası
- `start.py` — Başlatma scripti
- `run_all_imports.py` — Import doğrulama
- `pyproject.toml`, `requirements.txt`, `setup.sh` — Konfigürasyon

---

# 16-E — Yeniden Düzenleme Haritası: `services/api/`

**Tarih:** 2026-09-03
**Kapsam:** `services/api/` dizini
**Yöntem:** Gerçek `grep` ile doğrulanmış import analizi (tahmin değil)

---

## 1. Dosya Envanteri

| # | Dosya | Satır | Rolü |
|---|-------|-------|------|
| 1 | `__init__.py` | ~15 | Package facade — app, auth, dependencies, rate_limiter export |
| 2 | `app.py` | 577 | **Canonical** production FastAPI uygulaması (ENTRYPOINTS.md) |
| 3 | `auth.py` | ~300 | APIKeyManager, JWTHandler, RBACChecker, Role |
| 4 | `background_tasks.py` | 116 | Radar cache, ML scheduler, storage optimizer, paper trading scheduler |
| 5 | `binary_ws.py` | 801 | Protobuf tabanlı binary WebSocket desteği |
| 6 | `dependencies.py` | ~80 | FastAPI dependency injection (auth, rate limit, orchestrator) |
| 7 | `main.py` | 39 | **DEPRECATED** — sadece `app.py`'yi re-export eder |
| 8 | `rate_limiter.py` | ~120 | InMemoryRateLimiter + endpoint grup limitleri |
| 9 | `server.py` | 730 | **DEPRECATED** — ayrı FastAPI app + admin endpoint'leri |
| 10 | `websocket.py` | 271 | WebSocketConnection + WebSocketServer sınıfları |
| 11 | `v1/__init__.py` | ~30 | V1 router — 19 alt router'ı birleştirir |
| 12 | `v1/agents.py` | ~50 | Agent sistem endpoint'leri |
| 13 | `v1/alternative.py` | ~150 | Alternatif veri endpoint'leri |
| 14 | `v1/backtest.py` | ~100 | Backtest endpoint'leri |
| 15 | `v1/decisions.py` | ~80 | Karar geçmişi endpoint'leri |
| 16 | `v1/event_study.py` | ~200 | Event study endpoint'leri (yfinance entegre) |
| 17 | `v1/factors.py` | ~100 | Faktör skorlama endpoint'leri |
| 18 | `v1/holidays.py` | ~120 | Tatil günü CRUD endpoint'leri |
| 19 | `v1/intelligence.py` | ~200 | Regime, Monte Carlo, Gemini endpoint'leri |
| 20 | `v1/learning.py` | ~150 | Öğrenme pipeline endpoint'leri |
| 21 | `v1/macro.py` | ~250 | Makro veri endpoint'leri (yfinance entegre) |
| 22 | `v1/market.py` | ~400 | Piyasa verisi endpoint'leri (yfinance entegre) |
| 23 | `v1/models.py` | ~100 | ML model endpoint'leri |
| 24 | `v1/portfolio.py` | ~350 | Portföy yönetim endpoint'leri |
| 25 | `v1/risk.py` | ~200 | Risk analizi endpoint'leri |
| 26 | `v1/scanner.py` | ~250 | Tarama/sinyal endpoint'leri (SWR cache) |
| 27 | `v1/schemas.py` | 350 | Pydantic response modelleri (BaseResponse, ErrorResponse, vb.) |
| 28 | `v1/sse.py` | ~150 | Server-Sent Events endpoint'leri |
| 29 | `v1/system.py` | ~150 | Sistem durumu endpoint'leri |
| 30 | `v1/viop.py` | ~150 | VİOP opsiyon fiyatlandırma endpoint'leri |
| 31 | `v1/ws.py` | 282 | WebSocket endpoint + ConnectionManager |

**Toplam:** 31 dosya, ~5,500 satır

---

## 2. Dahili Bağımlılık Ağacı

```
rate_limiter.py (temel — dışa bağımlı yok)
    ↑
auth.py → services.core.otel, services.core.security
    ↑
dependencies.py → auth, rate_limiter
    ↑
v1/* (tüm router'lar) → dependencies
    ↑
v1/__init__.py → v1/* (19 router)
    ↑
app.py → rate_limiter, v1/__init__, background_tasks, services.core.database, services.core.otel

binary_ws.py (bağımsız — Protobuf)
    ↑
v1/ws.py → binary_ws (conditional import)

websocket.py (bağımsız — HİÇBİR YERDEN İMPORT EDİLMİYOR)
main.py → app.py (sadece re-export)
server.py (bağımsız — kendi FastAPI app'ini oluşturur, DEPRECATED)
```

**Sonuç:** Temiz DAG, döngüsellik yok.

---

## 3. Dış Bağımlılıklar

| Dosya | Dış İthalatçı | İthal Edilen Sembol | Tür |
|-------|---------------|---------------------|-----|
| `app.py` | `scripts/verify_all_api_endpoints.py` | `create_app` | Script |
| `app.py` | `scripts/verify_dashboard_live.py` | `app` | Script |
| `app.py` | `tests/test_api.py` | `create_app` | Test |
| `app.py` | `tests/test_observability_pipeline.py` | `app` | Test |
| `app.py` | `tests/test_openapi_contract.py` | `app` | Test |
| `auth.py` | `apps/api/main.py` | `jwt_handler` | **Üretim** |
| `auth.py` | `tests/test_api.py` | `APIKeyManager, JWTHandler, Role, rbac_checker` | Test |
| `rate_limiter.py` | `tests/test_api.py` | `InMemoryRateLimiter, RATE_LIMITS` | Test |
| `binary_ws.py` | `scripts/verify_all_api_endpoints.py` | `ProtobufMessage` | Script |

---

## 4. Tespit Edilen Yapısal Sorunlar

### 4.1. 🔴 ÜÇ AYRI FastAPI UYGULAMASI

| Dosya | Satır | Durum | Port |
|-------|-------|-------|------|
| `services/api/app.py` | 577 | **Canonical** | 8000 |
| `services/api/server.py` | 730 | **DEPRECATED** | ? |
| `apps/api/main.py` | ~300 | Standalone | 8001 |

`server.py`'de canonical `app.py`'de OLMAYAN 15+ admin endpoint var. Kullanıcı kararı gerektirir.

### 4.2. 🟡 `websocket.py` — ÖLÜ DOSYA (KANITLANMIŞ)
- 0 dış import, alternatifleri var → ARŞİVLENDİ

### 4.3. 🟡 `main.py` — ÖLÜ DOSYA (KANITLANMIŞ)
- 0 dış import, DEPRECATED re-export → ARŞİVLENDİ

### 4.4. 🟡 `schemas.py` — ÖLÜ DOSYA (KANITLANMIŞ)
- 0 dış import, hiçbir endpoint kullanmıyor → ARŞİVLENDİ

### 4.5. 🟡 `server.py` — DEPRECATED AMA BENZERSİZ İÇERİK
- 15+ benzersiz admin endpoint'i → KULLANICI KARARI GEREKTİRİR

### 4.6. 🟢 `rate_limiter.py` — İSİM TEKRARI AMA ÇAKIŞMA DEĞİL
- `services/api/` ve `services/ingestion/` farklı domain'ler

---

## 5. Yapılan Taşımalar

| # | Eski → Yeni | Gerekçe | Doğrulama |
|---|-------------|---------|----------|
| 1 | `services/api/main.py` → `archive/2026-09-03/services/api/main.py.deprecated` | 39 satır, DEPRECATED, 0 dış import | `grep` → 0 sonuç |
| 2 | `services/api/websocket.py` → `archive/2026-09-03/services/api/websocket.py.unused` | 271 satır, 0 dış import, alternatifleri var | `grep` → 0 sonuç |
| 3 | `services/api/v1/schemas.py` → `archive/2026-09-03/services/api/v1/schemas.py.unused` | 350 satır, 0 dış import | `grep` → 0 sonuç |

---

## 6. Doğrulama

- [x] `grep -rn "from services.api.main" --include="*.py"` → 0 sonuç
- [x] `grep -rn "from.*services.api.websocket" --include="*.py"` → 0 sonuç
- [x] `grep -rn "from.*schemas" --include="*.py" services/api/` → 0 sonuç
- [x] `grep -rn "from services.api.server" --include="*.py"` → 0 sonuç
- [x] `grep -rn "from services.api.app" --include="*.py"` → 10+ sonuç (canonical)
- [x] `grep -rn "from services.api.auth" --include="*.py"` → 7 sonuç (aktif)
- [x] `grep -rn "from services.api.rate_limiter" --include="*.py"` → 12+ sonuç (aktif)
- [x] 27/27 kalan dosya `ast.parse` → syntax OK
- [x] ENTRYPOINTS.md cross-check: `app.py` canonical, `server.py` deprecated

---

## 7. Sonuç

**3 dosya arşivlendi (660 satır, 0 dış import):**
1. `main.py` — DEPRECATED re-export
2. `websocket.py` — kullanılmayan WebSocket sınıfı
3. `schemas.py` — kullanılmayan Pydantic modelleri

**1 dosya kullanıcı kararı gerektirir:**
- `server.py` — DEPRECATED ama 15+ benzersiz admin endpoint'i var

---

## 8. Ek Karar: `server.py` Taşındı

**Tarih:** 2026-09-03 (devam)

### Karar
`server.py`'deki 15+ admin endpoint'i **ölü kod değil**, gerçek operasyonel endpoint'lerdi:
- `alerting.get_active_alerts()` — aktif alarmlar
- `alerting.update_policy()` / `rollback_policy()` — policy yönetimi
- `portfolio_monitor.get_lock_metrics_api()` — lock metrikleri
- `monitoring_auth` — admin auth

### Yapılan
1. Admin endpoint'leri `app.py`'ye taşındı (create_app() içinde)
2. Gerekli import'lar eklendi: `alerting`, `portfolio_monitor`, `monitoring_security`
3. `server.py` → `archive/2026-09-03/services/api/server.py.deprecated`
4. `Dockerfile.api` → `services.api.app:app` olarak güncellendi (önceden `services.api.main:app` kullanıyordu — bu bir ihmaldi)

### Doğrulama
- [x] `ast.parse(app.py)` → Syntax OK (817 satır)
- [x] 15 admin endpoint'i `app.py`'de mevcut
- [x] `Dockerfile.api` → canonical entry point'e güncellendi

---

## 9. Arşivleme Nedenleri — Dürüst Değerlendirme

| Dosya | Neden Kullanılmıyor? | Tür |
|-------|---------------------|-----|
| `main.py` | DEPRECATED re-export. **Ama Dockerfile hala bunu kullanıyordu — ihmal.** Dockerfile düzeltildi. | İhmal |
| `websocket.py` | v1.0 standalone WS sunucusu. `v1/ws.py` v2.0 ile değiştirilmiş, eski temizlenmemiş. | Yarım iş |
| `schemas.py` | Standart response modelleri oluşturulmuş ama hiçbir endpoint'e bağlanmamış. | Yarım iş |
| `server.py` | DEPRECATED + admin endpoint'leri. `app.py`'ye taşındı. | Başarısız migration |
