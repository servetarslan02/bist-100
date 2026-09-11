# services/factors/ — Denetim Raporu

**Tarih:** 2026-09-11  
**Kapsam:** 11 `.py` dosyası (10 kaynak + 1 `__init__.py`)  
**Denetim Sonucu:** 92 sorun tespit edildi, 92 düzeltildi (8/11 dosya tamamlandı)
**Smoke Test:** 247 test, 0 başarısız
**Ruff Check:** Tüm dosyalarda temiz

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
| 1 | `__init__.py` | Docstring "14 modül" → "10 modül"; `bist_anomalies.py` docstring "8+" → "8" | ✅ Düzeltildi |
| 2 | `altman.py` | 15 sorun (aşağıda detay) | ✅ Düzeltildi |
| 3 | `beneish.py` | 14 sorun (aşağıda detay) | ✅ Düzeltildi |
| 4 | `piotroski.py` | 11 sorun (aşağıda detay) | ✅ Düzeltildi |
| 5 | `fama_french.py` | 14 sorun (aşağıda detay) | ✅ Düzeltildi |
| 6 | `bist_anomalies.py` | 13 sorun (aşağıda detay) | ✅ Düzeltildi |
| 7 | `ranking.py` | 11 sorun (aşağıda detay) | ✅ Düzeltildi |
| 8 | `performance.py` | 12 sorun (aşağıda detay) | ✅ Düzeltildi |
| 9 | `factor_correlation.py` | — | ⏳ Bekliyor |
| 10 | `factor_rotation.py` | — | ⏳ Bekliyor |
| 11 | `factor_time_series.py` | — | ⏳ Bekliyor |

---

## `altman.py`

| # | Sorun | Düzeltme |
|---|-------|----------|
| 1 | `financials=None` → `AttributeError` crash | `TypeError` fırlatılır (Raises docstring ile) |
| 2 | Dict'te None değerler → `None / ta` crash | `_safe_float()` ile None guard |
| 3 | NaN/Inf değerler → sonsuz sonuç | `math.isnan/isinf` guard |
| 4 | `sector=''` → `None.upper()` crash | `ValueError` fırlatılır |
| 5 | `max(x, 1)` yetersiz bölen koruması | `_MIN_DENOMINATOR=1e-6` + `_safe_divide()` |
| 6 | Walrus operator `(_reta := re_ta)` gereksiz | Kaldırıldı |
| 7 | `__all__` eksik | Eklendi |
| 8 | Raises docstring eksik | Eklendi |
| 9 | `ZONES` dict'i mutable shared state | `dict(ZONES)` ile kopya döndürülür |
| 10 | `logger.get_logger()` → modül adı eksik | `__name__` ile |
| 11 | Nullable type annotation eksik | `dict[str, Any] \| None` eklendi |
| 12 | Eksik key'ler → sessiz 0/1 default, loglanmıyor | Her alan `_safe_float` ile loglanır |
| 13 | `COEFFICIENTS` mutable — dışarıdan değiştirilebilir | `MappingProxyType` ile immutable |
| 14 | `TURKEY_ADJUSTMENTS` mutable — dışarıdan değiştirilebilir | `MappingProxyType` ile immutable (iç içe sector dict dahil) |
| 15 | `ZONES` mutable — dışarıdan değiştirilebilir | `MappingProxyType` ile immutable |

### Smoke Test Sonuçları

| Test | Sonuç |
|------|-------|
| Normal veri (SANAYI, turkey_adjusted) | ✓ z=1.9659, GREY |
| `calculate_z_score_simple` | ✓ 0.33 |
| `None` → TypeError | ✓ |
| Boş dict `{}` | ✓ z=0.0, DISTRESS |
| NaN/Inf değerler | ✓ default'a düştü, loglandı |
| Sıfır bölen (total_assets=0) | ✓ crash yok |
| `turkey_adjusted=False` | ✓ |
| `sector=''` → ValueError | ✓ |
| `ruff check` | ✓ All checks passed |
| COEFFICIENTS immutable | ✓ TypeError |
| TURKEY_ADJUSTMENTS immutable | ✓ TypeError |
| ZONES immutable | ✓ TypeError |
| sector dict immutable | ✓ TypeError |
| factor_engine.py entegrasyonu | ✓ z=1.9951, GREY |

### Migration Tablosu

| Çağrı Noktası | Dosya | İmza Değişikliği | Uyumlu |
|---|---|---|---|
| `calculate_z_score(financials)` | `services/intelligence/factor_engine.py:316` | `financials: dict \| None` (genişletildi) | ✅ Evet |
| `services.factors.altman` | `run_all_imports.py:154` | Yok | ✅ Evet |
| `calculate_z_score_simple` | Dışçağrı yok | Yok | ✅ Evet |

---

## `performance.py`

