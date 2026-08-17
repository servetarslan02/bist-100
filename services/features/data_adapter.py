"""
ALPHA BIST — Data Adapter v1.0

Feature pipeline ile veri kaynakları arasında bağlantı katmanı.

Sorumluluk:
- Fundamental veriyi Motor 4 formatına çevir
- KAP/haber veriyi Motor 5 formatına çevir
- Katalizör veriyi Motor 6 formatına çevir
- Eksik veri durumunda MISSING/UNKNOWN döndür
- Point-in-time güvenliğini koru

Provider bağımlılıkları (yfinance, aiohttp) kurulu değilse
graceful degradation — MISSING status döner, pipeline durmaz.
"""

from typing import Dict, List, Optional, Any
from datetime import datetime, timezone
import structlog

from .feature_contract import (
    FeatureDataPoint, FeatureStatus,
    make_fresh, make_missing, make_unknown, make_stale,
)

logger = structlog.get_logger()


class DataAdapter:
    """Veri kaynaklarını feature pipeline'a bağlayan adaptör."""

    def __init__(self):
        self._fundamental_provider = None
        self._kap_provider = None
        self._news_provider = None
        self._providers_loaded = False

    def _load_providers(self):
        """Provider'ları lazy-load et (bağımlılık yoksa graceful skip)."""
        if self._providers_loaded:
            return
        self._providers_loaded = True

        # Fundamental (sync — yfinance)
        try:
            from services.ingestion.providers.fundamental_provider import fundamental_provider
            self._fundamental_provider = fundamental_provider
            logger.info("Fundamental provider loaded")
        except ImportError:
            logger.warning("Fundamental provider unavailable (yfinance not installed)")

        # KAP (async — aiohttp)
        try:
            from services.ingestion.providers.kap_provider import KAPProvider
            self._kap_provider = KAPProvider
            logger.info("KAP provider loaded")
        except ImportError:
            logger.warning("KAP provider unavailable (aiohttp not installed)")

        # News (async — aiohttp + feedparser)
        try:
            from services.ingestion.providers.news_provider import NewsProvider
            self._news_provider = NewsProvider
            logger.info("News provider loaded")
        except ImportError:
            logger.warning("News provider unavailable")

    # ==================================================
    # FUNDAMENTAL (Motor 4)
    # ==================================================

    def fetch_fundamentals(
        self,
        ticker: str,
        as_of_date: Optional[str] = None,
    ) -> Dict[str, FeatureDataPoint]:
        """Fundamental veriyi Motor 4 formatında döndür.

        Args:
            ticker: Hisse kodu
            as_of_date: Point-in-time tarih (YYYY-MM-DD). Bu tarihten sonra
                yayınlanan veriler kullanılamaz.

        Returns:
            Motor 4'ün beklediği feature isimlerinde FeatureDataPoint dict
        """
        self._load_providers()

        if self._fundamental_provider is None:
            return self._empty_fundamental(ticker, "provider_unavailable")

        try:
            raw = self._fundamental_provider.fetch_fundamentals(ticker)
            if raw is None:
                return self._empty_fundamental(ticker, "no_data")

            fetch_date = raw.get("fetch_date", "")
            source = raw.get("source", "yfinance")

            # Point-in-time kontrolü
            if as_of_date and fetch_date:
                fetch_day = fetch_date[:10]
                if fetch_day > as_of_date:
                    return self._empty_fundamental(ticker, "future_data_blocked")

            # Motor 4'ün beklediği formata çevir
            result = {}
            ts = fetch_date or datetime.now(timezone.utc).isoformat()

            field_map = {
                "pe_ratio": "pe_ratio",
                "pb_ratio": "pb_ratio",
                "ev_ebitda": "ev_ebitda",
                "fcf_yield": "fcf_yield",
                "roe": "roe",
                "roa": "roa",
                "profit_margin": "profit_margin",
                "gross_margin": "gross_margin",
                "operating_margin": "operating_margin",
                "revenue_growth": "revenue_growth",
                "earnings_growth": "earnings_growth",
                "debt_to_equity": "debt_to_equity",
                "current_ratio": "current_ratio",
                "free_cash_flow": "free_cash_flow",
                "revenue": "revenue",
                "market_cap": "market_cap",
                "total_assets": "total_assets",
            }

            for src_key, dst_key in field_map.items():
                val = raw.get(src_key)
                if val is not None:
                    try:
                        result[dst_key] = make_fresh(float(val), source, ts)
                    except (TypeError, ValueError):
                        result[dst_key] = make_unknown(source)
                else:
                    result[dst_key] = make_unknown(source)

            return result

        except Exception as e:
            logger.warning("Fundamental fetch error", ticker=ticker, error=str(e))
            return self._empty_fundamental(ticker, "fetch_error")

    def _empty_fundamental(self, ticker: str, reason: str) -> Dict[str, FeatureDataPoint]:
        """Boş fundamental veri — tüm feature'lar MISSING/UNKNOWN."""
        keys = [
            "pe_ratio", "pb_ratio", "ev_ebitda", "fcf_yield",
            "roe", "roa", "profit_margin", "gross_margin", "operating_margin",
            "revenue_growth", "earnings_growth", "debt_to_equity", "current_ratio",
            "free_cash_flow", "revenue", "market_cap", "total_assets",
        ]
        status = make_missing if reason == "provider_unavailable" else make_unknown
        return {k: status("fundamental") for k in keys}

    # ==================================================
    # KAP + HABER (Motor 5)
    # ==================================================

    def fetch_kap_events(
        self,
        ticker: str,
        as_of_date: Optional[str] = None,
        limit: int = 20,
    ) -> List[Dict[str, Any]]:
        """KAP olaylarını çek (sync wrapper).

        Args:
            ticker: Hisse kodu
            as_of_date: Bu tarihten sonra yayınlanan KAP'ları filtrele
            limit: Maksimum olay sayısı

        Returns:
            Motor 5'in beklediği formatta KAP olay listesi
        """
        self._load_providers()

        if self._kap_provider is None:
            logger.debug("KAP provider unavailable", ticker=ticker)
            return []

        try:
            import asyncio
            provider = self._kap_provider()

            # Async → sync bridge
            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    # Event loop zaten çalışıyorsa yeni thread'de çalıştır
                    import concurrent.futures
                    with concurrent.futures.ThreadPoolExecutor() as pool:
                        future = pool.submit(
                            asyncio.run,
                            provider.fetch_disclosures(ticker=ticker, limit=limit)
                        )
                        raw_events = future.result(timeout=30)
                else:
                    raw_events = loop.run_until_complete(
                        provider.fetch_disclosures(ticker=ticker, limit=limit)
                    )
            except RuntimeError:
                raw_events = asyncio.run(
                    provider.fetch_disclosures(ticker=ticker, limit=limit)
                )

            if not raw_events:
                return []

            # Motor 5 formatına çevir + PIT filtreleme
            events = []
            for item in raw_events:
                pub_date = item.get("publish_date", "")[:10]

                # Point-in-time: as_of_date'den sonra yayınlananları atla
                if as_of_date and pub_date > as_of_date:
                    continue

                events.append({
                    "category": self._classify_kap_category(item.get("title", "")),
                    "date": pub_date,
                    "sentiment": self._estimate_sentiment(item.get("title", ""), item.get("summary", "")),
                    "importance": self._estimate_importance(item.get("category", ""), item.get("title", "")),
                    "surprise": 0.0,
                    "source": "kap",
                    "title": item.get("title", ""),
                    "publish_date": pub_date,
                })

            return events

        except Exception as e:
            logger.warning("KAP fetch error", ticker=ticker, error=str(e))
            return []

    def fetch_news_events(
        self,
        ticker: str,
        as_of_date: Optional[str] = None,
        limit: int = 20,
    ) -> List[Dict[str, Any]]:
        """Haber olaylarını çek (sync wrapper).

        Args:
            ticker: Hisse kodu
            as_of_date: Bu tarihten sonra yayınlanan haberleri filtrele

        Returns:
            Motor 5'in beklediği formatta haber listesi
        """
        self._load_providers()

        if self._news_provider is None:
            logger.debug("News provider unavailable", ticker=ticker)
            return []

        try:
            import asyncio
            provider = self._news_provider()

            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    import concurrent.futures
                    with concurrent.futures.ThreadPoolExecutor() as pool:
                        future = pool.submit(
                            asyncio.run,
                            provider.fetch_financial_news_rss()
                        )
                        raw_news = future.result(timeout=30)
                else:
                    raw_news = loop.run_until_complete(
                        provider.fetch_financial_news_rss()
                    )
            except RuntimeError:
                raw_news = asyncio.run(
                    provider.fetch_financial_news_rss()
                )

            if not raw_news:
                return []

            # Ticker ile eşleştir + PIT filtreleme
            events = []
            for item in raw_news:
                if not provider.match_news_to_ticker(item, ticker):
                    continue

                pub_date = item.get("published", "")[:10]
                if as_of_date and pub_date > as_of_date:
                    continue

                events.append({
                    "date": pub_date,
                    "sentiment": item.get("sentiment", 0.0),
                    "importance": item.get("importance", 0.5),
                    "source": item.get("source", "news"),
                    "title": item.get("title", ""),
                    "published": pub_date,
                })

            return events[:limit]

        except Exception as e:
            logger.warning("News fetch error", ticker=ticker, error=str(e))
            return []

    # ==================================================
    # KATALİZÖR (Motor 6)
    # ==================================================

    def derive_catalysts(
        self,
        kap_events: List[Dict],
        news_events: List[Dict],
        as_of_date: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """KAP/haber olaylarından katalizör listesi türet.

        Motor 6'nın beklediği format:
        [{"type": "EARNINGS", "importance": 0.9, "days_until": 5}, ...]
        """
        catalysts = []

        # KAP olaylarından katalizör
        for event in kap_events:
            cat = event.get("category", "OTHER")
            importance = event.get("importance", 0.5)
            pub_date = event.get("publish_date", event.get("date", ""))

            # Gelecekteki olayları katalizör olarak ekle
            if as_of_date and pub_date > as_of_date:
                from datetime import datetime as dt
                try:
                    d1 = dt.strptime(as_of_date, "%Y-%m-%d")
                    d2 = dt.strptime(pub_date, "%Y-%m-%d")
                    days_until = (d2 - d1).days
                except ValueError:
                    days_until = 0
            else:
                days_until = 0  # Zaten gerçekleşmiş

            catalysts.append({
                "type": self._kap_category_to_catalyst_type(cat),
                "importance": importance,
                "days_until": max(0, days_until),
                "source": "kap",
            })

        return catalysts

    # ==================================================
    # HELPERS
    # ==================================================

    @staticmethod
    def _classify_kap_category(title: str) -> str:
        """KAP başlığından kategori tahmin et.

        Daha spesifik pattern'lar önce kontrol edilir
        (örn: "temettü" "finansal"dan önce).
        """
        title_lower = title.lower()
        # Spesifik pattern'lar önce
        if any(k in title_lower for k in ["temettü", "kar payı", "dividend"]):
            return "DIVIDEND"
        if any(k in title_lower for k in ["sermaye artırım", "capital increase"]):
            return "CAPITAL_INCREASE"
        if any(k in title_lower for k in ["birleşme", "satın alma", "devralma"]):
            return "MERGER_ACQUISITION"
        if any(k in title_lower for k in ["geri alım", "buyback"]):
            return "SHARE_BUYBACK"
        if any(k in title_lower for k in ["sözleşme", "ihale", "kontrat"]):
            return "CONTRACT"
        if any(k in title_lower for k in ["yönetim kurulu", "atama", "üye"]):
            return "BOARD_CHANGE"
        # Genel pattern'lar sonra
        if any(k in title_lower for k in ["finansal", "bilanço", "gelir tablosu", "kâr"]):
            return "FINANCIAL_REPORT"
        return "OTHER"

    @staticmethod
    def _estimate_sentiment(title: str, summary: str) -> float:
        """KAP başlığı/özeti için basit sentiment tahmini (-1 ile +1)."""
        text = (title + " " + summary).lower()
        positive = ["artış", "büyüme", "rekor", "kâr", "yükseliş", "olumlu", "başarı"]
        negative = ["düşüş", "azalma", "zarar", "kayıp", "olumsuz", "risk", "iptal"]

        pos_count = sum(1 for w in positive if w in text)
        neg_count = sum(1 for w in negative if w in text)

        total = pos_count + neg_count
        if total == 0:
            return 0.0
        return round((pos_count - neg_count) / total, 2)

    @staticmethod
    def _estimate_importance(category: str, title: str) -> float:
        """KAP olayı önem skoru (0-1)."""
        importance_map = {
            "FINANCIAL_REPORT": 1.0,
            "DIVIDEND": 0.8,
            "CAPITAL_INCREASE": 0.9,
            "MERGER_ACQUISITION": 1.0,
            "BOARD_CHANGE": 0.6,
            "SHARE_BUYBACK": 0.7,
            "CONTRACT": 0.7,
            "OTHER": 0.3,
        }
        return importance_map.get(category, 0.3)

    @staticmethod
    def _kap_category_to_catalyst_type(category: str) -> str:
        """KAP kategorisini katalizör tipine çevir."""
        mapping = {
            "FINANCIAL_REPORT": "EARNINGS",
            "DIVIDEND": "DIVIDEND_DATE",
            "CAPITAL_INCREASE": "OTHER",
            "MERGER_ACQUISITION": "OTHER",
            "BOARD_CHANGE": "OTHER",
            "SHARE_BUYBACK": "OTHER",
            "CONTRACT": "CONTRACT_EXPIRY",
        }
        return mapping.get(category, "OTHER")


# Singleton
data_adapter = DataAdapter()
