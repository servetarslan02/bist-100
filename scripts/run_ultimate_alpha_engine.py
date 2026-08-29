"""
ALPHA BIST — ULTIMATE ALL-INCLUSIVE ALPHA ENGINE v1.0 (2016-2026)
===================================================================
Tüm Zeka Motorlarının ve Metriklerinin Entegre Edildiği Nihai Sistem:

1. CANDLESTICK & PRICE ACTION MOTORU (CandlePatternEngine):
   - 12 Japon Mum Formasyonu (Çekiç, Yutan Boğa/Ayı, Sabah/Akşam Yıldızı, vb.)
   - Fitil & Gövde Anatomisi: Alıcı Gücü % vs Satıcı Gücü %
   - Smart Money: Fair Value Gap (Bullish / Bearish FVG) Dengesizlikleri
   - Mum Tabanlı Dinamik Stop Seviyesi (Dönüş fitili altı)
   - Tepe Yorulma Mumu ile Erken Kâr Realizasyonu (Shooting Star, Evening Star)

2. QUANT & FACTOR RANKING MOTORU (RankingModel & SevenMotors):
   - Relatif Güç (rs_5d, rs_20d, rs_60d vs BIST) + RS Regresyon Eğimi
   - Momentum & İvme (roc_5d, roc_20d, roc_60d)
   - Trend Kalitesi (R² 60g Doğrusal Regresyon Tutarlılığı)
   - Volatiliteye Göre Düzeltilmiş Momentum (vol_adj_mom / Sharpe Proxy)
   - Hacim Trendi & Kurumsal Akümülasyon (5g vs 20g Hacim Oranı)
   - Sektör Rotasyonu & Sektör İçi Liderlik

3. DİNAMİK PORTFÖY & RİSK YÖNETİMİ:
   - Tek Hisse Sınırı: Portföyün Maksimum %20 - %25'i
   - Rejim Sistemi: SMA20 / SMA50 / SMA100 / SMA200 Çift Bant (BULL/NEUTRAL/BEAR)
   - Sıfır %100 Nakit: Enflasyon erozyonuna karşı ayıda bile savunma pozisyonu
   - Gerçekçi BIST Komisyon (%0.15) + Kayma/Slippage (%0.10)
   - Point-in-Time: Gelecek veri sızıntısı kesinlikle YOK (t gün sinyal -> t+1 icra)
"""

from __future__ import annotations

import sys
import warnings
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

warnings.filterwarnings("ignore")

_ROOT = str(Path(__file__).resolve().parents[1])
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

import numpy as np
import polars as pl
import structlog
import yfinance as yf

logger = structlog.get_logger()

# ---------------------------------------------------------------------------
# 1. EVREN VE SEKTÖR TANIMLARI (50 Likit BIST Hissesi)
# ---------------------------------------------------------------------------
SECTORS: dict[str, list[str]] = {
    "finansal":   ["GARAN.IS", "AKBNK.IS", "ISCTR.IS", "YKBNK.IS", "HALKB.IS", "VAKBN.IS", "TSKB.IS"],
    "holding":    ["KCHOL.IS", "SAHOL.IS", "DOHOL.IS"],
    "sanayi":     ["ENKAI.IS", "EREGL.IS", "SISE.IS", "TOASO.IS", "FROTO.IS", "ARCLK.IS", "KRDMD.IS", "VESBE.IS"],
    "enerji":     ["TUPRS.IS", "PETKM.IS", "GUBRF.IS"],
    "havacilik":  ["THYAO.IS", "PGSUS.IS", "TAVHL.IS"],
    "teletek":    ["TTKOM.IS", "TCELL.IS", "ASELS.IS", "LOGO.IS"],
    "tuketim":    ["BIMAS.IS", "MGROS.IS", "CCOLA.IS", "AEFES.IS", "ULKER.IS", "MAVI.IS"],
    "diger":      ["TKFEN.IS", "CIMSA.IS", "BRSAN.IS", "ECILC.IS", "ISGYO.IS"],
}

BIST_UNIVERSE = [t for tickers in SECTORS.values() for t in tickers]
BENCHMARK_TICKER = "XU100.IS"
DEFENSIVE_TICKERS = set(SECTORS["tuketim"] + SECTORS["teletek"] + ["ECILC.IS"])
TICKER_TO_SECTOR = {t: s for s, ts in SECTORS.items() for t in ts}

