# RİSK — Risk Management System

## Giriş

Risk modülü, ALPHA BIST'in **bağımsız risk yönetim katmanıdır**. AI katmanının ÜZERİNDE çalışır — yani model bir "al" sinyali verse bile, risk motoru bunu veto edebilir. Temel felsefe: **fail-closed** (belirsiz durumda engelle, izin verme).

Modül, tek bir dosyadan oluşan monolitik bir sistem değil; birbirini tamamlayan 14 dosyalık bir servis katmanıdır. Her dosya riskin farklı bir boyutunu ele alır: pozisyon büyüklüğü, korelasyon, VaR/CVaR, drawdown, stres testi, kuyruk riski, risk parity, dinamik limitler, kalibrasyon, monitoring ve mutabakat.

## Katman Haritası

```
┌─────────────────────────────────────────────────────────────────┐
│                     main.py — RiskEngine                        │
│  (Event consumer, pre-trade checks, fail-closed orchestrator)   │
│  decision.created → _on_decision → 6 check → APPROVE/BLOCK     │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────────┐  │
│  │ position_    │  │ enhanced_    │  │ var_cvar.py          │  │
│  │ sizing.py    │  │ risk.py      │  │ VaRCalculator        │  │
│  │              │  │              │  │ Parametrik/Historik/ │  │
│  │ Fractional   │  │ Ledoit-Wolf  │  │ Monte Carlo          │  │
│  │ Kelly + Vol  │  │ Covariance + │  │ Component/Marginal   │  │
│  │ Targeting    │  │ Rebalance +  │  │ VaR-based limit      │  │
│  │              │  │ Concentration│  │                      │  │
│  └──────┬───────┘  └──────┬───────┘  └──────────┬───────────┘  │
│         │                 │                      │              │
│  ┌──────┴───────┐  ┌──────┴───────┐  ┌──────────┴───────────┐  │
│  │ calibration  │  │ covariance   │  │ stress_test.py       │  │
│  │ .py          │  │ .py          │  │                      │  │
│  │              │  │              │  │ Historical (2008,    │  │
│  │ Platt        │  │ Ledoit-Wolf  │  │ 2020, 2022, 2018)   │  │
│  │ Scaling      │  │ Shrinkage    │  │ Hypothetical (USD,   │  │
│  │ score → p    │  │ + Factor     │  │ BIST, TCMB, VIX)    │  │
│  │              │  │              │  │ Monte Carlo stress   │  │
│  └──────────────┘  └──────────────┘  └──────────────────────┘  │
│                                                                 │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────────┐  │
│  │ drawdown_    │  │ dynamic_     │  │ tail_hedge.py        │  │
│  │ response.py  │  │ limits.py    │  │                      │  │
│  │              │  │              │  │ Protective Put,      │  │
│  │ 5% → REDUCE  │  │ Vol/Regime/  │  │ Collar, Tail Spread, │  │
│  │ 10% → STOP   │  │ Drawdown/    │  │ VIX Call, Crisis     │  │
│  │ 15% → CLOSE  │  │ VIX-adjusted │  │ Alpha detection      │  │
│  │ 20% → HALT   │  │ limits       │  │                      │  │
│  └──────────────┘  └──────────────┘  └──────────────────────┘  │
│                                                                 │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────────┐  │
│  │ risk_        │  │ monitoring   │  │ reconciliation.py    │  │
│  │ parity.py    │  │ .py          │  │                      │  │
│  │              │  │              │  │ Ledger vs DB vs      │  │
│  │ Equal risk   │  │ Real-time    │  │ Cash vs Positions    │  │
│  │ contribution │  │ alerting +   │  │ vs Equity            │  │
│  │ per position │  │ customizable │  │ consistency check    │  │
│  │              │  │ rules        │  │                      │  │
│  └──────────────┘  └──────────────┘  └──────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
```

## Neden Bu Tasarım Seçimi?

