# Bölüm 23 — BIST Piyasa Kuralları ve Mekanizmaları

## Amaç

Borsa İstanbul'un kendine özgü kurallarını, mekanizmalarını ve sınırlamalarını anlamak. Sistem bu kurallara uygun çalışmalı, aksi halde verilen emirler reddedilir veya beklenmedik sonuçlar doğar.

**Kaynak:** Borsa İstanbul Resmi (borsaistanbul.com), MDPI (2026) AI vs Efficient Markets — trading halts and circuit breakers.

---

## Kullanılacak sistemler

- Market Calendar (BIST seans saatleri)
- Circuit Breaker Monitor (devre kesici takibi)
- Short Selling Monitor (açığa satış kontrolü)
- Gross Settlement Monitor (brüt takas kontrolü)
- Halt Monitor (şirket durdurma takibi)
- Order Validation (emir doğrulama)
- Fee Calculator (BIST ücret hesaplama)
- VIOP Monitor (vadeli işlemler takibi)

---

## Çalışma mantığı

```
Emir → BIST kurallarını kontrol et → Devre kesici aktif mi? →
Açığa satış yasak mı? → Brüt takas var mı? → Fiyat limiti aşıldı mı? →
Şirket durdurulmuş mu? → Seans açık mı? → Emir gönder
```

---

## 1. BIST Seans Saatleri

### Seans yapısı:

```
09:40 - 09:55  Emir Toplama (açılış)
09:55 - 10:00  Eşleştirme (açılış)
10:00 - 13:00  Sürekli İşlem (1. seans)
13:00 - 14:00  Gün Ortası Tatil
14:00 - 17:30  Sürekli İşlem (2. seans)
17:30 - 17:40  Kapanış Emir Toplama
17:40 - 17:45  Kapanış Eşleştirme
```

### Örnek: Seas kontrolü

```python
# services/core/market_calendar.py
from services.core.market_calendar import market_calendar

info = market_calendar.get_info()
# is_trading_day: True
# is_market_open: True (11:00)
# session: MORNING (1. seans)
# next_close: 2026-08-16T13:00:00

# Tatil kontrolü
market_calendar.is_trading_day(date(2026, 1, 1))  # False (Yılbaşı)
market_calendar.is_trading_day(date(2026, 4, 23))  # False (Ulusal Egemenlik)
```

---

## 2. Devre Kesici (Circuit Breaker)

**Araştırma bulgusu:** MDPI (2026) — "Trading halts, circuit breakers, and other market rules create temporary price limits."

BIST'te iki tür devre kesici vardır:

### a) Hisse bazlı devre kesici:
```
Bir hisse fiyatı %10 veya %20 düştüğünde → otomatik durdurma
Durdurma süresi: 5-30 dakika
Tekrar açılma: yeni emir toplama periyodu
```

### b) Piyasa bazlı devre kesici:
```
BIST-100 endeksi %5 düştüğünde → tüm piyasa durdurulur
%7 düşüş → 2. devre kesici
%10 düşüş → piyasa kapatılabilir
```

### Örnek: Devre kesici kontrolü

```python
# services/core/circuit_breaker.py
from services.core.market_calendar import market_calendar

# Hisse bazlı kontrol
market_calendar.add_halt("THYAO", datetime(2026, 8, 16, 11, 0),
    datetime(2026, 8, 16, 11, 30), reason="CIRCUIT_BREAKER")

is_open = market_calendar.is_market_open(datetime(2026, 8, 16, 11, 15))
# is_open: False (devre kesici aktif)

# Endeks bazlı kontrol
market_calendar.add_halt(None, datetime(2026, 8, 16, 14, 0),
    datetime(2026, 8, 16, 14, 30), reason="MARKET_CIRCUIT_BREAKER")
```

### Devre kesici sonrası strateji:
```
Devre kesici açıldı → Fiyat stabilize oldu mu? → Volume normalleşti mi? →
Spread normal mi? → Emir göndermeye devam et
```

---

## 3. Açığa satış Kuralları

BIST'te açığa satış kuralları sıkıdır:

```
Açığa satış sadece BIST-30 hisselerinde yapılabilir
Açığa satış fiyatı son işlem fiyatından yüksek olmalı (uptick rule)
Brüt takasa giren hisselerde açığa satış yasak
SPK geçici yasak koyabilir
```

### Örnek: Açığa satış kontrolü

```python
# services/core/short_selling.py
def can_short_sell(ticker, current_price, last_trade_price):
    # BIST-30 kontrolü
    if ticker not in BIST30_STOCKS:
        return False, "Not in BIST-30"
    
    # Uptick rule
    if current_price <= last_trade_price:
        return False, "Uptick rule violation"
    
    # Brüt takas kontrolü
    if is_in_gross_settlement(ticker):
        return False, "Gross settlement active"
    
    return True, "OK"
```

---

## 4. Brüt Takas (Gross Settlement)

Brüt takas, bir hissenin alım-satımının aynı gün tamamlanmasını gerektiren kısıtlamadır:

```
Normal: T+2 ödeme
Brüt takas: Aynı gün ödeme (T+0)
Etkisi: Likidite düşer, spekülasyon azalır
```

### Örnek: Brüt takas kontrolü

```python
# services/core/gross_settlement.py
def check_gross_settlement(ticker):
    # Brüt takas listesi günlük güncellenir
    if ticker in gross_settlement_list:
        return {
            "is_gross": True,
            "effect": "Same-day settlement required",
            "impact": "Reduced liquidity, higher spread"
        }
    return {"is_gross": False}
```

---

## 5. Fiyat Limitleri

BIST'te her hisse için günlük fiyat limitleri vardır:

