"""
ALPHA BIST — FX Features v2.0

Döviz kuru feature'ları:
- usdtry: USD/TRY kuru
- eurtry: EUR/TRY kuru
- usdtry_change: Günlük değişim
- usdtry_volatility: Volatilite
- eurtry_usdtry_ratio: EUR/USD paritesi
- usdtry_regime: Kur rejimi (değer kazanma/kayıp/stabil)
"""

from typing import Any

import numpy as np
import structlog

logger = structlog.get_logger()

# Kur momentum rejimi eşik sabitleri (%)
DEFAULT_FX_REGIME_STRONG_WEAKENING: float = 5.0
DEFAULT_FX_REGIME_MILD_WEAKENING: float = 2.0
DEFAULT_FX_REGIME_STRONG_STRENGTHENING: float = -5.0
DEFAULT_FX_REGIME_MILD_STRENGTHENING: float = -2.0


def compute_fx_features(fx_data: dict[str, Any]) -> dict[str, float]:
    """Döviz kuru seviye, momentum, volatilite ve rejim feature'larını hesaplar.

    Args:
        fx_data: USD/TRY, EUR/TRY, önceki USD/TRY ve tarihsel fiyat serisini içeren sözlük.

    Returns:
        dict[str, float]: Hesaplanmış döviz feature sözlüğü.

    Raises:
        ValueError: Sayısal dönüştürme hatası oluştuğunda (yakalanıp loglanır).
    """
    features: dict[str, float] = {}

    try:
        usdtry = fx_data.get("usdtry")
        eurtry = fx_data.get("eurtry")

        if usdtry and float(usdtry) > 0:
            usdtry = float(usdtry)
            features["fx_usdtry_level"] = round(usdtry, 4)

            # Günlük değişim
            usdtry_previous = fx_data.get("usdtry_previous")
            if usdtry_previous and float(usdtry_previous) > 0:
                change = (usdtry / float(usdtry_previous) - 1) * 100
                features["fx_usdtry_change_pct"] = round(change, 4)
                features["fx_usdtry_change_direction"] = 1.0 if change > 0 else (-1.0 if change < 0 else 0.0)

            # History-based features
            history = fx_data.get("usdtry_history", [])
            if isinstance(history, list) and len(history) >= 20:
                hist = np.array(history, dtype=np.float64)
                hist = hist[hist > 0]

                if len(hist) >= 20:
                    # Z-score
                    mean = float(np.mean(hist[-60:]))
                    std = float(np.std(hist[-60:]))
                    if std > 0:
                        features["fx_usdtry_zscore"] = round((usdtry - mean) / std, 4)

                    # Momentum (20 gün)
                    features["fx_usdtry_momentum_20d"] = round((usdtry / hist[-20] - 1) * 100, 2)

                    # Percentile
                    percentile = sum(1 for v in hist if v <= usdtry) / len(hist)
                    features["fx_usdtry_percentile"] = round(percentile, 4)

                    # Volatilite (20 gün)
                    returns = np.diff(np.log(hist[-21:]))
                    features["fx_usdtry_volatility_20d"] = round(float(np.std(returns) * np.sqrt(252) * 100), 2)

                    # Regime
                    momentum = features["fx_usdtry_momentum_20d"]
                    if momentum > DEFAULT_FX_REGIME_STRONG_WEAKENING:
                        features["fx_usdtry_regime"] = 3.0  # TRY zayıflıyor (kuvvetli)
                    elif momentum > DEFAULT_FX_REGIME_MILD_WEAKENING:
                        features["fx_usdtry_regime"] = 2.0  # TRY zayıflıyor (hafif)
                    elif momentum < DEFAULT_FX_REGIME_STRONG_STRENGTHENING:
                        features["fx_usdtry_regime"] = 0.0  # TRY güçleniyor (kuvvetli)
                    elif momentum < DEFAULT_FX_REGIME_MILD_STRENGTHENING:
                        features["fx_usdtry_regime"] = 1.0  # TRY güçleniyor (hafif)
                    else:
                        features["fx_usdtry_regime"] = 1.5  # STABIL

                    # 5 günlük değişim
                    if len(hist) >= 5:
                        features["fx_usdtry_change_5d"] = round((usdtry / hist[-5] - 1) * 100, 2)

        # EUR/TRY
        if eurtry and float(eurtry) > 0:
            features["fx_eurtry_level"] = round(float(eurtry), 4)
            if usdtry and usdtry > 0:
                features["fx_eurtry_usdtry_ratio"] = round(float(eurtry) / usdtry, 4)

    except Exception as e:
        logger.error("Döviz feature hesaplaması başarısız oldu", error=str(e))

    return features


__all__ = [
    "DEFAULT_FX_REGIME_STRONG_WEAKENING",
    "DEFAULT_FX_REGIME_MILD_WEAKENING",
    "DEFAULT_FX_REGIME_STRONG_STRENGTHENING",
    "DEFAULT_FX_REGIME_MILD_STRENGTHENING",
    "compute_fx_features",
]

