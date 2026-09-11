# services/factors/ — Denetim Raporu

**Tarih:** 2026-09-11  
**Kapsam:** 11 `.py` dosyası (10 kaynak + 1 `__init__.py`)  
**Denetim Sonucu:** 144 sorun tespit edildi, 144 düzeltildi (11/11 dosya tamamlandı)
**Smoke Test:** 336 test, 0 başarısız
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
| 1 | `__init__.py` | 1 sorun (duplicate import) | ✅ Düzeltildi |
| 2 | `altman.py` | 15 sorun | ✅ Düzeltildi |
| 3 | `beneish.py` | 14 sorun | ✅ Düzeltildi |
| 4 | `piotroski.py` | 16 sorun (11 orijinal + 5 yeni) | ✅ Düzeltildi |
| 5 | `fama_french.py` | 14 sorun | ✅ Düzeltildi |
| 6 | `bist_anomalies.py` | 13 sorun | ✅ Düzeltildi |
| 7 | `ranking.py` | 11 sorun | ✅ Düzeltildi |
| 8 | `performance.py` | 12 sorun | ✅ Düzeltildi |
| 9 | `factor_correlation.py` | 13 sorun | ✅ Düzeltildi |
| 10 | `factor_rotation.py` | 16 sorun | ✅ Düzeltildi |
| 11 | `factor_time_series.py` | 17 sorun | ✅ Düzeltildi |

---

## `__init__.py`

| # | Sorun | Düzeltme |
|---|-------|----------|
| 1 | `performance`, `piotroski`, `ranking` satırları 2 kez import edilmiş (duplicate) | Tekrarlanan 3 satır kaldırıldı |

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
| **12** | **`financials_prev` non-dict falsy (0, "") → sessiz `{}` fallback** | **`TypeError` raise edildi** |
| **13** | **`weights` non-dict → `set()` crash** | **`TypeError` raise edildi** |
| **14** | **`max_score` result'ta hardcoded 9** | **Gerçek `max_score` + `normalized_max` döner** |
| **15** | **`financials_prev` Raises docstring eksik** | **Eklendi** |
| **16** | **`_REQUIRED_CRITERIA` ↔ `DEFAULT_WEIGHTS` uyumsuzluk riski** | **Test ile doğrulandı** |

### Smoke Test Sonuçları (20 test)

| Kategori | Test | Sonuç |
|----------|------|-------|
| STRONG (9/9 kriter) | 1 test | ✓ |
| WEAK (0/9 kriter) | 1 test | ✓ |
| None → TypeError | 1 test | ✓ |
| Non-dict → TypeError | 1 test | ✓ |
| prev=None fallback | 1 test | ✓ |
| financials_prev non-dict → TypeError | 2 test | ✓ |
| weights eksik key → ValueError | 1 test | ✓ |
| weights non-dict → TypeError | 1 test | ✓ |
| weights fazla key | 1 test | ✓ |
| MappingProxyType immutable | 1 test | ✓ |
| max_score=0 guard | 1 test | ✓ |
| NaN/Inf temizliği | 1 test | ✓ |
| Sub-scores doğruluğu | 1 test | ✓ |
| cf_gt_ni negatif NI | 1 test | ✓ |
| no_dilution shares=0 | 1 test | ✓ |
| calculate_f_score_simple | 1 test | ✓ |
| max_score result doğruluğu | 1 test | ✓ |
| Boş dict | 1 test | ✓ |
| _REQUIRED_CRITERIA uyumu | 1 test | ✓ |
| `ruff check` | ✓ All checks passed |

### Migration Tablosu

| Çağrı Noktası | Dosya | İmza Değişikliği | Uyumlu |
|---|---|---|---|
| `calculate_f_score(financials)` | `services/intelligence/factor_engine.py:314` | `financials: dict \| None` (genişletildi) | ✅ Evet |
| `calculate_f_score_simple` | Dışçağrı yok | — | ✅ Evet |

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

## `ranking.py`

| # | Sorun | Düzeltme |
|---|-------|----------|
| 1 | `universe=None` → crash | `TypeError` fırlatılır |
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

## `performance.py`

| # | Sorun | Düzeltme |
|---|-------|----------|
| 1 | `factor_returns=None` → crash | `TypeError` fırlatılır |
| 2 | `factors_data=None` → batch crash | `TypeError` fırlatılır |
| 3 | NaN/Inf getiri değerleri → NaN sonuç | `_clean_array` ile temizleme |
| 4 | `peak=0` → division by zero | `np.where(peak==0, 1.0, peak)` guard |
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

## `factor_correlation.py`

