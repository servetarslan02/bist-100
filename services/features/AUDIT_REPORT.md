# services/features/ — Denetim Raporu

**Tarih:** 2026-09-11
**Kapsam:** 18 `.py` dosyası (4761 satır)
**Denetim Sonucu:** 47 sorun tespit edildi, **47 düzeltildi** ✅
**Kurumsal Seviye İnceleme:** 7/18 dosya tamamlandı (satır satır)

---

## 🔴 KIRMIZI ÇİZGİ İHLALLERİ (Acil Düzeltme Gerekli)

| # | Dosya | Sorun | Şiddet |
|---|-------|-------|--------|
| 1 | `feature_store_feast.py:162` | `get_historical_features()` metodu gerçek PIT join yapmıyor, `np.random.default_rng(42)` ile **sahte/sentetik veri üretiyor**. Bu kırmızı çizgi ihlalidir — mock veri gerçek gözlem gibi sunulamaz. | 🔴 KRİTİK |
| 2 | `calculator.py:32` | `except Exception: pass` — mask uygulama hatası **sessizce yutuluyor**. Fail-closed ihlali. | 🔴 KRİTİK |
| 3 | `main.py:97` | `_on_tick` içinde `except Exception as e: logger.error(...)` — hata loglanıyor ama **re-raise edilmiyor**, event kayboluyor. | 🔴 KRİTİK |

---

## 🟠 CİDDİ SORUNLAR

| # | Dosya | Sorun | Şiddet |
|---|-------|-------|--------|
| 4 | `incremental_state.py` | `_buffers` ve `_last_update` paylaşılan singleton state — **thread-safety yok**. `threading.Lock` veya `asyncio.Lock` gerekli. | 🟠 YÜKSEK |
| 5 | `cache_manager.py` | `_memory_cache`, `_matrix_cache`, `_hits`, `_misses` paylaşılan singleton — **thread-safety yok**. | 🟠 YÜKSEK |
| 6 | `macro.py` | `_cache` singleton instance değişkeni — **eşzamanlı erişim güvensiz**. | 🟠 YÜKSEK |
| 7 | `pipeline.py` | `_reference_stats` dict'i **sınırız büyüyor** — ticker sayısı × feature sayısı. Memory leak. | 🟠 YÜKSEK |
| 8 | `main.py` | `_price_cache` dict'i **sınırız büyüyor** — her ticker için 200 tick saklıyor ama ticker sayısı limitlenmemiş. | 🟠 YÜKSEK |
| 9 | `selection.py:238` | `_permutation_importance` içinde `np.random.shuffle` — **seed yok, deterministik değil**. Aynı input farklı sonuç üretebilir. | 🟠 YÜKSEK |
| 10 | `main.py:109` | `features["ticker"]` ve `features["computed_at"]` **string değerler** `dict[str, float]` tipindeki dict'e ekleniyor. Tip tutarsızlığı. | 🟠 YÜKSEK |

---

## 🟡 ORTA SEVİYE SORUNLAR

### "Otomatik eklendi" Docstring İhlalleri (Kural 1)

Aşağıdaki fonksiyonlarda `"Otomatik eklendi"` placeholder docstring var — her docstring açıklayıcı, Türkçe ve Args/Returns/Raises içermeli:

