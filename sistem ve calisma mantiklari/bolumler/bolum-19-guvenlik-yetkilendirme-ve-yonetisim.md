# Bölüm 19 — Güvenlik, Yetkilendirme ve Yönetişim

## Amaç

Sistemin ve AI agent'larının yanlış, yetkisiz veya tehlikeli işlem yapmasını engellemek.

**Kaynak:** RBAC, No-Trade Gate, Secret Management, Audit.

## Çalışma mantığı

```
Kullanıcı/Agent → Kimlik doğrulama → Yetki kontrolü →
Risk/Güvenlik kontrolü → İşleme izin → İşlem → Audit Log
```

### Örnek: Authorization

```python
from services.core.security import authz_service, Role, Permission

user = User(user_id="1", username="analyst", role=Role.ANALYST)
authz_service.check_permission(user, Permission.RUN_BACKTEST)  # True
authz_service.check_permission(user, Permission.LIVE_EXECUTION)  # False
```

## Temel prensip

AI hiçbir zaman sınırsız yetkiye sahip olmayacak.
