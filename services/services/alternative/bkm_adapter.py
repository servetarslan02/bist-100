"""
ALPHA BIST — BKM Credit Card Adapter v2.0

BKM (Bankalararası Kart Merkezi) kredi kartı harcama verisi.
Web scraping ile aylık kart verileri çekme.

Kaynak: https://www.bkm.com.tr/tr-TR/kart-verileri

Features:
- cc_total_spend: Toplam harcama (TL)
- cc_transaction_count: Toplam işlem sayısı
- cc_avg_transaction: Ortalama işlem tutarı
- cc_online_ratio: Online harcama oranı
- cc_growth_yoy: Yıllık büyüme
- cc_growth_mom: Aylık büyüme
- cc_foreign_ratio: Yabancı kart oranı
- cc_contactless_ratio: Temassız ödeme oranı
"""

import asyncio
import re
from typing import Dict, Any, Optional
from datetime import datetime, timezone
import structlog

from .base import BaseAdapter

logger = structlog.get_logger()


class BKMAdapter(BaseAdapter):
    """BKM kredi kartı harcama adapter'ı.

    BKM herkese açık API sunmaz ama aylık kart istatistiklerini
    web sitesinde yayınlar. Bu adapter o sayfayı scrape eder.
    """

    source_name = "bkm"
    rate_limit = 5

    BKM_URL = "https://www.bkm.com.tr/tr-TR/kart-verileri"

    # Sektör mapping (BIST sektör → BKM sektör)
    SECTOR_MAPPING = {
        "TEKNOLOJI": "technology",
        "BANKACILIK": "banking",
        "PERAKENDE": "retail",
        "SANAYI": "industry",
        "ULASTIRMA": "transportation",
        "GIDA": "food",
        "ENERJI": "energy",
        "INSAT": "construction",
        "OTOMOTIV": "automotive",
        "SAGLIK": "healthcare",
    }

    async def collect(self, ticker: str, **kwargs) -> Optional[Dict[str, Any]]:
        """BKM verisi çek — web scraping."""
        try:
            data = await self._scrape_bkm_page()
            if data:
                return data

            # Scrape başarısızsa cached rapor var mı?
            logger.info("BKM scrape returned no data, trying cached report")
            return None

        except Exception as e:
            logger.warning("BKM data fetch failed", ticker=ticker, error=str(e))
            return None

    async def _scrape_bkm_page(self) -> Optional[Dict[str, Any]]:
        """BKM kart verileri sayfasını scrape et."""
        try:
            import aiohttp
            from bs4 import BeautifulSoup

            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "Accept-Language": "tr-TR,tr;q=0.9",
            }

            async with aiohttp.ClientSession() as session:
                async with session.get(
                    self.BKM_URL,
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(total=15),
                ) as resp:
                    if resp.status != 200:
                        logger.warning("BKM page returned non-200", status=resp.status)
                        return None

                    html = await resp.text()
                    return self._parse_bkm_html(html)

        except ImportError:
            logger.warning("beautifulsoup4 not installed")
            return None
        except Exception as e:
            logger.warning("BKM scrape error", error=str(e))
            return None

    def _parse_bkm_html(self, html: str) -> Optional[Dict[str, Any]]:
        """BKM HTML'inden kart verilerini çıkar.

        BKM sayfası genellikle tablo formatında veri sunar:
        - Toplam kart sayısı
        - Toplam işlem adedi
        - Toplam işlem tutarı
        - Online/temassız dağılım
        """
        try:
            from bs4 import BeautifulSoup

            soup = BeautifulSoup(html, "html.parser")
            result = {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "source": "bkm_web",
            }

            # Sayısal verileri ara — tablo veya istatistik kutucukları
            text = soup.get_text(" ", strip=True)

            # Toplam işlem tutarı (milyar TL)
            spend_match = re.search(
                r'(?:toplam|tutar|har[cç]ama)[\s:]*(\d[\d.,]*)\s*(?:milyar|milyon|tl|₺)',
                text, re.IGNORECASE
            )
            if spend_match:
                value = self._parse_turkish_number(spend_match.group(1))
                if "milyar" in text[spend_match.start():spend_match.end() + 20].lower():
                    value *= 1_000_000_000
                elif "milyon" in text[spend_match.start():spend_match.end() + 20].lower():
                    value *= 1_000_000
                result["total_spend"] = value

            # Toplam işlem adedi
            count_match = re.search(
                r'(?:i[sş]lem\s+adedi|i[sş]lem\s+say[iı]s[iı])[\s:]*(\d[\d.,]*)',
                text, re.IGNORECASE
            )
            if count_match:
                result["transaction_count"] = self._parse_turkish_number(count_match.group(1))

            # Online oran
            online_match = re.search(
                r'(?:online)[\s:]*(\d[\d.,]*)\s*%',
                text, re.IGNORECASE
            )
            if online_match:
                result["online_ratio"] = self._parse_turkish_number(online_match.group(1)) / 100

            # Temassız oran
            contactless_match = re.search(
                r'(?:temass[iı]z)[\s:]*(\d[\d.,]*)\s*%',
                text, re.IGNORECASE
            )
            if contactless_match:
                result["contactless_ratio"] = self._parse_turkish_number(contactless_match.group(1)) / 100

            # Yıllık büyüme
            growth_match = re.search(
                r'(?:b[üu]y[üu]me|art[iı][sş])[\s:]*%?\s*(\d[\d.,]*)',
                text, re.IGNORECASE
            )
            if growth_match:
                result["growth_yoy"] = self._parse_turkish_number(growth_match.group(1)) / 100

            if len(result) <= 2:  # Sadece timestamp ve source
                logger.info("BKM page parsing found no numeric data")
                return None

            logger.info("BKM data scraped", fields=list(result.keys()))
            return result

        except Exception as e:
            logger.warning("BKM HTML parse error", error=str(e))
            return None

    def _parse_turkish_number(self, text: str) -> float:
        """Türk sayı formatını parse et (1.234,56 → 1234.56)."""
        cleaned = text.replace(".", "").replace(",", ".")
        try:
            return float(cleaned)
        except ValueError:
            return 0.0

    def compute_features(self, data: Dict[str, Any], ticker: str) -> Dict[str, float]:
        """BKM feature'ları hesapla."""
        if not data:
            return {}

        # Placeholder veri kontrolü
        if data.get("data_source") == "placeholder":
            return {}

        features = {
            "cc_spend_growth": float(data.get("growth_yoy", 0)),
            "cc_spend_growth_mom": float(data.get("growth_mom", 0)),
            "cc_transaction_count": float(data.get("transaction_count", 0)),
            "cc_avg_transaction": float(data.get("avg_transaction", 0)),
            "cc_online_ratio": float(data.get("online_ratio", 0)),
            "cc_contactless_ratio": float(data.get("contactless_ratio", 0)),
            "cc_vs_sector": float(data.get("growth_yoy", 0)) - float(data.get("sector_growth", 0)),
            "cc_seasonal_deviation": self._calc_seasonal_dev(data),
            "cc_foreign_ratio": float(data.get("foreign_card_ratio", 0)),
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
