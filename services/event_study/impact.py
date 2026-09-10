"""ALPHA BIST — Event Impact Score.

Event type'a göre özelleştirilmiş ağırlıklarla etki skoru hesaplama.
"""

from typing import Any

import numpy as np
import structlog

logger = structlog.get_logger()

# --- Sabitler (magic number yok) ---
DEFAULT_MAX_IMPACT_SCORE: float = 100.0
DEFAULT_MAX_SIGNIFICANCE_SCORE: float = 35.0
DEFAULT_MAX_VOLUME_SCORE: float = 25.0
DEFAULT_MAX_STAT_SCORE: float = 25.0
DEFAULT_MAX_MAGNITUDE_SCORE: float = 15.0
DEFAULT_VOLUME_SCALE_FACTOR: float = 10.0
DEFAULT_CAR_SCALE_FACTOR: float = 100.0
DEFAULT_MAGNITUDE_SCALE_FACTOR: float = 50.0

# İstatistiksel eşikler
P_VALUE_HIGHLY_SIGNIFICANT: float = 0.01
P_VALUE_SIGNIFICANT: float = 0.05
P_VALUE_MARGINALLY_SIGNIFICANT: float = 0.10

# Etki seviyesi eşikleri
IMPACT_VERY_HIGH_THRESHOLD: float = 75.0
IMPACT_HIGH_THRESHOLD: float = 50.0
IMPACT_MEDIUM_THRESHOLD: float = 25.0

# Stat skor kademeleri
STAT_SCORE_HIGH: float = 25.0
STAT_SCORE_MEDIUM: float = 20.0
STAT_SCORE_LOW: float = 10.0

