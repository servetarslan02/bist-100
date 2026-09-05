# services/core/ — Denetim Raporu

**Tarih:** 2026-09-05  
**Kapsam:** 104 `.py` dosyası  
**Denetim Sonucu:** 7 dosya denetlendi, 42 sorun düzeltildi. Bekleyen dosya: 97

---

## Denetim Kuralları

1. **Mock / Sahte / Placeholder Veri — Kesinlikle Yasak.** Test verisi, hardcoded değer, statik JSON, placeholder data, 'Otomatik eklendi' docstring, pass ile boş fonksiyon gövdesi — production kodunda yer alamaz.
2. **Kapsamlı Hata, Eşzamanlılık ve Sınır Kontrolleri.** Boundary hataları, dead code, sessiz exception yutma, bypass mekanizmaları düzeltilir. Polars null değerleri, ZeroDivisionError ve NaN/Inf sayısal taşmaları guard altına alınır. Paylaşılan singleton state/bağlantılarda thread-safety (threading.Lock/asyncio.Lock) zorunludur.
3. **Eksiksiz Fonksiyonellik ve Fail-Closed İlkesi.** Eksik parametre, loglama, fallback ve validasyon tamamlanır. Hatalar asla sessizce yutulamaz (except: pass yasak); loglanıp uygun istisna fırlatılır. Tüm parametre ve dönüşlerde eksiksiz type annotation belirtilir.
4. **Profesyonel Kod, Temizlik ve Loglama Mimarisi.** Her docstring açıklayıcı, Türkçe ve Args/Returns/Raises içeren formatta olmalıdır. Her dataclass ve veri modelinde __repr__ metodu bulunur. Fonksiyon içi gereksiz importlar dosya başına taşınır. Sistem genelinde (Web, API, Backtest, ML, Core) birincil loglayıcı olarak `structlog` (`logger = structlog.get_logger(__name__)`) kullanılır. Loglar ve hata mesajları Türkçe olmalıdır. Magic number yerine DEFAULT_* sabitleri kullanılır.
5. **Düzeltme Sonrası Canlı Doğrulama (Smoke/Execution Test).** Yalnızca syntax veya import yetmez; dosyanın ana fonksiyonlarını fiilen çalıştıran mikro test (uv run python -c '...' veya pytest) ve ruff check ile doğruluk kanıtlanmalıdır.
6. **Geliştirme Önerileri ve Proaktif İyileştirme.** Hata olmasa dahi performans, bellek, Polars optimizasyonu veya mimari açıdan sistemi iyileştirebilecek potansiyel alanlar raporlanmalı ve faydalı olanlar sisteme kazandırılmalıdır.
7. **Mimari Tutarlılık, Modül Dışa Aktarımı ve Göç (Migration) Takibi.** Modül seviyesinde __all__ listesi eksiksiz ve güncel olmalıdır. İsim/imza değişikliklerinde tüm repo taranıp çağıran noktalar güncellenmeli ve audit raporuna Migration tablosu eklenmelidir.

---

## Dosya Özeti

| # | Dosya | Sorun | Durum |
|---|-------|-------|-------|
| 1 | `__init__.py` | 4 | ✅ Denetlendi, düzeltildi |
| 2 | `alert_policy.py` | 7 | ✅ Denetlendi, düzeltildi |
| 3 | `alerting.py` | 8 | ✅ Denetlendi, düzeltildi |
| 4 | `algo_notification.py` | 4 | ✅ Denetlendi, düzeltildi |
| 5 | `alpha_engine.py` | 7 | ✅ Denetlendi, düzeltildi |
| 6 | `arrow_pipeline.py` | 6 | ✅ Denetlendi, düzeltildi |
| 7 | `async_http.py` | 6 | ✅ Denetlendi, düzeltildi |

---

## `__init__.py` (1. dosya)

| # | Kural | Sorun | Düzeltme |
|---|-------|-------|----------|
| 1 | 4 | Modül docstring İngilizce ve eksik kapsamlı | Kapsamlı ve Türkçe modül docstring yazıldı |
| 2 | 7 | `__all__` listesi eksikti; import edilen 20+ sembol listede yoktu | Tüm dışa aktarılan sınıflar, fonksiyonlar ve tekil nesneler `__all__` listesine eklendi (toplam 68 sembol) |
| 3 | 3 | `DeadLetterQueue` import için try-except ImportError hilesi vardı | `persistent_dlq` wrapper'ı sağlayan sınıf doğrudan import edildi |
| 4 | 5 | I001 import sıralaması düzensizdi | Ruff standartlarına göre alfabetik ve standart bloklara göre sıralandı |

