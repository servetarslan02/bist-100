# Bölüm 23-32 Uygulama Planı — 58 Modül

**Tarih:** 2026-08-18
**Durum:** BAŞLADI

---

## Genel Durum

| Kategori | Durum |
|----------|-------|
| Bölüm 1-8 (61 modül) | ✅ Kodda var, 14 bug düzeltildi |
| Bölüm 9-16 (8 bölüm) | ✅ Kodda var |
| Bölüm 17-22 (6 bölüm) | ✅ Kodda var |
| **Bölüm 23-32 (58 modül)** | ❌ BAŞLANACAK |
| Import testi | ✅ 104/104 başarılı |

---

## Aşama Sırası

| Aşama | Bölüm | İçerik | Modül Sayısı | Durum |
|-------|-------|--------|-------------|-------|
| 1 | 23 | BIST Piyasa Kuralları | 7 | ✅ 30 test geçti |
| 2 | 24 | Feature Engineering | 3 | ✅ 9 test geçti |
| 3 | 25 | ML Modelleri | 6 | ✅ 36 test geçti |
| 4 | 26 | Alternative Data | 5 | ✅ |
| 5 | 27 | SPK Regülasyon | 5 | ✅ |
| 6 | 28 | Turkish Macro | 7 | ✅ |
| 7 | 29 | FinRL/FinGPT | 5 | ✅ |
| 8 | 30 | Factor Investing | 7 | ✅ |
| 9 | 31 | Event Study | 7 | ✅ |
| 10 | 32 | Options/VIOP | 6 | ✅ |
| 11 | — | Entegrasyon + Test | — | ✅ 160/160 import |

---

## Aşama 1: BIST Piyasa Kuralları (7 modül)

### 1.1 services/core/short_selling.py
- `can_short_sell(ticker, current_price, last_trade_price)` → {allowed, reason}
- BIST-30 kontrolü, uptick rule, brüt takas, SPK geçici yasak
- Bağımlılık: bist_universe.py

### 1.2 services/core/fee_calculator.py
- `calculate_commission(amount, broker_rate)` → {broker_fee, bist_fee, mkk_fee, bsmv, total}
- Broker + BIST + MKK + BSMV + minimum ₺1
- Mevcut: backtest/engine.py basit oran → YENİ

### 1.3 services/core/price_limits.py
- `check_price_limit(ticker, current_price, reference_price)` → {limit_hit, direction, change_pct, limit}
- Normal %10, volatil %5/%20

### 1.4 services/core/halt_monitor.py
- `check_halt(ticker)` → {halted, reason, expected_resume, action}
- Şirket bazlı durdurma, KAP öncesi, bedelsiz

### 1.5 services/core/gross_settlement.py
- `check_gross_settlement(ticker)` → {is_gross, effect, impact}
- Brüt takas listesi, T+0

### 1.6 services/core/viop_monitor.py
- `check_viop_margin(position)` → {margin_call, required, available, action}
- SPAN teminat

### 1.7 services/core/compliance.py
- `check_spk_compliance(action, ticker, amount, portfolio)` → {notification_required, violation, action}
- %5 bildirim, manipülasyon kontrolü

---

## Aşama 2: Feature Engineering (3 modül)

### 2.1 services/features/technical_features.py
- compute_trend_features, compute_momentum_features, compute_volatility_features, compute_volume_features, compute_bist_specific_features
- Mevcut: extended_indicators.py güncellenecek

### 2.2 services/features/feature_selector.py
- select_features_shap, filter_correlated_features
- Bağımlılık: scikit-learn

### 2.3 services/features/feature_store.py (güncelleme)
- Mevcut store.py güncellenecek

---

## Aşama 3: ML Modelleri (6 modül)

### 3.1 services/ml/xgboost_model.py
- train_xgboost(X_train, y_train, X_val, y_val) → model
- Bağımlılık: xgboost

### 3.2 services/ml/lightgbm_model.py (güncelleme)
- Mevcut lightgbm_trainer.py güncellenecek

### 3.3 services/ml/lstm_model.py
- class StockLSTM(nn.Module)
- Bağımlılık: torch

### 3.4 services/ml/transformer_model.py
- class StockTransformer(nn.Module)
- Bağımlılık: torch

### 3.5 services/ml/model_comparator.py
- compare_models(models, X_train, y_train, X_test, y_test) → results

### 3.6 services/ml/ensemble.py
- ensemble_predict(models, weights, X) → predictions

---

## Aşama 4: Alternative Data (5 modül)

### 4.1 services/alternative/__init__.py
### 4.2 services/alternative/web_scraping.py
- compute_web_features(scraped_data, ticker) → features

### 4.3 services/alternative/social.py
- compute_social_features(social_data, ticker) → features

### 4.4 services/alternative/jobs.py
- compute_job_features(job_data, ticker) → features

### 4.5 services/alternative/credit_card.py
- compute_cc_features(cc_data, ticker) → features

### 4.6 services/alternative/satellite.py
- compute_satellite_features(sat_data, ticker) → features

---

