# services/agents/ — Denetim Raporu

**Tarih:** 2026-09-04  
**Kapsam:** 16 `.py` dosyası  
**Denetim Sonucu:** 61 sorun tespit edildi, 61 düzeltildi

---

## Denetim Kuralları

1. **Mock / Sahte Veri — Kesinlikle Yasak.** Test verisi, hardcoded değer, statik JSON, placeholder data production kodunda olmayacak.
2. **Tüm Hatalar Düzeltilecek.** Boundary hatası, dead code, exception yutma, yanlış veri kaynağı, bypass, tutarsızlık — sistemi bozan her şey düzeltilir.
3. **Eksik Fonksiyonellik Tamamlanacak.** Eksik parametre, eksik loglama, eksik fallback, eksik validasyon tespit edilen her eksik tamamlanır.
4. **Kod Profesyonel Olacak.** Her docstring açıklayıcı ve Türkçe. Her dataclass'ta `__repr__`. Return type annotation doğru. Gereksiz import olmayacak. Değişken isimleri anlamlı olacak.
5. **Düzeltme Sonrası Doğrulama.** Her düzeltme aşağıdaki yöntemlerle doğrulanır:
   - **Syntax:** `ast.parse()` ile sözdizimi kontrolü
   - **Import:** `python3 -c "from services.agents.modul import X"` ile import zinciri kontrolü
   - **Mantık:** Kod okunarak düzeltmenin doğru uygulandığı doğrulanır (boundary, filtre, parametre vb.)
   - **Etki:** Değişen kodun caller dosyalara doğru yansıtıldığı kontrol edilir
6. **Geliştirme Önerileri Verilecek.** Eksik değil ama geliştirilebilecek her alan için öneri sunulacak.

---

## Dosya Özeti

| # | Dosya | Sorun | Durum |
|---|-------|-------|-------|
| 1 | `__init__.py` | 1 | ✅ |
| 2 | `agent_memory.py` | 0 | ✅ Temiz |
| 3 | `agent_pipeline.py` | 4 | ✅ |
| 4 | `agent_system.py` | 3 | ✅ |
| 5 | `circuit_breaker.py` | 0 | ✅ Temiz |
| 6 | `communication_bus.py` | 1 | ✅ |
| 7 | `conflict_detector.py` | 4 | ✅ |
| 8 | `debate_engine.py` | 5 | ✅ |
| 9 | `llm_client.py` | 7 | ✅ |
| 10 | `parallel_runner.py` | 6 | ✅ |
| 11 | `risk_assessor.py` | 7 | ✅ |
| 12 | `self_evaluator.py` | 5 | ✅ |
| 13 | `synthesis_engine.py` | 8 | ✅ |
| 14 | `trace_context.py` | 2 | ✅ |
| 15 | `prompts/__init__.py` | 3 | ✅ |
| 16 | `schemas/__init__.py` | 5 | ✅ |

---

## `__init__.py`

| # | Sorun | Düzeltme |
|---|-------|----------|
| 1 | `ConflictSeverity` export eksik | Import ve `__all__`'a eklendi |

---

## `agent_memory.py`

Sorun bulunmadı. TTL, gzip, atomik yazım, O(1) index, deque(maxlen) — hepsi doğru uygulanmış.

---

## `agent_pipeline.py`

| # | Sorun | Düzeltme |
|---|-------|----------|
| 1 | `_get_or_create_agents()` unwrapped LLM atıyordu — circuit breaker bypass ediliyordu | `self._wrapped_llm` kullanılıyor |
| 2 | `assess()` çağrısına `context` gönderilmiyordu — `regime` feature'dan okunuyordu | `context=full_context` eklendi |
| 3 | `synthesize()` çağrısına `context` gönderilmiyordu — LLM synthesis bağlamdan yoksundu | `context=full_context` eklendi |
| 4 | Fallback `ConflictReport`'ta `severity` eksik | `severity=ConflictSeverity.NONE` eklendi |

---

## `agent_system.py`

| # | Sorun | Düzeltme |
|---|-------|----------|
| 1 | Modül docstring "5 katmanlı" diyor, kodda 6 katman var | "6 katmanlı" |
| 2 | `AIOutputValidator` docstring "5 katmanlı" diyor | "6 katmanlı" |
| 3 | `AIFallback` docstring "5 gösterge" diyor, kodda 7 tane var | "7 gösterge" |

---

## `circuit_breaker.py`

Sorun bulunmadı. State makinesi, stats, LLM wrapper — hepsi doğru.

---

## `communication_bus.py`

| # | Sorun | Düzeltme |
|---|-------|----------|
| 1 | `send()` exception fırlatmıyordu — DLQ tamamen işlevsizdi | `send()`'e receiver ve task_id validasyonu eklendi |

---

## `conflict_detector.py`

