"""ALPHA BIST — SPAN Margin Calculator."""
from typing import Dict, Any, List

def calculate_span_margin(positions: List[Dict[str, Any]]) -> Dict[str, Any]:
    """SPAN teminat hesaplama (basitleştirilmiş)."""
    total_margin = 0
    for pos in positions:
        value = pos.get("value", 0)
        margin_rate = pos.get("margin_rate", 0.15)
        total_margin += value * margin_rate
    return {"total_margin": round(total_margin, 2), "positions": len(positions)}
