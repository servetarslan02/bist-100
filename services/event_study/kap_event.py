"""ALPHA BIST — KAP Event Analysis.

KAP açıklamaları için detaylı event study.
Event type mapping, event-specific window sizes, clustering detection.
"""
import numpy as np
from typing import Dict, List, Any, Optional
from datetime import datetime
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


def classify_kap_event(description: str) -> Dict[str, Any]:
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
    stock_returns: np.ndarray,
    market_returns: np.ndarray,
    dates: Optional[np.ndarray] = None,
    volume_data: Optional[np.ndarray] = None,
) -> Dict[str, Any]:
    """KAP açıklaması için detaylı event study.

    Args:
        ticker: Hisse kodu
        event_description: KAP açıklama metni
        event_date: Event tarihi
        stock_returns: Hisse getirileri (event window)
        market_returns: BIST-100 getirileri (event window)
        dates: Tarih dizisi (opsiyonel)
        volume_data: Hacim verisi (opsiyonel)

    Returns:
        Dict with event_type, car, impact, significance, classification
    """
    from .expected_return import calculate_expected_return
    from .abnormal_return import calculate_abnormal_return
    from .car import calculate_car, calculate_car_sub_windows
    from .statistical_test import test_significance
    from .impact import calculate_event_impact

    # Event sınıflandırma
    classification = classify_kap_event(event_description)
    event_type = classification["event_type"]

    # Veri kontrolü
    n = min(len(stock_returns), len(market_returns))
    if n < 5:
        logger.warning("insufficient_data_for_kap_event", ticker=ticker, n=n)
        return {
            "ticker": ticker,
            "event_type": event_type,
            "event_date": event_date.isoformat() if isinstance(event_date, datetime) else str(event_date),
            "error": "Yetersiz veri",
            "car": 0.0,
            "significant": False,
        }

    sr = stock_returns[:n]
    mr = market_returns[:n]

    # Expected return modeli
    params = calculate_expected_return(sr, mr, model="market")

    # Abnormal return
    ar = calculate_abnormal_return(sr, mr, params["alpha"], params["beta_market"])

    # CAR
    car = calculate_car(ar)

    # Alt pencereler için CAR
    sub_cars = {}
    if dates is not None:
        day_offsets = np.array([(d - event_date).days for d in dates[:n]])
        sub_cars = calculate_car_sub_windows(ar, day_offsets)

    # İstatistiksel test
    n_params = 2  # market model
    significance = test_significance(car, ar, n_params=n_params)

    # Hacim analizi
    volume_change = 0.0
    if volume_data is not None and len(volume_data) > 1:
        vol = volume_data[:n]
        if len(vol) > 5:
            recent_vol = np.mean(vol[-3:])
            base_vol = np.mean(vol[:-3])
            volume_change = (recent_vol - base_vol) / base_vol if base_vol > 0 else 0.0

    # Etki skoru
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


def analyze_kap_events_batch(
    events: List[Dict[str, Any]],
    market_returns: np.ndarray,
    dates: Optional[np.ndarray] = None,
) -> Dict[str, Any]:
    """Birden fazla KAP event'i için toplu analiz.

    Args:
        events: [{ticker, description, date, stock_returns, volume_data}]
        market_returns: BIST-100 getirileri
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
            stock_returns=event["stock_returns"],
            market_returns=market_returns,
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
            "event_type_distribution": {
                r["event_type"]: sum(1 for x in results if x["event_type"] == r["event_type"])
                for set_r in [set(r["event_type"] for r in results)]
                for r in results
            },
        },
    }
