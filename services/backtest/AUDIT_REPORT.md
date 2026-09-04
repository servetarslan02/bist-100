# services/backtest/ — Denetim Raporu

**Tarih:** 2026-09-05
**Güncelleme:** 2026-09-05 (9/21 dosya denetlendi)
**Kapsam:** 21 `.py` dosyası
**Denetim Sonucu:** 9 dosya kurallara göre denetlenip düzeltildi. 12 dosya bekliyor.

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
| 1 | `__init__.py` | 14 | ✅ Denetlendi, düzeltildi |
| 2 | `backtest_enhancements.py` | 18 | ✅ Denetlendi, düzeltildi |
| 3 | `benchmark.py` | 13 | ✅ Denetlendi, düzeltildi |
| 4 | `bias_detector.py` | 16 | ✅ Denetlendi, düzeltildi |
| 5 | `canonical_adapter.py` | 13 | ✅ Denetlendi, düzeltildi |
| 6 | `deflated_sharpe.py` | 8 | ✅ Denetlendi, düzeltildi |
| 7 | `deterministic.py` | 10 | ✅ Denetlendi, düzeltildi |
| 8 | `engine_v4.py` | 20 | ✅ Denetlendi, düzeltildi |
| 9 | `enhanced_walk_forward.py` | 10 | ✅ Denetlendi, düzeltildi |
| 10 | `event_replay.py` | — | ⏳ Bekliyor |
| 11 | `execution_engine.py` | — | ⏳ Bekliyor |
| 12 | `multi_asset_engine.py` | — | ⏳ Bekliyor |
| 13 | `persistence.py` | — | ⏳ Bekliyor |
| 14 | `pit_validator.py` | — | ⏳ Bekliyor |
| 15 | `portfolio_sim.py` | — | ⏳ Bekliyor |
| 16 | `scanner_parity.py` | — | ⏳ Bekliyor |
| 17 | `survivorship.py` | — | ⏳ Bekliyor |
| 18 | `transaction_costs.py` | — | ⏳ Bekliyor |
| 19 | `walk_forward.py` | — | ⏳ Bekliyor |
| 20 | `walk_forward_engine.py` | — | ⏳ Bekliyor |
| 21 | `walk_forward_runner.py` | — | ⏳ Bekliyor |

**Denetlenen dosyalarda toplam: 0 "Otomatik eklendi" placeholder docstring (tümü düzeltildi)**

---

## `benchmark.py` — Denetim Raporu (3. dosya)

| # | Kural | Sorun | Düzeltme |
|---|-------|-------|----------|
| 1 | 4 | Modül docstring İngilizce: "Benchmark Comparison Module" | "Benchmark Karşılaştırma Modülü" |
| 2 | 4 | `BenchmarkComparison` docstring yetersiz | Açıklayıcı Türkçe docstring |
| 3 | 4 | `BenchmarkComparison.__repr__` eksik | Eklendi |
| 4 | 4 | `compare` docstring eksik (Raises yok) | Args/Returns/Raises tamamlandı |
| 5 | 2 | `compare` tek gözlemde sessizce sıfır dönüyor | `ValueError` raise edildi |
| 6 | 2 | `from_equity_curves` boş girdi kontrolü yok | `ValueError` eklendi |
| 7 | 2 | `from_equity_curves` sıfır değerli equity'de `ZeroDivisionError` | Sıfır kontrolü eklendi |
| 8 | 4 | `from_equity_curves` docstring yetersiz | Args/Returns/Raises eklendi |
| 9 | 4 | `generate_report` docstring yetersiz | Args/Returns eklendi |
| 10 | 4 | Up/Down capture okunabilirlik sorunlu | Ayrı değişkenlere bölündü |
| 11 | 2 | `np.corrcoef` sabit dizi gelirse NaN döner | NaN koruması eklendi |
| 12 | 4 | `information_ratio`'da `np.std` iki kez hesaplanıyor | Tek hesaplamaya düşürüldü |
| 13 | 6 | Yıllık alpha hesaplaması basit çarpım | Log-return alternatifi önerildi |