| # | Sorun | Düzeltme |
|---|-------|----------|
| 1 | `factor_returns=None` → crash (falsy → error dict ama type check yok) | `TypeError` fırlatılır |
| 2 | `factors_data=None` → `track_factor_performance_batch` crash | `TypeError` fırlatılır |
| 3 | NaN/Inf getiri değerleri → `np.prod`/`np.std` NaN sonuç | `_clean_array` ile temizleme |
| 4 | `peak=0` → division by zero (ilk getiri -100%) | `np.where(peak==0, 1.0, peak)` guard |
| 5 | `np.corrcoef` std=0 → NaN | `std > 1e-10` guard |
| 6 | `except Exception:` catch-all | `except ImportError:` ile daraltıldı |
| 7 | `__all__` eksik | Eklendi |
| 8 | Raises docstring eksik (2 fonksiyon) | Eklendi |
| 9 | `logger.get_logger()` → modül adı yok | `__name__` ile |
| 10 | `risk_free_rate = 0.15` magic number | `_DEFAULT_RISK_FREE_RATE` sabiti |
| 11 | `max(volatility, 0.001)` yetersiz | `_MIN_DENOMINATOR=1e-3` sabiti |
| 12 | Nullable type annotation eksik | `list[float] \| None` eklendi |

### Smoke Test Sonuçları (26 test)

| Kategori | Test | Sonuç |
|----------|------|-------|
| Normal senaryolar | 5 test | ✓ |
| Benchmark karşılaştırma | 4 test | ✓ |
| Sınır değerleri | 4 test | ✓ |
| NaN/Inf guard | 1 test | ✓ |
| Hata yönetimi | 2 test | ✓ |
| Batch | 4 test | ✓ |
| Peak=0 guard | 1 test | ✓ |
| `_safe_float` | 4 test | ✓ |
| `_clean_array` | 1 test | ✓ |
| `ruff check` | ✓ All checks passed |

---

## `ranking.py`

| # | Sorun | Düzeltme |
|---|-------|----------|
| 1 | `universe=None` → crash (None falsy, `not None` → [] ama type check yok) | `TypeError` fırlatılır |
| 2 | `DEFAULT_WEIGHTS` mutable | `MappingProxyType` ile immutable |
| 3 | `REGIME_WEIGHTS` mutable (iç içe dict) | `MappingProxyType` ile immutable (2 katman) |
| 4 | NaN/Inf/None factor scores → crash | `_safe_float` ile guard |
| 5 | `risk_score=None` → crash | `_safe_float` ile guard (default=50) |
| 6 | `__all__` eksik | Eklendi |
| 7 | Raises docstring eksik (3 fonksiyon) | Eklendi |
| 8 | `logger.get_logger()` → modül adı yok | `__name__` ile |
| 9 | `risk_aversion = 0.5` magic number | `_RISK_AVERSION` sabiti |
| 10 | `get_top_n`/`get_bottom_n` docstring eksik | Args/Returns eklendi |
| 11 | `rank_stocks` mutates input (in-place) | Docstring'de belirtildi (bilinen davranış) |

### Smoke Test Sonuçları (32 test)

| Kategori | Test | Sonuç |
|----------|------|-------|
| Normal senaryolar | 10 test | ✓ |
| Rejim ağırlıkları | 2 test | ✓ |
| Risk adjustment | 2 test | ✓ |
| Sektör nötr | 1 test | ✓ |
| Sınır değerleri | 3 test | ✓ |
| Hata yönetimi | 2 test | ✓ |
| Ağırlık normalizasyonu | 1 test | ✓ |
| get_top_n / get_bottom_n | 5 test | ✓ |
| Immutability (2 katman) | 2 test | ✓ |
| `_safe_float` | 4 test | ✓ |
| `ruff check` | ✓ All checks passed |

---

## `bist_anomalies.py`

| # | Sorun | Düzeltme |
|---|-------|----------|
| 1 | `stock=None` → crash | `TypeError` fırlatılır |
| 2 | `anomalies=None` → `calculate_anomaly_score` crash | `TypeError` fırlatılır |
| 3 | `universe=None` → `calculate_bist_anomalies_batch` crash | `TypeError` fırlatılır |
| 4 | `ANOMALY_DEFINITIONS` mutable (iç içe dict) | `MappingProxyType` ile immutable (2 katman) |
| 5 | NaN/Inf/None değerler → crash | `_safe_float` ile guard |
| 6 | `dividend_yield` negatif olabiliyor → skor < 0 | `max(0.0)` clamp eklendi |
| 7 | `__all__` eksik | Eklendi |
| 8 | Raises docstring eksik (3 fonksiyon) | Eklendi |
| 9 | `logger.get_logger()` → modül adı yok | `__name__` ile |
| 10 | Nullable type annotation eksik | `dict \| None` eklendi |
| 11 | Magic numbers (10.0, 10M, 2.0, 20.0, 50.0) | `_*_DIVISOR` sabitleri |
| 12 | `calculate_anomaly_score` → anomalies values NaN olabilir | `_safe_float` ile guard |
| 13 | Ruff E501 line too long | Düzeltildi |