```
Normal limit: %10 yukarı/aşağı
Volatil hisseler: %5 veya %20
Sürekli işlem: Fiyat limitleri seans içinde güncellenir
```

### Örnek: Fiyat limiti kontrolü

```python
# services/core/price_limits.py
def check_price_limit(ticker, current_price, reference_price):
    change_pct = (current_price - reference_price) / reference_price * 100
    
    limit = get_price_limit(ticker)  # %10, %5, veya %20
    
    if abs(change_pct) >= limit:
        return {
            "limit_hit": True,
            "direction": "UP" if change_pct > 0 else "DOWN",
            "change_pct": change_pct,
            "limit": limit
        }
    return {"limit_hit": False, "change_pct": change_pct}
```

---

## 6. Şirket Durdurma (Halt)

KAP açıklaması veya olağanüstü durumlarda şirketin işlemi durdurulabilir:

```
KAP açıklaması öncesi → 30 dakika önceden durdurma
Bedelsiz sermaye artırım → 1 gün durdurma
Birleşme/devralma → birkaç gün durdurma
```

### Örnek: Halt kontrolü

```python
# services/core/halt_monitor.py
def check_halt(ticker):
    halt_info = get_halt_info(ticker)
    
    if halt_info["is_halted"]:
        return {
            "halted": True,
            "reason": halt_info["reason"],
            "expected_resume": halt_info["resume_time"],
            "action": "NO_TRADE"
        }
    return {"halted": False}
```

---

## 7. BIST Komisyon ve Ücret Yapısı

### Ücret bileşenleri:
```
Broker komisyonu: %0.02 - %0.05 (anlaşmaya göre)
BIST payı: %0.004
MKK payı: %0.001
BSMV: Komisyon üzerinden %5
Minimum komisyon: ₺1
```

### Örnek: Komisyon hesaplama

```python
# services/core/fee_calculator.py
def calculate_commission(amount, broker_rate=0.0003):
    broker_fee = amount * broker_rate
    bist_fee = amount * 0.00004
    mkk_fee = amount * 0.00001
    
    subtotal = broker_fee + bist_fee + mkk_fee
    bsmv = subtotal * 0.05
    
    total = max(subtotal + bsmv, 1.0)  # minimum ₺1
    
    return {
        "broker_fee": broker_fee,
        "bist_fee": bist_fee,
        "mkk_fee": mkk_fee,
        "bsmv": bsmv,
        "total": total
    }
```

---

## 8. VIOP (Vadeli İşlem ve Opsiyon Piyasası)

VIOP, BIST'in türev ürünler piyasasıdır:

```
Futures (vadeli işlem): Endeks, hisse, döviz, emtia
Options (opsiyon): Endeks ve hisse opsiyonları
Kaldıraç: 10:1'e kadar
Teminat: SPAN sistemi ile hesaplanır
```

### Örnek: VIOP pozisyon kontrolü

```python
# services/core/viop_monitor.py
def check_viop_margin(position):
    # SPAN bazlı teminat hesaplama
    span_margin = calculate_span_margin(position)
    
    # Mevcut teminat yeterli mi?
    if account_margin < span_margin * 1.2:  # %20 tampon
        return {
            "margin_call": True,
            "required": span_margin * 1.2,
            "available": account_margin,
            "action": "REDUCE_POSITION"
        }
    return {"margin_call": False}
```

---

## 9. Kotasyon ve Piyasa Yapıcı

BIST'te piyasa yapıcılar belirli hisselerde likidite sağlar:

```
Piyasa yapıcı: Sürekli alım-satım kotasyonu verir
Spread garantisi: Maksimum spread belirlenir
Hacim garantisi: Minimum hacim belirlenir
```

---

## 10. SPK Regülasyonları

### Kritik kurallar:
```
Bilgi suistimali: İçerden bilgi ticareti yasak
Piyasa dolandırıcılığı: Yanıltıcı emir yasak
Manipülasyon: Fiyat manipülasyonu yasak
Bildirim yükümlülüğü: %5 üzeri alımlar bildirilmeli
Algoritmik trading: SPK'ya bildirim zorunlu
```

### Örnek: SPK uyumluluk kontrolü

```python
# services/core/compliance.py
def check_spk_compliance(action, ticker, amount, portfolio):
    # Bildirim yükümlülüğü kontrolü
    if action == "BUY":
        new_pct = (portfolio.holding(ticker) + amount) / portfolio.total_shares(ticker) * 100
        if new_pct >= 5.0:
            return {
                "notification_required": True,
                "authority": "SPK",
                "deadline": "2 business days",
                "action": "NOTIFY_BEFORE_TRADING"
            }
    
    # Manipülasyon kontrolü
    if is_spoofing_pattern(action, ticker, portfolio):
        return {
            "violation": "POTENTIAL_MANIPULATION",
            "action": "BLOCK"
        }
    
    return {"compliant": True}
```

---

## Çıktı

```
Trading session:      MORNING
Circuit breaker:      INACTIVE
Short selling:        ALLOWED (THYAO, BIST-30)
Gross settlement:     INACTIVE
Price limit:          10% (305.25 - 335.78)
Halt status:          NOT_HALTED
Commission:           ₺3.68 (0.03%)
VIOP margin:          OK
SPK compliance:       COMPLIANT
```

---

## Temel prensip

BIST'in kuralları ABD veya Avrupa piyasalarından farklıdır. Devre kesici eşiği, açığa satış kısıtlamaları, brüt takas ve komisyon yapısı BIST'e özgüdür. **Bu kuralları bilmeyen sistem, emir reddi, beklenmedik durdurma veya SPK cezası ile karşılaşabilir.**

> Kaynak: Borsa İstanbul Resmi (borsaistanbul.com), MDPI (2026) AI vs Efficient Markets