---

## `alert_policy.py` (2. dosya)

| # | Kural | Sorun | Düzeltme |
|---|-------|-------|----------|
| 1 | 1 | Tam 27 adet `"Otomatik eklendi."` placeholder docstring mevcuttu | Tamamı temizlendi; her fonksiyon ve metoda Türkçe, Args/Returns/Raises içeren profesyonel docstring yazıldı |
| 2 | 4 | `PolicyDiff`, `PolicyAuditEntry`, `SilenceRule`, `AlertPolicy` sınıflarında `__repr__` metodu yoktu | Açıklayıcı ve okunabilir `__repr__` metotları eklendi |
| 3 | 2 | `AlertPolicy` paylaşılan durumlarda eşzamanlı erişim koruması (`threading.Lock`) içermiyordu | `_lock = threading.Lock()` eklendi; kural, denetim, geçmiş ve kilit operasyonları thread-safe hale getirildi |
| 4 | 5 | SQLite spesifik `INSERT OR IGNORE` sözdizimi kullanılmıştı | Standart SQL / DuckDB uyumlu sözdizimine dönüştürüldü (`INSERT INTO`) |
| 5 | 7 | Modül seviyesinde `__all__` dışa aktarım listesi tanımlanmamıştı | `__all__` listesi eklendi (`AlertPolicy`, `PolicyDiff`, `SilenceRule`, vb.) |
| 6 | 4 | Log mesajları İngilizceydi ve yapısal değildi (`logger.warning("Policy save failed")`) | Standart Türkçe anahtar-değer structlog formatına geçirildi |
| 7 | 3 | Eksik ve gevşek tip tanımları (`db=None`, `path=None`, `-> Any`) | `db: Any = None`, `path: str | None = None` ve kesin dönüş tipleri ile güncellendi |

---

## `alerting.py` (3. dosya)

| # | Kural | Sorun | Düzeltme |
|---|-------|-------|----------|
| 1 | 1 | 35+ adet `"Otomatik eklendi."` placeholder docstring mevcuttu | Tamamı temizlendi; tüm sınıf, metot ve enumlara Türkçe, Args/Returns içeren eksiksiz docstring yazıldı |
| 2 | 4 | `Alert`, `NotificationResult`, `NotificationRouter`, `AlertingSystem`, sağlayıcı sınıflarında `__repr__` yoktu | Tüm sınıflara açıklayıcı `__repr__` metotları eklendi |
| 3 | 2 | `self._alerts` bir `deque` iken `list()` dilimleme ile tipi bozuluyordu | `deque(maxlen=self._max_alerts)` yapısı korundu, gereksiz ve tipi bozan `_trim_alerts` list dönüşümü düzeltildi |
| 4 | 5 | SQLite spesifik `INSERT OR REPLACE` sözdizimi kullanılmıştı | DuckDB uyumlu `DELETE` + `INSERT INTO` desenine geçirildi |
| 5 | 4 | Windows CP1254 terminalinde `\u2192` (`→`) karakteri `UnicodeEncodeError` patlatıyordu | ASCII `->` ile değiştirildi, Windows terminal çökmesi önlendi |
| 6 | 4 | Dağınık ve fonksiyon içi `aiohttp` importları vardı | Proje standardı `httpx.AsyncClient` ile birleştirildi, singleton ve güvenli oturum yönetimi sağlandı |
| 7 | 7 | Modül seviyesinde `__all__` listesi eksikti | `__all__` listesi eklendi (`Alert`, `AlertSeverity`, `AlertingSystem`, sağlayıcılar vb.) |
| 8 | 4 | Loglar ve hata mesajları İngilizceydi | `ALARM_BILDIRIMI`, `yeni_alarm_olusturuldu`, `alarm_onaylandi` gibi standart Türkçe structlog yapısına geçirildi |

---

## `algo_notification.py` (4. dosya)

| # | Kural | Sorun | Düzeltme |
|---|-------|-------|----------|
| 1 | 3 | `strategy` None veya eksik anahtarlı geldiğinde fail-closed koruması yetersizdi | Girdi doğrulaması, güvenli varsayılanlar ve fallback değerleri eklendi |
| 2 | 4 | SPK mevzuatına uygun tekil bildirim kimliği ve zaman damgası eksikti | Benzersiz `notification_id` (`uuid4`) ve `timestamp_iso` eklendi |
| 3 | 7 | Modül seviyesinde `__all__` dışa aktarım listesi yoktu | `__all__ = ["generate_algo_notification"]` eklendi |
| 4 | 4 | Fonksiyon docstring'i Args/Returns/Raises formatına uygun değildi | Standart Türkçe profesyonel docstring eklendi |

