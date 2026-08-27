"""ALPHA BIST — Cumulative Abnormal Return (CAR).

CAR[t1, t2] = Σ AR_it (t1'den t2'ye)
MacKinlay (1997) metodolojisi.
"""

import numpy as np
import structlog

logger = structlog.get_logger()


def calculate_car(abnormal_returns: np.ndarray) -> float:
    """CAR = Σ AR (tüm window)."""
    return float(np.sum(abnormal_returns))


def calculate_car_window(
    abnormal_returns: np.ndarray,
    day_offsets: np.ndarray,
    start_day: int,
    end_day: int,
) -> float:
    """Belirli bir gün aralığı için CAR hesapla.

    Args:
        abnormal_returns: AR dizisi
        day_offsets: Gün offset dizisi (-5, -4, ..., 0, ..., +5)
        start_day: Başlangıç günü (ör: -3)
        end_day: Bitiş günü (ör: +3)

    Returns:
        CAR değeri
    """
    mask = (day_offsets >= start_day) & (day_offsets <= end_day)
    return float(np.sum(abnormal_returns[mask]))


def calculate_car_sub_windows(
    abnormal_returns: np.ndarray,
    day_offsets: np.ndarray,
) -> dict[str, float]:
    """Alt pencereler için CAR hesapla (pre-event, event-day, post-event).

    Returns:
        {"pre_event": car, "event_day": car, "post_event": car, "full": car}
    """
    results = {}

    # Pre-event: [start, -1]
    mask_pre = day_offsets < 0
    results["pre_event"] = float(np.sum(abnormal_returns[mask_pre])) if np.any(mask_pre) else 0.0

    # Event day: [0, 0]
    mask_event = day_offsets == 0
    results["event_day"] = float(np.sum(abnormal_returns[mask_event])) if np.any(mask_event) else 0.0

    # Post-event: [1, end]
    mask_post = day_offsets > 0
    results["post_event"] = float(np.sum(abnormal_returns[mask_post])) if np.any(mask_post) else 0.0

    # Full window
    results["full"] = calculate_car(abnormal_returns)

    return results


def calculate_car_series(abnormal_returns: np.ndarray) -> np.ndarray:
    """CAR serisi (kümülatif toplam).

    Returns:
        CAR serisi — her gün için kümülatif AR toplamı
    """
    return np.cumsum(abnormal_returns)


def calculate_aar(car_dict: dict[str, float]) -> float:
    """Average Abnormal Return (AAR) — birden fazla event'in ortalaması."""
    if not car_dict:
        return 0.0
    return float(np.mean(list(car_dict.values())))


def calculate_caar(
    car_dict: dict[str, np.ndarray],
) -> np.ndarray:
    """Cumulative Average Abnormal Return (CAAR).

    Args:
        car_dict: {event_id: car_series} sözlüğü

    Returns:
        CAAR serisi
    """
    if not car_dict:
        return np.array([])

    series_list = list(car_dict.values())
    min_len = min(len(s) for s in series_list)

    stacked = np.array([s[:min_len] for s in series_list])
    return np.mean(stacked, axis=0)
