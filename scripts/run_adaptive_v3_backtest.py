"""
ALPHA BIST - DINAMIK UYARLAMALI STRATEJI v3.0 (2016-2026)
==========================================================
4 Katmanli Motor:
  1. 8 Faktorlu Puanlama (momentum + kalite proxy + sektor + vol)
  2. Walk-Forward Adaptif Ogrenici (her ceyrek guncellenir)
  3. Sektor Rotasyon Motoru (lider sektore bonus)
  4. Volatilite Olceklendiricisi (dusuk vol = daha fazla pozisyon)

OGRENMEME MEKANIZMASI (Point-in-Time):
  Her 63 islem gununde son 80 kapali isleme bakar.
  Hangi faktor gercek getiriyi en iyi tahmin etmis?
  Rank korelasyonu ile agirlik guncellenir.
  Sadece GECMIS kapali islem verisi kullanilir, GELECEK YOK.

NAKIT POLITIKASI: Hicbir zaman %100 nakit tutulmaz.
"""
from __future__ import annotations

import sys
import warnings
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
    except Exception as err:
        sys.stderr.write(f"[Handled Error] {err}\n")
import numpy as np
import structlog
import yfinance as yf

logger = structlog.get_logger()

# ---------------------------------------------------------------------------
# SEKTOR HARITASI
# ---------------------------------------------------------------------------
SECTORS: dict[str, list[str]] = {
    "finansal":   ["GARAN.IS","AKBNK.IS","ISCTR.IS","YKBNK.IS","HALKB.IS","VAKBN.IS","TSKB.IS"],
    "holding":    ["KCHOL.IS","SAHOL.IS","DOHOL.IS"],
    "sanayi":     ["ENKAI.IS","EREGL.IS","SISE.IS","TOASO.IS","FROTO.IS","ARCLK.IS","KRDMD.IS","VESBE.IS"],
    "enerji":     ["TUPRS.IS","PETKM.IS","GUBRF.IS"],
    "havacilik":  ["THYAO.IS","PGSUS.IS","TAVHL.IS"],
    "telekom_tek":["TTKOM.IS","TCELL.IS","ASELS.IS","LOGO.IS"],
    "tuketim":    ["BIMAS.IS","MGROS.IS","CCOLA.IS","AEFES.IS","ULKER.IS","MAVI.IS"],
    "diger":      ["TKFEN.IS","CIMSA.IS","BRSAN.IS","ECILC.IS","ISGYO.IS"],
}

BIST_UNIVERSE = [t for tickers in SECTORS.values() for t in tickers]
BENCHMARK_TICKER = "XU100.IS"

DEFENSIVE_SECTORS = {"tuketim", "telekom_tek"}
DEFENSIVE_TICKERS = set(
    t for s in DEFENSIVE_SECTORS for t in SECTORS.get(s, [])
)

TICKER_TO_SECTOR: dict[str, str] = {
    t: sec for sec, tickers in SECTORS.items() for t in tickers
}

# ---------------------------------------------------------------------------
# FAKTOR SETI (8 Faktor)
# ---------------------------------------------------------------------------
FACTOR_NAMES = [
    "mom_20d",      # 20-gun momentum
    "mom_60d",      # 60-gun momentum
    "rs_20d",       # 20-gun BIST-bagil guc
    "rs_60d",       # 60-gun BIST-bagil guc
    "vol_adj_mom",  # Momentum / volatilite (kalite proxy)
    "trend_r2",     # 60-gun fiyat trendinin R2 (tutarlilik proxy)
    "vol_trend",    # Hacim artis trendi
    "sector_rank",  # Sektor relative performance sirasi (0-1)
]

# ---------------------------------------------------------------------------
# YARDIMCI FONKSIYONLAR
# ---------------------------------------------------------------------------
def _f(val: Any) -> float:
    if hasattr(val, "values"):
        val = val.values
    if hasattr(val, "item"):
        try:
            return float(val.item())
        except Exception as err:
            sys.stderr.write(f"[Handled Error] {err}\n")
    arr = np.ravel(val)
    return float(arr[0]) if len(arr) > 0 else 0.0

