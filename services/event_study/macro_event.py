"""ALPHA BIST — Macro Event Analysis.

TCMB faiz kararı, enflasyon, GSYH, cari açık, USDTRY reaksiyonu.
MacKinlay (1997) metodolojisi ile detaylı makro event study.
"""

from typing import Any

import numpy as np
import structlog

logger = structlog.get_logger()

# --- Sabitler ---
MIN_MARKET_RETURNS: int = 3
MIN_SIGNIFICANCE_RETURNS: int = 3

# Surprise magnitude eşikleri (oran)
SURPRISE_VERY_HIGH: float = 0.05
SURPRISE_HIGH: float = 0.03
SURPRISE_MEDIUM: float = 0.01

# Genel makro surprise eşikleri
MACRO_SURPRISE_VERY_HIGH: float = 0.10
MACRO_SURPRISE_HIGH: float = 0.05
MACRO_SURPRISE_MEDIUM: float = 0.02

# Real rate eşikleri
REAL_RATE_TIGHT: float = 2.0
REAL_RATE_NEUTRAL: float = 0.0
REAL_RATE_LOOSE: float = -2.0

# TCMB parametre validasyonu
RATE_MIN: float = -100.0
RATE_MAX: float = 100.0

# Required keys for batch
REQUIRED_MACRO_EVENT_KEYS: tuple[str, ...] = ("event_type", "actual", "expected", "previous")

