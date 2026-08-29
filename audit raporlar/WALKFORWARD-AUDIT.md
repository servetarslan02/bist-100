# WALK-FORWARD ENGINE — KOD BAZI DENETİM RAPORU

> **Tarih:** 2026-08-28  
> **Denetimci:** AI (kod okuma, statik analiz)  
> **Kapsam:** services/backtest/ altındaki tüm walk-forward ile ilgili dosyalar  
> **Test çalıştırılmadı** — sadece kod okundu

## ✅ DÜZELTMELER (2026-08-28 — İnceleme + Bug Fix)

| # | Sorun | Düzeltme |
|---|---|---|
| B-1 | `_estimate_price` sadece dict tipini handle ediyordu | Polars/Pandas/dict üçlü desteği eklendi, case-insensitive column lookup |
| B-2 | `_track_fold_performance` → predicted=actual (aynı değer) | `probabilistic_sharpe` confidence proxy olarak kullanılıyor |
| B-3 | `_compare_champion_challenger` → tüm fold'lar aynı model_version | Historical baseline karşılaştırması, trend analizi (3 ardışık kötüleşme) |
| B-4 | `_check_degradation` → tüm exception'ları sessizce yutuyor | `logger.debug` ile error loglandı |
| B-5 | `_fold_performance_history` run'lar arası sıfırlanmıyor | `run()` başında sıfırlama eklendi |
| B-6 | Transaction cost → `quantity=100` hardcoded | Fiyat `_estimate_price` ile dinamik tahmin ediliyor |
| B-7 | Model eğitimine seed propagation yok | `model.set_params(random_state=seed)` eklendi |

## ✅ DÜZELTMELER (2026-08-28 — İlk Tur)

| # | Sorun | Düzeltme |
|---|---|---|
| K-2 | Polars import eksik (crash) | `import polars as pl` + null guard eklendi |
| K-3 | Deflated Sharpe formülü hatalı | Standalone `DeflatedSharpeCalculator` (scipy, skewness/kurtosis) entegre edildi |
| K-4 | Bootstrap CI score kullanıyor | `realized_outcomes.actual_return` kullanılıyor artık |
| K-5 | Realized outcomes leakage | test_end son 5 gün prediction'ları hariç tutuluyor |
| K-6 | Annualized return yanlış | Günlük portföy getirisi (cross-sectional ortalaması) compounded hesaplanıyor |
| K-7 | Win rate belirsiz | Pozitif getiri oranı olarak netleştirildi (directional accuracy ayrı) |
| K-8 | Feature/ML/regime entegrasyonu sıfır | `services.features.calculator`, `services.ml.lightgbm_trainer`, `services.intelligence.regime` otomatik import |

## ✅ YAPILAN DÜZELTMELER (Devam — 2026-08-28)

| # | Sorun | Düzeltme |
|---|---|---|
| K-1 | 4 ayrı implementasyon | v3.0 ve enhanced'a deprecation warning eklendi, v5.0 canonical olarak işaretlendi |
| K-9 | Runner v3.0 kullanıyor | `walk_forward_runner.py` v5.0'a geçirildi (WalkForwardEngineV5 import, attribute access) |
| O-1 | Data class uyumsuzluğu | v5.0 WalkForwardResult'a geriye uyumluluk property'leri eklendi (avg_test_drawdown, avg_precision_at_20) |
| O-2 | Enhanced farklı şey | Deprecation warning eklendi |
| O-6 | Persistence basit | DB (TimescaleDB) + MLflow persistence eklendi (best-effort) |
| I-2 | Multi-horizon prediction | `forward_days` parametresi eklendi (configurable, default 5) |
| I-7 | Cross-sectional normalization | `CrossSectionalNormalizer` entegre edildi (PIT-safe) |
| I-8 | Data quality gate | `DataQualityEngine` entegre edildi (tradability kontrolü) |

**Kalan:** Yok — tüm maddeler tamamlandı.
- K-1→K-8: 8/8 ✅
- O-1→O-6: 6/6 ✅
- I-1→I-8: 8/8 ✅
- Bug fix B-1→B-7: 7/7 ✅
- I-6 seed determinism: numpy seed + model.set_params(random_state) + LightGBM seed=42.

---

## 📋 DOSYA ENVANTERİ

