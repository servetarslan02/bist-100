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

# KAP Event Type Mapping
KAP_EVENT_TYPES = {
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


def classify_kap_event(description: str) -> dict[str, Any]:
    """KAP açıklamasından event tipini sınıflandır.

    Args:
        description: KAP açıklama metni

    Returns:
        Dict with event_type, confidence, config
    """
    desc_lower = description.lower()

    scores = {}
    for event_type, config in KAP_EVENT_TYPES.items():
        score = sum(1 for kw in config["keywords"] if kw in desc_lower)
        if score > 0:
            scores[event_type] = score

    if not scores:
        return {
            "event_type": "UNKNOWN",
            "confidence": 0.0,
            "config": KAP_EVENT_TYPES["CONTRACT"],  # Varsayılan
        }

    best_type = max(scores, key=scores.get)
    max_score = scores[best_type]
    confidence = min(max_score / 3.0, 1.0)  # Normalize

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
    """
    from .abnormal_return import calculate_abnormal_return
    from .car import calculate_car, calculate_car_sub_windows
    from .expected_return import calculate_expected_return
    from .impact import calculate_event_impact
    from .statistical_test import test_significance

    # Event sınıflandırma
    classification = classify_kap_event(event_description)
    event_type = classification["event_type"]

    # Tip dönüşümü
    est_sr = np.array(estimation_stock_returns, dtype=float)
    est_mr = np.array(estimation_market_returns, dtype=float)
    evt_sr = np.array(event_stock_returns, dtype=float)
    evt_mr = np.array(event_market_returns, dtype=float)

    # Veri kontrolü
    if len(est_sr) < 10 or len(est_mr) < 10:
        logger.warning("insufficient_estimation_data", ticker=ticker, n_est=len(est_sr))
        return _error_result(ticker, event_type, event_date, "Estimation verisi yetersiz")

    if len(evt_sr) < 3 or len(evt_mr) < 3:
        logger.warning("insufficient_event_data", ticker=ticker, n_evt=len(evt_sr))
        return _error_result(ticker, event_type, event_date, "Event verisi yetersiz")

    # 1. Estimation window → model parametreleri
    params = calculate_expected_return(est_sr, est_mr, model="market")

    # 2. Event window → abnormal return
    n_evt = min(len(evt_sr), len(evt_mr))
    ar = calculate_abnormal_return(evt_sr[:n_evt], evt_mr[:n_evt], params["alpha"], params["beta_market"])

    # 3. CAR
    car = calculate_car(ar)

    # 4. Alt pencereler için CAR
    sub_cars = {}
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

    result = {
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

    logger.info(
        "kap_event_analyzed",
        ticker=ticker,
        event_type=event_type,
        car=car,
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
    estimation_ratio: float = 0.7,
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
    """
    sr = np.array(stock_returns, dtype=float)
    mr = np.array(market_returns, dtype=float)
    n = min(len(sr), len(mr))

    if n < 10:
        classification = classify_kap_event(event_description)
        return _error_result(ticker, classification["event_type"], event_date, "Yetersiz veri")

    # Veriyi estimation ve event olarak böl
    split_idx = int(n * estimation_ratio)
    if split_idx < 5:
        split_idx = 5
    if n - split_idx < 3:
        split_idx = n - 3

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
    """
    from .cross_sectional import CrossSectionalEventStudy

    results = []
    for event in events:
        result = analyze_kap_event(
            ticker=event["ticker"],
            event_description=event.get("description", ""),
            event_date=event["date"],
            estimation_stock_returns=event["estimation_stock_returns"],
            estimation_market_returns=estimation_market_returns,
            event_stock_returns=event["event_stock_returns"],
            event_market_returns=event_market_returns,
            dates=dates,
            volume_data=event.get("volume_data"),
        )
        results.append(result)

    # Cross-sectional analysis
    cs = CrossSectionalEventStudy()
    cs_result = cs.analyze(results, group_by="event_type")

    return {
        "individual_results": results,
        "cross_sectional": cs_result,
        "summary": {
            "n_events": len(results),
            "n_significant": sum(1 for r in results if r.get("significance", {}).get("significant", False)),
            "mean_car": round(float(np.mean([r["car"] for r in results])), 4) if results else 0,
        },
    }


def _calculate_volume_change(volume_data: np.ndarray | None, n: int) -> float:
    """Hacim değişimi hesapla."""
    if volume_data is None or len(volume_data) < 2:
        return 0.0
    vol = np.array(volume_data, dtype=float)[:n]
    if len(vol) > 5:
        recent_vol = np.mean(vol[-3:])
        base_vol = np.mean(vol[:-3])
        return (recent_vol - base_vol) / base_vol if base_vol > 0 else 0.0
    return 0.0


def _error_result(ticker: str, event_type: str, event_date: Any, error_msg: str) -> dict[str, Any]:
    """Hata sonuç şablonu."""
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
