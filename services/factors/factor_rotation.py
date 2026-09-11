"""ALPHA BIST — Factor Rotation Strategy.

Rejime göre faktör rotasyonu, momentum-based rotation, dynamic weighting.
Piyasa volatilitesi ve trendi bazlı rejim tespiti ile faktör ağırlıklandırması.
"""

from __future__ import annotations

import math
from types import MappingProxyType
from typing import Any

import numpy as np
import numpy.typing as npt
import structlog

logger = structlog.get_logger(__name__)

__all__ = [
    "detect_regime",
    "get_rotation_weights",
    "calculate_rotation_signal",
    "REGIME_FACTOR_MAP",
]

# --- Sabitler (magic number yok) ---

_MIN_DENOMINATOR: float = 1e-6
_DRAWDOWN_BEAR_THRESHOLD: float = -0.15
_DRAWDOWN_CONFIDENCE_DIVISOR: float = 0.3
_VOL_RATIO_HIGH_THRESHOLD: float = 1.5
_VOL_RATIO_CONFIDENCE_DIVISOR: float = 2.0
_TREND_BULL_THRESHOLD: float = 0.10
_TREND_BULL_CONFIDENCE_DIVISOR: float = 0.2
_TREND_SIDEWAYS_THRESHOLD: float = 0.05
_SIGNAL_SPREAD_ACTIVE: float = 0.02
_SIGNAL_SPREAD_FAVOR: float = 0.01
_MIN_WINDOW_SIZE: int = 1

# Rejim-faktör eşleştirmesi — immutable
REGIME_FACTOR_MAP: MappingProxyType[str, dict[str, Any]] = MappingProxyType({
    "BULL": MappingProxyType({
        "preferred": ("momentum", "size", "bist_specific"),
        "avoid": ("low_vol", "dividend"),
        "description": "Yükseliş: momentum ve büyüme faktörleri öne çıkar",
    }),
    "BEAR": MappingProxyType({
        "preferred": ("quality", "low_vol", "dividend", "leverage"),
        "avoid": ("momentum", "size"),
        "description": "Düşüş: kalite ve defansif faktörleri öne çıkar",
    }),
    "SIDEWAYS": MappingProxyType({
        "preferred": ("value", "dividend", "quality"),
        "avoid": ("momentum",),
        "description": "Yatay: value ve temettü faktörleri öne çıkar",
    }),
    "HIGH_VOL": MappingProxyType({
        "preferred": ("low_vol", "quality", "leverage"),
        "avoid": ("momentum", "size"),
        "description": "Yüksek volatilite: düşük vol ve kalite faktörleri öne çıkar",
    }),
    "NORMAL": MappingProxyType({
        "preferred": (),
        "avoid": (),
        "description": "Normal: eşit ağırlık",
    }),
})


def _safe_float_array(values: Any, name: str = "unknown") -> npt.NDArray[np.float64]:
    """Değerleri güvenli float64 array'e çevirir; None, NaN, Inf temizler.

    Args:
        values: Dönüştürülecek değerler (list, array veya None).
        name: Loglama için alan adı.

    Returns:
        Temizlenmiş float64 numpy array.

    Raises:
        TypeError: values None ise.
        ValueError: values boş ise.
    """
    if values is None:
        raise TypeError(f"{name} parametresi None olamaz")
    arr = np.array(values, dtype=float)
    if arr.size == 0:
        raise ValueError(f"{name} parametresi boş olamaz")

    nan_count = int(np.isnan(arr).sum())
    inf_count = int(np.isinf(arr).sum())
    if nan_count > 0 or inf_count > 0:
        logger.warning(
            "rotation_dirty_values",
            field=name,
            nan_count=nan_count,
            inf_count=inf_count,
            action="replaced_with_zero",
        )
        arr = np.nan_to_num(arr, nan=0.0, posinf=0.0, neginf=0.0)

    return arr


def _clamp(value: float, min_val: float, max_val: float) -> float:
    """Değeri [min_val, max_val] aralığına sıkıştırır.

    Args:
        value: Sıkıştırılacak değer.
        min_val: Alt sınır.
        max_val: Üst sınır.

    Returns:
        Sıkıştırılmış değer.
    """
    return max(min_val, min(value, max_val))


