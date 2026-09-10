"""ALPHA BIST — KAP Event Analysis.

KAP açıklamaları için detaylı event study.
Event type mapping, event-specific window sizes, clustering detection.
MacKinlay (1997) — estimation window ayrı, event window ayrı.
"""

from datetime import datetime
from typing import Any

import numpy as np
import structlog

logger = structlog.get_logger()

# --- Sabitler ---
MIN_ESTIMATION_SAMPLES: int = 10
MIN_EVENT_SAMPLES: int = 3
MIN_SPLIT_IDX: int = 5
CONFIDENCE_DIVISOR: float = 3.0
MAX_CONFIDENCE: float = 1.0
DEFAULT_ESTIMATION_RATIO: float = 0.7
ESTIMATION_RATIO_MIN: float = 0.1
ESTIMATION_RATIO_MAX: float = 0.9
VOLUME_RECENT_WINDOW: int = 3
VOLUME_MIN_SAMPLES: int = 2

# KAP Event Type Mapping
KAP_EVENT_TYPES: dict[str, dict[str, Any]] = {
    # Finansal Sonuçlar
    "FINANCIAL_RESULTS": {
        "keywords": ["finansal", "finans", "bilanço", "gelir", "kâr", "kar", "ciro"],
        "estimation_window": 120,
        "event_window": (-5, 5),
        "expected_impact": "HIGH",
        "weight": 1.0,
    },
    # Temettü / Kar Payı
    "DIVIDEND": {
        "keywords": ["temettü", "kar payı", "kar_payı", "temettü dağıtımı", "nakit temettü"],
        "estimation_window": 60,
        "event_window": (-3, 3),
        "expected_impact": "MEDIUM",
        "weight": 0.8,
    },
    # Geri Alım
    "BUYBACK": {
        "keywords": ["geri alım", "pay geri alım", "buyback", "hisse geri alım"],
        "estimation_window": 60,
        "event_window": (-3, 3),
        "expected_impact": "MEDIUM",
        "weight": 0.7,
    },
    # Sermaye Artırımı
    "CAPITAL_INCREASE": {
        "keywords": ["sermaye artırımı", "bedelsiz", "bedelli", "sermaye"],
        "estimation_window": 90,
        "event_window": (-5, 5),
        "expected_impact": "HIGH",
        "weight": 0.9,
    },
    # Birleşme / Satın Alma
    "MERGER": {
        "keywords": ["birleşme", "satın alma", "devralma", "merger", "acquisition"],
        "estimation_window": 120,
        "event_window": (-10, 10),
        "expected_impact": "VERY_HIGH",
        "weight": 1.2,
    },
    # Yönetim Değişikliği
    "MANAGEMENT_CHANGE": {
        "keywords": ["yönetim", "CEO", "genel müdür", "başkan", "yonetim kurulu"],
        "estimation_window": 60,
        "event_window": (-3, 3),
        "expected_impact": "LOW",
        "weight": 0.5,
    },
    # Yasal / Düzenleyici
    "LEGAL": {
        "keywords": ["dava", "ceza", "yaptırım", "düzenleme", "regülasyon", "SPK"],
        "estimation_window": 90,
        "event_window": (-5, 5),
        "expected_impact": "MEDIUM",
        "weight": 0.8,
    },
    # Sözleşme / Yatırım
    "CONTRACT": {
        "keywords": ["sözleşme", "sipariş", "yatırım", "proje", "ihale"],
        "estimation_window": 60,
        "event_window": (-3, 3),
        "expected_impact": "MEDIUM",
        "weight": 0.7,
    },
    # Beklenti / Rehberlik
    "GUIDANCE": {
        "keywords": ["beklenti", "rehberlik", "tahmin", "hedef", "guidance"],
        "estimation_window": 60,
        "event_window": (-3, 3),
        "expected_impact": "MEDIUM",
        "weight": 0.7,
    },
}

# REQUIRED_EVENT_KEYS: analyze_kap_events_batch'te her event dict'inde bulunması gereken key'ler
REQUIRED_EVENT_KEYS: tuple[str, ...] = ("ticker", "date", "estimation_stock_returns", "event_stock_returns")


