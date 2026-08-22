# MARKET STATE — Piyasa Durumu Motoru

## Giriş

Market State servisi, BIST-100 piyasasının anlık durumunu çoklu bileşenlerden hesaplayan kapsamlı bir motorudur. 7 breadth göstergesi, 8 bileşen state, 3 yöntemli ensemble rejim tespiti, geçiş takibi, 6 faktörlü risk appetite ve çoklu zaman ufku analizini tek bir `MarketStateOutput`'ta birleştirir. Intelligence ve Orchestrator servislerinin temel girdi kaynağıdır.

## Katman Haritası

```
┌─────────────────────────────────────────────────────────────────┐
│                   MARKET STATE SERVICE v2.0                      │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │  main.py — MarketStateService                            │   │
│  │  (Event Consumer: feature.updated, market.tick,           │   │
│  │   world_state.changed, news.event)                        │   │
│  └──────────────────────┬───────────────────────────────────┘   │
│                         │                                       │
│  ┌──────────────────────▼───────────────────────────────────┐   │
│  │  PIPELINE (her 30 saniyede bir veya event tetikle)        │   │
│  │                                                          │   │
│  │  1. MarketBreadthEngine.compute()                        │   │
│  │     ┌─────────────────────────────────────────────┐      │   │
│  │     │ 7 Gösterge:                                 │      │   │
│  │     │ • Advance-Decline Line (cumulative)         │      │   │
│  │     │ • AD Ratio (advancing / declining)          │      │   │
│  │     │ • McClellan Oscillator (EMA19-EMA39)        │      │   │
│  │     │ • McClellan Summation Index                 │      │   │
│  │     │ • TRIN / Arms Index                         │      │   │
│  │     │ • New Highs - New Lows (52-week)            │      │   │
│  │     │ • Breadth Thrust (advancing/total)          │      │   │
│  │     │ + Döviz izolasyonu (fx_momentum düzeltmesi) │      │   │
│  │     │ + Sektörel breadth                          │      │   │
│  │     └─────────────────────────────────────────────┘      │   │
│  │                         │                                │   │
│  │  2. ComponentStateEngine.compute_all()                   │   │
│  │     ┌─────────────────────────────────────────────┐      │   │
│  │     │ 8 Bileşen State:                            │      │   │
│  │     │ • Momentum: POSITIVE / NEGATIVE / NEUTRAL   │      │   │
│  │     │ • Volatility: LOW / NORMAL / HIGH / EXTREME │      │   │
│  │     │ • Volume: BELOW_AVG / AVG / ABOVE_AVG/SURGE│      │   │
│  │     │ • RSI: OVERSOLD / NEUTRAL / OVERBOUGHT      │      │   │
│  │     │ • Liquidity: TIGHT / NORMAL / LOOSE         │      │   │
│  │     │ • Sentiment: NEGATIVE / NEUTRAL / POSITIVE  │      │   │
│  │     │           / EUPHORIA                         │      │   │
│  │     │ • Macro: EXPANSION / CONTRACTION /           │      │   │
│  │     │         STAGFLATION / REFLATION              │      │   │
│  │     │ • Anomaly: count + severity                  │      │   │
│  │     │ + Fear/Greed composite (news+social+VIX+PCR)│      │   │
│  │     └─────────────────────────────────────────────┘      │   │
│  │                         │                                │   │
│  │  3. EnsembleRegimeDetector.detect()                      │   │
│  │     ┌─────────────────────────────────────────────┐      │   │
│  │     │ 3 Yöntem Weighted Voting:                   │      │   │
│  │     │ • Skor bazlı (regime.py) — %50 (varsayılan) │      │   │
│  │     │ • HMM (hmm_regime.py) — %30                 │      │   │
│  │     │ • GMM (sklearn) — %20                       │      │   │
│  │     │ + Rejime göre ağırlık adaptasyonu:          │      │   │
│  │     │   Crisis → HMM %45, Bull → Skor %60        │      │   │
│  │     │ + Backtest'ten ağırlık optimizasyonu        │      │   │
│  │     └─────────────────────────────────────────────┘      │   │
│  │                         │                                │   │
│  │  4. RegimeTransitionTracker.record()                     │   │
│  │     ┌─────────────────────────────────────────────┐      │   │
│  │     │ • Geçiş kaydı (from→to, timestamp, duration)│      │   │
│  │     │ • Stability score (son 20 gözlemde geçiş)   │      │   │
│  │     │ • Transition probability matrix              │      │   │
│  │     │ • Confidence trend (INCREASING/DECREASING)   │      │   │
│  │     │ • Alert'ler: beklenmedik geçiş, düşük       │      │   │
│  │     │   kararlılık, uzun süren rejim              │      │   │
│  │     └─────────────────────────────────────────────┘      │   │
│  │                         │                                │   │
│  │  5. RiskAppetiteEngine.compute()                         │   │
│  │     ┌─────────────────────────────────────────────┐      │   │
│  │     │ 6 Faktör (ağırlıklı):                       │      │   │
│  │     │ • Breadth (0.30) — piyasa genişliği         │      │   │
│  │     │ • Momentum (0.20) — piyasa gücü             │      │   │
│  │     │ • Volatility (0.20) — düşük vol = risk-on   │      │   │
│  │     │ • RSI (0.10) — aşırı alım/satım            │      │   │
│  │     │ • Sentiment (0.10) — fear/greed             │      │   │
│  │     │ • Macro (0.10) — makro ortam                │      │   │
│  │     │ Çıktı: [0,1] → RISK_OFF..RISK_ON           │      │   │
│  │     └─────────────────────────────────────────────┘      │   │
│  │                         │                                │   │
│  │  6. MultiTimeframeEngine.compute_all_timeframes()        │   │
│  │     ┌─────────────────────────────────────────────┐      │   │
│  │     │ • Intraday / Daily / Weekly / Monthly        │      │   │
│  │     │ • Cross-timeframe divergence detection       │      │   │
│  │     │ • Alignment score [0,1]                      │      │   │
│  │     │ • Dominant timeframe selection               │      │   │
│  │     └─────────────────────────────────────────────┘      │   │
│  │                         │                                │   │
│  │  7. MarketStateFormatter.format()                        │   │
│  │     └─► MarketStateOutput (tek birleşik çıktı)           │   │
│  │                         │                                │   │
│  │  8. Redis + ClickHouse + Event Bus + Prometheus          │   │
│  └──────────────────────────────────────────────────────────┘   │
│                                                                 │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │  api.py — REST Endpoints                                 │   │
│  │  GET /api/market/state      — Tam market state           │   │
│  │  GET /api/market/breadth    — Breadth detayları          │   │
│  │  GET /api/market/regime     — Ensemble regime            │   │
│  │  GET /api/market/transition — Geçiş istatistikleri       │   │
│  │  GET /api/market/multi-tf   — Çoklu zaman ufku           │   │
│  │  GET /api/market/alerts     — Aktif alert'ler            │   │
│  │  GET /api/market/health     — Sağlık durumu              │   │
│  └──────────────────────────────────────────────────────────┘   │
│                                                                 │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │  monitoring.py — Prometheus + Grafana                     │   │
│  │  • market_state_regime (gauge, encoded)                   │   │
│  │  • market_state_confidence, stability, breadth_pct        │   │
│  │  • market_state_risk_appetite, transitions, alerts        │   │
│  │  • Grafana dashboard JSON (12 panel)                      │   │
│  └──────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────┘
```

