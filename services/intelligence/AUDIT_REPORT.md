# services/intelligence/ — Denetim Raporu

**Tarih:** 2026-09-13
**Kapsam:** 41 `.py` dosyası
**Denetim Sonucu:** 8 dosya denetlendi, 8 dosyada sorun tespit edildi ve düzeltildi

---

## Denetim Kuralları

1. **Mock / Sahte / Placeholder Veri — Kesinlikle Yasak.** Test verisi, hardcoded değer, statik JSON, placeholder data, 'Otomatik eklendi' docstring, pass ile boş fonksiyon gövdesi — production kodunda yer alamaz.
2. **Kapsamlı Hata, Eşzamanlılık ve Sınır Kontrolleri.** Boundary hataları, dead code, sessiz exception yutma, bypass mekanizmaları düzeltilir. Polars null değerleri, ZeroDivisionError ve NaN/Inf sayısal taşmaları guard altına alınır. Paylaşılan singleton state/bağlantılarda thread-safety (threading.Lock/asyncio.Lock) zorunludur.
3. **Eksiksiz Fonksiyonellik ve Fail-Closed İlkesi.** Eksik parametre, loglama, fallback ve validasyon tamamlanır. Hatalar asla sessizce yutulamaz (except: pass yasak); loglanıp uygun istisna fırlatılır. Tüm parametre ve dönüşlerde eksiksiz type annotation belirtilir.
4. **Profesyonel Kod, Temizlik ve Loglama Mimarisi.** Her docstring açıklayıcı, Türkçe ve Args/Returns/Raises içeren formatta olmalıdır. Her dataclass ve veri modelinde __repr__ metodu bulunur. Fonksiyon içi gereksiz importlar dosya başına taşınır. Web/API katmanında structlog, izole quant/motor katmanlarında standart logging kullanılır. Loglar ve hata mesajları Türkçe olmalıdır. Magic number yerine DEFAULT_* sabitleri kullanılır.
5. **Düzeltme Sonrası Canlı Doğrulama (Smoke/Execution Test).** Yalnızca syntax veya import yetmez; dosyanın ana fonksiyonlarını fiilen çalıştıran mikro test (uv run python -c '...' veya pytest) ve ruff check ile doğruluk kanıtlanmalıdır.
6. **Geliştirme Önerileri ve Proaktif İyileştirme.** Hata olmasa dahi performans, bellek, Polars optimizasyonu veya mimari açıdan sistemi iyileştirebilecek potansiyel alanlar raporlanmalı ve faydalı olanlar sisteme kazandırılmalıdır.
7. **Mimari Tutarlılık, Modül Dışa Aktarımı ve Göç (Migration) Takibi.** Modül seviyesinde __all__ listesi eksiksiz ve güncel olmalıdır. İsim/imza değişikliklerinde tüm repo taranıp çağıran noktalar güncellenmeli ve audit raporuna Migration tablosu eklenmelidir.

---

## Dosya Özeti

