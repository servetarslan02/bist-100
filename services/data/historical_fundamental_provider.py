"""
ALPHA BIST — Historical Fundamental Provider

yfinance quarterly financials + earnings_dates ile PIT-safe fundamental veri sağlar.

Her snapshot için:
- period_end: Finansal dönemin sonu (örn: 2025-06-30)
- available_at: Raporun açıklandığı tarih (earnings_date)
- values: Finansal metrikler

PIT kuralı: available_at <= backtest_date olan snapshot kullanılır.
"""

from typing import Dict, List
from datetime import datetime, timezone
import structlog

from ..data.historical_contracts import FundamentalSnapshot

logger = structlog.get_logger()


class HistoricalFundamentalProvider:
    """yfinance'dan PIT-safe historical fundamental veri çeker."""

    def __init__(self, cache_ttl_seconds: int = 3600):
        self._cache: Dict[str, List[FundamentalSnapshot]] = {}
        self._cache_ts: Dict[str, float] = {}
        self._cache_ttl = cache_ttl_seconds

    def fetch_historical_fundamentals(
        self,
        ticker: str,
        max_periods: int = 8,
    ) -> List[FundamentalSnapshot]:
        """Hisseye ait quarterly financial snapshot'ları çeker.

        Args:
            ticker: Hisse kodu (örn: THYAO)
            max_periods: Maksimum dönem sayısı

        Returns:
            FundamentalSnapshot listesi (en yeniden eskiye sıralı)
        """
        # Cache kontrolü
        now = datetime.now(timezone.utc).timestamp()
        if ticker in self._cache:
            if now - self._cache_ts.get(ticker, 0) < self._cache_ttl:
                return self._cache[ticker]

        snapshots = []

        try:
            import yfinance as yf
            yf_ticker = f"{ticker}.IS"
            t = yf.Ticker(yf_ticker)

            # Quarterly financials
            qf = t.quarterly_financials
            if qf is None or qf.empty:
                logger.warning("No quarterly financials", ticker=ticker)
                return []

            # Earnings dates (publication dates)
            earnings_dates = {}
            try:
                ed = t.earnings_dates
                if ed is not None and not ed.empty:
                    for idx in ed.index:
                        # Earnings date = raporun açıklandığı tarih
                        if hasattr(idx, 'date'):
                            earnings_dates[str(idx.date())] = str(idx.date())
            except Exception as e:
                logger.debug("Handled exception", error=str(e), context="historical_fundamental_provider.py:74")

            # Balance sheet (total_assets, total_equity vb. için)
            bs = t.quarterly_balance_sheet
            balance_sheet_data = {}
            if bs is not None and not bs.empty:
                for col in bs.columns[:max_periods]:
                    period_end = str(col.date()) if hasattr(col, 'date') else str(col)[:10]
                    balance_sheet_data[period_end] = {}
                    for metric in bs.index:
                        val = bs.loc[metric, col]
                        if val is not None and str(val) != 'nan':
                            balance_sheet_data[period_end][str(metric)] = float(val)

            # Her dönem için snapshot oluştur
            for i, col in enumerate(qf.columns[:max_periods]):
                period_end = str(col.date()) if hasattr(col, 'date') else str(col)[:10]

                # Publication date: earnings_dates'den bul
                # Earnings dates tarih sıralı, en yakın olanı eşleştir
                available_at = self._find_publication_date(
                    period_end, earnings_dates
                )

                # Finansal metrikleri topla
                values = {}
                for metric in qf.index:
                    val = qf.loc[metric, col]
                    if val is not None and str(val) != 'nan':
                        values[str(metric)] = float(val)

                # Balance sheet verilerini ekle
                if period_end in balance_sheet_data:
                    values.update(balance_sheet_data[period_end])

                # Ham metrikleri standart isimlere çevir
                mapped = self._map_metrics(values, ticker)

                if mapped:
                    snapshot = FundamentalSnapshot(
                        ticker=ticker,
                        period_end=period_end,
                        available_at=available_at,
                        values=mapped,
                        source="yfinance",
                        status="FRESH" if available_at else "UNKNOWN",
                    )
                    snapshots.append(snapshot)

            # En yeniden eskiye sırala
            snapshots.sort(key=lambda s: s.period_end, reverse=True)

            # Cache
            self._cache[ticker] = snapshots
            self._cache_ts[ticker] = now

            logger.info("Historical fundamentals fetched",
                       ticker=ticker, snapshots=len(snapshots))

        except Exception as e:
            logger.error("Historical fundamental fetch failed",
                        ticker=ticker, error=str(e))

        return snapshots

    def _find_publication_date(
        self,
        period_end: str,
        earnings_dates: Dict[str, str],
    ) -> str:
        """Dönem sonuna en yakın earnings date'i bul.

        earnings_dates raporun açıklandığı tarihi gösterir.
        period_end'den sonra gelen en yakın earnings_date = publication date.
        """
        # period_end'den sonra gelen en yakın earnings_date
        candidates = [
            ed for ed in sorted(earnings_dates.keys())
            if ed >= period_end
        ]

        if candidates:
            return candidates[0]

        # Bulunamazsa period_end + 60 gün tahmin et (güvenli taraf)
        try:
            from datetime import timedelta
            d = datetime.strptime(period_end, "%Y-%m-%d")
            estimated = d + timedelta(days=60)
            return estimated.strftime("%Y-%m-%d")
        except ValueError:
            return period_end

    def _map_metrics(
        self,
        raw_values: Dict[str, float],
        ticker: str,
    ) -> Dict[str, float]:
        """yfinance ham metriklerini standart isimlere çevir."""
        mapped = {}

        # Revenue
        for key in ['Total Revenue', 'Operating Revenue', 'Revenue']:
            if key in raw_values and raw_values[key] > 0:
                mapped['revenue'] = raw_values[key]
                break

        # Net income
        for key in ['Net Income', 'Net Income Common Stockholders']:
            if key in raw_values:
                mapped['net_income'] = raw_values[key]
                break

        # Operating income
        for key in ['Operating Income', 'EBIT']:
            if key in raw_values:
                mapped['operating_income'] = raw_values[key]
                break

        # Gross profit
        if 'Gross Profit' in raw_values:
            mapped['gross_profit'] = raw_values['Gross Profit']

        # EBITDA
        if 'EBITDA' in raw_values:
            mapped['ebitda'] = raw_values['EBITDA']

        # Free cash flow
        if 'Free Cash Flow' in raw_values:
            mapped['free_cash_flow'] = raw_values['Free Cash Flow']

        # Operating cash flow
        if 'Operating Cash Flow' in raw_values:
            mapped['operating_cash_flow'] = raw_values['Operating Cash Flow']

        # Capital expenditure
        if 'Capital Expenditure' in raw_values:
            mapped['capital_expenditure'] = raw_values['Capital Expenditure']

        # Shares outstanding
        if 'Basic Average Shares' in raw_values:
            mapped['shares_outstanding'] = raw_values['Basic Average Shares']

        # EPS
        if 'Diluted EPS' in raw_values:
            mapped['eps'] = raw_values['Diluted EPS']

        # Derived metrics
        revenue = mapped.get('revenue', 0)
        net_income = mapped.get('net_income', 0)
        gross_profit = mapped.get('gross_profit', 0)
        operating_income = mapped.get('operating_income', 0)
        free_cash_flow = mapped.get('free_cash_flow', 0)

        if revenue and revenue > 0:
            if net_income:
                mapped['profit_margin'] = net_income / revenue
            if gross_profit:
                mapped['gross_margin'] = gross_profit / revenue
            if operating_income:
                mapped['operating_margin'] = operating_income / revenue
            if free_cash_flow:
                mapped['fcf_margin'] = free_cash_flow / revenue

        return mapped

    def clear_cache(self):
        self._cache.clear()
        self._cache_ts.clear()
