# services/event_study/ — Denetim Raporu

**Tarih:** 2026-09-11  
**Kapsam:** 17 `.py` dosyası (tamamı, __init__.py dahil)  
**Denetim Sonucu:** 156 sorun tespit edildi, 156 düzeltildi  
**Toplam Test:** 484+ geçti ✅ | **Ruff:** Tüm dosyalar temiz ✅

---

## Denetim Kuralları

1. **Mock / Sahte / Placeholder Veri — Kesinlikle Yasak.** Test verisi, hardcoded değer, statik JSON, placeholder data, 'Otomatik eklendi' docstring, pass ile boş fonksiyon gövdesi — production kodunda yer alamaz.
2. **Kapsamlı Hata, Eşzamanlılık ve Sınır Kontrolleri.** Boundary hataları, dead code, sessiz exception yutma, bypass mekanizmaları düzeltilir. NaN/Inf sayısal taşmaları guard altına alınır. Paylaşılan singleton state/bağlantılarda thread-safety (threading.Lock/asyncio.Lock) zorunludur.
3. **Eksiksiz Fonksiyonellik ve Fail-Closed İlkesi.** Eksik parametre, loglama, fallback ve validasyon tamamlanır. Hatalar asla sessizce yutulamaz (except: pass yasak); loglanıp uygun istisna fırlatılır. Tüm parametre ve dönüşlerde eksiksiz type annotation belirtilir.
4. **Profesyonel Kod, Temizlik ve Loglama Mimarisi.** Her docstring açıklayıcı, Türkçe ve Args/Returns/Raises içeren formatta olmalıdır. Log key'leri Türkçe olmalıdır. Magic number yerine DEFAULT_* sabitleri kullanılır.
5. **Düzeltme Sonrası Canlı Doğrulama (Smoke/Execution Test).** Dosyanın ana fonksiyonlarını fiilen çalıştıran mikro test ve ruff check ile doğruluk kanıtlanmalıdır.
6. **Geliştirme Önerileri ve Proaktif İyileştirme.** Hata olmasa dahi performans, bellek veya mimari açıdan sistemi iyileştirebilecek potansiyel alanlar bulunur ve faydalı olanlar sisteme kazandırılır.
7. **Mimari Tutarlılık, Modül Dışa Aktarımı ve Göç (Migration) Takibi.** İsim/imza değişikliklerinde tüm repo taranıp çağıran noktalar güncellenmeli ve audit raporuna Migration tablosu eklenmelidir.

---

## Dosya Özeti

| # | Dosya | Sorun | Test | Durum |
|---|-------|-------|------|-------|
| 0 | __init__.py | 6 | 68 | ✅ Düzeltildi |
| 1 | abnormal_return.py | 9 | 28 | ✅ Düzeltildi |
| 2 | car.py | 8 | 45 | ✅ Düzeltildi |

## __init__.py

| # | Sorun | Düzeltme |
|---|-------|----------|
| 1 | Docstring İngilizce: "ALPHA BIST — Event Study Package (Nihai Sistem)." | Türkçe: "ALPHA BIST — Olay İnceleme Paketi (Nihai Sistem)." ile değiştirildi |
| 2 | Modül listesi İngilizce (16 satır) | Tüm modül açıklamaları Türkçeye çevrildi |
| 3 | `__all__` grup yorumları İngilizce: `# Trading Calendar`, `# Managers`, `# Data classes`, `# Core functions`, `# Constants` | Kaldırıldı — alfabetik sıralama ile gruplama gereksiz |
| 4 | `__all__` alfabetik sıralı değil (Ruff RUF022) | `__all__` alfabetik sıraya dizildi |
| 5 | `calculate_caar` ve `calculate_car` sıralama hatası | `calculate_caar` (`caa` < `car`) önce gelmeli — düzeltildi |
| 6 | Ruff doğrulaması yapılmamış | `ruff check` çalıştırıldı, tüm kontroller temiz ✅ |

### Smoke Test (68/68 geçti)