| Karar | Neden |
|-------|-------|
| **Fail-closed (fail-open değil)** | Risk limitleri okunamıyorsa sistem işlem yapmamalı. "Bilmiyorum" = "Engelle". P0-6 kuralı. |
| **AI katmanının üstünde** | Model overfit yapabilir, hallucination olabilir. Risk motoru bağımsız çalışır, modeli veto edebilir. |
| **Regime-conditioned Kelly** | Sabit Kelly fraction her rejimde aynı riski alır. BULL'da agresif, BEAR'da muhafazakar olmalı. SSRN 2026 araştırmasına dayalı. |
| **Ledoit-Wolf shrinkage** | Sample covariance küçük örneklemde gürültüdür. Shrinkage ile regularize edilir, condition number düşer. |
| **3 yöntemli VaR** | Tek yöntem yanıltıcı olabilir. Parametrik (normal varsayım), Historik (dağılım varsayımı yok), Monte Carlo (stokastik). Konsensüs = 3'ün ortalaması. |
| **Otomatik drawdown response** | İnsan müdahalesi gecikebilir. Drawdown %5'i aşınca pozisyon otomatik küçülür, %20'de sistem durur. |
| **Dynamic limits (sabit değil)** | Piyasa koşulları değişken. Sabit %10 limit yüksek vol'da çok agresif, düşük vol'da çok pasif. Volatilite/rejim/drawdown/VIX'e göre adapte olur. |
| **Singleton pattern** | Her modül tek bir instance ile çalışır. `var_calculator`, `dynamic_limits`, `stress_test_engine` vb. global erişim için. |

## Uçtan Uca Veri Akışı

```
1. Sinyal Üretilir (ML modeli)
       ↓
2. decision.created event → RiskEngine._on_decision()
       ↓
3. Risk limits yüklü mü? (FAIL-CLOSED kontrol)
       ↓ HAYIR → BLOCK (RISK_ALERT publish)
       ↓ EVET
4. 6 Paralel Check:
   ├── _check_position_limit()     → Pozisyon boyutu limiti
   ├── _check_sector_concentration() → Sektör konsantrasyonu
   ├── _check_daily_loss()         → Günlük zarar limiti
   ├── _check_drawdown()           → Max drawdown limiti
   ├── drawdown_system.check()     → Otomatik drawdown response
   └── dynamic_limits.check()      → Dinamik pozisyon limiti
       ↓
5. Tüm check'ler geçti mi?
       ↓ HAYIR → RISK_ALERT event publish, BLOCK
       ↓ EVET → risk_check:{ticker} Redis'e yaz (5 dk TTL)
       ↓
6. assess_portfolio_risk() (çağrılırsa):
   ├── VaR/CVaR (3 yöntem)
   ├── Dynamic Limits
   ├── Concentration (HHI)
   ├── Drawdown State
   ├── Stress Test
   ├── Tail Hedge
   └── Risk Score (0-100)
```

## Dosya Bazlı Sorumluluk Tablosu

| Dosya | Sorumluluk | Singleton | Kritik Sınıf/Fonksiyon |
|-------|-----------|-----------|------------------------|
| `main.py` | Event consumer, pre-trade risk checks, fail-closed orchestrator | — | `RiskEngine`, `assess_portfolio_risk()`, `assess_viop_risk()` |
| `position_sizing.py` | Fractional Kelly + volatility targeting + cold-start policy | `position_sizer` | `PositionSizer`, `_PositionSizerCompat.calculate()` |
| `enhanced_risk.py` | Ledoit-Wolf covariance, volatility targeting, rebalance, concentration | `ledoit_wolf`, `volatility_targeter`, `rebalance_engine`, `concentration_risk` | `compute_full_risk_metrics()` |
| `var_cvar.py` | VaR/CVaR hesaplama (3 yöntem), component VaR, marginal VaR | `var_calculator` | `VaRCalculator.calculate_full_var_report()` |
| `stress_test.py` | Tarihsel + hipotetik + Monte Carlo stres testleri | `stress_test_engine` | `StressTestEngine.run_all_scenarios()` |
| `covariance.py` | Ledoit-Wolf shrinkage covariance estimation (detaylı) | `covariance_estimator` | `CovarianceEstimator.estimate()` |
| `drawdown_response.py` | Otomatik drawdown yönetimi (5/10/15/20% eşikleri) | `drawdown_system` | `DrawdownResponseSystem.update_equity()` |
| `dynamic_limits.py` | Volatilite/rejim/drawdown/VIX'e göre dinamik risk limitleri | `dynamic_limits` | `DynamicRiskLimits.get_limits()` |
| `tail_hedge.py` | Kuyruk riski koruma stratejileri, crisis alpha tespiti | `tail_hedger` | `TailRiskHedger.analyze()`, `detect_crisis_alpha()` |
| `risk_parity.py` | Risk parity optimizasyonu (eşit risk katkısı) | `risk_parity_optimizer` | `RiskParityOptimizer.optimize()` |
| `calibration.py` | Score → win_probability kalibrasyonu (Platt scaling) | `calibrator` | `ScoreCalibrator.calibrate()`, `fit_from_trades()` |
| `monitoring.py` | Gerçek zamanlı risk izleme + alert kuralları | `risk_monitor` | `RiskMonitor.check_metrics()` |
| `reconciliation.py` | Ledger vs DB mutabakat kontrolü | `reconciliation_engine` | `ReconciliationEngine.reconcile()` |
| `__init__.py` | Public API exports | — | Tüm singleton'lar ve enum'lar |

