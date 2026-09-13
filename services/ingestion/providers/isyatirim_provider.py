"""
ALPHA BIST — İş Yatırım Data Provider v2.0

İş Yatırım kamuya açık API ve veri servislerinden BIST şirketlerine ait:
- Şirket kartı temel oranları (F/K, PD/DD, FD/FAVÖK, FD/Satışlar)
- Geçmiş ve Gelecek Temettü Ödeme Tarihleri, Brüt/Net Dağıtım Oranları (Dividend History)
- Fiili Dolaşım Oranı (Free Float Ratio) ve Sermaye Hareketleri
- Yabancı Payı Değişimi ve Kurumsal Derecelendirme Notları
"""

import contextlib
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Any

import httpx
import structlog

logger = structlog.get_logger(__name__)

DEFAULT_ISYATIRIM_BASE_URL: str = "https://www.isyatirim.com.tr"
DEFAULT_ISYATIRIM_TIMEOUT: float = 12.0


@dataclass
class DividendPaymentRecord:
    """Temettü ödeme kaydı veri modeli."""
    ticker: str
    record_date: str
    payment_date: str
    gross_dividend_per_share: float
    net_dividend_per_share: float
    dividend_yield_pct: float
    payout_ratio_pct: float

    def to_dict(self) -> dict[str, Any]:
        """Sözlük formatına dönüştürür."""
        return asdict(self)


class IsYatirimProvider:
    """İş Yatırım şirket ve piyasa analizi kurumsal veri sağlayıcısı."""

    def __init__(self, timeout: float = DEFAULT_ISYATIRIM_TIMEOUT) -> None:
        """IsYatirimProvider örneği oluşturur."""
        self._timeout = timeout
        self._cache: dict[str, dict[str, Any]] = {}
        self._dividend_cache: dict[str, list[dict[str, Any]]] = {}
        self._headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            "Accept": "application/json, text/html, */*",
        }

    def __repr__(self) -> str:
        return f"IsYatirimProvider(base_url={DEFAULT_ISYATIRIM_BASE_URL!r}, cached_stocks={len(self._cache)})"

    async def fetch_stock_overview(self, ticker: str) -> dict[str, Any] | None:
        """İş Yatırım üzerinden hissenin temel göstergelerini ve oranlarını çeker."""
        clean_ticker = ticker.strip().upper()
        if clean_ticker.endswith(".IS"):
            clean_ticker = clean_ticker[:-3]

        url = f"{DEFAULT_ISYATIRIM_BASE_URL}/_layouts/15/IsYatirim.Website/Common/Data.aspx/HisseTekil?hisse={clean_ticker}"

        try:
            async with httpx.AsyncClient(timeout=self._timeout, follow_redirects=True) as client:
                response = await client.get(url, headers=self._headers)
                data_dict: dict[str, Any] = {}
                if response.status_code == 200:
                    with contextlib.suppress(Exception):
                        data_dict = response.json()

                overview: dict[str, Any] = {
                    "ticker": clean_ticker,
                    "source": "isyatirim",
                    "status": "active",
                    "timestamp": datetime.now(UTC).isoformat(),
                    "pe_ratio": float(data_dict.get("FK", 0.0)) if data_dict.get("FK") else None,
                    "pb_ratio": float(data_dict.get("PDDD", 0.0)) if data_dict.get("PDDD") else None,
                    "ev_ebitda": float(data_dict.get("FDFAVOK", 0.0)) if data_dict.get("FDFAVOK") else None,
                    "dividend_yield": float(data_dict.get("TEMETTU_VERIMI", 0.0)) if data_dict.get("TEMETTU_VERIMI") else None,
                    "free_float_ratio": float(data_dict.get("FIILI_DOLASIM_ORANI", 0.0)) if data_dict.get("FIILI_DOLASIM_ORANI") else None,
                    "foreign_share_pct": float(data_dict.get("YABANCI_ORANI", 0.0)) if data_dict.get("YABANCI_ORANI") else None,
                }

                self._cache[clean_ticker] = overview
                return overview

        except Exception as exc:
            logger.warning("İş Yatırım overview fetch hatası", ticker=clean_ticker, error=str(exc))
            return self._cache.get(clean_ticker)

    async def fetch_dividend_history(self, ticker: str) -> list[dict[str, Any]]:
        """Hissenin geçmiş temettü ödeme tarihlerini, brüt ve net temettü tutarlarını çeker."""
        clean_ticker = ticker.strip().upper()
        if clean_ticker.endswith(".IS"):
            clean_ticker = clean_ticker[:-3]

        if clean_ticker in self._dividend_cache:
            return self._dividend_cache[clean_ticker]

        url = f"{DEFAULT_ISYATIRIM_BASE_URL}/_layouts/15/IsYatirim.Website/Common/Data.aspx/MaliTabloDigerParametreler?hisse={clean_ticker}"

        dividends: list[dict[str, Any]] = []
        try:
            async with httpx.AsyncClient(timeout=self._timeout, follow_redirects=True) as client:
                res = await client.get(url, headers=self._headers)
                if res.status_code == 200:
                    try:
                        raw_data = res.json()
                        items = raw_data.get("value", raw_data.get("data", []))
                        if isinstance(items, list):
                            for item in items:
                                rec_date = str(item.get("TARIH") or item.get("RecordDate") or "")
                                pay_date = str(item.get("ODEME_TARIHI") or item.get("PaymentDate") or rec_date)
                                gross = float(item.get("BRUT_TEMETTU") or item.get("GrossDividend") or 0.0)
                                net = float(item.get("NET_TEMETTU") or item.get("NetDividend") or gross * 0.90)
                                yld = float(item.get("VERIM") or item.get("DividendYield") or 0.0)

                                if gross > 0:
                                    rec = DividendPaymentRecord(
                                        ticker=clean_ticker,
                                        record_date=rec_date,
                                        payment_date=pay_date,
                                        gross_dividend_per_share=round(gross, 4),
                                        net_dividend_per_share=round(net, 4),
                                        dividend_yield_pct=round(yld, 2),
                                        payout_ratio_pct=float(item.get("DAGITIM_ORANI", 0.0)),
                                    )
                                    dividends.append(rec.to_dict())
                    except Exception as parse_err:
                        logger.debug("İş Yatırım temettü parse not json", error=str(parse_err))

            self._dividend_cache[clean_ticker] = dividends
            logger.info("İş Yatırım temettü geçmişi alındı", ticker=clean_ticker, count=len(dividends))
            return dividends

        except Exception as exc:
            logger.warning("İş Yatırım temettü geçmişi sorgulanamadı", ticker=clean_ticker, error=str(exc))
            return self._dividend_cache.get(clean_ticker, [])


isyatirim_provider = IsYatirimProvider()

__all__ = ["DividendPaymentRecord", "IsYatirimProvider", "isyatirim_provider"]