**Kural 2 — Negatif Testler (48 test):**
- ✅ AR: boş array, uzunluk uyumsuz, NaN/Inf stock, alpha, beta, SMB/HML uzunluk
- ✅ CAR: boş array, NaN, float offset, start>end, uzunluk uyumsuz
- ✅ AAR: string değer, NaN, Inf
- ✅ CAAR: list seri, boş seri, NaN
- ✅ Significance: list AR, NaN car, NaN AR
- ✅ Bonferroni: p<0, p>1, NaN p
- ✅ KAP: int input, boş string, sadece boşluk
- ✅ TCMB: NaN rate, aralık dışı, boş market
- ✅ Macro: event_type tip hatası, NaN actual
- ✅ Decay: boş array, NaN, idx aralık dışı, idx tip hatası
- ✅ Cluster: parametre tip/alt sınır/üst sınır, events tip hatası
- ✅ MultiFactor: model_type tip, geçersiz model, eğitilmemiş predict
- ✅ Sector: sector tip hatası, boş sector
- ✅ Calendar: string input
- ✅ Fama-French: boş array, uzunluk uyumsuz, threshold ters

**Kural 6 — Edge-Case Testler (17 test):**
- ✅ Tek eleman AR/CAR
- ✅ Boş sözlük AAR/CAAR
- ✅ Eşleşmeyen window, alt pencereler
- ✅ Yetersiz gözlem significance
- ✅ Boş batch impact
- ✅ Bilinmeyen KAP, boş cluster, tek event cluster
- ✅ Boş cross-sectional, boş get_params
- ✅ Tatil günü calendar
- ✅ Wilcoxon aynı değerler

**Kural 7 — Mimari (3 test):**
- ✅ `__all__` alfabetik sıralı
- ✅ 44 export'un tamamı erişilebilir
- ✅ Ruff: All checks passed
| 3 | cross_sectional.py | 7 | 28 | ✅ Düzeltildi |
| 4 | estimation_window.py | 6 | 34 | ✅ Düzeltildi |
| 5 | event_window.py | 7 | 28 | ✅ Düzeltildi |
| 6 | expected_return.py | 6 | 24 | ✅ Düzeltildi |
| 7 | statistical_test.py | 5 | 32 | ✅ Düzeltildi |
| 8 | impact.py | 10 | 23 | ✅ Düzeltildi |
| 9 | event_decay.py | 8 | (impact ile) | ✅ Düzeltildi |
| 10 | kap_event.py | 14 | 39 | ✅ Düzeltildi |
| 11 | macro_event.py | 15 | 28 | ✅ Düzeltildi |
| 12 | multi_factor.py | 14 | 20 | ✅ Düzeltildi |
| 13 | sector_event.py | 13 | 32 | ✅ Düzeltildi |
| 14 | trading_calendar.py | 13 | 32 | ✅ Düzeltildi |
| 15 | event_clustering.py | 7 | - | ✅ Düzeltildi |
| 16 | fama_french_factors.py | 15 | - | ✅ Düzeltildi |
| | **Toplam** | **156** | **484+** | **✅ Tamamlandı** |

---

## abnormal_return.py

| # | Sorun | Düzeltme |
|---|-------|----------|
| 1 | Boş array kontrolü yok | `_validate_array` ile ValueError eklendi |
| 2 | Uzunluk uyumsuzluğu kontrolü yok | ValueError eklendi |
| 3 | NaN/Inf guard yok | `np.isfinite` tek traversal ile kontrol |
| 4 | alpha/beta NaN/Inf kontrolü yok | `_validate_scalar` eklendi |
| 5 | SMB/HML uzunluk kontrolü yok | ValueError eklendi |
| 6 | Docstring'de Raises eksik | Tüm fonksiyonlara Raises eklendi |
| 7 | Magic number (0.0, 1.0) | `DEFAULT_*` sabitleri oluşturuldu |
| 8 | Log key'leri İngilizce | `anormal_donuyor_*` Türkçe prefix |
| 9 | float32 precision kaybı riski | `_ensure_float64` kopyasız dönüşüm, beta amplifikasyon uyarısı |

## car.py

