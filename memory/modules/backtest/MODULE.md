# 01 — Backtest Modülü

## Rolü

Backtest modülü, ALPHA BIST sisteminin strateji doğrulama katmanıdır. Geçmiş piyasa verileri üzerinde alım-satım sinyallerini simüle ederek stratejinin gerçek performansını ölçer. Finansal doğruluk (look-ahead bias koruması, survivorship bias düzeltmesi, gerçekçi işlem maliyetleri) ve deterministik tekrar üretilebilirlik bu modülün temel taahhütleridir.

## Katman Haritası

```
┌─────────────────────────────────────────────────────────────────┐
│                     BACKTEST MODÜLÜ                             │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  ┌──────────────┐  ┌──────────────┐  ┌───────────────────────┐ │
│  │ engine.py    │  │ engine_v4.py │  │ multi_asset_engine.py │ │
│  │ (v1.0 Canon) │  │ (v4.0 Panel) │  │ (Çoklu Hisse)        │ │
│  └──────┬───────┘  └──────┬───────┘  └───────────┬───────────┘ │
│         │                 │                       │             │
│         ▼                 ▼                       ▼             │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │              portfolio_sim.py (v3.0)                     │   │
│  │  Pozisyon yaşam döngüsü · Komisyon · Slippage · Audit   │   │
│  └────────────────────────┬────────────────────────────────┘   │
│                           │                                     │
│  ┌────────────────────────▼────────────────────────────────┐   │
│  │           transaction_costs.py                           │   │
│  │  BIST ücret yapısı · Spread · Market Impact · BSMV      │   │
│  └─────────────────────────────────────────────────────────┘   │
│                                                                 │
│  ┌──────────────┐  ┌──────────────────┐  ┌─────────────────┐  │
│  │ walk_forward │  │ walk_forward_    │  │ enhanced_walk_  │  │
│  │ .py          │  │ runner.py        │  │ forward.py      │  │
│  │ (Purge+Emb.) │  │ (Engine+WF)      │  │ (PurgeEmbargo)  │  │
│  └──────┬───────┘  └──────┬───────────┘  └────────┬────────┘  │
│         │                 │                        │            │
│         ▼                 ▼                        ▼            │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │              deflated_sharpe.py                          │   │
│  │  Multiple testing düzeltmesi · PSR · Overfitting tespit │   │
│  └─────────────────────────────────────────────────────────┘   │
│                                                                 │
│  ┌──────────────┐  ┌──────────────┐  ┌─────────────────────┐  │
│  │ bias_detector│  │ survivorship │  │ pit_validator.py    │  │
│  │ .py          │  │ .py          │  │                     │  │
│  │ (Look-Ahead) │  │ (Delisting)  │  │ (Point-in-Time)     │  │
│  └──────────────┘  └──────────────┘  └─────────────────────┘  │
│                                                                 │
│  ┌──────────────┐  ┌──────────────┐  ┌─────────────────────┐  │
│  │ event_replay │  │ deterministic│  │ canonical_adapter.py│  │
│  │ .py          │  │ .py          │  │                     │  │
│  │ (Debug/Replay│  │ (Recovery)   │  │ (Scoring Bridge)    │  │
│  └──────────────┘  └──────────────┘  └─────────────────────┘  │
│                                                                 │
│  ┌──────────────┐  ┌──────────────┐  ┌─────────────────────┐  │
│  │ benchmark.py │  │ persistence  │  │ scanner_parity.py   │  │
│  │              │  │ .py          │  │                     │  │
│  │ (Alpha/Beta) │  │ (SQLite)     │  │ (Parity Guard)      │  │
│  └──────────────┘  └──────────────┘  └─────────────────────┘  │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

## Neden Bu Tasarım Seçimi?

| Karar | Neden |
|-------|-------|
| İki motor (v1.0 canonical + v4.0 panel) | v1.0 referans implementasyon, v4.0 performans için vektörize panel feature. İkisi birebir aynı finansal sonuç üretmeli — eşdeğerlik testleri bu yola karşı yapılır. |
| PortfolioSimulatorV3 ayrı modül | Pozisyon yaşam döngüsü, komisyon modeli ve audit trail tek sorumluluk. Motor değişse bile simülatör aynı kalır. |
| Walk-forward runner ayrı | Engine + WF entegrasyonu karmaşık; point-in-time kesit, ML eğitimi ve leakage guard'ları tek yerde yönetilir. |
| Purge + embargo | Train sonu ile test başı arasındaki veri sızıntısını kesin olarak engeller. |
| Deflated Sharpe | Çoklu strateji test edildiğinde şans eseri yüksek Sharpe çıkmasını düzeltir (Bailey & López de Prado, 2014). |
| Bias detector + PIT validator ayrı | Her biri farklı bias türünü tespit eder (look-ahead, label leakage, revision leakage). Ayrılmış sorumluluk. |
| Canonical adapter | Backtest ile canlı sistemin aynı scoring pipeline'ını kullanmasını garanti eder. |
| SQLite persistence | Restart sonrası eksiksiz veri yükler; audit trail kalıcı. |

## Uçtan Uca Veri Akışı

```
1. Girdi: market_data (OHLCV), signals (sinyal listesi), config
         │
