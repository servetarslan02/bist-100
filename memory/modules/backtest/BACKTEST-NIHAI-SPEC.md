# Backtest Nihai Sistem Dokümanı — Kod Analizi + Araştırma Bazlı

**Tarih:** 2026-08-18
**Kaynaklar:** arXiv Momentum-Gated Framework (2026), For Traders Bias Guide (2026), MDPI Regime-Aware LightGBM (2026), QuantConnect/Zipline/Backtrader, Aladdin mimarisi

---

## 0. Mevcut Durum (Kod Analizi)

### Modüller (8 dosya, 3,961 satır)

| Modül | Satır | Class | Fonksiyon | Durum |
|-------|-------|-------|-----------|-------|
| `engine_v4.py` | 1,225 | 9 | 31 | ✅ En kapsamlı — canonical scoring, fast mode, feature cache |
| `walk_forward_runner.py` | 649 | 3 | 11 | ✅ Walk-forward backtest runner |
| `portfolio_sim.py` | 565 | 6 | 25 | ✅ Portföy simülasyonu (Trade, Position, EquitySnapshot, BISTCommission) |
| `walk_forward.py` | 436 | 3 | 7 | ✅ Walk-forward analysis (folds, metrics, deflated sharpe) |
| `enhanced_walk_forward.py` | 369 | 3 | 12 | ✅ Purge/embargo walk-forward (precision@K, IC, hit rate) |
| `engine.py` | 302 | 4 | 4 | ✅ Basit backtest engine |
| `persistence.py` | 250 | 1 | 10 | ✅ SQLite tabanlı sonuç saklama |
| `canonical_adapter.py` | 165 | 1 | 6 | ✅ Canonical scoring adapter |

### Test Dosyaları (7)

```
tests/test_backtest_data_parity.py
tests/test_backtest_performance.py
tests/test_backtest_v4.py
tests/test_backtest_v5_upgrade.py
tests/test_canonical_backtest.py
tests/test_faz4_backtest.py
tests/test_walkforward_canonical.py
```

### Kritik Fonksiyonlar

| Fonksiyon | Modül | Ne Yapıyor | Durum |
|-----------|-------|------------|-------|
| `BacktestEngineV4.run()` | engine_v4 | Ana backtest çalıştır (legacy + fast mode) | ✅ İyi |
| `BacktestEngineV4._run_fast()` | engine_v4 | Hızlı backtest (vectorized) | ✅ İyi |
| `BacktestEngineV4._compute_score()` | engine_v4 | Canonical scoring | ✅ İyi |
| `BacktestEngineV4._get_features()` | engine_v4 | Feature cache ile feature hesaplama | ✅ İyi |
| `PurgeEmbargoWalkForward.split()` | enhanced_wf | Purge/embargo ile fold bölme | ✅ İyi |
| `PurgeEmbargoWalkForward.run()` | enhanced_wf | Walk-forward çalıştır | ✅ İyi |
| `PortfolioSimulatorV3.execute_buy()` | portfolio_sim | Alım simülasyonu | ✅ İyi |
| `PortfolioSimulatorV3.execute_sell()` | portfolio_sim | Satış simülasyonu | ✅ İyi |
| `PortfolioSimulatorV3.check_invariants()` | portfolio_sim | Muhasebe invariant kontrolü | ✅ İyi |
| `BacktestPersistence.save_run()` | persistence | Sonuç kaydetme | ✅ İyi |
| `BacktestPersistence.save_trades()` | persistence | Trade kaydetme | ✅ İyi |

### Eksikler (Kod Analizi)

| Eksik | Açıklama | Öncelik | Durum |
|-------|----------|--------|-------|
| **Look-ahead bias detection** | Kodda timestamp validation yok | 🔴 Kritik | ✅ `bias_detector.py` |
| **Survivorship bias handling** | Delisted şirketleri dahil etme yok | 🔴 Kritik | ✅ `survivorship.py` |
| **Point-in-time validation** | Feature hesaplamanın zaman doğruluğu yok | 🔴 Kritik | ✅ `pit_validator.py` |
| **Transaction cost model** | Sadece komisyon (BISTCommissionModel) — spread/slippage yok | 🟡 Önemli | ✅ `transaction_costs.py` |
| **Spread model** | Bid/ask spread kullanılmıyor | 🟡 Önemli | ✅ `transaction_costs.py` |
| **Slippage model** | Sabit %0.05 — volatilite bazlı değil | 🟡 Önemli | ✅ `transaction_costs.py` |
| **Market impact** | Büyük emirler için impact modeli yok | 🟡 Önemli | ✅ `transaction_costs.py` |
| **Multi-asset backtest** | Sadece tek hisse | 🟡 Önemli | ✅ `multi_asset_engine.py` |
| **Event replay** | Belirli günü yeniden çalıştırma | 🟡 Önemli | ✅ `event_replay.py` |
| **Deterministic recovery** | Restart sonrası aynı sonuç garantisi yok | 🟡 Önemli | ✅ `deterministic.py` |
| **API endpoint** | Backtest API endpoint'i yok | 🟡 Önemli | ⏳ Mevcut `/api/v1/backtest` |
| **Backtest-scanner parity** | Backtest ve canlı tarama aynı kodu kullanmıyor | 🟡 Önemli | ✅ `scanner_parity.py` |