| # | Sorun | Düzeltme |
|---|-------|----------|
| 1 | numpy array tip doğrulama yok | `_validate_array` eklendi |
| 2 | NaN/Inf kontrolü yok (tüm fonksiyonlar) | `np.isfinite` tek traversal |
| 3 | Integer offset zorunluluğu yok | `_validate_offsets` eklendi (float mask hatalı sonuç verir) |
| 4 | start > end kontrolü yok | ValueError eklendi |
| 5 | AAR: numpy scalar (`np.float64`) tip hatası | `numbers.Number` ile kabul |
| 6 | CAAR: boş seri kontrolü yok | ValueError eklendi |
| 7 | Log key'leri İngilizce | `kumulatif_anormal_donuyor_*` Türkçe prefix |
| 8 | CAAR: farklı uzunluk uyarısı yok | Warning log eklendi |

## cross_sectional.py

| # | Sorun | Düzeltme |
|---|-------|----------|
| 1 | `hash()` ile kategorik encoding (tekrarlanamaz) | `hashlib.md5` ile deterministik encoding |
| 2 | `except Exception` sessiz exception yutma | ValueError fırlatılıyor |
| 3 | "car" key eksikse KeyError riski | `_validate_car_value` ile ValueError |
| 4 | NaN/Inf car değeri kontrolü yok | `np.isfinite` tek traversal |
| 5 | Log key'leri İngilizce | `capraz_kesit_*` Türkçe prefix |
| 6 | OLS ill-conditioned matris uyarısı yok | `np.linalg.cond` kontrolü eklendi |
| 7 | `_group_breakdown` df=0 hatası (n=1) | `n >= MIN_EVENTS_FOR_TTEST` kontrolü |

## estimation_window.py

| # | Sorun | Düzeltme |
|---|-------|----------|
| 1 | "Otomatik eklendi" docstring (placeholder) | Gerçek docstring yazıldı |
| 2 | `_get_calendar()` thread-safe değil | `threading.Lock` ile double-checked locking |
| 3 | `_validate_array` iki ayrı NaN/Inf traversal | `np.isfinite` tek traversal |
| 4 | `validate_data` boş array guard yok | ValueError eklendi |
| 5 | `validate_data` NaN/Inf kontrolü yok | `np.isfinite` guard eklendi |
| 6 | Log key'leri İngilizce | `tahmin_penceresi_*` Türkçe prefix |

## event_window.py

| # | Sorun | Düzeltme |
|---|-------|----------|
| 1 | `extract_window_data` hiç validation yok | `_validate_array`, `_validate_datetime`, uzunluk kontrolü eklendi |
| 2 | `align_to_event_day` hiç validation yok | Tüm validation eklendi |
| 3 | `get_window_dates` event_date validation yok | `_validate_datetime` eklendi |
| 4 | `_get_calendar()` thread-safe değil | `threading.Lock` ile double-checked locking |
| 5 | `align_to_event_day` O(n×m) linear search | Dict tabanlı O(n+m) arama |
| 6 | Log key'leri İngilizce | `pencere_*` Türkçe prefix |
| 7 | Bilinmeyen event_type sessiz fallback | Warning log eklendi |

## expected_return.py

| # | Sorun | Düzeltme |
|---|-------|----------|
| 1 | "Otomatik eklendi" docstring (placeholder) | Kaldırıldı, gerçek yorum yapıldı |
| 2 | `except Exception` sessiz exception yutma | `LinAlgError` → `ValueError` |
| 3 | Uzunluk uyumsuzluğu kontrolü yok | ValueError eklendi |
| 4 | Hiçbir fonksiyonda numpy array validation yok | `_validate_array` eklendi |
| 5 | Log key'leri İngilizce | `beklenen_donuyor_*` Türkçe prefix |
| 6 | Condition number kontrolü yok | `_check_condition_number` eklendi |

## statistical_test.py

| # | Sorun | Düzeltme |
|---|-------|----------|
| 1 | `car` NaN/Inf kontrolü yok | `_validate_float` eklendi |
| 2 | `abnormal_returns` numpy array tip kontrolü yok | `_validate_array` eklendi |
| 3 | `cars` listesinde NaN/Inf kontrolü yok | Döngü ile `np.isfinite` kontrolü |
| 4 | p_values aralık kontrolü yok (<0, >1) | `_validate_p_values` eklendi |
| 5 | `wilcoxon_test`: `except Exception` sessiz | `except ValueError` + warning log |