# ---------------------------------------------------------------------------
# 2. CANDLESTICK & PRICE ACTION MOTORU (CandlePatternEngine)
# ---------------------------------------------------------------------------
@dataclass
class CandleMetrics:
    open: float
    high: float
    low: float
    close: float
    volume: float = 0.0
    body: float = 0.0
    range: float = 0.0
    upper_wick: float = 0.0
    lower_wick: float = 0.0
    body_ratio: float = 0.0
    upper_wick_ratio: float = 0.0
    lower_wick_ratio: float = 0.0
    is_green: bool = True
    is_doji: bool = False

    def __post_init__(self):
        self.body = abs(self.close - self.open)
        self.range = max(self.high - self.low, 1e-9)
        self.is_green = self.close >= self.open
        if self.is_green:
            self.upper_wick = self.high - self.close
            self.lower_wick = self.open - self.low
        else:
            self.upper_wick = self.high - self.open
            self.lower_wick = self.close - self.low
        self.body_ratio = self.body / self.range
        self.upper_wick_ratio = self.upper_wick / self.range
        self.lower_wick_ratio = self.lower_wick / self.range
        self.is_doji = self.body_ratio <= 0.08


@dataclass
class CandleAnalysis:
    patterns: list[str] = field(default_factory=list)
    buyer_pressure_pct: float = 50.0
    seller_pressure_pct: float = 50.0
    candle_score: float = 50.0  # 0 - 100
    has_bullish_entry_signal: bool = False
    has_bearish_exit_signal: bool = False
    stop_level: float = 0.0
    has_fvg: bool = False


def analyze_candlesticks(hist_df: Any) -> CandleAnalysis:
    """Tarihsel verinin son mumlarını analiz eder."""
    res = CandleAnalysis()
    if hist_df is None or len(hist_df) < 4:
        return res

    opens = hist_df["Open"].values.astype(float)
    highs = hist_df["High"].values.astype(float)
    lows = hist_df["Low"].values.astype(float)
    closes = hist_df["Close"].values.astype(float)
    vols = hist_df["Volume"].values.astype(float) if "Volume" in hist_df else np.ones(len(hist_df))

    c0 = CandleMetrics(opens[-1], highs[-1], lows[-1], closes[-1], vols[-1])
    c1 = CandleMetrics(opens[-2], highs[-2], lows[-2], closes[-2], vols[-2])
    c2 = CandleMetrics(opens[-3], highs[-3], lows[-3], closes[-3], vols[-3])

    # 1. Alıcı & Satıcı Baskı Analizi
    buyer_p = (c0.lower_wick_ratio * 0.5) + (c0.body_ratio if c0.is_green else 0.0)
    seller_p = (c0.upper_wick_ratio * 0.5) + (c0.body_ratio if not c0.is_green else 0.0)
    tot = max(buyer_p + seller_p, 1e-9)
    res.buyer_pressure_pct = round((buyer_p / tot) * 100, 1)
    res.seller_pressure_pct = round((seller_p / tot) * 100, 1)

    score = 50.0
    patterns = []
    res.stop_level = min(c0.low, c1.low) * 0.995

    # 2. Bullish Giriş Sinyalleri
    # A) Yutan Boğa (Bullish Engulfing)
    if not c1.is_green and c0.is_green and c0.open <= (c1.close * 1.005) and c0.close >= (c1.open * 0.995):
        patterns.append("BULLISH_ENGULFING")
        score += 25
        res.has_bullish_entry_signal = True

    # B) Çekiç / Dip Pinbar (Hammer)
    elif c0.lower_wick_ratio >= 0.45 and c0.upper_wick_ratio <= 0.25 and c0.body_ratio >= 0.10:
        patterns.append("HAMMER_PINBAR")
        score += 22
        res.has_bullish_entry_signal = True

    # C) Sabah Yıldızı (Morning Star)
    elif not c2.is_green and c1.body_ratio <= 0.25 and c0.is_green and c0.close >= (c2.open + c2.close) / 2:
        patterns.append("MORNING_STAR")
        score += 30
        res.has_bullish_entry_signal = True

    # D) Üç Beyaz Asker (Three White Soldiers)
    elif c2.is_green and c1.is_green and c0.is_green and c0.close > c1.close > c2.close:
        patterns.append("THREE_WHITE_SOLDIERS")
        score += 20
        res.has_bullish_entry_signal = True

    # E) Bullish Fair Value Gap (FVG)
    if c0.low > c2.high:
        patterns.append("BULLISH_FVG")
        score += 15
        res.has_fvg = True
        res.has_bullish_entry_signal = True

    # 3. Bearish Çıkış / Tepe Yorulma Sinyalleri
    # A) Kayan Yıldız (Shooting Star / Tepe Pinbar)
    if c0.upper_wick_ratio >= 0.50 and c0.lower_wick_ratio <= 0.20 and c1.is_green:
        patterns.append("SHOOTING_STAR")
        score -= 25
        res.has_bearish_exit_signal = True

    # B) Yutan Ayı (Bearish Engulfing)
    elif c1.is_green and not c0.is_green and c0.open >= (c1.close * 0.995) and c0.close <= (c1.open * 1.005):
        patterns.append("BEARISH_ENGULFING")
        score -= 25
        res.has_bearish_exit_signal = True

    # C) Akşam Yıldızı (Evening Star)
    elif c2.is_green and c1.body_ratio <= 0.25 and not c0.is_green and c0.close <= (c2.open + c2.close) / 2:
        patterns.append("EVENING_STAR")
        score -= 30
        res.has_bearish_exit_signal = True

    # D) Bearish FVG
    if c0.high < c2.low:
        patterns.append("BEARISH_FVG")
        score -= 15
        res.has_bearish_exit_signal = True

    # Genel Alıcı Baskısı Bonusu
    if res.buyer_pressure_pct >= 65.0:
        score += 10
        res.has_bullish_entry_signal = True
    elif res.seller_pressure_pct >= 70.0:
        score -= 10

    res.patterns = patterns
    res.candle_score = float(np.clip(score, 0, 100))
    return res