def _validate_description(description: str) -> str:
    """KAP açıklama metni doğrulama.

    Args:
        description: Kontrol edilecek açıklama metni

    Returns:
        Doğrulanmış description (lowercase)

    Raises:
        TypeError: String değilse
        ValueError: Boş string ise
    """
    if not isinstance(description, str):
        raise TypeError(f"description string olmalı, alınan: {type(description).__name__}")
    desc_stripped = description.strip()
    if not desc_stripped:
        raise ValueError("description boş olamaz")
    return desc_stripped.lower()


def _validate_ticker(ticker: str) -> None:
    """Ticker doğrulama.

    Args:
        ticker: Kontrol edilecek ticker

    Raises:
        TypeError: String değilse
        ValueError: Boş string ise
    """
    if not isinstance(ticker, str):
        raise TypeError(f"ticker string olmalı, alınan: {type(ticker).__name__}")
    if not ticker.strip():
        raise ValueError("ticker boş olamaz")


def _validate_event_date(event_date: Any) -> None:
    """Event tarihi doğrulama.

    Args:
        event_date: Kontrol edilecek tarih

    Raises:
        TypeError: datetime veya string değilse
    """
    if not isinstance(event_date, (datetime, str)):
        raise TypeError(
            f"event_date datetime veya ISO format string olmalı, alınan: {type(event_date).__name__}"
        )


def _validate_array_not_empty(arr: np.ndarray, name: str, min_size: int = 1) -> np.ndarray:
    """Array doğrulama (tip, boşluk, NaN/Inf).

    Args:
        arr: Kontrol edilecek array (ndarray, list veya tuple)
        name: Array adı (hata mesajı için)
        min_size: Minimum boyut

    Returns:
        Doğrulanmış numpy array

    Raises:
        TypeError: Desteklenmeyen tip ise
        ValueError: Boş, yetersiz veya NaN/Inf içeriyorsa
    """
    if isinstance(arr, (list, tuple)):
        arr = np.asarray(arr, dtype=float)
    if not isinstance(arr, np.ndarray):
        raise TypeError(f"{name} numpy.ndarray, list veya tuple olmalı, alınan: {type(arr).__name__}")
    if arr.size == 0:
        raise ValueError(f"{name} boş olamaz")
    if arr.size < min_size:
        raise ValueError(f"{name} en az {min_size} örneklem içermeli, alınan: {arr.size}")
    if not np.all(np.isfinite(arr)):
        raise ValueError(f"{name} NaN veya Inf değerler içeriyor")
    return arr


def _validate_estimation_ratio(estimation_ratio: float) -> None:
    """Estimation ratio aralık kontrolü.

    Args:
        estimation_ratio: Kontrol edilecek oran

    Raises:
        TypeError: Sayısal değilse
        ValueError: [0.1, 0.9] aralığında değilse
    """
    if not isinstance(estimation_ratio, (int, float, np.integer, np.floating)):
        raise TypeError(f"estimation_ratio sayısal olmalı, alınan: {type(estimation_ratio).__name__}")
    if not (ESTIMATION_RATIO_MIN <= estimation_ratio <= ESTIMATION_RATIO_MAX):
        raise ValueError(
            f"estimation_ratio [{ESTIMATION_RATIO_MIN}, {ESTIMATION_RATIO_MAX}] aralığında olmalı, "
            f"alınan: {estimation_ratio}"
        )