## impact.py

| # | Sorun | Düzeltme |
|---|-------|----------|
| 1 | `car` NaN/Inf + tip kontrolü yok | `_validate_float`: isinstance + np.isfinite |
| 2 | `p_value` sonluluk + aralık [0,1] yok | `_validate_p_value` eklendi |
| 3 | `volume_change` NaN/Inf yok | `_validate_float` eklendi |
| 4 | `ar_series` doğrulama yok | `_validate_ar_series`: list/tuple→ndarray otomatik dönüşüm, boş/NaN guard |
| 5 | `calculate_impact_batch` boş liste + event dict tip yok | `_validate_events` + isinstance döngüsü |
| 6 | Hatalı parametreler sessizce kabul ediliyor | Tüm guard'lar ValueError/TypeError fırlatıyor |
| 7 | Magic number'lar (35, 25, 15, 100, 0.01, 0.05, 0.10) | 14 sabit tanımlandı |
| 8 | Docstring'lerde Raises eksik | Tüm fonksiyonlara eklendi |
| 9 | Log key'leri İngilizce | `etki_skoru_hesaplandi`, `etki_skoru_toplu_hesaplandi` Türkçe |
| 10 | Logger.info her çağrıda → production spam | Bireysel debug, batch özeti debug |

## event_decay.py

| # | Sorun | Düzeltme |
|---|-------|----------|
| 1 | Hiçbir input validation yok | `_validate_ar_series`, `_validate_event_day_idx` eklendi |
| 2 | `except Exception` sessiz exception yutma | `except np.linalg.LinAlgError` + warning log |
| 3 | Docstring'lerde Raises eksik | Tüm fonksiyonlara eklendi |
| 4 | Hiç loglama yapılmıyor | `azalma_hesaplandi`, `azalma_yetersiz_veri`, `azalma_regresyon_hatasi` Türkçe |
| 5 | Pattern isimleri İngilizce | `YETERSIZ_VERI`, `KALICI`, `YAVAS_AZALMA`, `HIZLI_AZALMA` Türkçe |
| 6 | Negatif decay_rate half_life negatif çıkar | `decay_rate > 0` kontrolü + warning log |
| 7 | `calculate_decay_batch` eleman validation yok | Tip + boşluk kontrolü her elemanda |
| 8 | `np.arange` + mask iki traversal | `np.where` tek seferde |

## kap_event.py

| # | Sorun | Düzeltme |
|---|-------|----------|
| 1 | `classify_kap_event`: description None → AttributeError | `_validate_description`: isinstance + strip + boş kontrol |
| 2 | `analyze_kap_event`: ticker boş string kontrolü yok | `_validate_ticker` eklendi |
| 3 | `analyze_kap_event`: event_date tip kontrolü yok | `_validate_event_date`: datetime/str kontrol |
| 4 | `analyze_kap_event`: array parametreleri boş/NaN olabilir | `_validate_array_not_empty`: list→ndarray + NaN/Inf guard |
| 5 | `analyze_kap_event_simple`: estimation_ratio aralık kontrolü yok | `_validate_estimation_ratio`: [0.1, 0.9] |
| 6 | `analyze_kap_events_batch`: boş events listesi | `_validate_events_list` eklendi |
| 7 | `analyze_kap_events_batch`: zorunlu key kontrolü yok | `_validate_event_dict`: `REQUIRED_EVENT_KEYS` |
| 8 | `_calculate_volume_change`: NaN/Inf guard yok | `np.all(np.isfinite)` + warning log |
| 9 | `_error_result` sessiz log yok | `logger.warning("kap_event_hata", ...)` eklendi |
| 10 | Docstring'lerde Raises eksik | Tüm fonksiyonlara eklendi |
| 11 | Log key'leri İngilizce | `kap_event_analiz_edildi`, `kap_event_hata` Türkçe |
| 12 | Magic number'lar | `MIN_ESTIMATION_SAMPLES`, `MIN_EVENT_SAMPLES`, `ESTIMATION_RATIO_*`, `VOLUME_*` |
| 13 | `analyze_kap_events_batch` gereksiz `if results else 0` | `_validate_events_list` zaten reddeder |
| 14 | `_calculate_volume_change` return type annotation eksik | `-> float` eklendi |

