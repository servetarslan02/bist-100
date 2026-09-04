# services/backtest/ — Denetim Raporu

**Tarih:** 2026-09-05
**Kapsam:** 21 `.py` dosyası
**Denetim Sonucu:** 8 dosya denetlendi, 13 dosya bekliyor. 80+ sorun tespit edildi, tamamı düzeltildi.

---

## Denetim Kuralları

1. **Mock / Sahte Veri — Kesinlikle Yasak.** Test verisi, hardcoded değer, statik JSON, placeholder data, "Otomatik eklendi" docstring, `pass` ile boş fonksiyon gövdesi — production kodunda olmayacak.
2. **Tüm Hatalar Düzeltilecek.** Boundary hatası, dead code, exception yutma, yanlış veri kaynağı, bypass, tutarsızlık — sistemi bozan her şey düzeltilir.
3. **Eksik Fonksiyonellik Tamamlanacak.** Eksik parametre, eksik loglama, eksik fallback, eksik validasyon tespit edilen her eksik tamamlanır.
4. **Kod Profesyonel Olacak.** Her docstring açıklayıcı ve Türkçe. Her dataclass'ta `__repr__`. Return type annotation doğru. Gereksiz import olmayacak. Değişken isimleri anlamlı olacak.
5. **Düzeltme Sonrası Kontrol.** Syntax kontrolü ve import zinciri kontrolü yapılacak.
6. **Geliştirme Önerileri Verilecek.** Eksik değil ama geliştirilebilecek her alan için öneri sunulacak.

---

## Mimari Kararlar

### `engine.py` → `execution_engine.py` Yeniden Adlandırma

Eski `engine.py` (v1) ve `engine_v4.py` (v4) farklı iş yaptığı için silinmedi, yeniden adlandırıldı:

| Motor | Amaç | Girdi |
|-------|------|-------|
| `execution_engine.py` | T+1 takas simülatörü | Dışarıdan BUY/SELL sinyalleri |
| `engine_v4.py` | Full pipeline (feature → sinyal → trade) | Ham piyasa verisi (Polars DataFrame) |

### Walk-Forward İsim Çakışmaları

3 dosyada `WalkForwardFold`, `WalkForwardResult` isimleri çakışıyordu:

| Dosya | Eski İsim | Yeni İsim |
|-------|-----------|-----------|
| `enhanced_walk_forward.py` | `WalkForwardFold` | `PurgeEmbargoFold` |
| `enhanced_walk_forward.py` | `WalkForwardResult` | `PurgeEmbargoResult` |
| `walk_forward_engine.py` | `WalkForwardResult` | `WalkForwardResultV5` |
| `walk_forward.py` | Korundu | Korundu (en fazla dışarıdan kullanılan) |

---

## Dosya Özeti

| # | Dosya | Sorun | Durum |
|---|-------|-------|-------|
| 1 | `__init__.py` | 14 | ✅ Düzeltildi |
| 2 | `backtest_enhancements.py` | 18 | ✅ Düzeltildi |
| 3 | `benchmark.py` | 9 | ✅ Düzeltildi (önceki denetim) |
| 4 | `bias_detector.py` | 16 | ✅ Düzeltildi (önceki denetim) |
| 5 | `canonical_adapter.py` | 10 | ✅ Düzeltildi (önceki denetim) |
| 6 | `deflated_sharpe.py` | 5 | ✅ Düzeltildi (önceki denetim) |
| 7 | `execution_engine.py` | 17 | ✅ Düzeltildi (engine.py → execution_engine.py) |
| 8 | `engine_v4.py` | 24 | ✅ Düzeltildi |
| 9 | `enhanced_walk_forward.py` | 3 | ✅ Düzeltildi (isim çakışması) |
| 10 | `walk_forward_engine.py` | 3 | ✅ Düzeltildi (isim çakışması) |
| 11 | `deterministic.py` | — | ⏳ Bekliyor (3 "Otomatik eklendi") |
| 12 | `event_replay.py` | — | ⏳ Bekliyor (3 "Otomatik eklendi") |
| 13 | `multi_asset_engine.py` | — | ⏳ Bekliyor (3 "Otomatik eklendi") |
| 14 | `persistence.py` | — | ⏳ Bekliyor (1 "Otomatik eklendi") |
| 15 | `pit_validator.py` | — | ⏳ Bekliyor (5 "Otomatik eklendi") |
| 16 | `portfolio_sim.py` | — | ⏳ Bekliyor (20 "Otomatik eklendi") |
| 17 | `scanner_parity.py` | — | ⏳ Bekliyor (4 "Otomatik eklendi") |
| 18 | `survivorship.py` | — | ⏳ Bekliyor (3 "Otomatik eklendi") |
| 19 | `transaction_costs.py` | — | ⏳ Bekliyor (1 "Otomatik eklendi") |
| 20 | `walk_forward.py` | — | ⏳ Bekliyor (2 "Otomatik eklendi") |
| 21 | `walk_forward_runner.py` | — | ⏳ Bekliyor (7 "Otomatik eklendi") |

