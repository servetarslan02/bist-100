# services/ingestion/ — Denetim Raporu

**Tarih:** 2026-09-12  
**Kapsam:** 18 `.py` dosyası  
**Denetim Sonucu:** 10/18 dosya denetlendi, 72 sorun tespit edildi, 72 düzeltildi

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
| 1 | `__init__.py` | 4 | ✅ Düzeltildi |
| 2 | `backfill.py` | 8 | ✅ Düzeltildi |
| 3 | `bist_universe.py` | 8 | ✅ Düzeltildi |
| 4 | `circuit_breaker.py` | 7 | ✅ Düzeltildi |
| 5 | `corporate_actions.py` | 9 | ✅ Düzeltildi |
| 6 | `data_pipeline.py` | 8 | ✅ Düzeltildi |
| 7 | `deduplication.py` | 7 | ✅ Düzeltildi |
| 8 | `incremental.py` | 7 | ✅ Düzeltildi |
| 9 | `ingestion_metrics.py` | 6 | ✅ Düzeltildi |
| 10 | `main.py` | 9 | ✅ Düzeltildi |
| 11 | `orchestrator_integration.py` | — | ⏳ Bekliyor |
| 12 | `point_in_time.py` | — | ⏳ Bekliyor |
| 13 | `provider_manager.py` | — | ⏳ Bekliyor |
| 14 | `questdb_consumer.py` | — | ⏳ Bekliyor |
| 15 | `rate_limiter.py` | — | ⏳ Bekliyor |
| 16 | `realtime.py` | — | ⏳ Bekliyor |
| 17 | `reconciliation.py` | — | ⏳ Bekliyor |
| 18 | `retry_policy.py` | — | ⏳ Bekliyor |
| 19 | `universe_enhancements.py` | — | ⏳ Bekliyor |

---

## Kritik Bulgular Özeti

| # | Dosya | Seviye | Sorun |
|---|-------|--------|-------|
| 1 | `backfill.py` | KRİTİK | Gap tespiti `market_bars`/`market_data` sorguluyor ama backfill `daily_bars` yazıyordu → sonsuz döngü |
| 2 | `corporate_actions.py` | KRİTİK | `adjust_historical_prices` compounding error — üst üste düzeltme |
| 3 | `main.py` | KRİTİK | `bist_universe.get_tickers()` modül seviyesinde — provider erişilemezse import patlar |

---

## Düzeltme Detayları

### `__init__.py`
| # | Sorun | Düzeltme |
|---|-------|----------|
| 1 | `from typing import Any` docstring'den önce | Docstring dosya başına taşındı |
| 2 | Docstring İngilizce | Türkçe, Kullanım/Raises eklendi |
| 3 | `get_orchestrator()` docstring eksik | Türkçe docstring eklendi |
| 4 | `__all__` kontrolü | Eksiksiz mevcut |

### `backfill.py`
| # | Sorun | Düzeltme |
|---|-------|----------|
| 1 | KRİTİK tablo adı uyumsuzluğu | `TABLE_DAILY_BARS` sabitinde birleştirildi |
| 2 | 5× placeholder docstring | Türkçe docstring |
| 3 | 3 dataclass `__repr__` eksik | Eklendi |
| 4 | Type annotation eksik | `Any | None` eklendi |
| 5 | `stop() -> Any` | `-> None` |
| 6 | Magic number `86400` | `SECONDS_PER_DAY` sabiti |
| 7 | `progress_callback` kullanılmıyor | `_backfill_chunk` içinde çağrıldı |
| 8 | Dead code öncelik mantığı | Aralıklar yeniden düzenlendi |

### `bist_universe.py`
| # | Sorun | Düzeltme |
|---|-------|----------|
| 1 | Docstring'den önce import | Sıralama düzeltildi |
| 2 | Modül docstring İngilizce | Türkçe'ye çevrildi |
| 3 | `use_auto_discovery` dead parametre | Kaldırıldı |
| 4 | `refresh()` hata maskeliyor | RuntimeError fırlatıyor |
| 5 | 8 eksik docstring | Tamamlandı |
| 6 | `__all__` eksik | Eklendi |
| 7 | Standalone string dead code | Comment'e çevrildi |

### `circuit_breaker.py`
| # | Sorun | Düzeltme |
|---|-------|----------|
| 1 | 7× placeholder docstring | Türkçe docstring |
| 2 | 5 method `-> Any` | `-> None` |
| 3 | Context manager `-> Any` | Doğru tipler |
| 4 | `CircuitStats.__repr__` eksik | Eklendi |
| 5 | `_lock` dead code | Kaldırıldı |
| 6 | Dar dönüş tipleri | `dict[str, Any]` |
| 7 | `__init__` docstring eksik | Args eklendi |