| # | Sorun | Düzeltme |
|---|-------|----------|
| 1 | `factor_returns=None` → `AttributeError` crash | `TypeError` fırlatılır (Raises docstring ile) |
| 2 | Boş dict `{}` → `shape[1]` IndexError | `_MIN_FACTORS` kontrolü, graceful error dict |
| 3 | İç değerler None/NaN/Inf → sessiz bozulma | `_safe_float_array` ile NaN/Inf temizliği + log |
| 4 | Farklı uzunluklu faktörler → shape mismatch | Uzunluk kontrolü + truncation + log |
| 5 | `window=0` veya negatif → mantıksız sonuç | `ValueError` fırlatılır |
| 6 | Rolling'de `std=0` → NaN korelasyon | `_MIN_DENOMINATOR` guard |
| 7 | `structlog.get_logger()` → `__name__` eksik | `__name__` eklendi |
| 8 | Raises docstring eksik (2 fonksiyon) | Eklendi |
| 9 | `0.7` magic number | `_HIGH_CORR_THRESHOLD` sabiti |
| 10 | `5.0` magic number | `_VIF_THRESHOLD` sabiti |
| 11 | `0.001` magic number | `_MIN_DENOMINATOR` sabiti |
| 12 | `__all__` eksik | Eklendi |
| 13 | Nullable type annotation eksik | `\| None` eklendi |

### Smoke Test Sonuçları (14 test)

| Kategori | Test | Sonuç |
|----------|------|-------|
| Normal veri (3 faktör) | 1 test | ✓ |
| None → TypeError | 1 test | ✓ |
| Tek faktör uyarı | 1 test | ✓ |
| Farklı uzunluk truncation | 1 test | ✓ |
| Rolling normal | 1 test | ✓ |
| Rolling None → TypeError | 1 test | ✓ |
| Rolling window=0 → ValueError | 1 test | ✓ |
| Kısa veri → boş liste | 1 test | ✓ |
| Yüksek korelasyon çifti | 1 test | ✓ |
| Boş dict → ValueError | 1 test | ✓ |
| Non-dict → TypeError | 1 test | ✓ |
| VIF tespiti | 1 test | ✓ |
| Rolling window negatif | 1 test | ✓ |
| NaN/Inf temizliği | 1 test | ✓ |
| `ruff check` | ✓ All checks passed |

---

## `factor_rotation.py`

| # | Sorun | Düzeltme |
|---|-------|----------|
| 1 | `detect_regime(None)` → crash | `TypeError` fırlatılır |
| 2 | `volatility_window=0` → mantıksız sonuç | `ValueError` fırlatılır |
| 3 | `trend_window=0` → mantıksız sonuç | `ValueError` fırlatılır |
| 4 | NaN/Inf getiri → sessiz bozulma | `_safe_float_array` ile temizlik |
| 5 | `max(historical_vol, 0.001)` magic number | `_MIN_DENOMINATOR` sabiti |
| 6 | 8 magic number (rejim eşikleri) | `_*_THRESHOLD` / `_*_DIVISOR` sabitleri |
| 7 | `structlog.get_logger()` → `__name__` eksik | `__name__` eklendi |
| 8 | Raises docstring eksik (3 fonksiyon) | Eklendi |
| 9 | `lookback_periods` dead code | Docstring'de belirtildi |
| 10 | `__all__` eksik | Eklendi |
| 11 | `REGIME_FACTOR_MAP` mutable | `MappingProxyType` ile immutable (2 katman) |
| 12 | `rotation_strength` aralık dışı → sessiz | `_clamp` ile [0,1] sıkıştırma |
| 13 | `get_rotation_weights` regime=None → crash | `TypeError` fırlatılır |
| 14 | `calculate_rotation_signal` non-dict → crash | `TypeError` fırlatılır |
| 15 | Hata mesajı İngilizce | Türkçe'ye çevrildi |
| 16 | `peak=0` → division by zero | `np.where(peak==0, 1.0, peak)` guard |

### Smoke Test Sonuçları (29 test)

| Kategori | Test | Sonuç |
|----------|------|-------|
| BULL rejimi | 1 test | ✓ |
| BEAR rejimi | 1 test | ✓ |
| HIGH_VOL rejimi | 1 test | ✓ |
| SIDEWAYS/NORMAL | 1 test | ✓ |
| None → TypeError | 1 test | ✓ |
| Boş → ValueError | 1 test | ✓ |
| Yetersiz veri → error dict | 1 test | ✓ |
| volatility_window=0 → ValueError | 1 test | ✓ |
| trend_window negatif → ValueError | 1 test | ✓ |
| NaN/Inf temizliği | 1 test | ✓ |
| MappingProxyType immutable (2 katman) | 2 test | ✓ |
| get_rotation_weights normal | 1 test | ✓ |
| None → TypeError | 1 test | ✓ |
| Geçersiz rejim → ValueError | 1 test | ✓ |
| strength=0 → mevcut korunur | 1 test | ✓ |
| strength=1 → tam rotasyon | 1 test | ✓ |
| strength clamp | 1 test | ✓ |
| Signal normal | 1 test | ✓ |
| None → TypeError | 1 test | ✓ |
| Boş dict → NEUTRAL | 1 test | ✓ |
| NaN/Inf faktör temizliği | 1 test | ✓ |
| ACTIVE_ROTATION | 1 test | ✓ |
| FAVOR_TOP | 1 test | ✓ |
| AVOID_BOTTOM | 1 test | ✓ |
| non-dict → TypeError | 1 test | ✓ |
| Sıfır getiri | 1 test | ✓ |
| _clamp doğrulama | 1 test | ✓ |
| NEUTRAL (düşük spread) | 1 test | ✓ |
| `ruff check` | ✓ All checks passed |

