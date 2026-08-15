# Bölüm 21 — Hata Yönetimi ve Dayanıklılık

## Amaç

Bir veri kaynağı, servis, model veya agent hata verdiğinde tüm yatırım sisteminin bozulmasını veya yanlış karar vermesini engellemek.

---

## Kullanılacak sistemler

- Error Handling
- Retry / Backoff
- Timeout
- Circuit Breaker
- Fallback
- Idempotency
- Distributed Lock
- Failure Detection
- Health Check
- Recovery
- Dead Letter Queue
- Event Replay

---

## Çalışma mantığı

```
İşlem
    ↓
Hata oluştu mu?
├─ Hayır → Devam
│
└─ Evet
    ↓
Hata sınıflandır
    ↓
Retry mümkün mü?
├─ Evet → Retry
│
└─ Hayır
    ↓
Fallback
    ↓
Güvenilir mi?
├─ Evet → Devam
└─ Hayır → NO_TRADE / BLOCK
```

---

## Örneğin veri servisi çökerse

Sistem doğrudan:

> "Veri yok ama eski veriyle devam edelim."

demeyecek.

Önce verinin ne kadar eski olduğunu ve karar için hâlâ kullanılabilir olup olmadığını kontrol edecek.

Kritik veri güncel değilse:

> **NO_TRADE**

üretebilir.

---

## Retry

Geçici API hatalarında:

```
1. deneme → bekle → 2. deneme → bekle → 3. deneme
```

gibi kontrollü retry uygulanır.

**Sonsuz retry yapılmaz.**

---

## Circuit Breaker

Bir servis sürekli hata veriyorsa sistem onu sürekli çağırmaz.

```
Healthy
    ↓
Errors ↑
    ↓
OPEN
    ↓
Servis çağrıları durur
    ↓
Recovery Check
    ↓
Healthy → CLOSE
```

---

## Kritik prensip

**Hata durumunda sistem tahmin üretmek yerine güvenli şekilde durabilmeli.**

Örneğin:

- Monte Carlo çalışmıyor
- Risk Engine çalışmıyor
- Güncel fiyat yok

ise sistem:

> **BUY**

üretmemeli.

Sonuç:

> **NO_TRADE — gerekli doğrulamalar tamamlanamadı.**

---

## Recovery

Sistem kaldığı yeri hatırlayabilmeli.

- Task State
- Event Checkpoint
- Last Successful Step

saklanır ve servis geri geldiğinde işlem baştan başlamak zorunda kalmaz.

---

## Temel prensip

Hata olduğunda sistem yanlış karar vermek yerine **kontrollü olarak yavaşlar, fallback kullanır veya işlemi durdurur.**
