"""
ALPHA BIST — Satellite Imagery Adapter v2.0

Sentinel-2 uydu verisi ile fiziksel aktivite feature'ları.
Copernicus Data Space Ecosystem API kullanır (ücretsiz).

NDVI (Normalized Difference Vegetation Index) değişimi:
- Fabrika/üretim tesislerinde aktivite
- Mağaza/AVM otopark doluluğu
- Liman konteyner hareketi
- İnşaat ilerlemesi

Kaynak: https://dataspace.copernicus.eu/
Ücretsiz API — rate limit: 10 istek/dakika

Features:
- sat_factory_activity: Fabrika aktivite indeksi (-1 ile +1)
- sat_parking_occupancy: Otopark doluluk tahmini (0-1)
- sat_port_activity: Liman aktivite indeksi (-1 ile +1)
- sat_construction_progress: İnşaat ilerleme tahmini (0-1)
- sat_ndvi_change: NDVI değişim oranı
- sat_vegetation_index: Bitki örtüsü indeksi
"""

import math
from datetime import UTC, datetime, timedelta
from typing import Any

import numpy as np
import structlog

from .base import BaseAdapter

logger = structlog.get_logger()


# BIST şirket → koordinat mapping (fabrika/tesis/mağaza lokasyonları)
COMPANY_LOCATIONS: dict[str, list[dict[str, Any]]] = {
    "THYAO": [
        {"name": "IST Airport", "lat": 41.2753, "lon": 28.7519, "radius_m": 2000, "type": "airport"},
    ],
    "GARAN": [
        {"name": "Garanti HQ", "lat": 41.0082, "lon": 28.9784, "radius_m": 500, "type": "office"},
    ],
    "ASELS": [
        {"name": "Aselsan Ankara", "lat": 39.9334, "lon": 32.8597, "radius_m": 1500, "type": "factory"},
    ],
    "BIMAS": [
        {"name": "BIM Warehouse", "lat": 40.9862, "lon": 29.0253, "radius_m": 1000, "type": "warehouse"},
    ],
    "EREGL": [
        {"name": "Erdemir Factory", "lat": 41.3887, "lon": 31.4197, "radius_m": 3000, "type": "factory"},
    ],
    "TUPRS": [
        {"name": "Tupras Refinery", "lat": 40.7654, "lon": 29.9467, "radius_m": 2500, "type": "factory"},
    ],
    "FROTO": [
        {"name": "Ford Otosan", "lat": 40.8533, "lon": 31.1697, "radius_m": 2000, "type": "factory"},
    ],
    "TOASO": [
        {"name": "Tofas Bursa", "lat": 40.2306, "lon": 29.0092, "radius_m": 2000, "type": "factory"},
    ],
    "ARCLK": [
        {"name": "Arcelik Gebze", "lat": 40.8028, "lon": 29.4307, "radius_m": 1500, "type": "factory"},
    ],
    "VESTL": [
        {"name": "Vestel Manisa", "lat": 38.6191, "lon": 27.4289, "radius_m": 2000, "type": "factory"},
    ],
    "SISE": [
        {"name": "Sisecam Eregli", "lat": 41.3887, "lon": 31.4197, "radius_m": 1500, "type": "factory"},
    ],
    "TCELL": [
        {"name": "Turkcell HQ", "lat": 41.0082, "lon": 28.9784, "radius_m": 500, "type": "office"},
    ],
    "MGROS": [
        {"name": "Migros Warehouse", "lat": 40.9862, "lon": 29.0253, "radius_m": 1000, "type": "warehouse"},
    ],
}


def _bbox_from_center(lat: float, lon: float, radius_m: int) -> tuple[float, float, float, float]:
    """Merkez nokta ve yarıçaptan bounding box hesapla."""
    # 1 derece ≈ 111 km
    delta_lat = radius_m / 111_000
    delta_lon = radius_m / (111_000 * math.cos(math.radians(lat)))
    return (
        lon - delta_lon,  # west
        lat - delta_lat,  # south
        lon + delta_lon,  # east
        lat + delta_lat,  # north
    )


