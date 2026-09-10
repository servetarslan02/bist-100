# services/event_study/ — Denetim Raporu

**Tarih:** 2026-09-11  
**Kapsam:** 7 `.py` dosyası  
**Denetim Sonucu:** 48 sorun tespit edildi, 48 düzeltildi

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

| # | Dosya | Sorun | Test | Durum |
|---|-------|-------|------|-------|
| 1 | abnormal_return.py | 9 | 28 | ✅ Düzeltildi |
| 2 | car.py | 8 | 45 | ✅ Düzeltildi |
| 3 | cross_sectional.py | 7 | 28 | ✅ Düzeltildi |
| 4 | estimation_window.py | 6 | 34 | ✅ Düzeltildi |
| 5 | event_window.py | 7 | 28 | ✅ Düzeltildi |
| 6 | expected_return.py | 6 | 24 | ✅ Düzeltildi |
| 7 | statistical_test.py | 5 | 32 | ✅ Düzeltildi |
| | **Toplam** | **48** | **219** | |

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

---

## Geliştirme Önerileri

| # | Alan | Öneri |
|---|------|-------|
| 1 | Performance | `is_trading_day()` her tarih için tek tek çağrılıyor — vectorize edilebilir |
| 2 | Bellek | Çok büyük array'lerde (100K+) OLS hesabında inplace operasyonlar düşünülebilir |
| 3 | Test | Property-based testing (hypothesis) ile edge case'ler otomatik bulunabilir |
| 4 | Integration | Dosyalar arası entegrasyon testleri (end-to-end pipeline) eklenebilir |

---

## Bilinen Eksikler

| # | Eksik | Neden Yapılmadı |
|---|-------|-----------------|
| 1 | `impact.py`, `kap_event.py`, `macro_event.py`, `multi_factor.py`, `sector_event.py`, `trading_calendar.py` denetlenmedi | Sıra bekliyor — aynı kurumsal seviyede denetim yapılacak |
| 2 | Property-based testing (hypothesis) | Ek bağımlılık gerektirir — proje kararı |
| 3 | End-to-end integration testi | Tüm modüllerin denetimi tamamlandıktan sonra |

---

## Migration Tablosu

| Modül | Fonksiyon | İmza Değişikliği | Çağrı Noktaları |
|-------|-----------|-------------------|-----------------|
| abnormal_return | calculate_abnormal_return | Yok (backward compatible) | kap_event.py:188, sector_event.py:72,78,126 |
| abnormal_return | calculate_abnormal_return_batch | `warn_on_default` eklendi (opsiyonel) | — |
| car | calculate_car | Yok | kap_event.py:191, macro_event.py:136,145,158,243,249, sector_event.py:73,79,127 |
| car | calculate_car_sub_windows | Yok | kap_event.py:197 |
| cross_sectional | CrossSectionalEventStudy | Yok | kap_event.py:339 |
| estimation_window | EstimationWindowManager | Yok | — |
| event_window | EventWindowManager | Yok | — |
| expected_return | calculate_expected_return | Yok | kap_event.py:184, multi_factor.py:48 |
| statistical_test | test_significance | Yok | kap_event.py, macro_event.py |