## Neden Bu Tasarım Seçimi?

| Karar | Neden |
|-------|-------|
| **7 Breadth Göstergesi** | Tek gösterge (ör. AD Ratio) yanıltıcı olabilir. McClellan + TRIN + Thrust birlikte bakıldığında piyasa genişliği daha güvenilir ölçülür. |
| **Döviz İzolasyonu** | BIST'te USDTRY yükseldiğinde hisseler düşer ama bu gerçek bearishlik değil. Breadth'i döviz etkisine göre düzeltmek false negative'i önler. |
| **3 Yöntem Ensemble** | Tek yöntem (skor veya HMM) yetersiz. Skor yorumlanabilir, HMM matematiksel, GMM hızlı. Ağırlıklı oylama ile robust karar. |
| **Rejime Göre Ağırlık Adaptasyonu** | Crisis'te HMM daha güvenilir (matematiksel model), Bull'da skor daha iyi (yorumlanabilirlik). Sabit ağırlık suboptimal. |
| **Stability Score** | Sık rejim değişimi = kararsız piyasa. Son 20 gözlemdeki geçiş oranı ile ölçülür. |
| **6 Faktörlü Risk Appetite** | Breadth tek başına yetersiz. Momentum, volatilite, sentiment, macro ile birleşince daha güvenilir. |
| **Multi-Timeframe** | Günlük BULL ama haftalık BEAR → divergence uyarısı. Farklı zaman ufukları farklı sinyal verebilir. |
| **30s Güncelleme** | Her tick'te yeniden hesaplama pahalı. 30 saniyelik debounce ile performans korunur. |
| **ClickHouse Depolama** | Tarihsel market state verisi analiz ve backtest için ClickHouse'a yazılır. |
| **Prometheus + Grafana** | Operasyonel izleme için standart metrikler. 12 panelli Grafana dashboard. |

