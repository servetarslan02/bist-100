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

from typing import Dict, List, Optional, Any, Set
from datetime import datetime, timezone, timedelta
import hashlib
import structlog

from .feature_contract import (
    FeatureDataPoint, FeatureStatus,
    make_fresh, make_missing, make_unknown, make_stale,
)

logger = structlog.get_logger()

# Fundamental veri freshness eşikleri
FUNDAMENTAL_STALE_DAYS = 90   # 90 günden eski → STALE
FUNDAMENTAL_MAX_AGE_DAYS = 365  # 1 yıldan eski → MISSING


class DataAdapter:
    """Veri kaynaklarını feature pipeline'a bağlayan adaptör."""

    def __init__(self):
        self._fundamental_provider = None
        self._kap_provider = None
        self._news_provider = None
        self._providers_loaded = False
        self._seen_event_ids: Set[str] = set()  # Duplicate kontrolü
        self._kap_provider_instance = None
        self._news_provider_instance = None

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

    def reset_duplicates(self):
        """Duplicate tracking sıfırla (pipeline run başlangıcında çağrılır)."""
        self._seen_event_ids.clear()

    # ==================================================
    # ASYNC BRIDGE
    # ==================================================

    def _run_async(self, coro, timeout: float = 10.0):
        """Async coroutine'u sync olarak çalıştır.

        Thread-based timeout: ağ çağrısı asla sonsuz bloklanmaz.
        Her çağrıda yeni event loop oluşturulur — aiohttp session lifecycle sorunu çözülür.
        """
        import asyncio
        import threading

        result = [None]
        error = [None]

        def _run():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                result[0] = loop.run_until_complete(coro)
            except Exception as e:
                error[0] = e
            finally:
                loop.close()

        thread = threading.Thread(target=_run, daemon=True)
        thread.start()
        thread.join(timeout=timeout)

        if thread.is_alive():
            logger.warning("Async call timed out", timeout=timeout)
            return None
        if error[0]:
            logger.warning("Async call failed", error=str(error[0]))
            return None
        return result[0]

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
            # KRİTİK: fetch_date, verinin ÇEKİLME tarihidir, yayınlanma tarihi değil.
            # yfinance gibi real-time kaynaklarda fetch_date her zaman "şimdi"dir.
            # PIT kontrolü sadece "published_date" veya "report_date" varsa uygulanır.
            # Fundamental veri için publication_date yoksa, freshness check yeterlidir.
            pub_date = raw.get("publication_date", "") or raw.get("report_date", "")
            if as_of_date and pub_date:
                pub_day = pub_date[:10]
                if pub_day > as_of_date:
                    return self._empty_fundamental(ticker, "future_data_blocked")

            # Freshness kontrolü
            # KRİTİK: yfinance real-time kaynaktır, fetch_date her zaman "şimdi"dir.
            # publication_date/report_date yoksa → her zaman FRESH (live data)
            # publication_date varsa → PIT kontrolü yapılır
            if pub_date:
                # Gerçek yayın tarihi var → freshness check
                ts = pub_date
                freshness_status = self._check_fundamental_freshness(ts, as_of_date)
            else:
                # Real-time kaynak (yfinance) → her zaman FRESH
                freshness_status = FeatureStatus.FRESH
                ts = fetch_date or datetime.now(timezone.utc).isoformat()

            if freshness_status == FeatureStatus.MISSING:
                return self._empty_fundamental(ticker, "stale_data")

            # Motor 4'ün beklediği formata çevir
            result = {}

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
                        float_val = float(val)
                        if freshness_status == FeatureStatus.STALE:
                            result[dst_key] = make_stale(float_val, source, ts)
                        else:
                            result[dst_key] = make_fresh(float_val, source, ts)
                    except (TypeError, ValueError):
                        result[dst_key] = make_unknown(source)
                else:
                    result[dst_key] = make_unknown(source)

            return result

        except Exception as e:
            logger.warning("Fundamental fetch error", ticker=ticker, error=str(e))
            return self._empty_fundamental(ticker, "fetch_error")

    def _check_fundamental_freshness(
        self, fetch_ts: str, as_of_date: Optional[str],
    ) -> FeatureStatus:
        """Fundamental veri freshness kontrolü.

        fetch_ts: Verinin çekildiği timestamp (yfinance → her zaman "şimdi")
        as_of_date: Backtest snapshot tarihi (None → live)

        Kural: Real-time kaynaklar (yfinance) her zaman FRESH.
        Publication date varsa PIT kontrolü yapılır.
        """
        if not fetch_ts:
            return FeatureStatus.MISSING

        try:
            fetch_day = fetch_ts[:10]

            # as_of_date yoksa → live mode → her zaman FRESH
            if not as_of_date:
                return FeatureStatus.FRESH

            d_fetch = datetime.strptime(fetch_day, "%Y-%m-%d")
            d_ref = datetime.strptime(as_of_date, "%Y-%m-%d")
            age_days = (d_ref - d_fetch).days

            # fetch_date gelecekte → bu veri gelecekte çekilmiş, PIT'de kullanılamaz
            # Ama bu sadece publication_date yoksa geçerli (yfinance'da fetch_date her zaman şimdi)
            # Bu durumda STALE olarak işaretle, MISSING değil
            if age_days < 0:
                # Gelecek tarihli fetch — STALE (kullanılabilir ama güven düşük)
                return FeatureStatus.STALE
            elif age_days <= FUNDAMENTAL_STALE_DAYS:
                return FeatureStatus.FRESH
            elif age_days <= FUNDAMENTAL_MAX_AGE_DAYS:
                return FeatureStatus.STALE
            else:
                return FeatureStatus.MISSING
        except (ValueError, TypeError):
            return FeatureStatus.MISSING

    def _empty_fundamental(self, ticker: str, reason: str) -> Dict[str, FeatureDataPoint]:
        """Boş fundamental veri — tüm feature'lar MISSING/UNKNOWN."""
        keys = [
            "pe_ratio", "pb_ratio", "ev_ebitda", "fcf_yield",
            "roe", "roa", "profit_margin", "gross_margin", "operating_margin",
            "revenue_growth", "earnings_growth", "debt_to_equity", "current_ratio",
            "free_cash_flow", "revenue", "market_cap", "total_assets",
        ]
        if reason == "provider_unavailable":
            status_fn = make_missing
        elif reason == "stale_data":
            status_fn = make_unknown
        else:
            status_fn = make_unknown
        return {k: status_fn("fundamental") for k in keys}

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
            if self._kap_provider_instance is None:
                self._kap_provider_instance = self._kap_provider()
            provider = self._kap_provider_instance

            raw_events = self._run_async(
                provider.fetch_disclosures(ticker=ticker, limit=limit)
            )

            if not raw_events:
                return []

            # Motor 5 formatına çevir + PIT filtreleme + duplicate kontrolü
            events = []
            for item in raw_events:
                # Zorunlu alan kontrolü
                kap_ticker = item.get("ticker", "").strip().upper()
                pub_date = item.get("publish_date", "")[:10]
                title = item.get("title", "").strip()

                if not pub_date or not title:
                    continue  # Zorunlu alan eksik

                # Ticker doğrulama: KAP API'den gelen stockTicker
                if kap_ticker and kap_ticker != ticker.upper():
                    continue  # Farklı şirket

                # Point-in-time: as_of_date'den sonra yayınlananları atla
                if as_of_date and pub_date > as_of_date:
                    continue

                # Duplicate kontrolü (event ID veya title hash)
                event_id = item.get("id", "") or hashlib.md5(
                    f"{pub_date}:{title}".encode()
                ).hexdigest()[:16]
                if event_id in self._seen_event_ids:
                    continue
                self._seen_event_ids.add(event_id)

                events.append({
                    "category": self._classify_kap_category(title),
                    "date": pub_date,
                    "sentiment": self._estimate_sentiment(title, item.get("summary", "")),
                    "importance": self._estimate_importance(item.get("category", ""), title),
                    "surprise": 0.0,
                    "source": "kap",
                    "title": title,
                    "publish_date": pub_date,
                    "ticker": kap_ticker or ticker,
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
            if self._news_provider_instance is None:
                self._news_provider_instance = self._news_provider()
            provider = self._news_provider_instance

            raw_news = self._run_async(
                provider.fetch_financial_news_rss()
            )

            if not raw_news:
                return []

            # Ticker ile eşleştir + PIT filtreleme + duplicate kontrolü
            events = []
            for item in raw_news:
                title = item.get("title", "").strip()
                if not title:
                    continue

                # Tarih parse (RFC 2822: "Thu, 06 Aug 2026 09:03:00 +0000")
                raw_date = item.get("published", "")
                pub_date = self._parse_news_date(raw_date)
                if not pub_date:
                    continue

                if as_of_date and pub_date > as_of_date:
                    continue

                # Ticker eşleşme kontrolü
                # Genel finansal haberler (ticker boş) → tüm hisseler için geçerli
                # Şirket özel haberleri → sadece eşleşen hisse için
                news_ticker = item.get("ticker", "").strip()
                if news_ticker and not provider.match_news_to_ticker(item, ticker):
                    continue

                # Duplicate kontrolü (title hash)
                event_id = hashlib.md5(
                    f"{pub_date}:{title}".encode()
                ).hexdigest()[:16]
                if event_id in self._seen_event_ids:
                    continue
                self._seen_event_ids.add(event_id)

                events.append({
                    "date": pub_date,
                    "sentiment": item.get("sentiment", 0.0),
                    "importance": item.get("importance", 0.5),
                    "source": item.get("source", "news"),
                    "title": title,
                    "published": pub_date,
                    "ticker": ticker,
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
    def _parse_news_date(raw_date: str) -> str:
        """Haber tarihini YYYY-MM-DD formatına çevir.

        Desteklenen formatlar:
        - RFC 2822: "Thu, 06 Aug 2026 09:03:00 +0000"
        - ISO: "2026-08-06T09:03:00Z"
        - Basit: "2026-08-06"
        """
        if not raw_date:
            return ""

        # Zaten YYYY-MM-DD formatında
        if len(raw_date) >= 10 and raw_date[4] == "-" and raw_date[7] == "-":
            return raw_date[:10]

        # RFC 2822 parse
        try:
            from email.utils import parsedate_to_datetime
            dt = parsedate_to_datetime(raw_date)
            return dt.strftime("%Y-%m-%d")
        except Exception:
            pass

        # Manuel parse ("06 Aug 2026" formatı)
        try:
            parts = raw_date.split()
            if len(parts) >= 3:
                day = parts[1] if len(parts[1]) == 2 else parts[1]
                month_map = {"Jan": "01", "Feb": "02", "Mar": "03", "Apr": "04",
                             "May": "05", "Jun": "06", "Jul": "07", "Aug": "08",
                             "Sep": "09", "Oct": "10", "Nov": "11", "Dec": "12"}
                month = month_map.get(parts[2][:3], "")
                year = parts[3] if len(parts) > 3 else ""
                if year and month and day:
                    return f"{year}-{month}-{day.zfill(2)}"
        except Exception:
            pass

        return ""

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
