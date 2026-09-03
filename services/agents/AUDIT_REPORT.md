# services/agents/ — Denetim Raporu

---

## SAYFA 1 — Denetim Kuralları

### K1 — Placeholder Docstring
`"metod metodu"`, `"__init__ metodu"`, `"X metodu"`, `"Otomatik eklendi"`, sınıf docstring'i ile aynı olan metod docstring'leri → düzeltilir.

### K2 — Kritik Mantık Hataları
Boundary hataları, yanlış veri kaynağı, eksik filtreleme, dead code → düzeltilir.

### K3 — Eksik Fonksiyonellik
Eksik parametreler, eksik loglama, eksik fallback → düzeltilir.

### K4 — Güvenlik ve Dayanıklılık
Güvensiz dict erişimi, exception handling eksikliği, regex sınırlamaları → düzeltilir.

### K5 — Kod Kalitesi
`__repr__` eksik, gereksiz import, return type eksik, değişken gölgeleme → düzeltilir.

### Düzeltme Standartları
- Docstring'ler Türkçe ve açıklayıcı
- Production-grade, mock/statik veri yok
- `__repr__` tüm dataclass'lara
- Return type'lar doğru
- Düzeltme sonrası syntax + import zinciri kontrolü

---

## SAYFA 2 — `__init__.py`

**Sorun:** 1 | **Durum:** ✅ Düzeltildi

| # | Kategori | Sorun | Düzeltme |
|---|----------|-------|----------|
| 1 | K3 | `ConflictSeverity` export eksik | Import ve `__all__`'a eklendi |

---

## SAYFA 3 — `agent_memory.py`

**Sorun:** 0 | **Durum:** ✅ Temiz

TTL, gzip, atomik yazım, O(1) index, deque(maxlen) — hepsi doğru uygulanmış. Sorun bulunmadı.

---

## SAYFA 4 — `agent_pipeline.py`

**Sorun:** 4 | **Durum:** ✅ Düzeltildi

| # | Kategori | Sorun | Düzeltme |
|---|----------|-------|----------|
| 1 | K2 | `_get_or_create_agents()` unwrapped LLM atıyordu — circuit breaker bypass | `self._wrapped_llm` kullanılıyor |
| 2 | K3 | `assess()` çağrısına `context` gönderilmiyordu | `context=full_context` eklendi |
| 3 | K3 | `synthesize()` çağrısına `context` gönderilmiyordu | `context=full_context` eklendi |
| 4 | K3 | Fallback `ConflictReport`'ta `severity` eksik | `severity=ConflictSeverity.NONE` eklendi |

---

## SAYFA 5 — `agent_system.py`

**Sorun:** 3 | **Durum:** ✅ Düzeltildi

| # | Kategori | Sorun | Düzeltme |
|---|----------|-------|----------|
| 1 | K1 | Modül docstring "5 katmanlı" (6 tane var) | "6 katmanlı" |
| 2 | K1 | `AIOutputValidator` docstring "5 katmanlı" | "6 katmanlı" |
| 3 | K1 | `AIFallback` docstring "5 gösterge" (7 tane var) | "7 gösterge" |

---

## SAYFA 6 — `circuit_breaker.py`

**Sorun:** 0 | **Durum:** ✅ Temiz

State makinesi, stats, LLM wrapper — hepsi doğru. Sorun bulunmadı.

---

## SAYFA 7 — `communication_bus.py`

**Sorun:** 1 | **Durum:** ✅ Düzeltildi

| # | Kategori | Sorun | Düzeltme |
|---|----------|-------|----------|
| 1 | K2 | `send()` exception fırlatmıyordu — DLQ tamamen işlevsiz | `send()`'e receiver + task_id validasyonu eklendi |

---

## SAYFA 8 — `conflict_detector.py`

**Sorun:** 4 | **Durum:** ✅ Düzeltildi

| # | Kategori | Sorun | Düzeltme |
|---|----------|-------|----------|
| 1 | K2 | `detect_cross_agent_conflicts()` `_EXCLUDE_ROLES` filtresi yok — BULL/BEAR çelişkileri raporlanıyordu | `exclude_roles` parametresi eklendi |
| 2 | K3 | Confidence-weighted skor yok — sadece oy sayısına bakıyordu | `conf_diff` ağırlıklı skor formülü eklendi |
| 3 | K3 | Conflict severity seviyeleri yok | `ConflictSeverity` enum eklendi (NONE/LOW/MEDIUM/HIGH/CRITICAL) |
| 4 | K3 | `ConflictReport`'ta `severity` alanı eksik | `severity` alanı + log eklendi |

