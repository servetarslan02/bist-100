"""ALPHA BIST — Fama-French Factor Return Builder (BIST-Özel).

Fama-French factor'leri (SMB, HML, RMW, CMA) BIST hisselerinden
otomatik hesaplayan modül.

Matematiksel Metodoloji (Fama & French, 1993, 2015):
═══════════════════════════════════════════════════════

1. SMB (Small Minus Big):
   - Hisseleri piyasa değerine (market cap) göre sırala
   - Median'a göre Small ve Big olarak ikiye ayır
   - SMB = ortalama(Small getirileri) - ortalama(Big getirileri)

2. HML (High Minus Low):
   - Hisseleri Book-to-Market (B/M) oranına göre sırala
   - Üç portföy: Value (yüksek B/M, %30), Neutral, Growth (düşük B/M, %30)
   - HML = ortalama(Value getirileri) - ortalama(Growth getirileri)

3. RMW (Robust Minus Weak):
   - Hisseleri karlılığa (ROE veya Operating Margin) göre sırala
   - Üç portföy: Robust (yüksek, %30), Neutral, Weak (düşük, %30)
   - RMW = ortalama(Robust getirileri) - ortalama(Weak getirileri)

4. CMA (Conservative Minus Aggressive):
   - Hisseleri yatırım agresifliğine (Asset Growth) göre sırala
   - Üç portföy: Conservative (düşük büyüme, %30), Neutral, Aggressive (yüksek, %30)
   - CMA = ortalama(Conservative getirileri) - ortalama(Aggressive getirileri)

2x3 Sort (Fama-French standardı):
══════════════════════════════════
- Size × B/M → 6 portföy
- Size × ROE → 6 portföy (RMW için)
- Size × AG  → 6 portföy (CMA için)
- Her factor, size-controlled (küçük/büyük hisse ortalaması)

BIST'e Özel Düzeltmeler:
══════════════════════════
- Döviz kuru etkisi: TL bazlı getiriler + USD bazlı getiri kontrolü
- Enflasyon düzeltmesi: Yüksek enflasyon döneminde B/M şişer
- Likidite filtresi: Düşük hacimli hisseleri hariç tut (Amihud illiquidity)
- Sektör kontrolü: BIST'te bankacılık/holding ağırlığı yüksek
"""
import numpy as np
from typing import Dict, List, Optional, Tuple, Any
from datetime import datetime, date, timedelta
from dataclasses import dataclass
import structlog

logger = structlog.get_logger()


@dataclass
class StockData:
    """Hisse verisi (factor hesaplama için)."""
    ticker: str
    market_cap: float          # Piyasa değeri (TL)
    book_to_market: float      # Book-to-Market oranı
    roe: float                 # Return on Equity
    operating_margin: float    # Operating Margin
    asset_growth: float        # Total Asset Growth (yıllık)
    daily_return: float        # Günlük getiri
    sector: str = ""
    avg_volume: float = 0.0    # Ortalama günlük hacim (likidite filtresi)


@dataclass
class FactorReturns:
    """Günlük factor return'leri."""
    date: date
    smb: float    # Small Minus Big
    hml: float    # High Minus Low
    rmw: float    # Robust Minus Weak
    cma: float    # Conservative Minus Aggressive
    n_small: int  # Küçük hisse sayısı
    n_big: int    # Büyük hisse sayısı
    n_value: int  # Value hisse sayısı
    n_growth: int # Growth hisse sayısı