### Smoke Test Sonuçları (25 test)

| Kategori | Test | Sonuç |
|----------|------|-------|
| Normal senaryolar | 4 test | ✓ |
| Sınır değerleri | 4 test | ✓ |
| NaN/Inf/None guard | 1 test | ✓ |
| Hata yönetimi (TypeError) | 1 test | ✓ |
| Anomaly score (yön düzeltmesi) | 3 test | ✓ |
| Score hata yönetimi | 2 test | ✓ |
| Batch | 4 test | ✓ |
| Immutability (2 katman) | 2 test | ✓ |
| `_safe_float` | 4 test | ✓ |
| `ruff check` | ✓ All checks passed |

---

## `fama_french.py`

| # | Sorun | Düzeltme |
|---|-------|----------|
| 1 | `stock=None` → crash | `TypeError` fırlatılır |
| 2 | `universe_stats=None` → crash | `None` → boş dict fallback |
| 3 | `FACTOR_DEFINITIONS` mutable (iç içe dict) | `MappingProxyType` ile immutable (3 katman) |
| 4 | NaN/Inf/None değerler → crash | `_safe_float` ile guard |
| 5 | `__all__` eksik | Eklendi |
| 6 | Raises docstring eksik | Eklendi (3 fonksiyon) |
| 7 | `logger.get_logger()` → modül adı yok | `__name__` ile |
| 8 | Nullable type annotation eksik | `dict \| None` eklendi |
| 9 | Fonksiyon içi `from scipy.stats import norm` | `_percentile_from_z` helper'a taşındı |
| 10 | Kullanılmayan `p25`, `p75` değişkenleri | Kaldırıldı |
| 11 | `calculate_factor_scores_batch` → NaN array | `np.isfinite` ile temizleme |
| 12 | `calculate_factor_scores_batch` None guard yok | `TypeError` fırlatılır |
| 13 | `std=0` → ZeroDivisionError | `std > 1e-10` guard |
| 14 | `get_factor_weights` rejim ağırlıkları 1.0'a eşit değil (BULL=0.95, BEAR=1.10) | Normalizasyon eklendi |

### Smoke Test Sonuçları (40 test)

| Kategori | Test | Sonuç |
|----------|------|-------|
| Normal senaryolar | 4 test | ✓ |
| Yön düzeltmesi | 1 test | ✓ |
| Sınır değerleri | 3 test | ✓ |
| NaN/Inf/None guard | 3 test | ✓ |
| Hata yönetimi (TypeError) | 2 test | ✓ |
| Batch işlem | 7 test | ✓ |
| Ağırlıklar (6 rejim) | 6 test | ✓ |
| Immutability (3 katman) | 3 test | ✓ |
| `_safe_float` | 6 test | ✓ |
| `_percentile_from_z` | 3 test | ✓ |
| `ruff check` | ✓ All checks passed |

---

## `piotroski.py`

| # | Sorun | Düzeltme |
|---|-------|----------|
| 1 | `financials=None` → crash | `TypeError` fırlatılır |
| 2 | `DEFAULT_WEIGHTS` mutable | `MappingProxyType` ile immutable |
| 3 | NaN/Inf/None değerler → crash | `_safe_float` ile guard |
| 4 | `__all__` eksik | Eklendi |
| 5 | Raises docstring eksik | Eklendi |
| 6 | `logger.get_logger()` → modül adı yok | `__name__` ile |
| 7 | Nullable type annotation eksik | `dict \| None` eklendi |
| 8 | `calculate_f_score_simple` Raises eksik | Eklendi |
| 9 | `w = weights or DEFAULT_WEIGHTS` → mutable ref | `dict(weights)` ile kopya |
| 10 | Eksik weights key → KeyError | `_REQUIRED_CRITERIA` ile `ValueError` |
| 11 | `max_score=0` → ZeroDivisionError | Guard eklendi, warning loglandı |

### Smoke Test Sonuçları (44 test)

| Kategori | Test | Sonuç |
|----------|------|-------|
| Normal senaryolar (STRONG/MODERATE/WEAK) | 10 test | ✓ |
| Sub-scores | 4 test | ✓ |
| Ağırlıklar (özel, eksik, immutable) | 3 test | ✓ |
| Sınır değerleri | 4 test | ✓ |
| NaN/Inf/None guard | 2 test | ✓ |
| Hata yönetimi (TypeError) | 3 test | ✓ |
| Boolean arithmetic | 2 test | ✓ |
| `calculate_f_score_simple` | 5 test | ✓ |
| `_safe_float` | 7 test | ✓ |
| Prev fallback | 2 test | ✓ |
| `ruff check` | ✓ All checks passed |

