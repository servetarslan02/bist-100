"""
ALPHA BIST — Current Account Features v2.0

Cari açık feature'ları:
- ca_balance: Cari denge (milyar USD)
- ca_gdp_ratio: Cari denge/GSYH (%)
- ca_trend: Cari açık trendi
- ca_improving: İyileşiyor mu?
"""

from typing import Any

import structlog

logger = structlog.get_logger()


def compute_ca_features(ca_data: dict[str, Any]) -> dict[str, float]:
    """Cari açık feature'ları.

    Args:
        ca_data: {
            "ca_balance": float,         # Cari denge (milyar USD)
            "ca_gdp_ratio": float,       # Cari denge/GSYH (%)
            "ca_previous": float,        # Önceki denge
            "ca_12m_avg": float,         # 12 aylık ortalama
        }

    Returns:
        Feature dictionary
    """
    features = {}

    try:
        ca_balance = ca_data.get("ca_balance")
        if ca_balance is not None:
            features["ca_balance"] = round(float(ca_balance), 2)

            # Cari açık rejimi
            balance = float(ca_balance)
            if balance > 0:
                features["ca_regime"] = 2.0  # FAZLA
            elif balance > -5:
                features["ca_regime"] = 1.0  # KÜÇÜK AÇIK
            elif balance > -15:
                features["ca_regime"] = 0.0  # ORTA AÇIK
            else:
                features["ca_regime"] = -1.0  # BÜYÜK AÇIK

        # Cari denge/GSYH
        ca_gdp = ca_data.get("ca_gdp_ratio")
        if ca_gdp is not None:
            features["ca_gdp_ratio"] = round(float(ca_gdp), 2)

        # Trend
        ca_previous = ca_data.get("ca_previous")
        if ca_balance is not None and ca_previous is not None:
            trend = float(ca_balance) - float(ca_previous)
            features["ca_trend"] = round(trend, 4)
            features["ca_improving"] = 1.0 if trend > 0 else 0.0

        # 12 aylık ortalama
        ca_12m = ca_data.get("ca_12m_avg")
        if ca_12m is not None:
            features["ca_12m_avg"] = round(float(ca_12m), 2)

    except Exception as e:
        logger.error("Current account feature computation failed", error=str(e))

    return features
