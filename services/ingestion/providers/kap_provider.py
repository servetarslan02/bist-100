"""
ALPHA BIST — KAP Data Provider v2.0 (Async + Detaylı)

Kamuyu Aydınlatma Platformu — şirket açıklamaları, KAP bildirimleri,
finansal tablolar, fiyat olayları.

v2.0: Async refactor + detaylı KAP çekme + corporate actions parsing
"""

import re
from typing import Any

import structlog

from ...core.async_http import get_client

logger = structlog.get_logger()

KAP_BASE_URL = "https://kap.org.tr"
KAP_API_URL = "https://www.kap.org.tr/tr/api"


class KAPProvider:
    """KAP şirket açıklamaları — async + detaylı."""

    # KAP kategori eşleme
    CATEGORIES = {
        "FINANCAL": "Finansal Tablo",
        "GENERAL": "Genel",
        "BOARD_DECISION": "YK Kararı",
        "CAPITAL_MARKETS": "Sermaye Piyasası",
        "DIVIDEND": "Temettü",
        "MERGER": "Birleşme",
        "AUDIT": "Denetim",
        "EXPLANATION": "Açıklama",
    }

    def __init__(self):
        """Otomatik eklendi."""
        self._client = get_client(
            "kap",
            timeout=3.0,
            max_retries=1,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "Accept": "application/json, text/html, */*",
                "Accept-Language": "tr-TR,tr;q=0.9",
            },
        )

    async def fetch_disclosures(
        self,
        from_date: str | None = None,
        to_date: str | None = None,
        ticker: str | None = None,
        category: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """KAP açıklamalarını çek (async).

        Args:
            from_date: Başlangıç tarihi (YYYY-MM-DD)
            to_date: Bitiş tarihi (YYYY-MM-DD)
            ticker: Hisse kodu (opsiyonel)
            category: Kategori filtresi (opsiyonel)
            limit: Maksimum sonuç sayısı
        """
        try:
            params = {"fromDate": from_date or "", "toDate": to_date or "", "limit": str(limit)}
            if ticker:
                params["ticker"] = ticker
            if category:
                params["category"] = category

            data = await self._client.get_json(f"{KAP_API_URL}/disclosures", params=params)
            if not data:
                return []

            disclosures = []
            for item in data if isinstance(data, list) else []:
                disclosure = {
                    "kap_id": item.get("disclosureId", ""),
                    "ticker": item.get("stockTicker", ""),
                    "title": item.get("title", ""),
                    "summary": item.get("summary", ""),
                    "category": item.get("category", ""),
                    "category_name": self.CATEGORIES.get(item.get("category", ""), item.get("category", "")),
                    "publish_date": item.get("publishDate", ""),
                    "kap_url": f"{KAP_BASE_URL}{item.get('url', '')}",
                    "source": "kap",
                    "is_price_sensitive": self._is_price_sensitive(item),
                    "sentiment": self._classify_sentiment(item),
                    "importance": self._classify_importance(item),
                }
                disclosures.append(disclosure)

            logger.info("KAP disclosures fetched", count=len(disclosures))
            return disclosures

        except Exception as e:
            logger.debug("KAP fetch fallback activated", error=str(e))
            return []

    async def fetch_company_info(self, ticker: str) -> dict[str, Any] | None:
        """Şirket bilgisi çek (async)."""
        try:
            data = await self._client.get_json(f"{KAP_API_URL}/company/{ticker}")
            if data:
                return {
                    "ticker": ticker,
                    "name": data.get("name", ""),
                    "sector": data.get("sector", ""),
                    "market_cap": data.get("marketCap", 0),
                    "employees": data.get("employees", 0),
                    "website": data.get("website", ""),
                    "established": data.get("established", ""),
                    "description": data.get("description", ""),
                }
            return None
        except Exception as e:
            logger.warning("KAP company info failed", ticker=ticker, error=str(e))
            return None

    async def fetch_financial_data(self, ticker: str) -> dict[str, Any] | None:
        """Finansal veri çek (async)."""
        try:
            data = await self._client.get_json(f"{KAP_API_URL}/financial/{ticker}")
            if data:
                return {
                    "ticker": ticker,
                    "revenue": data.get("revenue", 0),
                    "net_income": data.get("netIncome", 0),
                    "total_assets": data.get("totalAssets", 0),
                    "total_equity": data.get("totalEquity", 0),
                    "eps": data.get("eps", 0),
                    "pe_ratio": data.get("peRatio", 0),
                    "report_date": data.get("reportDate", ""),
                    "period": data.get("period", ""),
                    "currency": data.get("currency", "TRY"),
                }
            return None
        except Exception as e:
            logger.warning("KAP financial data failed", ticker=ticker, error=str(e))
            return None

    async def fetch_corporate_actions(
        self,
        ticker: str | None = None,
        from_date: str | None = None,
        to_date: str | None = None,
    ) -> list[dict[str, Any]]:
        """Şirket olaylarını çek (async) — temettü, bölünme, bedelsiz."""
        try:
            params = {"limit": "100"}
            if ticker:
                params["ticker"] = ticker
            if from_date:
                params["fromDate"] = from_date
            if to_date:
                params["toDate"] = to_date

            data = await self._client.get_json(f"{KAP_API_URL}/corporate-actions", params=params)
            if not data:
                return []

            actions = []
            for item in data if isinstance(data, list) else []:
                action = {
                    "kap_id": item.get("disclosureId", ""),
                    "ticker": item.get("stockTicker", ""),
                    "action_type": self._classify_action_type(item),
                    "title": item.get("title", ""),
                    "summary": item.get("summary", ""),
                    "ex_date": item.get("exDate", ""),
                    "record_date": item.get("recordDate", ""),
                    "payment_date": item.get("paymentDate", ""),
                    "amount": self._extract_amount(item),
                    "ratio": self._extract_ratio(item),
                    "publish_date": item.get("publishDate", ""),
                    "source": "kap",
                }
                if action["action_type"]:
                    actions.append(action)

            logger.info("KAP corporate actions fetched", count=len(actions))
            return actions

        except Exception as e:
            logger.error("KAP corporate actions failed", error=str(e))
            return []

    async def fetch_price_sensitive_disclosures(
        self,
        ticker: str,
        from_date: str | None = None,
    ) -> list[dict[str, Any]]:
        """Fiyat olayı niteliğindeki KAP açıklamaları (async)."""
        all_disclosures = await self.fetch_disclosures(ticker=ticker, from_date=from_date, limit=100)
        return [d for d in all_disclosures if d.get("is_price_sensitive")]

    def _is_price_sensitive(self, item: dict) -> bool:
        """Fiyat olayı niteliğinde mi?"""
        category = item.get("category", "").upper()
        title = (item.get("title", "") + " " + item.get("summary", "")).lower()

        sensitive_keywords = [
            "temettü",
            "kar payı",
            "dividend",
            "bölünme",
            "split",
            "bedelsiz",
            "bonus",
            "bedelli",
            "rights",
            "birleşme",
            "merger",
            "devralma",
            "acquisition",
            "borsadan çıkış",
            "delisting",
            "sermaye artırımı",
            "capital increase",
            "iptal",
            "cancellation",
            "satın alma",
            "purchase",
        ]

        if category in ("DIVIDEND", "MERGER", "CAPITAL_MARKETS"):
            return True

        return any(kw in title for kw in sensitive_keywords)

    def _classify_sentiment(self, item: dict) -> float:
        """KAP açıklaması sentiment skoru."""
        title = (item.get("title", "") + " " + item.get("summary", "")).lower()

        positive = [
            "artış",
            "büyüme",
            "kâr",
            "rekor",
            "yükseliş",
            "pozitif",
            "başarı",
            "sermaye artırımı",
            "temettü",
            "kar payı",
            "ciro artışı",
            "sipariş",
            "sözleşme",
            "anlaşma",
            "işbirliği",
            "ihale",
            "yatırım",
            "genişleme",
            "ihracat",
            "büyüme hedefi",
            "kapasite artışı",
            "verimlilik",
            "optimizasyon",
            "iyileştirme",
            "güçlü",
            "sağlıklı",
            "istikrarlı",
            "toparlanma",
            "yükseltme",
            "alım",
            "tavsiye",
            "hedef fiyat",
            "endeks üstü",
            "outperform",
        ]
        negative = [
            "düşüş",
            "kayıp",
            "zarar",
            "azalma",
            "gerileme",
            "iptal",
            "risk",
            "iflas",
            "erteleme",
            "daralma",
            "borç",
            "temerrüt",
            "dava",
            "ceza",
            "soruşturma",
            "yaptırım",
            "kısıtlama",
            "askıya alma",
            "durdurma",
            "ihraç",
            "geri çağırma",
            "recall",
            "kriz",
            "çöküş",
            "bunalım",
            "zayıf",
            "olumsuz",
            "negatif",
            "satış",
            "çıkış",
            "azaltma",
            "downgrade",
            "sat",
            "ağırlık azalt",
            "underperform",
        ]

        pos = sum(1 for w in positive if w in title)
        neg = sum(1 for w in negative if w in title)
        total = pos + neg

        if total == 0:
            return 0.0
        return round((pos - neg) / total, 3)

    def _classify_importance(self, item: dict) -> int:
        """Önem derecesi (1-5)."""
        category = item.get("category", "").upper()

        if category in ("DIVIDEND", "MERGER", "CAPITAL_MARKETS"):
            return 5
        if category in ("FINANCAL", "BOARD_DECISION"):
            return 4
        if category in ("GENERAL", "EXPLANATION"):
            return 3
        return 2

    def _classify_action_type(self, item: dict) -> str | None:
        """Şirket olayı türünü sınıflandır."""
        title = (item.get("title", "") + " " + item.get("summary", "")).lower()

        if any(w in title for w in ["temettü", "kar payı", "dividend"]):
            return "DIVIDEND"
        if any(w in title for w in ["bedelsiz", "bonus"]):
            return "BONUS_SHARE"
        if any(w in title for w in ["bedelli", "rights issue"]):
            return "RIGHTS_ISSUE"
        if any(w in title for w in ["bölünme", "split"]):
            return "STOCK_SPLIT"
        if any(w in title for w in ["birleşme", "merger"]):
            return "MERGER"
        if any(w in title for w in ["devralma", "acquisition"]):
            return "ACQUISITION"
        if any(w in title for w in ["borsadan çıkış", "delisting"]):
            return "DELISTING"
        return None

    def _extract_amount(self, item: dict) -> float | None:
        """Temettü miktarını çıkar."""
        text = item.get("title", "") + " " + item.get("summary", "")
        patterns = [
            r"(\d+[.,]\d+)\s*(?:TL|₺|tl)",
            r"hisse\s+başına.*?(\d+[.,]\d+)\s*(?:TL|₺|tl)?",
            r"kar\s+payı.*?(\d+[.,]\d+)",
            r"(\d+[.,]\d+)\s*kuruş",
        ]
        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                try:
                    val = float(match.group(1).replace(",", "."))
                    if "kuruş" in match.group(0).lower():
                        val /= 100.0
                    return val
                except ValueError:
                    continue
        return None

    def _extract_ratio(self, item: dict) -> float | None:
        """Bölünme/bedelsiz oranını çıkar (% veya x:y formatı)."""
        text = item.get("title", "") + " " + item.get("summary", "")
        patterns = [
            r"%\s*(\d+[.,]?\d*)",
            r"yüzde\s*(\d+[.,]?\d*)",
            r"1[''e]\s*(\d+)",
            r"(\d+)\s*:\s*1",
        ]
        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                try:
                    val = float(match.group(1).replace(",", "."))
                    return val
                except ValueError:
                    continue
        return None

    def sync_disclosures_to_registry(self, disclosures: list[dict[str, Any]], current_date: str) -> int:
        """KAP bildirimlerinden VBTS / Tedbir / İşlem durdurma kararlarını ayıklar ve KAPMarketRestrictionRegistry'ye kaydeder."""
        from services.paper_trading.kap_market_restriction_registry import kap_restriction_registry

        registered_count = 0
        for item in disclosures:
            ticker = item.get("ticker", "").strip()
            if not ticker:
                continue

            title = (item.get("title", "") + " " + item.get("summary", "")).lower()
            pub_date = item.get("publish_date", current_date)

            # 1. VBTS Brüt Takas Tespiti
            if any(w in title for w in ["brüt takas", "brut takas", "gross settlement"]):
                kap_restriction_registry.register_restriction(
                    ticker=ticker,
                    restriction_type="VBTS_GROSS_SETTLEMENT",
                    published_at=pub_date,
                    effective_date=current_date,
                    details=item.get("title", "KAP VBTS Brüt Takas Bildirimi"),
                )
                registered_count += 1

            # 2. VBTS Açığa Satış ve Kredili İşlem Yasağı
            elif any(w in title for w in ["açığa satış", "kredili işlem", "short sale ban"]):
                kap_restriction_registry.register_restriction(
                    ticker=ticker,
                    restriction_type="VBTS_SHORT_BAN",
                    published_at=pub_date,
                    effective_date=current_date,
                    details=item.get("title", "KAP Açığa Satış Yasağı"),
                )
                registered_count += 1

            # 3. İşlem Sırası Durdurma / Devre Kesici (Halt)
            elif any(w in title for w in ["işlem sırası durdurul", "işleme kapatıl", "devre kesici"]):
                kap_restriction_registry.register_restriction(
                    ticker=ticker,
                    restriction_type="HALT",
                    published_at=pub_date,
                    effective_date=current_date,
                    details=item.get("title", "KAP İşlem Sırası Durdurma"),
                )
                registered_count += 1

        if registered_count > 0:
            logger.info("Automated KAP market restrictions synced", count=registered_count, date=current_date)
        return registered_count

    async def close(self) -> Any:
        """Otomatik eklendi."""
        await self._client.close()


# Singleton
kap_provider = KAPProvider()