| # | Sorun | Düzeltme |
|---|-------|----------|
| 1 | `detect_cross_agent_conflicts()` BULL/BEAR rollerini de dahil ediyordu | `exclude_roles` parametresi eklendi |
| 2 | Conflict score sadece oy sayısına bakıyordu, confidence'ı hesaba katmıyordu | Confidence-weighted skor formülü eklendi |
| 3 | Conflict severity seviyeleri yoktu | `ConflictSeverity` enum eklendi (NONE/LOW/MEDIUM/HIGH/CRITICAL) |
| 4 | `ConflictReport`'ta `severity` alanı eksikti | `severity` alanı ve log eklendi |

---

## `debate_engine.py`

| # | Sorun | Düzeltme |
|---|-------|----------|
| 1 | `__init__` docstring "metod metodu" | Açıklayıcı docstring yazıldı |
| 2 | `bull_arg` ve `bear_arg` aynı objeydi — değişken isimleri yanıltıcı | Tek `last_round` değişkeni |
| 3 | LLM hata yönetimi yoktu — tek tur başarısız olsa tüm debate çöküyordu | try/except + NO_TRADE fallback |
| 4 | Hiç tur tamamlanamadı durumu yoktu | Boş history → NO_TRADE |
| 5 | Reasoning cümle ortasında kesiliyordu | `_truncate_at_sentence()` fonksiyonu eklendi |

---

## `llm_client.py`

| # | Sorun | Düzeltme |
|---|-------|----------|
| 1 | `OllamaLLMClient.chat()` docstring "metod metodu" | "Ollama API ile chat completion" |
| 2 | `OpenAILLMClient.chat()` docstring "metod metodu" | "OpenAI-compatible API ile chat completion" |
| 3 | `AnthropicLLMClient.chat()` docstring "metod metodu" | "Anthropic API ile chat completion" |
| 4 | `OpenAILLMClient` `data["choices"][0]` güvenliksiz — boş choices'ta IndexError | `.get()` + boş kontrolü |
| 5 | `AnthropicLLMClient` `data["content"][0]` güvenliksiz — boş content'te IndexError | `.get()` + boş kontrolü |
| 6 | `parse_llm_json` her JSON parse denemesinde ERROR log + stack trace atıyordu | DEBUG seviyesine düşürüldü |
| 7 | `parse_llm_json` regex sadece 2 seviye iç içe JSON destekliyordu | `_find_json_object()` ile brace counting — sınırsız derinlik |

---

## `parallel_runner.py`

| # | Sorun | Düzeltme |
|---|-------|----------|
| 1 | 7 farklı yerde placeholder docstring ("metod metodu", "all_failed metodu" vb.) | Açıklayıcı docstring'ler yazıldı |
| 2 | `_run_one_with_semaphore` içinde gereksiz `except TimeoutError: raise` bloğu | Kaldırıldı |
| 3 | `_create_timeout_result` ve `_create_error_result` boş `prompt_version` atıyordu | `task.template_name or ""` atandı |
| 4 | `AgentPipelineBuilder.run()` task_id için `int(time.time())` kullanıyordu — aynı saniyede collision riski | `uuid.uuid4().hex[:8]` ile değiştirildi |
| 5 | `__repr__` yoktu (3 sınıf) | `ParallelRunResult`, `ParallelAgentRunner`, `AgentPipelineBuilder` eklendi |
| 6 | `partial_success` property'si eksik total hesabı yapıyordu | `total` değişkeni eklendi |

---

## `risk_assessor.py`

| # | Sorun | Düzeltme |
|---|-------|----------|
| 1 | Risk seviye eşik mantığı boundary hatası — `score=50` MEDIUM oluyordu, HIGH olmalıydı | `_determine_risk_level()` static method ile `>=` doğru eşik |
| 2 | `regime` feature'dan okunuyordu, context'ten gelmeliydi | `context` parametresi eklendi |
| 3 | `to_dict()` docstring sınıf docstring'i ile aynıydı | "Serialization için dict'e çevir" |
| 4 | Veto log'u yoktu — veto olduğunda loglanmıyordu | `logger.warning("Risk VETO applied")` eklendi |
| 5 | `__repr__` yoktu | Eklendi |
| 6 | Pozisyon minimum sınırı HIGH risk'te bile 1% idi | 0.5%'e düşürüldü |
| 7 | `agent_pipeline.py`'deki `assess()` çağrısında `context` parametresi eksikti | `full_context` olarak eklendi |

---

## `self_evaluator.py`

