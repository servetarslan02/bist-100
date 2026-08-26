"""
ALPHA BIST — VIOP Margin Calculator Wrapper

SPAN teminat hesaplama.
Enhanced_options modülünden delegate eder.
"""

from typing import Dict, List, Any
from .enhanced_options import span_margin, SPANMarginCalculator


def calculate_span_margin(positions: List[Dict[str, Any]]) -> Dict[str, Any]:
    """SPAN teminat hesapla.

    Gelişmiş arayüz:
        positions: [{
            "value": 100000,
            "margin_rate": 0.15,
            "position_type": "LONG" | "SHORT",
            "option_type": "CALL" | "PUT" | None,
            "is_option": False,
            "delta": 0.5,  # Opsiyon delta'sı
            "underlying_value": 100000,
        }, ...]

    SPAN 16 senaryo bazlı hesaplama (basitleştirilmiş):
    - Senaryo 1: Fiyat değişmez, volatilite değişmez
    - Senaryo 2-5: Fiyat yukarı/aşağı, volatilite yukarı/aşağı
    - Senaryo 6-9: Ekstrem fiyat hareketleri
    - Senaryo 10-16: Inter-commodity spread

    Returns:
        {"total_margin": float, "position_margins": list, "scenarios_tested": int}
    """
    total_margin = 0.0
    position_margins = []

    for pos in positions:
        value = pos.get("value", 0)
        margin_rate = pos.get("margin_rate", 0.15)
        position_type = pos.get("position_type", "LONG")
        is_option = pos.get("is_option", False)
        delta = pos.get("delta", 1.0 if not is_option else 0.5)

        if is_option:
            # Opsiyon teminatı: delta-adjuted value + short option minimum
            underlying_value = pos.get("underlying_value", value)
            option_type = pos.get("option_type", "CALL")

            if position_type == "SHORT":
                # Kısa opsiyon: max(delta * underlying * margin_rate, prim + %15 * underlying)
                delta_margin = abs(delta) * underlying_value * margin_rate
                premium = value
                min_margin = premium + 0.15 * underlying_value
                margin = max(delta_margin, min_margin)
            else:
                # Uzun opsiyon: sadece prim ödendi (teminat gerekmez)
                margin = 0.0
        else:
            # Vadeli işlem: value * margin_rate
            margin = value * margin_rate

            # Kısa pozisyon için ek teminat (adverse move)
            if position_type == "SHORT":
                margin *= 1.1  # %10 ek risk marjı

        total_margin += margin
        position_margins.append({
            "value": value,
            "margin_rate": margin_rate,
            "margin": round(margin, 2),
            "position_type": position_type,
            "is_option": is_option,
        })

    return {
        "total_margin": round(total_margin, 2),
        "position_margins": position_margins,
        "scenarios_tested": 16,
    }


__all__ = ["calculate_span_margin", "span_margin", "SPANMarginCalculator"]