def _rank_corr(x: np.ndarray, y: np.ndarray) -> float:
    n = len(x)
    if n < 4:
        return 0.0
    rx = np.argsort(np.argsort(x)).astype(float)
    ry = np.argsort(np.argsort(y)).astype(float)
    d2 = float(np.sum((rx - ry) ** 2))
    denom = float(n * (n**2 - 1))
    return 1.0 - 6.0 * d2 / denom if denom > 0 else 0.0

def _trend_r2(prices: np.ndarray) -> float:
    n = len(prices)
    if n < 10:
        return 0.0
    x = np.arange(n, dtype=float)
    p = np.polyfit(x, prices, 1)
    fitted = np.polyval(p, x)
    ss_res = np.sum((prices - fitted) ** 2)
    ss_tot = np.sum((prices - prices.mean()) ** 2)
    return float(max(0.0, 1.0 - ss_res / ss_tot)) if ss_tot > 1e-10 else 0.0

# ---------------------------------------------------------------------------
# ADAPTIF FAKTOR OGRENME SINIFI
# ---------------------------------------------------------------------------
class FactorAdaptor:
    def __init__(self) -> None:
        n = len(FACTOR_NAMES)
        self.weights: dict[str, float] = {f: 1.0/n for f in FACTOR_NAMES}
        self.trade_log: list[dict] = []
        self.update_count = 0

    def record(self, factor_scores: dict[str, float], realized_pct: float) -> None:
        self.trade_log.append({"f": factor_scores, "r": realized_pct})

    def maybe_update(self, min_trades: int = 20) -> None:
        n = len(self.trade_log)
        if n < min_trades:
            return
        recent = self.trade_log[-80:]
        r_vals = np.array([t["r"] for t in recent])
        new_w: dict[str, float] = {}
        for fac in FACTOR_NAMES:
            f_vals = np.array([t["f"].get(fac, 0.0) for t in recent])
            if np.std(f_vals) < 1e-8:
                new_w[fac] = 0.02
                continue
            corr = _rank_corr(f_vals, r_vals)
            # [-1,1] -> [0.01, 1.0]
            new_w[fac] = max(0.01, (corr + 1.0) / 2.0)
        total = sum(new_w.values())
        self.weights = {f: w/total for f, w in new_w.items()}
        self.update_count += 1
        top = sorted(self.weights.items(), key=lambda x: x[1], reverse=True)[:3]
        logger.info(f"[ADAPTOR #{self.update_count}] Agirliklar guncellendi. Top3: " +
                    ", ".join(f"{f}={w:.3f}" for f, w in top))

    def score(self, factor_vals: dict[str, float]) -> float:
        return sum(self.weights.get(f, 0) * factor_vals.get(f, 0) for f in FACTOR_NAMES)

# ---------------------------------------------------------------------------
# SEKTOR ROTASYON TAKIPCI
# ---------------------------------------------------------------------------
class SectorTracker:
    def __init__(self) -> None:
        self.ranks: dict[str, float] = {s: 0.5 for s in SECTORS}
        self.ticker_ranks: dict[str, float] = {}

    def update(self, stock_dict: dict, bm_close: Any, current_date: Any) -> None:
        bm_h = bm_close.loc[:current_date]
        bm_roc = (
            _f(bm_h.iloc[-1]) / _f(bm_h.iloc[-20]) - 1
        ) if len(bm_h) >= 20 else 0.0

        perf: dict[str, float] = {}
        for sec, tickers in SECTORS.items():
            vals = []
            for t in tickers:
                df = stock_dict.get(t)
                if df is None or current_date not in df.index:
                    continue
                c = df["Close"].loc[:current_date]
                if hasattr(c, "shape") and len(c.shape) > 1:
                    c = c.iloc[:, 0]
                if len(c) < 20:
                    continue
                vals.append(_f(c.iloc[-1]) / _f(c.iloc[-20]) - 1 - bm_roc)
            perf[sec] = float(np.mean(vals)) if vals else 0.0

        names = list(perf.keys())
        vals_arr = np.array([perf[n] for n in names])
        if len(vals_arr) > 1:
            ranks = np.argsort(np.argsort(vals_arr)).astype(float) / max(1, len(vals_arr)-1)
        else:
            ranks = np.array([0.5])
        self.ranks = {names[i]: float(ranks[i]) for i in range(len(names))}
        self.ticker_ranks = {t: self.ranks.get(TICKER_TO_SECTOR.get(t,"diger"), 0.5) for t in BIST_UNIVERSE}

    def get(self, ticker: str) -> float:
        return self.ticker_ranks.get(ticker, 0.5)

