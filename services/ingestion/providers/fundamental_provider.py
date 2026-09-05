"""
ALPHA BIST — Fundamental Data Provider v2.0 (Async)

KAP ve yfinance'dan şirket finansal verilerini çeker:
- Bilanço (balance sheet)
- Gelir tablosu (income statement)
- Nakit akış (cash flow)
- Finansal oranlar (ratios)

v2.0: Async refactor + retry + rate limiter entegrasyonu
"""

import asyncio
import concurrent.futures
from datetime import UTC, datetime
from typing import Any

import structlog

logger = structlog.get_logger()


class FundamentalProvider:
    """Şirket finansal verilerini çeker (async)."""

    def __init__(self):
        """Otomatik eklendi."""
        self._cache: dict[str, dict] = {}
        self._cache_ttl_seconds = 3600  # 1 saat cache
        self._executor = concurrent.futures.ThreadPoolExecutor(max_workers=4)

    async def _run_sync(self, func, *args, timeout: int = 30, **kwargs) -> Any:
        """Blocking fonksiyonu async olarak çalıştır."""
        loop = asyncio.get_event_loop()
        try:
            return await asyncio.wait_for(
                loop.run_in_executor(self._executor, lambda: func(*args, **kwargs)),
                timeout=timeout,
            )
        except TimeoutError:
            logger.warning("Fundamental fetch timeout", timeout=timeout)
            return None

    def __repr__(self) -> str:
        return f"<FundamentalProvider(primary='tradingview', backups=['kap', 'yfinance'], cache_size={len(self._cache)})>"

    async def fetch_fundamentals(self, ticker: str) -> dict[str, Any] | None:
        """Ana fundamental veri çekme fonksiyonu (async).

        ÖNCELİK SIRASI:
        1. BİRİNCİL: TradingView Scanner API (Canlı rasyolar, çarpanlar ve finansallar)
        2. YEDEK 1: KAP (Resmi finansal tablolar ve çeyreklik bilançolar)
        3. YEDEK 2: yfinance (Alternatif global yedek)
        """
        # Cache kontrolü
        cached = self._cache.get(ticker)
        if cached:
            cached_time = cached.get("_cached_at", 0)
            if cached_time and (datetime.now(UTC).timestamp() - cached_time) < self._cache_ttl_seconds:
                return cached

        # 1. BİRİNCİL: TradingView'den çek
        result = await self._fetch_from_tradingview(ticker)
        if result:
            result["_cached_at"] = datetime.now(UTC).timestamp()
            result["_source"] = "tradingview_primary"
            self._cache[ticker] = result
            return result

        # 2. YEDEK 1: KAP'tan çek
        result = await self._fetch_from_kap(ticker)
        if result:
            result["_cached_at"] = datetime.now(UTC).timestamp()
            result["_source"] = "kap_backup"
            self._cache[ticker] = result
            return result

        # 3. YEDEK 2: yfinance'dan çek
        result = await self._fetch_from_yfinance(ticker)
        if result:
            result["_cached_at"] = datetime.now(UTC).timestamp()
            result["_source"] = "yfinance_backup"
            self._cache[ticker] = result
            return result

        logger.warning("No fundamental data found across all sources", ticker=ticker)
        return None

    async def _fetch_from_tradingview(self, ticker: str) -> dict[str, Any] | None:
        """TradingView Scanner API üzerinden hissenin birincil temel analiz rasyolarını çeker (async)."""
        sym = ticker.upper().replace(".IS", "").strip()
        cols = [
            "name",
            "description",
            "close",
            "market_cap_basic",
            "price_earnings_ttm",
            "price_book_fq",
            "dividend_yield_recent",
            "return_on_equity_fq",
            "return_on_assets_fq",
            "debt_to_equity_fq",
            "total_debt_fq",
            "total_revenue_fq",
            "ebitda",
        ]
        payload = {
            "filter": [{"left": "name", "operation": "match", "right": sym}],
            "options": {"lang": "tr"},
            "symbols": {"query": {"types": []}},
            "columns": cols,
            "range": [0, 1],
        }
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept": "application/json",
            "Content-Type": "application/json",
        }
        try:
            import httpx

            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post("https://scanner.tradingview.com/turkey/scan", json=payload, headers=headers)
                if resp.status_code == 200:
                    data = resp.json()
                    rows = data.get("data", [])
                    if rows:
                        d = rows[0].get("d", [])
                        raw = dict(zip(cols, d, strict=False))
                        pe = raw.get("price_earnings_ttm")
                        return {
                            "ticker": sym,
                            "fetch_date": datetime.now(UTC).isoformat(),
                            "source": "tradingview",
                            "market_cap": raw.get("market_cap_basic"),
                            "pe_ratio": float(pe) if pe is not None else None,
                            "forward_pe": None,
                            "pb_ratio": float(raw.get("price_book_fq")) if raw.get("price_book_fq") is not None else None,
                            "ps_ratio": None,
                            "ev_ebitda": None,
                            "ev_revenue": None,
                            "dividend_yield": float(raw.get("dividend_yield_recent")) if raw.get("dividend_yield_recent") is not None else None,
                            "earnings_yield": (1.0 / float(pe)) if (pe is not None and float(pe) > 0) else None,
                            "fcf_yield": None,
                            "gross_margin": None,
                            "ebitda_margin": None,
                            "operating_margin": None,
                            "profit_margin": None,
                            "roe": float(raw.get("return_on_equity_fq")) if raw.get("return_on_equity_fq") is not None else None,
                            "roa": float(raw.get("return_on_assets_fq")) if raw.get("return_on_assets_fq") is not None else None,
                            "revenue_growth": None,
                            "earnings_growth": None,
                            "revenue": float(raw.get("total_revenue_fq")) if raw.get("total_revenue_fq") is not None else None,
                            "net_income": None,
                            "ebitda": float(raw.get("ebitda")) if raw.get("ebitda") is not None else None,
                            "total_debt": float(raw.get("total_debt_fq")) if raw.get("total_debt_fq") is not None else None,
                            "total_cash": None,
                            "total_assets": None,
                            "total_equity": None,
                            "current_ratio": None,
                            "debt_to_equity": float(raw.get("debt_to_equity_fq")) if raw.get("debt_to_equity_fq") is not None else None,
                            "quick_ratio": None,
                        }
        except Exception as exc:
            logger.debug("TradingView fundamental fetch error", ticker=sym, error=str(exc))
        return None

    async def _fetch_from_yfinance(self, ticker: str) -> dict[str, Any] | None:
        """yfinance'dan finansal veri çek (async)."""
        try:
            import yfinance as yf

            def _fetch() -> Any:
                """Otomatik eklendi."""
                yf_ticker = f"{ticker}.IS"
                t = yf.Ticker(yf_ticker)
                info = t.info
                if not info or info.get("regularMarketPrice") is None:
                    return None

                return {
                    "ticker": ticker,
                    "fetch_date": datetime.now(UTC).isoformat(),
                    # Değerleme
                    "pe_ratio": info.get("trailingPE"),
                    "forward_pe": info.get("forwardPE"),
                    "pb_ratio": info.get("priceToBook"),
                    "ps_ratio": info.get("priceToSalesTrailing12Months"),
                    "ev_ebitda": info.get("enterpriseToEbitda"),
                    "ev_revenue": info.get("enterpriseToRevenue"),
                    "dividend_yield": info.get("dividendYield"),
                    "earnings_yield": (1.0 / info.get("trailingPE")) if (info.get("trailingPE") and info.get("trailingPE") > 0) else None,
                    "fcf_yield": None,
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

            result = await self._run_sync(_fetch, timeout=20)

            # FCF yield hesapla
            if result and result.get("free_cash_flow") and result.get("market_cap"):
                if result["market_cap"] > 0:
                    result["fcf_yield"] = result["free_cash_flow"] / result["market_cap"]

            return result

        except Exception as e:
            logger.debug("yfinance fundamental fetch failed", ticker=ticker, error=str(e))
            return None

    async def _fetch_from_kap(self, ticker: str) -> dict[str, Any] | None:
        """KAP'tan finansal veri çek (async)."""
        try:
            from .kap_provider import kap_provider

            return await kap_provider.fetch_financial_data(ticker)
        except Exception as e:
            logger.debug("KAP fundamental fetch failed", ticker=ticker, error=str(e))
            return None

    async def fetch_quarterly_financials(self, ticker: str, periods: int = 8) -> list[dict] | None:
        """Çeyreklik finansal veri çek (async)."""
        try:
            import yfinance as yf

            def _fetch() -> Any:
                """Otomatik eklendi."""
                yf_ticker = f"{ticker}.IS"
                t = yf.Ticker(yf_ticker)
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

            return await self._run_sync(_fetch, timeout=20)

        except Exception as e:
            logger.debug("Quarterly financials fetch failed", ticker=ticker, error=str(e))
            return None

    async def fetch_balance_sheet(self, ticker: str) -> dict[str, Any] | None:
        """Güncel bilanço verisi çek (async)."""
        try:
            import yfinance as yf

            def _fetch() -> Any:
                """Otomatik eklendi."""
                yf_ticker = f"{ticker}.IS"
                t = yf.Ticker(yf_ticker)
                bs = t.balance_sheet
                if bs is None or bs.empty:
                    return None
                latest = bs.iloc[:, 0]
                result = {"ticker": ticker, "period": str(bs.columns[0])}
                for idx in bs.index:
                    val = latest.get(idx)
                    if val is not None and str(val) != "nan":
                        result[idx.lower().replace(" ", "_")] = float(val)
                return result

            return await self._run_sync(_fetch, timeout=20)

        except Exception as e:
            logger.debug("Balance sheet fetch failed", ticker=ticker, error=str(e))
            return None

    async def fetch_cash_flow(self, ticker: str) -> dict[str, Any] | None:
        """Nakit akış tablosu çek (async)."""
        try:
            import yfinance as yf

            def _fetch() -> Any:
                """Otomatik eklendi."""
                yf_ticker = f"{ticker}.IS"
                t = yf.Ticker(yf_ticker)
                cf = t.cashflow
                if cf is None or cf.empty:
                    return None
                latest = cf.iloc[:, 0]
                result = {"ticker": ticker, "period": str(cf.columns[0])}
                for idx in cf.index:
                    val = latest.get(idx)
                    if val is not None and str(val) != "nan":
                        result[idx.lower().replace(" ", "_")] = float(val)
                return result

            return await self._run_sync(_fetch, timeout=20)

        except Exception as e:
            logger.debug("Cash flow fetch failed", ticker=ticker, error=str(e))
            return None

    async def get_valuation_summary(self, ticker: str) -> dict[str, Any] | None:
        """Değerleme özeti oluştur (async)."""
        fund = await self.fetch_fundamentals(ticker)
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
            summary["price_vs_52w_high"] = round((price / fund["fifty_two_week_high"] - 1) * 100, 2)
        if fund.get("fifty_two_week_low") and fund["fifty_two_week_low"] > 0:
            summary["price_vs_52w_low"] = round((price / fund["fifty_two_week_low"] - 1) * 100, 2)
        if fund.get("fifty_day_avg") and fund["fifty_day_avg"] > 0:
            summary["price_vs_50d_avg"] = round((price / fund["fifty_day_avg"] - 1) * 100, 2)
        if fund.get("two_hundred_day_avg") and fund["two_hundred_day_avg"] > 0:
            summary["price_vs_200d_avg"] = round((price / fund["two_hundred_day_avg"] - 1) * 100, 2)

        return summary

    def clear_cache(self, ticker: str | None = None) -> Any:
        """Cache temizle."""
        if ticker:
            self._cache.pop(ticker, None)
        else:
            self._cache.clear()


# Singleton
fundamental_provider = FundamentalProvider()