def detect_regime(
    market_returns: list[float] | None,
    volatility_window: int = 20,
    trend_window: int = 60,
) -> dict[str, Any]:
    """Piyasa rejimini tespit et.

    Volatilite oranı ve trend yönüne göre piyasa rejimini belirler:
    BULL, BEAR, SIDEWAYS, HIGH_VOL veya NORMAL.

    Args:
        market_returns: Piyasa getiri serisi. None olamaz.
        volatility_window: Volatilite penceresi (pozitif tamsayı olmalı).
        trend_window: Trend penceresi (pozitif tamsayı olmalı).

    Returns:
        Dict with regime, confidence, metrics, description.

    Raises:
        TypeError: market_returns None ise.
        ValueError: market_returns boş ise veya pencereler pozitif değilse.
    """
    # --- Input validation (Rule 3: Fail-Closed) ---
    if market_returns is None:
        raise TypeError("market_returns parametresi None olamaz")
    if not isinstance(volatility_window, int) or volatility_window < _MIN_WINDOW_SIZE:
        raise ValueError(
            f"volatility_window pozitif tamsayı olmalı, alınan: {volatility_window}"
        )
    if not isinstance(trend_window, int) or trend_window < _MIN_WINDOW_SIZE:
        raise ValueError(
            f"trend_window pozitif tamsayı olmalı, alınan: {trend_window}"
        )

    try:
        r = _safe_float_array(market_returns, name="market_returns")
    except (TypeError, ValueError) as exc:
        logger.error("regime_detection_array_failed", error=str(exc))
        raise

    n = len(r)

    if n < trend_window:
        logger.warning(
            "regime_insufficient_data",
            data_length=n,
            required=trend_window,
        )
        return {
            "regime": "NORMAL",
            "confidence": 0.0,
            "error": f"Yetersiz veri: {n} gözlem, en az {trend_window} gerekli",
            "metrics": {},
            "description": REGIME_FACTOR_MAP["NORMAL"]["description"],
        }

    # Volatilite (yıllıklandırılmış)
    recent_vol = float(np.std(r[-volatility_window:]) * np.sqrt(252))
    historical_vol = float(np.std(r) * np.sqrt(252))

    # Trend
    recent_return = float(np.sum(r[-trend_window:]))
    cumulative = np.cumprod(1 + r)
    peak = np.maximum.accumulate(cumulative)
    # Sıfıra bölmeyi önle
    safe_peak = np.where(peak == 0, 1.0, peak)
    drawdown = (cumulative - peak) / safe_peak
    current_drawdown = float(drawdown[-1])

    # Rejim tespiti
    vol_ratio = recent_vol / max(historical_vol, _MIN_DENOMINATOR)

    if current_drawdown < _DRAWDOWN_BEAR_THRESHOLD:
        regime = "BEAR"
        confidence = _clamp(abs(current_drawdown) / _DRAWDOWN_CONFIDENCE_DIVISOR, 0.0, 1.0)
    elif vol_ratio > _VOL_RATIO_HIGH_THRESHOLD:
        regime = "HIGH_VOL"
        confidence = _clamp(vol_ratio / _VOL_RATIO_CONFIDENCE_DIVISOR, 0.0, 1.0)
    elif recent_return > _TREND_BULL_THRESHOLD:
        regime = "BULL"
        confidence = _clamp(recent_return / _TREND_BULL_CONFIDENCE_DIVISOR, 0.0, 1.0)
    elif abs(recent_return) < _TREND_SIDEWAYS_THRESHOLD:
        regime = "SIDEWAYS"
        confidence = 1.0 - abs(recent_return) / _TREND_SIDEWAYS_THRESHOLD
    else:
        regime = "NORMAL"
        confidence = 0.5

    logger.info(
        "regime_detected",
        regime=regime,
        confidence=round(confidence, 2),
        vol_ratio=round(vol_ratio, 2),
        current_drawdown=round(current_drawdown, 4),
    )

    return {
        "regime": regime,
        "confidence": round(confidence, 2),
        "metrics": {
            "recent_volatility": round(recent_vol, 4),
            "historical_volatility": round(historical_vol, 4),
            "vol_ratio": round(vol_ratio, 2),
            "recent_return": round(recent_return, 4),
            "current_drawdown": round(current_drawdown, 4),
        },
        "description": REGIME_FACTOR_MAP[regime]["description"],
    }