---

## 1. Nihai Backtest Sistemi Nasıl Olmalı?

### Temel Prensipler

**5 Bias Koruması (Zorunlu):**

| Bias | Ne | Çözüm |
|------|-----|-------|
| **Look-ahead** | Gelecek veri kullanma | Point-in-time data, timestamp validation |
| **Survivorship** | İflas eden şirketleri hariç tutma | Delisted şirketleri dahil et |
| **Data-snooping** | Aşırı optimizasyon | Deflated Sharpe, multiple testing correction |
| **Optimization** | Parametre tuning sonrası test | Out-of-sample hold-out |
| **Overfitting** | Noise'a uyum | Walk-forward, cross-validation |

**Kırmızı Bayraklar:**
- Sharpe > 3.0 → Muhtemelen curve-fit
- Drawdown < %5 → Muhtemelen unrealistic
- 30+ parametre → Muhtemelen overfit

---

## 2. Nihai Backtest Mimarisi

```
┌─────────────────────────────────────────────────────────────┐
│                    BACKTEST ORCHESTRATOR                     │
│                                                             │
│  ┌───────────┐  ┌───────────┐  ┌───────────┐              │
│  │ Strategy  │  │ Universe  │  │ Calendar  │              │
│  │ Definition│  │ Filter    │  │ Manager   │              │
│  └─────┬─────┘  └─────┬─────┘  └─────┬─────┘              │
│        └───────────────┴───────────────┘                    │
│                        ↓                                    │
│  ┌─────────────────────────────────────────────────────┐   │
│  │              POINT-IN-TIME DATA ENGINE               │   │
│  │  - Timestamp validation                              │   │
│  │  - Look-ahead detection                              │   │
│  │  - Survivorship handling                             │   │
│  │  - Corporate action adjustment                       │   │
│  └─────────────────────────┬───────────────────────────┘   │
│                            ↓                                │
│  ┌─────────────────────────────────────────────────────┐   │
│  │              FEATURE ENGINE (Live Parity)            │   │
│  │  - Same features as live system                      │   │
│  │  - No future data leakage                            │   │
│  │  - Version-locked features                           │   │
│  └─────────────────────────┬───────────────────────────┘   │
│                            ↓                                │
│  ┌─────────────────────────────────────────────────────┐   │
│  │              SIGNAL GENERATOR                        │   │
│  │  - Model prediction                                  │   │
│  │  - Threshold / ranking                               │   │
│  │  - Confidence scoring                                │   │
│  └─────────────────────────┬───────────────────────────┘   │
│                            ↓                                │
│  ┌─────────────────────────────────────────────────────┐   │
│  │              RISK GATE (Same as Live)                │   │
│  │  - Position limits                                   │   │
│  │  - Sector exposure                                   │   │
│  │  - Drawdown limits                                   │   │
│  │  - Liquidity check                                   │   │
│  └─────────────────────────┬───────────────────────────┘   │
│                            ↓                                │
│  ┌─────────────────────────────────────────────────────┐   │
│  │              EXECUTION SIMULATOR                     │   │
│  │  - Spread model (bid/ask)                            │   │
│  │  - Slippage model (volatility-based)                 │   │
│  │  - Market impact (order size)                        │   │
│  │  - Commission (BIST-specific)                        │   │
│  │  - Partial fill                                      │   │
│  │  - Rejection (liquidity)                             │   │
│  └─────────────────────────┬───────────────────────────┘   │
│                            ↓                                │
│  ┌─────────────────────────────────────────────────────┐   │
│  │              PORTFOLIO SIMULATOR                     │   │
│  │  - Cash management                                   │   │
│  │  - Position tracking                                 │   │
│  │  - P&L calculation                                   │   │
│  │  - Drawdown tracking                                 │   │
│  │  - Rebalancing                                       │   │
│  └─────────────────────────┬───────────────────────────┘   │
│                            ↓                                │
│  ┌─────────────────────────────────────────────────────┐   │
│  │              METRICS ENGINE                          │   │
│  │  - Performance metrics (Sharpe, Sortino, Calmar)     │   │
│  │  - Risk metrics (VaR, CVaR, MaxDD)                  │   │
│  │  - ML metrics (IC, Precision@K, Hit Rate)            │   │
│  │  - Deflated Sharpe Ratio                             │   │
│  │  - Benchmark comparison                              │   │
│  └─────────────────────────┬───────────────────────────┘   │
│                            ↓                                │
│  ┌─────────────────────────────────────────────────────┐   │
│  │              PERSISTENCE & AUDIT                     │   │
│  │  - SQLite/PostgreSQL storage                         │   │
│  │  - Trade log (immutable)                             │   │
│  │  - Equity curve                                      │   │
│  │  - Configuration snapshot                            │   │
│  │  - Reproducibility hash                              │   │
│  └─────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────┘
```