def _validate_events_list(events: list) -> None:
    """Events listesi doğrulama.

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


def _validate_event_dict(event: Any, idx: int) -> None:
    """Event dict doğrulama (zorunlu key'ler).

    Args:
        event: Kontrol edilecek event dict'i
        idx: Dizideki indeks (hata mesajı için)

    Raises:
        TypeError: Sözlük değilse
        ValueError: Zorunlu key'ler eksikse
    """
    if not isinstance(event, dict):
        raise TypeError(f"events[{idx}] sözlük olmalı, alınan: {type(event).__name__}")
    missing = [k for k in REQUIRED_EVENT_KEYS if k not in event]
    if missing:
        raise ValueError(f"events[{idx}] zorunlu key'ler eksik: {missing}")


def classify_kap_event(description: str) -> dict[str, Any]:
    """KAP açıklamasından event tipini sınıflandır.

    Args:
        description: KAP açıklama metni

    Returns:
        Dict with event_type, confidence, config

    Raises:
        TypeError: description string değilse
        ValueError: description boş ise
    """
    desc_lower = _validate_description(description)

    scores: dict[str, int] = {}
    for event_type, config in KAP_EVENT_TYPES.items():
        score = sum(1 for kw in config["keywords"] if kw in desc_lower)
        if score > 0:
            scores[event_type] = score

    if not scores:
        logger.debug(
            "kap_event_siniflandirilamadi",
            description=description[:50],
            varsayilan="CONTRACT",
        )
        return {
            "event_type": "UNKNOWN",
            "confidence": 0.0,
            "config": KAP_EVENT_TYPES["CONTRACT"],  # Varsayılan
        }

    best_type = max(scores, key=scores.get)
    max_score = scores[best_type]
    confidence = min(max_score / CONFIDENCE_DIVISOR, MAX_CONFIDENCE)  # Normalize

    return {
        "event_type": best_type,
        "confidence": round(confidence, 2),
        "config": KAP_EVENT_TYPES[best_type],
    }


def analyze_kap_event(
    ticker: str,
    event_description: str,
    event_date: datetime,
    estimation_stock_returns: np.ndarray,
    estimation_market_returns: np.ndarray,
    event_stock_returns: np.ndarray,
    event_market_returns: np.ndarray,
    dates: np.ndarray | None = None,
    volume_data: np.ndarray | None = None,
) -> dict[str, Any]:
    """KAP açıklaması için detaylı event study (MacKinlay 1997 uyumlu).

    Estimation window ve event window AYRI veri ile çalışır.
    Look-ahead bias önlenir.

    Args:
        ticker: Hisse kodu
        event_description: KAP açıklama metni
        event_date: Event tarihi
        estimation_stock_returns: Estimation window hisse getirileri
        estimation_market_returns: Estimation window BIST-100 getirileri
        event_stock_returns: Event window hisse getirileri
        event_market_returns: Event window BIST-100 getirileri
        dates: Event window tarih dizisi (opsiyonel)
        volume_data: Event window hacim verisi (opsiyonel)

    Returns:
        Dict with event_type, car, impact, significance, classification

    Raises:
        TypeError: Parametre tipleri uygun değilse
        ValueError: Veri yetersiz veya geçersiz ise
    """
    from .abnormal_return import calculate_abnormal_return
    from .car import calculate_car, calculate_car_sub_windows
    from .expected_return import calculate_expected_return
    from .impact import calculate_event_impact
    from .statistical_test import test_significance

    # --- Validasyon ---
    _validate_ticker(ticker)
    _validate_event_date(event_date)

    # Event sınıflandırma
    classification = classify_kap_event(event_description)
    event_type = classification["event_type"]

    # Tip dönüşümü + doğrulama
    est_sr = _validate_array_not_empty(estimation_stock_returns, "estimation_stock_returns", MIN_ESTIMATION_SAMPLES)
    est_mr = _validate_array_not_empty(estimation_market_returns, "estimation_market_returns", MIN_ESTIMATION_SAMPLES)
    evt_sr = _validate_array_not_empty(event_stock_returns, "event_stock_returns", MIN_EVENT_SAMPLES)
    evt_mr = _validate_array_not_empty(event_market_returns, "event_market_returns", MIN_EVENT_SAMPLES)

    # 1. Estimation window → model parametreleri
    params = calculate_expected_return(est_sr, est_mr, model="market")

    # 2. Event window → abnormal return
    n_evt = min(len(evt_sr), len(evt_mr))
    ar = calculate_abnormal_return(evt_sr[:n_evt], evt_mr[:n_evt], params["alpha"], params["beta_market"])

    # 3. CAR
    car = calculate_car(ar)

    # 4. Alt pencereler için CAR
    sub_cars: dict[str, Any] = {}
    if dates is not None:
        day_offsets = np.array([(d - event_date).days for d in dates[:n_evt]])
        sub_cars = calculate_car_sub_windows(ar, day_offsets)

    # 5. İstatistiksel test
    significance = test_significance(car, ar, n_params=2)

    # 6. Hacim analizi
    volume_change = _calculate_volume_change(volume_data, n_evt)

    # 7. Etki skoru
    impact = calculate_event_impact(
        car=car,
        p_value=significance["p_value"],
        volume_change=volume_change,
        event_type=event_type,
        ar_series=ar.tolist(),
    )

    result: dict[str, Any] = {
        "ticker": ticker,
        "event_type": event_type,
        "event_date": event_date.isoformat() if isinstance(event_date, datetime) else str(event_date),
        "classification_confidence": classification["confidence"],
        "car": round(car, 4),
        "car_sub_windows": sub_cars,
        "significance": significance,
        "impact": impact,
        "volume_change": round(volume_change, 4),
        "model_params": {
            "alpha": round(params["alpha"], 6),
            "beta": round(params["beta_market"], 4),
            "r_squared": round(params["r_squared"], 4),
        },
    }

    logger.debug(
        "kap_event_analiz_edildi",
        ticker=ticker,
        event_type=event_type,
        car=round(car, 4),
        significant=significance["significant"],
        impact_score=impact["impact_score"],
    )

    return result


def analyze_kap_event_simple(
    ticker: str,
    event_description: str,
    event_date: datetime,
    stock_returns: np.ndarray,
    market_returns: np.ndarray,
    estimation_ratio: float = DEFAULT_ESTIMATION_RATIO,
    dates: np.ndarray | None = None,
    volume_data: np.ndarray | None = None,
) -> dict[str, Any]:
    """Basitleştirilmiş KAP event study — tek veri setini estimation/event olarak böler.

    Veriyi estimation_ratio oranında estimation ve event window olarak ayırır.
    Tam veri olmadığında pratik çözüm.

    Args:
        ticker: Hisse kodu
        event_description: KAP açıklama metni
        event_date: Event tarihi
        stock_returns: Tüm getiri serisi (estimation + event)
        market_returns: Tüm piyasa getiri serisi
        estimation_ratio: Estimation window oranı (default: %70)
        dates: Tarih dizisi
        volume_data: Hacim verisi

    Returns:
        Dict with event_type, car, impact, significance

    Raises:
        TypeError: Parametre tipleri uygun değilse
        ValueError: Veri yetersiz veya estimation_ratio geçersiz ise
    """
    _validate_ticker(ticker)
    _validate_event_date(event_date)
    _validate_estimation_ratio(estimation_ratio)

    sr = _validate_array_not_empty(stock_returns, "stock_returns", MIN_ESTIMATION_SAMPLES)
    mr = _validate_array_not_empty(market_returns, "market_returns", MIN_ESTIMATION_SAMPLES)

    n = min(len(sr), len(mr))
    if n < MIN_ESTIMATION_SAMPLES:
        classification = classify_kap_event(event_description)
        return _error_result(ticker, classification["event_type"], event_date, "Yetersiz veri")

    # Veriyi estimation ve event olarak böl
    split_idx = int(n * estimation_ratio)
    if split_idx < MIN_SPLIT_IDX:
        split_idx = MIN_SPLIT_IDX
    if n - split_idx < MIN_EVENT_SAMPLES:
        split_idx = n - MIN_EVENT_SAMPLES

    est_sr = sr[:split_idx]
    est_mr = mr[:split_idx]
    evt_sr = sr[split_idx:]
    evt_mr = mr[split_idx:]

    return analyze_kap_event(
        ticker=ticker,
        event_description=event_description,
        event_date=event_date,
        estimation_stock_returns=est_sr,
        estimation_market_returns=est_mr,
        event_stock_returns=evt_sr,
        event_market_returns=evt_mr,
        dates=dates[split_idx:] if dates is not None else None,
        volume_data=volume_data[split_idx:] if volume_data is not None else None,
    )


def analyze_kap_events_batch(
    events: list[dict[str, Any]],
    estimation_market_returns: np.ndarray,
    event_market_returns: np.ndarray,
    dates: np.ndarray | None = None,
) -> dict[str, Any]:
    """Birden fazla KAP event'i için toplu analiz.

    Args:
        events: [{ticker, description, date, estimation_stock_returns, event_stock_returns}]
        estimation_market_returns: Estimation window BIST-100 getirileri
        event_market_returns: Event window BIST-100 getirileri
        dates: Tarih dizisi

    Returns:
        Dict with individual results and summary statistics

    Raises:
        TypeError: Parametre tipleri uygun değilse
        ValueError: Boş liste veya zorunlu key'ler eksikse
    """
    from .cross_sectional import CrossSectionalEventStudy

    _validate_events_list(events)

    # Her event dict'ini doğrula
    for idx, event in enumerate(events):
        _validate_event_dict(event, idx)

    # Market getirilerini doğrula
    est_mr = _validate_array_not_empty(estimation_market_returns, "estimation_market_returns")
    evt_mr = _validate_array_not_empty(event_market_returns, "event_market_returns")

    results: list[dict[str, Any]] = []
    for event in events:
        result = analyze_kap_event(
            ticker=event["ticker"],
            event_description=event.get("description", ""),
            event_date=event["date"],
            estimation_stock_returns=event["estimation_stock_returns"],
            estimation_market_returns=est_mr,
            event_stock_returns=event["event_stock_returns"],
            event_market_returns=evt_mr,
            dates=dates,
            volume_data=event.get("volume_data"),
        )
        results.append(result)

    # Cross-sectional analysis
    cs = CrossSectionalEventStudy()
    cs_result = cs.analyze(results, group_by="event_type")

    n_significant = sum(1 for r in results if r.get("significance", {}).get("significant", False))
    mean_car = round(float(np.mean([r["car"] for r in results])), 4)

    summary: dict[str, Any] = {
        "n_events": len(results),
        "n_significant": n_significant,
        "mean_car": mean_car,
    }

    logger.debug(
        "kap_event_toplu_analiz_edildi",
        n_events=summary["n_events"],
        n_significant=n_significant,
        mean_car=mean_car,
    )

    return {
        "individual_results": results,
        "cross_sectional": cs_result,
        "summary": summary,
    }


def _calculate_volume_change(volume_data: np.ndarray | None, n: int) -> float:
    """Hacim değişimi hesapla.

    Args:
        volume_data: Hacim verisi (None olabilir)
        n: Kullanılacak veri uzunluğu

    Returns:
        Hacim değişimi oranı (%)
    """
    if volume_data is None or len(volume_data) < VOLUME_MIN_SAMPLES:
        return 0.0
    vol = np.asarray(volume_data, dtype=float)[:n]
    if not np.all(np.isfinite(vol)):
        logger.warning("hacim_verisi_nan_inf", n=len(vol))
        return 0.0
    if len(vol) > VOLUME_RECENT_WINDOW:
        recent_vol = np.mean(vol[-VOLUME_RECENT_WINDOW:])
        base_vol = np.mean(vol[:-VOLUME_RECENT_WINDOW])
        if base_vol <= 0:
            return 0.0
        return (recent_vol - base_vol) / base_vol
    return 0.0


def _error_result(ticker: str, event_type: str, event_date: Any, error_msg: str) -> dict[str, Any]:
    """Hata sonuç şablonu.

    Args:
        ticker: Hisse kodu
        event_type: Event tipi
        event_date: Event tarihi
        error_msg: Hata mesajı

    Returns:
        Varsayılan değerlerle hata sonucu
    """
    logger.warning(
        "kap_event_hata",
        ticker=ticker,
        event_type=event_type,
        hata=error_msg,
    )
    return {
        "ticker": ticker,
        "event_type": event_type,
        "event_date": event_date.isoformat() if isinstance(event_date, datetime) else str(event_date),
        "error": error_msg,
        "car": 0.0,
        "significant": False,
        "significance": {"t_statistic": 0.0, "p_value": 1.0, "significant": False},
        "impact": {"impact_score": 0.0, "direction": "NEUTRAL", "significant": False, "impact_level": "LOW"},
    }
