# BIST-100 — Kalan Hatalar ve İyileştirmeler

> **Son güncelleme:** 2026-08-22  
> **Düzeltilen:** 32 hata (2 commit)  
> **Kalan:** Bu dosyadaki maddeler

---

## 🔴 P0 — KRİTİK (Sprint'te düzeltilmeli)

### 1. Walk-forward'da model eğitimi yok
- **Dosya:** `services/learning/real_bist_walkforward_backtest.py`
- **Sorun:** "Walk-forward" adı altında 6 model var ama hiçbiri `fit()` çağrılmıyor. Hepsi deterministik kurallarla çalışıyor (sabit ağırlıklar, eşik değerleri).
- **Düzeltme:** Her split'te modeli train verisiyle eğit, test ile predict et.

### 2. Label üretimi mask-aware değil (look-ahead bias)
- **Dosya:** `services/labels/generator.py`
- **Sorun:** Forward return hesaplanırken `close[i+period]` kullanılıyor ama feature'larla label arasında purge gap yok.
- **Düzeltme:** Label üretimi sırasında feature penceresinin son `purge_days` barını hariç tut.

### 3. Ranking model grup yapısı eksik
- **Dosya:** `services/ml/ranking_model.py`
- **Sorun:** `_prepare_training_data()` `group_sizes` oluşturuyor ama LambdaRank'in `group` parametresi düzgün hesaplanmıyor.
- **Düzeltme:** `date_groups` kullanarak gerçek tarih bazlı gruplar oluştur.

### 4. Seasonality motoru mask kırığı
- **Dosya:** `services/features/seven_motors.py`
- **Sorun:** `valid_close` ve `valid_dates` farklı filtreleme kriterleri kullanıyor — uzunluk farkı oluşabilir.
- **Düzeltme:** Birleşik mask kullan: `mask == 1 & ~np.isnan(close)`.

### 5. 14 test dosyasında `except Exception: pass`
- **Dosya:** `tests/` dizini (14 dosya)
- **Sorun:** Hatalar yutuluyor, test "geçiyor" ama hiçbir şey doğrulamıyor.
- **Düzeltme:** Her `except` bloğunda `pytest.fail()` veya exception assertion.

### 6. CI/CD pipeline yok
- **Sorun:** `.github/`, `.gitlab-ci.yml`, `Makefile` — hiçbir CI/CD yapılandırması yok.
- **Düzeltme:** GitHub Actions ile test + lint + build.

### 7. Hardcoded API key
- **Dosya:** `services/api/auth.py`
- **Sorun:** `alpha-system-key-change-me` default key.
- **Düzeltme:** `SYSTEM_API_KEY` env var zorunlu yap.

---

## 🟠 P1 — YÜKSEK (2-4 hafta)

### 8. Purge gap eksik (feature ↔ label)
- **Dosya:** `services/labels/generator.py`, `services/ml/walk_forward.py`
- **Sorun:** Feature hesaplama ile label üretimi arasında purge gap yok.

### 9. HMM regime — warm-up döneminde sahte veri
- **Dosya:** `services/intelligence/regime.py`
- **Sorun:** İlk 63 gözlemde `np.pad(mode="edge")` ile sahte veri üretiliyor.

### 10. Walk-forward evaluate'da feature purge yok
- **Dosya:** `services/ml/walk_forward.py`
- **Sorun:** Train feature'ları hesaplanırken son purge_days bar hariç tutulmuyor.

### 11. Panel engine RSI ≠ Wilder's smoothing
- **Dosya:** `services/features/panel_engine.py`
- **Sorun:** Calculator Wilder's smoothing kullanıyor, panel engine basit ortalama.

### 12. Exposure_pct hesaplanmaması
- **Dosya:** `services/backtest/engine.py`
- **Sorun:** `exposure_pct=0.0` sabit.

### 13. Equity curve'de güncel fiyat eksik
- **Dosya:** `services/backtest/engine.py`
- **Sorun:** Sadece işlem yapılan ticker'ın fiyatı güncelleniyor, diğerleri avg_cost.

### 14. Double-entry muhasebe eksik
- **Dosya:** `services/portfolio/portfolio_manager.py`
- **Sorun:** Her işlem tek taraflı kaydediliyor.

