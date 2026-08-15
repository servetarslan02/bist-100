# Bölüm 19 — Güvenlik, Yetkilendirme ve Yönetişim

## Amaç

Sistemin ve AI agent'larının yanlış, yetkisiz veya tehlikeli işlem yapmasını engellemek.

---

## Kullanılacak sistemler

- Authentication
- Authorization / RBAC
- Agent Permission System
- Risk Limits
- No-Trade Gate
- Secret Management
- Audit System
- Security Monitoring
- Governance Rules

---

## Çalışma mantığı

```
Kullanıcı / Agent
    ↓
Kimlik doğrulama
    ↓
Yetki kontrolü
    ↓
Risk / Güvenlik kontrolü
    ↓
İşleme izin
    ↓
İşlem
    ↓
Audit Log
```

---

## Agent yetkileri

Her agent'ın ayrı yetkisi olacak.

Örneğin:

- Research Agent → Veri okuyabilir
- Risk Agent → Risk hesaplayabilir
- Portfolio Agent → Portföy simülasyonu yapabilir
- Execution Agent → Sadece izin verilen emirleri oluşturabilir
- Audit Agent → Kontrol edebilir

**Bir agent kendi yetkisini yükseltemez.**

---

## Risk Gate

Bir karar üretilse bile doğrudan uygulanmaz.

```
Karar
    ↓
Risk Gate
    ↓
Position Limit
    ↓
Liquidity Check
    ↓
Security Check
    ↓
ALLOW / BLOCK
```

Örneğin:

- Risk limiti aşıldı → BLOCK
- Veri güvenilir değil → BLOCK
- Risk Engine çalışmıyor → NO_TRADE

---

## Secret Management

API key, şifre ve tokenlar:

- kod içine yazılmaz
- loglara düşmez
- agent'a gereksiz yere verilmez
- yetkisi sınırlı şekilde kullanılır

---

## Audit

Kritik işlemlerde:

- Kim?
- Ne yaptı?
- Ne zaman?
- Hangi veri?
- Hangi model?
- Hangi karar?
- Hangi risk kontrolü?
- Sonuç ne?

kaydedilir.

---


---

**Kaynak:** Security — RBAC. No-trade gate. Secret redaction. System state machine.


### Örnek: Authorization check

```python
# services/core/security.py
from services.core.security import authz_service, Role, Permission

user = User(user_id="1", username="analyst", role=Role.ANALYST)

authz_service.check_permission(user, Permission.RUN_BACKTEST)  # True
authz_service.check_permission(user, Permission.LIVE_EXECUTION)  # False
```

## Temel prensip

**AI hiçbir zaman sınırsız yetkiye sahip olmayacak.**

Sistem:

> "AI ne yapmak istiyor?"

sorusundan önce:

> "Bunu yapmaya yetkisi var mı ve güvenli mi?"

sorusunu kontrol edecek.

**Bu katman sistemin diğer bütün bölümlerinin üzerinde çalışan güvenlik bariyeridir.**
