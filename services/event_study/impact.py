"""ALPHA BIST — Event Impact Score.

Event type'a göre özelleştirilmiş ağırlıklarla etki skoru hesaplama.
"""
from typing import Any

import structlog

logger = structlog.get_logger()

# Event type → etki ağırlıkları (significance, volume, statistical, magnitude)
EVENT_WEIGHTS = {
    "FINANCIAL_RESULTS": {"significance": 0.30, "volume": 0.25, "statistical": 0.25, "magnitude": 0.20},
    "DIVIDEND": {"significance": 0.25, "volume": 0.20, "statistical": 0.25, "magnitude": 0.30},
    "BUYBACK": {"significance": 0.25, "volume": 0.25, "statistical": 0.20, "magnitude": 0.30},
    "CAPITAL_INCREASE": {"significance": 0.30, "volume": 0.25, "statistical": 0.25, "magnitude": 0.20},
    "MERGER": {"significance": 0.35, "volume": 0.20, "statistical": 0.25, "magnitude": 0.20},
    "MANAGEMENT_CHANGE": {"significance": 0.20, "volume": 0.25, "statistical": 0.25, "magnitude": 0.30},
    "LEGAL": {"significance": 0.30, "volume": 0.20, "statistical": 0.30, "magnitude": 0.20},
    "CONTRACT": {"significance": 0.25, "volume": 0.25, "statistical": 0.20, "magnitude": 0.30},
    "GUIDANCE": {"significance": 0.25, "volume": 0.25, "statistical": 0.25, "magnitude": 0.25},
    "TCMB_RATE": {"significance": 0.35, "volume": 0.20, "statistical": 0.25, "magnitude": 0.20},
    "INFLATION": {"significance": 0.30, "volume": 0.20, "statistical": 0.25, "magnitude": 0.25},
    "GDP": {"significance": 0.30, "volume": 0.20, "statistical": 0.25, "magnitude": 0.25},
    "DEFAULT": {"significance": 0.25, "volume": 0.25, "statistical": 0.25, "magnitude": 0.25},
}


def calculate_event_impact(
    car: float,
    p_value: float,
    volume_change: float = 0.0,
    event_type: str = "DEFAULT",
    ar_series: list | None = None,
) -> dict[str, Any]:
    """Event type'a göre özelleştirilmiş etki skoru (0-100).

    Args:
        car: Cumulative Abnormal Return
        p_value: İstatistiksel anlamlılık p-value
        volume_change: Hacim değişimi (%)
        event_type: Event tipi
        ar_series: AR serisi (decay analizi için)

    Returns:
        Dict with impact_score, magnitude, direction, significant, impact_level
    """
    weights = EVENT_WEIGHTS.get(event_type, EVENT_WEIGHTS["DEFAULT"])

    # 1. Significance score (CAR büyüklüğü) — max 35
    significance_score = min(abs(car) * 100, 35) * (weights["significance"] / 0.35)

    # 2. Volume score — max 25
    volume_score = min(abs(volume_change) * 10, 25) * (weights["volume"] / 0.25)

    # 3. Statistical score — max 25
    if p_value < 0.01:
        stat_score = 25
    elif p_value < 0.05:
        stat_score = 20
    elif p_value < 0.10:
        stat_score = 10
    else:
        stat_score = 0
    stat_score *= (weights["statistical"] / 0.25)

    # 4. Magnitude score — max 15
    magnitude_score = min(abs(car) * 50, 15) * (weights["magnitude"] / 0.25)

    # Toplam skor
    impact_score = significance_score + volume_score + stat_score + magnitude_score
    impact_score = min(impact_score, 100)

    # Yön
    direction = "POSITIVE" if car > 0 else "NEGATIVE"

    # Etki seviyesi
    if impact_score >= 75:
        impact_level = "VERY_HIGH"
    elif impact_score >= 50:
        impact_level = "HIGH"
    elif impact_score >= 25:
        impact_level = "MEDIUM"
    else:
        impact_level = "LOW"

    result = {
        "impact_score": round(impact_score, 1),
        "magnitude": round(abs(car), 4),
        "direction": direction,
        "significant": bool(p_value < 0.05),
        "impact_level": impact_level,
        "event_type": event_type,
        "components": {
            "significance": round(significance_score, 1),
            "volume": round(volume_score, 1),
            "statistical": round(stat_score, 1),
            "magnitude": round(magnitude_score, 1),
        },
    }

    # Decay analizi (AR serisi varsa)
    if ar_series is not None and len(ar_series) > 1:
        from .event_decay import EventImpactDecay
        decay = EventImpactDecay()
        result["decay_analysis"] = decay.calculate_decay(ar_series)

    return result


def calculate_impact_batch(
    events: list,
) -> dict[str, Any]:
    """Birden fazla event için toplu etki analizi.

    Args:
        events: [{car, p_value, volume_change, event_type}] listesi

    Returns:
        Dict with individual impacts and summary statistics
    """
    impacts = []
    for event in events:
        impact = calculate_event_impact(
            car=event.get("car", 0),
            p_value=event.get("p_value", 1.0),
            volume_change=event.get("volume_change", 0),
            event_type=event.get("event_type", "DEFAULT"),
        )
        impacts.append(impact)

    # Özet istatistikler
    scores = [i["impact_score"] for i in impacts]
    return {
        "impacts": impacts,
        "summary": {
            "mean_score": round(float(sum(scores) / len(scores)), 1) if scores else 0,
            "max_score": round(max(scores), 1) if scores else 0,
            "min_score": round(min(scores), 1) if scores else 0,
            "n_events": len(impacts),
            "n_significant": sum(1 for i in impacts if i["significant"]),
            "n_positive": sum(1 for i in impacts if i["direction"] == "POSITIVE"),
            "n_negative": sum(1 for i in impacts if i["direction"] == "NEGATIVE"),
        },
    }