| # | Dosya | Sorun | Durum |
|---|-------|-------|-------|
| 1 | `__init__.py` | __all__ eksik modüller (analysis_engines, candle_patterns, dynamic_candle_matrix) | ✅ Düzeltildi |
| 2 | `analysis_engines.py` | 8 sorun: magic numbers, dead code, eksik __repr__, __all__, docstring | ✅ Düzeltildi |
| 3 | `candle_patterns.py` | 8 sorun: "Otomatik eklendi", dead code (c3), fail-closed, magic numbers, __repr__, __all__ | ✅ Düzeltildi |
| 4 | `confidence_calibrator.py` | 5 sorun: "Otomatik eklendi", magic numbers, __repr__, docstring, __all__ | ✅ Düzeltildi |
| 5 | `dynamic_candle_matrix.py` | 6 sorun: "Otomatik eklendi", magic numbers, __repr__, docstring, __all__, eksik kolon kontrolü | ✅ Düzeltildi |
| 6 | `ensemble_forecast.py` | 7 sorun: "Otomatik eklendi", sessiz exception, magic numbers, __repr__, docstring, __all__, guard eksik | ✅ Düzeltildi |
| 7 | `evidence_engine.py` | 8 sorun: "Otomatik eklendi" ×3, stub placeholder, mutable default, sessiz exception, magic numbers, __repr__, __all__ | ✅ Düzeltildi |
| 8 | `factor_engine.py` | 5 sorun: magic numbers, __repr__, docstring, __all__, sessiz ImportError | ✅ Düzeltildi |
| 9 | `forecasting.py` | — | ⏳ Bekliyor |
| 10 | `forecasting_utils.py` | — | ⏳ Bekliyor |
| 11 | `gemini_service.py` | — | ⏳ Bekliyor |
| 12 | `hmm_regime.py` | — | ⏳ Bekliyor |
| 13 | `impact_engine.py` | — | ⏳ Bekliyor |
| 14 | `kap_extractor.py` | — | ⏳ Bekliyor |
| 15 | `kap_llm_extractor.py` | — | ⏳ Bekliyor |
| 16 | `knowledge_graph.py` | — | ⏳ Bekliyor |
| 17 | `llm_agent.py` | — | ⏳ Bekliyor |
| 18 | `llm_client.py` | — | ⏳ Bekliyor |
| 19 | `llm_context_builder.py` | — | ⏳ Bekliyor |
| 20 | `llm_tools.py` | — | ⏳ Bekliyor |
| 21 | `macro_sensitivity.py` | — | ⏳ Bekliyor |
| 22 | `main.py` | — | ⏳ Bekliyor |
| 23 | `ml_signal_fusion.py` | — | ⏳ Bekliyor |
| 24 | `monte_carlo.py` | — | ⏳ Bekliyor |
| 25 | `news_pipeline.py` | — | ⏳ Bekliyor |
| 26 | `parallel_pipeline.py` | — | ⏳ Bekliyor |
| 27 | `pipeline.py` | — | ⏳ Bekliyor |
| 28 | `prediction_layer.py` | — | ⏳ Bekliyor |
| 29 | `probability.py` | — | ⏳ Bekliyor |
| 30 | `regime.py` | — | ⏳ Bekliyor |
| 31 | `research_memory.py` | — | ⏳ Bekliyor |
| 32 | `scenario.py` | — | ⏳ Bekliyor |
| 33 | `signal_fusion.py` | — | ⏳ Bekliyor |
| 34 | `spec_engine.py` | — | ⏳ Bekliyor |
| 35 | `trade_planner.py` | — | ⏳ Bekliyor |
| 36 | `trend_rider.py` | — | ⏳ Bekliyor |
| 37 | `valuation/__init__.py` | — | ⏳ Bekliyor |
| 38 | `valuation/engine.py` | — | ⏳ Bekliyor |
| 39 | `vector_memory.py` | — | ⏳ Bekliyor |
| 40 | `world_state.py` | — | ⏳ Bekliyor |

---

## `__init__.py`

| # | Sorun | Düzeltme |
|---|-------|----------|
| 1 | `__all__` ve importlarda 9 modül eksik (analysis_engines, candle_patterns, dynamic_candle_matrix) | Import ve `__all__` listesine eklendi |

---

## `analysis_engines.py`

| # | Sorun | Düzeltme |
|---|-------|----------|
| 1 | `1.65` VaR z-score magic number | `DEFAULT_VAR_CONFIDENCE_Z` sabiti |
| 2 | `0.30/0.30/0.20/0.20` ağırlık magic number | `DEFAULT_DATA_CONFIDENCE_WEIGHTS` sabiti |
| 3 | `0.99/1.01` breakout toleransı | `BREAKOUT_TOLERANCE` / `BREAKDOWN_TOLERANCE` |
| 4 | `np.std(errors)` hesaplanıp kullanılmıyor — dead code | Kaldırıldı |
| 5 | `logger` import edilmiş ama hiç kullanılmıyor | Tüm fonksiyonlarda aktif kullanıma alındı |
| 6 | `__repr__` metodu yok (10 class) | Tüm classlara eklendi |
| 7 | Docstringler tek satır, Args/Returns/Raises yok | Genişletildi |
| 8 | `__all__` eksik | Eklendi |
| 9 | Sessiz `{}` dönüşleri (fail-closed değil) | Kritik hatalarda `ValueError` raise edildi |
| 10 | Type annotation eksik | Tamamlandı |

---

## `candle_patterns.py`

| # | Sorun | Düzeltme |
|---|-------|----------|
| 1 | `"Otomatik eklendi"` docstring × 2 (__post_init__, __init__) | Anlamlı Türkçe docstring |
| 2 | `c3` oluşturulmuş ama hiç kullanılmıyor — dead code | Kaldırıldı |
| 3 | Eksik kolon sessizce boş result döndürüyor | `ValueError` raise edildi |
| 4 | 30+ magic number (0.08, 1e-9, 0.50, 0.20, 3.5, 1.5 vb.) | `UPPER_CASE` sabitlere dönüştürüldü |
| 5 | `__repr__` yok (3 class) | Eklendi |
| 6 | Docstringler tek satır | Args/Returns/Raises ile genişletildi |
| 7 | `logger` hiç kullanılmıyor | Analiz sonucu loglandı |
| 8 | `__all__` eksik | Eklendi |

---

## `confidence_calibrator.py`

