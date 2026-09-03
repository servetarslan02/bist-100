# services/agents/ — Denetim Raporu

---

## SAYFA 1 — Denetim Kuralları

Bu klasördeki tüm `.py` dosyaları aşağıdaki kurallara göre denetlenmiştir.

### K1 — Placeholder Docstring
Aşağıdaki ifadeler placeholder kabul edilir ve düzeltilir:
- `"metod metodu"`, `"__init__ metodu"`, `"X metodu"`
- `"Otomatik eklendi"`
- Sınıf docstring'i ile aynı olan metod docstring'leri
- Anlamsız tek cümlelik docstring'ler ("Değerlendirme raporu." gibi)

**Kural:** Her docstring, o metodun/sınıfın ne yaptığını açıkça tanımlar.

### K2 — Kritik Mantık Hataları
- Boundary hataları (eşik değerlerde yanlış sonuç)
- Yanlış veri kaynağı (features yerine context vb.)
- Eksik filtreleme (hariç tutulması gereken roller dahil ediliyor)
- Circuit breaker / retry bypass
- Dead code (hiç çalışmayan kod parçaları)

### K3 — Eksik Fonksiyonellik
- Eksik parametreler (context, exclude_roles vb.)
- Eksik loglama (veto, error, warning)
- Eksik enum/seviye sınıflandırması
- Eksik fallback mekanizmaları

### K4 — Güvenlik ve Dayanıklılık
- Güvensiz dict erişimi (`data["key"]` yerine `data.get("key")`)
- Exception handling eksikliği
- Gereksiz exception yakalama
- Regex sınırlamaları

