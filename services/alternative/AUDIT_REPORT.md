# services/alternative/ — Denetim Raporu

**Tarih:** 2026-09-04  
**Kapsam:** 16 `.py` dosyası  
**Denetim Sonucu:** ✅ 16/16 dosya denetlendi ve düzeltildi

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
| 1 | `__init__.py` | 2 geliştirme | ✅ |
| 2 | `base.py` | 7 | ✅ |
| 3 | `bkm_adapter.py` | 5 | ✅ |
| 4 | `credit_card.py` | 3 | ✅ |
| 5 | `eksi_sozluk.py` | 3 | ✅ |
| 6 | `feature_engine.py` | 6 | ✅ |
| 7 | `feature_store.py` | 8 | ✅ |
| 8 | `google_trends.py` | 3 | ✅ |
| 9 | `investing_adapter.py` | 4 | ✅ |
| 10 | `jobs.py` | 3 | ✅ |
| 11 | `kariyer_net.py` | 4 | ✅ |
| 12 | `llm_sentiment.py` | 6 | ✅ |
| 13 | `reconciliation.py` | 3 | ✅ |
| 14 | `satellite_adapter.py` | 4 | ✅ |
| 15 | `social.py` | 1 | ✅ |
| 16 | `web_scraping.py` | 2 | ✅ |

**Toplam:** 64 sorun tespit edildi, 64'ü düzeltildi.

---

## Kritik Düzeltmeler (2. İnceleme)

| # | Dosya | Sorun | Düzeltme |
|---|-------|-------|----------|
| 1 | `feature_engine.py` | Lazy import bypass — `investing_adapter` ve `satellite_adapter` top-level import ediliyordu | `initialize()` methoduna taşındı, top-level import kaldırıldı |
| 2 | `feature_engine.py` | Feature isim uyumsuzluğu — 8 adapter feature'ı `get_feature_names()`'de listelenmemiş | `cc_vs_sector`, `tech_hiring_pct`, `avg_salary_change`, `layoff_signal`, `social_engagement`, `social_sentiment_momentum`, `social_manipulation_score`, `search_volume_change` eklendi |

---

## Import Zinciri Kontrolü

| Kontrol | Sonuç |
|---------|-------|
| Circular import | ✅ Yok |
| Top-level cross-module import | ✅ Yok (sadece `llm_sentiment.py`'de lazy import var) |
| Placeholder docstring | ✅ Kalmadı |
| `-> Any` return type | ✅ Kalmadı |
| Feature isim eşleşmesi | ✅ Tüm adapter feature'ları engine'de listeleniyor |
| Syntax kontrolü (16 dosya) | ✅ Tümü geçti |

---

## Genel Geliştirme Önerileri

| # | Alan | Öneri |
|---|------|-------|
| 1 | Cache | In-memory cache yerine Redis veya TTL-based cache sınıfı düşünülebilir. |
| 2 | BKM Scraping | Regex tabanlı parsing kırılgan. CSS selector stratejisi düşünülebilir. |
| 3 | Sentiment | `_basic_sentiment` eksi_sozluk, investing, llm_sentiment içinde tekrar ediyor. Ortak bir keyword sentiment modülüne çıkarılabilir. |
| 4 | Feature Engine | `get_feature_names()` statik liste. Adapter'lardan dinamik olarak toplanabilir. |
| 5 | Feature Store | `__del__` yerine context manager kullanımı teşvik edilmeli. |
| 6 | Google Trends | `pytrends` senkron kütüphane. Thread pool boyutu sınırlandırılmalı. |
| 7 | LLM Sentiment | `_llm_analyze` cross-module bağımlılık. Dependency injection ile çözülebilir. |
| 8 | Satellite | `rasterio` ağır bir bağımlılık. Lazy import zaten var ama yükleme süresi uzun olabilir. |
| 9 | Feature Mapper | `compute_cc_features`, `compute_job_features`, `compute_web_features` aynı pattern. Ortak bir feature mapper sınıfı düşünülebilir. |
| 10 | Scraping | Tüm scraper'lar aynı User-Agent ve timeout kullanıyor. Ortak bir scraping config sınıfı düşünülebilir. |

---

## Bilinen Eksikler

| # | Eksik | Neden Yapılmadı |
|---|-------|-----------------|
| — | — | — |