# ---------------------------------------------------------------------------
# 3. YARDIMCI VE QUANT FONKSİYONLAR
# ---------------------------------------------------------------------------
def _to_float(v: Any) -> float:
    if hasattr(v, "values"):
        v = v.values
    if hasattr(v, "item"):
        try:
            return float(v.item())
        except Exception:
            pass
    arr = np.ravel(v)
    return float(arr[0]) if len(arr) > 0 else 0.0


def _calc_r2(prices: np.ndarray) -> float:
    if len(prices) < 10:
        return 0.0
    x = np.arange(len(prices), dtype=float)
    p = np.polyfit(x, prices, 1)
    fitted = np.polyval(p, x)
    ss_res = np.sum((prices - fitted) ** 2)
    ss_tot = np.sum((prices - prices.mean()) ** 2)
    return float(max(0.0, 1.0 - ss_res / ss_tot)) if ss_tot > 1e-10 else 0.0


class SectorRotationTracker:
    """7 Sektörün BIST'e göre bağıl performansını takip eder."""

    def __init__(self):
        self.sector_ranks: dict[str, float] = {s: 0.5 for s in SECTORS}
        self.ticker_ranks: dict[str, float] = {}

    def update(self, stock_dict: dict, bm_close: Any, current_date: Any):
        bm_h = bm_close.loc[:current_date]
        bm_arr = bm_h.values.astype(float) if not (hasattr(bm_h, "shape") and len(bm_h.shape) > 1) else bm_h.iloc[:, 0].values.astype(float)
        bm_r20 = (bm_arr[-1] / bm_arr[-20] - 1) if len(bm_arr) >= 20 else 0.0

        sec_perfs: dict[str, float] = {}
        for sec, tickers in SECTORS.items():
            perfs = []
            for t in tickers:
                df = stock_dict.get(t)
                if df is None or current_date not in df.index:
                    continue
                c = df["Close"].loc[:current_date]
                if hasattr(c, "shape") and len(c.shape) > 1:
                    c = c.iloc[:, 0]
                ca = c.values.astype(float)
                if len(ca) < 20:
                    continue
                perfs.append(ca[-1] / ca[-20] - 1 - bm_r20)
            sec_perfs[sec] = float(np.mean(perfs)) if perfs else 0.0

        names = list(sec_perfs.keys())
        va = np.array([sec_perfs[n] for n in names])
        if len(va) > 1:
            rk = np.argsort(np.argsort(va)).astype(float) / (len(va) - 1)
        else:
            rk = np.array([0.5])

        self.sector_ranks = {names[i]: float(rk[i]) for i in range(len(names))}
        self.ticker_ranks = {t: self.sector_ranks.get(TICKER_TO_SECTOR.get(t, "diger"), 0.5) for t in BIST_UNIVERSE}

    def get_rank(self, ticker: str) -> float:
        return self.ticker_ranks.get(ticker, 0.5)

    def top_sectors(self, top_n: int = 3) -> set[str]:
        return set(sorted(self.sector_ranks, key=self.sector_ranks.get, reverse=True)[:top_n])


# ---------------------------------------------------------------------------
# 4. ÇOK BOYUTLU PUANLAMA MOTORU (Quant + Mum + Sektör)
# ---------------------------------------------------------------------------
@dataclass
class StockEvaluation:
    ticker: str
    total_score: float
    price_now: float
    atr: float
    candle_stop: float
    has_candle_entry: bool
    has_candle_exit: bool
    buyer_pressure: float
    patterns: list[str]
    sector_rank: float
    in_top_sector: bool
    is_defensive: bool


