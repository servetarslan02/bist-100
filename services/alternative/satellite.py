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

from typing import Any

import structlog

logger = structlog.get_logger()


def compute_satellite_features(sat_data: dict[str, Any], ticker: str) -> dict[str, float]:
    """Uydu verisi feature'ları."""
    features = {}

    if not sat_data:
        return features

    key_feature_map = {
        "factory_traffic": "factory_traffic_change",
        "store_traffic": "store_traffic_change",
        "parking_occupancy": "parking_lot_occupancy",
        "port_activity": "port_activity",
        "construction_progress": "construction_progress",
    }
    for key, feature_name in key_feature_map.items():
        value = sat_data.get(key)
        if value is not None:
            features[feature_name] = value

    return features