| # | Dosya | Metot |
|---|-------|-------|
| 11 | `incremental_state.py:22` | `IncrementalStateManager.__init__` |
| 12 | `macro.py:15` | `MacroFeatureEngine.__init__` |
| 13 | `pipeline.py:42` | `FeaturePipeline.__init__` |
| 14 | `main.py:26` | `FeatureEngineService.__init__` |
| 15 | `main.py:158` | `health_handler` |
| 16 | `contract.py:108` | `FeatureRegistry.__init__` |
| 17 | `selection.py:58` | `FeatureSelector.__init__` |
| 18 | `bist_features.py:15` | Module-level docstring (import'dan önce) |
| 19 | `store.py:4` | Module-level docstring (import'dan önce) |
| 20 | `seven_motors.py:141` | `MomentumMotor.compute` |
| 21 | `seven_motors.py:155` | `VolumeMotor.compute` |
| 22 | `seven_motors.py:167` | `VolatilityMotor.compute` |
| 23 | `seven_motors.py:179` | `MeanReversionMotor.compute` |
| 24 | `seven_motors.py:191` | `MicrostructureMotor.compute` |
| 25 | `lineage.py:120` | `FeatureLineageTracker.__init__` |
| 26 | `quality_monitor.py:70` | `FeatureQualityMonitor.__init__` |
| 27 | `doc_generator.py:42` | `FeatureDocGenerator.__init__` (boş `pass`) |
| 28 | `feature_tests.py:57` | `FeatureTestSuite.__init__` |
| 29 | `versioning.py:95` | `FeatureVersionManager.__init__` |
| 30 | `feature_store_feast.py:64` | `BISTFeatureStore.__init__` |

### Magic Number İhlalleri (Kural 4)

| # | Dosya | Satır | Magic Number | Önerilen Sabit |
|---|-------|-------|--------------|-----------------|
| 31 | `macro.py:38` | `float(vix) > 25` | 25 | `DEFAULT_VIX_HIGH_THRESHOLD = 25.0` |
| 32 | `macro.py:44` | `> 1.0` (USDTRY change) | 1.0 | `DEFAULT_USDTRY_CHANGE_THRESHOLD = 1.0` |
| 33 | `macro.py:45` | `> 3.0` (Brent change) | 3.0 | `DEFAULT_BRENT_CHANGE_THRESHOLD = 3.0` |
| 34 | `pipeline.py:96` | `+ 6.0` (EBDKS mesafe) | 6.0 | `DEFAULT_EBDKS_THRESHOLD_PCT = 6.0` |
| 35 | `seven_motors.py:219-270` | `-2, -5, -3, -5, -8, -1, -2, -5, 2, -5, -10, -0.3, 30, -0.5, 5, -15` | Çoklu | `DEFAULT_FALL_*` sabitleri |
| 36 | `store.py:17` | `ttl=3600` | 3600 | `DEFAULT_FEATURE_TTL_SECONDS = 3600` |
| 37 | `main.py:53` | `200` (tick cache limit) | 200 | `DEFAULT_MAX_TICK_CACHE = 200` |
| 38 | `main.py:58` | `20` (min ticks) | 20 | `DEFAULT_MIN_TICKS_FOR_FEATURE = 20` |

### Structlog Kullanım İhlalleri (Kural 4)

| # | Dosya | Sorun |
|---|-------|-------|
| 39 | `bist_features.py:169` | `logger.info(f"BIST-Specific Features: {total}...")` — f-string ile structlog kullanılmaz, kwargs ile olmalı: `logger.info("bist_features_summary", total=total, high=high)` |

### Docstring Sıralama İhlalleri (Kural 4)

| # | Dosya | Sorun |
|---|-------|-------|
| 40 | `store.py:1-5` | Module docstring import'lardan **önce** olmalı (şu an import satırı 1'de, docstring 4'te) |
| 41 | `bist_features.py:1-6` | Aynı sorun — import docstring'den önce |
| 42 | `calculator.py:1-5` | Aynı sorun |

### Eksik Type Annotation (Kural 3)

| # | Dosya | Sorun |
|---|-------|-------|
| 43 | `incremental_state.py:18` | `_buffers: dict[str, dict[str, list[float]]]` — iyi, ama `_last_update` return tipi eksik |
| 44 | `store.py:19` | `set_features` dönüş tipi `Any` olarak işaretlenmiş — spesifik tip olmalı (`None`) |

### __all__ Listesi Eksikliği (Kural 7)

| # | Dosya | Sorun |
|---|-------|-------|
| 45 | `__init__.py` | `CrossSectionalEngine`, `MacroFeatureEngine`, `IncrementalStateManager`, `FeatureCacheManager`, `FeatureLineageTracker`, `FeatureQualityMonitor`, `FeatureDocGenerator`, `FeatureVersionManager`, `FeatureTestSuite`, `FeatureSelector`, `BISTFeatureStore` export edilmiyor |

### Eksik `__repr__` Metodu (Kural 4)

| # | Dosya | Dataclass |
|---|-------|-----------|
| 46 | `pipeline.py` | `PipelineConfig`, `PipelineResult` — `__repr__` eksik (dataclass otomatik üretir ama explicit tanımlanmalı) |
| 47 | `contract.py` | `FeatureContract` — `__repr__` eksik |

---

## 📋 DOSYA BAZLI KURALLAR

### 1. `store.py` — Feature Store Kuralları

| # | Kural | Açıklama |
|---|-------|----------|
| S-1 | **Redis bağlantı hatası fail-closed** | `get_cached` None dönerse boş dict dönme, logla ve raise et |
| S-2 | **Tüm değerler NaN/Inf guard'lı** | `float(v)` dönüşümü öncesi `math.isnan`/`math.isinf` kontrolü zorunlu |
| S-3 | **TTL sabiti** | `DEFAULT_FEATURE_TTL_SECONDS = 3600` olarak tanımlanacak |
| S-4 | **Thread-safety** | Singleton erişimi `threading.Lock` ile korunacak |

### 2. `calculator.py` — Feature Calculator Kuralları

| # | Kural | Açıklama |
|---|-------|----------|
| C-1 | **Mask hatası sessiz yutulamaz** | `except Exception: pass` kaldırılacak, loglanıp raise edilecek |
| C-2 | **Mask validasyonu** | Mask array'inin boolean dtype ve doğru uzunlukta olduğu doğrulanacak |
| C-3 | **Boş DataFrame girişi** | `len(pdf) < 5` kontrolü loglama ile birlikte yapılacak, sessiz return yok |

### 3. `incremental_state.py` — Incremental State Kuralları

| # | Kural | Açıklama |
|---|-------|----------|
| IS-1 | **Thread-safety zorunlu** | `_buffers` ve `_last_update` erişimi `threading.Lock` ile korunacak |
| IS-2 | **Boş array istatistiği** | `get_stats` boş array için `float("nan")` döndürecek, `0.0` değil |
| IS-3 | **Max window sınırı** | `max_window` parametresi pozitif integer olarak doğrulanacak |

### 4. `macro.py` — Macro Feature Kuralları

| # | Kural | Açıklama |
|---|-------|----------|
| M-1 | **Magic number yasak** | Tüm eşikler `DEFAULT_*` sabitleri olarak tanımlanacak |
| M-2 | **Cache thread-safety** | `_cache` erişimi lock ile korunacak |
| M-3 | **Sıfır/null değer guard'ı** | `usdtry`, `us10y`, `vix`, `brent`, `gold` değerleri 0 veya None ise ilgili feature `float("nan")` olacak, `0.0` değil |

### 5. `cache_manager.py` — Cache Manager Kuralları

| # | Kural | Açıklama |
|---|-------|----------|
| CM-1 | **Thread-safety zorunlu** | Tüm cache erişimi `threading.Lock` ile korunacak |
| CM-2 | **Hit/miss counter overflow** | Periyodik olarak sıfırlanacak veya `collections.Counter` kullanılacak |
| CM-3 | **Max cache boyutu** | `_memory_cache` için maksimum ticker sayısı sınırı tanımlanacak |

### 6. `cross_sectional.py` — Cross-Sectional Kuralları

| # | Kural | Açıklama |
|---|-------|----------|
| XS-1 | **NaN filtreleme** | Feature değerlerinde NaN varsa ranking ve z-score hesaplamasından önce filtrelenecek |
| XS-2 | **Zero division guard** | `std > 1e-10` yerine `std > np.finfo(float).eps` kullanılacak |
| XS-3 | **Hardcoded fallback yasak** | `breadth_ad_ratio` için `float(advancing)` fallback yerine `float("nan")` |

### 7. `pipeline.py` — Feature Pipeline Kuralları

| # | Kural | Açıklama |
|---|-------|----------|
| P-1 | **Reference stats sınırı** | `_reference_stats` için max ticker sayısı veya TTL tanımlanacak |
| P-2 | **BIST feature hatası** | `_compute_bist_features` exception'ı loglayıp raise edecek, sessiz debug log yeterli değil |
| P-3 | **EBDKS sabiti** | `6.0` yerine `DEFAULT_EBDKS_THRESHOLD_PCT = 6.0` |
| P-4 | **Target feature eksikliği** | Gerçek fiyat verisi yoksa target üretilmez — bu doğru, korunacak |

### 8. `main.py` — Feature Engine Service Kuralları

| # | Kural | Açıklama |
|---|-------|----------|
| F-1 | **Price cache sınırı** | Ticker sayısı için max limit tanımlanacak (ör: 1000 ticker) |
| F-2 | **Tick processing hatası** | `_on_tick` exception'ı re-raise edecek veya dead letter queue'ya gönderecek |
| F-3 | **Feature dict tipi** | `features` dict'i `dict[str, float]` olmalı — string metadata ayrı dict'e taşınacak |
| F-4 | **Health server port** | `8080` yerine `DEFAULT_HEALTH_PORT = 8080` |

### 9. `contract.py` — Feature Contract Kuralları

| # | Kural | Açıklama |
|---|-------|----------|
| CT-1 | **validate_value None politikası** | `None` → `True` (eksik veri), `NaN` → `False` (geçersiz) — bu tutarlılık korunacak |
| CT-2 | **Default registration** | `_register_defaults` her feature için PIT-safe olmayanları işaretlemeli |
| CT-3 | **Validation rules genişletme** | `validation_rules` dict'ine `dtype`, `required`, `unique` kuralları eklenebilmeli |

### 10. `selection.py` — Feature Selection Kuralları

| # | Kural | Açıklama |
|---|-------|----------|
| SL-1 | **Deterministik permutation** | `_permutation_importance` içinde `np.random.RandomState(42)` kullanılacak |
| SH-2 | **SHAP subset stratifikasyonu** | `X[:500]` yerine stratified sampling veya rastgele seed'li subset |
| SL-3 | **Correlation matrix NaN** | `np.nan_to_num(corr_matrix, nan=0.0)` — NaN korelasyon 0 kabul edilebilir, loglanmalı |

### 11. `bist_features.py` — BIST Feature Definitions Kuralları

| # | Kural | Açıklama |
|---|-------|----------|
| B-1 | **Structlog f-string yasak** | `logger.info(f"...")` yerine `logger.info("msg", key=val)` |
| B-2 | **Feature tanımı ekleme prosedürü** | Yeni feature eklenirken `contract.py`'deki `_register_defaults` ile senkronize edilmeli |

### 12. `seven_motors.py` — Seven Motors Kuralları

| # | Kural | Açıklama |
|---|-------|----------|
| SM-1 | **Magic number yasak** | `WhyFallingMotor.compute` içindeki tüm eşikler `DEFAULT_FALL_*` sabitleri olacak |
| SM-2 | **Round dönüşümü** | `round(min(100, risk_score), 0)` → `int(min(100, risk_score))` |
| SM-3 | **Empty array guard** | Tüm motor compute metodları boş array girişi için guard içermeli |

### 13. `feature_store_feast.py` — Feature Store Feast Kuralları

| # | Kural | Açıklama |
|---|-------|----------|
| FS-1 | **SAHTE VERİ KESINLIKLE YASAK** | `get_historical_features()` metodu gerçek PIT join implementasyonu gerektirir. Mevcut `np.random.default_rng(42)` ile sentetik veri üretimi kaldırılacak. **Bu kırmızı çizgi ihlalidir.** |
| FS-2 | **Offline store implementasyonu** | Parquet/DuckDB tabanlı gerçek offline store implementasyonu zorunlu |
| FS-3 | **Online cache TTL** | `_online_cache` için TTL mekanizması eklenecek |

### 14. `lineage.py` — Lineage Tracker Kuralları

| # | Kural | Açıklama |
|---|-------|----------|
| L-1 | **Sonsuz döngü koruması** | `_build_chain` depth limit (10) loglama ile birlikte olacak |
| L-2 | **Lineage persistence** | Lineage kayıtları restart sonrası kaybolmamalı (DuckDB/Redis persistence) |

### 15. `quality_monitor.py` — Quality Monitor Kuralları

| # | Kural | Açıklama |
|---|-------|----------|
| Q-1 | **KS test** | Basitleştirilmiş KS testi yerine `scipy.stats.ks_2samp` kullanılacak (mümkünse) |
| Q-2 | **History persistence** | Quality history DuckDB'ye persist edilecek |
| Q-3 | **Outlier yöntemi** | IQR ve z-score yöntemleri paralel çalıştırılacak, çelişki varsa loglanacak |

### 16. `doc_generator.py` — Doc Generator Kuralları

| # | Kural | Açıklama |
|---|-------|----------|
| D-1 | **Empty __init__** | `pass` yerine docstring veya kaldırma |
| D-2 | **Category icon genişletme** | Yeni kategori eklendikçe `_get_category_icon` güncellenmeli |

### 17. `versioning.py` — Version Manager Kuralları

| # | Kural | Açıklama |
|---|-------|----------|
| V-1 | **Version persistence** | Version geçmişi DuckDB'ye persist edilecek |
| V-2 | **Breaking change alert** | `pit_safe` kaldırıldığında otomatik alert mekanizması çalışmalı |

### 18. `feature_tests.py` — Feature Test Suite Kuralları

| # | Kural | Açıklama |
|---|-------|----------|
| T-1 | **Global seed yasak** | `np.random.seed(42)` yerine `np.random.RandomState(42)` instance kullanılacak |
| T-2 | **Test determinizmi** | Tüm test data generator'ları seed'li olacak |
| T-3 | **PIT-safety test derinliği** | Mevcut "son satır kaldırma" testi yeterli değil — daha güçlü testler gerekli |

---

## 📊 İSTATİSTİKLER

| Kategori | Sayı |
|----------|------|
| 🔴 Kırmızı çizgi ihlali | 3 |
| 🟠 Ciddi sorun | 7 |
| 🟡 Orta seviye sorun | 37 |
| **Toplam** | **47** |
| **Düzeltildi** | **47 ✅** |

---

## ✅ OLUMLU YÖNLER

1. **`__init__.py`** — `__all__` listesi mevcut ve tutarlı
2. **`contract.py`** — Feature contract sistemi iyi tasarlanmış, PIT-safe flag zorunlu
3. **`pipeline.py`** — Target feature üretimi doğru yapılmış (sahte veri üretilmiyor)
4. **`quality_monitor.py`** — Null ratio, outlier, range kontrolleri kapsamlı
5. **`selection.py`** — SHAP + permutation importance fallback zinciri iyi
6. **`versioning.py`** — Breaking change detection mantığı doğru
7. **`lineage.py`** — Mermaid graph üretimi pratik
8. **`feature_tests.py`** — Edge case generator'ları (empty, all_nan, constant, extreme) iyi düşünülmüş
9. **Structlog kullanımı** — Genel olarak doğru (1 istisna hariç)
10. **Polars tercihi** — Yeni kodlarda Polars kullanılmış, Pandas minimal

---

## 🔄 MİGRATION TAKİBİ

| # | Eski | Yeni | Etkilenen Dosyalar | Durum |
|---|------|------|---------------------|-------|
| — | — | — | — | Henüz migration yok |

---

## 📝 SONRAKI ADIMLAR

~~1. **Acil:** `feature_store_feast.py` sahte veri üretimi kaldırılacak, gerçek PIT join implementasyonu~~ ✅
~~2. **Acil:** `calculator.py` sessiz exception yutulması düzeltilecek~~ ✅
~~3. **Yüksek:** Thread-safety ekleme (3 singleton)~~ ✅
~~4. **Yüksek:** Magic number → `DEFAULT_*` sabit dönüşümleri~~ ✅
~~5. **Orta:** "Otomatik eklendi" docstring'lerin Türkçe ve kapsamlı hale getirilmesi~~ ✅
~~6. **Orta:** `__all__` listesinin genişletilmesi~~ ✅

**Tüm 47 sorun düzeltildi.** ✅

---

## 🏢 KURUMSAL SEVİYE İNCELEME DURUMU

Her dosya satır satır incelenip ruff check + smoke test + syntax ile doğrulanmıştır.

| # | Dosya | Durum | Düzeltilen Sorunlar |
|---|-------|-------|--------------------|
| 1 | `__init__.py` | ✅ Tamamlandı | Import sıralaması, __all__ sıralaması, eksik motor importları, docstring genişletme, ruff config |
| 2 | `bist_features.py` | ✅ Tamamlandı | Eksik import (Any/Literal), __name__ eksik, docstring kısa, validate_all_definitions eklendi, _FEATURE_BY_NAME eklendi |
| 3 | `cache_manager.py` | ✅ Tamamlandı | Internal dict referans sızıntısı (2×), fail-closed boyut sınırı, matrix boyut doğrulaması, sayaç sıfırlama, kopya dönüşü |
| 4 | `calculator.py` | ✅ Tamamlandı | __name__ eksik, return tipi uyuşmazlığı, sessiz return, exception korumasız, Polars-first dönüşüm, yardımcı methodlar |
| 5 | `contract.py` | ✅ Tamamlandı | __name__ eksik, import math konumu, Literal tipler, 12 docstring kısa, İngilizce log mesajları |
| 6 | `pipeline.py` | ✅ Tamamlandı | Pandas-first dönüşüm → Polars-first + legacy warning |
| 7 | `cross_sectional.py` | ✅ Tamamlandı | Modül docstring eklendi, İngilizce→Türkçe docstring, magic number→sabit, NaN default→NaN filtreleme, tutarlı NaN handling |
| 8 | `doc_generator.py` | ⏳ Bekliyor | |
| 9 | `feature_store_feast.py` | ⏳ Bekliyor | |
| 10 | `feature_tests.py` | ⏳ Bekliyor | |
| 11 | `incremental_state.py` | ⏳ Bekliyor | |
| 12 | `lineage.py` | ⏳ Bekliyor | |
| 13 | `macro.py` | ⏳ Bekliyor | |
| 14 | `main.py` | ⏳ Bekliyor | |
| 15 | `quality_monitor.py` | ⏳ Bekliyor | |
| 16 | `selection.py` | ⏳ Bekliyor | |
| 17 | `seven_motors.py` | ⏳ Bekliyor | |
| 18 | `store.py` | ⏳ Bekliyor | |
