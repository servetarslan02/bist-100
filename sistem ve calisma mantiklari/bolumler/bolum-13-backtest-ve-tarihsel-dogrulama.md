# Bölüm 13 — Backtest ve Tarihsel Doğrulama

## Amaç

Sistemin ürettiği strateji ve sinyallerin geçmişte gerçekten işe yarayıp yaramadığını ölçmek.

**Kaynak:** QuestDB Backtesting Guide, Walk-forward with purge+embargo (Du 2026).

## Çalışma mantığı

```
Strateji → Geçmişteki Point-in-Time Veri → Hisse Seçimi → Pozisyon →
İşlem Maliyetleri → Portföy Getirisi → Benchmark → Risk Analizi → Sonuç
```

### Örnek: Walk-forward validation

```python
from services.backtest.enhanced_walk_forward import PurgeEmbargoWalkForward

engine = PurgeEmbargoWalkForward(train_days=252, test_days=63, step_days=21,
    purge_days=5, embargo_days=5)
result = engine.run(predictions, actuals, tickers, dates)
# total_folds: 8, avg_precision_at_5: 0.72, avg_ic: 0.15, deflated_sharpe: 1.45
```

## Temel prensip

Backtest'in amacı güzel bir geçmiş grafik üretmek değil, stratejinin farklı dönemlerde dayanıklı olup olmadığını kanıtlamaktır.
