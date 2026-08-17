# core/security

**Dosya:** `services/core/security.py`
**Satır:** 260

## Açıklama

ALPHA BIST — Security & Governance v1.0

- Authentication (session/token)
- Authorization (RBAC)
- API Security
- Secret Redaction
- Safety Governance
- System State Machine

## Sınıflar (8)

- `Role`
- `Permission`
- `User`
- `AuthenticationService`
- `AuthorizationService`
- `SecretRedaction`
- `SystemStateMachine`
- `SafetyGovernance`

## Fonksiyonlar (16)

- `__init__()`
- `create_user()`
- `authenticate()`
- `validate_token()`
- `_hash_password()`
- `_verify_password()`
- `_find_user()`
- `check_permission()`
- `require_permission()`
- `redact()`
- `__init__()`
- `state()`
- `transition()`
- `set_substate()`
- `get_health()`
- `validate_ai_action()`