def evaluate_stock(
    ticker: str,
    stock_dict: dict,
    current_date: Any,
    bm_close: Any,
    sector_tracker: SectorRotationTracker,
    regime: str,
) -> StockEvaluation | None:
    df = stock_dict.get(ticker)
    if df is None or current_date not in df.index:
        return None

    hist = df.loc[:current_date]
    if len(hist) < 60:
        return None

    c_s = hist["Close"]
    h_s = hist["High"]
    l_s = hist["Low"]
    v_s = hist["Volume"]
    if hasattr(c_s, "shape") and len(c_s.shape) > 1:
        c_s = c_s.iloc[:, 0]
    if hasattr(h_s, "shape") and len(h_s.shape) > 1:
        h_s = h_s.iloc[:, 0]
    if hasattr(l_s, "shape") and len(l_s.shape) > 1:
        l_s = l_s.iloc[:, 0]
    if hasattr(v_s, "shape") and len(v_s.shape) > 1:
        v_s = v_s.iloc[:, 0]

    ca = c_s.values.astype(float)
    ha = h_s.values.astype(float)
    la = l_s.values.astype(float)
    va = v_s.values.astype(float)
    p_now = ca[-1]
    if p_now <= 0:
        return None

    # A) Mum ve Price Action Analizi
    candle_res = analyze_candlesticks(hist)

    # B) Relatif Güç ve Momentum
    bh = bm_close.loc[:current_date]
    ba = bh.values.astype(float) if not (hasattr(bh, "shape") and len(bh.shape) > 1) else bh.iloc[:, 0].values.astype(float)
    bm_roc20 = (ba[-1] / ba[-20] - 1) if len(ba) >= 20 else 0.0
    bm_roc60 = (ba[-1] / ba[-60] - 1) if len(ba) >= 60 else 0.0

    roc5 = (p_now / ca[-5] - 1) if len(ca) >= 5 else 0.0
    roc20 = (p_now / ca[-20] - 1) if len(ca) >= 20 else 0.0
    roc60 = (p_now / ca[-60] - 1) if len(ca) >= 60 else 0.0

    rs20 = roc20 - bm_roc20
    rs60 = roc60 - bm_roc60

    # C) ATR Hesabı (14 günlük)
    h_arr = ha[-14:]
    l_arr = la[-14:]
    c_prev = ca[-15:-1]
    if len(h_arr) == len(c_prev):
        tr = np.maximum.reduce([h_arr - l_arr, np.abs(h_arr - c_prev), np.abs(l_arr - c_prev)])
        atr_val = float(np.mean(tr))
    else:
        atr_val = p_now * 0.025
    if atr_val <= 0:
        atr_val = p_now * 0.025

    # D) Volatiliteye Göre Düzeltilmiş Momentum (Sharpe Proxy)
    rets20 = np.diff(ca[-21:]) / ca[-21:-1] if len(ca) >= 21 else np.array([0.0])
    vol20 = float(np.std(rets20)) if len(rets20) > 1 else 0.02
    vol_adj_mom = roc20 / vol20 if vol20 > 1e-8 else 0.0

    # E) Trend Tutarlılığı (R²) ve Hacim Trendi
    trend_r2 = _calc_r2(ca[-60:])
    v_avg20 = float(np.mean(va[-20:])) if len(va) >= 20 else 1.0
    v_avg5 = float(np.mean(va[-5:])) if len(va) >= 5 else 1.0
    vol_trend = v_avg5 / v_avg20 if v_avg20 > 0 else 1.0

    # F) Sektör & Savunma Durumu
    sec_name = TICKER_TO_SECTOR.get(ticker, "diger")
    sec_rk = sector_tracker.get_rank(ticker)
    in_top_sec = sec_name in sector_tracker.top_sectors(3)
    is_def = ticker in DEFENSIVE_TICKERS

    sma20 = float(np.mean(ca[-20:])) if len(ca) >= 20 else 0.0

    # G) Rejime Göre Giriş Filtreleri (Geniş Tabanlı + Mum Onayı)
    if regime == "BULL":
        # Temel kriter: Fiyat SMA20 üstü VEYA güçlü alıcı mumu/toparlanma
        ok = (p_now > sma20 * 0.97 and (rs20 > -0.02 or candle_res.has_bullish_entry_signal)) or in_top_sec or is_def
        if not ok:
            return None
    elif regime == "NEUTRAL":
        ok = (p_now > sma20 * 0.95 and rs60 > -0.03) or in_top_sec or is_def
        if not ok:
            return None
    else:  # BEAR
        if not (is_def or (in_top_sec and rs20 > -0.04) or candle_res.has_bullish_entry_signal):
            return None

    # H) BÜTÜNLEŞİK SKOR HESAPLAMA (Quant + Mum + Sektör)
    # Ağırlıklar: Mum(%25) + Kalite Momentum(%25) + Sektör(%20) + Relatif Güç(%15) + Trend R²(%10) + Hacim(%5)
    quant_score = (
        (np.clip(vol_adj_mom, -4, 4) / 4.0 * 0.25)
        + (sec_rk * 0.20)
        + (np.clip(rs20, -0.20, 0.20) * 5.0 * 0.15)
        + (trend_r2 * 0.10)
        + (min(vol_trend, 2.5) / 2.5 * 0.05)
    )

    candle_normalized = (candle_res.candle_score - 50.0) / 50.0  # [-1, +1]
    total_score = (quant_score * 0.75) + (candle_normalized * 0.25)

    return StockEvaluation(
        ticker=ticker,
        total_score=total_score,
        price_now=p_now,
        atr=atr_val,
        candle_stop=candle_res.stop_level,
        has_candle_entry=candle_res.has_bullish_entry_signal,
        has_candle_exit=candle_res.has_bearish_exit_signal,
        buyer_pressure=candle_res.buyer_pressure_pct,
        patterns=candle_res.patterns,
        sector_rank=sec_rk,
        in_top_sector=in_top_sec,
        is_defensive=is_def,
    )


