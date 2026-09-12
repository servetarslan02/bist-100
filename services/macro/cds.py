"""
ALPHA BIST — CDS Features v2.0

CDS spread feature'ları:
- cds_5y: 5 yıllık CDS
- cds_change: CDS değişim
- cds_zscore: Z-score
- risk_level: Risk seviyesi (düşük/orta/yüksek/çok yüksek)
"""

from typing import Any

import numpy as np
import structlog

logger = structlog.get_logger()

# Risk seviyesi eşik sabitleri (baz puan)
DEFAULT_CDS_RISK_LOW: float = 150.0
DEFAULT_CDS_RISK_MEDIUM: float = 250.0
DEFAULT_CDS_RISK_HIGH: float = 400.0


def compute_cds_features(cds_data: dict[str, Any]) -> dict[str, float]:
    """CDS spread göstergelerini ve risk seviyesini hesaplar.

    Args:
        cds_data: 5 yıllık CDS, önceki CDS ve tarihsel CDS listesini içeren sözlük.

    Returns:
        dict[str, float]: Hesaplanmış CDS feature sözlüğü (z-score, momentum, risk level vb.).

    Raises:
        ValueError: Girdi verisi sayısal formata dönüştürülemediğinde (hata yakalanıp loglanır).
    """
    features: dict[str, float] = {}

    try:
        cds_5y = cds_data.get("cds_5y")
        if cds_5y is None:
            return features

        cds_5y = float(cds_5y)
        features["cds_5y"] = round(cds_5y, 2)

        # CDS değişim
        cds_previous = cds_data.get("cds_previous")
        if cds_previous and float(cds_previous) > 0:
            change = (cds_5y / float(cds_previous) - 1) * 100
            features["cds_change_pct"] = round(change, 4)
            features["cds_change_direction"] = 1.0 if change > 0 else (-1.0 if change < 0 else 0.0)

        # History-based features
        history = cds_data.get("cds_history", [])
        if isinstance(history, list) and len(history) >= 10:
            hist = np.array(history, dtype=np.float64)
            hist = hist[hist > 0]

            if len(hist) >= 10:
                # Z-score
                mean = float(np.mean(hist[-60:]))
                std = float(np.std(hist[-60:]))
                if std > 0:
                    features["cds_zscore"] = round((cds_5y - mean) / std, 4)

                # Momentum (20 gün)
                if len(hist) >= 20:
                    features["cds_momentum_20d"] = round((cds_5y / hist[-20] - 1) * 100, 2)

                # Percentile
                percentile = sum(1 for v in hist if v <= cds_5y) / len(hist)
                features["cds_percentile"] = round(percentile, 4)

        # Risk seviyesi
        if cds_5y < DEFAULT_CDS_RISK_LOW:
            features["cds_risk_level"] = 0.0  # DÜŞÜK
        elif cds_5y < DEFAULT_CDS_RISK_MEDIUM:
            features["cds_risk_level"] = 1.0  # ORTA
        elif cds_5y < DEFAULT_CDS_RISK_HIGH:
            features["cds_risk_level"] = 2.0  # YÜKSEK
        else:
            features["cds_risk_level"] = 3.0  # ÇOK YÜKSEK

    except Exception as e:
        logger.error("CDS feature hesaplaması başarısız oldu", error=str(e))

    return features


__all__ = [
    "DEFAULT_CDS_RISK_LOW",
    "DEFAULT_CDS_RISK_MEDIUM",
    "DEFAULT_CDS_RISK_HIGH",
    "compute_cds_features",
]