---

## SAYFA 9 — `debate_engine.py`

**Sorun:** 5 | **Durum:** ✅ Düzeltildi

| # | Kategori | Sorun | Düzeltme |
|---|----------|-------|----------|
| 1 | K1 | `__init__` docstring "metod metodu" | Açıklayıcı docstring |
| 2 | K2 | `bull_arg` ve `bear_arg` aynı obje — yanıltıcı | Tek `last_round` değişkeni |
| 3 | K3 | LLM hata yönetimi yok — tüm debate çöker | try/except + NO_TRADE fallback |
| 4 | K3 | Hiç tur tamamlanamadı durumu yok | Boş history → NO_TRADE |
| 5 | K4 | Reasoning cümle ortasında kesiliyor | `_truncate_at_sentence()` fonksiyonu |

---

## SAYFA 10 — `llm_client.py`

**Sorun:** 7 | **Durum:** ✅ Düzeltildi

| # | Kategori | Sorun | Düzeltme |
|---|----------|-------|----------|
| 1 | K1 | `OllamaLLMClient.chat()` docstring "metod metodu" | "Ollama API ile chat completion" |
| 2 | K1 | `OpenAILLMClient.chat()` docstring "metod metodu" | "OpenAI-compatible API ile chat completion" |
| 3 | K1 | `AnthropicLLMClient.chat()` docstring "metod metodu" | "Anthropic API ile chat completion" |
| 4 | K4 | `OpenAILLMClient` `data["choices"][0]` güvenliksiz — IndexError | `.get()` + boş kontrolü |
| 5 | K4 | `AnthropicLLMClient` `data["content"][0]` güvenliksiz — IndexError | `.get()` + boş kontrolü |
| 6 | K4 | `parse_llm_json` her hatada ERROR log + stack trace | DEBUG seviyesine düşürüldü |
| 7 | K4 | `parse_llm_json` regex 2 seviye JSON limit | `_find_json_object()` brace counting |

---

## SAYFA 11 — `parallel_runner.py`

**Sorun:** 6 | **Durum:** ✅ Düzeltildi

| # | Kategori | Sorun | Düzeltme |
|---|----------|-------|----------|
| 1 | K1 | 7× placeholder docstring | Açıklayıcı docstring'ler |
| 2 | K2 | `_run_one_with_semaphore` gereksiz `except TimeoutError: raise` | Kaldırıldı |
| 3 | K3 | `_create_timeout_result` / `_create_error_result` boş `prompt_version` | `task.template_name or ""` atandı |
| 4 | K5 | `AgentPipelineBuilder.run()` task_id `int(time.time())` — collision riski | `uuid.uuid4().hex[:8]` |
| 5 | K5 | `__repr__` yok (3 sınıf) | `ParallelRunResult`, `ParallelAgentRunner`, `AgentPipelineBuilder` eklendi |
| 6 | K5 | `partial_success` property — eksik total hesabı | `total` değişkeni eklendi |

---

## SAYFA 12 — `risk_assessor.py`

**Sorun:** 7 | **Durum:** ✅ Düzeltildi