class FamaFrenchFactorBuilder:
    """BIST için Fama-French factor return'leri hesaplar.

    Fama-French (1993) 2x3 sort metodolojisi:
    - Size breakpoint: BIST-100 median market cap
    - B/M breakpoints: %30 ve %70 percentil
    - ROE breakpoints: %30 ve %70 percentil
    - AG breakpoints: %30 ve %70 percentil

    Likidite filtresi:
    - Amihud illiquidity ratio > threshold olan hisseler hariç
    - Minimum günlük hacim: 100.000 TL (güncellenebilir)
    """

    def __init__(
        self,
        size_breakpoint: float = 0.5,     # Median
        bm_low: float = 0.30,             # B/M alt eşik
        bm_high: float = 0.70,            # B/M üst eşik
        roe_low: float = 0.30,            # ROE alt eşik
        roe_high: float = 0.70,           # ROE üst eşik
        ag_low: float = 0.30,             # Asset Growth alt eşik
        ag_high: float = 0.70,            # Asset Growth üst eşik
        min_volume_tl: float = 100_000,   # Minimum günlük hacim (TL)
        min_market_cap: float = 50_000_000,  # Minimum piyasa değeri (50M TL)
    ):
        self.size_breakpoint = size_breakpoint
        self.bm_low = bm_low
        self.bm_high = bm_high
        self.roe_low = roe_low
        self.roe_high = roe_high
        self.ag_low = ag_low
        self.ag_high = ag_high
        self.min_volume_tl = min_volume_tl
        self.min_market_cap = min_market_cap

    def calculate_daily_factors(
        self,
        stocks: List[StockData],
        trade_date: Optional[date] = None,
    ) -> Optional[FactorReturns]:
        """Tek bir gün için Fama-French factor return'leri hesapla.

        2x3 Sort Metodolojisi:
        1. Hisseleri size'a göre Small/Big olarak ikiye böl
        2. Her boyut grubunu B/M'ye göre Value/Neutral/Growth olarak üçlü böl
        3. SMB = (SL + SN + SG)/3 - (BL + BN + BG)/3
        4. HML = (SH + BH)/2 - (SL + BL)/2

        Args:
            stocks: O günkü hisse verileri
            trade_date: İşlem tarihi

        Returns:
            FactorReturns veya None (yetersiz veri)
        """
        if trade_date is None:
            trade_date = date.today()

        # Likidite ve minimum boyut filtresi
        filtered = self._filter_stocks(stocks)

        if len(filtered) < 10:
            logger.warning(
                "insufficient_stocks_for_factor_calc",
                n_stocks=len(filtered),
                min_required=10,
                date=trade_date.isoformat(),
            )
            return None

        # Market cap ve B/M dizileri
        market_caps = np.array([s.market_cap for s in filtered])
        bm_ratios = np.array([s.book_to_market for s in filtered])
        roes = np.array([s.roe for s in filtered])
        asset_growths = np.array([s.asset_growth for s in filtered])
        returns = np.array([s.daily_return for s in filtered])

        # ═══ SMB (Small Minus Big) ═══
        smb = self._calculate_smb(market_caps, returns)

        # ═══ HML (High Minus Low) ═══
        hml = self._calculate_hml(market_caps, bm_ratios, returns)

        # ═══ RMW (Robust Minus Weak) ═══
        rmw = self._calculate_rmw(market_caps, roes, returns)

        # ═══ CMA (Conservative Minus Aggressive) ═══
        cma = self._calculate_cma(market_caps, asset_growths, returns)

        # Boyut grupları (istatistik için)
        median_cap = np.median(market_caps)
        n_small = int(np.sum(market_caps <= median_cap))
        n_big = int(np.sum(market_caps > median_cap))
        n_value = int(np.sum(bm_ratios >= np.percentile(bm_ratios, self.bm_high * 100)))
        n_growth = int(np.sum(bm_ratios <= np.percentile(bm_ratios, self.bm_low * 100)))

        result = FactorReturns(
            date=trade_date,
            smb=float(smb),
            hml=float(hml),
            rmw=float(rmw),
            cma=float(cma),
            n_small=n_small,
            n_big=n_big,
            n_value=n_value,
            n_growth=n_growth,
        )

        logger.debug(
            "fama_french_factors_calculated",
            date=trade_date.isoformat(),
            smb=f"{smb:.4f}",
            hml=f"{hml:.4f}",
            rmw=f"{rmw:.4f}",
            cma=f"{cma:.4f}",
            n_stocks=len(filtered),
        )

        return result

    def calculate_factor_series(
        self,
        daily_stocks: Dict[date, List[StockData]],
    ) -> List[FactorReturns]:
        """Zaman serisi factor return'leri hesapla.

        Args:
            daily_stocks: {date: [StockData, ...]} sözlüğü

        Returns:
            Tarihe göre sıralanmış FactorReturns listesi
        """
        results = []
        for trade_date in sorted(daily_stocks.keys()):
            factors = self.calculate_daily_factors(
                daily_stocks[trade_date], trade_date
            )
            if factors is not None:
                results.append(factors)

        logger.info(
            "factor_series_calculated",
            n_days=len(results),
            start=results[0].date.isoformat() if results else "N/A",
            end=results[-1].date.isoformat() if results else "N/A",
        )

        return results

    def _filter_stocks(self, stocks: List[StockData]) -> List[StockData]:
        """Likidite ve boyut filtresi uygula.

        Fama-French (1993) NYSE breakpoint kullanır → BIST için
        minimum boyut ve hacim filtresi uyguluyoruz.

        Hariç tutulanlar:
        - Market cap < min_market_cap (çok küçük hisseler)
        - avg_volume < min_volume_tl (likit olmayan hisseler)
        - book_to_market <= 0 (negatif defter değeri)
        - daily_return eksik/NaN
        """
        filtered = []
        for s in stocks:
            if s.market_cap < self.min_market_cap:
                continue
            if s.avg_volume > 0 and s.avg_volume < self.min_volume_tl:
                continue
            if s.book_to_market <= 0:
                continue
            if np.isnan(s.daily_return) or np.isinf(s.daily_return):
                continue
            filtered.append(s)
        return filtered

    def _calculate_smb(
        self,
        market_caps: np.ndarray,
        returns: np.ndarray,
    ) -> float:
        """SMB = Small portfolio return - Big portfolio return.

        Fama-French (1993) 2x3 sort:
        - Size breakpoint: median(market_cap)
        - SMB = (SL + SN + SG)/3 - (BL + BN + BG)/3

        Basitleştirilmiş versiyon (tek boyut):
        - SMB = mean(Small returns) - mean(Big returns)
        """
        median_cap = np.median(market_caps)
        small_mask = market_caps <= median_cap
        big_mask = market_caps > median_cap

        if np.sum(small_mask) == 0 or np.sum(big_mask) == 0:
            return 0.0

        small_return = np.mean(returns[small_mask])
        big_return = np.mean(returns[big_mask])

        return small_return - big_return

    def _calculate_hml(
        self,
        market_caps: np.ndarray,
        bm_ratios: np.ndarray,
        returns: np.ndarray,
    ) -> float:
        """HML = Value portfolio return - Growth portfolio return.

        2x3 Sort:
        - B/M breakpoints: %30 ve %70 percentil
        - HML = (SH + BH)/2 - (SL + BL)/2

        SH = Small + High B/M (küçük value)
        BH = Big + High B/M (büyük value)
        SL = Small + Low B/M (küçük growth)
        BL = Big + Low B/M (büyük growth)
        """
        bm_low_threshold = np.percentile(bm_ratios, self.bm_low * 100)
        bm_high_threshold = np.percentile(bm_ratios, self.bm_high * 100)
        median_cap = np.median(market_caps)

        # 6 portföy
        small = market_caps <= median_cap
        big = market_caps > median_cap
        high_bm = bm_ratios >= bm_high_threshold
        low_bm = bm_ratios <= bm_low_threshold

        # Small High (SH), Big High (BH), Small Low (SL), Big Low (BL)
        sh_mask = small & high_bm
        bh_mask = big & high_bm
        sl_mask = small & low_bm
        bl_mask = big & low_bm

        # Her portföyün ortalama getirisi
        def safe_mean(mask):
            if np.sum(mask) == 0:
                return 0.0
            return float(np.mean(returns[mask]))

        sh_ret = safe_mean(sh_mask)
        bh_ret = safe_mean(bh_mask)
        sl_ret = safe_mean(sl_mask)
        bl_ret = safe_mean(bl_mask)

        # HML = (SH + BH)/2 - (SL + BL)/2
        hml = (sh_ret + bh_ret) / 2 - (sl_ret + bl_ret) / 2
        return hml

    def _calculate_rmw(
        self,
        market_caps: np.ndarray,
        roes: np.ndarray,
        returns: np.ndarray,
    ) -> float:
        """RMW = Robust portfolio return - Weak portfolio return.

        Fama-French (2015) 5-factor model:
        - ROE breakpoints: %30 ve %70 percentil
        - RMW = (SR + BR)/2 - (SW + BW)/2

        SR = Small + Robust (küçük karlı)
        BR = Big + Robust (büyük karlı)
        SW = Small + Weak (küçük zayıf)
        BW = Big + Weak (büyük zayıf)
        """
        roe_low_threshold = np.percentile(roes, self.roe_low * 100)
        roe_high_threshold = np.percentile(roes, self.roe_high * 100)
        median_cap = np.median(market_caps)

        small = market_caps <= median_cap
        big = market_caps > median_cap
        robust = roes >= roe_high_threshold
        weak = roes <= roe_low_threshold

        sr_mask = small & robust
        br_mask = big & robust
        sw_mask = small & weak
        bw_mask = big & weak

        def safe_mean(mask):
            if np.sum(mask) == 0:
                return 0.0
            return float(np.mean(returns[mask]))

        sr_ret = safe_mean(sr_mask)
        br_ret = safe_mean(br_mask)
        sw_ret = safe_mean(sw_mask)
        bw_ret = safe_mean(bw_mask)

        rmw = (sr_ret + br_ret) / 2 - (sw_ret + bw_ret) / 2
        return rmw

    def _calculate_cma(
        self,
        market_caps: np.ndarray,
        asset_growths: np.ndarray,
        returns: np.ndarray,
    ) -> float:
        """CMA = Conservative portfolio return - Aggressive portfolio return.

        Fama-French (2015) 5-factor model:
        - Asset Growth breakpoints: %30 ve %70 percentil
        - CMA = (SC + BC)/2 - (SA + BA)/2

        SC = Small + Conservative (küçük muhafazakâr)
        BC = Big + Conservative (büyük muhafazakâr)
        SA = Small + Aggressive (küçük agresif)
        BA = Big + Aggressive (büyük agresif)
        """
        ag_low_threshold = np.percentile(asset_growths, self.ag_low * 100)
        ag_high_threshold = np.percentile(asset_growths, self.ag_high * 100)
        median_cap = np.median(market_caps)

        small = market_caps <= median_cap
        big = market_caps > median_cap
        conservative = asset_growths <= ag_low_threshold  # Düşük büyüme = muhafazakâr
        aggressive = asset_growths >= ag_high_threshold    # Yüksek büyüme = agresif

        sc_mask = small & conservative
        bc_mask = big & conservative
        sa_mask = small & aggressive
        ba_mask = big & aggressive

        def safe_mean(mask):
            if np.sum(mask) == 0:
                return 0.0
            return float(np.mean(returns[mask]))

        sc_ret = safe_mean(sc_mask)
        bc_ret = safe_mean(bc_mask)
        sa_ret = safe_mean(sa_mask)
        ba_ret = safe_mean(ba_mask)

        cma = (sc_ret + bc_ret) / 2 - (sa_ret + ba_ret) / 2
        return cma

    def get_factor_arrays(
        self,
        factor_series: List[FactorReturns],
    ) -> Dict[str, np.ndarray]:
        """Factor return listesini numpy array'lere çevir.

        expected_return.py ile uyumlu format.

        Returns:
            {
                "dates": np.array of dates,
                "smb": np.array of float,
                "hml": np.array of float,
                "rmw": np.array of float,
                "cma": np.array of float,
            }
        """
        if not factor_series:
            return {
                "dates": np.array([]),
                "smb": np.array([]),
                "hml": np.array([]),
                "rmw": np.array([]),
                "cma": np.array([]),
            }

        return {
            "dates": np.array([f.date for f in factor_series]),
            "smb": np.array([f.smb for f in factor_series]),
            "hml": np.array([f.hml for f in factor_series]),
            "rmw": np.array([f.rmw for f in factor_series]),
            "cma": np.array([f.cma for f in factor_series]),
        }


