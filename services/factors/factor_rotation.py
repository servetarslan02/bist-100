"""ALPHA BIST — Factor Rotation Strategy.

Rejime göre faktör rotasyonu, momentum-based rotation, dynamic weighting.
"""
from typing import Any

import numpy as np
import structlog

logger = structlog.get_logger()

# Rejim-faktör eşleştirmesi
REGIME_FACTOR_MAP = {
    "BULL": {
        "preferred": ["momentum", "size", "bist_specific"],
        "avoid": ["low_vol", "dividend"],
        "description": "Yükseliş: momentum ve büyüme faktörleri öne çıkar",
    },
    "BEAR": {
        "preferred": ["quality", "low_vol", "dividend", "leverage"],
        "avoid": ["momentum", "size"],
        "description": "Düşüş: kalite ve defansif faktörler öne çıkar",
    },
    "SIDEWAYS": {
        "preferred": ["value", "dividend", "quality"],
        "avoid": ["momentum"],
        "description": "Yatay: value ve temettü faktörleri öne çıkar",
    },
    "HIGH_VOL": {
        "preferred": ["low_vol", "quality", "leverage"],
        "avoid": ["momentum", "size"],
        "description": "Yüksek volatilite: düşük vol ve kalite faktörleri öne çıkar",
    },
    "NORMAL": {
        "preferred": [],
        "avoid": [],
        "description": "Normal: eşit ağırlık",
    },
}


def detect_regime(
    market_returns: list[float],
    volatility_window: int = 20,
    trend_window: int = 60,
) -> dict[str, Any]:
    """Piyasa rejimini tespit et.

    Args:
        market_returns: Piyasa getiri serisi
        volatility_window: Volatilite penceresi
        trend_window: Trend penceresi

    Returns:
        Dict with regime, confidence, metrics
    """
    r = np.array(market_returns, dtype=float)
    n = len(r)

    if n < trend_window:
        return {"regime": "NORMAL", "confidence": 0.0, "error": "Insufficient data"}

    # Volatilite
    recent_vol = float(np.std(r[-volatility_window:]) * np.sqrt(252))
    historical_vol = float(np.std(r) * np.sqrt(252))

    # Trend
    recent_return = float(np.sum(r[-trend_window:]))
    cumulative = np.cumprod(1 + r)
    drawdown = (cumulative - np.maximum.accumulate(cumulative)) / np.maximum.accumulate(cumulative)
    current_drawdown = float(drawdown[-1])

    # Rejim tespiti
    vol_ratio = recent_vol / max(historical_vol, 0.001)

    if current_drawdown < -0.15:
        regime = "BEAR"
        confidence = min(abs(current_drawdown) / 0.3, 1.0)
    elif vol_ratio > 1.5:
        regime = "HIGH_VOL"
        confidence = min(vol_ratio / 2.0, 1.0)
    elif recent_return > 0.10:
        regime = "BULL"
        confidence = min(recent_return / 0.2, 1.0)
    elif abs(recent_return) < 0.05:
        regime = "SIDEWAYS"
        confidence = 1.0 - abs(recent_return) / 0.05
    else:
        regime = "NORMAL"
        confidence = 0.5

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
    regime: str,
    current_weights: dict[str, float] | None = None,
    rotation_strength: float = 0.5,
) -> dict[str, float]:
    """Rejime göre faktör ağırlıklarını döndür.

    Args:
        regime: Tespit edilen rejim
        current_weights: Mevcut ağırlıklar
        rotation_strength: Rotasyon gücü (0-1, 0 = mevcut korunur, 1 = tam rotasyon)

    Returns:
        Yeni faktör ağırlıkları
    """
    from .fama_french import get_factor_weights

    base = current_weights or get_factor_weights("NORMAL")
    target = get_factor_weights(regime)

    # Rotasyon gücüne göre ağırlık karışımı
    new_weights = {}
    for factor in set(list(base.keys()) + list(target.keys())):
        base_w = base.get(factor, 0)
        target_w = target.get(factor, 0)
        new_weights[factor] = base_w + (target_w - base_w) * rotation_strength

    # Normalize
    total = sum(new_weights.values())
    if total > 0:
        new_weights = {k: v / total for k, v in new_weights.items()}

    return new_weights


def calculate_rotation_signal(
    factor_performance: dict[str, float],
    lookback_periods: int = 20,
) -> dict[str, Any]:
    """Faktör momentum sinyali — hangi faktörler performans gösteriyor.

    Args:
        factor_performance: {factor_name: recent_return}
        lookback_periods: Geriye bakış periyodu

    Returns:
        Dict with top_factors, bottom_factors, rotation_signal
    """
    if not factor_performance:
        return {"rotation_signal": "NEUTRAL", "top_factors": [], "bottom_factors": []}

    # Sırala
    sorted_factors = sorted(factor_performance.items(), key=lambda x: x[1], reverse=True)

    n = len(sorted_factors)
    top_n = max(n // 3, 1)
    bottom_n = max(n // 3, 1)

    top_factors = [{"factor": name, "return": round(ret, 4)} for name, ret in sorted_factors[:top_n]]
    bottom_factors = [{"factor": name, "return": round(ret, 4)} for name, ret in sorted_factors[-bottom_n:]]

    # Rotasyon sinyali
    top_return = np.mean([f["return"] for f in top_factors])
    bottom_return = np.mean([f["return"] for f in bottom_factors])

    if top_return > 0.02 and bottom_return < -0.02:
        signal = "ACTIVE_ROTATION"
    elif top_return > 0.01:
        signal = "FAVOR_TOP"
    elif bottom_return < -0.01:
        signal = "AVOID_BOTTOM"
    else:
        signal = "NEUTRAL"

    return {
        "rotation_signal": signal,
        "top_factors": top_factors,
        "bottom_factors": bottom_factors,
        "spread": round(float(top_return - bottom_return), 4),
    }
