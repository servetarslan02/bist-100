# intelligence/world_state

**Dosya:** `services/intelligence/world_state.py`
**Satır:** 294

## Açıklama

ALPHA BIST - Dynamic World State v1.1

World State = zaman içinde değişen latent state.
Event → World State t0 → Event → World State t1 → Impact Propagation → BIST State t1

## Sınıflar (2)

- `WorldState`
- `WorldStateManager`

## Fonksiyonlar (10)

- `to_vector()`
- `from_vector()`
- `to_dict()`
- `apply_decay()`
- `__init__()`
- `current_state()`
- `update_from_event()`
- `update_from_macro()`
- `get_state_vector()`
- `get_state_dict()`

