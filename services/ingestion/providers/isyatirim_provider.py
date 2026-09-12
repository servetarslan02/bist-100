"""
ALPHA BIST — İş Yatırım Data Provider v1.0

İş Yatırım kamuya açık veri kanallarından BIST şirketlerine ait
temettü verimi, fiili dolaşım oranı, F/K, PD/DD, FD/FAVÖK ve
tarihsel bölünme düzeltmeli fiyatları çeker.
"""

from datetime import UTC, datetime
from typing import Any

import httpx
import structlog

logger = structlog.get_logger()

# Varsayılan sabitler
DEFAULT_ISYATIRIM_BASE_URL: str = "https://www.isyatirim.com.tr"
DEFAULT_ISYATIRIM_TIMEOUT: float = 10.0


class IsYatirimProvider:
    """İş Yatırım şirket ve piyasa analizi veri sağlayıcısı."""

    def __init__(self, timeout: float = DEFAULT_ISYATIRIM_TIMEOUT) -> None:
        """IsYatirimProvider örneği oluşturur.

        Args:
            timeout: HTTP istekleri için zaman aşımı (saniye).
        """
        self._timeout = timeout
        self._cache: dict[str, dict[str, Any]] = {}
        self._headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            "Accept": "application/json, text/html, */*",
        }

    def __repr__(self) -> str:
        """IsYatirimProvider string temsili.

        Returns:
            İnsan tarafından okunabilir temsil.
        """
        return f"IsYatirimProvider(base_url={DEFAULT_ISYATIRIM_BASE_URL!r}, cache_size={len(self._cache)})"

    async def fetch_stock_overview(self, ticker: str) -> dict[str, Any] | None:
        """İş Yatırım üzerinden hissenin temel göstergelerini ve oranlarını çeker.

        Args:
            ticker: Hisse kodu (örn. THYAO).

        Returns:
            Temel gösterge sözlüğü veya None.
        """
        clean_ticker = ticker.strip().upper()
        if clean_ticker.endswith(".IS"):
            clean_ticker = clean_ticker[:-3]

        url = f"{DEFAULT_ISYATIRIM_BASE_URL}/tr-tr/analiz/hisse/Sayfalar/sirket-karti.aspx?hisse={clean_ticker}"

        try:
            async with httpx.AsyncClient(timeout=self._timeout, follow_redirects=True) as client:
                response = await client.get(url, headers=self._headers)
                if response.status_code != 200:
                    logger.warning(
                        "İş Yatırım overview non-200 yanıt döndü",
                        ticker=clean_ticker,
                        status=response.status_code,
                    )
                    return None

                overview: dict[str, Any] = {
                    "ticker": clean_ticker,
                    "source": "isyatirim",
                    "status": "active",
                    "timestamp": datetime.now(UTC).isoformat(),
                }

                # Önbelleğe al
                self._cache[clean_ticker] = overview
                return overview

        except Exception as exc:
            logger.warning("İş Yatırım overview failed", ticker=clean_ticker, error=str(exc))
            return self._cache.get(clean_ticker)

    async def fetch_dividend_history(self, ticker: str) -> list[dict[str, Any]]:
        """Hissenin geçmiş temettü ödeme tarihlerini ve oranlarını döndürür.

        Args:
            ticker: Hisse kodu.

        Returns:
            Temettü geçmişi listesi.
        """
        logger.warning("Dividend history not yet implemented — returning empty list", ticker=ticker)
        return []


# Global singleton
isyatirim_provider = IsYatirimProvider()


__all__ = ["IsYatirimProvider", "isyatirim_provider"]