2. engine.run_backtest() veya engine_v4.run()
         │
3. Tarih döngüsü (her gün):
   ├─ Feature hesaplama (feature_calculator + tradability_mask)
   ├─ Quality cache kontrolü
   ├─ SELL sinyalleri → PortfolioSimulator.execute_sell()
   ├─ BUY sinyalleri → PortfolioSimulator.execute_buy()
   │   ├─ Dinamik slippage (_compute_dynamic_slippage)
   │   ├─ Likidite kısıtı (_check_liquidity_constraint)
   │   └─ Komisyon (BISTCommissionModel veya TransactionCostEngine)
   └─ Equity snapshot (update_equity)
         │
4. Metrik hesaplama (_compute_metrics)
   ├─ Sharpe, Sortino, Calmar, Max DD, Win Rate, Profit Factor
   ├─ CAGR, VaR, CVaR
   └─ Benchmark karşılaştırma (alpha, beta, IR)
         │
5. Walk-forward (opsiyonel):
   ├─ Fold'lar oluştur (purge + embargo korumalı)
   ├─ Her fold için engine çalıştır (trade_start, trade_end)
   ├─ Leakage guard doğrulaması
   └─ Aggregasyon (stability, deflated sharpe)
         │
6. Persistence (SQLite) + BacktestResult döndür
```

## Dosya Bazlı Sorumluluk Tablosu

| Dosya | Sorumluluk |
|-------|-----------|
| `engine.py` | v1.0 canonical backtest motoru. Dinamik slippage, likidite kısıtı, CSV ledger dump, performans metrikleri. Singleton: `backtest_engine`. |
| `engine_v4.py` | v4.0 kurumsal motor. Panel feature (hızlı yol) + legacy ticker-by-ticker (referans yol). Canonical scoring, feature cache, quality cache, borderline tie-breaking. |
| `walk_forward.py` | Walk-forward validation. Purge + embargo gap'leri, expanding window desteği, Precision@K, IC, deflated sharpe. |
| `walk_forward_runner.py` | Engine v4.0 + WalkForward entegrasyonu. Her fold için point-in-time veri kesiti, ML model eğitimi (LightGBM multi-horizon), leakage guard. |
| `enhanced_walk_forward.py` | PurgeEmbargoWalkForward — numpy tabanlı, predictions/actuals ile çalışan alternatif WF. Precision@K, IC, hit rate, turnover, deflated sharpe. |
| `deflated_sharpe.py` | Deflated Sharpe Ratio (Bailey & López de Prado, 2014). Multiple testing düzeltmesi, Probabilistic Sharpe Ratio (PSR). Cornish-Fisher expansion ile higher-order moment düzeltmesi. |
| `bias_detector.py` | Look-ahead bias tespiti. Timestamp monotonicity, rolling window boundary, label-feature alignment, fold boundary, data revision integrity. Middleware olarak backtest'e entegre edilebilir. |
| `survivorship.py` | Survivorship bias yönetimi. Delisting event kayıtları, tarihsel evren hesaplama, bias düzeltmesi, bias büyüklüğü ölçümü. BIST-specific loader (henüz gerçek veri yok — uyarı ile boş döner). |
| `transaction_costs.py` | BIST gerçekçi işlem maliyeti modeli. Broker + BIST + MKK + Takasbank + BSMV. Spread modeli (likidite katmanına göre), slippage modeli (volatilite + hacim + emir boyutu), market impact (square-root model). |
| `pit_validator.py` | Point-in-time doğrulama. Fundamental veri publish_date vs report_date, revizyon sızıntısı, feature set PIT kontrolü, label üretimi zamanlaması, corporate action kayıtları. |
| `event_replay.py` | Belirli bir günü yeniden oynatma. Point-in-time data ile replay, karar karşılaştırma (expected vs actual), audit trail (hash chain), state snapshot & restore. |
| `deterministic.py` | Deterministik recovery. Checkpoint oluşturma/yükleme, random seed yönetimi, config versioning, reproducibility raporu, idempotency guard. |
| `benchmark.py` | Benchmark karşılaştırma. Jensen's alpha, beta, information ratio, tracking error, up/down capture ratio, correlation, R². |
| `canonical_adapter.py` | Backtest → CanonicalScoringPipeline adapter. Feature parity (prepare_features_for_inference), CS normalization, feature contract doğrulama. |
| `multi_asset_engine.py` | Çoklu hisse backtest. Portfolio-level risk limitleri, sektör maruziyet kontrolü, korelasyon kontrolü, gap risk (tavan/taban kilidi), likidite kısıtı, T+1 execution. |
| `persistence.py` | SQLite persistence. Run metadata, trades, equity curve. CRUD operasyonları. |
| `portfolio_sim.py` | PortfolioSimulatorV3. Pozisyon yaşam döngüsü, oversell prevention, cash accounting invariant, audit trail, BIST komisyon modeli, realistic cost entegrasyonu, benchmark tracking. |
| `scanner_parity.py` | Backtest-scanner parity garantisi. Feature, signal, risk, cost parity kontrolleri. Feature version lock. |

## Tasarım İlkeleri ve Kırmızı Çizgiler

1. **Gelecek veri kullanmak = ölüm.** Her feature sadece karar anına kadar olan veriden türetilmeli. PIT validator ve bias detector bunu zorunlu kılar.
2. **Aynı veri → aynı sonuç.** Deterministik motor; random seed, config hash ve checkpoint ile garanti edilir.
3. **Farklı kod = farklı sonuç yok.** Scanner ile backtest aynı kod yolunu kullanmalı (canonical_adapter + scanner_parity).
4. **Sahte veri üretmek yasaktır.** Survivorship handler'ın `create_known_bist_delistings()` fonksiyonu bilinçli olarak boş döner — gerçek delisting verisi olmadan düzeltme uygulanmaz.
5. **Tüm maliyetler dahil.** Komisyon, spread, slippage, market impact, BSMV — tek bileşen atlanmaz.
6. **Invariant ihlali = alarm.** PortfolioSimulator her gün `cash + market_value = equity` kontrolü yapar; ihlal audit log'a yazılır.

## Bilinen Sınırlamalar

- `survivorship.py` → `create_known_bist_delistings()` gerçek BIST delisting verisi içermez; manuel doldurma gerekir.
- `engine.py` (v1.0) tek hisse bazlı çalışır; çoklu hisse için `multi_asset_engine.py` kullanılmalı.
- `enhanced_walk_forward.py` numpy array tabanlıdır; DataFrame tabanlı pipeline ile doğrudan uyumlu değildir.
- `walk_forward_runner.py` → ML model eğitimi için minimum 50 sample gerekir; küçük evrenlerde rule-based fallback'a düşer.
- `transaction_costs.py` → Spread ve slippage modelleri kalibrasyon gerektirir; varsayılan değerler BIST ortalamasıdır.

## Cross-Reference

- **Scanner modülü** → `scanner_parity.py` ve `canonical_adapter.py` aracılığıyla aynı scoring fonksiyonunu kullanır.
- **Factors modülü** → `engine_v4.py` canonical scoring modunda fundamental factor skorlarını tüketir.
- **Event Study modülü** → `event_replay.py` event study mantığını kullanır; KAP event verileri backtest'te event-driven sinyal üretimi için beslenir.
- **ML katmanı** → `walk_forward_runner.py` LightGBM trainer ile multi-horizon model eğitir.
- **Features katmanı** → `engine_v4.py` feature_calculator, panel_engine, cross_sectional, seven_motors modüllerini tüketir.