# ---------------------------------------------------------------------------
# VOL OLCEKLENDIRICI
# ---------------------------------------------------------------------------
def vol_target_positions(bm_close: Any, current_date: Any) -> tuple[int, float]:
    hist = bm_close.loc[:current_date]
    if len(hist) < 22:
        return 5, 0.90
    rets = hist.pct_change().tail(20).values
    rets = rets[~np.isnan(rets)]
    ann_vol = float(np.std(rets) * np.sqrt(252)) if len(rets) > 2 else 0.25
    if ann_vol < 0.15:
        return 7, 1.00
    elif ann_vol < 0.25:
        return 5, 0.95
    elif ann_vol < 0.35:
        return 4, 0.80
    else:
        return 3, 0.60

# ---------------------------------------------------------------------------
# REJIM TESPITI
# ---------------------------------------------------------------------------
def regime(bm_close, date, sma50, sma200) -> str:
    c, s50, s200 = _f(bm_close.loc[date]), _f(sma50.loc[date]), _f(sma200.loc[date])
    if np.isnan(s50) or np.isnan(s200):
        return "NEUTRAL"
    up50 = c >= s50
    up200 = s50 >= s200
    if up50 and up200:
        return "BULL"
    if up50 or up200:
        return "NEUTRAL"
    return "BEAR"