## Tasarım İlkeleri ve Kırmızı Çizgiler

### İlkeler

1. **Fail-closed, asla fail-open**: Risk limitleri yüklenemezse tüm işlemler BLOCKED. Exception durumunda da BLOCK.
2. **Unknown = BLOCK**: Bilinmeyen sektör, bulunamayan portföy, okunamayan veri → BLOCK (WARN değil).
3. **Bağımsız katman**: Risk motoru AI'dan bağımsız çalışır. Model "al" dese bile risk "dur" diyebilir.
4. **Regime-conditioned**: Sabit parametreler yerine piyasa rejimine göre adapte olan parametreler.
5. **Audit trail**: Her risk kararı loglanır. Drawdown aksiyon değişiklikleri event olarak publish edilir.
6. **Kelly ≠ confidence**: Score ve win_probability ayrı değişkenler. Kalibrasyon gerekli.

### Kırmızı Çizgiler

- ❌ Risk limitleri yüklenmeden işlem yapma
- ❌ Exception durumunda işlemi devam ettirme
- ❌ Bilinmeyen sektör/portföy için varsayılan olarak izin verme
- ❌ Kelly fraction'ı rejimsiz uygulama
- ❌ Sample covariance'ı shrinkage olmadan kullanma
- ❌ Drawdown %20'yi geçtikten sonra sistemi açık bırakma

## Bilinen Sınırlamalar

1. **Kalibrasyon soğuk başlangıcı**: `calibrator._fitted = False` olduğunda sigmoid fallback kullanılır. Gerçek Platt scaling için en az 30 trade gerekir.
2. **Monte Carlo normal dağılım varsayımı**: `var_cvar.py`'deki Monte Carlo normal dağılım kullanır. Fat tail'leri yakalamaz (simulation modülündeki jump-diffusion daha gerçekçi).
3. **Stres testi statik senaryolar**: Tarihsel senaryolar sabit. `add_custom_scenario()` ile genişletilebilir ama otomatik adaptasyon yok.
4. **Reconciliation sadece kontrol**: Uyuşmazlık tespit eder ama otomatik düzeltme yapmaz.
5. **Monitoring callback yokluğu**: Varsayılan alert callback'i yok. `register_callback()` ile eklenmeli.
6. **Risk parity scipy bağımlılığı**: `scipy.optimize.minimize` gerektirir. Ortamda yoksa çalışamaz.

## Cross-Referanslar

| Bu modül | İlişki | Diğer modül |
|----------|--------|-------------|
| `risk/main.py` | `assess_viop_risk()` → `services.viop.enhanced_options` | VIOP modülü |
| `risk/main.py` | Event bus → `decision.created`, `signal.generated` | Core event_bus |
| `risk/position_sizing.py` | `calculate_var_based_position_limit()` → `risk/var_cvar.py` | VaR modülü (iç) |
| `risk/enhanced_risk.py` | `suggest_hedge()` → `services.viop.hedging` | VIOP hedging |
| `risk/enhanced_risk.py` | `check_options_strategy()` → `services.viop.strategies` | VIOP stratejileri |
| `risk/calibration.py` | `calibrate()` ← `position_sizing.py` tarafından çağrılır | Position sizing (iç) |
| `risk/drawdown_response.py` | `KILL_SWITCH_TRIGGERED` event publish | Core event_bus |
| `risk/monitoring.py` | `ingest_pipeline_metrics()` ← pipeline'dan beslenir | Pipeline servisi |
| `risk/stress_test.py` | `run_all_scenarios()` ← `main.py:assess_portfolio_risk()` | Risk main (iç) |
| `portfolio/portfolio_manager.py` | `get_risk_metrics()` → `risk/var_cvar.py` | Portfolio modülü |
| `simulation/enhanced_stress_test.py` | Benzer stres testi mantığı (farklı implementasyon) | Simulation modülü |
