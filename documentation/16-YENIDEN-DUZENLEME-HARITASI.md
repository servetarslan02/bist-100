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

## 5. Yapılacak İşlemler

### Kullanıcı Kararı Gerektiren Durumlar

| # | Bulgu | Seçenekler | Risk |
|---|-------|-----------|------|
| 1 | `services/alternative/` production'da kullanılmıyor | a) Entegre et, b) Arşivle, c) Bırak | Yüksek |
| 2 | Legacy `compute_*` fonksiyonları | a) Migrate et, b) Bırak | Düşük |
| 3 | `satellite.py` legacy | a) `satellite_adapter.py`'ye taşı, b) Bırak | Düşük |

---

## 6. Doğrulama

- [x] Tüm dış importlar grep ile doğrulandı
- [x] Production kod taraması: orchestrator, workers, config — hiçbiri kullanmıyor
- [x] `feature_store` — üç farklı dosya, farklı amaç
- [x] `reconciliation` — dört farklı dosya, farklı amaç
- [x] `satellite` — iki dosya, legacy + modern
- [x] DAG — döngüsellik yok
- [x] Taşıma/silme yapılmadı

---

## 7. Sonuç (services/alternative/)

**Paket iyi yapılandırılmış ama hiçbir üretim kodu tarafından kullanılmıyor.** Kullanıcı kararı gerektirir:
- Alternatif veri aktif kullanılacaksa → entegre et
- Hazır değilse → arşivle
- Sadece test amaçlıysa → bırak