def get_rotation_weights(
    regime: str | None,
    current_weights: dict[str, float] | None = None,
    rotation_strength: float = 0.5,
) -> dict[str, float]:
    """Rejime göre faktör ağırlıklarını döndür.

    Mevcut ağırlıklar ile hedef rejim ağırlıklarını rotation_strength
    oranında karıştırarak yeni ağırlık vektörü oluşturur.

    Args:
        regime: Tespit edilen rejim (BULL/BEAR/SIDEWAYS/HIGH_VOL/NORMAL).
        current_weights: Mevcut faktör ağırlıkları (opsiyonel).
        rotation_strength: Rotasyon gücü (0-1). 0 = mevcut korunur, 1 = tam rotasyon.

    Returns:
        Normalize edilmiş yeni faktör ağırlıkları.

    Raises:
        TypeError: regime None ise.
        ValueError: regime geçersiz bir değerse veya rotation_strength aralık dışıysa.
    """
    if regime is None:
        raise TypeError("regime parametresi None olamaz")
    if not isinstance(regime, str):
        raise TypeError(f"regime str olmalı, alınan tip: {type(regime).__name__}")
    if regime not in REGIME_FACTOR_MAP:
        raise ValueError(
            f"Geçersiz rejim: '{regime}'. Geçerli değerler: {sorted(REGIME_FACTOR_MAP.keys())}"
        )
    if not isinstance(rotation_strength, (int, float)):
        raise TypeError(
            f"rotation_strength sayı olmalı, alınan tip: {type(rotation_strength).__name__}"
        )
    rotation_strength = _clamp(float(rotation_strength), 0.0, 1.0)

    from .fama_french import get_factor_weights

    base = current_weights if current_weights is not None else get_factor_weights("NORMAL")
    target = get_factor_weights(regime)

    # Rotasyon gücüne göre ağırlık karışımı
    new_weights: dict[str, float] = {}
    all_factors = set(list(base.keys()) + list(target.keys()))
    for factor in all_factors:
        base_w = base.get(factor, 0.0)
        target_w = target.get(factor, 0.0)
        new_weights[factor] = base_w + (target_w - base_w) * rotation_strength

    # Normalize — sıfıra bölmeyi önle
    total = sum(new_weights.values())
    if total > _MIN_DENOMINATOR:
        new_weights = {k: v / total for k, v in new_weights.items()}
    else:
        logger.warning("rotation_weights_zero_total", regime=regime, total=total)

    logger.info(
        "rotation_weights_calculated",
        regime=regime,
        rotation_strength=rotation_strength,
        n_factors=len(new_weights),
    )

    return new_weights


def calculate_rotation_signal(
    factor_performance: dict[str, float] | None,
    lookback_periods: int = 20,
) -> dict[str, Any]:
    """Faktör momentum sinyali — hangi faktörler performans gösteriyor.

    Faktör getirilerini sıralayarak üst/alt üçüncüleri belirler ve
    rotasyon sinyali üretir.

    Args:
        factor_performance: {factor_name: recent_return} sözlüğü. None olamaz.
        lookback_periods: Geriye bakış periyodu (bilgi amaçlı, sıralama için kullanılmaz).

    Returns:
        Dict with rotation_signal, top_factors, bottom_factors, spread.

    Raises:
        TypeError: factor_performance None veya dict değilse.
    """
    if factor_performance is None:
        raise TypeError("factor_performance parametresi None olamaz")
    if not isinstance(factor_performance, dict):
        raise TypeError(
            f"factor_performance dict olmalı, alınan tip: {type(factor_performance).__name__}"
        )

    if not factor_performance:
        logger.warning("rotation_empty_performance")
        return {
            "rotation_signal": "NEUTRAL",
            "top_factors": [],
            "bottom_factors": [],
            "spread": 0.0,
        }

    # Değerlerin güvenli float olduğundan emin ol
    clean_performance: dict[str, float] = {}
    for name, ret in factor_performance.items():
        try:
            val = float(ret)
            if math.isnan(val) or math.isinf(val):
                logger.warning("rotation_nan_inf_factor", factor=name, value=ret, action="skipped")
                continue
            clean_performance[name] = val
        except (ValueError, TypeError) as exc:
            logger.warning("rotation_invalid_factor_value", factor=name, value=ret, error=str(exc))
            continue

    if not clean_performance:
        logger.warning("rotation_all_factors_invalid")
        return {
            "rotation_signal": "NEUTRAL",
            "top_factors": [],
            "bottom_factors": [],
            "spread": 0.0,
        }

    # Sırala (yüksek getiri → düşük getiri)
    sorted_factors = sorted(clean_performance.items(), key=lambda x: x[1], reverse=True)

    n = len(sorted_factors)
    top_n = max(n // 3, 1)
    bottom_n = max(n // 3, 1)

    top_factors = [{"factor": name, "return": round(ret, 4)} for name, ret in sorted_factors[:top_n]]
    bottom_factors = [{"factor": name, "return": round(ret, 4)} for name, ret in sorted_factors[-bottom_n:]]

    # Rotasyon sinyali
    top_return = float(np.mean([f["return"] for f in top_factors]))
    bottom_return = float(np.mean([f["return"] for f in bottom_factors]))
    spread = top_return - bottom_return

    if top_return > _SIGNAL_SPREAD_ACTIVE and bottom_return < -_SIGNAL_SPREAD_ACTIVE:
        signal = "ACTIVE_ROTATION"
    elif top_return > _SIGNAL_SPREAD_FAVOR:
        signal = "FAVOR_TOP"
    elif bottom_return < -_SIGNAL_SPREAD_FAVOR:
        signal = "AVOID_BOTTOM"
    else:
        signal = "NEUTRAL"

    logger.info(
        "rotation_signal_calculated",
        signal=signal,
        spread=round(spread, 4),
        n_factors=n,
    )

    return {
        "rotation_signal": signal,
        "top_factors": top_factors,
        "bottom_factors": bottom_factors,
        "spread": round(spread, 4),
    }
