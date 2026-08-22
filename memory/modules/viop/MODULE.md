# VIOP — Vadeli İşlem ve Opsiyon Piyasası

## Giriş

VIOP modülü, Borsa İstanbul Vadeli İşlem ve Opsiyon Piyasası için kapsamlı bir opsiyon fiyatlama, Greeks hesaplama, strateji oluşturma, hedge yönetimi ve risk analizi sistemi sağlar. Black-Scholes tabanlı fiyatlamadan SPAN teminat hesaplamasına, 9 opsiyon stratejisinden futures-spot arbitraj tespitine kadar tüm VIOP işlemlerini destekler.

## Katman Haritası

```
┌─────────────────────────────────────────────────────────────┐
│                    enhanced_options.py                        │
│                    (Tüm VIOP sistemi tek modülde)             │
├──────────┬──────────┬──────────┬──────────┬─────────────────┤
│ Pricing  │ Greeks   │Strategies│ Hedging  │ Risk & Margin   │
│          │          │          │          │                 │
│ Black-   │ Delta    │ Covered  │ Delta    │ SPAN Margin     │
│ Scholes  │ Gamma    │ Call     │ Hedger   │ (16 senaryo)    │
│          │ Theta    │Protective│ Gamma    │                 │
│ Implied  │ Vega     │ Put      │ Scalp    │ VIOP Risk       │
│ Vol      │ Rho      │ Collar   │          │ Calculator      │
│ (Newton- │          │ Iron     │          │                 │
│ Raphson) │Portfolio │ Condor   │          │ Futures-Spot    │
│          │ Greeks   │ Straddle │          │ Arbitrage       │
│          │          │ Strangle │          │                 │
│          │          │ Bull Call│          │ Put-Call        │
│          │          │ Spread   │          │ Parity          │
│          │          │ Bear Put │          │                 │
│          │          │ Spread   │          │ Options         │
│          │          │ Butterfly│          │ Backtest        │
├──────────┴──────────┴──────────┴──────────┴─────────────────┤
│                    OptionsChain                               │
│                    (Opsiyon zinciri veri modeli)              │
├─────────────────────────────────────────────────────────────┤
│                    contract_catalog.py                        │
│                    VIOPContractCatalog                        │
│                    (XU030, DOL, EUR, GAU, CAY, BUD, PAM, ELK)│
├──────────┬──────────┬──────────┬──────────┬─────────────────┤
│greeks.py │options_  │hedging.py│strategies│margin.py        │
│(wrapper) │pricing.py│(wrapper) │.py       │(wrapper)        │
│          │(wrapper) │          │(wrapper) │                 │
│parity.py │          │          │          │                 │
│(wrapper) │          │          │          │                 │
└──────────┴──────────┴──────────┴──────────┴─────────────────┘
```

## Neden Bu Tasarım Seçimi?

| Karar | Neden |
|-------|-------|
| Tek modül (enhanced_options.py) | Tüm opsiyon mantığı tek dosyada — döngüsel import yok, bakım kolay |
| Wrapper dosyalar (greeks.py, options_pricing.py vb.) | Geriye uyumluluk — eski import'lar `from viop.greeks import calculate_greeks` şeklinde çalışmaya devam eder |
| Black-Scholes + scipy fallback | scipy yoksa `math.erf` ile manuel normal CDF; her ortamda çalışır |
| Newton-Raphson + bisection IV | Newton-Raphson hızlı ama diverge olabilir; bisection garantili konverjans sağlar |
| 9 strateji | En yaygın opsiyon stratejileri kapsanmış; her biri max_profit, max_loss, breakeven, risk_reward hesaplar |
| SPAN 16 senaryo | BIST SPAN modeline uygun; fiyat + volatilite kombinasyonları ile en kötü senaryo teminat olarak alınır |
| Contract catalog (hardcoded) | BIST VIOP sözleşme tanımları (sözleşme büyüklüğü, tick size, margin rate, vade ayları) — API'ye bağımlı olmadan çalışır |
| Options backtest | Strateji performansını geçmiş veri üzerinde test etme — parametre optimizasyonu için |

## Uçtan Uca Veri Akışı

```
1. Opsiyon Fiyatlama:
   black_scholes(S, K, T, r, sigma, option_type) → teorik fiyat
   calculate_greeks(S, K, T, r, sigma, option_type) → {delta, gamma, theta, vega, rho}
   implied_volatility.calculate(market_price, S, K, T, r) → IV

2. Options Chain:
   OptionsChain(underlying, spot_price) → add_quote() → get_chain(expiry)
   calculate_all_greeks(sigma) → tüm opsiyonlar için Greeks

3. Strateji Oluşturma:
   options_strategies.covered_call(spot, strike, premium) → StrategyResult
   options_strategies.iron_condor(...) → StrategyResult (4 bacak)
   options_strategies.butterfly(...) → StrategyResult (3 strike)

4. Hedge Yönetimi:
   delta_hedger.hedge(portfolio_delta, spot_price) → DeltaHedgeResult
   delta_hedger.gamma_scalp(gamma, spot, move_pct) → gamma P&L

5. Teminat Hesaplama:
   SPANMarginCalculator.calculate(positions) → 16 senaryo P&L → en kötü = teminat

6. Arbitraj Tespiti:
   futures_spot_arbitrage.analyze(spot, futures, r, q, T) → ArbitrageResult
   check_put_call_parity(call, put, spot, K, r, T) → parity deviation

7. Portföy Risk:
   viop_risk.calculate_portfolio_viop_risk(positions, portfolio_value) → risk metrikleri
   viop_risk.calculate_margin_requirement(positions) → toplam teminat

8. Backtest:
   options_backtest.backtest_covered_call(price_series) → BacktestResult
   options_backtest.backtest_iron_condor(price_series) → BacktestResult
```

