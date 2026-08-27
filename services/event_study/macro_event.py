"""ALPHA BIST — Macro Event Analysis.

TCMB faiz kararı, enflasyon, GSYH, cari açık, USDTRY reaksiyonu.
MacKinlay (1997) metodolojisi ile detaylı makro event study.
"""

from typing import Any

import numpy as np
import structlog

logger = structlog.get_logger()

# Makro event type konfigürasyonu
MACRO_EVENT_TYPES = {
    "TCMB_RATE": {
        "name": "TCMB Faiz Kararı",
        "estimation_window": 90,
        "event_window": (-1, 3),
        "impact_level": "VERY_HIGH",
    },
    "INFLATION": {
        "name": "Enflasyon Verisi (TÜFE)",
        "estimation_window": 60,
        "event_window": (-1, 3),
        "impact_level": "HIGH",
    },
    "GDP": {
        "name": "GSYH Verisi",
        "estimation_window": 90,
        "event_window": (-1, 3),
        "impact_level": "MEDIUM",
    },
    "CPI": {
        "name": "Tüketici Fiyat Endeksi",
        "estimation_window": 60,
        "event_window": (-1, 3),
        "impact_level": "HIGH",
    },
    "PPI": {
        "name": "Üretici Fiyat Endeksi",
        "estimation_window": 60,
        "event_window": (-1, 2),
        "impact_level": "MEDIUM",
    },
    "CURRENT_ACCOUNT": {
        "name": "Cari Açık",
        "estimation_window": 60,
        "event_window": (-1, 3),
        "impact_level": "MEDIUM",
    },
    "UNEMPLOYMENT": {
        "name": "İşsizlik Verisi",
        "estimation_window": 60,
        "event_window": (-1, 2),
        "impact_level": "LOW",
    },
    "INDUSTRIAL_PRODUCTION": {
        "name": "Sanayi Üretim Endeksi",
        "estimation_window": 60,
        "event_window": (-1, 2),
        "impact_level": "MEDIUM",
    },
}


def analyze_tcmb_event(
    rate_actual: float,
    rate_expected: float,
    rate_previous: float,
    market_returns: np.ndarray,
    dates: np.ndarray | None = None,
    event_date: Any | None = None,
    inflation: float | None = None,
    usdtry_returns: np.ndarray | None = None,
    sector_returns: dict[str, np.ndarray] | None = None,
) -> dict[str, Any]:
    """TCMB faiz kararı için detaylı event study.

    Args:
        rate_actual: Gerçekleşen faiz oranı
        rate_expected: Beklenen faiz oranı
        rate_previous: Önceki faiz oranı
        market_returns: BIST-100 getirileri (event window)
        dates: Tarih dizisi
        event_date: Event tarihi
        inflation: Güncel enflasyon oranı
        usdtry_returns: USDTRY getirileri
        sector_returns: {sector: returns} sektör getirileri

    Returns:
        Dict with surprise, direction, car, sector_breakdown, fx_reaction
    """
    from .car import calculate_car
    from .statistical_test import test_significance

    # Surprise hesapla
    surprise = rate_actual - rate_expected
    surprise_pct = surprise / rate_previous if rate_previous > 0 else 0.0

    # Direction
    if surprise > 0:
        direction = "HAWKISH"
        expected_bist = "NEGATIVE"
    elif surprise < 0:
        direction = "DOVISH"
        expected_bist = "POSITIVE"
    else:
        direction = "NEUTRAL"
        expected_bist = "NEUTRAL"

    # Magnitude
    abs_surprise = abs(surprise_pct)
    if abs_surprise > 0.05:
        impact_level = "VERY_HIGH"
    elif abs_surprise > 0.03:
        impact_level = "HIGH"
    elif abs_surprise > 0.01:
        impact_level = "MEDIUM"
    else:
        impact_level = "LOW"

    # BIST-100 CAR
    mr = np.array(market_returns, dtype=float)
    n = len(mr)
    if n < 3:
        return {
            "surprise": round(surprise, 4),
            "surprise_pct": round(surprise_pct, 4),
            "direction": direction,
            "error": "Yetersiz veri",
        }

    # Market AR (market model: beta=1, alpha=0 → BIST-100 kendi getirisi)
    bist_ar = mr[:n]
    bist_car = calculate_car(bist_ar)

    # İstatistiksel test
    significance = test_significance(bist_car, bist_ar, n_params=2)

    # USDTRY reaksiyonu
    fx_reaction = None
    if usdtry_returns is not None and len(usdtry_returns) > 0:
        fx_ar = np.array(usdtry_returns, dtype=float)[:n]
        fx_car = calculate_car(fx_ar)
        fx_significance = test_significance(fx_car, fx_ar)
        fx_reaction = {
            "usdtry_car": round(fx_car, 4),
            "significant": fx_significance["significant"],
            "direction": "USD_UP" if fx_car > 0 else "USD_DOWN",
        }

    # Sektör breakdown
    sector_breakdown = {}
    if sector_returns:
        for sector, rets in sector_returns.items():
            s_ar = np.array(rets, dtype=float)[:n]
            s_car = calculate_car(s_ar)
            s_sig = test_significance(s_car, s_ar)
            sector_breakdown[sector] = {
                "car": round(s_car, 4),
                "significant": s_sig["significant"],
                "t_statistic": s_sig["t_statistic"],
            }

    result = {
        "event_type": "TCMB_RATE",
        "rate_actual": rate_actual,
        "rate_expected": rate_expected,
        "rate_previous": rate_previous,
        "change": round(rate_actual - rate_previous, 4),
        "surprise": round(surprise, 4),
        "surprise_pct": round(surprise_pct, 4),
        "direction": direction,
        "expected_bist_reaction": expected_bist,
        "impact_level": impact_level,
        "bist_car": round(bist_car, 4),
        "significance": significance,
        "fx_reaction": fx_reaction,
        "sector_breakdown": sector_breakdown,
        "inflation_context": inflation,
        "consistency": _check_rate_inflation_consistency(rate_actual, inflation),
    }

    logger.info(
        "tcmb_event_analyzed",
        surprise=surprise,
        direction=direction,
        bist_car=bist_car,
        significant=significance["significant"],
    )

    return result