# Event type → etki ağırlıkları (significance, volume, statistical, magnitude)
EVENT_WEIGHTS: dict[str, dict[str, float]] = {
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


def _validate_float(value: float, name: str) -> None:
    """Float değer için tip ve NaN/Inf kontrolü.

    Args:
        value: Kontrol edilecek değer
        name: Değerin adı (hata mesajı için)

    Raises:
        TypeError: Sayısal değilse
        ValueError: Değer NaN veya Inf ise
    """
    if not isinstance(value, (int, float, np.integer, np.floating)):
        raise TypeError(f"{name} sayısal olmalı, alınan: {type(value).__name__} ({value})")
    if not np.isfinite(value):
        raise ValueError(f"{name} sonucu sonlu değil: {value}")


def _validate_p_value(p_value: float) -> None:
    """p_value aralık ve sonluluk kontrolü.

    Args:
        p_value: Kontrol edilecek p-value

    Raises:
        ValueError: p_value [0, 1] aralığında değilse veya sonlu değilse
    """
    if not np.isfinite(p_value):
        raise ValueError(f"p_value sonlu değil: {p_value}")
    if not (0.0 <= p_value <= 1.0):
        raise ValueError(f"p_value [0, 1] aralığında olmalı, alınan: {p_value}")


def _validate_ar_series(ar_series: Any) -> np.ndarray:
    """AR serisi doğrulama ve ndarray'e dönüştürme.

    Args:
        ar_series: Kontrol edilecek AR serisi (np.ndarray, list veya tuple)

    Returns:
        Doğrulanmış numpy array

    Raises:
        TypeError: Desteklenmeyen tip ise
        ValueError: Boş array ise veya NaN/Inf içeriyorsa
    """
    if isinstance(ar_series, (list, tuple)):
        ar_series = np.asarray(ar_series, dtype=float)
    if not isinstance(ar_series, np.ndarray):
        raise TypeError(f"ar_series numpy.ndarray, list veya tuple olmalı, alınan: {type(ar_series).__name__}")
    if ar_series.size == 0:
        raise ValueError("ar_series boş olamaz")
    if not np.all(np.isfinite(ar_series)):
        raise ValueError("ar_series NaN veya Inf değerler içeriyor")
    return ar_series


def _validate_events(events: list) -> None:
    """Event listesi doğrulama.

    Args:
        events: Kontrol edilecek event listesi

    Raises:
        TypeError: Liste değilse
        ValueError: Boş liste ise
    """
    if not isinstance(events, list):
        raise TypeError(f"events liste olmalı, alınan: {type(events).__name__}")
    if len(events) == 0:
        raise ValueError("events listesi boş olamaz")


def calculate_event_impact(
    car: float,
    p_value: float,
    volume_change: float = 0.0,
    event_type: str = "DEFAULT",
    ar_series: np.ndarray | None = None,
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

    Raises:
        TypeError: Parametre tipleri uygun değilse
        ValueError: Değerler sonlu değilse veya p_value aralık dışındaysa
    """
    # --- Validasyon ---
    _validate_float(car, "car")
    _validate_p_value(p_value)
    _validate_float(volume_change, "volume_change")

    weights = EVENT_WEIGHTS.get(event_type, EVENT_WEIGHTS["DEFAULT"])

    if event_type not in EVENT_WEIGHTS:
        logger.warning(
            "etki_skoru_bilinmeyen_event_tipi",
            event_type=event_type,
            varsayilan="DEFAULT",
        )

    # 1. Significance score (CAR büyüklüğü) — max 35
    significance_score = (
        min(abs(car) * DEFAULT_CAR_SCALE_FACTOR, DEFAULT_MAX_SIGNIFICANCE_SCORE)
        * (weights["significance"] / 0.35)
    )

    # 2. Volume score — max 25
    volume_score = (
        min(abs(volume_change) * DEFAULT_VOLUME_SCALE_FACTOR, DEFAULT_MAX_VOLUME_SCORE)
        * (weights["volume"] / 0.25)
    )

    # 3. Statistical score — max 25
    if p_value < P_VALUE_HIGHLY_SIGNIFICANT:
        stat_score = STAT_SCORE_HIGH
    elif p_value < P_VALUE_SIGNIFICANT:
        stat_score = STAT_SCORE_MEDIUM
    elif p_value < P_VALUE_MARGINALLY_SIGNIFICANT:
        stat_score = STAT_SCORE_LOW
    else:
        stat_score = 0.0
    stat_score *= weights["statistical"] / 0.25

    # 4. Magnitude score — max 15
    magnitude_score = (
        min(abs(car) * DEFAULT_MAGNITUDE_SCALE_FACTOR, DEFAULT_MAX_MAGNITUDE_SCORE)
        * (weights["magnitude"] / 0.25)
    )

    # Toplam skor
    impact_score = significance_score + volume_score + stat_score + magnitude_score
    impact_score = min(impact_score, DEFAULT_MAX_IMPACT_SCORE)

    # Yön
    direction = "POSITIVE" if car > 0 else "NEGATIVE"

    # Etki seviyesi
    if impact_score >= IMPACT_VERY_HIGH_THRESHOLD:
        impact_level = "VERY_HIGH"
    elif impact_score >= IMPACT_HIGH_THRESHOLD:
        impact_level = "HIGH"
    elif impact_score >= IMPACT_MEDIUM_THRESHOLD:
        impact_level = "MEDIUM"
    else:
        impact_level = "LOW"

    result: dict[str, Any] = {
        "impact_score": round(impact_score, 1),
        "magnitude": round(abs(car), 4),
        "direction": direction,
        "significant": bool(p_value < P_VALUE_SIGNIFICANT),
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
    if ar_series is not None:
        validated_ar = _validate_ar_series(ar_series)
        if len(validated_ar) > 1:
            from .event_decay import EventImpactDecay

            decay = EventImpactDecay()
            result["decay_analysis"] = decay.calculate_decay(validated_ar)

    logger.debug(
        "etki_skoru_hesaplandi",
        event_type=event_type,
        impact_score=result["impact_score"],
        impact_level=impact_level,
        direction=direction,
        significant=result["significant"],
    )

    return result


def calculate_impact_batch(
    events: list[dict[str, Any]],
) -> dict[str, Any]:
    """Birden fazla event için toplu etki analizi.

    Args:
        events: [{car, p_value, volume_change, event_type}] listesi

    Returns:
        Dict with individual impacts and summary statistics

    Raises:
        TypeError: events liste değilse
        ValueError: events boş liste ise
    """
    _validate_events(events)

    impacts: list[dict[str, Any]] = []
    for idx, event in enumerate(events):
        if not isinstance(event, dict):
            raise TypeError(f"events[{idx}] sözlük olmalı, alınan: {type(event).__name__}")
        impact = calculate_event_impact(
            car=event.get("car", 0),
            p_value=event.get("p_value", 1.0),
            volume_change=event.get("volume_change", 0),
            event_type=event.get("event_type", "DEFAULT"),
        )
        impacts.append(impact)

    # Özet istatistikler (scores boş olamaz — _validate_events bunu garanti eder)
    scores = [i["impact_score"] for i in impacts]
    n_significant = sum(1 for i in impacts if i["significant"])
    n_positive = sum(1 for i in impacts if i["direction"] == "POSITIVE")
    n_negative = sum(1 for i in impacts if i["direction"] == "NEGATIVE")

    summary: dict[str, Any] = {
        "mean_score": round(float(sum(scores) / len(scores)), 1),
        "max_score": round(max(scores), 1),
        "min_score": round(min(scores), 1),
        "n_events": len(impacts),
        "n_significant": n_significant,
        "n_positive": n_positive,
        "n_negative": n_negative,
    }

    logger.debug(
        "etki_skoru_toplu_hesaplandi",
        n_events=summary["n_events"],
        mean_score=summary["mean_score"],
        n_significant=n_significant,
    )

    return {
        "impacts": impacts,
        "summary": summary,
    }