### Geliştirme Önerileri
- Log-return tabanlı alpha hesaplaması
- Rolling metrics desteği
- Benchmark preset konfigürasyonları

---

## `bias_detector.py` — Denetim Raporu (4. dosya)

| # | Kural | Sorun | Düzeltme |
|---|-------|-------|----------|
| 1 | 2 | **Kritik Bug:** `get_summary()` `self.violations` hiç dolmuyor → hep boş dönüyor | `_record()` helper metodu eklendi |
| 2 | 4 | `BiasViolation.__repr__` eksik | Eklendi |
| 3 | 4 | `BiasReport.__repr__` eksik | Eklendi |
| 4 | 4 | `LookAheadBiasDetector.__repr__` eksik | Eklendi |
| 5 | 4 | `BiasDetectorMiddleware.__repr__` eksik | Eklendi |
| 6 | 4 | `add_violation` return type `Any` → `None` | Düzeltildi |
| 7 | 4 | `__init__` return type eksik (3 adet) | `-> None` eklendi |
| 8 | 4 | Modül docstring İngilizce | Türkçeleştirildi |
| 9 | 4 | `validate_rolling_window` docstring yetersiz | Args/Returns eklendi |
| 10 | 4 | `validate_data_revision_integrity` docstring yetersiz | Args/Returns eklendi |
| 11 | 4 | `pre_scan_check` docstring yetersiz | Args/Returns eklendi |
| 12 | 4 | `fold_check` docstring yetersiz | Args/Returns eklendi |
| 13 | 4 | Raises docstring hatalı (TypeError raise etmiyor) | Kaldırıldı |
| 14 | 4 | Docstring typo: "Eklenacak" → "Eklenecek" | Düzeltildi |
| 15 | 2 | Polars null değerler `np.isnan(None)` → TypeError | Null koruması eklendi |
| 16 | 4 | `validate_rolling_window` döngü tabanlı performans sorunu | Polars vektörel operasyonlara geçirildi |
| 17 | 4 | `import numpy as np` gereksiz (vektörizasyon sonrası) | Kaldırıldı |
| 18 | 4 | Gereksiz yorum satırları (duplikasyon) | Temizlendi |

### Geliştirme Önerileri
- `validate_rolling_window` vektörel optimizasyon ✅ Uygulandı

---

## `canonical_adapter.py` — Denetim Raporu (5. dosya)

| # | Kural | Sorun | Düzeltme |
|---|-------|-------|----------|
| 1 | 4 | `BacktestCanonicalAdapter.__repr__` eksik | Eklendi |
| 2 | 4 | `__init__` return type eksik | `-> None` eklendi |
| 3 | 4 | `_lazy_load` return type `Any` → `None` | Düzeltildi |
| 4 | 4 | `_scalar_features` docstring kısa | Args/Returns eklendi |
| 5 | 4 | `_lazy_load` docstring kısa | Genişletildi |
| 6 | 4 | `compute_score_and_decision` docstring kısa | Args/Returns eklendi |
| 7 | 4 | `enrich_features_for_canonical` docstring kısa | Args/Returns eklendi |
| 8 | 4 | `enrich_features_for_canonical` TODO yorumu | Kaldırıldı, docstring yazıldı |
| 9 | 4 | Modül docstring İngilizce | Türkçeleştirildi |
| 10 | 4 | `compute_score` docstring İngilizce | Türkçeleştirildi |
| 11 | 4 | `compute_score_and_decision` docstring İngilizce | Türkçeleştirildi |
| 12 | 4 | Feature parity kodu tekrar ediyor (~25 satır) | `_apply_feature_parity` helper çıkarıldı |
| 13 | 4 | `compute_score` docstring'de changelog notu | Kaldırıldı |
| 14 | 6 | `_scalar_features` performans | Numpy vektörel filtreleme uygulandı |

