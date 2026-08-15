"""
ALPHA BIST — Fundamental Data Provider v1.0

KAP ve yfinance'dan şirket finansal verilerini çeker:
- Bilanço (balance sheet)
- Gelir tablosu (income statement)
- Nakit akış (cash flow)
- Finansal oranlar (ratios)

FAZ 1.4: Fundamental Provider
"""

import requests
from datetime import datetime, timezone, date
from typing import Optional, List, Dict, Any
import structlog

logger = structlog.get_logger()


class FundamentalProvider:
    """Şirket finansal verilerini çeker."""

    def __init__(self):
        self._cache: Dict[str, Dict] = {}
        self._cache_ttl_seconds = 3600  # 1 saat cache

    def fetch_fundamentals(self, ticker: str) -> Optional[Dict[str, Any]]:
        """Ana fundamental veri çekme fonksiyonu.

        Önce yfinance'dan dener, başarısız olursa KAP'tan dener.
        """
        # Cache kontrolü
        cached = self._cache.get(ticker)
        if cached:
            cached_time = cached.get("_cached_at", 0)
            if (datetime.now(timezone.utc).timestamp() - cached_time) < self._cache_ttl_seconds:
                return cached

        # yfinance'dan çek
        result = self._fetch_from_yfinance(ticker)

        if result:
            result["_cached_at"] = datetime.now(timezone.utc).timestamp()
            result["_source"] = "yfinance"
            self._cache[ticker] = result
            return result

        # KAP'tan çek
        result = self._fetch_from_kap(ticker)
        if result:
            result["_cached_at"] = datetime.now(timezone.utc).timestamp()
            result["_source"] = "kap"
            self._cache[ticker] = result
            return result

        logger.warning("No fundamental data found", ticker=ticker)
        return None

    def _fetch_from_yfinance(self, ticker: str) -> Optional[Dict[str, Any]]:
        """yfinance'dan finansal veri çek."""
        try:
            import yfinance as yf
            yf_ticker = f"{ticker}.IS"
            t = yf.Ticker(yf_ticker)

            info = t.info
            if not info or info.get("regularMarketPrice") is None:
                return None

            result = {
                "ticker": ticker,
                "fetch_date": datetime.now(timezone.utc).isoformat(),

                # Değerleme
                "pe_ratio": info.get("trailingPE"),
                "forward_pe": info.get("forwardPE"),
                "pb_ratio": info.get("priceToBook"),
                "ps_ratio": info.get("priceToSalesTrailing12Months"),
                "ev_ebitda": info.get("enterpriseToEbitda"),
                "ev_revenue": info.get("enterpriseToRevenue"),
                "dividend_yield": info.get("dividendYield"),
                "earnings_yield": info.get("trailingPE"),
                "fcf_yield": None,  # Hesaplanacak

                # Kârlılık
                "gross_margin": info.get("grossMargins"),
                "ebitda_margin": info.get("ebitdaMargins"),
                "operating_margin": info.get("operatingMargins"),
                "profit_margin": info.get("profitMargins"),
                "roe": info.get("returnOnEquity"),
                "roa": info.get("returnOnAssets"),

                # Büyüme
                "revenue_growth": info.get("revenueGrowth"),
                "earnings_growth": info.get("earningsGrowth"),
                "revenue": info.get("totalRevenue"),
                "net_income": info.get("netIncomeToCommon"),
                "ebitda": info.get("ebitda"),

                # Bilanço
                "total_debt": info.get("totalDebt"),
                "total_cash": info.get("totalCash"),
                "total_assets": info.get("totalAssets"),
                "total_equity": info.get("bookValue"),
                "current_ratio": info.get("currentRatio"),
                "debt_to_equity": info.get("debtToEquity"),
                "free_cash_flow": info.get("freeCashflow"),
                "operating_cash_flow": info.get("operatingCashflow"),
                "capital_expenditure": info.get("capitalExpenditures"),

                # Piyasa
                "market_cap": info.get("marketCap"),
                "enterprise_value": info.get("enterpriseValue"),
                "shares_outstanding": info.get("sharesOutstanding"),
                "float_shares": info.get("floatShares"),
                "avg_volume": info.get("averageVolume"),
                "beta": info.get("beta"),

                # Fiyat
                "price": info.get("regularMarketPrice"),
                "fifty_two_week_high": info.get("fiftyTwoWeekHigh"),
                "fifty_two_week_low": info.get("fiftyTwoWeekLow"),
                "fifty_day_avg": info.get("fiftyDayAverage"),
                "two_hundred_day_avg": info.get("twoHundredDayAverage"),
            }

            # FCF yield hesapla
            if result.get("free_cash_flow") and result.get("market_cap") and result["market_cap"] > 0:
                result["fcf_yield"] = result["free_cash_flow"] / result["market_cap"]

            return result

        except Exception as e:
            logger.debug("yfinance fundamental fetch failed", ticker=ticker, error=str(e))
            return None

    def _fetch_from_kap(self, ticker: str) -> Optional[Dict[str, Any]]:
        """KAP'tan finansal veri çek."""
        try:
            from .kap_provider import kap_provider
            return kap_provider.fetch_company_financials(ticker)
        except Exception as e:
            logger.debug("KAP fundamental fetch failed", ticker=ticker, error=str(e))
            return None

    def fetch_quarterly_financials(self, ticker: str, periods: int = 8) -> Optional[List[Dict]]:
        """Çeyreklik finansal veri çek (trend analizi için)."""
        try:
            import yfinance as yf
            yf_ticker = f"{ticker}.IS"
            t = yf.Ticker(yf_ticker)

            # Quarterly financials
            qf = t.quarterly_financials
            if qf is None or qf.empty:
                return None

            results = []
            for col in qf.columns[:periods]:
                period_data = {
                    "period": col.strftime("%Y-%m-%d") if hasattr(col, "strftime") else str(col),
                    "ticker": ticker,
                }
                for idx in qf.index:
                    val = qf.loc[idx, col]
                    if val is not None and str(val) != "nan":
                        period_data[idx.lower().replace(" ", "_")] = float(val)
                results.append(period_data)

            return results

        except Exception as e:
            logger.debug("Quarterly financials fetch failed", ticker=ticker, error=str(e))
            return None

    def fetch_balance_sheet(self, ticker: str) -> Optional[Dict[str, Any]]:
        """Güncel bilanço verisi çek."""
        try:
            import yfinance as yf
            yf_ticker = f"{ticker}.IS"
            t = yf.Ticker(yf_ticker)

            bs = t.balance_sheet
            if bs is None or bs.empty:
                return None

            latest = bs.iloc[:, 0]  # En güncel dönem
            result = {"ticker": ticker, "period": str(bs.columns[0])}

            for idx in bs.index:
                val = latest.get(idx)
                if val is not None and str(val) != "nan":
                    result[idx.lower().replace(" ", "_")] = float(val)

            return result

        except Exception as e:
            logger.debug("Balance sheet fetch failed", ticker=ticker, error=str(e))
            return None

    def get_valuation_summary(self, ticker: str) -> Optional[Dict[str, Any]]:
        """Değerleme özeti oluştur."""
        fund = self.fetch_fundamentals(ticker)
        if not fund:
            return None

        price = fund.get("price", 0)
        if not price or price <= 0:
            return None

        summary = {
            "ticker": ticker,
            "price": price,
            "fetch_date": fund.get("fetch_date"),

            # Değerleme çarpanları
            "pe_ratio": fund.get("pe_ratio"),
            "pb_ratio": fund.get("pb_ratio"),
            "ev_ebitda": fund.get("ev_ebitda"),
            "fcf_yield": fund.get("fcf_yield"),
            "dividend_yield": fund.get("dividend_yield"),

            # Kârlılık
            "roe": fund.get("roe"),
            "roa": fund.get("roa"),
            "profit_margin": fund.get("profit_margin"),

            # Büyüme
            "revenue_growth": fund.get("revenue_growth"),
            "earnings_growth": fund.get("earnings_growth"),

            # Bilanço sağlığı
            "debt_to_equity": fund.get("debt_to_equity"),
            "current_ratio": fund.get("current_ratio"),

            # Fiyat konumu
            "price_vs_52w_high": None,
            "price_vs_52w_low": None,
            "price_vs_50d_avg": None,
            "price_vs_200d_avg": None,
        }

        # Fiyat konumu hesapla
        if fund.get("fifty_two_week_high") and fund["fifty_two_week_high"] > 0:
            summary["price_vs_52w_high"] = (price / fund["fifty_two_week_high"] - 1) * 100
        if fund.get("fifty_two_week_low") and fund["fifty_two_week_low"] > 0:
            summary["price_vs_52w_low"] = (price / fund["fifty_two_week_low"] - 1) * 100
        if fund.get("fifty_day_avg") and fund["fifty_day_avg"] > 0:
            summary["price_vs_50d_avg"] = (price / fund["fifty_day_avg"] - 1) * 100
        if fund.get("two_hundred_day_avg") and fund["two_hundred_day_avg"] > 0:
            summary["price_vs_200d_avg"] = (price / fund["two_hundred_day_avg"] - 1) * 100

        return summary

    def clear_cache(self, ticker: Optional[str] = None):
        """Cache temizle."""
        if ticker:
            self._cache.pop(ticker, None)
        else:
            self._cache.clear()


# Singleton
fundamental_provider = FundamentalProvider()
