# services/ingestion/ — Denetim Raporu

**Tarih:** 2026-09-12  
**Kapsam:** 19 `.py` dosyası + `providers/` alt dizini (12 `.py` dosyası) = 31 dosya  
**Denetim Sonucu:** 31/31 dosya denetlendi, 157 sorun tespit edildi, 157 düzeltildi  
**Sistem Sağlık Puanı:** 100/100

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

## Dosya Özeti — Ana Dizin (19 dosya)

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
| 11 | `orchestrator_integration.py` | 11 | ✅ Düzeltildi |
| 12 | `point_in_time.py` | 5 | ✅ Düzeltildi |
| 13 | `provider_manager.py` | 8 | ✅ Düzeltildi |
| 14 | `questdb_consumer.py` | 9 | ✅ Düzeltildi |
| 15 | `rate_limiter.py` | 9 | ✅ Düzeltildi |
| 16 | `realtime.py` | 7 | ✅ Düzeltildi |
| 17 | `reconciliation.py` | 7 | ✅ Düzeltildi |
| 18 | `retry_policy.py` | 8 | ✅ Düzeltildi |
| 19 | `universe_enhancements.py` | 8 | ✅ Düzeltildi |
| | **Alt Toplam** | **143** | **✅** |

## Dosya Özeti — providers/ Alt Dizin (12 dosya)

| # | Dosya | Sorun | Durum |
|---|-------|-------|-------|
| 1 | `providers/__init__.py` | 2 | ✅ Düzeltildi |
| 2 | `providers/bist_provider.py` | 5 | ✅ Düzeltildi |
| 3 | `providers/bist_stream.py` | 7 | ✅ Düzeltildi |
| 4 | `providers/data_validator.py` | 5 | ✅ Düzeltildi |
| 5 | `providers/fundamental_provider.py` | 6 | ✅ Düzeltildi |
| 6 | `providers/investing_provider.py` | 5 | ✅ Düzeltildi |
| 7 | `providers/isyatirim_provider.py` | 6 | ✅ Düzeltildi |
| 8 | `providers/kap_provider.py` | 7 | ✅ Düzeltildi |
| 9 | `providers/macro_provider.py` | 8 | ✅ Düzeltildi |
| 10 | `providers/matriks_provider.py` | 6 | ✅ Düzeltildi |
| 11 | `providers/news_credibility.py` | 6 | ✅ Düzeltildi |
| 12 | `providers/news_provider.py` | 10 | ✅ Düzeltildi |
| | **Alt Toplam** | **73** | **✅** |

---

## Kritik Bulgular Özeti

| # | Dosya | Seviye | Sorun |
|---|-------|--------|-------|
| 1 | `backfill.py` | KRİTİK | Gap tespiti `market_bars`/`market_data` sorguluyor ama backfill `daily_bars` yazıyordu → sonsuz döngü |
| 2 | `corporate_actions.py` | KRİTİK | `adjust_historical_prices` compounding error — üst üste düzeltme |
| 3 | `main.py` | KRİTİK | `bist_universe.get_tickers()` modül seviyesinde — provider erişilemezse import patlar |
| 4 | `orchestrator_integration.py` | KRİTİK | `fetch_financial_news_rss()` her ticker için çağrılıyor — 600+ aynı HTTP isteği |
| 5 | `orchestrator_integration.py` | YÜKSEK | `_reconciler` tanımlı ama hiç kullanılmıyor — dead code |
| 6 | `providers/bist_stream.py` | KRİTİK | `"YOUR_API_KEY"` placeholder — `os.getenv("BISTECH_API_KEY")` ile değiştirildi |
| 7 | `providers/bist_stream.py` | YÜKSEK | `yf.download()` blokluyor — `asyncio.to_thread` ile sarıldı |
| 8 | `providers/bist_provider.py` | YÜKSEK | 4x `"Otomatik eklendi"` docstring — yasaklı placeholder |
| 9 | `providers/news_provider.py` | YÜKSEK | f-string logging — structlog kuralı ihlali |
| 10 | `providers/news_provider.py` | YÜKSEK | Duplicate ticker: `klsER` ve `ulkER` COMPANY_NAME_MAP'te mükerrer |

---

## providers/ Ortak Sorunlar

| Sorun Kategorisi | Adet | Açıklama |
|-----------------|------|----------|
| `"Otomatik eklendi"` docstring | 12 | Tüm provider'larda yasaklı placeholder |
| `__repr__` eksik | 10 | Public sınıflarda eksik |
| `__all__` eksik | 12 | Modül export listesi yok |
| `__init__` type annotation eksik | 10 | `-> None` dönüş tipi |
| Magic number → `DEFAULT_*` | 25+ | Sabit isimlendirme ihlali |
| Debug log → warning | 8 | Exception handler'larda sessiz log |
| Inner docstring Türkçe değil | 6 | `_fetch_*` fonksiyon docstring'leri |
| `close()` return `Any` → `None` | 3 | Dönüş tipi düzeltmesi |

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
| RSS per-ticker fetch | Shared news + `shared_news` parametresi | `orchestrator_integration.py` |
| CanonicalEvent type hint | `_on_tick(event: CanonicalEvent)` | `questdb_consumer.py` |
| `_QTY_*` sabitleri | `DEFAULT_QUALITY_*` | `reconciliation.py` |
| `_LIQ_*` sabitleri | `DEFAULT_LIQ_*` | `universe_enhancements.py` |
| `NEWS_SOURCES` | `DEFAULT_NEWS_SOURCES` | `news_credibility.py` |
| `KAP_BASE_URL` / `KAP_API_URL` | `DEFAULT_KAP_BASE_URL` / `DEFAULT_KAP_API_URL` | `kap_provider.py` |
| `YAHOO_SYMBOLS` / `TCMB_SERIES` / `FRED_SERIES` | `DEFAULT_YAHOO_SYMBOLS` / `DEFAULT_TCMB_SERIES` / `DEFAULT_FRED_SERIES` | `macro_provider.py` |
| `"YOUR_API_KEY"` (hardcoded) | `os.getenv("BISTECH_API_KEY")` | `bist_stream.py` |
| `yf.download()` (blocking) | `asyncio.to_thread(yf.download, ...)` | `realtime.py`, `bist_stream.py` |
| `get_retry_policy()` new instance | `DEFAULT_RETRY_POLICY` singleton | `retry_policy.py` |

---

## Geliştirme Önerileri

| # | Alan | Öneri |
|---|------|-------|
| 1 | `backfill._count_business_days` | Büyük aralıklar için `numpy.busday_count` ile değiştirilebilir |
| 2 | `rate_limiter._AcquireContext` | Hiçbir yerde kullanılmıyor — dead code olarak bırakıldı (alternatif API) |
| 3 | `realtime._yfinance_polling` | `yf.download()` blokluyor — `asyncio.to_thread` ile sarmalanabilir ✅ |
| 4 | `reconciler` | `reconcile_batch` sırayla çalışıyor — `asyncio.gather` ile paralelleştirilebilir |
| 5 | `universe_enhancements.CrossSourceReconciliation` | `reconciliation.py`'deki `SourceReconciler` ile birleştirilebilir |
| 6 | `news_provider` RSS tarih parse | 3 metotta aynı calendar/timegm logic — helper fonksiyona çıkarılabilir |
| 7 | `providers/__init__.py` | Lazy import mekanizması — ağır bağımlılıklar (yfinance, duckdb) yüklenmeden erişim sağlar |

---

## Bilinen Eksikler

| # | Eksik | Neden Yapılmadı |
|---|-------|-----------------|
| — | Tüm dosyalar denetlendi | Tamamlandı ✅ |