# Makro event type konfigürasyonu
MACRO_EVENT_TYPES: dict[str, dict[str, Any]] = {
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


def _validate_float(value: float, name: str) -> float:
    """Float değer için tip ve NaN/Inf kontrolü.

    Args:
        value: Kontrol edilecek değer
        name: Değerin adı (hata mesajı için)

    Returns:
        Doğrulanmış float değer

    Raises:
        TypeError: Sayısal değilse
        ValueError: NaN veya Inf ise
    """
    if not isinstance(value, (int, float, np.integer, np.floating)):
        raise TypeError(f"{name} sayısal olmalı, alınan: {type(value).__name__} ({value})")
    if not np.isfinite(value):
        raise ValueError(f"{name} sonlu değil: {value}")
    return float(value)


def _validate_rate(rate: float, name: str) -> float:
    """Faiz oranı doğrulama.

    Args:
        rate: Kontrol edilecek oran
        name: Parametre adı

    Returns:
        Doğrulanmış float

    Raises:
        TypeError: Sayısal değilse
        ValueError: NaN/Inf ise veya makul aralık dışındaysa
    """
    val = _validate_float(rate, name)
    if not (RATE_MIN <= val <= RATE_MAX):
        raise ValueError(f"{name} [{RATE_MIN}, {RATE_MAX}] aralığında olmalı, alınan: {val}")
    return val


def _validate_market_returns(market_returns: Any, min_size: int = MIN_MARKET_RETURNS) -> np.ndarray:
    """Market getirileri doğrulama.

    Args:
        market_returns: Kontrol edilecek getiri serisi
        min_size: Minimum boyut

    Returns:
        Doğrulanmış numpy array

    Raises:
        TypeError: Desteklenmeyen tip ise
        ValueError: Boş, yetersiz veya NaN/Inf içeriyorsa
    """
    if isinstance(market_returns, (list, tuple)):
        market_returns = np.asarray(market_returns, dtype=float)
    if not isinstance(market_returns, np.ndarray):
        raise TypeError(
            f"market_returns numpy.ndarray, list veya tuple olmalı, alınan: {type(market_returns).__name__}"
        )
    if market_returns.size == 0:
        raise ValueError("market_returns boş olamaz")
    if market_returns.size < min_size:
        raise ValueError(f"market_returns en az {min_size} örneklem içermeli, alınan: {market_returns.size}")
    if not np.all(np.isfinite(market_returns)):
        raise ValueError("market_returns NaN veya Inf değerler içeriyor")
    return market_returns


def _validate_optional_returns(arr: Any | None, name: str) -> np.ndarray | None:
    """Opsiyonel getiri serisi doğrulama (None geçerli).

    Args:
        arr: Kontrol edilecek array veya None
        name: Parametre adı

    Returns:
        Doğrulanmış numpy array veya None

    Raises:
        TypeError: Desteklenmeyen tip ise
        ValueError: NaN/Inf içeriyorsa
    """
    if arr is None:
        return None
    if isinstance(arr, (list, tuple)):
        arr = np.asarray(arr, dtype=float)
    if not isinstance(arr, np.ndarray):
        raise TypeError(f"{name} numpy.ndarray, list veya tuple olmalı, alınan: {type(arr).__name__}")
    if not np.all(np.isfinite(arr)):
        raise ValueError(f"{name} NaN veya Inf değerler içeriyor")
    return arr


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
        idx: Dizideki indeks

    Raises:
        TypeError: Sözlük değilse
        ValueError: Zorunlu key'ler eksikse
    """
    if not isinstance(event, dict):
        raise TypeError(f"events[{idx}] sözlük olmalı, alınan: {type(event).__name__}")
    missing = [k for k in REQUIRED_MACRO_EVENT_KEYS if k not in event]
    if missing:
        raise ValueError(f"events[{idx}] zorunlu key'ler eksik: {missing}")


def _validate_sector_returns(sector_returns: dict[str, Any] | None) -> dict[str, np.ndarray] | None:
    """Sektör getirileri doğrulama.

    Args:
        sector_returns: {sector: returns} sözlüğü veya None

    Returns:
        Doğrulanmış sözlük veya None

    Raises:
        TypeError: Sözlük değilse
        ValueError: Herhangi bir sektör getirisi NaN/Inf içeriyorsa
    """
    if sector_returns is None:
        return None
    if not isinstance(sector_returns, dict):
        raise TypeError(f"sector_returns sözlük olmalı, alınan: {type(sector_returns).__name__}")
    validated: dict[str, np.ndarray] = {}
    for sector, rets in sector_returns.items():
        if isinstance(rets, (list, tuple)):
            rets = np.asarray(rets, dtype=float)
        if not isinstance(rets, np.ndarray):
            raise TypeError(f"sector_returns['{sector}'] numpy.ndarray olmalı")
        if not np.all(np.isfinite(rets)):
            raise ValueError(f"sector_returns['{sector}'] NaN veya Inf değerler içeriyor")
        validated[sector] = rets
    return validated


def _classify_surprise_tcmb(abs_surprise_pct: float) -> str:
    """TCMB surprise magnitude sınıflandırması.

    Args:
        abs_surprise_pct: Mutlak surprise yüzdesi

    Returns:
        Etki seviyesi
    """
    if abs_surprise_pct > SURPRISE_VERY_HIGH:
        return "VERY_HIGH"
    elif abs_surprise_pct > SURPRISE_HIGH:
        return "HIGH"
    elif abs_surprise_pct > SURPRISE_MEDIUM:
        return "MEDIUM"
    return "LOW"


def _classify_surprise_macro(abs_surprise_pct: float) -> str:
    """Genel makro surprise magnitude sınıflandırması.

    Args:
        abs_surprise_pct: Mutlak surprise yüzdesi

    Returns:
        Etki seviyesi
    """
    if abs_surprise_pct > MACRO_SURPRISE_VERY_HIGH:
        return "VERY_HIGH"
    elif abs_surprise_pct > MACRO_SURPRISE_HIGH:
        return "HIGH"
    elif abs_surprise_pct > MACRO_SURPRISE_MEDIUM:
        return "MEDIUM"
    return "LOW"


def _get_macro_direction(event_type: str, surprise: float) -> tuple[str, str]:
    """Makro event yön mantığı.

    Args:
        event_type: Event tipi
        surprise: Surprise değeri

    Returns:
        (direction, expected_bist) tuple'ı
    """
    negative_surprise_types = {"INFLATION", "CPI", "PPI", "CURRENT_ACCOUNT", "UNEMPLOYMENT"}
    positive_surprise_types = {"GDP", "INDUSTRIAL_PRODUCTION"}

    if event_type in negative_surprise_types:
        direction = "NEGATIVE_SURPRISE" if surprise > 0 else "POSITIVE_SURPRISE"
        expected_bist = "NEGATIVE" if surprise > 0 else "POSITIVE"
    elif event_type in positive_surprise_types:
        direction = "POSITIVE_SURPRISE" if surprise > 0 else "NEGATIVE_SURPRISE"
        expected_bist = "POSITIVE" if surprise > 0 else "NEGATIVE"
    else:
        direction = "NEUTRAL"
        expected_bist = "NEUTRAL"
    return direction, expected_bist


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

    Raises:
        TypeError: Parametre tipleri uygun değilse
        ValueError: Değerler sonlu değilse veya veri yetersiz ise
    """
    from .car import calculate_car
    from .statistical_test import test_significance

    # --- Validasyon ---
    rate_actual = _validate_rate(rate_actual, "rate_actual")
    rate_expected = _validate_rate(rate_expected, "rate_expected")
    rate_previous = _validate_rate(rate_previous, "rate_previous")
    mr = _validate_market_returns(market_returns)
    inflation = _validate_float(inflation, "inflation") if inflation is not None else None
    usdtry_returns = _validate_optional_returns(usdtry_returns, "usdtry_returns")
    sector_returns = _validate_sector_returns(sector_returns)

    # Surprise hesapla
    surprise = rate_actual - rate_expected
    # rate_previous == 0 → surprise_pct = 0 (bölme hatası önlenir)
    surprise_pct = surprise / abs(rate_previous) if rate_previous != 0 else 0.0

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
    impact_level = _classify_surprise_tcmb(abs(surprise_pct))

    n = len(mr)

    # Market AR (market model: beta=1, alpha=0 → BIST-100 kendi getirisi)
    bist_ar = mr[:n]
    bist_car = calculate_car(bist_ar)

    # İstatistiksel test
    significance = test_significance(bist_car, bist_ar, n_params=2)

    # USDTRY reaksiyonu
    fx_reaction: dict[str, Any] | None = None
    if usdtry_returns is not None and len(usdtry_returns) > 0:
        fx_ar = usdtry_returns[:n]
        fx_car = calculate_car(fx_ar)
        fx_significance = test_significance(fx_car, fx_ar)
        fx_reaction = {
            "usdtry_car": round(fx_car, 4),
            "significant": fx_significance["significant"],
            "direction": "USD_UP" if fx_car > 0 else "USD_DOWN",
        }

    # Sektör breakdown
    sector_breakdown: dict[str, dict[str, Any]] = {}
    if sector_returns:
        for sector, rets in sector_returns.items():
            s_ar = rets[:n]
            s_car = calculate_car(s_ar)
            s_sig = test_significance(s_car, s_ar)
            sector_breakdown[sector] = {
                "car": round(s_car, 4),
                "significant": s_sig["significant"],
                "t_statistic": s_sig["t_statistic"],
            }

    result: dict[str, Any] = {
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

    logger.debug(
        "tcmb_event_analiz_edildi",
        surprise=round(surprise, 4),
        direction=direction,
        bist_car=round(bist_car, 4),
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

    Raises:
        TypeError: Parametre tipleri uygun değilse
        ValueError: Değerler sonlu değilse
    """
    from .car import calculate_car
    from .statistical_test import test_significance

    # --- Validasyon ---
    if not isinstance(event_type, str):
        raise TypeError(f"event_type string olmalı, alınan: {type(event_type).__name__}")
    actual = _validate_float(actual, "actual")
    expected = _validate_float(expected, "expected")
    previous = _validate_float(previous, "previous")
    mr = _validate_market_returns(market_returns)
    usdtry_returns = _validate_optional_returns(usdtry_returns, "usdtry_returns")

    config = MACRO_EVENT_TYPES.get(event_type)
    if config is None:
        logger.warning(
            "makro_event_bilinmeyen_tip",
            event_type=event_type,
            varsayilan="INFLATION",
        )
        config = MACRO_EVENT_TYPES["INFLATION"]

    # Surprise
    surprise = actual - expected
    change = actual - previous
    surprise_pct = surprise / abs(previous) if previous != 0 else 0.0

    # Direction
    direction, expected_bist = _get_macro_direction(event_type, surprise)

    # BIST CAR
    n = len(mr)
    bist_car = calculate_car(mr[:n])
    significance = test_significance(bist_car, mr[:n]) if n >= MIN_SIGNIFICANCE_RETURNS else {"significant": False}

    # USDTRY
    fx_car = 0.0
    if usdtry_returns is not None and len(usdtry_returns) > 0:
        fx_car = calculate_car(usdtry_returns[:n])

    # Impact level
    impact_level = _classify_surprise_macro(abs(surprise_pct))

    result: dict[str, Any] = {
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

    logger.debug(
        "makro_event_analiz_edildi",
        event_type=event_type,
        surprise=round(surprise, 4),
        direction=direction,
        bist_car=round(bist_car, 4),
    )

    return result


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

    Raises:
        TypeError: Parametre tipleri uygun değilse
        ValueError: Boş liste veya zorunlu key'ler eksikse
    """
    _validate_events_list(events)

    for idx, event in enumerate(events):
        _validate_event_dict(event, idx)

    mr = _validate_market_returns(market_returns)
    usdtry_returns = _validate_optional_returns(usdtry_returns, "usdtry_returns")

    results: list[dict[str, Any]] = []
    for event in events:
        result = analyze_macro_event(
            event_type=event["event_type"],
            actual=event["actual"],
            expected=event["expected"],
            previous=event["previous"],
            market_returns=mr,
            usdtry_returns=usdtry_returns,
        )
        results.append(result)

    # Özet
    cars = [r["bist_car"] for r in results]
    mean_car = round(float(np.mean(cars)), 4)
    n_significant = sum(1 for r in results if r.get("significance", {}).get("significant", False))

    summary: dict[str, Any] = {
        "n_events": len(results),
        "mean_bist_car": mean_car,
        "n_significant": n_significant,
        "n_positive_surprise": sum(1 for r in results if "POSITIVE" in r.get("direction", "")),
        "n_negative_surprise": sum(1 for r in results if "NEGATIVE" in r.get("direction", "")),
    }

    logger.debug(
        "makro_event_toplu_analiz_edildi",
        n_events=summary["n_events"],
        mean_bist_car=mean_car,
        n_significant=n_significant,
    )

    return {
        "individual_results": results,
        "summary": summary,
    }


def _check_rate_inflation_consistency(rate: float, inflation: float | None) -> str:
    """Faiz-enflasyon tutarlılığı kontrolü.

    Args:
        rate: Faiz oranı
        inflation: Enflasyon oranı (None olabilir)

    Returns:
        Tutarlılık etiketi

    Raises:
        TypeError: Sayısal değilse
        ValueError: Sonlu değilse
    """
    if inflation is None:
        return "UNKNOWN"

    rate = _validate_float(rate, "rate")
    inflation = _validate_float(inflation, "inflation")

    real_rate = rate - inflation
    if real_rate > REAL_RATE_TIGHT:
        return "TIGHT"  # Sıkı para politikası
    elif real_rate > REAL_RATE_NEUTRAL:
        return "NEUTRAL"
    elif real_rate > REAL_RATE_LOOSE:
        return "LOOSE"  # Gevşek para politikası
    else:
        return "VERY_LOOSE"  # Çok gevşek
