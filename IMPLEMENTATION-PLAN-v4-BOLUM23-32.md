# Uygulama Planı v4 — Bölüm 23-32 (Detaylı İnceleme)

## Durum Özeti

| Kategori | Eski Plan | Gerçek İhtiyaç |
|----------|----------|----------------|
| Toplam yeni modül | 20 | **49** (10'u mevcut kodda kısmen var) |
| Bölüm 23 | 4 | **7** |
| Bölüm 24 | 2 | **3** (1'i mevcut güncellenecek) |
| Bölüm 25 | 1 | **6** |
| Bölüm 26 | 3 | **5** |
| Bölüm 27 | 2 | **5** (1'i bölüm 23 ile birleşik) |
| Bölüm 28 | 0 | **7** (mevcut macro.py güncellenecek) |
| Bölüm 29 | 1 | **5** |
| Bölüm 30 | 3 | **7** |
| Bölüm 31 | 2 | **7** |
| Bölüm 32 | 2 | **6** |

---

## Mevcut Kodda Kısmen Olan Fonksiyonlar

| Fonksiyon | Mevcut Konum | Durum |
|-----------|-------------|-------|
| commission | `backtest/engine.py:124` | Basit oran, detaylı fee_breakdown yok |
| halt | `core/market_calendar.py:203` | add_halt() var, şirket bazlı halt yok |
| manipulation | `features/sentiment.py:194` | _detect_manipulation() var, SPK uyumlu değil |
| tcmb features | `features/macro.py:90` | compute_rate_features() var, detaylı değil |
| inflation | `features/macro.py:115` | compute_inflation_features() var, TMS29 yok |
| tax rate | `intelligence/valuation/engine.py:79` | DEFAULT_TAX_RATE var, detaylı vergi yok |

---

## AŞAMA 1: Bölüm 23 — BIST Piyasa Kuralları (7 modül)

### 1.1 services/core/short_selling.py

```python
def can_short_sell(ticker, current_price, last_trade_price):
    # BIST-30 kontrolü
    # Uptick rule
    # Brüt takas kontrolü
    # SPK geçici yasak kontrolü
    return {"allowed": bool, "reason": str}
```

**Bağımlılık:** `bist_universe.py` (BIST-30 listesi)

### 1.2 services/core/fee_calculator.py

```python
def calculate_commission(amount, broker_rate=0.0003):
    # Broker komisyonu
    # BIST payı
    # MKK payı
    # BSMV
    # Minimum ₺1
    return {"broker_fee", "bist_fee", "mkk_fee", "bsmv", "total"}
```

**Mevcut:** `backtest/engine.py`'de basit oran var → YENİ yazılacak

### 1.3 services/core/price_limits.py

```python
def check_price_limit(ticker, current_price, reference_price):
    # Normal limit: %10
    # Volatil hisse: %5 veya %20
    return {"limit_hit", "direction", "change_pct", "limit"}
```

**Bağımlılık:** Yok

### 1.4 services/core/halt_monitor.py

```python
def check_halt(ticker):
    # Şirket bazlı durdurma
    # KAP açıklaması öncesi
    # Bedelsiz sermaye artırımı
    return {"halted", "reason", "expected_resume", "action"}
```

**Mevcut:** `market_calendar.py`'de genel halt var → şirket bazlı YENİ

### 1.5 services/core/gross_settlement.py

```python
def check_gross_settlement(ticker):
    # Brüt takas listesi
    # T+0 ödeme
    return {"is_gross", "effect", "impact"}
```

**Bağımlılık:** Yok

### 1.6 services/core/viop_monitor.py

```python
def check_viop_margin(position):
    # SPAN teminat
    # Teminat yeterliliği
    return {"margin_call", "required", "available", "action"}
```

**Bağımlılık:** Yok

### 1.7 services/core/compliance.py

```python
def check_spk_compliance(action, ticker, amount, portfolio):
    # %5 bildirim yükümlülüğü
    # Manipülasyon kontrolü
    return {"notification_required", "violation", "action"}
```

**Bağımlılık:** `manipulation_detector.py` (bölüm 27)

---

## AŞAMA 2: Bölüm 24 — Feature Engineering (3 modül)

### 2.1 services/features/technical_features.py

```python
def compute_trend_features(prices):       # SMA, EMA, MACD, crossover
def compute_momentum_features(prices, highs, lows):  # RSI, ROC, Stochastic
def compute_volatility_features(prices, highs, lows, closes):  # ATR, BB, vol
def compute_volume_features(prices, volumes):  # OBV, VWAP, MFI
def compute_bist_specific_features(market_data):  # USDTRY, TCMB, CDS
```

**Mevcut:** `features/extended_indicators.py` var → teknik göstergeler kısmen orada
**Aksiyon:** Mevcut extended_indicators.py'yi güncelle veya birleştir

### 2.2 services/features/feature_store.py

```python
def save(ticker, date, features):
def get(ticker, date):
def get_range(ticker, start_date, end_date):
```

**Mevcut:** `features/store.py` var → güncellenecek

### 2.3 services/features/feature_selector.py

```python
def select_features_shap(model, X_train, y_train, top_n=20):
def filter_correlated_features(X, threshold=0.95):
```

**Bağımlılık:** scikit-learn, shap

---

## AŞAMA 3: Bölüm 25 — ML Model Seçimi (6 modül)

### 3.1 services/ml/xgboost_model.py

```python
def train_xgboost(X_train, y_train, X_val, y_val):
    # XGBClassifier, early stopping
    return model
```

### 3.2 services/ml/lightgbm_model.py

```python
def train_lightgbm(X_train, y_train, X_val, y_val):
    # LGBMClassifier, early stopping
    return model
```

### 3.3 services/ml/lstm_model.py

```python
class StockLSTM(nn.Module):
    def __init__(self, input_size, hidden_size=64, num_layers=2):
    def forward(self, x):
```

### 3.4 services/ml/transformer_model.py

```python
class StockTransformer(nn.Module):
    def __init__(self, input_size, d_model=64, nhead=4, num_layers=2):
    def forward(self, x):
```

### 3.5 services/ml/model_comparator.py

```python
def compare_models(models, X_train, y_train, X_test, y_test):
    # accuracy, precision, recall, f1, ic
    return results
```

### 3.6 services/ml/ensemble.py

```python
def ensemble_predict(models, weights, X):
    # Ağırlıklı ortalama
    return predictions
```

**Bağımlılık:** xgboost, lightgbm, torch, scikit-learn

---

## AŞAMA 4: Bölüm 26 — Alternative Data (5 modül)

### 4.1 services/alternative/web_scraping.py

```python
def compute_web_features(scraped_data, ticker):
    # job_posting_growth, review_count_growth, price_vs_competitors
    return features
```

### 4.2 services/alternative/social.py

```python
def compute_social_features(social_data, ticker):
    # social_sentiment, social_volume, social_viral
    return features
```

### 4.3 services/alternative/jobs.py

```python
def compute_job_features(job_data, ticker):
    # job_posting_growth, tech_hiring_pct, layoff_signal
    return features
```

### 4.4 services/alternative/credit_card.py

```python
def compute_cc_features(cc_data, ticker):
    # cc_spend_growth, cc_vs_sector, cc_seasonal_deviation
    return features
```

### 4.5 services/alternative/satellite.py

```python
def compute_satellite_features(sat_data, ticker):
    # factory_traffic_change, store_traffic_change
    return features
```

**Bağımlılık:** Yok (data dictionary tabanlı)

---

## AŞAMA 5: Bölüm 27 — Regülasyon SPK (5 modül)

### 5.1 services/core/manipulation_detector.py

```python
def detect_manipulation(trade_history, order_history):
    # Wash trading, spoofing, layering, volume manipulation
    return alerts
```

**Mevcut:** `features/sentiment.py`'de _detect_manipulation() var → SPK uyumlu YENİ

### 5.2 services/core/insider_detector.py

```python
def detect_insider_pattern(trades, kap_events):
    # KAP açıklaması öncesi olağandışı işlem
    return alerts
```

### 5.3 services/core/algo_notification.py

```python
def generate_algo_notification(strategy):
    # SPK algoritmik trading bildirimi
    return notification
```

### 5.4 services/core/reporting.py

```python
def generate_daily_report(portfolio, trades, risk_metrics):
    # Günlük rapor
    return report
```

### 5.5 services/core/tax.py

```python
def calculate_tax(trade):
    # Holding süresi, vergi oranı, stopaj
    return {"profit", "tax_rate", "tax", "holding_days"}
```

**Mevcut:** `valuation/engine.py`'de DEFAULT_TAX_RATE var → detaylı YENİ

---

## AŞAMA 6: Bölüm 28 — Turkish Macro (7 modül)

### 6.1 services/macro/tcmb.py

```python
def compute_tcmb_features(tcmb_data):
    # policy_rate, real_rate, rate_surprise, policy_stance
    return features
```

**Mevcut:** `features/macro.py`'de compute_rate_features() var → detaylı YENİ

### 6.2 services/macro/inflation.py

```python
def compute_inflation_features(inflation_data):
    # cpi_yoy, ppi_yoy, core_cpi, ppi_cpi_spread, inflation_expectation
    return features
```

**Mevcut:** `features/macro.py`'de compute_inflation_features() var → detaylı YENİ

### 6.3 services/macro/fx.py

```python
def compute_fx_features(fx_data, stock_data):
    # usdtry, usdtry_change, usdtry_volatility, usdtry_bist_corr
    return features
```

### 6.4 services/macro/cds.py

```python
def compute_cds_features(cds_data):
    # cds_5y, cds_change, risk_level
    return features
```

### 6.5 services/macro/credit.py

```python
def compute_credit_features(credit_data):
    # credit_growth_yoy, credit_gdp_ratio
    return features
```

### 6.6 services/macro/current_account.py

```python
def compute_ca_features(ca_data):
    # current_account_balance, ca_trend, ca_improving
    return features
```

### 6.7 services/macro/calendar.py

```python
def get_macro_events(date):
    # TCMB PPK, TÜFE, cari açık, işsizlik, GSYH
    return events
```

**Bağımlılık:** `ingestion/providers/tcmb_provider.py` (veri çekme)

---

## AŞAMA 7: Bölüm 29 — FinRL/FinGPT (5 modül)

### 7.1 services/ml/finrl_bist.py

```python
class BISTTradingEnv(gym.Env):
    # State: [price, volume, rsi, macd, bb_pct, atr, usdtry, cds, portfolio_weight]
    # Action: [-1, +1]
    # Reward: return - λ×risk - γ×cost
```

### 7.2 services/ml/fingpt.py

```python
class FinGPTSentiment:
    def analyze(self, text):
        # Turkish financial text sentiment
        return {"sentiment", "score"}
```

### 7.3 services/ml/hybrid_model.py

```python
def hybrid_predict(rl_model, fingpt, news_data, market_data):
    # FinGPT sentiment + RL action
    return decision, sentiment_score, action
```

### 7.4 services/ml/rl_agent.py

```python
def train_rl_agent(env, total_timesteps=100000):
    # PPO agent eğitimi
    return model
```

### 7.5 services/ml/qlib_integration.py

```python
# Qlib ile BIST verisi entegrasyonu
```

**Bağımlılık:** gymnasium, stable-baselines3, transformers

---

## AŞAMA 8: Bölüm 30 — Factor Investing (7 modül)

### 8.1 services/factors/piotroski.py

```python
def calculate_f_score(financials):
    # 9 kriter (0-9 skor)
    return score
```

### 8.2 services/factors/beneish.py

```python
def calculate_m_score(financials):
    # 8 değişken, eşik: -1.78
    return m_score
```

### 8.3 services/factors/altman.py

```python
def calculate_z_score(financials):
    # 5 değişken, eşik: 1.81 / 2.99
    return z_score
```

### 8.4 services/factors/fama_french.py

```python
def calculate_factor_scores(stock, universe):
    # Value, Momentum, Quality, Size, Low Vol
    return scores
```

### 8.5 services/factors/bist_anomalies.py

```python
def calculate_bist_anomalies(stock, market_data):
    # Temettü, likidite, kur etkisi anomalileri
    return anomalies
```

### 8.6 services/factors/ranking.py

```python
def rank_stocks(universe, factors):
    # Çok faktörlü sıralama
    return ranked
```

### 8.7 services/factors/performance.py

```python
def track_factor_performance(factor_returns, benchmark_returns):
    # Alpha, Sharpe, drawdown
    return results
```

**Bağımlılık:** Yok

---

## AŞAMA 9: Bölüm 31 — Event Study (7 modül)

### 9.1 services/event_study/expected_return.py

```python
def calculate_expected_return(stock_returns, market_returns, estimation_window):
    # Market Model: α + β × R_mt
    return alpha, beta
```

### 9.2 services/event_study/abnormal_return.py

```python
def calculate_abnormal_return(stock_returns, market_returns, alpha, beta, event_window):
    # AR = R - E[R]
    return abnormal_returns
```

### 9.3 services/event_study/car.py

```python
def calculate_car(abnormal_returns, event_window):
    # CAR = Σ AR
    return car
```

### 9.4 services/event_study/statistical_test.py

```python
def test_significance(car, std_error):
    # t-test, p-value
    return {"t_statistic", "p_value", "significant"}
```

### 9.5 services/event_study/kap_event.py

```python
def analyze_kap_event(ticker, event_type, event_date):
    # KAP açıklaması etki analizi
    return {"car_5d", "ar_day0", "significant"}
```

### 9.6 services/event_study/macro_event.py

```python
def analyze_tcmb_event(rate_actual, rate_expected, market_returns):
    # TCMB faiz kararı etki analizi
    return {"surprise", "car_5d", "correlation"}
```

### 9.7 services/event_study/impact.py

```python
def calculate_event_impact(car, p_value, volume_change):
    # Etki skoru (0-100)
    return {"impact_score", "magnitude", "direction"}
```

**Bağımlılık:** statsmodels, scipy

---

## AŞAMA 10: Bölüm 32 — Options/VIOP (6 modül)

### 10.1 services/viop/options_pricing.py

```python
def black_scholes(S, K, T, r, sigma, option_type="call"):
    # Black-Scholes formülü
    return price
```

### 10.2 services/viop/greeks.py

```python
def calculate_greeks(S, K, T, r, sigma, option_type="call"):
    # Delta, Gamma, Theta, Vega, Rho
    return greeks
```

### 10.3 services/viop/strategies.py

```python
def create_covered_call(spot_price, call_strike, call_premium, shares):
def create_protective_put(spot_price, put_strike, put_premium, shares):
```

### 10.4 services/viop/parity.py

```python
def check_put_call_parity(call_price, put_price, spot_price, strike, r, T):
    return {"parity_holds", "deviation", "arbitrage_opportunity"}
```

### 10.5 services/viop/margin.py

```python
def calculate_span_margin(positions):
    # SPAN teminat hesaplama
    return total_margin
```

### 10.6 services/viop/hedging.py

```python
def hedge_portfolio(portfolio_value, beta, futures_price, multiplier=100):
    return {"hedge_ratio", "contracts_needed", "hedge_type"}
```

**Bağımlılık:** scipy, numpy

---

## Uygulama Sırası (Öncelik Sırasıyla)

```
GÜN 1-2:  Bölüm 23 (BIST kuralları — en kritik)
GÜN 3:    Bölüm 24 (Feature engineering — mevcut güncelleme)
GÜN 4-5:  Bölüm 25 (ML modelleri)
GÜN 6:    Bölüm 26 (Alternative data — framework)
GÜN 7:    Bölüm 27 (Regülasyon — SPK uyumluluk)
GÜN 8-9:  Bölüm 28 (Turkish macro — mevcut güncelleme)
GÜN 10:   Bölüm 29 (FinRL/FinGPT — framework)
GÜN 11:   Bölüm 30 (Factor investing)
GÜN 12:   Bölüm 31 (Event study)
GÜN 13:   Bölüm 32 (Options/VIOP)
GÜN 14:   Entegrasyon + test
```

---

## Test Dosyaları (49 yeni)

```
tests/test_core/
├── test_short_selling.py
├── test_fee_calculator.py
├── test_price_limits.py
├── test_halt_monitor.py
├── test_gross_settlement.py
├── test_viop_monitor.py
├── test_compliance.py
├── test_manipulation_detector.py
├── test_insider_detector.py
├── test_algo_notification.py
├── test_reporting.py
└── test_tax.py

tests/test_features/
├── test_technical_features.py
├── test_feature_selector.py
└── test_feature_store.py

tests/test_ml/
├── test_xgboost_model.py
├── test_lightgbm_model.py
├── test_lstm_model.py
├── test_transformer_model.py
├── test_model_comparator.py
├── test_ensemble.py
├── test_finrl_bist.py
├── test_fingpt.py
├── test_hybrid_model.py
└── test_rl_agent.py

tests/test_alternative/
├── test_web_scraping.py
├── test_social.py
├── test_jobs.py
├── test_credit_card.py
└── test_satellite.py

tests/test_macro/
├── test_tcmb.py
├── test_inflation.py
├── test_fx.py
├── test_cds.py
├── test_credit.py
├── test_current_account.py
└── test_calendar.py

tests/test_factors/
├── test_piotroski.py
├── test_beneish.py
├── test_altman.py
├── test_fama_french.py
├── test_bist_anomalies.py
├── test_ranking.py
└── test_performance.py

tests/test_event_study/
├── test_expected_return.py
├── test_abnormal_return.py
├── test_car.py
├── test_statistical_test.py
├── test_kap_event.py
├── test_macro_event.py
└── test_impact.py

tests/test_viop/
├── test_options_pricing.py
├── test_greeks.py
├── test_strategies.py
├── test_parity.py
├── test_margin.py
└── test_hedging.py
```

---

## Başarı Kriterleri

- [ ] 49 yeni modül implemente edilmiş
- [ ] 59 test dosyası yazıl
- [ ] Her modülün fonksiyonları çalışıyor
- [ ] Mevcut kodla entegrasyon sağlanmış (macro.py, store.py, sentiment.py)
- [ ] Bağımlılıklar kurulmuş (xgboost, lightgbm, torch, gymnasium, stable-baselines3, scipy, statsmodels)
- [ ] `run_system.py`'ye yeni modüller entegre edilmiş