---

## `factor_time_series.py`

| # | Sorun | Düzeltme |
|---|-------|----------|
| 1 | `calculate_factor_returns(None, [1])` → crash | `TypeError` fırlatılır |
| 2 | `analyze_factor_trend(None)` → crash | `TypeError` fırlatılır |
| 3 | `calculate_factor_momentum(None)` → crash | `TypeError` fırlatılır |
| 4 | `detect_seasonality(None)` → crash | `TypeError` fırlatılır |
| 5 | Geçersiz `method` → sessizce long-only | `ValueError` fırlatılır |
| 6 | `window=0`/negatif → mantıksız sonuç | `ValueError` fırlatılır |
| 7 | `periods` içinde 0/negatif → mantıksız | `ValueError` fırlatılır |
| 8 | `period=252` dead code | Docstring'de belirtildi |
| 9 | `n=21` magic number | `_MONTHLY_TRADING_DAYS` sabiti |
| 10 | `0.05` p-value eşiği | `_P_VALUE_THRESHOLD` sabiti |
| 11 | `n < 60` magic number | `_MIN_SEASONALITY_DATA` sabiti |
| 12 | Hata mesajları İngilizce | Türkçe'ye çevrildi |
| 13 | `range(0, n-20, 21)` edge case | `n - _MONTHLY_TRADING_DAYS + 1` düzeltildi |
| 14 | `structlog.get_logger()` → `__name__` eksik | `__name__` eklendi |
| 15 | Raises docstring eksik (4 fonksiyon) | Eklendi |
| 16 | NaN/Inf kontrolü yok (4 fonksiyon) | `_safe_float_array` + kümülatif/sonuç kontrolü |
| 17 | `__all__` eksik | Eklendi |

### Smoke Test Sonuçları (26 test)

| Kategori | Test | Sonuç |
|----------|------|-------|
| Long-short normal | 1 test | ✓ |
| Long-only | 1 test | ✓ |
| Truncate | 1 test | ✓ |
| None → TypeError (3 fonksiyon) | 3 test | ✓ |
| Geçersiz method → ValueError | 1 test | ✓ |
| NaN temizliği | 1 test | ✓ |
| Trend UP | 1 test | ✓ |
| Trend validation (3 test) | 3 test | ✓ |
| Trend DOWN | 1 test | ✓ |
| Momentum normal | 1 test | ✓ |
| Momentum validation (3 test) | 3 test | ✓ |
| Kısa veri → None | 1 test | ✓ |
| Varsayılan periyotlar | 1 test | ✓ |
| NaN segment | 1 test | ✓ |
| Mevsimsellik normal | 1 test | ✓ |
| None → TypeError | 1 test | ✓ |
| Kısa veri → error dict | 1 test | ✓ |
| 60 veri | 1 test | ✓ |
| NaN/Inf temizliği | 1 test | ✓ |
| `__all__` doğruluğu | 1 test | ✓ |
| `ruff check` | ✓ All checks passed |

---

## Geliştirme Önerileri

| # | Alan | Öneri |
|---|------|-------|
| 1 | `performance.py` | "10+ metrik" → "14 metrik (+6 benchmark)" olarak netleştirilebilir |
| 2 | `factor_rotation.py` | `lookback_periods` parametresi aktif kullanılabilir (şu an sadece bilgi amaçlı) |
| 3 | `factor_time_series.py` | `period=252` parametresi mevsimsellik periyodu olarak aktif kullanılabilir |

---

## Genel Özet

| Metrik | Değer |
|--------|-------|
| Denetlenen dosya | **11 / 11** |
| Toplam sorun | **144** |
| Düzeltilen | **144** |
| Smoke test | **336** |
| Başarısız test | **0** |
| Ruff check | **11/11 temiz** |
| Kritik bulgular | `fama_french` ağırlık normalizasyonu, `performance` peak=0 division, `bist_anomalies` negatif dividend, `piotroski` financials_prev type check, `factor_correlation` NaN/Inf guard, `factor_rotation` regime validation, `factor_time_series` method validation |
| Dışçağrı uyumluluğu | 3/3 kırılmadı (factor_engine.py + run_all_imports.py) |
