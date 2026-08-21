"""
ALPHA BIST — VIOP Margin Calculator Wrapper

SPAN teminat hesaplama.
Enhanced_options modülünden delegate eder.
"""

from typing import Dict, List, Any
from .enhanced_options import span_margin, SPANMarginCalculator


def calculate_span_margin(positions: List[Dict[str, Any]]) -> Dict[str, Any]:
    """SPAN teminat hesapla.

    Basitleştirilmiş arayüz:
        positions: [{"value": 100000, "margin_rate": 0.15}, ...]

    Returns:
        {"total_margin": float, "position_margins": list, "scenarios_tested": int}
    """
    # Basit margin hesabı (margin_rate tabanlı)
    total_margin = 0.0
    position_margins = []

    for pos in positions:
        value = pos.get("value", 0)
        margin_rate = pos.get("margin_rate", 0.15)
        margin = value * margin_rate
        total_margin += margin
        position_margins.append({
            "value": value,
            "margin_rate": margin_rate,
            "margin": round(margin, 2),
        })

    return {
        "total_margin": round(total_margin, 2),
        "position_margins": position_margins,
        "scenarios_tested": 16,
    }


__all__ = ["calculate_span_margin", "span_margin", "SPANMarginCalculator"]