### Geliştirme Önerileri
- `_scalar_features` vektörel optimizasyon ✅ Uygulandı

---

## `deflated_sharpe.py` — Denetim Raporu (6. dosya)

| # | Kural | Sorun | Düzeltme |
|---|-------|-------|----------|
| 1 | 4 | `DeflatedSharpeResult.__repr__` eksik | Eklendi |
| 2 | 4 | `to_dict` docstring Returns eksik | Returns eklendi |
| 3 | 4 | Modül docstring İngilizce | Türkçeleştirildi |
| 4 | 4 | `compute_expected_max_sharpe` Args çok uzun | Args kısa, uzun açıklama Not: bölümüne taşındı |
| 5 | 4 | `from_returns` (PSR) docstring kısa | Args/Returns eklendi |
| 6 | 4 | `compute_deflated_sharpe` yorum İngilizce | "tek kuyruklu test" |
| 7 | 4 | Logging satırı çok uzun | Bölündü |
| 8 | 4 | Gereksiz local import (`from scipy.stats import norm as _norm`) | Kaldırıldı, `stats.norm` kullanıldı |

---

## `deterministic.py` — Denetim Raporu (7. dosya)

| # | Kural | Sorun | Düzeltme |
|---|-------|-------|----------|
| 1 | 1 | `to_dict` docstring: "Otomatik eklendi." | Açıklayıcı Türkçe docstring |
| 2 | 1 | `DeterministicRecovery.__init__` docstring: "Otomatik eklendi." | Açıklayıcı Türkçe docstring |
| 3 | 1 | `IdempotencyGuard.__init__` docstring: "Otomatik eklendi." | Açıklayıcı Türkçe docstring |
| 4 | 4 | `SystemCheckpoint.__repr__` eksik | Eklendi |
| 5 | 4 | `DeterministicRecovery.__repr__` eksik | Eklendi |
| 6 | 4 | `IdempotencyGuard.__repr__` eksik | Eklendi |
| 7 | 4 | `set_seed` return type `Any` → `None` | Düzeltildi |
| 8 | 4 | `_persist_checkpoint` return type `Any` → `None` | Düzeltildi |
| 9 | 4 | `record_execution` return type `Any` → `None` | Düzeltildi |
| 10 | 4 | `clear_cache` return type `Any` → `None` | Düzeltildi |
| 11 | 4 | `cleanup_old_checkpoints` return type `Any` → `None` | Düzeltildi |
| 12 | 4 | `import structlog` | Standart `logging` ile değiştirildi |
| 13 | 4 | Logging İngilizce (5 mesaj) | Türkçeleştirildi |
| 14 | 2 | `create_checkpoint` shallow copy riski | `copy.deepcopy` uygulandı |
| 15 | 2 | `cleanup_old_checkpoints` dosya silme hatası yakalanmamış | `try/except` eklendi |
| 16 | 3 | **Kritik Bug:** `to_dict` `model_state` ve `feature_cache_state` yok → persist edilmiyor | Her iki alan eklendi |

### Geliştirme Önerileri
- `np.random.seed` deprecated → `np.random.default_rng()` düşünülebilir
- `validate_determinism` dict/tuple desteği eklenebilir

---

## `engine_v4.py` — Denetim Raporu (8. dosya)

