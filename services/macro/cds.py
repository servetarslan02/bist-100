"""
ALPHA BIST — CDS Features v2.0

CDS spread feature'ları:
- cds_5y: 5 yıllık CDS
- cds_change: CDS değişim
- cds_zscore: Z-score
- risk_level: Risk seviyesi (düşük/orta/yüksek/çok yüksek)
"""

from typing import Dict, Any
import numpy as np
import structlog

logger = structlog.get_logger()


def compute_cds_features(cds_data: Dict[str, Any]) -> Dict[str, float]:
    """CDS spread feature'ları.

    Args:
        cds_data: {
            "cds_5y": float,           # 5 yıllık CDS
            "cds_previous": float,     # Önceki CDS
            "cds_history": List[float], # Son 20+ gün
        }

    Returns:
        Feature dictionary
    """
    features = {}

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
                mean = np.mean(hist[-60:])
                std = np.std(hist[-60:])
                if std > 0:
                    features["cds_zscore"] = round((cds_5y - mean) / std, 4)

                # Momentum (20 gün)
                if len(hist) >= 20:
                    features["cds_momentum_20d"] = round((cds_5y / hist[-20] - 1) * 100, 2)

                # Percentile
                percentile = sum(1 for v in hist if v <= cds_5y) / len(hist)
                features["cds_percentile"] = round(percentile, 4)

        # Risk seviyesi
        if cds_5y < 150:
            features["cds_risk_level"] = 0.0  # DÜŞÜK
        elif cds_5y < 250:
            features["cds_risk_level"] = 1.0  # ORTA
        elif cds_5y < 400:
            features["cds_risk_level"] = 2.0  # YÜKSEK
        else:
            features["cds_risk_level"] = 3.0  # ÇOK YÜKSEK

    except Exception as e:
        logger.error("CDS feature computation failed", error=str(e))

    return features