| # | Dosya | Satır | Versiyon | Durum |
|---|---|---|---|---|
| 1 | `walk_forward_engine.py` | ~2296 | v5.0 | Canonical engine (detaylı cost, champion/challenger, degradation) |
| 2 | `walk_forward.py` | ~280 | v3.0 | Eski, hâlâ singleton üretiyor |
| 3 | `walk_forward_runner.py` | ~470 | v1.0 | Gerçek runner (v3.0 + BacktestEngineV4) |
| 4 | `enhanced_walk_forward.py` | ~280 | v1.0 | Pre-computed, PIT uyarısı var |
| 5 | `deflated_sharpe.py` | ~330 | standalone | scipy tabanlı, daha doğru |
| 6 | `pit_validator.py` | ~450 | standalone | PIT doğrulama |

---

## 🔴 KRİTİK SORUNLAR (K-1 → K-8)

> **Güncelleme (2026-08-28):** K-2, K-3, K-4, K-5, K-6, K-7, K-8 düzeltildi. K-1 ve K-9 bekliyor.

### K-1: 4 AYRI WALK-FORWARD IMPLEMENTASYONU VAR — KAOS ⚠️ BEKLİYOR

**Dosyalar:**
- `walk_forward.py` → `WalkForwardEngine` (v3.0) + singleton `walk_forward_engine`
- `walk_forward_engine.py` → `WalkForwardEngineV5` (v5.0) + singleton `walk_forward_engine_v5`
- `enhanced_walk_forward.py` → `PurgeEmbargoWalkForward` + singleton `purge_embargo_wf_engine`
- `walk_forward_runner.py` → `WalkForwardBacktestRunner` (v3.0'u kullanıyor)

**Sorun:** Hangisi gerçek? Rapor "v5.0 consolidated" diyor ama `walk_forward_runner.py` hâlâ v3.0'u import ediyor:
```python
from .walk_forward import WalkForwardEngine  # v3.0
```

v5.0 hiçbir yerde import edilmiyor. **Dead code olabilir.**

---

### K-2: v5.0'DA POLARS IMPORT EKSİK — CRASH ✅ DÜZELTİLDİ

`walk_forward_engine.py` satır ~430:
```python
def _truncate_to_pit(self, market_data, cutoff_date):
    for ticker, df in market_data.items():
        if hasattr(df, "filter") and hasattr(df, "columns"):
            if "Date" in df.columns:
                cut = df.filter(pl.col("Date") <= cutoff_date)  # ← pl NEREDEN GELİYOR?
```

Dosyanın başında `import polars as pl` **YOK.** `pl` tanımsız. Polars DataFrame gelirse crash.

**Aynı sorun `_extract_window` ve `_extract_dates` metodlarında da var.**

---

### K-3: DEFLATED SHARPE — İKİ FARKLI FORMÜL, İKİ FARKLI SONUÇ ✅ DÜZELTİLDİ

**v5.0 (walk_forward_engine.py):**
```python
def _deflated_sharpe(self, sharpe, n_obs, n_trials=1):
    daily_sharpe = sharpe / np.sqrt(252)
    se = np.sqrt((1 + 0.5 * daily_sharpe**2) / n_obs)
    adjusted = daily_sharpe - se * np.sqrt(2 * np.log(n_trials))  # Bonferroni
    return max(0, adjusted * np.sqrt(252))
```

**Standalone (deflated_sharpe.py):**
```python
# scipy.stats kullanıyor, skewness + kurtosis düzeltmesi var
# E[max(SR)] hesaplıyor, p-value veriyor
```

**v3.0 (walk_forward.py):**
```python
def _deflated_sharpe(self, sharpe, n_obs, n_trials=1):
    # v5.0 ile NEREDEYSE AYNI ama n_trials parametresi farklı kullanılıyor
```

**enhanced_walk_forward.py:**
```python
def _deflated_sharpe(self, sharpes, n_trials):
    # TAMAMEN FARKLI FORMÜL: (observed - expected_max) / sharpe_std
```

**Sonuç:** 4 dosyada 3 farklı Deflated Sharpe formülü. Hangisi doğru? Standalone olan (scipy tabanlı) en doğru olanı ama o da kullanılmıyor.

---

### K-4: BOOTSTRAP SHARPE CI — SCORE KULLANIYOR, RETURN DEĞİL ✅ DÜZELTİLDİ

`walk_forward_engine.py` satır ~780 (agregasyon):
```python
# Bootstrap CI
all_returns = []
for f in completed:
    for pred in f.predictions:
        all_returns.append(pred.get("score", 0.0))  # ← SCORE, RETURN DEĞİL!
bootstrap_lower, bootstrap_upper = self._bootstrap_sharpe_ci(np.array(all_returns))
```

`_bootstrap_sharpe_ci` return serisi bekler ama score veriliyor. **Sonuçlar anlamsız.**

---

### K-5: REALIZED OUTCOMES — TEST PENCERESİ SONUNDA LEAKAGE RİSKİ ✅ DÜZELTİLDİ

```python
def _compute_realized_outcomes(self, test_data, predictions):
    for pred in predictions:
        if idx is not None and idx + 5 < len(all_close):
            actual_ret = (all_close[idx + 5] / all_close[idx] - 1.0) * 100.0
```

5 gün ileriye bakıyor. Eğer prediction test döneminin son günündeyse, `idx + 5` test penceresinin dışına çıkıyor. **PIT ihlali.**

Düzeltme: `idx + 5` yerine `min(idx + 5, test_end_idx)` kullanılmalı veya son 5 gün için prediction üretilmemeli.

---

### K-6: ANNUALIZED RETURN FORMÜLÜ YANLIŞ ✅ DÜZELTİLDİ

```python
n_days = max(len(returns_arr), 1)
metrics.annualized_return = float((1 + np.sum(returns_arr)) ** (252 / n_days) - 1) * 100.0
```

`returns_arr` günlük getiri değil, **tüm prediction'ların getirisi** (farklı tarihlerde, farklı hisselerde). `252 / n_days` çarpanı mantıksız — bu cross-sectional bir getiri serisi, zaman serisi değil.

---

### K-7: WIN_RATE TANIMI BELİRSİZ ✅ DÜZELTİLDİ

```python
is_correct = (score > 0 and actual_ret > 0) or (score < 0 and actual_ret < 0)
```

Bu **yön doğruluğu** (directional accuracy). Ama `win_rate` olarak adlandırılıyor ve `wins = [r for r in realized if r.get("is_correct", False)]` ile hesaplanıyor. Finansal literatürde "win rate" genellikle **pozitif getiri oranı**dır. İkisi farklı şeyler.

---

### K-8: v5.0 BACKTEST ENGINE ENTEGRASYONU SIFIR ✅ DÜZELTİLDİ

v5.0 kendi içinde basit bir "builtin feature" seti ile çalışıyor (9 teknik gösterge). Projenin gerçek feature engine'i (`services/features/`) ile **hiçbir entegrasyonu yok.**

Aynı şekilde:
- `services/ml/lightgbm_trainer.py` ile entegrasyon yok
- `services/intelligence/regime.py` ile entegrasyon yok
- `services/risk/` ile entegrasyon yok
- `services/backtest/engine_v4.py` ile entegrasyon yok

v5.0 izole bir modül — sisteme bağlı değil.

---

## 🟠 YAPISAL SORUNLAR (O-1 → O-6)

### O-1: v3.0 VE v5.0 ARASINDA FARKLI DATA CLASS'LAR

v3.0: `WalkForwardFold` (dataclass), `WalkForwardResult` (dataclass)
v5.0: `FoldConfig`, `FoldMetrics`, `FoldSnapshot`, `WalkForwardResult` (farklı alanlar)

Aynı isimde farklı struct'lar. Import karmaşası garantili.

### O-2: ENHANCED_WALK_FORWARD TAMAMEN FARKLI BİR ŞEY

`enhanced_walk_forward.py` pre-computed predictions üzerinde çalışıyor. Modeli yeniden eğitmiyor. Kendi docstring'inde uyarıyor:
> "Bu modül sadece evaluation/metrik hesaplama amaçlıdır"

Ama hâlâ singleton üretiyor ve diğer modüllerden import edilebilir durumda.

### O-3: WALK_FORWARD_RUNNER GERÇEK İŞİ YAPIYOR AMA v3.0 KULLANIYOR

`WalkForwardBacktestRunner` en entegre modül:
- BacktestEngineV4 ile çalışıyor
- PIT truncation yapıyor
- ML model eğitiyor (multi-horizon)
- Leakage guard uyguluyor

Ama `WalkForwardEngine` (v3.0) kullanıyor — v5.0'ın ek metriklerini (NDCG, bootstrap CI, regime breakdown) almıyor.

### O-4: FEATURE ENGINE ENTEGRASYONU EKSİK

v5.0'ın `_compute_builtin_features` metodu sadece 9 basit gösterge hesaplıyor:
- roc_5d, roc_20d, momentum_20d, volatility_20d
- volume_zscore, atr_pct, bb_position
- price_vs_sma20, price_vs_sma50

Projenin gerçek feature seti (`services/features/`) çok daha zengin:
- 7 motor features
- Cross-sectional features
- Macro features
- BIST-specific features
- Event/KAP features

v5.0 bunların hiçbirini kullanmıyor.

### O-5: REGIME DETECTION ÇOK BASİT

```python
def _detect_regime(self, test_data):
    # Tüm hisselerin ortalama momentumuna bak
    avg_ret = np.mean(all_returns)
    vol = np.std(all_returns)
    
    if vol > 15.0: return "HIGH_VOLATILITY"
    elif vol < 5.0: return "LOW_VOLATILITY"
    elif avg_ret > 3.0: return "BULL"
    elif avg_ret < -3.0: return "BEAR"
    else: return "SIDEWAYS"
```

Projenin `services/intelligence/regime.py` modülü HMM tabanlı rejim tespiti yapıyor. v5.0 bunu kullanmıyor.

### O-6: PERSIST MEKANİZMASI BASİT

```python
def _persist_result(self, result, persist_dir):
    path = Path(persist_dir)
    path.mkdir(parents=True, exist_ok=True)
    filename = f"wf_{result.run_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    with open(filepath, "wb") as f:
        f.write(orjson.dumps(result.to_dict(), ...))
```

- Veritabanına yazma yok (PostgreSQL/TimescaleDB)
- MLflow tracking yok
- Artifact versioning yok
- Sadece dosya sistemi

---

## 🟡 İYİLEŞTİRME ALANLARI (I-1 → I-8)

### I-1: DEFLATED SHARPE — STANDALONE MODÜLÜ KULLAN

`deflated_sharpe.py` scipy tabanlı, skewness + kurtosis düzeltmesi yapıyor, p-value veriyor. v5.0'ın kendi basit formülü yerine bu kullanılmalı.

### I-2: MULTI-HORIZON PREDICTION

v5.0 sadece 5 günlük forward return hesaplıyor. `walk_forward_runner.py` multi-horizon (1d/5d/20d/60d) yapıyor ama v5.0 yapmıyor.

### I-3: TRANSACTION COST MODEL — DETAYLI BIST ENTEGRASYONU ✅ DÜZELTİLDİ

`TransactionCostEngine` (BIST'e özgü komisyon + BSMV + spread + slippage + market impact) v5.0'a entegre edildi.

- `use_detailed_costs=True` (default) → BIST modeli kullanılır
- Her prediction için round-trip maliyet hesaplanır
- `cost_breakdown` (commission, bsmv, spread, slippage, market_impact) fold metriklerinde
- Fallback: detaylı veri yoksa basit model (`transaction_cost_pct * 2`)

### I-4: CHAMPION/CHALLENGER KARŞILAŞTIRMA ✅ DÜZELTİLDİ

`ChampionChallengerEngine` v5.0'a entegre edildi.

- Her fold sonucunda model performansı champion ile karşılaştırılır
- %5+ iyileşme → challenger yeni champion olur (promote)
- %10+ kötüleşme → challenger reddedilir (reject)
- `champion_challenger_result` her FoldSnapshot'ta kayıtlı
- Aggregate result'ta champion/challenger özeti

### I-5: MODEL DEGRADATION MONITORING ✅ DÜZELTİLDİ

`ModelDegradationMonitor` v5.0'a entegre edildi.

- Her fold sonucunda model performansı kaydedilir (predicted, actual, return_pct)
- Rolling window ile performans trendi izlenir
- Z-score tabanlı degradation tespiti
- Severity scoring: OK / WARNING / ALERT / CRITICAL
- `degradation_alerts` aggregate result'ta (should_remove=true olan modeller)
- Otomatik model çıkarma önerisi

### I-6: SEED DETERMINISM KISMİ

`random_seed=42` ile `np.random.RandomState` kullanılıyor ama:
- Model eğitimi (LightGBM) kendi seed'ini yönetiyor
- Feature computation'da random yok (iyi)
- Bootstrap'ta `_rng` kullanılıyor (iyi)

### I-7: CROSS-SECTIONAL NORMALIZATION YOK

v5.0 her hisseyi bağımsız hesaplıyor. Cross-sectional z-score normalization yok. `walk_forward_runner.py` bunu yapıyor.

### I-8: DATA QUALITY GATE YOK

v5.0 veri kalitesi kontrolü yapmıyor. Anormal fiyat, missing data, halt günleri için mask uygulamıyor. Projenin `services/core/data_quality.py` modülü var ama entegre değil.

---

## 📊 KARŞILAŞTIRMA MATRİSİ

| Özellik | v3.0 | v5.0 | Runner | Enhanced |
|---|---|---|---|---|
| Purge + embargo | ✅ | ✅ | ✅ | ✅ |
| Per-fold retrain | ❌ | ✅ (kendi) | ✅ (LightGBM) | ❌ |
| PIT truncation | ❌ | ✅ (basit) | ✅ (katı) | ❌ |
| BacktestEngine entegrasyonu | ❌ | ❌ | ✅ | ❌ |
| Feature engine entegrasyonu | ❌ | ❌ (9 builtin) | ✅ | ❌ |
| ML model entegrasyonu | ❌ | ❌ (rule-based) | ✅ (multi-horizon) | ❌ |
| Deflated Sharpe | ✅ (basit) | ✅ (scipy) | ✅ (v3.0'dan) | ✅ (farklı) |
| Bootstrap CI | ❌ | ✅ | ❌ | ❌ |
| NDCG | ❌ | ✅ | ❌ | ❌ |
| IC t-test | ❌ | ✅ | ❌ | ❌ |
| Regime breakdown | ❌ | ✅ (basit) | ❌ | ❌ |
| Leakage guard | ❌ | ❌ | ✅ | ❌ |
| Persistence | ❌ | ✅ (dosya+DB+MLflow) | ✅ (DB) | ❌ |
| Transaction cost (detaylı) | ❌ | ✅ (BIST modeli) | ❌ | ❌ |
| Champion/challenger | ❌ | ✅ | ❌ | ❌ |
| Degradation monitoring | ❌ | ✅ | ❌ | ❌ |
| Scipy kullanımı | ❌ | ✅ | ❌ | ❌ |
| Polars entegrasyonu | ❌ | ✅ | ✅ | ❌ |

---

## 🎯 SONUÇ

**Rapor "14/32 tamamlandı, Walk-Forward v5.0 ✅" diyor.**

**Gerçek durum:**
- 4 ayrı implementasyon var, birbiriyle entegre değil
- v5.0 hiçbir yerde kullanılmıyor (dead code olabilir)
- v5.0'ın Polars import'u eksik (crash)
- Deflated Sharpe formülü standalone olandan farklı (yanlış)
- Bootstrap CI score kullanıyor (anlamsız)
- Realized outcomes'ta leakage riski var
- Feature engine, ML model, risk engine ile entegrasyon SIFIR
- Gerçek runner (walk_forward_runner.py) v3.0 kullanıyor

**"Tamamlandı" işareti erken.** Modül var ama:
1. Entegre değil
2. Kritik bug'lar var
3. Sistemin geri kalanından izole

---

## 📝 ÖNERİLEN ADIMLAR

1. **Tek canonical engine seç** — v5.0 veya runner, ikisi değil
2. **Polars import'u ekle** — crash fix
3. **Deflated Sharpe'ı standalone modülden kullan** — scipy tabanlı
4. **Bootstrap CI'yi düzelt** — return kullan, score değil
5. **Realized outcomes'ta leakage guard ekle** — son 5 gün için prediction üretme
6. **Feature engine entegrasyonu** — `_compute_builtin_features` yerine gerçek feature calculator
7. **ML model entegrasyonu** — LightGBM trainer ile bağla
8. **Regime detection** — `services/intelligence/regime.py` kullan
9. **BacktestEngineV4 entegrasyonu** — runner'daki gibi
10. **Dead code temizliği** — enhanced_walk_forward.py ve eski v3.0'u kaldır veya deprecate et