def analyze_macro_event(
    event_type: str,
    actual: float,
    expected: float,
    previous: float,
    market_returns: np.ndarray,
    usdtry_returns: np.ndarray | None = None,
) -> dict[str, Any]:
    """Genel makro event analizi.

    Args:
        event_type: Event tipi (INFLATION, GDP, CPI, PPI, CURRENT_ACCOUNT, etc.)
        actual: Gerçekleşen değer
        expected: Beklenen değer
        previous: Önceki değer
        market_returns: BIST-100 getirileri
        usdtry_returns: USDTRY getirileri

    Returns:
        Dict with surprise, direction, car, significance
    """
    from .car import calculate_car
    from .statistical_test import test_significance

    config = MACRO_EVENT_TYPES.get(event_type, MACRO_EVENT_TYPES["INFLATION"])

    # Surprise
    surprise = actual - expected
    change = actual - previous
    surprise_pct = surprise / previous if previous != 0 else 0.0

    # Direction (makro veri için yön mantığı farklı)
    if event_type in ["INFLATION", "CPI", "PPI", "CURRENT_ACCOUNT", "UNEMPLOYMENT"]:
        # Yüksek kötü, düşük iyi
        direction = "NEGATIVE_SURPRISE" if surprise > 0 else "POSITIVE_SURPRISE"
        expected_bist = "NEGATIVE" if surprise > 0 else "POSITIVE"
    elif event_type in ["GDP", "INDUSTRIAL_PRODUCTION"]:
        # Yüksek iyi, düşük kötü
        direction = "POSITIVE_SURPRISE" if surprise > 0 else "NEGATIVE_SURPRISE"
        expected_bist = "POSITIVE" if surprise > 0 else "NEGATIVE"
    else:
        direction = "NEUTRAL"
        expected_bist = "NEUTRAL"

    # BIST CAR
    mr = np.array(market_returns, dtype=float)
    n = len(mr)
    bist_car = calculate_car(mr[:n]) if n > 0 else 0.0
    significance = test_significance(bist_car, mr[:n]) if n > 2 else {"significant": False}

    # USDTRY
    fx_car = 0.0
    if usdtry_returns is not None and len(usdtry_returns) > 0:
        fx_car = calculate_car(np.array(usdtry_returns, dtype=float)[:n])

    # Impact level
    abs_surprise_pct = abs(surprise_pct)
    if abs_surprise_pct > 0.10:
        impact_level = "VERY_HIGH"
    elif abs_surprise_pct > 0.05:
        impact_level = "HIGH"
    elif abs_surprise_pct > 0.02:
        impact_level = "MEDIUM"
    else:
        impact_level = "LOW"

    return {
        "event_type": event_type,
        "event_name": config["name"],
        "actual": actual,
        "expected": expected,
        "previous": previous,
        "change": round(change, 4),
        "surprise": round(surprise, 4),
        "surprise_pct": round(surprise_pct, 4),
        "direction": direction,
        "expected_bist_reaction": expected_bist,
        "impact_level": impact_level,
        "bist_car": round(bist_car, 4),
        "usdtry_car": round(fx_car, 4),
        "significance": significance,
    }


def analyze_macro_events_batch(
    events: list[dict[str, Any]],
    market_returns: np.ndarray,
    usdtry_returns: np.ndarray | None = None,
) -> dict[str, Any]:
    """Birden fazla makro event için toplu analiz.

    Args:
        events: [{event_type, actual, expected, previous}]
        market_returns: BIST-100 getirileri
        usdtry_returns: USDTRY getirileri

    Returns:
        Dict with individual results and summary
    """
    results = []
    for event in events:
        result = analyze_macro_event(
            event_type=event["event_type"],
            actual=event["actual"],
            expected=event["expected"],
            previous=event["previous"],
            market_returns=market_returns,
            usdtry_returns=usdtry_returns,
        )
        results.append(result)

    # Özet
    cars = [r["bist_car"] for r in results]
    mean_car = float(np.mean(cars)) if cars else 0.0

    return {
        "individual_results": results,
        "summary": {
            "n_events": len(results),
            "mean_bist_car": round(mean_car, 4),
            "n_significant": sum(1 for r in results if r.get("significance", {}).get("significant", False)),
            "n_positive_surprise": sum(1 for r in results if "POSITIVE" in r.get("direction", "")),
            "n_negative_surprise": sum(1 for r in results if "NEGATIVE" in r.get("direction", "")),
        },
    }


def _check_rate_inflation_consistency(rate: float, inflation: float | None) -> str:
    """Faiz-enflasyon tutarlılığı kontrolü."""
    if inflation is None:
        return "UNKNOWN"

    real_rate = rate - inflation
    if real_rate > 2:
        return "TIGHT"  # Sıkı para politikası
    elif real_rate > 0:
        return "NEUTRAL"
    elif real_rate > -2:
        return "LOOSE"  # Gevşek para politikası
    else:
        return "VERY_LOOSE"  # Çok gevşek