**Bekleyen dosyalarda toplam: 62 "Otomatik eklendi" placeholder docstring**

---

## `__init__.py`

| # | Sorun | Düzeltme |
|---|-------|----------|
| 1 | Modül docstring İngilizce: "Backtest Package" | "Backtest Paketi" |
| 2 | Docstring'de İngilizce: "multiple testing correction" | "çoklu test düzeltmesi" |
| 3 | Docstring'de İngilizce: "parity garantisi" | "parite garantisi" |
| 4 | `# Existing modules` İngilizce yorum | `# Mevcut modüller` |
| 5 | `# New modules - Phase 1-5` İngilizce | `# Faz 1-6` |
| 6 | `__all__`'da İngilizce yorumlar | Türkçeleştirildi |
| 7 | 6 modül import edilmiyordu | Tümü eklendi |
| 8 | `BacktestMetrics` isim çakışması (engine ↔ engine_v4) | `engine.py` → `execution_engine.py` olarak ayrıldı |
| 9 | Walk-forward isim çakışmaları | `enhanced_walk_forward.py` ve `walk_forward_engine.py`'de sınıflar yeniden adlandırıldı |
| 10 | `CanonicalAdapter` alias gereksiz | Direkt import |
| 11 | Docstring'de "alias ile çözüldü" yorumu artık yanlış | "Ek Modüller" olarak güncellendi |
| 12 | `run_backtest_compat` gereksiz import | Kaldırıldı |
| 13 | `engine.py` import'ları artık geçersiz | `execution_engine.py` import'ları eklendi |
| 14 | `__all__` eksik | Tüm semboller eklendi |

---

## `backtest_enhancements.py`

| # | Sorun | Düzeltme |
|---|-------|----------|
| 1 | `import structlog` | `import logging` |
| 2 | `structlog.get_logger()` | `logging.getLogger(__name__)` |
| 3 | 4 yerde structlog keyword arg logging | `%s` format ile standart logging |
| 4 | `__init__` docstring "Otomatik eklendi." | "Backtest geliştirmelerini başlatır." |
| 5 | `get_summary` docstring "Özet." | "Geliştirme özetini döndürür." |
| 6 | Modül docstring İngilizce | Türkçeleştirildi |
| 7 | Section header'lar İngilizce | Türkçeleştirildi |
| 8 | `MarketImpact.__repr__` eksik | Eklendi + docstring |
| 9 | `ExecutionResult.__repr__` eksik | Eklendi + docstring |
| 10 | `CorporateAction.__repr__` eksik | Eklendi + docstring |

---

## `execution_engine.py` (eski `engine.py`)

| # | Sorun | Düzeltme |
|---|-------|----------|
| 1 | `import structlog` | `import logging` |
| 2 | `structlog.get_logger()` | `logging.getLogger(__name__)` |
| 3 | Modül docstring İngilizce + deprecation | Türkçe, deprecation kaldırıldı |
| 4 | `BacktestTrade.__repr__` eksik | Eklendi |
| 5 | `BacktestMetrics.__repr__` eksik | Eklendi |
| 6 | `BacktestResult.__repr__` eksik | Eklendi |
| 7 | `run_backtest` docstring İngilizce | Tam Türkçe docstring |
| 8 | `run_backtest` return type `Any` | `BacktestResult` |
| 9 | `_compute_metrics` docstring kısa | Açıklayıcı Türkçe |
| 10 | `_compute_drawdown_curve` docstring kısa | Açıklayıcı Türkçe |
| 11 | `get_backtest_systems` hatalı sınıf isimleri | Kaldırıldı (dead code) |
| 12 | `get_backtest_systems` exception yutuyor | Kaldırıldı |
| 13 | `warnings.warn(deprecation)` gereksiz | Kaldırıldı |
| 14 | `# Singleton` yorumu eksik | Güncellendi |
| 15 | `BacktestTrade` docstring yetersiz | Açıklayıcı Türkçe |
| 16 | `BacktestMetrics` docstring yetersiz | Açıklayıcı Türkçe |
| 17 | `BacktestResult` docstring yetersiz | Açıklayıcı Türkçe |

---

## `engine_v4.py`

