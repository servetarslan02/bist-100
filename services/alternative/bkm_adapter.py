"""
ALPHA BIST — BKM Credit Card Adapter v2.0

BKM (Bankalararası Kart Merkezi) kredi kartı harcama verisi.
Web scraping ile aylık kart verileri çekme.

Kaynak: https://www.bkm.com.tr/tr-TR/kart-verileri

Features:
- cc_spend_growth: Yıllık büyüme oranı
- cc_transaction_count: Toplam işlem sayısı
- cc_avg_transaction: Ortalama işlem tutarı
- cc_online_ratio: Online harcama oranı
- cc_contactless_ratio: Temassız ödeme oranı
- cc_seasonal_deviation: Mevsimsel sapma
"""

import re
from datetime import UTC, datetime
from typing import Any

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

    async def collect(self, ticker: str, **kwargs) -> dict[str, Any] | None:
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

    async def _scrape_bkm_page(self) -> dict[str, Any] | None:
        """BKM kart verileri sayfasını scrape et."""
        try:
            import aiohttp

            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "Accept-Language": "tr-TR,tr;q=0.9",
            }

            async with (
                aiohttp.ClientSession() as session,
                session.get(
                    self.BKM_URL,
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(total=15),
                ) as resp,
            ):
                if resp.status != 200:
                    logger.warning("BKM page returned non-200", status=resp.status)
                    return None

                html = await resp.text()
                return self._parse_bkm_html(html)

        except ImportError as e:
            logger.warning("Missing dependency for BKM scraping", missing=str(e))
            return None
        except Exception as e:
            logger.warning("BKM scrape error", error=str(e))
            return None

    def _parse_bkm_html(self, html: str) -> dict[str, Any] | None:
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
                "timestamp": datetime.now(UTC).isoformat(),
                "source": "bkm_web",
            }

            # Sayısal verileri ara — tablo veya istatistik kutucukları
            text = soup.get_text(" ", strip=True)

            # Toplam işlem tutarı (milyar TL)
            spend_match = re.search(
                r"(?:toplam|tutar|har[cç]ama)[\s:]*(\d[\d.,]*)\s*(?:milyar|milyon|tl|₺)", text, re.IGNORECASE
            )
            if spend_match:
                try:
                    value = self._parse_turkish_number(spend_match.group(1))
                    if "milyar" in text[spend_match.start() : spend_match.end() + 20].lower():
                        value *= 1_000_000_000
                    elif "milyon" in text[spend_match.start() : spend_match.end() + 20].lower():
                        value *= 1_000_000
                    result["total_spend"] = value
                except ValueError:
                    logger.debug("BKM parse skip: total_spend", raw=spend_match.group(1))

            # Toplam işlem adedi
            count_match = re.search(
                r"(?:i[sş]lem\s+adedi|i[sş]lem\s+say[iı]s[iı])[\s:]*(\d[\d.,]*)", text, re.IGNORECASE
            )
            if count_match:
                try:
                    result["transaction_count"] = self._parse_turkish_number(count_match.group(1))
                except ValueError:
                    logger.debug("BKM parse skip: transaction_count", raw=count_match.group(1))

            # Online oran
            online_match = re.search(r"(?:online)[\s:]*(\d[\d.,]*)\s*%", text, re.IGNORECASE)
            if online_match:
                try:
                    result["online_ratio"] = self._parse_turkish_number(online_match.group(1)) / 100
                except ValueError:
                    logger.debug("BKM parse skip: online_ratio", raw=online_match.group(1))

            # Temassız oran
            contactless_match = re.search(r"(?:temass[iı]z)[\s:]*(\d[\d.,]*)\s*%", text, re.IGNORECASE)
            if contactless_match:
                try:
                    result["contactless_ratio"] = self._parse_turkish_number(contactless_match.group(1)) / 100
                except ValueError:
                    logger.debug("BKM parse skip: contactless_ratio", raw=contactless_match.group(1))

            # Yıllık büyüme
            growth_match = re.search(r"(?:b[üu]y[üu]me|art[iı][sş])[\s:]*%?\s*(\d[\d.,]*)", text, re.IGNORECASE)
            if growth_match:
                try:
                    result["growth_yoy"] = self._parse_turkish_number(growth_match.group(1)) / 100
                except ValueError:
                    logger.debug("BKM parse skip: growth_yoy", raw=growth_match.group(1))

            if len(result) <= 2:  # Sadece timestamp ve source
                logger.info("BKM page parsing found no numeric data")
                return None

            logger.info("BKM data scraped", fields=list(result.keys()))
            return result

        except Exception as e:
            logger.warning("BKM HTML parse error", error=str(e))
            return None

    def _parse_turkish_number(self, text: str) -> float:
        """Türk sayı formatını parse et (1.234,56 → 1234.56).

        Args:
            text: Parse edilecek sayı metni.

        Returns:
            Parse edilmiş float değer.

        Raises:
            ValueError: Geçersiz sayı formatı.
        """
        cleaned = text.replace(".", "").replace(",", ".")
        return float(cleaned)

    def compute_features(self, data: dict[str, Any], ticker: str) -> dict[str, float]:
        """BKM verisinden feature'ları hesapla.

        Args:
            data: BKM'den çekilen ham veri.
            ticker: Hisse sembolü.

        Returns:
            Feature sözlüğü.
        """
        if not data:
            return {}

        # Sentetik/test veri kontrolü
        if data.get("data_source") in ("mock", "placeholder"):
            return {}

        total_spend = float(data.get("total_spend", 0))
        transaction_count = float(data.get("transaction_count", 0))
        avg_transaction = (total_spend / transaction_count) if transaction_count > 0 else 0.0

        features = {
            "cc_spend_growth": float(data.get("growth_yoy", 0)),
            "cc_transaction_count": transaction_count,
            "cc_avg_transaction": avg_transaction,
            "cc_online_ratio": float(data.get("online_ratio", 0)),
            "cc_contactless_ratio": float(data.get("contactless_ratio", 0)),
            "cc_seasonal_deviation": self._calc_seasonal_dev(data),
        }

        return features

    def _calc_seasonal_dev(self, data: dict[str, Any]) -> float:
        """Mevsimsel sapma hesapla.

        Büyüme oranı ile sektör ortalaması arasındaki fark.
        Sektör verisi yoksa 0 döner.
        """
        growth = data.get("growth_yoy", 0)
        sector_growth = data.get("sector_growth", 0)
        if sector_growth == 0:
            return 0.0
        return float(growth) - float(sector_growth)


# Singleton
bkm_adapter = BKMAdapter()