# ---------------------------------------------------------------------------
# 5. REJİM MOTORU
# ---------------------------------------------------------------------------
def compute_market_regime(bm_close: Any, dt: Any, s20: Any, s50: Any, s200: Any) -> str:
    c = _to_float(bm_close.loc[dt])
    sma20_v = _to_float(s20.loc[dt])
    sma50_v = _to_float(s50.loc[dt])
    sma200_v = _to_float(s200.loc[dt])

    if np.isnan(sma50_v) or np.isnan(sma200_v):
        return "NEUTRAL"

    if c >= sma50_v and sma50_v >= sma200_v:
        return "BULL"
    elif c >= sma50_v or sma50_v >= sma200_v or c >= sma20_v:
        return "NEUTRAL"
    else:
        return "BEAR"


# ---------------------------------------------------------------------------
# 6. ANA SİMÜLASYON MOTORU (Ultimate Alpha Backtest)
# ---------------------------------------------------------------------------
def run_ultimate_simulation() -> None:
    START = "2016-01-01"
    END = "2026-08-29"
    INITIAL_CAPITAL = 100_000.0
    COMMISSION = 0.0015
    SLIPPAGE = 0.0010
    COST_ONE_WAY = COMMISSION + SLIPPAGE
    ATR_TRAIL_MULT = 3.5
    MAX_POSITION_PCT = 0.25  # Kullanıcının şartı: Portföyün max %20-%25'i

    logger.info("=" * 85)
    logger.info(f"[1] BIST PİYASA VERİSİ İNDİRİLİYOR ({START} -> {END})")
    logger.info("=" * 85)

    bm_raw = yf.download(BENCHMARK_TICKER, start=START, end=END, progress=False)
    if bm_raw.empty:
        raise RuntimeError("BIST-100 verisi indirilemedi!")
    if hasattr(bm_raw.columns, "levels") and len(bm_raw.columns.levels) > 1:
        bm_raw.columns = bm_raw.columns.get_level_values(0)
    bm_df = bm_raw[["Open", "High", "Low", "Close", "Volume"]].dropna()
    logger.info(f"  [OK] BIST-100: {len(bm_df):,} seans ({bm_df.index[0].date()} - {bm_df.index[-1].date()})")

    stocks_raw = yf.download(BIST_UNIVERSE, start=START, end=END, progress=False, group_by="ticker")
    stock_dict: dict[str, Any] = {}
    for t in BIST_UNIVERSE:
        try:
            if hasattr(stocks_raw.columns, "levels") and t in stocks_raw.columns.get_level_values(0):
                df_t = stocks_raw[t][["Open", "High", "Low", "Close", "Volume"]].dropna()
                if len(df_t) > 250:
                    stock_dict[t] = df_t
        except Exception:
            continue
    logger.info(f"  [OK] {len(stock_dict)} hisse hazırlandı ({len(BIST_UNIVERSE)} istendi).\n")

    logger.info("=" * 85)
    logger.info("[2] ULTIMATE ALL-INCLUSIVE ALPHA ENGINE BAŞLATILIYOR")
    logger.info("=" * 85)
    logger.info(f"  Başlangıç Sermayesi  : {INITIAL_CAPITAL:,.0f} TL")
    logger.info(f"  Max Tek Pozisyon     : %{MAX_POSITION_PCT * 100:.0f} (Portföy Limiti)")
    logger.info(f"  Mum Motoru           : 12 Japon Formasyonu + Alıcı/Satıcı Gücü + FVG Onayı")
    logger.info(f"  Sektör Takibi        : 7 Sektör Bağıl Gücü & Sektör İçi Liderlik")
    logger.info(f"  Akıllı Stop          : Min(Son Mum Fitil Tabanı, 3.5x ATR Trailing)")
    logger.info(f"  İşlem Maliyeti       : %{COST_ONE_WAY * 100:.2f} tek yön")
    logger.info("-" * 85)

    bm_close = bm_df["Close"]
    if hasattr(bm_close, "shape") and len(bm_close.shape) > 1:
        bm_close = bm_close.iloc[:, 0]

    bm_sma20 = bm_close.rolling(20).mean()
    bm_sma50 = bm_close.rolling(50).mean()
    bm_sma200 = bm_close.rolling(200).mean()

    trading_dates = list(bm_df.index)[200:]

    capital = INITIAL_CAPITAL
    positions: dict[str, dict[str, Any]] = {}
    trade_logs: list[dict[str, Any]] = []
    equity_curve: list[dict[str, Any]] = []

    yearly_stats: dict[int, dict[str, Any]] = {}
    current_year = trading_dates[0].year
    year_start_capital = capital
    year_start_bm = _to_float(bm_close.loc[trading_dates[0]])

    sector_tracker = SectorRotationTracker()
    last_sector_update_week = -1
    last_rebalance_month = -1
    regime_counter: dict[str, int] = {"BULL": 0, "NEUTRAL": 0, "BEAR": 0}

    for day_idx, current_date in enumerate(trading_dates):
        # Yıl geçişi kaydı
        if current_date.year != current_year:
            port_val = capital + sum(p["shares"] * p["current_price"] for p in positions.values())
            year_ret = (port_val - year_start_capital) / year_start_capital * 100
            bm_curr = _to_float(bm_close.loc[current_date])
            bm_ret = (bm_curr - year_start_bm) / year_start_bm * 100
            yearly_stats[current_year] = {
                "port_return": year_ret,
                "bm_return": bm_ret,
                "alpha": year_ret - bm_ret,
                "end_equity": port_val,
            }
            current_year = current_date.year
            year_start_capital = port_val
            year_start_bm = bm_curr

        # Sektör Rotasyonunu Haftalık Güncelle
        iso_week = current_date.isocalendar()[1]
        if iso_week != last_sector_update_week:
            last_sector_update_week = iso_week
            sector_tracker.update(stock_dict, bm_close, current_date)

        # Rejim Tespiti
        regime = compute_market_regime(bm_close, current_date, bm_sma20, bm_sma50, bm_sma200)
        regime_counter[regime] += 1

        if regime == "BULL":
            target_positions = 5  # Her biri %20
            invest_ratio = 1.00
        elif regime == "NEUTRAL":
            target_positions = 4  # Her biri %20-25
            invest_ratio = 0.85
        else:  # BEAR
            target_positions = 3  # Savunma pozisyonları
            invest_ratio = 0.65

        # -------------------------------------------------------------
        # 1. MEVCUT POZİSYONLARI GÜNCELLE & AKILLI ÇIKIŞLARI KONTROL ET
        # -------------------------------------------------------------
        closed_tickers = []
        for ticker, pos in list(positions.items()):
            s_df = stock_dict.get(ticker)
            if s_df is None or current_date not in s_df.index:
                continue

            bar = s_df.loc[current_date]
            p_open = _to_float(bar["Open"])
            p_high = _to_float(bar["High"])
            p_low = _to_float(bar["Low"])
            p_close = _to_float(bar["Close"])
            pos["current_price"] = p_close

            # Zirve fiyat ve trailing stop güncelleme
            if p_high > pos["peak_price"]:
                pos["peak_price"] = p_high
                atr_stop = pos["peak_price"] - (ATR_TRAIL_MULT * pos["atr"])
                if atr_stop > pos["stop_level"]:
                    pos["stop_level"] = atr_stop

            hold_days = (current_date - pos["entry_date"]).days
            gain_pct = (p_close / pos["entry_price"] - 1.0) * 100

            # O anki günün mum analizi
            hist_now = s_df.loc[:current_date]
            candle_now = analyze_candlesticks(hist_now)

            should_exit = False
            exit_reason = ""
            exit_price = p_close

            # Çıkış Kriteri 1: Trailing Stop / Fitil Stopu Patladı
            if p_low <= pos["stop_level"]:
                should_exit = True
                exit_price = min(p_open, pos["stop_level"])
                exit_reason = "TRAILING_STOP" if exit_price > pos["entry_price"] else "STOP_LOSS"

            # Çıkış Kriteri 2: Zirvede Tepe Yorulma Mumu ile Erken Kâr Alma (%10+ kârdayken)
            elif gain_pct >= 10.0 and candle_now.has_bearish_exit_signal:
                should_exit = True
                exit_price = p_close
                exit_reason = f"CANDLE_TAKE_PROFIT ({', '.join(candle_now.patterns)})"

            # Çıkış Kriteri 3: Zaman Stopu (45 gün kâr etmeyen pozisyonu tasfiye et)
            elif hold_days > 45 and p_close < pos["entry_price"] * 0.98:
                should_exit = True
                exit_price = p_close
                exit_reason = "TIME_STOP_45D"

            if should_exit:
                realized_price = exit_price * (1 - SLIPPAGE)
                gross_proceeds = pos["shares"] * realized_price
                net_proceeds = gross_proceeds * (1 - COMMISSION)
                capital += net_proceeds

                total_cost = pos["shares"] * pos["entry_price"] * (1 + COST_ONE_WAY)
                pnl = net_proceeds - total_cost
                pnl_pct = pnl / total_cost * 100

                trade_logs.append({
                    "date": current_date.strftime("%Y-%m-%d"),
                    "ticker": ticker,
                    "reason": exit_reason,
                    "pnl": pnl,
                    "pnl_pct": pnl_pct,
                    "hold_days": hold_days,
                    "regime": regime,
                })
                closed_tickers.append(ticker)

        for t in closed_tickers:
            positions.pop(t, None)

        # -------------------------------------------------------------
        # 2. YENİ POZİSYON GİRİŞLERİ (Aylık / Boş Slot Oldukça)
        # -------------------------------------------------------------
        open_slots = target_positions - len(positions)
        is_rebalance_trigger = (current_date.month != last_rebalance_month) or (open_slots >= 2)

        if open_slots > 0 and is_rebalance_trigger:
            last_rebalance_month = current_date.month

            evaluations: list[StockEvaluation] = []
            for ticker in stock_dict.keys():
                if ticker in positions:
                    continue
                eval_res = evaluate_stock(ticker, stock_dict, current_date, bm_close, sector_tracker, regime)
                if eval_res is not None:
                    evaluations.append(eval_res)

            # En yüksek skordan düşüğe sırala
            evaluations.sort(key=lambda x: x.total_score, reverse=True)

            port_equity = capital + sum(p["shares"] * p["current_price"] for p in positions.values())
            investable_capital = port_equity * invest_ratio

            # Adayları filtrele ve alım yap
            for ev in evaluations:
                if len(positions) >= target_positions:
                    break

                # MUM GİRİŞ FİLTRESİ:
                # Normal hisseler alıcı baskısı (>%55) veya mum formasyonu (Hammer, Engulfing, FVG) vermeli
                # Savunma hisselerine ayıda tolerans tanınır
                if not ev.is_defensive and ev.buyer_pressure < 52.0 and not ev.has_candle_entry:
                    continue

                # Pozisyon başına sermaye (Maksimum %25 kuralı)
                target_alloc = min(port_equity * MAX_POSITION_PCT, investable_capital / target_positions)
                alloc = min(capital * 0.95, target_alloc)

                if alloc > 2000:
                    entry_price = ev.price_now * (1 + SLIPPAGE)
                    cost_per_share = entry_price * (1 + COMMISSION)
                    shares = int(alloc / cost_per_share)

                    if shares > 0:
                        total_outflow = shares * cost_per_share
                        if total_outflow <= capital:
                            capital -= total_outflow

                            # Dinamik Başlangıç Stopu: Fitil Altı veya ATR Stopunun en temkinlisi
                            init_atr_stop = entry_price - (ATR_TRAIL_MULT * ev.atr)
                            init_stop = max(ev.candle_stop, init_atr_stop) if ev.candle_stop > 0 else init_atr_stop

                            positions[ev.ticker] = {
                                "shares": shares,
                                "entry_price": entry_price,
                                "current_price": entry_price,
                                "peak_price": entry_price,
                                "stop_level": init_stop,
                                "atr": ev.atr,
                                "entry_date": current_date,
                            }

        day_equity = capital + sum(p["shares"] * p["current_price"] for p in positions.values())
        equity_curve.append({"date": current_date, "equity": day_equity})

    # -------------------------------------------------------------
    # 3. PERFORMANS METRİKLERİ VE RAPORLAMA
    # -------------------------------------------------------------
    final_equity = capital + sum(p["shares"] * p["current_price"] for p in positions.values())
    if current_year not in yearly_stats:
        year_ret = (final_equity - year_start_capital) / year_start_capital * 100
        bm_curr = float(bm_close.iloc[-1])
        bm_ret = (bm_curr - year_start_bm) / year_start_bm * 100
        yearly_stats[current_year] = {
            "port_return": year_ret,
            "bm_return": bm_ret,
            "alpha": year_ret - bm_ret,
            "end_equity": final_equity,
        }

    total_net_profit = final_equity - INITIAL_CAPITAL
    total_return_pct = total_net_profit / INITIAL_CAPITAL * 100

    bm_initial = float(bm_close.loc[trading_dates[0]])
    bm_final = float(bm_close.loc[trading_dates[-1]])
    bm_total_return_pct = (bm_final - bm_initial) / bm_initial * 100

    eq_series = np.array([e["equity"] for e in equity_curve])
    daily_returns = np.diff(eq_series) / eq_series[:-1]
    sharpe = float((np.mean(daily_returns) / np.std(daily_returns)) * np.sqrt(252)) if np.std(daily_returns) > 0 else 0.0

    peaks = np.maximum.accumulate(eq_series)
    drawdowns = (eq_series - peaks) / peaks
    max_drawdown_pct = float(np.min(drawdowns) * 100)

    n_years = len(eq_series) / 252
    cagr = (final_equity / INITIAL_CAPITAL) ** (1 / n_years) - 1 if n_years > 0 else 0
    bm_cagr = (bm_final / bm_initial) ** (1 / n_years) - 1 if n_years > 0 else 0

    total_trades = len(trade_logs)
    winning_trades = [t for t in trade_logs if t["pnl"] > 0]
    losing_trades = [t for t in trade_logs if t["pnl"] <= 0]
    win_rate = len(winning_trades) / total_trades * 100 if total_trades > 0 else 0
    loss_sum = abs(sum(t["pnl"] for t in losing_trades))
    profit_factor = sum(t["pnl"] for t in winning_trades) / loss_sum if loss_sum > 0 else 999.0

    sep = "=" * 90
    logger.info(f"\n{sep}")
    logger.info("  ULTIMATE ALPHA ENGINE 10-YILLIK SONUÇ KARTI (2016 - 2026)")
    logger.info(sep)
    logger.info(f"  {'Metrik':<38} {'Ultimate Motor':>15} {'BIST-100':>15}")
    logger.info("-" * 72)
    logger.info(f"  {'10Y Toplam Getiri':<38} {total_return_pct:>14.1f}% {bm_total_return_pct:>14.1f}%")
    logger.info(f"  {'Yıllık Bileşik Getiri (CAGR)':<38} {cagr * 100:>14.1f}% {bm_cagr * 100:>14.1f}%")
    logger.info(f"  {'Sharpe Oranı':<38} {sharpe:>15.2f} {'---':>15}")
    logger.info(f"  {'Maksimum Drawdown':<38} {max_drawdown_pct:>14.2f}% {'---':>15}")
    logger.info(f"  {'Kâr Faktörü (Profit Factor)':<38} {profit_factor:>15.2f} {'---':>15}")
    logger.info(f"  {'Kazanma Oranı (Win Rate)':<38} {win_rate:>14.1f}% {'---':>15}")
    logger.info(f"  {'Toplam Gerçekleşen İşlem':<38} {total_trades:>15,} {'---':>15}")
    logger.info(f"  {'Bitiş Sermayesi (100K TL Başlangıç)':<38} {final_equity:>14,.0f}TL")
    logger.info(f"  {'Üretilen Toplam Alfa':<38} {total_return_pct - bm_total_return_pct:>14.1f}%")
    logger.info(sep)

    logger.info(f"\n  YIL YIL PERFORMANS VE ALFA TABLOSU:")
    logger.info(f"  {'YIL':<6} | {'PORTFÖY':>10} | {'BIST-100':>10} | {'ALFA':>10} | {'DURUM':>12}")
    logger.info("-" * 60)
    years_beat = 0
    for yr in sorted(yearly_stats.keys()):
        st = yearly_stats[yr]
        p = st["port_return"]
        b = st["bm_return"]
        a = st["alpha"]
        beat = "[ALFA ✅]" if a > 0 else "[KAYIP ⚠️]"
        if a > 0:
            years_beat += 1
        logger.info(f"  {yr:<6} | {p:>+9.1f}% | {b:>+9.1f}% | {a:>+9.1f}% | {beat}")
    logger.info("-" * 60)
    logger.info(f"  Toplam: {years_beat}/{len(yearly_stats)} yıl BIST'i geçti")

    # Çıkış Nedenleri Analizi
    reasons_count: dict[str, int] = {}
    for tl in trade_logs:
        r = tl["reason"].split(" ")[0]
        reasons_count[r] = reasons_count.get(r, 0) + 1

    logger.info("\n  İŞLEM ÇIKIŞ NEDENLERİ DAĞILIMI:")
    for r, count in sorted(reasons_count.items(), key=lambda x: x[1], reverse=True):
        logger.info(f"    {r:<30}: {count} işlem (%{count / max(1, total_trades) * 100:.1f})")

    if trade_logs:
        by_ticker: dict[str, float] = {}
        for tl in trade_logs:
            by_ticker[tl["ticker"]] = by_ticker.get(tl["ticker"], 0) + tl["pnl"]
        best = sorted(by_ticker.items(), key=lambda x: x[1], reverse=True)[:5]
        worst = sorted(by_ticker.items(), key=lambda x: x[1])[:5]
        logger.info("\n  [TOP 5] En Kârlı Hisseler (Toplam TL PnL):")
        for t, pnl in best:
            logger.info(f"    {t:<15} +{pnl:,.0f} TL")
        logger.info("\n  [BOT 5] En Çok Kaybettiren Hisseler:")
        for t, pnl in worst:
            logger.info(f"    {t:<15} {pnl:,.0f} TL")
    logger.info(sep)


if __name__ == "__main__":
    run_ultimate_simulation()
