# services/pipeline/ — Denetim Raporu

**Tarih:** 2026-09-13  
**Kapsam:** 4 `.py` dosyası (`__init__.py`, `main_backtest.py`, `run_daily_inference.py`, `run_unified_daily.py`, `startup_catchup.py`)  
**Denetim Sonucu:** 14 sorun tespit edildi, 14 düzeltildi. Testler %100 başarılı (9/9 passed).

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
| 1 | `__init__.py` | Dosya boştu (0 byte), hiçbir sembol ve docstring dışa aktarılmıyordu. | ✅ Düzeltildi |
| 2 | `main_backtest.py` | `run_final()` metodunda "Otomatik eklendi." placeholder docstring, import sırası karmaşası, magic numbers (`100000.0`, `0.001`, `0.002`, `10`), eksik `__all__`. | ✅ Düzeltildi |
| 3 | `run_daily_inference.py` | `datetime.timedelta` eksikliği nedeniyle `AttributeError` çalışma zamanı çöküşü, fonksiyon içi importlar, `save_to_db` içinde "Otomatik eklendi." placeholder, eksik `__all__`. | ✅ Düzeltildi |
| 4 | `run_unified_daily.py` | Eksik modül sabitleri (`DEFAULT_MAX_POSITION_CAP`, `DEFAULT_MIN_SCORE_THRESHOLD`), eksik `__all__`. | ✅ Düzeltildi |
| 5 | `startup_catchup.py` | `__repr__` yetersizliği (`<MasterStartupCatchup>`), `self.calendar.is_holiday()` çağrısının eksik metot riski, magic numbers (`50`, `6379`), eksik `__all__`. | ✅ Düzeltildi |

---

## `main_backtest.py`

| # | Sorun | Düzeltme |
|---|-------|----------|
| 1 | "Otomatik eklendi." placeholder docstring | `run_final` için kapsamlı Türkçe docstring (Args/Returns/Raises) eklendi. |
| 2 | Magic number kullanımı (`100000.0`, `0.001`, `0.002`, `10`) | `DEFAULT_INITIAL_CAPITAL`, `DEFAULT_COMMISSION_RATE`, `DEFAULT_SLIPPAGE_PCT`, `DEFAULT_TOP_PICKS` sabitleri tanımlandı. |
| 3 | f-string loglama yerine structlog | Key-value yapısal loglamaya geçildi. |
| 4 | Eksik dışa aktarım | `__all__` listesi eklendi. |

---

## `run_daily_inference.py`

| # | Sorun | Düzeltme |
|---|-------|----------|
| 1 | `today - datetime.timedelta(...)` AttributeError | `from datetime import UTC, date, datetime, timedelta` import edilerek çalışma zamanı hatası giderildi. |
| 2 | Fonksiyon içi import dağınıklığı | Bütün importlar PEP 8 uyumlu olarak dosya başına taşındı. |
| 3 | `save_to_db` "Otomatik eklendi." placeholder | Açıklayıcı Türkçe docstring eklendi. |
| 4 | Tarih dönüşümü kırılganlığı | `date.fromisoformat(target_date[:10])` ile ISO güvenli ayrıştırma sağlandı. |
| 5 | Eksik dışa aktarım | `__all__` listesi eklendi. |

---

## `run_unified_daily.py`

| # | Sorun | Düzeltme |
|---|-------|----------|
| 1 | Magic number risk eşikleri | `DEFAULT_MAX_POSITION_CAP`, `DEFAULT_MIN_POSITION_FLOOR`, `DEFAULT_MIN_SCORE_THRESHOLD`, `DEFAULT_MIN_EXIT_SCORE` sabitleri tanımlandı. |
| 2 | Eksik dışa aktarım | `__all__` listesi eklendi. |

---

## `startup_catchup.py`

| # | Sorun | Düzeltme |
|---|-------|----------|
| 1 | Basit `__repr__` | `MasterStartupCatchup(calendar=...)` detaylı gösterimi eklendi. |
| 2 | `calendar.is_holiday` eksikliği | `services.core.market_calendar.MarketCalendar` sınıfına `is_holiday` metodu eklenerek uyumluluk sağlandı. |
| 3 | Eksik dışa aktarım | `__all__` listesi eklendi. |

---

## Canlı Doğrulama ve Test Sonuçları

- **Ruff Linter:** `uv run ruff check services/pipeline/ tests/test_audit_pipeline.py` -> 0 hata.
- **Birim & Entegrasyon Testi:** `uv run pytest tests/test_audit_pipeline.py` -> **9/9 passed (100% green)**.
- **Geriye Dönük Uyumluluk:** `uv run pytest tests/test_api_v1_portfolio_comprehensive.py tests/test_api_v1_backtest_scanner_comprehensive.py` -> **17/17 passed (100% green)**.
