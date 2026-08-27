# Bölüm 27 — Regülasyon Uyumu (SPK)

## Amaç

Sistemin SPK (Sermaye Piyasası Kurulu) kurallarına uygun çalışmasını sağlamak. İhlal para cezası, lisans iptali veya hukuki sonuçlar doğurabilir.

**Kaynak:** Norton Rose Fulbright (2024) AI Regulation Guide — Capital Markets Board (SPK) for capital markets.

---

## Kullanılacak sistemler

- Compliance Checker
- Position Limit Monitor
- Reporting Engine
- Notification System
- Audit Trail
- KYC/AML Checker
- Insider Trading Detector
- Manipulation Detector

---

## Çalışma mantığı

```
İşlem → SPK kurallarını kontrol et → Bildirim yükümlülüğü →
Pozisyon limiti → Manipülasyon kontrolü → İçeriden bilgi kontrolü →
Raporlama → Audit log
```

---

## 1. Bildirim Yükümlülükleri

### %5 kuralı:
```
Bir şirketin paylarının %5'ini aşan alım → SPK'ya bildirim
Her %1 artış için ayrı bildirim
Bildirim: 2 iş günü içinde
```

### Örnek: Bildirim kontrolü

```python
# services/core/compliance.py
def check_notification_requirement(action, ticker, quantity, portfolio):
    total_shares = get_total_shares(ticker)
    current_pct = portfolio.holding(ticker) / total_shares * 100

    if action == "BUY":
        new_pct = (portfolio.holding(ticker) + quantity) / total_shares * 100

        # %5 eşiği aşıldı mı?
        if current_pct < 5.0 and new_pct >= 5.0:
            return {
                "notification_required": True,
                "authority": "SPK",
                "deadline": "2 business days",
                "form": "Özel Durum Açıklaması",
                "action": "NOTIFY_BEFORE_TRADING",
            }

        # Her %1 artış
        if new_pct >= 5.0 and int(new_pct) > int(current_pct):
            return {
                "notification_required": True,
                "authority": "SPK",
                "deadline": "2 business days",
                "form": "Pay Alım Bildirimi",
            }

    return {"notification_required": False}
```

---

## 2. Manipülasyon Tespiti

### SPK'nın yasakladığı manipülasyon türleri:
```
1. Wash Trading: Kendi kendine işlem yapma
2. Spoofing: Sahte emir verip iptal etme
3. Layering: Birden fazla sahte emir katmanı
4. Cornering: Piyasayı köşeye sıkıştırma
5. Painting the Tape: Hacmi şişirme
6. Pump and Dump: Fiyatı şişirip satma
```

### Örnek: Manipülasyon tespiti

```python
# services/core/manipulation_detector.py
def detect_manipulation(trade_history, order_history):
    alerts = []

    # Wash trading kontrolü
    for trade in trade_history:
        if trade.buyer == trade.seller:
            alerts.append({"type": "WASH_TRADING", "severity": "HIGH", "details": trade})

    # Spoofing kontrolü
    cancelled_orders = [o for o in order_history if o.status == "CANCELLED"]
    cancel_rate = len(cancelled_orders) / len(order_history) if order_history else 0

    if cancel_rate > 0.8:  # %80'den fazla iptal
        alerts.append({"type": "POTENTIAL_SPOOFING", "severity": "MEDIUM", "cancel_rate": cancel_rate})

    # Volume manipulation
    avg_volume = np.mean([t.volume for t in trade_history[-20:]])
    recent_volume = np.mean([t.volume for t in trade_history[-3:]])

    if recent_volume > avg_volume * 5:  # 5x ortalama hacim
        alerts.append({"type": "VOLUME_ANOMALY", "severity": "MEDIUM", "volume_ratio": recent_volume / avg_volume})

    return alerts
```

---

## 3. İçeriden Bilgi Ticareti (Insider Trading)

### Tanım:
```
Kamuya açıklanmamış bilgiyi kullanarak işlem yapmak
Bilgiyi başkasına aktarmak
Yakın çevreye bilgi sızdırmak
```

### Tespit kriterleri:
```
- KAP açıklamasından hemen önce büyük alım
- Bilinen insider'ların aile üyeleriyle korelasyon
- Olağandışı işlem kalıpları
```

### Örnek: Insider trading tespiti

