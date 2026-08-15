# Bölüm 19 — Güvenlik, Yetkilendirme ve Yönetişim

## Amaç

Sistemin ve AI agent'larının yanlış, yetkisiz veya tehlikeli işlem yapmasını engellemek.

**Kaynak:** arXiv (2026) Secure Systems of Interacting AI Agents, arXiv (2026) Claude Code Design Space — human decision authority, safety, security, privacy.

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
Kullanıcı/Agent → Kimlik doğrulama → Yetki kontrolü →
Risk/Güvenlik kontrolü → İşleme izin → İşlem → Audit Log
```

---

## 1. Agent Yetkileri

**Araştırma bulgusu:** arXiv (2026) — "Safety-critical systems without human verification or cryptographic authorization. Governance vulnerabilities exemplify cross-cutting concerns."

### Örnek: RBAC

```python
# services/core/security.py
from services.core.security import authz_service, Role, Permission

authz_service.check_permission(
    User(user_id="1", username="analyst", role=Role.ANALYST),
    Permission.RUN_BACKTEST)  # True

authz_service.check_permission(
    User(user_id="1", username="analyst", role=Role.ANALYST),
    Permission.LIVE_EXECUTION)  # False
```

---

## 2. No-Trade Gate

```
Karar → Risk Gate → Position Limit → Liquidity Check → Security Check → ALLOW / BLOCK
```

Koşullar (herhangi biri → NO_TRADE):
- Risk Engine çalışmıyor
- Veri güvenilir değil
- Portföy tutarsız
- Model geçersiz

---

## 3. Safety Governance

Yapamayacakları:
- AI risk bypass edemez
- AI doğrudan portföy değiştiremez
- AI audit geçmişini silemez
- Agent kendi permissions'unu değiştiremez

---

## 4. System State Machine

```
STARTING → INITIALIZING → READY → DEGRADED → RECOVERY → READY
                                       ↓
                                    FAILED
```

---

## Temel prensip

**AI hiçbir zaman sınırsız yetkiye sahip olmayacak.**

> "Human decision authority, safety, security, and privacy." — arXiv (2026)