### 15. Sabit slippage modeli
- **Dosya:** `services/backtest/engine.py`
- **Sorun:** `slippage_pct=0.05` sabit. Hacim ve volatiliteye bağlı olmalı.

### 16. Likidite kısıtı eksik
- **Dosya:** `services/backtest/engine.py`
- **Sorun:** Günlük hacim kontrolü yok.

### 17. Deflated Sharpe duplicate
- **Dosya:** `services/backtest/walk_forward.py` vs `enhanced_walk_forward.py`
- **Sorun:** İki farklı formül farklı sonuçlar üretiyor.

### 18. Walk-forward expanding window yok
- **Dosya:** `services/ml/walk_forward.py`
- **Sorun:** Train penceresi sabit, expanding window uygulanmıyor.

### 19. Stochastic RSI yanlış implementasyon
- **Dosya:** `services/features/seven_motors.py`
- **Sorun:** Close fiyatlarını kullanıyor, RSI serisini değil.

### 20. IntegratedLearningSystem feature_importance boş
- **Dosya:** `services/learning/integrated_learning.py`
- **Sorun:** `_feature_importance` hiçbir yerde doldurulmuyor.

### 21. Scenario engine sektör matrisi hard-coded
- **Dosya:** `services/intelligence/scenario.py`
- **Sorun:** Sadece 6 sektör, değerler doğrulanmamış.

### 22. Real BIST backtest'te model confidence sabit
- **Dosya:** `services/learning/real_bist_walkforward_backtest.py`
- **Sorun:** `confidence = 0.62`, `0.60`, `0.54` sabit.

### 23. Breadth scoring tutarsızlığı
- **Dosya:** `services/intelligence/regime.py`
- **Sorun:** `_score_bull` ve `_score_momentum_expansion` farklı breadth aralıkları kullanıyor.

### 24. Platt scaling validation set overfitting
- **Dosya:** `services/ml/calibration.py`
- **Sorun:** Calibrator tüm veriyle eğitiliyor.

### 25. Cross-sectional sector momentum tarih bağımlılığı yok
- **Dosya:** `services/features/cross_sectional.py`

### 26. Holiday takvimi sadece 2026
- **Dosya:** `services/scheduler/unified_scheduler.py`

### 27. 6 farklı entry point
- **Dosya:** `main.py`, `start.py`, `run_system.py`, `apps/api/main.py`, `services/api/main.py`, `services/api/server.py`

### 28. Hard-coded risk-free rate
- **Dosya:** `services/portfolio/enhancements.py`
- **Sorun:** `risk_free_rate=0.15` sabit.

### 29. Stress test senaryoları statik
- **Dosya:** `services/risk/stress_test.py`

### 30. Paper trading state store atomic write eksik
- **Dosya:** `services/paper_trading/state_store.py`

### 31. Performance tracker max DD yanlış
- **Dosya:** `services/paper_trading/performance_tracker.py`
- **Sorun:** Günlük max DD'lerin en büyüğünü döndürüyor, gerçek peak-to-trough değil.

### 32. Walk-forward singleton çakışması
- **Dosya:** `services/backtest/walk_forward.py` + `enhanced_walk_forward.py`
- **Sorun:** Her ikisi de `walk_forward_engine` singleton'ı tanımlıyor.

### 33. Virtual portfolio komisyon çift sayım
- **Dosya:** `services/paper_trading/virtual_portfolio.py`

### 34. Drawdown response reset kimlik doğrulaması yok
- **Dosya:** `services/risk/drawdown_response.py`

### 35. Regime scoring eşitlik durumunda hatalı
- **Dosya:** `services/intelligence/regime.py`

### 36. Macro regime import yolu yanlış
- **Dosya:** `services/intelligence/regime.py`
- **Sorun:** `from services.macro.regime_detector` — bu dizin var mı?

### 37. Data quality timestamp check eksik
- **Dosya:** `services/core/data_quality.py`

---

## 🟡 P2 — ORTA (1-3 ay)