| # | Sorun | Düzeltme |
|---|-------|----------|
| 1 | `"Otomatik eklendi"` docstring | Anlamlı Türkçe docstring |
| 2 | Magic numbers: `10000`, `0.1`, `0.2`, `0.3`, `0.7`, `0.85`, `0.9` | `MAX_OBSERVATIONS`, `OVERCONFIDENCE_THRESHOLD`, `ADJUSTMENT_*` sabitleri |
| 3 | `__repr__` yok (4 class) | Eklendi |
| 4 | Docstringler tek satır | Args/Returns/Raises ile genişletildi |
| 5 | `__all__` eksik | Eklendi |

---

## `dynamic_candle_matrix.py`

| # | Sorun | Düzeltme |
|---|-------|----------|
| 1 | `"Otomatik eklendi"` docstring | Anlamlı Türkçe docstring |
| 2 | Magic numbers: `252`, `15`, `20`, `5`, `50.0`, `3`, `1e-9`, `2.5`, `5.0`, `2.0`, `-0.5`, `45.0` | `DEFAULT_*` sabitleri |
| 3 | `__repr__` yok (2 class) | Eklendi |
| 4 | Docstringler eksik | Args/Returns/Raises ile genişletildi |
| 5 | `__all__` eksik | Eklendi |
| 6 | Eksik kolon kontrolü yok | `ValueError` raise edildi |

---

## `ensemble_forecast.py`

| # | Sorun | Düzeltme |
|---|-------|----------|
| 1 | `"Otomatik eklendi"` docstring | Anlamlı Türkçe docstring |
| 2 | `except Exception` → `logger.debug` (sessiz yutma) | `logger.warning` seviyesine yükseltildi |
| 3 | Magic numbers: `0.3`, `0.5`, `0.001`, `4`, `0.9`, `70`, `30`, `20`, `15` | `DEFAULT_*` sabitleri |
| 4 | `__repr__` yok (3 class) | Eklendi |
| 5 | Docstringler eksik | Args/Returns/Raises ile genişletildi |
| 6 | `__all__` eksik | Eklendi |
| 7 | `total_w == 0` guard yok | Eşit ağırlık fallback eklendi |

---

## `evidence_engine.py`

| # | Sorun | Düzeltme |
|---|-------|----------|
| 1 | `"Otomatik eklendi"` docstring × 3 (enum class) | Anlamlı Türkçe docstring |
| 2 | `detect_hallucination`: boş `issues = []` + `pass` — stub/placeholder | Tam implementasyon: ticker, fiyat, tarih, KAP kontrolü |
| 3 | `verify_claim`: mutable default args | `None` ile varsayılan, body'de atama |
| 4 | `except Exception` sessiz timestamp hatası | `except (ValueError, TypeError)` + `logger.warning` |
| 5 | Cross-check hardcoded `True` — işlevsiz | `supporting.append` ile kanıt ekleme |
| 6 | Magic numbers: `50`, `70`, `40`, `20`, `25`, `15`, `10`, `5`, `-5`, `-10`, `30` | `DEFAULT_*` sabitleri + `_TYPE_BONUS` / `_SOURCE_BONUS` dict |
| 7 | `__repr__` yok (6 class) | Eklendi |
| 8 | `__all__` eksik | Eklendi |

---

## `factor_engine.py`

| # | Sorun | Düzeltme |
|---|-------|----------|
| 1 | Magic numbers: `50`, `100`, `25`, `15`, `5`, `20`, `10`, `3`, `8`, `0.6`, `0.8`, `1.2`, `1.5`, `30e9`, `80`, `65`, `35`, `40` | `DEFAULT_*` ve eşik sabitleri |
| 2 | `__repr__` yok (3 class) | Eklendi |
| 3 | `_compute_*` docstringleri tek satır | Args/Returns ile genişletildi |
| 4 | `__all__` eksik | Eklendi |
| 5 | `except ImportError` → `logger.debug` (sessiz) | `logger.warning` seviyesine yükseltildi |

---

## Geliştirme Önerileri

| # | Alan | Öneri |
|---|------|-------|
| 1 | Bağımlılık Yönetimi | `__init__.py` zincirleme import yerine lazy import düşünülebilir (startup hızı) |
| 2 | Singleton Pattern | Singletonlar yerine dependency injection daha test edilebilir olur |
| 3 | Test Altyapısı | Her modül için izole `pytest` test dosyası oluşturulmalı |

---

## Bilinen Eksikler

| # | Eksik | Neden Yapılmadı |
|---|-------|-----------------|
| 1 | 33 dosya henüz denetlenmedi | Sıra ile elle devam ediliyor (toplu iş yasak) |
| 2 | Full entegrasyon testi | `services.core` ve `services.ml` bağımlılıkları eksik (duckdb, yfinance, sklearn vb.) |