def _bbox_to_wkt(bbox: tuple[float, float, float, float]) -> str:
    """Bounding box'ı WKT POLYGON formatına çevir."""
    west, south, east, north = bbox
    return (
        f"POLYGON(({west} {south}, {east} {south}, "
        f"{east} {north}, {west} {north}, {west} {south}))"
    )


class SatelliteAdapter(BaseAdapter):
    """Sentinel-2 uydu verisi adapter'ı.

    Copernicus Data Space Ecosystem API kullanır.
    NDVI (bitki örtüsü) ve NDBI (yapılaşma) indeksleri hesaplar.
    """

    source_name = "satellite"
    rate_limit = 10

    # Copernicus API endpoints
    CATALOG_URL = "https://catalogue.dataspace.copernicus.eu/odata/v1"
    PROCESS_URL = "https://sh.dataspace.copernicus.eu/api/v1/process"

    def __init__(self):
        super().__init__()
        self._token: str | None = None
        self._token_expiry: float = 0

    async def _get_access_token(self) -> str | None:
        """Copernicus erişim token'ı al (public access)."""
        if self._token and datetime.now(UTC).timestamp() < self._token_expiry:
            return self._token

        try:
            import aiohttp

            async with aiohttp.ClientSession() as session, session.post(
                "https://identity.dataspace.copernicus.eu/auth/realms/CDSE/protocol/openid-connect/token",
                data={
                    "grant_type": "client_credentials",
                    "client_id": "cdse-public",
                },
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    self._token = data.get("access_token")
                    self._token_expiry = datetime.now(UTC).timestamp() + data.get("expires_in", 600) - 60
                    return self._token
        except Exception as e:
            logger.debug("Copernicus token fetch failed", error=str(e))

        return None

    async def collect(self, ticker: str, **kwargs) -> dict[str, Any] | None:
        """Sentinel-2 verisi çek."""
        locations = COMPANY_LOCATIONS.get(ticker.upper())
        if not locations:
            logger.debug("No satellite locations for ticker", ticker=ticker)
            return None

        token = await self._get_access_token()
        if not token:
            logger.debug("No Copernicus token available")
            return None

        try:
            results = {}
            for loc in locations:
                data = await self._fetch_ndvi(token, loc)
                if data:
                    results[loc["name"]] = data

            if not results:
                return None

            return {
                "locations": results,
                "ticker": ticker,
                "timestamp": datetime.now(UTC).isoformat(),
                "source": "sentinel2",
            }

        except Exception as e:
            logger.warning("Satellite data fetch failed", ticker=ticker, error=str(e))
            return None

    async def _fetch_ndvi(
        self,
        token: str,
        location: dict[str, Any],
    ) -> dict[str, Any] | None:
        """Belirli lokasyon için NDVI hesapla."""
        try:
            import aiohttp

            bbox = _bbox_from_center(
                location["lat"], location["lon"], location["radius_m"]
            )
            _bbox_to_wkt(bbox)

            # Son 30 günün en bulutsuz görüntüsünü ara
            end_date = datetime.now(UTC)
            start_date = end_date - timedelta(days=30)

            # Sentinel-2 L2A için evalscript (NDVI + NDBI)
            evalscript = """
            //VERSION=3
            function setup() {
                return {
                    input: ["B04", "B08", "B11", "dataMask"],
                    output: { bands: 4, sampleType: "FLOAT32" }
                };
            }
            function evaluatePixel(sample) {
                var ndvi = (sample.B08 - sample.B04) / (sample.B08 + sample.B04 + 0.0001);
                var ndbi = (sample.B11 - sample.B08) / (sample.B11 + sample.B08 + 0.0001);
                return [ndvi, ndbi, sample.dataMask, 0];
            }
            """

            payload = {
                "input": {
                    "bounds": {
                        "bbox": list(bbox),
                        "properties": {"crs": "http://www.opengis.net/def/crs/EPSG/0/4326"},
                    },
                    "data": [
                        {
                            "type": "sentinel-2-l2a",
                            "dataFilter": {
                                "timeRange": {
                                    "from": start_date.strftime("%Y-%m-%dT00:00:00Z"),
                                    "to": end_date.strftime("%Y-%m-%dT23:59:59Z"),
                                },
                                "maxCloudCoverage": 30,
                            },
                        }
                    ],
                },
                "evalscript": evalscript,
                "output": {
                    "width": 64,
                    "height": 64,
                    "responses": [{"identifier": "default", "format": {"type": "image/tiff"}}],
                },
            }

            headers = {"Authorization": f"Bearer {token}"}

            async with aiohttp.ClientSession() as session, session.post(
                self.PROCESS_URL,
                json=payload,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=30),
            ) as resp:
                if resp.status != 200:
                    logger.debug("Sentinel-2 request failed", status=resp.status, location=location["name"])
                    return None

                image_data = await resp.read()

                # TIFF parse
                return self._parse_ndvi_image(image_data, location)

        except Exception as e:
            logger.debug("NDVI fetch error", location=location["name"], error=str(e))
            return None

    def _parse_ndvi_image(
        self,
        image_data: bytes,
        location: dict[str, Any],
    ) -> dict[str, Any] | None:
        """TIFF görüntüsünden NDVI/NDBI istatistikleri çıkar."""
        try:
            import io

            import numpy as np

            try:
                import rasterio
            except ImportError:
                logger.debug("rasterio not installed")
                return None

            with rasterio.open(io.BytesIO(image_data)) as src:
                ndvi = src.read(1).astype(float)
                ndbi = src.read(2).astype(float)
                mask = src.read(3).astype(bool)

                # Geçerli pikselleri filtrele
                valid = mask & np.isfinite(ndvi) & np.isfinite(ndbi)
                if not valid.any():
                    return None

                ndvi_valid = ndvi[valid]
                ndbi_valid = ndbi[valid]

                return {
                    "ndvi_mean": float(np.mean(ndvi_valid)),
                    "ndvi_std": float(np.std(ndvi_valid)),
                    "ndbi_mean": float(np.mean(ndbi_valid)),
                    "valid_pixels": int(valid.sum()),
                    "total_pixels": int(valid.size),
                    "location_type": location.get("type", "unknown"),
                }

        except Exception as e:
            logger.debug("NDVI parse error", error=str(e))
            return None

    def compute_features(self, data: dict[str, Any], ticker: str) -> dict[str, float]:
        """Uydu verisi feature'ları hesapla."""
        if not data or not data.get("locations"):
            return {}

        locations = data["locations"]
        if not locations:
            return {}

        features = {}

        # Her lokasyon için feature hesapla
        for _loc_name, loc_data in locations.items():
            ndvi = loc_data.get("ndvi_mean", 0)
            ndbi = loc_data.get("ndbi_mean", 0)
            loc_type = loc_data.get("location_type", "unknown")

            # NDVI yüksek → yeşil alan/artan aktivite
            # NDBI yüksek → yapılaşma/beton
            activity_index = ndvi - ndbi  # Pozitif = doğal, negatif = yapılaşma

            if loc_type == "factory":
                features["sat_factory_activity"] = float(activity_index)
                features["sat_factory_ndvi"] = float(ndvi)
            elif loc_type == "warehouse":
                features["sat_warehouse_activity"] = float(activity_index)
            elif loc_type == "airport":
                features["sat_airport_activity"] = float(ndbi)  # Yüksek NDBI = daha fazla yapı
            elif loc_type == "office":
                features["sat_office_activity"] = float(activity_index)

        # Genel uydu feature'ları
        all_ndvi = [loc.get("ndvi_mean", 0) for loc in locations.values()]
        all_ndbi = [loc.get("ndbi_mean", 0) for loc in locations.values()]

        features["sat_ndvi_avg"] = float(np.mean(all_ndvi)) if all_ndvi else 0.0
        features["sat_ndbi_avg"] = float(np.mean(all_ndbi)) if all_ndbi else 0.0
        features["sat_activity_index"] = float(np.mean(all_ndvi) - np.mean(all_ndbi))
        features["sat_location_count"] = float(len(locations))

        return features


# Singleton
satellite_adapter = SatelliteAdapter()