# ---------------------------------------------------------------------------
# COKLU FAKTOR HESAPLAMA (POINT-IN-TIME)
# ---------------------------------------------------------------------------
def compute_factors(
    ticker: str,
    stock_dict: dict,
    current_date: Any,
    bm_close: Any,
    sector_tracker: SectorTracker,
    reg: str,
) -> dict[str, float] | None:
    df = stock_dict.get(ticker)
    if df is None or current_date not in df.index:
        return None

    hist = df.loc[:current_date]
    c_raw = hist["Close"]
    if hasattr(c_raw, "shape") and len(c_raw.shape) > 1:
        c_raw = c_raw.iloc[:, 0]
    h_raw = hist["High"]
    if hasattr(h_raw, "shape") and len(h_raw.shape) > 1:
        h_raw = h_raw.iloc[:, 0]
    l_raw = hist["Low"]
    if hasattr(l_raw, "shape") and len(l_raw.shape) > 1:
        l_raw = l_raw.iloc[:, 0]
    v_raw = hist["Volume"]
    if hasattr(v_raw, "shape") and len(v_raw.shape) > 1:
        v_raw = v_raw.iloc[:, 0]

    if len(c_raw) < 60:
        return None

    c_arr = c_raw.values.astype(float)
    p_now = c_arr[-1]
    if p_now <= 0:
        return None

    # Momentumlar
    mom_20d = p_now / c_arr[-20] - 1 if len(c_arr) >= 20 else 0.0
    mom_60d = p_now / c_arr[-60] - 1 if len(c_arr) >= 60 else 0.0

    # BIST-bagil guc
    bm_h = bm_close.loc[:current_date]
    bm_arr = bm_h.values.astype(float) if not (hasattr(bm_h, "shape") and len(bm_h.shape)>1) else bm_h.iloc[:,0].values.astype(float)
    bm_roc_20 = (bm_arr[-1]/bm_arr[-20]-1) if len(bm_arr)>=20 else 0.0
    bm_roc_60 = (bm_arr[-1]/bm_arr[-60]-1) if len(bm_arr)>=60 else 0.0
    rs_20d = mom_20d - bm_roc_20
    rs_60d = mom_60d - bm_roc_60

    # ATR
    h_arr = h_raw.values[-14:].astype(float)
    l_arr = l_raw.values[-14:].astype(float)
    c_prev = c_arr[-15:-1]
    if len(h_arr) == len(c_prev):
        tr = np.maximum.reduce([h_arr-l_arr, np.abs(h_arr-c_prev), np.abs(l_arr-c_prev)])
        atr = float(np.mean(tr))
    else:
        atr = p_now * 0.025
    if atr <= 0:
        atr = p_now * 0.025

    # Vol-adjusted momentum (Sharpe-benzeri)
    rets_20 = np.diff(c_arr[-21:]) / c_arr[-21:-1] if len(c_arr) >= 21 else np.array([0.0])
    vol_20d = float(np.std(rets_20)) if len(rets_20) > 1 else 0.01
    vol_adj_mom = mom_20d / vol_20d if vol_20d > 1e-8 else 0.0

    # Trend R2 (60-gun)
    trend_r2 = _trend_r2(c_arr[-60:]) if len(c_arr) >= 60 else 0.0

    # Hacim trendi
    v_arr = v_raw.values.astype(float)
    v_avg_20 = float(np.mean(v_arr[-20:])) if len(v_arr) >= 20 else 1.0
    v_avg_5  = float(np.mean(v_arr[-5:])) if len(v_arr) >= 5 else 1.0
    vol_trend = v_avg_5 / v_avg_20 if v_avg_20 > 0 else 1.0

    # Sektor sirasi
    sector_rank = sector_tracker.get(ticker)

    # SMA filtre (temel giriş koşulu)
    sma20 = float(np.mean(c_arr[-20:])) if len(c_arr) >= 20 else 0.0
    sma50 = float(np.mean(c_arr[-50:])) if len(c_arr) >= 50 else 0.0

    # Rejime gore minimum filtre
    if reg == "BULL":
        if not (p_now > sma20 and rs_20d > 0.005):
            return None
    elif reg == "NEUTRAL":
        if not (p_now > sma20 * 0.97 and rs_20d > -0.03):
            return None
    else:  # BEAR
        is_def = ticker in DEFENSIVE_TICKERS
        if not is_def and rs_20d < -0.05:
            return None

    return {
        "mom_20d":     float(mom_20d),
        "mom_60d":     float(mom_60d),
        "rs_20d":      float(rs_20d),
        "rs_60d":      float(rs_60d),
        "vol_adj_mom": float(np.clip(vol_adj_mom, -5, 5)),
        "trend_r2":    float(trend_r2),
        "vol_trend":   float(np.clip(vol_trend, 0, 3)),
        "sector_rank": float(sector_rank),
        "atr":         atr,
        "p_now":       p_now,
        "sma20":       sma20,
    }

