# Bölüm 14 — Paper Trading ve Execution Simulation

## Amaç

Backtest'ten geçen sistemi gerçek para kullanmadan, gerçek piyasa akışına yakın koşullarda çalıştırmak.

---

## Kullanılacak sistemler

- Paper Trading Engine
- Execution Simulator
- Order Management
- Liquidity Engine
- Spread Model
- Slippage Model
- Partial Fill
- Transaction Cost
- Portfolio Ledger
- P&L Tracking

---

## Çalışma mantığı

```
Gerçek Piyasa Verisi
    ↓
Karar / Sinyal
    ↓
Risk Gate
    ↓
Emir Simülasyonu
    ↓
Spread + Slippage + Likidite
    ↓
Fill / Partial Fill
    ↓
Sanal Portföy
    ↓
P&L + Risk
    ↓
Gerçek Sonuçla Karşılaştırma
```

---

## Nasıl kullanılacak?

Örneğin sistem:

> BUY — Hisse X — %4 pozisyon

dedi.

Paper Trading sistemi gerçek emir göndermez.

Piyasa koşullarına bakarak:

```
Emir:       1.000 lot
Spread:     ...
Slippage:   ...
Likidite:   ...
Fill:       850 lot
Bekleyen:   150 lot
```

gibi gerçekçi bir işlem sonucu üretir.

---

## Neden gerekli?

Backtest'te iyi görünen sistem gerçek piyasada:

- slippage
- spread
- düşük likidite
- emir gerçekleşmemesi
- ani fiyat hareketleri

nedeniyle kötü çalışabilir.

Paper trading bunu production öncesinde ortaya çıkarır.

---

## Ölçülecekler

- Signal Accuracy
- Execution Quality
- Slippage
- Fill Rate
- Realized P&L
- Drawdown Risk
- Portfolio Impact

---

## Kritik bağlantı

```
Backtest → Paper Trading → Gerçek piyasa sonuçları → Prediction / Execution karşılaştırması → Model iyileştirme
```

Sistem yeterli süre paper trading'de başarılı olmadan gerçek para ile işlem katmanına geçmemeli.

---

## Temel prensip

Backtest **"geçmişte çalıştı mı?"**, paper trading ise **"bugünün gerçek piyasa koşullarında gerçekten çalışıyor mu?"** sorusunu cevaplar.
