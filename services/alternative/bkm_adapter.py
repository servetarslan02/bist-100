"""
ALPHA BIST — BKM Credit Card Adapter v1.0

BKM (Bankalararası Kart Merkezi) kredi kartı harcama verisi.
Aylık raporlar üzerinden feature hesaplama.

Kaynak: https://www.bkm.com.tr

Features:
- cc_total_spend: Toplam harcama (TL)
- cc_transaction_count: Toplam işlem sayısı
- cc_avg_transaction: Ortalama işlem tutarı
- cc_online_ratio: Online harcama oranı
- cc_growth_yoy: Yıllık büyüme
- cc_growth_mom: Aylık büyüme
- cc_sector_growth: Sektörel büyüme
"""

import asyncio
import aiohttp
from typing import Dict, Any, Optional
import structlog

from .base import BaseAdapter

logger = structlog.get_logger()


class BKMAdapter(BaseAdapter):
    """BKM kredi kartı harcama adapter'ı."""

    source_name = "bkm"
    rate_limit = 10

    # Sektör mapping (BIST sektör → BKM sektör)
    SECTOR_MAPPING = {
        "TEKNOLOJI": "technology",
        "BANKACILIK": "banking",
        "PERAKENDE": "retail",
        "SANAYI": "industry",
        "ULAŞTIRMA": "transportation",
        "GIDA": "food",
        "ENERJI": "energy",
        "İNŞAAT": "construction",
        "OTOMOTIV": "automotive",
        "SAGLIK": "healthcare",
    }

    async def collect(self, ticker: str, **kwargs) -> Optional[Dict[str, Any]]:
        """BKM verisi çek.

        Not: BKM herkese açık API sunmaz.
        Gerçek implementasyonda web scraping veya manuel veri yükleme kullanılır.
        Bu adapter demo/mock veri üretir — production'da gerçek veri kaynağına bağlanmalı.
        """
        sector = kwargs.get("sector", "UNKNOWN")

        try:
            # Gerçek implementasyon: BKM web sitesinden scraping
            # data = await self._scrape_bkm()

            # Mock veri — production'da gerçek veri ile değiştirilecek
            data = await self._fetch_bkm_data(ticker, sector)
            return data
        except Exception as e:
            logger.warning("BKM data fetch failed", ticker=ticker, error=str(e))
            return None

    async def _fetch_bkm_data(self, ticker: str, sector: str) -> Dict[str, Any]:
        """BKM verisi çek (mock/placeholder).

        Production'da bu method:
        1. BKM aylık raporunu scrape eder VEYA
        2. BKM API'sından çeker VEYA
        3. Manuel yüklenen CSV/JSON'dan okur
        """
        # Mock data structure — gerçek BKM verisi bu formatta gelmeli
        return {
            "total_spend": 0,  # Gerçek veri buraya gelecek
            "transaction_count": 0,
            "avg_transaction": 0,
            "online_ratio": 0,
            "growth_yoy": 0,
            "growth_mom": 0,
            "sector_growth": 0,
            "foreign_card_ratio": 0,
            "data_source": "placeholder",
            "timestamp": "2026-01-01T00:00:00Z",
        }

    def compute_features(self, data: Dict[str, Any], ticker: str) -> Dict[str, float]:
        """BKM feature'ları hesapla."""
        if not data or data.get("data_source") == "placeholder":
            # Placeholder veri — feature üretme
            return {}

        features = {
            "cc_spend_growth": data.get("growth_yoy", 0),
            "cc_spend_growth_mom": data.get("growth_mom", 0),
            "cc_transaction_count": data.get("transaction_count", 0),
            "cc_avg_transaction": data.get("avg_transaction", 0),
            "cc_online_ratio": data.get("online_ratio", 0),
            "cc_vs_sector": data.get("growth_yoy", 0) - data.get("sector_growth", 0),
            "cc_seasonal_deviation": self._calc_seasonal_dev(data),
            "cc_foreign_ratio": data.get("foreign_card_ratio", 0),
        }

        return features

    def _calc_seasonal_dev(self, data: Dict[str, Any]) -> float:
        """Mevsimsel sapma hesapla."""
        growth = data.get("growth_yoy", 0)
        sector_growth = data.get("sector_growth", 0)
        if sector_growth == 0:
            return 0
        return growth - sector_growth


# Singleton
bkm_adapter = BKMAdapter()