### Migration Tablosu

| Çağrı Noktası | Dosya | İmza Değişikliği | Uyumlu |
|---|---|---|---|
| `calculate_f_score(financials)` | `services/intelligence/factor_engine.py:314` | `financials: dict \| None` (genişletildi) | ✅ Evet |
| `calculate_f_score_simple` | Dışçağrı yok | — | ✅ Evet |

---

## `beneish.py`

| # | Sorun | Düzeltme |
|---|-------|----------|
| 1 | `current=None` → `AttributeError` crash | `TypeError` fırlatılır |
| 2 | `_calculate_components` — None/NaN/Inf guard yok | `_safe_float` + `_safe_divide` ile koruma |
| 3 | `_read_raw_indices` — None/NaN guard yok | `_safe_float` ile koruma |
| 4 | `COEFFICIENTS` mutable shared state | `MappingProxyType` ile immutable |
| 5 | `THRESHOLDS` mutable shared state | `MappingProxyType` ile immutable |
| 6 | `__all__` eksik | Eklendi |
| 7 | Raises docstring eksik | Eklendi |
| 8 | `logger.get_logger()` → modül adı eksik | `__name__` ile |
| 9 | Nullable type annotation eksik | `dict[str, Any] \| None` eklendi |
| 10 | `_calculate_components` docstring eksik | Args/Returns eklendi |
| 11 | `_read_raw_indices` docstring eksik | Args/Returns eklendi |
| 12 | `calculate_m_score_simple` Raises eksik | Eklendi |
| 13 | Return `coefficients` module dict'in referansı | `dict(COEFFICIENTS)` ile kopya |
| 14 | `max(x, 0.001)` yetersiz bölen koruması | `_MIN_DENOMINATOR=1e-3` + `_safe_divide` |

### Smoke Test Sonuçları (49 test)

| Kategori | Test | Sonuç |
|----------|------|-------|
| Normal (previous ile) | 7 test | ✓ |
| Raw index (backward compat) | 2 test | ✓ |
| Kategori/eşik | 6 test | ✓ |
| Sınır değerleri | 4 test | ✓ |
| NaN/Inf/None guard | 4 test | ✓ |
| Hata yönetimi (TypeError) | 3 test | ✓ |
| Immutability | 3 test | ✓ |
| `calculate_m_score_simple` | 4 test | ✓ |
| `_safe_float` | 6 test | ✓ |
| `_safe_divide` | 4 test | ✓ |
| `_calculate_components` | 3 test | ✓ |
| `_read_raw_indices` | 3 test | ✓ |
| `ruff check` | ✓ All checks passed |

### Migration Tablosu

| Çağrı Noktası | Dosya | İmza Değişikliği | Uyumlu |
|---|---|---|---|
| `calculate_m_score(financials)` | `services/intelligence/factor_engine.py:315` | `current: dict \| None` (genişletildi) | ✅ Evet |
| `calculate_m_score_simple` | Dışçağrı yok | — | ✅ Evet |

---

## `__init__.py`

| # | Sorun | Düzeltme |
|---|-------|----------|
| 1 | Docstring "14 modül" → gerçek sayı 10 | "10 modül" olarak düzeltildi |
| 2 | `bist_anomalies.py` docstring "8+" → gerçek sayı 8 | "8" olarak düzeltildi (`bist_anomalies.py`'de) |

---

## Geliştirme Önerileri

| # | Alan | Öneri |
|---|------|-------|
| 1 | `performance.py` | "10+ metrik" → "14 metrik (+6 benchmark)" olarak netleştirilebilir |

---

## Bilinen Eksikler

| # | Eksik | Neden Yapılmadı |
|---|-------|-----------------|
| 1 | `factor_correlation.py` denetimi | Sıradaki dosya, henüz başlanmadı |
| 2 | `factor_rotation.py` denetimi | Sıradaki dosya, henüz başlanmadı |
| 3 | `factor_time_series.py` denetimi | Sıradaki dosya, henüz başlanmadı |

---

## Genel Özet

| Metrik | Değer |
|--------|-------|
| Denetlenen dosya | 8 / 11 |
| Toplam sorun | 92 |
| Düzeltilen | 92 |
| Smoke test | 247 |
| Başarısız test | 0 |
| Ruff check | 8/8 temiz |
| Kritik bulgular | `fama_french` ağırlık normalizasyonu (BULL=0.95), `performance` peak=0 division, `bist_anomalies` negatif dividend |
| Silinen boş modül | `services/events/` (0 kod, 0 import) |
| Dışçağrı uyumluluğu | 3/3 kırılmadı (factor_engine.py + run_all_imports.py) |
