# core/audit_log

**Dosya:** `services/core/audit_log.py`
**Satır:** 277

## Açıklama

ALPHA BIST — Audit Log v1.0

Immutable audit trail:
- Decision lineage
- Risk decisions
- Order/fill tracking
- State changes
- Config changes

FAZ 14: Audit Log

## Sınıflar (2)

- `AuditEntry`
- `AuditLog`

## Fonksiyonlar (13)

- `__init__()`
- `log()`
- `log_decision()`
- `log_risk_check()`
- `log_order()`
- `log_fill()`
- `log_state_change()`
- `log_config_change()`
- `get_entity_history()`
- `get_decision_lineage()`
- `get_recent()`
- `get_stats()`
- `_generate_id()`

