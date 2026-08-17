# core/monitoring_security

**Dosya:** `services/core/monitoring_security.py`
**Satır:** 369

## Açıklama

ALPHA BIST — Monitoring Security

Authentication ve authorization for monitoring endpoints.

Endpoint koruma seviyeleri:
- PUBLIC: /health, /health/detailed (kimlik doğrulama yok)
- METRICS: /metrics (Bearer token)
- ADMIN: /admin/* (Bearer token + admin role)

Token yönetimi:
- Monitoring token'ları environment variable'dan yüklenir
- Default token production'da değiştirilmeli

## Sınıflar (8)

- `AuthConfig`
- `MonitoringAuth`
- `AuthProvider`
- `AuthResult`
- `StaticTokenProvider`
- `JWTProvider`
- `OAuthProvider`
- `AuthManager`

## Fonksiyonlar (15)

- `__init__()`
- `verify_metrics_token()`
- `verify_admin_token()`
- `check_rate_limit()`
- `record_failed_attempt()`
- `get_auth_status()`
- `_constant_time_compare()`
- `name()`
- `has_role()`
- `__init__()`
- `__init__()`
- `__init__()`
- `__init__()`
- `add_provider()`
- `get_providers()`