---

## `alpha_engine.py` (5. dosya)

| # | Kural | Sorun | Düzeltme |
|---|-------|-------|----------|
| 1 | 3 | Model başlatmada diskten otomatik yüklenmiyordu (`self.model = None` kalıyordu) | `__init__` içine 30 günlük otomatik model yükleme eklendi |
| 2 | 4 | `AlphaEngine` sınıfında `__repr__` metodu yoktu | Cihaz, durum ve özellik sayısını bildiren `__repr__` eklendi |
| 3 | 7 | Modül seviyesinde `__all__` listesi tanımlanmamıştı | `__all__ = ["AlphaEngine"]` eklendi |
| 4 | 4 | Metot docstring'leri eksik ve yetersizdi | Tüm metotlara (`fetch_data`, `train`, `predict`, vb.) Türkçe profesyonel docstring yazıldı |
| 5 | 4 | E402 ve E501 import sırası ve satır uzunluğu kuralları ihlal ediliyordu | Docstring başa alındı, satır uzunlukları 120 karakter altına çekildi |
| 6 | 4 | Loglama İngilizceydi ve yapısal değildi | `alpha_engine_model_egitildi`, `alpha_engine_optuna_parametreleri` gibi structlog yapısına geçirildi |
| 7 | 3 | Gevşek tip tanımları (`exclude_features: list[str] = None`) | `exclude_features: list[str] | None = None` ve kesin dönüş tipleri ile güncellendi |

---

## `arrow_pipeline.py` (6. dosya)

| # | Kural | Sorun | Düzeltme |
|---|-------|-------|----------|
| 1 | 1 | 3 adet `"Otomatik eklendi."` placeholder docstring mevcuttu | Tamamı temizlendi; tüm metotlara Türkçe, Args/Returns/Raises içeren docstring yazıldı |
| 2 | 4 | `ArrowPipeline` sınıfında `__repr__` metodu yoktu | `base_path` bilgisini içeren açıklayıcı `__repr__` eklendi |
| 3 | 7 | Modül seviyesinde `__all__` listesi tanımlanmamıştı | `__all__ = ["ArrowPipeline"]` eklendi |
| 4 | 4 | Fonksiyon içi dağınık `import pyarrow`, `import polars` çağrıları vardı | Dosya başında temiz, merkezi import yapısına geçirildi |
| 5 | 2 | `merge_parquet` ve `from_polars` metotlarında boş girdi/None kontrolleri eksikti | Fail-closed sınır kontrolleri (`ValueError`, `FileNotFoundError`) eklendi |
| 6 | 4 | Log mesajları İngilizceydi (`"Parquet written"`, vb.) | `parquet_dosyasi_yazildi`, `parquet_dosyasi_okundu` gibi Türkçe structlog yapısına geçirildi |

---

## `async_http.py` (7. dosya)

| # | Kural | Sorun | Düzeltme |
|---|-------|-------|----------|
| 1 | 1 | 3 adet `"Otomatik eklendi."` placeholder docstring mevcuttu | Tamamı temizlendi; tüm metotlara Türkçe, Args/Returns/Raises içeren docstring yazıldı |
| 2 | 4 | `AsyncHTTPClient` sınıfında `__repr__` metodu yoktu | Oturum durumu ve retry sınırını gösteren `__repr__` eklendi |
| 3 | 7 | Modül seviyesinde `__all__` listesi tanımlanmamıştı | `__all__ = ["AsyncHTTPClient", "close_all_clients", "get_client"]` eklendi |
| 4 | 2 | `get_client` singleton registry'de eşzamanlılık koruması (thread-safety) eksikti | `threading.Lock()` ile korumalı hale getirildi |
| 5 | 4 | Fonksiyon içlerinde gereksiz `import time` tekrarları vardı | Dosya başında standart modül importuna taşındı |
| 6 | 4 | Log ve hata mesajları İngilizceydi | `http_json_ayristirma_hatasi`, `http_zaman_asimi`, `http_istek_siniri_asildi` gibi Türkçe structlog formatına geçirildi |








---

## Geliştirme Önerileri

| # | Alan | Öneri |
|---|------|-------|
| — | — | — |

---

## Bilinen Eksikler

| # | Eksik | Neden Yapılmadı |
|---|-------|-----------------|
| — | — | — |