## Dosya Bazlı Sorumluluk Tablosu

| Dosya | Sorumluluk |
|-------|-----------|
| `enhanced_options.py` | **Ana modül** — black_scholes (fiyatlama), calculate_greeks (5 Greeks), ImpliedVolatility (Newton-Raphson + bisection), OptionsChain (opsiyon zinciri veri modeli), PortfolioGreeks (toplu Greeks aggregation), OptionsStrategies (9 strateji: covered_call, protective_put, collar, iron_condor, straddle, strangle, bull_call_spread, bear_put_spread, butterfly), DeltaHedger (delta hedge + gamma scalping), SPANMarginCalculator (16 senaryo), FuturesSpotArbitrage (cost-of-carry), check_put_call_parity, VIOPRiskCalculator (portföy risk + margin), OptionsBacktestEngine (covered_call + iron_condor backtest) |
| `contract_catalog.py` | VIOPContractCatalog — 8 sözleşme tanımları (XU030, XU030D, DOL, EUR, GAU, CAY, BUD, PAM, ELK), sözleşme büyüklüğü/tick size/margin rate/vade ayları, vade tarihi hesaplama, teminat ve K/Z hesaplama |
| `greeks.py` | Wrapper — `calculate_greeks` fonksiyonunu enhanced_options'tan yeniden dışa aktarır |
| `options_pricing.py` | Wrapper — `black_scholes` fonksiyonunu enhanced_options'tan yeniden dışa aktarır |
| `hedging.py` | Wrapper — `hedge_portfolio` fonksiyonu (portföy beta'sından delta hedge hesaplama) |
| `strategies.py` | Wrapper — `create_covered_call`, `create_protective_put` fonksiyonları |
| `margin.py` | Wrapper — `calculate_span_margin` fonksiyonu (basitleştirilmiş arayüz) |
| `parity.py` | Wrapper — `check_put_call_parity` fonksiyonunu enhanced_options'tan yeniden dışa aktarır |

## Tasarım İlkeleri ve Kırmızı Çizgiler

1. **Put-call parity korunur** — `sigma=0` durumunda bile `C - P = S - K*e^(-rT)` sağlanır; `max(S-K, 0)` yerine `max(S - K*e^(-rT), 0)` kullanılır.
2. **IV her zaman konverje** — Newton-Raphson diverge olursa bisection fallback çalışır; max 200 iterasyon.
3. **Greeks boundary handling** — `T<=0` veya `sigma<=0` durumunda intrinsic Greeks döndürülür (crash yok).
4. **SPAN senaryoları sabit** — 16 senaryo (fiyat ±3/6/10/15%, vol +0/2/4/6/8%) — BIST standardına uygun.
5. **Contract catalog hardcoded** — API erişimi yokken bile çalışır; manuel güncelleme gerektirir.
6. **Backtest point-in-time** — Gelecek veri sızıntısı yok; `i + holding_days` ile exit.
7. **Infinity handling** — Protective put ve straddle'da `max_profit=float("inf")` — sınırsız upside.

## Bilinen Sınırlamalar

- **Black-Scholes varsayımları** — Sabit volatilite, log-normal dağılım, sürekli hedge — gerçek piyasada sapmalar olur.
- **Amerikan opsiyon yok** — Sadece Avrupa tipi opsiyon fiyatlaması; BIST'te Amerikan opsiyonlar da var.
- **Contract catalog manuel** — Yeni sözleşme eklenmesi veya değişiklikler kod güncellemesi gerektirir.
- **Backtest basit** — Slippage, likidite kısıtlamaları, transaction cost dahil değil.
- **IV hesaplama hızı** — Bisection fallback 200 iterasyon sürebilir; büyük opsiyon zincirlerinde yavaşlık.
- **Türkçe terminoloji** — Kod İngilizce, dokümantasyon Türkçe; karışıklık olabilir.

## Cross-Reference

- **Agent System** → `risk_assessor.py` → VIOP pozisyon riskleri risk agent'a bilgi olarak gider
- **API** → `v1/viop.py` → opsiyon fiyatlaması, Greeks, strateji, teminat endpoint'leri
- **Portfolio** → Portfolio manager, VIOP pozisyonlarını hedge etmek için delta hedger kullanır
- **Scanner** → Opportunity engine, opsiyon volatilite anomalilerini tespit eder
- **Scheduler** → `risk_monitoring` job'u → VIOP pozisyon riskleri periyodik kontrol edilir