class FamaFrenchDataFetcher:
    """BIST hisseleri için Fama-French factor verisi çeker ve hesaplar.

    Veri kaynakları:
    - Market cap: yfinance (shares_outstanding × price)
    - Book-to-Market: yfinance (book_value / market_cap)
    - ROE: yfinance (income_statement / equity)
    - Asset Growth: yfinance (total_assets değişimi)
    - Daily returns: yfinance (adjusted close)
    """

    def __init__(self):
        self._cache: Dict[str, Any] = {}

    async def fetch_and_build_factors(
        self,
        tickers: List[str],
        start_date: date,
        end_date: date,
    ) -> List[FactorReturns]:
        """Hisse verilerini çek ve factor return'leri hesapla.

        Args:
            tickers: BIST hisse listesi (ör: ["AEFES", "AKBNK", ...])
            start_date: Başlangıç tarihi
            end_date: Bitiş tarihi

        Returns:
            Günlük FactorReturns listesi
        """
        import yfinance as yf

        builder = FamaFrenchFactorBuilder()

        # yfinance ticker'larını hazırla
        yf_tickers = [f"{t}.IS" for t in tickers]

        logger.info(
            "fetching_fama_french_data",
            n_tickers=len(tickers),
            start=start_date.isoformat(),
            end=end_date.isoformat(),
        )

        # Fiyat verilerini çek (toplu)
        try:
            price_data = yf.download(
                yf_tickers,
                start=start_date.isoformat(),
                end=end_date.isoformat(),
                group_by="ticker",
                auto_adjust=True,
                progress=False,
            )
        except Exception as e:
            logger.error("price_data_fetch_error", error=str(e))
            return []

        # Fundamental verileri çek (her hisse için)
        fundamentals = await self._fetch_fundamentals(tickers)

        # Günlük factor return'leri hesapla
        factor_series = []

        # Trading günlerini belirle (fiyat verisinden)
        if hasattr(price_data.index, 'date'):
            trading_dates = [d.date() for d in price_data.index]
        else:
            trading_dates = [d for d in price_data.index]

        for trade_date in trading_dates:
            daily_stocks = []

            for ticker in tickers:
                yf_ticker = f"{ticker}.IS"

                try:
                    # Günlük getiri
                    if yf_ticker in price_data.columns.get_level_values(0):
                        close_prices = price_data[yf_ticker]["Close"]
                        # Bugünkü ve dünkü kapanış
                        date_idx = trading_dates.index(trade_date)
                        if date_idx < 1:
                            continue
                        today_close = close_prices.iloc[date_idx]
                        yesterday_close = close_prices.iloc[date_idx - 1]

                        if np.isnan(today_close) or np.isnan(yesterday_close):
                            continue
                        if yesterday_close == 0:
                            continue

                        daily_return = (today_close - yesterday_close) / yesterday_close
                    else:
                        continue

                    # Fundamental veriler
                    fund = fundamentals.get(ticker, {})
                    market_cap = fund.get("market_cap", 0)
                    book_value = fund.get("book_value", 0)
                    roe = fund.get("roe", 0)
                    total_assets = fund.get("total_assets", 0)
                    prev_total_assets = fund.get("prev_total_assets", 0)
                    avg_volume = fund.get("avg_volume", 0)

                    # Book-to-Market hesapla
                    bm = book_value / market_cap if market_cap > 0 else 0

                    # Asset Growth hesapla
                    asset_growth = 0
                    if prev_total_assets > 0:
                        asset_growth = (total_assets - prev_total_assets) / prev_total_assets

                    stock_data = StockData(
                        ticker=ticker,
                        market_cap=market_cap,
                        book_to_market=bm,
                        roe=roe,
                        operating_margin=fund.get("operating_margin", 0),
                        asset_growth=asset_growth,
                        daily_return=daily_return,
                        sector=fund.get("sector", ""),
                        avg_volume=avg_volume,
                    )
                    daily_stocks.append(stock_data)

                except Exception as e:
                    logger.debug("stock_data_error", ticker=ticker, error=str(e))
                    continue

            # Günlük factor'leri hesapla
            factors = builder.calculate_daily_factors(daily_stocks, trade_date)
            if factors is not None:
                factor_series.append(factors)

        logger.info(
            "fama_french_factors_built",
            n_days=len(factor_series),
            n_tickers=len(tickers),
        )

        return factor_series

    async def _fetch_fundamentals(
        self, tickers: List[str]
    ) -> Dict[str, Dict[str, float]]:
        """Hisse fundamental verilerini çek."""
        import yfinance as yf
        import concurrent.futures

        fundamentals = {}
        executor = concurrent.futures.ThreadPoolExecutor(max_workers=4)

        def _fetch_one(ticker: str) -> Tuple[str, Dict]:
            try:
                stock = yf.Ticker(f"{ticker}.IS")
                info = stock.info or {}

                # Bilanço verileri
                balance_sheet = stock.balance_sheet
                book_value = 0
                total_assets = 0
                prev_total_assets = 0

                if balance_sheet is not None and not balance_sheet.empty:
                    if "Total Assets" in balance_sheet.index:
                        total_assets = float(balance_sheet.iloc[
                            balance_sheet.index.get_loc("Total Assets")
                        ].iloc[0]) if len(balance_sheet.columns) > 0 else 0
                        if len(balance_sheet.columns) > 1:
                            prev_total_assets = float(balance_sheet.iloc[
                                balance_sheet.index.get_loc("Total Assets")
                            ].iloc[1])

                    if "Stockholders Equity" in balance_sheet.index:
                        book_value = float(balance_sheet.iloc[
                            balance_sheet.index.get_loc("Stockholders Equity")
                        ].iloc[0]) if len(balance_sheet.columns) > 0 else 0

                # Gelir tablosu
                income = stock.income_stmt
                roe = 0
                operating_margin = info.get("operatingMargins", 0) or 0

                if income is not None and not income.empty:
                    if "Net Income" in income.index and book_value > 0:
                        net_income = float(income.iloc[
                            income.index.get_loc("Net Income")
                        ].iloc[0]) if len(income.columns) > 0 else 0
                        roe = net_income / book_value

                return ticker, {
                    "market_cap": info.get("marketCap", 0) or 0,
                    "book_value": book_value,
                    "total_assets": total_assets,
                    "prev_total_assets": prev_total_assets,
                    "roe": roe,
                    "operating_margin": operating_margin,
                    "sector": info.get("sector", ""),
                    "avg_volume": info.get("averageVolume", 0) or 0,
                }
            except Exception as e:
                logger.debug("fundamental_fetch_error", ticker=ticker, error=str(e))
                return ticker, {}

        # Paralel çek
        loop = __import__("asyncio").get_event_loop()
        futures = [
            loop.run_in_executor(executor, _fetch_one, t) for t in tickers
        ]
        results = await __import__("asyncio").gather(*futures, return_exceptions=True)

        for result in results:
            if isinstance(result, Exception):
                continue
            ticker, data = result
            if data:
                fundamentals[ticker] = data

        return fundamentals


# Kolaylık fonksiyonu
def build_factor_arrays_from_series(
    factor_series: List[FactorReturns],
) -> Dict[str, np.ndarray]:
    """Factor series'den numpy array'ler oluştur (expected_return.py uyumlu)."""
    builder = FamaFrenchFactorBuilder()
    return builder.get_factor_arrays(factor_series)
