"""ALPHA BIST - KAP (Kamuyu Aydınlatma Platformu) Data Provider"""

import requests
import re
from datetime import datetime
from typing import Optional, List, Dict, Any
from bs4 import BeautifulSoup
import structlog

logger = structlog.get_logger()

KAP_BASE_URL = "https://kap.org.tr"
KAP_API_URL = "https://www.kap.org.tr/tr/api"


class KAPProvider:
    """Fetches company disclosures from KAP (Public Disclosure Platform)."""

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept": "application/json",
            "Accept-Language": "tr-TR,tr;q=0.9",
        })

    def fetch_disclosures(
        self,
        from_date: Optional[str] = None,
        to_date: Optional[str] = None,
        subject_list: Optional[List[str]] = None,
        term: Optional[str] = None,
        ticker: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Fetch disclosures from KAP API."""
        url = f"{KAP_API_URL}/disclosures"

        params = {}
        if from_date:
            params["fromDate"] = from_date
        if to_date:
            params["toDate"] = to_date
        if subject_list:
            params["subjectList"] = ",".join(subject_list)
        if term:
            params["term"] = term
        if ticker:
            params["ticker"] = ticker

        try:
            resp = self.session.get(url, params=params, timeout=30)
            resp.raise_for_status()
            data = resp.json()

            disclosures = []
            for item in data.get("data", []):
                disclosure = {
                    "kap_id": item.get("disclosureID", ""),
                    "ticker": item.get("ticker", ""),
                    "company_name": item.get("companyName", ""),
                    "title": item.get("title", ""),
                    "summary": item.get("summary", ""),
                    "category": item.get("category", ""),
                    "subject": item.get("subject", ""),
                    "publish_date": item.get("publishDate", ""),
                    "is_price_sensitive": item.get("isPriceSensitive", False),
                    "attachment_count": item.get("attachmentCount", 0),
                    "raw_html": item.get("content", ""),
                }

                # Parse sentiment and importance
                disclosure["sentiment"] = self._analyze_sentiment(disclosure)
                disclosure["importance"] = self._assess_importance(disclosure)

                disclosures.append(disclosure)

            logger.info("KAP disclosures fetched", count=len(disclosures))
            return disclosures

        except Exception as e:
            logger.error("Failed to fetch KAP disclosures", error=str(e))
            return []

    def fetch_company_financials(self, ticker: str) -> Optional[Dict[str, Any]]:
        """Fetch latest financial data for a company from KAP."""
        url = f"{KAP_API_URL}/financials/{ticker}"

        try:
            resp = self.session.get(url, timeout=30)
            resp.raise_for_status()
            data = resp.json()

            if not data:
                return None

            return {
                "ticker": ticker,
                "period": data.get("period", ""),
                "revenue": data.get("revenue", 0),
                "net_income": data.get("netIncome", 0),
                "ebitda": data.get("ebitda", 0),
                "total_assets": data.get("totalAssets", 0),
                "total_equity": data.get("totalEquity", 0),
                "total_debt": data.get("totalDebt", 0),
                "cash": data.get("cash", 0),
                "roe": data.get("roe", 0),
                "roa": data.get("roa", 0),
                "debt_equity": data.get("debtEquity", 0),
                "net_margin": data.get("netMargin", 0),
                "revenue_growth": data.get("revenueGrowth", 0),
                "earnings_growth": data.get("earningsGrowth", 0),
                "publish_date": data.get("publishDate", ""),
            }

        except Exception as e:
            logger.warning("Failed to fetch KAP financials", ticker=ticker, error=str(e))
            return None

    def _analyze_sentiment(self, disclosure: Dict[str, Any]) -> float:
        """Basic Turkish NLP sentiment analysis on KAP disclosure."""
        title = disclosure.get("title", "").lower()
        summary = disclosure.get("summary", "").lower()
        text = f"{title} {summary}"

        # Positive keywords
        positive_words = [
            "kar", "büyüme", "artış", "kazanç", "rekor", "yükseliş",
            "olumlu", "başarı", "gelişme", "iyileşme", "arttı", "yükseldi",
            "temettü", "bedelsiz", "yatırım", "sözleşme", "ihale",
            "işbirliği", "anlaşma", "satın alma", "birleşme",
        ]

        # Negative keywords
        negative_words = [
            "zarar", "düşüş", "kayıp", "azalış", "olumsuz", "gerileme",
            "bozulma", "risk", "uyarı", "iptal", "erteleme", "dava",
            "ceza", "sorun", "kriz", "iflas", "borç", "default",
        ]

        positive_count = sum(1 for w in positive_words if w in text)
        negative_count = sum(1 for w in negative_words if w in text)

        total = positive_count + negative_count
        if not total or total == 0:
            return 0.0

        return (positive_count - negative_count) / total

    def _assess_importance(self, disclosure: Dict[str, Any]) -> float:
        """Assess the importance of a KAP disclosure."""
        importance = 0.5

        # Price sensitive = high importance
        if disclosure.get("is_price_sensitive"):
            importance += 0.3

        # Financial results = high importance
        subject = disclosure.get("subject", "").lower()
        if any(word in subject for word in ["finansal", "bilanço", "kar", "zarar", "temettü"]):
            importance += 0.2

        # Attachments indicate detail
        if disclosure.get("attachment_count", 0) > 0:
            importance += 0.1

        return min(importance, 1.0)


# Singleton
kap_provider = KAPProvider()