| # | Sorun | Düzeltme |
|---|-------|----------|
| 1 | `AgentSelfEvaluator.__init__` docstring "metod metodu" | Açıklayıcı docstring |
| 2 | `MultiAgentEvaluator.__init__` docstring "__init__ metodu" | Açıklayıcı docstring |
| 3 | `_confidence_stats` basit istatistikler için numpy kullanıyordu — gereksiz overhead | `statistics` modülüne geçildi |
| 4 | `__repr__` yoktu (2 sınıf) | `EvalReport`, `MultiAgentEvaluator` eklendi |
| 5 | `_outcome_distribution` NO_TRADE outcomes saymıyordu | `"no_trade"` kategorisi eklendi |

---

## `synthesis_engine.py`

| # | Sorun | Düzeltme |
|---|-------|----------|
| 1 | `to_dict()` docstring sınıf docstring'i ile aynıydı | "Serialization için dict'e çevir" |
| 2 | `_analyze_conflicts` `is_unanimous` hesabında NEUTRAL'ı da sayıyordu | Sadece directional (LONG/SHORT) sayılır |
| 3 | `_llm_synthesize` boş context gönderiyordu — LLM bağlamdan yoksun sentez yapıyordu | `context` parametresi eklendi |
| 4 | `_simple_majority` içinde değişken gölgeleme (`r` dış scope ile karışıyor) | `r` → `res` |
| 5 | `consensus_reached` mantığı karmaşıktı — `resolution None` iken `True` dönüyordu | Basitleştirildi |
| 6 | `to_dict()` içinde `memory_context` dahil edilmemişti | Eklendi |
| 7 | `__repr__` yoktu | Eklendi |
| 8 | `agent_pipeline.py`'deki `synthesize()` çağrısında `context` parametresi eksikti | `full_context` olarak eklendi |

---

## `trace_context.py`

| # | Sorun | Düzeltme |
|---|-------|----------|
| 1 | `_phase_var` exit'te sıfırlanmıyordu — nested context'te faz sızıntısı oluyordu | `__enter__`'a kayıt eklendi |
| 2 | Gereksiz `contextmanager` import'u | Kaldırıldı |

---

## `prompts/__init__.py`

| # | Sorun | Düzeltme |
|---|-------|----------|
| 1 | Gereksiz import'lar (`orjson`, `Dict`, `List`, `Optional`) | Kaldırıldı |
| 2 | `get_prompts` return type `tuple` idi | `tuple[str, str]` |
| 3 | `register_template` validasyon yoktu — geçersiz format string kaydedilebiliyordu | Format string sözdizimi kontrolü eklendi |

---

## `schemas/__init__.py`

| # | Sorun | Düzeltme |
|---|-------|----------|
| 1 | `RiskLevel` docstring "metod metodu" | "Risk seviyeleri — LOW, MEDIUM, HIGH, CRITICAL" |
| 2 | 3× `validate_confidence` docstring "validate_confidence metodu" | "Confidence değerini 0-1 aralığına normalize et" |
| 3 | `Direction` docstring "Standart agent çıktı şeması" — yanlış | "Yön kararları — LONG, SHORT, NEUTRAL, NO_TRADE" |
| 4 | Gereksiz import'lar (`Dict`, `List`, `Optional`) | Kaldırıldı |
| 5 | `validate_agent_output` return type `tuple` idi | `tuple[bool, dict[str, Any], list[str]]` |

---

## Pipeline Entegrasyon Düzeltmeleri

| Faz | Değişiklik |
|-----|-----------|
| Agent Cache | `_get_or_create_agents()` artık `self._wrapped_llm` kullanıyor |
| Phase 4 (Risk) | `assess()` → `context=full_context` eklendi |
| Phase 6 (Synthesis) | `synthesize()` → `context=full_context` eklendi |
| Fallback | `ConflictReport` → `severity=ConflictSeverity.NONE` eklendi |
| Import | `ConflictSeverity` import edildi |

---

## Geliştirme Önerileri

| # | Alan | Öneri |
|---|------|-------|
| 1 | Observability | Prometheus/Grafana metric'leri eklenebilir — pipeline başarı oranı, latency, circuit breaker durumu |
| 2 | Distributed Tracing | Jaeger/OpenTelemetry entegrasyonu — çoklu servis arası trace takibi |
| 3 | Thread Safety | `AgentMemory` şu an tek thread çalışıyor, çoklu thread gerekirse lock mekanizması eklenebilir |
| 4 | Test Coverage | Mevcut testler refactor sonrası çalışır durumda olmalı, yeni testler yazılmalı |
| 5 | BULL/BEAR Debate | TUR2/TUR3 prompt'larında `{context}` yok — debate'te bağlam kasıtlı çıkarılmış, tasarım kararı olarak kalmış |

---

## Bilinen Eksikler

| # | Eksik | Neden Yapılmadı |
|---|-------|-----------------|
| 1 | `AgentOrchestrator` kaldırma | Test bağımlılığı — test güncellenmeli |
| 2 | Thread safety (memory) | Şu an gerekli değil — tek thread |