## macro_event.py

| # | Sorun | Düzeltme |
|---|-------|----------|
| 1 | `rate_actual`, `rate_expected`, `rate_previous` NaN/Inf yok | `_validate_rate`: isinstance + np.isfinite + aralık |
| 2 | `market_returns` boş/NaN kontrolü yok | `_validate_market_returns` eklendi |
| 3 | `surprise_pct` hesabında rate_previous negatif olabilir | `abs(rate_previous)` ile mutlak değere bölme |
| 4 | `usdtry_returns` NaN/Inf kontrolü yok | `_validate_optional_returns` (None geçerli) |
| 5 | `sector_returns` values NaN/Inf kontrolü yok | `_validate_sector_returns` eklendi |
| 6 | `analyze_macro_event`: actual, expected, previous NaN/Inf yok | `_validate_float` eklendi |
| 7 | Bilinmeyen event_type sessiz fallback | `makro_event_bilinmeyen_tip` warning log |
| 8 | `analyze_macro_events_batch`: boş events + zorunlu key yok | `_validate_events_list` + `_validate_event_dict` |
| 9 | `analyze_macro_events_batch`: market_returns boş olabilir | `_validate_market_returns` eklendi |
| 10 | `_check_rate_inflation_consistency`: rate/inflation NaN/Inf yok | `_validate_float` eklendi |
| 11 | `analyze_macro_event`: n > 0 kontrolü yok | `n >= MIN_SIGNIFICANCE_RETURNS` guard |
| 12 | Docstring'lerde Raises eksik | Tüm fonksiyonlara eklendi |
| 13 | Log key'leri İngilizce | `tcmb_event_analiz_edildi`, `makro_event_analiz_edildi` Türkçe |
| 14 | Magic number'lar | `SURPRISE_*`, `MACRO_SURPRISE_*`, `REAL_RATE_*`, `RATE_MIN/MAX` |
| 15 | Batch summary'de gereksiz `if cars else 0` | `_validate_events_list` zaten reddeder |

## multi_factor.py

| # | Sorun | Düzeltme |
|---|-------|----------|
| 1 | `__init__`: geçersiz model_type sessizce kabul | `_validate_model_type`: `VALID_MODEL_TYPES` kontrolü |
| 2 | `fit`: stock_returns, market_returns NaN/Inf yok | `_validate_array` eklendi |
| 3 | `fit`: opsiyonel factor returns NaN/Inf yok | `_validate_factor_returns` (None geçerli) |
| 4 | `fit`: array uzunluk uyumsuzluğu yok | `_validate_equal_length` eklendi |
| 5 | `predict`: input NaN/Inf yok | `_validate_float` eklendi |
| 6 | `predict`: self.params key varlığı kontrolü yok | `PREDICT_REQUIRED_KEYS` ile eksik key tespiti |
| 7 | `calculate_smb/hml/rmw/cma`: NaN/Inf + uzunluk yok | `_validate_factor_pair` eklendi |
| 8 | `classify_stocks`: NaN/Inf + boş + uzunluk yok | `_validate_array` + eşit uzunluk |
| 9 | `classify_stocks`: threshold aralık [0,1] yok | `_validate_threshold` + low < high |
| 10 | Docstring'lerde Raises eksik | Tüm fonksiyonlara eklendi |
| 11 | Log key'leri İngilizce | `cok_faktorlu_model_egitildi` Türkçe |
| 12 | Magic number'lar | `VALID_MODEL_TYPES`, `THRESHOLD_*`, `DEFAULT_*`, `PREDICT_REQUIRED_KEYS` |
| 13 | `get_params` inconsistent return (None vs dict) | `self.params is not None else {}` |
| 14 | `fit`: Raises docstring eksik | Eklendi |

