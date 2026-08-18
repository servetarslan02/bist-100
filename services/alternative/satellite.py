"""
ALPHA BIST — Satellite Data Features v2.0

Uydu verisi feature'ları.

Features:
- factory_traffic_change: Fabrika trafiği değişim
- store_traffic_change: Mağaza trafiği değişim
- parking_lot_occupancy: Otopark doluluk oranı
- port_activity: Liman aktivite indeksi
- construction_progress: İnşaat ilerleme oranı
"""

from typing import Dict, Any
import structlog

logger = structlog.get_logger()


def compute_satellite_features(sat_data: Dict[str, Any], ticker: str) -> Dict[str, float]:
    """Uydu verisi feature'ları."""
    features = {}

    if not sat_data:
        return features

    features["factory_traffic_change"] = sat_data.get("factory_traffic", 0)
    features["store_traffic_change"] = sat_data.get("store_traffic", 0)
    features["parking_lot_occupancy"] = sat_data.get("parking_occupancy", 0)
    features["port_activity"] = sat_data.get("port_activity", 0)
    features["construction_progress"] = sat_data.get("construction_progress", 0)

    return features