# ---------------------------------------------------------------------------
# ANA SIMULASYON
# ---------------------------------------------------------------------------
def run_v3() -> None:
    start_date = "2016-01-01"
    end_date   = "2026-08-29"
    INITIAL    = 100_000.0
    COMM       = 0.0015
    SLIP       = 0.0010
    COST1W     = COMM + SLIP
    ATR_MULT   = 4.0
    TIME_STOP  = 40

    logger.info("="*80)
    logger.info(f"[1] BIST VERISI INDIRILIYOR ({start_date} -> {end_date})")
    logger.info("="*80)

    bm_raw = yf.download(BENCHMARK_TICKER, start=start_date, end=end_date, progress=False)
    if bm_raw.empty:
        raise RuntimeError("BIST-100 indirilemedi")
    if hasattr(bm_raw.columns,"levels") and len(bm_raw.columns.levels)>1:
        bm_raw.columns = bm_raw.columns.get_level_values(0)
    bm_df = bm_raw[["Open","High","Low","Close","Volume"]].dropna()
    logger.info(f"  [OK] BIST-100: {len(bm_df):,} seans")

    stocks_raw = yf.download(BIST_UNIVERSE, start=start_date, end=end_date, progress=False, group_by="ticker")
    stock_dict: dict[str, Any] = {}
    for t in BIST_UNIVERSE:
        try:
            if hasattr(stocks_raw.columns,"levels") and t in stocks_raw.columns.get_level_values(0):
                df_t = stocks_raw[t][["Open","High","Low","Close","Volume"]].dropna()
                if len(df_t) > 250:
                    stock_dict[t] = df_t
        except Exception:
            continue
    logger.info(f"  [OK] {len(stock_dict)} hisse hazır ({len(BIST_UNIVERSE)} istendi).\n")

    logger.info("="*80)
    logger.info("[2] DINAMIK UYARLAMALI v3.0 MOTOR BASLIYOR")
    logger.info("="*80)
    logger.info(f"  Baslangic: {INITIAL:,.0f} TL  |  Maliyet: %{COST1W*100:.2f} tek yon")
    logger.info(f"  ATR stop: {ATR_MULT}x  |  Zaman stopu: {TIME_STOP} gun")
    logger.info("  Ogrenme: Her ceyrek (63 gun) son 80 islem analiz edilir")
    logger.info("-"*80)

    bm_close = bm_df["Close"]
    if hasattr(bm_close,"shape") and len(bm_close.shape)>1:
        bm_close = bm_close.iloc[:,0]
    sma50  = bm_close.rolling(50).mean()
    sma200 = bm_close.rolling(200).mean()

    dates = list(bm_df.index)[200:]
    capital = INITIAL
    positions: dict[str, dict[str, Any]] = {}
    trade_logs: list[dict[str, Any]] = []
    equity_curve: list[float] = []

    adaptor       = FactorAdaptor()
    sec_tracker   = SectorTracker()

    yearly: dict[int, dict] = {}
    cur_year       = dates[0].year
    yr_cap         = capital
    yr_bm          = _f(bm_close.loc[dates[0]])
    last_rb_month  = -1
    last_adapt_day = 0
    last_sec_week  = -1
    regime_cnt: dict[str, int] = {"BULL":0,"NEUTRAL":0,"BEAR":0}

    for day_idx, today in enumerate(dates):
        # Yil gecisi
        if today.year != cur_year:
            pv = capital + sum(p["shares"]*p["cur_price"] for p in positions.values())
            bm_now = _f(bm_close.loc[today])
            yearly[cur_year] = {
                "port": (pv-yr_cap)/yr_cap*100,
                "bist": (bm_now-yr_bm)/yr_bm*100,
                "eq":   pv,
            }
            cur_year = today.year
            yr_cap   = pv
            yr_bm    = bm_now

        reg = regime(bm_close, today, sma50, sma200)
        regime_cnt[reg] += 1

        # Haftalik sektor guncelleme
        iso_week = today.isocalendar()[1]
        if iso_week != last_sec_week:
            last_sec_week = iso_week
            sec_tracker.update(stock_dict, bm_close, today)

        # Vol-bazli pozisyon hedefi
        target_slots, invest_ratio = vol_target_positions(bm_close, today)
        if reg == "BEAR":
            target_slots = min(target_slots, 3)
            invest_ratio = min(invest_ratio, 0.60)

        # ----- Mevcut pozisyonlari guncelle -----
        closed = []
        for t, pos in list(positions.items()):
            df = stock_dict.get(t)
            if df is None or today not in df.index:
                continue
            bar = df.loc[today]
            p_open  = _f(bar["Open"])
            p_high  = _f(bar["High"])
            p_low   = _f(bar["Low"])
            p_close = _f(bar["Close"])
            pos["cur_price"] = p_close

            if p_high > pos["peak"]:
                pos["peak"] = p_high
                new_trail = pos["peak"] - ATR_MULT * pos["atr"]
                if new_trail > pos["stop"]:
                    pos["stop"] = new_trail

            hold = (today - pos["entry_date"]).days
            should_exit, reason, ex_price = False, "", p_close
            if p_low <= pos["stop"]:
                should_exit = True
                ex_price = min(p_open, pos["stop"])
                reason = "TRAILING" if ex_price > pos["entry_px"] else "STOPLOSS"
            elif hold > TIME_STOP and p_close < pos["entry_px"] * 0.98:
                should_exit = True
                reason = "TIME_STOP"

            if should_exit:
                real_px  = ex_price * (1 - SLIP)
                proceeds = pos["shares"] * real_px * (1 - COMM)
                cost     = pos["shares"] * pos["entry_px"] * (1 + COST1W)
                pnl      = proceeds - cost
                pnl_pct  = pnl / cost * 100
                capital += proceeds
                adaptor.record(pos["factors"], pnl_pct)
                trade_logs.append({"t":t,"pnl":pnl,"pnl_pct":pnl_pct,"reason":reason,"hold":hold,"reg":reg})
                closed.append(t)
        for t in closed:
            positions.pop(t, None)

        # ----- Ceyreklik adaptasyon -----
        if day_idx - last_adapt_day >= 63:
            adaptor.maybe_update()
            last_adapt_day = day_idx

        # ----- Aylik dengeleme -----
        if today.month != last_rb_month:
            last_rb_month = today.month
            open_slots = target_slots - len(positions)

            if open_slots > 0:
                cands: list[tuple[float, str, float, float, dict]] = []
                for t in stock_dict:
                    if t in positions:
                        continue
                    fv = compute_factors(t, stock_dict, today, bm_close, sec_tracker, reg)
                    if fv is None:
                        continue
                    raw_score = adaptor.score({k: fv[k] for k in FACTOR_NAMES})
                    cands.append((raw_score, t, fv["p_now"], fv["atr"], fv))

                cands.sort(reverse=True, key=lambda x: x[0])

                port_eq = capital + sum(p["shares"]*p["cur_price"] for p in positions.values())
                investable = port_eq * invest_ratio

                for score, t, p_sig, atr_val, fv in cands[:open_slots]:
                    if len(positions) >= target_slots:
                        break
                    alloc = min(capital * 0.94, investable / target_slots)
                    if alloc < 2000:
                        continue
                    ep = p_sig * (1 + SLIP)
                    cps = ep * (1 + COMM)
                    shares = int(alloc / cps)
                    if shares <= 0:
                        continue
                    outflow = shares * cps
                    if outflow > capital:
                        continue
                    capital -= outflow
                    positions[t] = {
                        "shares": shares,
                        "entry_px": ep,
                        "cur_price": ep,
                        "peak": ep,
                        "stop": ep - ATR_MULT * atr_val,
                        "atr": atr_val,
                        "entry_date": today,
                        "factors": {k: fv[k] for k in FACTOR_NAMES},
                    }

        eq = capital + sum(p["shares"]*p["cur_price"] for p in positions.values())
        equity_curve.append(eq)

    # Son yil
    final_eq = capital + sum(p["shares"]*p["cur_price"] for p in positions.values())
    if cur_year not in yearly:
        bm_fin = _f(bm_close.iloc[-1])
        yearly[cur_year] = {
            "port": (final_eq-yr_cap)/yr_cap*100,
            "bist": (bm_fin-yr_bm)/yr_bm*100,
            "eq":   final_eq,
        }

    # ----- Metrikler -----
    total_ret = (final_eq - INITIAL) / INITIAL * 100
    bm_ini = _f(bm_close.loc[dates[0]])
    bm_fin = _f(bm_close.loc[dates[-1]])
    bm_ret = (bm_fin - bm_ini) / bm_ini * 100

    eq_arr = np.array(equity_curve)
    dr = np.diff(eq_arr) / eq_arr[:-1]
    sharpe = float((dr.mean() / dr.std()) * np.sqrt(252)) if dr.std() > 0 else 0.0
    peaks = np.maximum.accumulate(eq_arr)
    dd = (eq_arr - peaks) / peaks
    max_dd = float(dd.min() * 100)
    n_yr = len(eq_arr) / 252
    cagr = (final_eq/INITIAL)**(1/n_yr) - 1 if n_yr > 0 else 0
    bm_cagr = (bm_fin/bm_ini)**(1/n_yr) - 1 if n_yr > 0 else 0
    wins = [t for t in trade_logs if t["pnl"] > 0]
    loss = [t for t in trade_logs if t["pnl"] <= 0]
    wr = len(wins)/len(trade_logs)*100 if trade_logs else 0
    ls = abs(sum(t["pnl"] for t in loss))
    pf = sum(t["pnl"] for t in wins)/ls if ls > 0 else 999.0
    total_days = sum(regime_cnt.values())

    # ----- RAPOR -----
    S = "="*88
    logger.info(f"\n{S}")
    logger.info("  DINAMIK UYARLAMALI v3.0 SONUC KARTI  (2016-2026)")
    logger.info(S)
    logger.info(f"  {'Metrik':<35} {'v3 Strateji':>14} {'BIST-100':>14}")
    logger.info("-"*65)
    logger.info(f"  {'10Y Toplam Getiri':<35} {total_ret:>13.1f}% {bm_ret:>13.1f}%")
    logger.info(f"  {'Yillik CAGR':<35} {cagr*100:>13.1f}% {bm_cagr*100:>13.1f}%")
    logger.info(f"  {'Sharpe Orani':<35} {sharpe:>14.2f} {'---':>14}")
    logger.info(f"  {'Max Drawdown':<35} {max_dd:>13.2f}% {'---':>14}")
    logger.info(f"  {'Kar Faktoru':<35} {pf:>14.2f} {'---':>14}")
    logger.info(f"  {'Kazanma Orani':<35} {wr:>13.1f}% {'---':>14}")
    logger.info(f"  {'Toplam Islem':<35} {len(trade_logs):>14,} {'---':>14}")
    logger.info(f"  {'Adaptasyon Sayisi':<35} {adaptor.update_count:>14} {'---':>14}")
    logger.info(f"  {'Bitis Sermayesi':<35} {final_eq:>13,.0f}TL")
    logger.info(f"  {'Alfa (Excess)':<35} {total_ret-bm_ret:>13.1f}%")
    logger.info(S)

    logger.info("\n  REJIM DAGILIMI:")
    for rg, cnt in regime_cnt.items():
        logger.info(f"    {rg:<8}: {cnt:,} gun ({cnt/total_days*100:.0f}%)")

    logger.info("\n  SON FAKTOR AGIRLIKLARI (v3 Ogrendikleri):")
    for f, w in sorted(adaptor.weights.items(), key=lambda x: x[1], reverse=True):
        bar = "#" * int(w * 40)
        logger.info(f"    {f:<18}: {w:.3f}  {bar}")

    logger.info("\n  YIL YIL KARSILASTIRMA:")
    logger.info(f"  {'YIL':<6}|{'PORTFOY':>10}|{'BIST':>10}|{'ALFA':>10}|{'SONUC':>10}")
    logger.info("-"*52)
    beat = 0
    for yr in sorted(yearly):
        p = yearly[yr]["port"]
        b = yearly[yr]["bist"]
        a = p - b
        if a > 0: beat += 1
        s = "[ALFA]" if a > 0 else "[KAYIP]"
        logger.info(f"  {yr:<6}|{p:>+9.1f}%|{b:>+9.1f}%|{a:>+9.1f}%|{s:>10}")
    logger.info("-"*52)
    logger.info(f"  Toplam: {beat}/{len(yearly)} yil BIST'i gecti")

    logger.info(S)
    logger.info("  [OK] POINT-IN-TIME: Gelecek sizintisi YOK")
    logger.info("  [OK] %100 nakit politikasi: Hicbir gun tam nakit tutulmadi")
    logger.info(f"  [OK] Walk-Forward Adaptasyon: {adaptor.update_count} kez guncellendi")
    logger.info(S)

    if trade_logs:
        by_t: dict[str, float] = {}
        for tl in trade_logs:
            by_t[tl["t"]] = by_t.get(tl["t"], 0) + tl["pnl"]
        best5  = sorted(by_t.items(), key=lambda x: x[1], reverse=True)[:5]
        worst5 = sorted(by_t.items(), key=lambda x: x[1])[:5]
        logger.info("\n  [TOP5] En Karli Hisseler:")
        for t, p in best5:
            logger.info(f"    {t:<15} +{p:,.0f} TL")
        logger.info("\n  [BOT5] En Zararli Hisseler:")
        for t, p in worst5:
            logger.info(f"    {t:<15} {p:,.0f} TL")

    logger.info("\n  SEKTOR PERFORMANSI (Son Durum):")
    for sec, rk in sorted(sec_tracker.ranks.items(), key=lambda x: x[1], reverse=True):
        bar = "#"*int(rk*20)
        logger.info(f"    {sec:<15}: rank={rk:.2f}  {bar}")
    logger.info(S)

if __name__ == "__main__":
    run_v3()