---

## 3. Walk-Forward Analysis (Zorunlu)

### Neden Walk-Forward?

**Statik backtest yanıltıcıdır.** Model geçmişe uyum sağlar ama geleceği tahmin edemez. Walk-forward, modelin görmediği verilerde test edilmesini sağlar.

### Walk-Forward Akışı

```
Veri: [============================]
       |  Train  |  Test  |
       |---------|--------|
       |  Fold 1 |        |
       |    Fold 2 |      |
       |       Fold 3 |   |
       |          Fold 4  |
       
Her fold:
1. Train döneminde model eğit
2. Test döneminde tahmin yap
3. Sonuçları kaydet
4. Pencereyi kaydır
```

### Purge/Embargo (Kritik)

```
Train: [===========]
                     ← Purge gap (data leakage önleme)
Test:                [===========]
                     ← Embargo period (sonraki verilerden izolasyon)

Purge: Train sonu ile Test başı arasındaki veriyi at
Embargo: Test bitiminden sonraki belirli günleri hariç tut
```

---

## 4. Transaction Cost Model (Gerçekçi)

### BIST'e Özel Maliyetler

```
Toplam Maliyet = Komisyon + Spread + Slippage + Market Impact + BSMV

Komisyon:
- Broker: %0.03
- BIST: %0.0056
- MKK: %0.00109
- Minimum: ₺1

Spread:
- Büyük hacimli (THYAO, GARAN): %0.05-0.1
- Orta hacimli: %0.1-0.3
- Düşük hacimli: %0.3-1.0

Slippage (Volatilite bazlı):
- Düşük volatilite: %0.05
- Orta volatilite: %0.1-0.2
- Yüksek volatilite: %0.2-0.5

Market Impact (Emir boyutu):
- Küçük emir (<%1 günlük hacim): %0
- Orta emir (%1-5): %0.05-0.1
- Büyük emir (>%5): %0.1-0.5

BSMV: Komisyon üzerinden %5
```

---

## 5. Metrikler (Detaylı)

### Performans Metrikleri
| Metrik | Formül | İyi Değer |
|--------|--------|-----------|
| Total Return | (Final/Initial - 1) × 100 | > %15/yıl |
| CAGR | (Final/Initial)^(1/yıl) - 1 | > %12 |
| Sharpe Ratio | (Return - Rf) / StdDev | > 1.5 |
| Sortino Ratio | (Return - Rf) / DownsideDev | > 2.0 |
| Calmar Ratio | CAGR / MaxDrawdown | > 1.0 |
| Max Drawdown | Max(peak - trough) / peak | < %20 |
| Win Rate | Kazanan / Toplam | > %50 |
| Profit Factor | Gross Profit / Gross Loss | > 1.5 |
| Expectancy | (Win% × AvgWin) - (Loss% × AvgLoss) | > 0 |

### Risk Metrikleri
| Metrik | Açıklama |
|--------|----------|
| VaR 95% | %95 güvenle max kayıp |
| CVaR 95% | VaR'ı aşan ortalama kayıp |
| Downside Deviation | Negatif getiri standart sapması |
| Drawdown Duration | Drawdown süresi |
| Tail Risk | Kuyruk riski |

### ML Metrikleri
| Metrik | Açıklama |
|--------|----------|
| IC (Information Coefficient) | Tahmin-gerçek korelasyonu |
| Precision@K | Top-K tahmin doğruluğu |
| Hit Rate | Doğru yön tahmini |
| Top-K Return | Top-K hisse getirisi |
| Deflated Sharpe | Multiple testing düzeltmesi |
| Turnover | Portföy devir hızı |

---

## 6. Deflated Sharpe Ratio (Kritik)

### Neden Önemli?

Birden fazla strateji test ettiğinizde, şans eseri yüksek Sharpe çıkabilir. Deflated Sharpe, bu düzeltmeyi yapar.

### Formül

```
DSR = (SR - E[max_SR]) / Std[max_SR]

SR: Gözlemlenen Sharpe
E[max_SR]: N denemeden beklenen max Sharpe
Std[max_SR]: Standart sapma
```

### Uygulama
- 100 strateji test ettiyseniz ve en iyisi Sharpe 2.5
- Deflated Sharpe 1.2 çıkabilir → Gerçek edge belirsiz
- Deflated Sharpe > 1.5 → Güvenilir

