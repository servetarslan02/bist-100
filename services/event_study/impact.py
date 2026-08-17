"""ALPHA BIST — Event Impact Score."""
from typing import Dict, Any

def calculate_event_impact(car: float, p_value: float, volume_change: float = 0) -> Dict[str, Any]:
    """Etki skoru (0-100)."""
    significance_score = min(abs(car) * 100, 50)  # Max 50
    volume_score = min(abs(volume_change) * 10, 30)  # Max 30
    stat_score = 20 if p_value < 0.05 else (10 if p_value < 0.10 else 0)
    impact_score = significance_score + volume_score + stat_score
    direction = "POSITIVE" if car > 0 else "NEGATIVE"
    return {"impact_score": round(min(impact_score, 100), 1), "magnitude": round(abs(car), 4), "direction": direction, "significant": p_value < 0.05}