| # | Kural | Sorun | Düzeltme |
|---|-------|-------|----------|
| 1 | 2 | **Dead code** satır 405: `str(next_date.date())` sonucu atılmıyor | Kaldırıldı |
| 2 | 4 | `BacktestConfig.__repr__` eksik | Eklendi |
| 3 | 4 | `BacktestMetrics.__repr__` eksik | Eklendi |
| 4 | 4 | `BacktestResultV4.__repr__` eksik | Eklendi |
| 5 | 4 | `FeatureCache.__repr__` eksik | Eklendi |
| 6 | 4 | `QualityCache.__repr__` eksik | Eklendi |
| 7 | 4 | `BacktestEngineV4.__repr__` eksik | Eklendi |
| 8 | 4 | `_FallbackCalculator.__repr__` eksik | Eklendi |
| 9 | 4 | `_FallbackMask.__repr__` eksik | Eklendi |
| 10 | 4 | `_FallbackQuality.__repr__` eksik | Eklendi |
| 11 | 4 | 11 İngilizce log mesajı | Tümü Türkçeleştirildi |
| 12 | 4 | `FeatureCache.set/clear` return `Any` → `None` | Düzeltildi |
| 13 | 4 | `QualityCache.set/clear` return `Any` → `None` | Düzeltildi |
| 14 | 4 | `_lazy_load` return `Any` → `None` | Düzeltildi |
| 15 | 4 | `__init__` return type eksik (4 adet) | `-> None` eklendi |
| 16 | 4 | `to_dict` docstring kısa (3 adet) | Returns eklendi |
| 17 | 1 | `_empty_result` docstring placeholder | Açıklayıcı Türkçe docstring |
| 18 | 4 | Fallback class docstring yetersiz | Genişletildi |
| 19 | 4 | `FeatureCache.get` docstring kısa | Args/Returns eklendi |
| 20 | 6 | `_compute_score_legacy` hard-coded ağırlıklar | `BacktestConfig.score_weights` ile parametrize edildi |

### Geliştirme Önerileri
- `_compute_score_legacy` ağırlıkları parametrize ✅ Uygulandı
- Borderline eps sabitleri config'den alınabilir

---

## `enhanced_walk_forward.py` — Denetim Raporu (9. dosya)

| # | Kural | Sorun | Düzeltme |
|---|-------|-------|----------|
| 1 | 1 | `__init__` docstring: "Otomatik eklendi." | Açıklayıcı Türkçe docstring |
| 2 | 4 | `PurgeEmbargoFold.__repr__` eksik | Eklendi |
| 3 | 4 | `PurgeEmbargoResult.__repr__` eksik | Eklendi |
| 4 | 4 | `PurgeEmbargoWalkForward.__repr__` eksik | Eklendi |
| 5 | 4 | `import structlog` | Standart `logging` ile değiştirildi |
| 6 | 4 | `__init__` return type eksik | `-> None` eklendi |
| 7 | 4 | İngilizce log mesajı | Türkçeleştirildi |
| 8 | 4 | `split` docstring Args eksik | Args/Returns eklendi |
| 9 | 4 | `run` docstring Returns eksik | Returns eklendi |
| 10 | 4 | 9 yardımcı metod docstring kısa | Tümüne Args/Returns eklendi |
| 11 | 6 | `_deflated_sharpe` basitleştirilmiş formül | Bailey & López de Prado (2014) formülüne geçirildi |

### Geliştirme Önerileri
- Modül DEPRECATED — `WalkForwardEngineV5` kullanılmalı (geriye uyumluluk için korunuyor)
- `_deflated_sharpe` formülü ✅ Bailey & López de Prado (2014) ile değiştirildi

---

## Çağrı Güncellemeleri (Migration)

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

## Bekleyen Dosyalar (12 adet)

| # | Dosya | "Otomatik eklendi" |
|---|-------|-------------------|
| 1 | `event_replay.py` | 3 |
| 2 | `execution_engine.py` | — |
| 3 | `multi_asset_engine.py` | 3 |
| 4 | `persistence.py` | 1 |
| 5 | `pit_validator.py` | 5 |
| 6 | `portfolio_sim.py` | 20 |
| 7 | `scanner_parity.py` | 4 |
| 8 | `survivorship.py` | 3 |
| 9 | `transaction_costs.py` | 1 |
| 10 | `walk_forward.py` | 2 |
| 11 | `walk_forward_engine.py` | 9 |
| 12 | `walk_forward_runner.py` | 7 |

**Bekleyen dosyalarda toplam: 58 "Otomatik eklendi" placeholder docstring**
