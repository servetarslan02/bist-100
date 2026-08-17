# Bölüm 13 — Backtest ve Tarihsel Doğrulama

## Amaç

Sistemin ürettiği strateji ve sinyallerin geçmişte gerçekten işe yarayıp yaramadığını ölçmek.

**Kaynak:** arXiv AlgoXpert (2026) IS-WFA-OOS Framework, MDPI (2026) Regime-Aware LightGBM Walk-Forward, TensorBlue Deflated Sharpe.

---

## Kullanılacak sistemler

- Backtest Engine
- Walk-Forward Analysis
- Historical Simulation
- Transaction Cost Model
- Slippage Model
- Benchmark Engine
- Performance Attribution
- Look-Ahead Bias Protection
- Survivorship Bias Protection

---

## Çalışma mantığı

```
Strateji → Point-in-Time Veri → Hisse Seçimi → Pozisyon →
İşlem Maliyetleri → Portföy Getirisi → Benchmark → Risk Analizi → Sonuç
```

---

## 1. Walk-Forward Validation

**Araştırma bulgusu:** arXiv AlgoXpert (2026) — "Rigorous IS-WFA-OOS framework with purged validation, parameter stability, backtest overfitting detection."

**MDPI (2026):** "Walk-Forward Validation with Purge and Embargo. Deflated Sharpe Ratio for multiple testing."

### Örnek: Walk-forward with purge+embargo

```python
# services/backtest/enhanced_walk_forward.py
from services.backtest.enhanced_walk_forward import PurgeEmbargoWalkForward

engine = PurgeEmbargoWalkForward(
    train_days=252, test_days=63, step_days=21,
    purge_days=5, embargo_days=5,  # Data leakage koruması
)

result = engine.run(predictions, actuals, tickers, dates)
# total_folds: 8
# avg_precision_at_5: 0.72
# avg_ic: 0.15
# deflated_sharpe: 1.45
# stability_score: 0.82
```

**Purge gap:** Train sonundan test başına kadar 5 gün boşluk — gelecek veri sızmasını engeller.
**Embargo gap:** Test sonundan bir sonraki train başına kadar 5 gün boşluk.

---

## 2. Deflated Sharpe Ratio

**Araştırma bulgusu:** MDPI (2026) — "Deflated Sharpe Ratio for multiple testing correction."

Backtest sayısı arttıkça Sharpe'ın güvenilirliği düşer.

### Örnek: Deflated Sharpe

```python
sharpes = [2.0, 2.1, 1.9, 2.2, 2.0]
deflated = engine._deflated_sharpe(sharpes, n_trials=5)
# deflated = yüksek (az deneme, güvenilir)

sharpes_many = [2.0] * 100
deflated_many = engine._deflated_sharpe(sharpes_many, n_trials=1000)
# deflated = düşük (çok deneme, overfitting riski)
```

---

## 3. Değerlendirme Metrikleri

```
Toplam getiri | CAGR | Sharpe | Sortino | Max DD | Win Rate |
Profit Factor | VaR/CVaR | Precision@K | IC | Turnover
```

---

## 4. Bias Koruması

- **Look-ahead bias:** PIT store ile engellenir
- **Survivorship bias:** Delisted şirketler tarihte tutulur
- **Data snooping:** Deflated Sharpe ile tespit edilir

---

## Çıktı

```
Strategy Return:   +185%
BIST100:           +112%
Alpha:             +73%
Sharpe:            1.62
Max Drawdown:      -18%
Win Rate:          %61
Profit Factor:     1.84
Robustness:        GOOD
```

---

## Temel prensip

> "Rigorous IS-WFA-OOS framework with purged validation and parameter stability." — arXiv AlgoXpert (2026)

Backtest'in amacı güzel bir geçmiş grafik üretmek değil, **stratejinin farklı dönemlerde dayanıklı olup olmadığını kanıtlamaktır**.

## 5. BIST'e Gerçekçi Backtest

### BIST komisyon yapısı:
```python
def bist_transaction_cost(amount, broker_rate=0.0003):
    broker_fee = amount * broker_rate
    bist_fee = amount * 0.00004
    mkk_fee = amount * 0.00001
    bsmv = (broker_fee + bist_fee + mkk_fee) * 0.05
    
    return max(broker_fee + bist_fee + mkk_fee + bsmv, 1.0)
```

### BIST slippage modeli:
```python
def bist_slippage(order_size, avg_daily_volume, volatility, spread_pct):
    base_slippage = spread_pct / 2
    volume_impact = (order_size / avg_daily_volume) * volatility * 10
    
    return base_slippage + volume_impact
```

### BIST devre kesici etkisi:
```python
def account_for_circuit_breaker(trades, halts):
    adjusted_trades = []
    
    for trade in trades:
        if any(halt["start"] <= trade["time"] <= halt["end"] for halt in halts):
            trade["executed"] = False
            trade["reason"] = "Circuit breaker active"
        
        adjusted_trades.append(trade)
    
    return adjusted_trades
```

---

## BIST Komisyon Modeli Entegrasyonu

**Kaynak:** Bölüm 23 — BIST Piyasa Kuralları

Bu bölümün backtest motoru, Bölüm 23'teki BIST-specific modelleri kullanır:

| Model | Bölüm 23 Motoru | Bölüm 13 Kullanımı |
|-------|----------------|-------------------|
| Komisyon | `core/fee_calculator.py` | Gerçekçi işlem maliyeti |
| Slippage | `core/price_limits.py` | Fiyat limiti etkisi |
| Devre kesici | `core/halt_monitor.py` | Durdurma etkisi |
| Açığa satış | `core/short_selling.py` | Short satış kısıtlaması |

### Örnek: BIST komisyon ile backtest

```python
from services.core.fee_calculator import calculate_commission

# Backtest'te gerçekçi komisyon
commission = calculate_commission(amount=305250, broker_rate=0.0003)
# broker_fee: 91.58
# bist_fee: 12.21
# mkk_fee: 3.05
# bsmv: 5.34
# total: 112.18

# Backtest'e uygula
capital -= (cost + commission["total"])
```