## Uçtan Uca Veri Akışı

```
┌─────────────┐    ┌─────────────┐    ┌─────────────┐
│ Feature     │    │ Market Tick │    │ World State │
│ Updated     │    │ Event       │    │ Changed     │
└──────┬──────┘    └──────┬──────┘    └──────┬──────┘
       │                  │                  │
       ▼                  ▼                  ▼
  _on_feature_update  _on_tick        _on_world_state
  (RSI, momentum,     (price,         (usd_strength,
   volatility,         volume)          vix_level)
   volume_zscore)
       │                  │                  │
       └──────────┬───────┘                  │
                  │                          │
                  ▼                          │
         _instrument_states                  │
         (tüm hisselerin                     │
          anlık durumu)                      │
                  │                          │
                  ▼                          │
    ┌─────────────┴─────────────┐            │
    │   _compute_market_state() │◄───────────┘
    │   (her 30 saniyede)       │
    └─────────────┬─────────────┘
                  │
    ┌─────────────▼─────────────┐
    │ 1. BreadthEngine.compute()│──► BreadthResult
    │    (7 gösterge)           │    (pct_advancing, mcclellan,
    │    + fx_momentum düzeltme │     trin, thrust, alert_level)
    └─────────────┬─────────────┘
                  │
    ┌─────────────▼─────────────┐
    │ 2. ComponentEngine        │──► ComponentStates
    │    .compute_all()         │    (8 state + fear/greed)
    │    (momentum, vol, RSI,   │
    │     liquidity, sentiment, │
    │     macro, anomaly)       │
    └─────────────┬─────────────┘
                  │
    ┌─────────────▼─────────────┐
    │ 3. EnsembleDetector       │──► EnsembleResult
    │    .detect()              │    (regime, confidence,
    │    (skor + HMM + GMM)     │     consensus, probabilities)
    └─────────────┬─────────────┘
                  │
    ┌─────────────▼─────────────┐
    │ 4. TransitionTracker      │──► TransitionStats
    │    .record()              │    (stability, duration,
    │    + .check_alerts()      │     transition_matrix)
    └─────────────┬─────────────┘
                  │
    ┌─────────────▼─────────────┐
    │ 5. RiskAppetiteEngine     │──► risk_appetite [0,1]
    │    .compute()             │    + state (RISK_ON/OFF)
    │    (6 faktör)             │
    └─────────────┬─────────────┘
                  │
    ┌─────────────▼─────────────┐
    │ 6. MultiTimeframeEngine   │──► MultiTimeframeResult
    │    .compute_all_timeframes│    (daily, weekly states,
    │    (daily + weekly)       │     alignment, divergences)
    └─────────────┬─────────────┘
                  │
    ┌─────────────▼─────────────┐
    │ 7. MarketStateFormatter   │──► MarketStateOutput
    │    .format()              │    (tek birleşik çıktı)
    └─────────────┬─────────────┘
                  │
    ┌─────────────▼─────────────┐
    │ 8. Yayın                  │
    │ • Redis (market_state,    │
    │   TTL: 60s)               │
    │ • ClickHouse (market_     │
    │   states tablosu)         │
    │ • Event Bus:              │
    │   - market_state.changed  │
    │   - regime.transition     │
    │   - breadth.alert         │
    │   - liquidity.alert       │
    │   - anomaly.cluster       │
    │   - sentiment.shift       │
    │   - multi_tf.divergence   │
    │ • Prometheus gauges       │
    └───────────────────────────┘
```

## Dosya Bazlı Sorumluluk Tablosu