## Aşama 5: SPK Regülasyon (5 modül)

### 5.1 services/core/manipulation_detector.py
- detect_manipulation(trade_history, order_history) → alerts
- Wash trading, spoofing, layering

### 5.2 services/core/insider_detector.py
- detect_insider_pattern(trades, kap_events) → alerts

### 5.3 services/core/algo_notification.py
- generate_algo_notification(strategy) → notification

### 5.4 services/core/reporting.py
- generate_daily_report(portfolio, trades, risk_metrics) → report

### 5.5 services/core/tax.py
- calculate_tax(trade) → {profit, tax_rate, tax, holding_days}

---

## Aşama 6: Turkish Macro (7 modül)

### 6.1 services/macro/__init__.py
### 6.2 services/macro/tcmb.py
- compute_tcmb_features(tcmb_data) → features

### 6.3 services/macro/inflation.py
- compute_inflation_features(inflation_data) → features

### 6.4 services/macro/fx.py
- compute_fx_features(fx_data, stock_data) → features

### 6.5 services/macro/cds.py
- compute_cds_features(cds_data) → features

### 6.6 services/macro/credit.py
- compute_credit_features(credit_data) → features

### 6.7 services/macro/current_account.py
- compute_ca_features(ca_data) → features

### 6.8 services/macro/calendar.py
- get_macro_events(date) → events

---

## Aşama 7: FinRL/FinGPT (5 modül)

### 7.1 services/ml/finrl_bist.py
- class BISTTradingEnv(gym.Env)

### 7.2 services/ml/fingpt.py
- class FinGPTSentiment

### 7.3 services/ml/hybrid_model.py
- hybrid_predict(rl_model, fingpt, news_data, market_data)

### 7.4 services/ml/rl_agent.py
- train_rl_agent(env, total_timesteps)

### 7.5 services/ml/qlib_integration.py

---

## Aşama 8: Factor Investing (7 modül)

### 8.1 services/factors/__init__.py
### 8.2 services/factors/piotroski.py
- calculate_f_score(financials) → score (0-9)

### 8.3 services/factors/beneish.py
- calculate_m_score(financials) → m_score (eşik: -1.78)

### 8.4 services/factors/altman.py
- calculate_z_score(financials) → z_score (eşik: 1.81/2.99)

### 8.5 services/factors/fama_french.py
- calculate_factor_scores(stock, universe) → scores

### 8.6 services/factors/bist_anomalies.py
- calculate_bist_anomalies(stock, market_data) → anomalies

### 8.7 services/factors/ranking.py
- rank_stocks(universe, factors) → ranked

### 8.8 services/factors/performance.py
- track_factor_performance(factor_returns, benchmark_returns) → results

---

## Aşama 9: Event Study (7 modül)

### 9.1 services/event_study/__init__.py
### 9.2 services/event_study/expected_return.py
- calculate_expected_return(stock_returns, market_returns, estimation_window)

### 9.3 services/event_study/abnormal_return.py
- calculate_abnormal_return(stock_returns, market_returns, alpha, beta, event_window)

### 9.4 services/event_study/car.py
- calculate_car(abnormal_returns, event_window) → car

### 9.5 services/event_study/statistical_test.py
- test_significance(car, std_error) → {t_statistic, p_value, significant}

### 9.6 services/event_study/kap_event.py
- analyze_kap_event(ticker, event_type, event_date)

### 9.7 services/event_study/macro_event.py
- analyze_tcmb_event(rate_actual, rate_expected, market_returns)

### 9.8 services/event_study/impact.py
- calculate_event_impact(car, p_value, volume_change) → {impact_score, magnitude, direction}

---

## Aşama 10: Options/VIOP (6 modül)

### 10.1 services/viop/__init__.py
### 10.2 services/viop/options_pricing.py
- black_scholes(S, K, T, r, sigma, option_type) → price

### 10.3 services/viop/greeks.py
- calculate_greeks(S, K, T, r, sigma, option_type) → {delta, gamma, theta, vega, rho}

### 10.4 services/viop/strategies.py
- create_covered_call, create_protective_put

### 10.5 services/viop/parity.py
- check_put_call_parity(...) → {parity_holds, deviation, arbitrage_opportunity}

### 10.6 services/viop/margin.py
- calculate_span_margin(positions) → total_margin

### 10.7 services/viop/hedging.py
- hedge_portfolio(portfolio_value, beta, futures_price) → {hedge_ratio, contracts_needed}

---

## Aşama 11: Entegrasyon + Test

1. Tüm 58 modülü run_all_imports.py'ye ekle
2. Import testi çalıştır (162 modül)
3. Her modül için unit test yaz
4. Entegrasyon testleri
5. Git commit + push

---

## Uygulama Kuralı

Her modül için:
1. Modülü oluştur
2. Unit test yaz
3. Testi çalıştır → geçmezse düzelt
4. Mevcut sistemle entegre et
5. Import testi çalıştır
6. Sonraki modüle geç

**YARIM İŞ YOK. PLACEHOLDER YOK. MOCK YOK.**