### 38. Dead code temizliği
- `services/features/feature_contract.py` — tanımlanmış ama kullanılmıyor
- `services/features/calculator.py::compute_extended_features()` — caller yok
- `services/ml/ranker.py` vs `ranking_model.py` — duplicate mantık
- `services/scanner/opportunity_engine` vs `alpha_scanner` — duplicate
- `services/backtest/portfolio_sim.py` vs `engine.py` — duplicate simulation

### 39. Hard-coded sabitler (kalan)
- Valuation engine: `DEFAULT_WACC=0.20`, `DEFAULT_TAX_RATE=0.23`
- Fundamental motor: `quality_score=50` başlangıç
- Scenario engine: sabit sektör duyarlılık matrisi
- Scanner: sabit opportunity score ağırlıkları
- Ranking model: sabit rule-based ağırlıklar

### 40. İsim standardizasyonu (kalan)
- Volume feature: `volume_zscore_10d`, `_20d`, `_60d` — sadece 20d canonical
- Momentum: `momentum_20d` calculator vs Motor 2 farklı anlamlar
- Sector-relative: `SECTOR_REL_TARGETS` eksik

### 41. Magic numbers (9,382 adet)
- En kritik olanları sabit olarak tanımla.

### 42. `print()` debug çıktısı (~250 adet services dışı)
- `logger`'a dönüştür.

### 43. Monte Carlo seed kullanılmaması
- **Dosya:** `services/simulation/monte_carlo_enhanced.py`

### 44. Feature drift detector PSI basitleştirilmiş
- **Dosya:** `services/ml/feature_drift.py`
- **Sorun:** Gerçek PSI değil, z-score benzeri metrik.

### 45. Scenario engine breaking point negatif şok desteği yok
- **Dosya:** `services/intelligence/scenario.py`

### 46. Bollinger bb_position Motor 8'de sınırlanmamış
- **Dosya:** `services/features/seven_motors.py`

---

## 🔵 İYİLEŞTİRME (Backlog)

### 47. Redpanda → Redis Streams
- Mevcut event volume Kafka/Redpanda gerektirmiyor.

### 48. Feature store (Redis-based)
- Feature'lar her seferinde hesaplanıyor, cache'lenmiyor.

### 49. OpenTelemetry tracing
- Monitoring sadece health check düzeyinde.

### 50. Pandera data validation
- Sistematik data quality framework'ü yok.

### 51. PgBouncer connection pooling
- Production'da connection exhaustion riski.

### 52. Grafana alert rules
- Alert tanımları eksik.

### 53. API versioning standardizasyonu
- `/api/v1/` prefix zaten var ama tutarsız.

### 54. Agent memory persistence
- `memory_path=None` varsayılan, restart sonrası kaybolur.

### 55. LLM client fallback zinciri
- Fallback sessizce gerçekleşiyor, log eksik.

### 56. Hallucination protection etkinliği
- Fiyat/tarih/olay doğrulaması yok.

---

## ❌ FALSE POSITIVE (Düzeltilmiş / Yanlış Tespit)

| # | Rapor İddiası | Durum |
|---|--------------|-------|
| 1 | macro_impact * 100 | ✅ Zaten * 15 |
| 2 | ClickHouse hardcoded creds | ✅ Zaten env var |
| 3 | assert True sahte test | ✅ Zaten kaldırılmış |
| 4 | JWT secret hardcoded | ✅ Zaten RuntimeError |
| 5 | AUTH_STRICT → ADMIN | ✅ Zaten VIEWER |
| 6 | production_scheduler.py duruyor | ✅ Zaten kaldırılmış |
| 7 | pytest.ini çelişki | ✅ Zaten deprecated |
| 8 | BKM adapter mock | ✅ compute_features reddediyor |
| 9 | 3 boş fonksiyon (alerting) | ✅ Protocol stub |
| 10 | Duplicate logger (server.py) | ✅ Zaten düzeltilmiş |
| 11 | Scheduler trigger endpoint | ✅ Mevcut (line 217) |

---

## 📊 ÖZET

| Kategori | Sayı |
|----------|------|
| 🔴 P0 (Kritik) | 7 |
| 🟠 P1 (Yüksek) | 30 |
| 🟡 P2 (Orta) | 9 |
| 🔵 İyileştirme | 10 |
| ❌ False positive | 11 |
| **Toplam açık** | **56** |