| # | Kategori | Sorun | Düzeltme |
|---|----------|-------|----------|
| 1 | K2 | Risk seviye eşik mantığı boundary hatası (`score=50` → MEDIUM, HIGH olmalı) | `_determine_risk_level()` static method, `>=` ile doğru eşik |
| 2 | K2 | `features.get("regime")` — yanlış kaynak | `context` parametresi eklendi, `(context or {}).get("regime")` |
| 3 | K1 | `to_dict()` docstring "Risk değerlendirme sonucu" | "Serialization için dict'e çevir" |
| 4 | K3 | Veto log'u yok | `logger.warning("Risk VETO applied")` eklendi |
| 5 | K5 | `__repr__` yok | Eklendi |
| 6 | K5 | Pozisyon minimum 1% (HIGH'ta bile) | 0.5%'e düşürüldü |
| 7 | K3 | `agent_pipeline.py`'de `context` parametresi eksik | `full_context` olarak eklendi |

---

## SAYFA 13 — `self_evaluator.py`

**Sorun:** 5 | **Durum:** ✅ Düzeltildi

| # | Kategori | Sorun | Düzeltme |
|---|----------|-------|----------|
| 1 | K1 | `AgentSelfEvaluator.__init__` docstring "metod metodu" | Açıklayıcı docstring |
| 2 | K1 | `MultiAgentEvaluator.__init__` docstring "__init__ metodu" | Açıklayıcı docstring |
| 3 | K4 | `_confidence_stats` — basit istatistikler için numpy aşırı | `statistics` modülüne geçildi |
| 4 | K5 | `__repr__` yok (2 sınıf) | `EvalReport`, `MultiAgentEvaluator` eklendi |
| 5 | K3 | `_outcome_distribution` — NO_TRADE outcomes sayılmıyor | `"no_trade"` kategorisi eklendi |

---

## SAYFA 14 — `synthesis_engine.py`

**Sorun:** 8 | **Durum:** ✅ Düzeltildi

| # | Kategori | Sorun | Düzeltme |
|---|----------|-------|----------|
| 1 | K1 | `to_dict()` docstring "Sentez sonucu" | "Serialization için dict'e çevir" |
| 2 | K2 | `_analyze_conflicts` `is_unanimous` NEUTRAL sayıyordu | Sadece directional (LONG/SHORT) sayılır |
| 3 | K3 | `_llm_synthesize` boş context gönderiyordu | `context` parametresi eklendi |
| 4 | K5 | `_simple_majority` değişken gölgeleme (`r`) | `r` → `res` |
| 5 | K2 | `consensus_reached` mantığı karmaşık | Basitleştirildi |
| 6 | K3 | `to_dict()` eksik `memory_context` | Eklendi |
| 7 | K5 | `__repr__` yok | Eklendi |
| 8 | K3 | `agent_pipeline.py`'de `context` parametresi eksik | `full_context` olarak eklendi |

---

## SAYFA 15 — `trace_context.py`

**Sorun:** 2 | **Durum:** ✅ Düzeltildi

| # | Kategori | Sorun | Düzeltme |
|---|----------|-------|----------|
| 1 | K2 | `_phase_var` exit'te sıfırlanmıyordu — nested context'te faz sızıntısı | `__enter__`'a kayıt eklendi |
| 2 | K5 | Gereksiz `contextmanager` import'u | Kaldırıldı |

---

## SAYFA 16 — `prompts/__init__.py`

**Sorun:** 3 | **Durum:** ✅ Düzeltildi

| # | Kategori | Sorun | Düzeltme |
|---|----------|-------|----------|
| 1 | K5 | Gereksiz import'lar (`orjson`, `Dict`, `List`, `Optional`) | Kaldırıldı |
| 2 | K5 | `get_prompts` return type `tuple` | `tuple[str, str]` |
| 3 | K3 | `register_template` validasyon yok | Format string sözdizimi kontrolü eklendi |

---

## SAYFA 17 — `schemas/__init__.py`

**Sorun:** 5 | **Durum:** ✅ Düzeltildi

| # | Kategori | Sorun | Düzeltme |
|---|----------|-------|----------|
| 1 | K1 | `RiskLevel` docstring "metod metodu" | "Risk seviyeleri — LOW, MEDIUM, HIGH, CRITICAL" |
| 2 | K1 | 3× `validate_confidence` docstring "validate_confidence metodu" | "Confidence değerini 0-1 aralığına normalize et" |
| 3 | K1 | `Direction` docstring "Standart agent çıktı şeması" | "Yön kararları — LONG, SHORT, NEUTRAL, NO_TRADE" |
| 4 | K5 | Gereksiz import'lar (`Dict`, `List`, `Optional`) | Kaldırıldı |
| 5 | K5 | `validate_agent_output` return type `tuple` | `tuple[bool, dict[str, Any], list[str]]` |

---

## SAYFA 18 — Bilinen Eksikler

| # | Eksik | Neden Yapılmadı |
|---|-------|-----------------|
| 1 | `AgentOrchestrator` kaldırma | `tests/test_phase7.py` bağımlılığı |
| 2 | Thread safety (memory) | Gerekli değil — tek thread |
| 3 | Prometheus/Grafana metrics | Altyapı gerektirir |
| 4 | Distributed tracing (Jaeger) | Altyapı gerektirir |
| 5 | BULL/BEAR TUR2/TUR3 `{context}` | Tasarım kararı |