---

## 7. Event Replay (Gerekli)

### Ne İşe Yarar?

Belirli bir günü yeniden çalıştırarak:
- Bug reproducing
- Model debugging
- Karar audit
- State recovery

### Akış

```
1. Belirli tarih seç (örn: 2025-03-15)
2. O güne ait tüm verileri yükle
3. Event'leri sırayla oynat
4. Aynı kararları üret
5. Sonuçları karşılaştır
6. Fark varsa → bug
```

---

## 8. Nihai Backtest Checklist

### Her Backtest İçin Kontrol

```
[ ] Point-in-time data kullanıldı mı?
[ ] Survivorship bias kontrol edildi mi?
[ ] Walk-forward analiz yapıldı mı?
[ ] Out-of-sample test var mı?
[ ] Deflated Sharpe hesaplandı mı?
[ ] Transaction cost gerçekçi mi?
[ ] Slippage modeli var mı?
[ ] Market impact modeli var mı?
[ ] Benchmark karşılaştırması var mı?
[ ] Drawdown analizi var mı?
[ ] Turnover analizi var mı?
[ ] Parametre sayısı < 30 mu?
[ ] Sharpe < 3.0 mu (curve-fit riski)?
[ ] Sonuçlar tekrarlanabilir mi?
[ ] Configuration snapshot kaydedildi mi?
[ ] Trade log immutable mı?
```

---

## 9. Mevcut Sistem vs Nihai Vizyon

| Özellik | Mevcut | Hedef |
|---------|--------|-------|
| Basic backtest | ✅ | ✅ |
| Walk-forward | ✅ | ✅ |
| Purge/embargo | ✅ | ✅ |
| Portfolio sim | ✅ | ✅ |
| Persistence | ✅ | ✅ |
| Look-ahead detection | ✅ | ✅ |
| Survivorship handling | ✅ | ✅ |
| Point-in-time validation | ✅ | ✅ |
| Deflated Sharpe | ✅ | ✅ |
| Realistic transaction cost | ✅ | ✅ |
| Spread model | ✅ | ✅ |
| Slippage model | ✅ | ✅ |
| Market impact | ✅ | ✅ |
| Event replay | ✅ | ✅ |
| Deterministic recovery | ✅ | ✅ |
| API endpoint | ✅ | ✅ |
| Multi-asset backtest | ✅ | ✅ |
| Benchmark comparison | ✅ | ✅ |

---

## 10. ÇÖZÜLDÜ — Düzeltme Kayıtları (2026-08-20)

### Düzeltme 1: TransactionCostEngine Entegrasyonu
- **Dosya:** `portfolio_sim.py`
- **Sorun:** PortfolioSimulatorV3 sadece sabit slippage_rate kullanıyordu, TransactionCostEngine entegre değildi
- **Çözüm:** `use_realistic_costs=True` parametresi ile TransactionCostEngine opsiyonel olarak entegre edildi
- **Etki:** `execute_buy()` ve `execute_sell()` artık spread, slippage, market impact modeli kullanabiliyor
- **Geriye uyumluluk:** `use_realistic_costs=False` (varsayılan) → legacy davranış aynen korunur

### Düzeltme 2: VaR/CVaR Metrikleri
- **Dosya:** `portfolio_sim.py`, `engine_v4.py`
- **Sorun:** Spec'te tanımlı VaR 95% ve CVaR 95% hesaplanmıyordu
- **Çözüm:** Historical percentile method ile VaR/CVaR eklendi
- **Etki:** `compute_metrics()` artık `var_95` ve `cvar_95` döndürüyor

### Düzeltme 3: Max Drawdown Duration
- **Dosya:** `portfolio_sim.py`
- **Sorun:** Drawdown süresi (gün olarak) izlenmiyordu
- **Çözüm:** `_drawdown_start_date` ve `_max_drawdown_duration_days` ile izleme eklendi
- **Etki:** `compute_metrics()` artık `max_drawdown_duration_days` döndürüyor

### Düzeltme 4: BUY/SELL Eşik Asimetrisi Dokümantasyonu
- **Sorun:** Asimetri kodda var ama dokümante edilmemiş
- **Çözüm:** CURRENT-STATE.md'de açıklandı
- **SELL:** `score <= (100 - signal_threshold)` = 40 (esnek çıkış)
- **BUY:** `score >= signal_threshold + 10` = 70 (seçici giriş)
- **Hysteresis gap:** 30 puan → whipsaw önleme

### Düzeltme 5: Entegrasyon Testleri
- **Dosya:** `tests/test_backtest_integration.py` (yeni)
- **İçerik:** 25 test, tüm backtest modüllerini kapsıyor
- **Durum:** 25/25 PASSED