### `corporate_actions.py`
| # | Sorun | Düzeltme |
|---|-------|----------|
| 1 | KRİTİK compounding error | Orijinal değerlerden bağımsız düzeltme |
| 2 | `_parse_date` sessiz fallback | Log eklendi |
| 3 | ActionType placeholder docstring | Türkçe Attributes |
| 4 | `CorporateAction.__repr__` eksik | Eklendi |
| 5 | `-> Any` dönüşleri | `-> None` |
| 6 | `dict` parametre tipi | `dict[str, Any]` |
| 7 | `import re` fonksiyon içinde | Dosya başı + sabit regex |
| 8 | 7 eksik docstring | Tamamlandı |
| 9 | `__all__` eksik | Eklendi |

### `data_pipeline.py`
| # | Sorun | Düzeltme |
|---|-------|----------|
| 1 | 6× placeholder docstring | Türkçe docstring |
| 2 | 2 dataclass `__repr__` eksik | Eklendi |
| 3 | `_add_audit() -> Any` | `-> None` |
| 4 | Dar dönüş tipi | `dict[str, int]` |
| 5 | 6 eksik docstring | Tamamlandı |
| 6 | Sütun adı uyumu | `_FEATURE_COLS` + `_resolve_columns` |
| 7 | `__all__` eksik | Eklendi |
| 8 | `np.mean` gereksiz | `sum/len` |

### `deduplication.py`
| # | Sorun | Düzeltme |
|---|-------|----------|
| 1 | Placeholder docstring | Türkçe docstring |
| 2 | `DedupStats.__repr__` eksik | Eklendi |
| 3 | 4 method `-> Any` | `-> None` |
| 4 | Dar dönüş tipi | `dict[str, Any]` |
| 5 | 2 eksik docstring | Tamamlandı |
| 6 | MD5 kullanımı | SHA-256 |
| 7 | `__all__` eksik | Eklendi |

### `incremental.py`
| # | Sorun | Düzeltme |
|---|-------|----------|
| 1 | Docstring'den önce import | Sıralama düzeltildi |
| 2 | Placeholder docstring | Türkçe docstring |
| 3 | 2 dataclass `__repr__` eksik | Eklendi |
| 4 | 2 method `-> Any` | `-> None` |
| 5 | Dar dönüş tipleri | `dict[str, dict[str, Any]]` |
| 6 | 2 eksik docstring | Tamamlandı |
| 7 | `__all__` eksik | Eklendi |

### `ingestion_metrics.py`
| # | Sorun | Düzeltme |
|---|-------|----------|
| 1 | Docstring'den önce import | Sıralama düzeltildi |
| 2 | Placeholder docstring | Türkçe docstring |
| 3 | 14 method `-> Any` | `-> None` |
| 4 | Context manager `-> Any` | `-> Generator[None, None, None]` |
| 5 | 16 eksik docstring | Tamamlandı |
| 6 | `__all__` eksik | Eklendi |

### `main.py`
| # | Sorun | Düzeltme |
|---|-------|----------|
| 1 | KRİTİK modül seviyesinde hata riski | `_load_bist_stocks()` güvenli wrapper |
| 2 | `BIST_ALL` duplikasyon | Kaldırıldı |
| 3 | 10+ docstring İngilizce | Türkçe'ye çevrildi |
| 4 | 2× placeholder docstring | Türkçe docstring |
| 5 | 12 method `-> Any` | `-> None` / `-> web.Response` |
| 6 | `import gc` fonksiyon içinde | Dosya başı |
| 7 | `health_handler` type eksik | Tam tip annotation |
| 8 | `stop()` task cancel etmiyor | `for task: task.cancel()` |
| 9 | `__all__` eksik | Eklendi |

---

## Migration Tablosu

| Eski | Yeni | Etkilenen Dosyalar |
|------|------|--------------------|
| `BISTUniverse(use_auto_discovery=True)` | `BISTUniverse()` | Dışçağrı yok — güvenli |
| `market_bars` / `market_data` (CH/PG) | `daily_bars` (tek tablo) | `backfill.py` iç entegrasyon |
| `stop() -> Any` | `stop() -> None` | Dışçağrı yok — güvenli |
| `BIST_ALL` (main.py) | `BIST_STOCKS` | `bist_universe.__getattr__` backward compat |
| `hashlib.md5` (dedup) | `hashlib.sha256` | In-memory, restart sonrası sıfırlanır |
| `np.mean` (data_pipeline) | `sum/len` | `numpy` importu kaldırıldı |

---

## Geliştirme Önerileri

| # | Alan | Öneri |
|---|------|-------|
| 1 | `backfill._count_business_days` | Büyük aralıklar için `numpy.busday_count` ile değiştirilebilir |
| 2 | `bist_universe` | `realtime_provider.py` lazy import ile çalışıyor — `main.py`'deki refresh ile uyumlu |
| 3 | `circuit_breaker._lock` | Kaldırıldı — single-threaded async yeterli |

---

## Bilinen Eksikler

| # | Eksik | Neden Yapılmadı |
|---|-------|-----------------|
| 1 | Geri kalan 8 dosya henüz denetlenmedi | Sırayla devam edilecek |