```python
# services/core/insider_detector.py
def detect_insider_pattern(trades, kap_events):
    alerts = []

    for event in kap_events:
        # KAP açıklamasından 3 gün önce
        pre_event_trades = [t for t in trades if event.date - timedelta(days=3) <= t.date < event.date]

        for trade in pre_event_trades:
            if trade.volume > trade.avg_volume * 3:  # Olağandışı hacim
                alerts.append(
                    {
                        "type": "POTENTIAL_INSIDER_TRADING",
                        "severity": "CRITICAL",
                        "trade": trade,
                        "event": event,
                        "days_before": (event.date - trade.date).days,
                    }
                )

    return alerts
```

---

## 4. Algoritmik Trading Bildirimi

SPK, algoritmik trading yapanların bildirimde bulunmasını ister:

```
Algoritmik trading: Otomatik emir oluşturma
Bildirim: SPK'ya yazılı bildirim
İçerik: Strateji türü, risk kontrolleri, test sonuçları
```

### Örnek: Bildirim şablonu

```python
# services/core/algo_notification.py
def generate_algo_notification(strategy):
    return {
        "firm_name": "BIST-100 Trading System",
        "strategy_type": strategy.type,  # "MOMENTUM", "MEAN_REVERSION", etc.
        "risk_controls": [
            "Position limit: 10% per stock",
            "Daily loss limit: 2%",
            "Circuit breaker: Auto-pause on anomalies",
        ],
        "testing": {
            "backtest_period": "2020-2026",
            "paper_trading_period": "3 months",
            "max_drawdown": "-18%",
        },
        "emergency_contact": "...",
        "submission_date": datetime.now().isoformat(),
    }
```

---

## 5. Raporlama Yükümlülükleri

### Günlük:
```
- İşlem logları
- Pozisyon değişiklikleri
- Risk limitleri
```

### Aylık:
```
- Portföy performans raporu
- İşlem hacmi raporu
- Risk raporu
```

### Yıllık:
```
- Denetim raporu
- Uyum raporu
- Vergi raporu
```

### Örnek: Rapor oluşturma

```python
# services/core/reporting.py
def generate_daily_report(portfolio, trades, risk_metrics):
    return {
        "date": datetime.now().date(),
        "portfolio_value": portfolio.total_value,
        "daily_return": portfolio.daily_return,
        "positions": portfolio.positions,
        "trades_executed": len(trades),
        "risk_metrics": {
            "var_95": risk_metrics["var_95"],
            "max_drawdown": risk_metrics["max_drawdown"],
            "concentration": risk_metrics["concentration"],
        },
        "compliance_status": "COMPLIANT",
    }
```

---

## 6. KYC/AML (Know Your Customer / Anti-Money Laundering)

### Yükümlülükler:
```
- Müşteri kimlik doğrulaması
- Şüpheli işlem bildirimi
- MASAK'a raporlama
- İşlem limitleri
```

---

## 7. Vergi Yükümlülükleri

### BIST'te vergi:
```
- Hisse satış kârı: %0 (bireysel, 2 yıldan fazla tutulan)
- Hisse satış kârı: %10-15 (kısa vadeli)
- Temettü: %10 stopaj
- VIOP: %0-10
```

### Örnek: Vergi hesaplama

```python
# services/core/tax.py
def calculate_tax(trade):
    if trade.type == "STOCK_SALE":
        holding_days = (trade.sell_date - trade.buy_date).days

        if holding_days > 730:  # 2 yıldan fazla
            tax_rate = 0.0
        else:
            tax_rate = 0.10  # %10

        profit = (trade.sell_price - trade.buy_price) * trade.quantity
        tax = max(profit * tax_rate, 0)

        return {"profit": profit, "tax_rate": tax_rate, "tax": tax, "holding_days": holding_days}
```

---

## Çıktı

```
SPK Compliance:          COMPLIANT
Notifications pending:   0
Manipulation alerts:     0
Insider alerts:          0
Algo notification:       SUBMITTED
Daily report:            GENERATED
Audit trail:             ACTIVE
```

---

## Temel prensip

SPK kuralları ihlali para cezası, lisans iptali veya hukuki sonuçlar doğurabilir. **Sistem otomatik olarak bildirim yükümlülüklerini takip etmeli, manipülasyon kalıplarını tespit etmeli ve tüm işlemleri audit log'da kaydetmelidir.**

> Kaynak: Norton Rose Fulbright (2024) AI Regulation Guide, SPK Mevzuat