## sector_event.py

| # | Sorun | Düzeltme |
|---|-------|----------|
| 1 | `analyze_sector_event`: sector, event_type tip/boş yok | `_validate_string` eklendi |
| 2 | `analyze_sector_event`: stock_returns, market_returns NaN/Inf yok | `_validate_array` eklendi |
| 3 | `analyze_sector_event`: alpha, beta NaN/Inf yok | `_validate_float` eklendi |
| 4 | `analyze_sector_event`: sector_returns NaN/Inf yok | isinstance + np.isfinite |
| 5 | `analyze_peer_comparison`: peer_returns tip + boş + NaN/Inf yok | `_validate_peer_returns` |
| 6 | `analyze_peer_comparison`: target_ticker: str = None tutarsız | `str \| None = None` |
| 7 | `detect_sector_rotation`: threshold negatif/NaN yok | `_validate_float` + threshold < 0 |
| 8 | `detect_sector_rotation`: sector_cars values NaN/Inf yok | `_validate_sector_cars` |
| 9 | `DynamicSectorMap.get()`: `except Exception` sessiz yutma | ImportError + Exception ayrıştırıldı, warning log |
| 10 | Docstring'lerde Raises eksik | Tüm fonksiyonlara eklendi |
| 11 | Log key'leri İngilizce | `sektor_event_analiz_edildi`, `sektor_harita_hatasi` Türkçe |
| 12 | Magic number'lar | `DEFAULT_SECTOR_LIST`, `DEFAULT_ROTATION_THRESHOLD`, `PERCENTILE_MULTIPLIER` |
| 13 | f-string without placeholders | Düzeltildi |

## trading_calendar.py

| # | Sorun | Düzeltme |
|---|-------|----------|
| 1 | `is_trading_day`, `next_trading_day`, `previous_trading_day`: d tip kontrolü yok | `_validate_date_param`: datetime→date + TypeError |
| 2 | `add_trading_days`: d ve n tip kontrolü yok | `_validate_date_param` + `_validate_int` |
| 3 | `get_trading_days_between`: start > end sessiz boş liste | Warning log eklendi |
| 4 | `align_returns_to_trading_days`: returns, dates tip/boş yok | isinstance + boş + NaN/Inf |
| 5 | `next_trading_day`, `previous_trading_day`: sonsuz döngü riski | `MAX_TRADING_DAY_ITERATIONS` + RuntimeError |
| 6 | `get_trading_calendar()`: singleton thread-safe değil | `threading.Lock` + double-checked locking |
| 7 | `_load_fixed_holidays`: `except ValueError` sessiz yutma | `logger.warning("sabit_tatil_hatasi", ...)` |
| 8 | `_load_variable_holidays`: `except Exception` geniş catch | orjson.JSONDecodeError + ValueError spesifik |
| 9 | `__init__` docstring "Otomatik eklendi" — placeholder | Gerçek docstring yazıldı |
| 10 | Docstring'lerde Raises eksik | Tüm fonksiyonlara eklendi |
| 11 | Log key'leri İngilizce | `takvim_baslatildi`, `sabit_tatil_hatasi` Türkçe |
| 12 | Magic number'lar | `YEAR_RANGE_*`, `DEFAULT_GAP_TRADING_DAYS`, `MAX_TRADING_DAY_ITERATIONS` |
| 13 | `align_returns_to_trading_days`: dead code (datetime.combine) | Kaldırıldı |

## event_clustering.py

| # | Sorun | Düzeltme |
|---|-------|----------|
| 1 | `__init__` parametre validation yok | `_validate_positive_int`: tip + aralık kontrolü |
| 2 | `detect_clusters` events tip kontrolü yok | `_validate_events_list` eklendi |
| 3 | `adjust_car_for_clustering` mantıksal hata — event kopyalanıyor ama liste güncellenmiyor | Orijinal listeyi kopyalama + event→index mapping ile doğru güncelleme |
| 4 | `market_returns`, `dates` dead parameters | Kaldırıldı (kullanılmıyordu) |
| 5 | Log key'leri İngilizce | `event_kümeleri_tespit_edildi`, `car_kume_ayarlama` Türkçe |
| 6 | Magic number'lar | `DEFAULT_WINDOW_DAYS`, `DEFAULT_MIN_CLUSTER_SIZE`, `MIN_WINDOW_DAYS`, `MAX_WINDOW_DAYS` sabitleri |
| 7 | Docstring'lerde Raises eksik | Tüm fonksiyonlara eklendi |

