# Bölüm 13 — Backtest ve Tarihsel Doğrulama

## Amaç

Sistemin ürettiği strateji ve sinyallerin geçmişte gerçekten işe yarayıp yaramadığını ölçmek.

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
Strateji / Karar
    ↓
Geçmişteki Point-in-Time Veri
    ↓
Hisse Seçimi
    ↓
Pozisyon
    ↓
İşlem Maliyetleri
    ↓
Portföy Getirisi
    ↓
Benchmark Karşılaştırması
    ↓
Risk Analizi
    ↓
Sonuç
```

---

## En önemli prensip

**Backtest sırasında sistem geleceği bilmeyecek.**

Örneğin 2022'de karar veriyorsa:

- 2023 bilançosunu kullanamaz.
- Sonradan düzeltilmiş veriyi kullanamaz.
- O tarihte henüz yayınlanmamış KAP'ı göremez.
- Sonradan borsadan silinen şirketleri yok sayamaz.

---

## İşlem gerçekçi olacak

Sadece:

> 100 TL'den aldım, 120 TL'den sattım = %20

şeklinde hesaplanmayacak.

Şunlar hesaba katılacak:

- Spread
- Slippage
- Commission
- Liquidity
- Position Size
- Partial Fill

---

## Walk-Forward

Model tüm geçmişi görüp kendisini geçmişe göre optimize etmeyecek.

```
Train → Test → Yeni dönem → Train → Test → ...
```

şeklinde ilerleyerek gerçek hayata daha yakın test yapılacak.

---

## Ölçülecek sonuçlar

- Toplam getiri
- Benchmark'a göre getiri
- CAGR
- Sharpe
- Sortino
- Maximum Drawdown
- Win Rate
- Profit Factor
- VaR/CVaR
- İşlem sayısı
- Ortalama işlem
- En kötü dönem
- Regime bazlı performans

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

Ancak yüksek geçmiş performans tek başına başarılı strateji anlamına gelmez. **Overfitting** ve **veri sızıntısı** ayrıca kontrol edilir.

---


---

**Kaynak:** Walk-forward with purge+embargo (Du 2026). Precision@K, IC, Deflated Sharpe Ratio for overfitting detection.


### Örnek: Walk-forward validation

```python
# services/backtest/enhanced_walk_forward.py
from services.backtest.enhanced_walk_forward import PurgeEmbargoWalkForward
import numpy as np

engine = PurgeEmbargoWalkForward(
    train_days=252, test_days=63, step_days=21,
    purge_days=5, embargo_days=5,
)

# predictions: her gün için tüm hisselerin tahmin skoru
# actuals: her gün için tüm hisselerin gerçek getirisi
result = engine.run(predictions, actuals, tickers, dates)

# result.total_folds = 8
# result.avg_precision_at_5 = 0.72
# result.avg_ic = 0.15
# result.avg_sharpe = 1.62
# result.deflated_sharpe = 1.45
# result.stability_score = 0.82
```

## Temel prensip

Backtest'in amacı güzel bir geçmiş grafik üretmek değil, **stratejinin farklı dönemlerde ve farklı piyasa koşullarında gerçekten dayanıklı olup olmadığını kanıtlamaktır**.