| Dosya | Sorumluluk | Kritik Çıktı |
|-------|-----------|--------------|
| `main.py` | Ana servis, event consumer, pipeline orchestrator | `MarketStateOutput` |
| `breadth_engine.py` | 7 breadth göstergesi + döviz izolasyonu + sektörel breadth | `BreadthResult` |
| `component_states.py` | 8 bileşen state (momentum, vol, volume, RSI, liquidity, sentiment, macro, anomaly) + Fear/Greed composite | `ComponentStates` |
| `ensemble_regime.py` | 3 yöntem weighted voting (skor %50, HMM %30, GMM %20), rejime göre ağırlık adaptasyonu | `EnsembleResult` |
| `transition_tracker.py` | Geçiş kaydı, stability score, transition matrix, confidence trend, alert'ler | `TransitionStats` |
| `risk_appetite.py` | 6 faktörlü risk appetite [0,1], detaylı katkı analizi | `float` + `state` |
| `multi_timeframe.py` | Intraday/Daily/Weekly/Monthly state, cross-timeframe divergence, alignment score | `MultiTimeframeResult` |
| `output_formatter.py` | Tüm bileşenleri tek `MarketStateOutput`'ta birleştirir | `MarketStateOutput` |
| `api.py` | 7 REST endpoint (state, breadth, regime, transition, multi-tf, alerts, health) | JSON response |
| `monitoring.py` | Prometheus metrikleri (12 gauge/counter), Grafana dashboard JSON (12 panel) | `MarketStateMetrics` |

## Tasarım İlkeleri ve Kırmızı Çizgiler

### İlkeler
1. **Tek Kaynak Doğruluk (Single Source of Truth)**: Rejim tespiti sadece `EnsembleRegimeDetector`'dan gelir. Diğer modüller kendi rejim tahminlerini yapmaz.
2. **Graceful Degradation**: HMM veya GMM çalışamazsa, kalan yöntemlerle devam edilir. Hiçbiri çalışmazsa "UNKNOWN" döner.
3. **Döviz İzolasyonu**: BIST breadth'i döviz etkisinden arındırılır — USDTRY kaynaklı düşüş gerçek bearishlik değildir.
4. **Smoothing (Chatter Önleme)**: Rejim geçişleri minimum süre filtresi ile düzeltilir (hızlı titreşim önlenir).
5. **Config-Driven**: Tüm eşikler `settings`'ten okunur (breadth_mcclellan_ema_short, regime_score_weight vb.).
6. **Event-Driven**: `_compute_market_state()` sadece event geldiğinde ve 30s debounce ile çalışır.

### Kırmızı Çizgiler
- ❌ Breadth hesaplamasında düşük likiditeli hisseler (volume < 10,000) hariç tutulur.
- ❌ Rejim confidence'ı belirsizse (iki rejim eşit skor) "UNKNOWN" döner, zorla seçim yapılmaz.
- ❌ Beklenmedik geçiş (CRISIS → BULL) otomatik alert üretir, manuel doğrulama gerekir.
- ❌ Risk appetite skoru [0,1] aralığında clamp edilir — aşırı değerler sızamaz.

## Bilinen Sınırlamalar

| Sınırlama | Açıklama |
|-----------|---------|
| **HMM soğuk başlangıç** | 63 günden az veri ile HMM eğitilemez, ensemble 2 yöntemle çalışır. |
| **GMM opsiyonel** | `sklearn` yoksa GMM devre dışı, ensemble skor + HMM ile çalışır. |
| **Weekly aggregate basit** | Haftalık veri olarak günlük veri kullanılır — gerçek haftalık OHLCV aggregation henüz yok. |
| **In-memory state** | `_instrument_states` restart sonrası sıfırlanır. Redis'ten yeniden yükleme mekanizması yok. |
| **Sektörel breadth manuel** | `sector_map` parametre olarak gelmeli — otomatik sektör tespiti yok. |
| **Sentiment basit** | News sentiment EMA'sı basit — sosyal medya entegrasyonu sınırlı. |
| **ClickHouse opsiyonel** | ClickHouse yoksa insert sessizce başarısız olur. |

## Cross-Reference

- **Intelligence** → `regime.py` → `MacroRegimeDetector` import edilir; macro regime skorları intelligence rejim skorlarına katılır.
- **Intelligence** → `world_state.py` → `WorldStateManager` market_state tarafından `world_state.changed` event'i ile beslenir.
- **Intelligence** → `pipeline.py` → `IntelligencePipeline` market_state çıktısını (`MarketStateOutput`) girdi olarak kullanır.
- **Orchestrator** → Market state Redis'ten okunur (`redis_get("market_state")`).
- **Event Bus** → `market_state.changed`, `regime.transition`, `breadth.alert`, `liquidity.alert`, `anomaly.cluster`, `sentiment.shift`, `multi_tf.divergence` event'leri publish edilir.
- **Macro** → `macro.regime_detector` → Macro regime skorları ensemble'a %15 ağırlıkla katılır.
- **Prometheus** → `market_state_regime`, `market_state_confidence`, `market_state_breadth_pct` vb. gauge'lar.