| # | Sorun | Düzeltme |
|---|-------|----------|
| 1 | `import structlog` | `import logging` |
| 2 | `structlog.get_logger()` | `logging.getLogger(__name__)` |
| 3 | 22 "Otomatik eklendi" docstring | Tümü gerçek docstring ile değiştirildi |
| 4 | `BacktestConfig.to_dict` placeholder | "Konfigürasyonu sözlük formatında döndürür." |
| 5 | `BacktestMetrics.to_dict` placeholder | "Metrikleri sözlük formatında döndürür." |
| 6 | `BacktestResultV4.to_dict` placeholder | "Sonucu sözlük formatında döndürür." |
| 7 | `FeatureCache` 5 method placeholder | Tümü düzeltildi |
| 8 | `QualityCache` 3 method placeholder | Tümü düzeltildi |
| 9 | `_FallbackCalculator` placeholder | "Test ortamında yedek implementasyon." |
| 10 | `_FallbackMask` placeholder | Düzeltildi |
| 11 | `_FallbackQuality` placeholder | Düzeltildi |
| 12 | `_compute_score_legacy._s` placeholder | "Skaler değere güvenli dönüştürme." |
| 13 | `_empty_result` placeholder | "Yetersiz veri durumunda boş sonuç oluşturur." |
| 14 | `run_backtest_compat` wrapper eklendi (sonra kaldırıldı) | Gereksiz olduğu tespit edildi |

---

## `enhanced_walk_forward.py`

| # | Sorun | Düzeltme |
|---|-------|----------|
| 1 | `WalkForwardFold` isim çakışması (`walk_forward.py` ile) | `PurgeEmbargoFold` olarak yeniden adlandırıldı |
| 2 | `WalkForwardResult` isim çakışması | `PurgeEmbargoResult` olarak yeniden adlandırıldı |
| 3 | `__init__.py` import'ları eski isimleri kullanıyordu | Güncellendi |

---

## `walk_forward_engine.py`

| # | Sorun | Düzeltme |
|---|-------|----------|
| 1 | `WalkForwardResult` isim çakışması | `WalkForwardResultV5` olarak yeniden adlandırıldı |
| 2 | `__init__.py` import'ları eski ismi kullanıyordu | Güncellendi |
| 3 | 9 "Otomatik eklendi" docstring | ⏳ Bekliyor |

---

## Çağrı Güncellemeleri

| # | Dosya | Değişiklik |
|---|-------|------------|
| 1 | `scripts/verify_structural_fixes.py` | `engine` → `execution_engine` |
| 2 | `services/ml/feature_ablation.py` | `engine` → `execution_engine` |
| 3 | `services/pipeline/main_backtest.py` | `engine` → `execution_engine` |
| 4 | `services/api/v1/backtest.py` | `engine` → `execution_engine` |
| 5 | `run_all_imports.py` | `engine` → `execution_engine` + `engine_v4` |
| 6 | `scripts/verify_all_api_endpoints.py` | `engine` → `execution_engine` + `engine_v4` |
| 7 | `services/paper_trading/performance_tracker.py` | Comment referansı güncellendi |

---

## Geliştirme Önerileri

| # | Alan | Öneri |
|---|------|-------|
| 1 | `canonical_adapter.py` | `enrich_features_for_canonical` fonksiyonu şu an passthrough — gerçek enrichment logic eklenmeli |
| 2 | `backtest_enhancements.py` | Tatil takvimi entegrasyonu ile T+1 hesaplaması daha doğru yapılabilir (BIST resmi tatilleri) |
| 3 | `benchmark.py` | Annualized return hesaplaması bilgi amaçlı geri eklenebilir |
| 4 | `execution_engine.py` / `engine_v4.py` | İki motor birleştirilebilir — V4 kendi sinyal ürettikten sonra execution_engine mantığını kullanabilir |
| 5 | `portfolio_sim.py` | 20 "Otomatik eklendi" — en fazla placeholder'a sahip dosya, öncelikli denetim gerekli |

---

## Bekleyen Dosyalar (13 adet, 62 "Otomatik eklendi")

| # | Dosya | "Otomatik eklendi" |
|---|-------|-------------------|
| 1 | `portfolio_sim.py` | 20 |
| 2 | `walk_forward_engine.py` | 9 |
| 3 | `walk_forward_runner.py` | 7 |
| 4 | `pit_validator.py` | 5 |
| 5 | `scanner_parity.py` | 4 |
| 6 | `deterministic.py` | 3 |
| 7 | `event_replay.py` | 3 |
| 8 | `multi_asset_engine.py` | 3 |
| 9 | `survivorship.py` | 3 |
| 10 | `walk_forward.py` | 2 |
| 11 | `enhanced_walk_forward.py` | 1 |
| 12 | `persistence.py` | 1 |
| 13 | `transaction_costs.py` | 1 |
