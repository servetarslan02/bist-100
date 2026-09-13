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
    macro_tilt: dict[str, float] | None = None,
) -> dict[str, float]:
    """Rejime göre faktör ağırlıklarını döndür.

    Mevcut ağırlıklar ile hedef rejim ağırlıklarını rotation_strength
    oranında karıştırarak ve opsiyonel makro eğilim (macro_tilt) çarpanlarını
    uygulayarak yeni ağırlık vektörü oluşturur.

    Args:
        regime: Tespit edilen rejim (BULL/BEAR/SIDEWAYS/HIGH_VOL/NORMAL).
        current_weights: Mevcut faktör ağırlıkları (opsiyonel).
        rotation_strength: Rotasyon gücü (0-1). 0 = mevcut korunur, 1 = tam rotasyon.
        macro_tilt: Opsiyonel makro faktör çarpanları (ör. {"quality": 1.2, "momentum": 0.8}).

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
        blended_w = base_w + (target_w - base_w) * rotation_strength

        # Makro eğilim çarpanı (varsa)
        if macro_tilt and factor in macro_tilt:
            tilt = max(0.0, float(macro_tilt[factor]))
            blended_w *= tilt

        new_weights[factor] = blended_w

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
        macro_tilt_applied=bool(macro_tilt),
        n_factors=len(new_weights),
    )

    return new_weights


def calculate_rotation_signal(
    factor_performance: dict[str, Any] | None,
    lookback_periods: int = 20,
) -> dict[str, Any]:
    """Faktör momentum ve sebat (persistence) sinyali.

    Faktör getirilerini veya zaman serilerini sıralayarak üst/alt dilimleri
    belirler; risk ayarlı getiri (Sharpe/IR) ve otokorelasyon kalıcılığını
    hesaplayarak kurumsal kalitede rotasyon sinyali üretir.

    Args:
        factor_performance: {factor_name: recent_return_or_returns_list} sözlüğü. None olamaz.
        lookback_periods: Geriye bakış periyodu.

    Returns:
        Dict with rotation_signal, top_factors, bottom_factors, spread, persistence_score.

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
            "persistence_score": 0.0,
        }

    # Değerlerin güvenli float veya zaman serisi float array olduğundan emin ol
    clean_metrics: dict[str, dict[str, float]] = {}
    for name, raw_val in factor_performance.items():
        try:
            if isinstance(raw_val, (list, np.ndarray)):
                arr = np.array(raw_val, dtype=float)
                arr = arr[np.isfinite(arr)]
                if len(arr) == 0:
                    continue
                mean_ret = float(np.mean(arr))
                vol = float(np.std(arr)) if len(arr) > 1 else 0.0
                sharpe = mean_ret / max(vol, 1e-6)
                # AR(1) Otokorelasyon / Sebat (Persistence)
                if len(arr) >= 4:
                    autocorr = float(np.corrcoef(arr[:-1], arr[1:])[0, 1])
                    autocorr = 0.0 if np.isnan(autocorr) else autocorr
                else:
                    autocorr = 0.0
                clean_metrics[name] = {
                    "return": mean_ret,
                    "volatility": vol,
                    "sharpe": sharpe,
                    "persistence": autocorr,
                    "score": sharpe if vol > 1e-4 else mean_ret,
                }
            else:
                val = float(raw_val)
                if math.isnan(val) or math.isinf(val):
                    logger.warning("rotation_nan_inf_factor", factor=name, value=raw_val, action="skipped")
                    continue
                clean_metrics[name] = {
                    "return": val,
                    "volatility": 0.0,
                    "sharpe": val,
                    "persistence": 0.5,
                    "score": val,
                }
        except (ValueError, TypeError) as exc:
            logger.warning("rotation_invalid_factor_value", factor=name, value=raw_val, error=str(exc))
            continue

    if not clean_metrics:
        logger.warning("rotation_all_factors_invalid")
        return {
            "rotation_signal": "NEUTRAL",
            "top_factors": [],
            "bottom_factors": [],
            "spread": 0.0,
            "persistence_score": 0.0,
        }

    # Skorlarına göre sırala (yüksek → düşük)
    sorted_factors = sorted(clean_metrics.items(), key=lambda x: x[1]["score"], reverse=True)

    n = len(sorted_factors)
    top_n = max(n // 3, 1)
    bottom_n = max(n // 3, 1)

    top_factors = [
        {
            "factor": name,
            "return": round(m["return"], 4),
            "sharpe": round(m["sharpe"], 4),
            "persistence": round(m["persistence"], 4),
        }
        for name, m in sorted_factors[:top_n]
    ]
    bottom_factors = [
        {
            "factor": name,
            "return": round(m["return"], 4),
            "sharpe": round(m["sharpe"], 4),
            "persistence": round(m["persistence"], 4),
        }
        for name, m in sorted_factors[-bottom_n:]
    ]

    # Rotasyon metrikleri
    top_return = float(np.mean([f["return"] for f in top_factors]))
    bottom_return = float(np.mean([f["return"] for f in bottom_factors]))
    spread = top_return - bottom_return

    avg_persistence = float(np.mean([f["persistence"] for f in top_factors]))

    if top_return > _SIGNAL_SPREAD_ACTIVE and bottom_return < -_SIGNAL_SPREAD_ACTIVE:
        signal = "ACTIVE_ROTATION_STRONG" if avg_persistence > 0.3 else "ACTIVE_ROTATION"
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
        persistence=round(avg_persistence, 4),
        n_factors=n,
    )

    return {
        "rotation_signal": signal,
        "top_factors": top_factors,
        "bottom_factors": bottom_factors,
        "spread": round(spread, 4),
        "persistence_score": round(avg_persistence, 4),
    }
