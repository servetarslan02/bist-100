# services/core/ — Denetim Raporu

**Tarih:** 2026-09-05  
**Kapsam:** 104 `.py` dosyası  
**Denetim Sonucu:** 2 dosya denetlendi, 11 sorun düzeltildi. Bekleyen dosya: 102

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

## Geliştirme Önerileri

| # | Alan | Öneri |
|---|------|-------|
| — | — | — |

---

## Bilinen Eksikler

| # | Eksik | Neden Yapılmadı |
|---|-------|-----------------|
| — | — | — |