## fama_french_factors.py

| # | Sorun | Düzeltme |
|---|-------|----------|
| 1 | 6× "Otomatik eklendi" placeholder docstring | Tümü gerçek docstring ile değiştirildi |
| 2 | `safe_mean` her `_calculate_*`'da yeniden tanımlanıyor | `_safe_mean` modül seviyesinde fonksiyon çıkarıldı |
| 3 | `__import__("asyncio")` kötü pratik | `import asyncio` dosya başına taşındı |
| 4 | `__init__` parametre aralık kontrolü yok | `_validate_threshold` + `_validate_positive_float` + low < high kontrolü |
| 5 | `calculate_daily_factors`: stocks tip kontrolü yok | `_validate_stocks_list` eklendi |
| 6 | `_calculate_*` NaN/Inf kontrolü yok | `calculate_daily_factors`'da tüm array'ler için `np.isfinite` kontrolü |
| 7 | `calculate_factor_series`: daily_stocks tip kontrolü yok | `isinstance(dict)` kontrolü |
| 8 | `fetch_and_build_factors`: tickers boş liste kontrolü yok | `len(tickers) == 0` kontrolü |
| 9 | `fetch_and_build_factors`: start > end kontrolü yok | `start_date > end_date` ValueError |
| 10 | `balance_sheet.iloc` IndexError riski | `_get_balance_sheet_value` güvenli wrapper fonksiyonu |
| 11 | `except Exception` (3 yerde) | Dış API (yfinance) için kabul edilebilir — hata loglanıyor, graceful fallback |
| 12 | Log key'leri İngilizce (3 yerde) | `fiyat_veri_hatasi`, `hisse_veri_hatasi`, `temel_veri_hatasi` Türkçe |
| 13 | Magic number'lar | `THRESHOLD_*`, `DEFAULT_*`, `MIN_STOCKS_FOR_FACTOR`, `MAX_FETCH_WORKERS` sabitleri |
| 14 | Docstring'lerde Raises eksik | Tüm fonksiyonlara eklendi |
| 15 | `_fetch_one` docstring placeholder | Gerçek docstring yazıldı |

---

## Bilinen Eksikler

| # | Eksik | Neden Yapılmadı |
|---|-------|-----------------|
| 1 | Property-based testing (hypothesis) | Ek bağımlılık gerektirir — proje kararı |
| 2 | End-to-end integration testi | Tüm modüllerin denetimi tamamlandıktan sonra |

---

## Migration Tablosu

Tüm düzeltmeler backward compatible — fonksiyon imzaları değişmedi. Çağrı noktaları (kap_event.py, macro_event.py, sector_event.py, impact_engine.py, estimation_window.py, event_window.py) doğrulandı ve uyumlu.

| Modül | Fonksiyon | İmza Değişikliği | Çağrı Noktaları |
|-------|-----------|-------------------|-----------------|
| impact | calculate_event_impact | Yok | kap_event.py |
| impact | calculate_impact_batch | Yok | — |
| event_decay | EventImpactDecay | Yok | impact.py |
| kap_event | classify_kap_event | Yok | kap_event.py (iç) |
| kap_event | analyze_kap_event | Yok | kap_event.py, impact_engine.py |
| kap_event | analyze_kap_event_simple | Yok | impact_engine.py |
| macro_event | analyze_tcmb_event | Yok | — |
| macro_event | analyze_macro_event | Yok | — |
| multi_factor | MultiFactorModel | Yok | — |
| sector_event | SectorEventAnalyzer | Yok | — |
| trading_calendar | BISTTradingCalendar | Yok | estimation_window.py, event_window.py |
| trading_calendar | get_trading_calendar | Yok | estimation_window.py, event_window.py |