### K5 — Kod Kalitesi
- `__repr__` eksik (dataclass'lar için zorunlu)
- Gereksiz import'lar
- Return type annotation eksik
- Değişken gölgeleme
- Task ID collision riski

### Düzeltme Standartları
- Tüm docstring'ler Türkçe ve açıklayıcı
- Mock/statik veri kabul edilmez — production-grade
- `__repr__` tüm dataclass'lara eklenir
- Return type'lar doğru (`Any` yerine gerçek tip)
- Gereksiz import'lar kaldırılır
- Düzeltme sonrası syntax kontrolü yapılır
- Import zinciri kontrolü yapılır (caller dosyalar güncellenir)

---

## SAYFA 2 — Genel Bakış

**Tarih:** 2026-09-04  
**Kapsam:** `services/agents/` — 16 `.py` dosyası  
**Denetim Sonucu:** 61 sorun tespit edildi, 61 düzeltildi

### Dosya Özeti

| # | Dosya | Sorun | Durum |
|---|-------|-------|-------|
| 1 | `__init__.py` | 1 | ✅ Düzeltildi |
| 2 | `agent_memory.py` | 0 | ✅ Temiz |
| 3 | `agent_pipeline.py` | 4 | ✅ Düzeltildi |
| 4 | `agent_system.py` | 3 | ✅ Düzeltildi |
| 5 | `circuit_breaker.py` | 0 | ✅ Temiz |
| 6 | `communication_bus.py` | 1 | ✅ Düzeltildi |
| 7 | `conflict_detector.py` | 4 | ✅ Düzeltildi |
| 8 | `debate_engine.py` | 5 | ✅ Düzeltildi |
| 9 | `llm_client.py` | 7 | ✅ Düzeltildi |
| 10 | `parallel_runner.py` | 6 | ✅ Düzeltildi |
| 11 | `risk_assessor.py` | 7 | ✅ Düzeltildi |
| 12 | `self_evaluator.py` | 5 | ✅ Düzeltildi |
| 13 | `synthesis_engine.py` | 8 | ✅ Düzeltildi |
| 14 | `trace_context.py` | 2 | ✅ Düzeltildi |
| 15 | `prompts/__init__.py` | 3 | ✅ Düzeltildi |
| 16 | `schemas/__init__.py` | 5 | ✅ Düzeltildi |

### Kategori Dağılımı

| Kategori | Sayı |
|----------|------|
| Placeholder docstring | 23 |
| Kritik mantık hatası | 5 |
| Eksik fonksiyonellik | 8 |
| Güvenlik ve dayanıklılık | 7 |
| Kod kalitesi | 18 |
| **Toplam** | **61** |

---

## SAYFA 3 — Kritik Mantık Hataları (5 adet)

| # | Dosya | Hata | Etki | Düzeltme |
|---|-------|------|------|----------|
| 1 | `risk_assessor.py` | Risk seviye eşik mantığı boundary hatası (`score=50` → MEDIUM) | Yanlış risk seviyesi | `_determine_risk_level()` static method, `>=` ile doğru eşik |
| 2 | `conflict_detector.py` | `detect_cross_agent_conflicts()` `_EXCLUDE_ROLES` filtresi yok | BULL/BEAR çelişkileri raporlanıyordu | `exclude_roles` parametresi eklendi |
| 3 | `agent_pipeline.py` | `_get_or_create_agents()` unwrapped LLM atıyordu | Circuit breaker bypass | `self._wrapped_llm` kullanılıyor |
| 4 | `communication_bus.py` | `send()` exception fırlatmıyordu | DLQ tamamen işlevsiz | `send()`'e validasyon eklendi |
| 5 | `synthesis_engine.py` | `_analyze_conflicts` `is_unanimous` NEUTRAL sayıyordu | Yanlış consensus | Sadece directional (LONG/SHORT) sayılır |

---

## SAYFA 4 — Eksik Fonksiyonellik (8 adet)

| # | Dosya | Eksik | Eklenen |
|---|-------|-------|---------|
| 1 | `conflict_detector.py` | Confidence-weighted skor | `conf_diff` ağırlıklı skor formülü |
| 2 | `conflict_detector.py` | Severity seviyeleri | `ConflictSeverity` enum (NONE/LOW/MEDIUM/HIGH/CRITICAL) |
| 3 | `risk_assessor.py` | Veto log'u | `logger.warning("Risk VETO applied")` |
| 4 | `risk_assessor.py` | `context` parametresi | `regime` artık context'ten geliyor |
| 5 | `synthesis_engine.py` | LLM synthesis'e context | `context=full_context` parametresi |
| 6 | `self_evaluator.py` | NO_TRADE outcomes | `"no_trade"` kategorisi dağılımda |
| 7 | `trace_context.py` | `_phase_var` exit'te sıfırlanmıyordu | `__enter__`'a kayıt eklendi |
| 8 | `prompts/__init__.py` | `register_template` validasyon | Format string sözdizimi kontrolü |

---

## SAYFA 5 — Güvenlik ve Dayanıklılık (7 adet)

| # | Dosya | Sorun | Düzeltme |
|---|-------|-------|----------|
| 1 | `llm_client.py` | `OpenAILLMClient` `data["choices"][0]` güvenliksiz | `.get()` + boş kontrolü |
| 2 | `llm_client.py` | `AnthropicLLMClient` `data["content"][0]` güvenliksiz | `.get()` + boş kontrolü |
| 3 | `llm_client.py` | `parse_llm_json` her hatada ERROR log | DEBUG seviyesine düşürüldü |
| 4 | `llm_client.py` | `parse_llm_json` regex 2 seviye limit | `_find_json_object()` brace counting |
| 5 | `debate_engine.py` | LLM hata yönetimi yok | try/except + NO_TRADE fallback |
| 6 | `debate_engine.py` | Hiç tur tamamlanamadı | Boş history → NO_TRADE |
| 7 | `parallel_runner.py` | `_run_one_with_semaphore` gereksiz exception | Kaldırıldı |

---

## SAYFA 6 — Kod Kalitesi (18 adet)

### `__repr__` Eksik (8 adet)
`LLMResponse`, `RiskAssessment`, `EvalReport`, `SynthesisResult`, `ParallelRunResult`, `ParallelAgentRunner`, `AgentPipelineBuilder`, `MultiAgentEvaluator`

### Gereksiz Import (4 adet)
- `orjson` → `prompts/__init__.py`
- `numpy` → `self_evaluator.py` (statistics modülüne geçildi)
- `contextmanager` → `trace_context.py`
- `Dict`, `List`, `Optional` → `schemas/__init__.py`, `prompts/__init__.py`

### Return Type Eksik (3 adet)
- `get_prompts` → `tuple[str, str]`
- `validate_agent_output` → `tuple[bool, dict[str, Any], list[str]]`
- `PromptFactory.get_prompts` → `tuple[str, str]`

### Diğer (3 adet)
- `Direction` docstring yanlış → düzeltildi
- Modül docstring "5 katmanlı" → "6 katmanlı" düzeltildi
- `int(time.time())` task_id → `uuid.uuid4().hex[:8]`

---

## SAYFA 7 — İyileştirmeler

### 7.1 Confidence-Weighted Conflict Score (`conflict_detector.py`)

**Eski:** `min(LONG%, SHORT%) * 2` — sadece oy sayısına bakıyordu  
**Yeni:** Confidence farkını da hesaba katar

```
final_score = base_score * max(0.2, 1.0 - conf_diff)
```

| 2L/2S, 0.8/0.8 | base=1.0 | diff=0.0 | weight=1.0 | **1.00** |
| 2L/2S, 0.9/0.3 | base=1.0 | diff=0.6 | weight=0.4 | **0.40** |
| 3L/1S, 0.7/0.7 | base=0.5 | diff=0.0 | weight=1.0 | **0.50** |
| 3L/1S, 0.9/0.2 | base=0.5 | diff=0.7 | weight=0.3 | **0.15** |

### 7.2 ConflictSeverity Enum (`conflict_detector.py`)

```
NONE     = 0.0
LOW      = 0.0 - 0.3
MEDIUM   = 0.3 - 0.5
HIGH     = 0.5 - 0.8
CRITICAL = 0.8 - 1.0
```

### 7.3 Cümle Sınırında Kesme (`debate_engine.py`)

**Eski:** `reasoning[:150]` → cümle ortasında kesiyordu  
**Yeni:** `_truncate_at_sentence()` → `.`, `!`, `?` sınırında keser

### 7.4 Brace Counting JSON Parser (`llm_client.py`)

**Eski:** Regex → 2 seviye limit  
**Yeni:** `_find_json_object()` → depth counting ile sınırsız derinlik

### 7.5 Risk Seviye Düzeltmesi (`risk_assessor.py`)

**Eski:** `score=50` → MEDIUM (hatalı)  
**Yeni:** `>= 70` CRITICAL, `>= 50` HIGH, `>= 30` MEDIUM, `< 30` LOW

---

## SAYFA 8 — Pipeline Entegrasyon Düzeltmeleri

`agent_pipeline.py`'de yapılan değişiklikler:

| Faz | Değişiklik |
|-----|-----------|
| Agent Cache | `_get_or_create_agents()` → `self._wrapped_llm` kullanıyor |
| Phase 4 (Risk) | `assess()` → `context=full_context` eklendi |
| Phase 6 (Synthesis) | `synthesize()` → `context=full_context` eklendi |
| Fallback | `ConflictReport` → `severity=ConflictSeverity.NONE` eklendi |
| Import | `ConflictSeverity` import edildi |

---

## SAYFA 9 — Bilinen Eksikler

| # | Eksik | Neden Yapılmadı |
|---|-------|-----------------|
| 1 | `AgentOrchestrator` kaldırma | `tests/test_phase7.py` bağımlılığı |
| 2 | Thread safety (memory) | Gerekli değil — tek thread |
| 3 | Prometheus/Grafana metrics | Altyapı gerektirir |
| 4 | Distributed tracing (Jaeger) | Altyapı gerektirir |
| 5 | BULL/BEAR TUR2/TUR3 `{context}` | Tasarım kararı — debate akışında bağlam kasıtlı çıkarılmış |

---

## SAYFA 10 — Dosya Bazlı Detaylar

### `agent_memory.py` ✅ Temiz
TTL, gzip, atomik yazım, O(1) index — hepsi doğru uygulanmış. Sorun bulunmadı.

### `agent_pipeline.py` ⚠️ 4 düzeltme
Wrapped LLM cache, ConflictSeverity import, context parametreleri (risk + synthesis), fallback severity.

### `agent_system.py` ⚠️ 3 düzeltme
Modül docstring "5→6 katmanlı", sınıf docstring "5→6 katmanlı", sınıf docstring "5→7 gösterge".

### `circuit_breaker.py` ✅ Temiz
State makinesi, stats, LLM wrapper — hepsi doğru. Sorun bulunmadı.

### `communication_bus.py` ⚠️ 1 düzeltme
`send()` validasyon eklendi (receiver + task_id). DLQ artık çalışıyor.

### `conflict_detector.py` ⚠️ 4 düzeltme
`_EXCLUDE_ROLES` filtresi, confidence-weighted skor, `ConflictSeverity` enum, `severity` alanı + log.

### `debate_engine.py` ⚠️ 5 düzeltme
`__init__` docstring, `bull_arg`/`bear_arg` → `last_round`, LLM hata yönetimi, boş history fallback, cümle sınırında kesme.

### `llm_client.py` ⚠️ 7 düzeltme
3× placeholder docstring, `BaseLLMClient.__init__` docstring, `parse_llm_json` log seviyesi, OpenAI/Anthropic güvenli parsing, `LLMResponse.__repr__`, `_find_json_object()` brace counting.

### `parallel_runner.py` ⚠️ 6 düzeltme
7× placeholder docstring, gereksiz exception handling, boş `prompt_version`, UUID task_id, `__repr__` metodları, `partial_success` hesabı.

### `risk_assessor.py` ⚠️ 7 düzeltme
Risk seviye boundary hatası, `regime` kaynağı, `to_dict()` docstring, veto log'u, `__repr__`, pozisyon minimum sınırı, `context` parametresi.

### `self_evaluator.py` ⚠️ 5 düzeltme
2× placeholder docstring, `to_dict()` docstring, numpy → statistics, `__repr__`, NO_TRADE kategorisi.

### `synthesis_engine.py` ⚠️ 8 düzeltme
`to_dict()` docstring, `is_unanimous` mantığı, `_llm_synthesize` boş context, `_simple_majority` değişken gölgeleme, `consensus_reached` mantığı, `memory_context` to_dict, `__repr__`, `context` parametresi.

### `trace_context.py` ⚠️ 2 düzeltme
`_phase_var` exit'te sıfırlanmıyordu, gereksiz `contextmanager` import'u.

### `prompts/__init__.py` ⚠️ 3 düzeltme
Gereksiz import'lar, return type, `register_template` validasyon.

### `schemas/__init__.py` ⚠️ 5 düzeltme
4× placeholder docstring, `Direction` docstring, gereksiz import'lar, return type.

### `__init__.py` ⚠️ 1 düzeltme
`ConflictSeverity` export eklendi.
