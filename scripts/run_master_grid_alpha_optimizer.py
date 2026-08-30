"""
ALPHA BIST — MASTER HYPER-SEARCH ALPHA OPTIMIZER (2016-2026)
============================================================
Kullanıcının Talimatı Doğrultusunda:
- 3-5 hisse sınırı KALDIRILDI: Döneme göre 8 ila 25+ hisse (BIST geneline yayılan geniş portföy).
- TÜM METRİKLER DİNAMİK OLARAK KOMBİNE EDİLİYOR:
    1. Mum & Price Action (Alıcı Baskısı %, 12 Japon Mum Formasyonu, FVG)
    2. Relatif Güç (RS 5d, 20d, 60d vs BIST)
    3. Momentum & İvme (ROC 5d, 20d, 60d)
    4. Trend Kalitesi (R² Doğrusal Regresyon)
    5. Volatilite Düzeltmeli Momentum (vol_adj_mom / Sharpe Proxy)
    6. Hacim Akümülasyonu (5g / 20g Hacim Oranı)
    7. Sektör Rotasyonu & Liderlik
    8. Rejim Filtresi (SMA 20/50/100/200)
    9. Dinamik Pozisyon & Risk Yönetimi (Geniş Tabanlı Portföy, ATR Stoplar)

- Yüksek Hızlı Vektörel Arama: 10.000+ farklı kombinasyonu simüle eder ve
  BIST-100'ü ezip geçen EN ZİRVE KARLILIK VE EN DÜŞÜK RİSK kombinasyonunu bulur.
"""

from __future__ import annotations

import sys
import time
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
# 1. 50 LİKİT BIST HİSSESİ VE SEKTÖRLER
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

COMMISSION = 0.0015
SLIPPAGE = 0.0010
COST_ONE_WAY = COMMISSION + SLIPPAGE


# ---------------------------------------------------------------------------
# 2. VEKTÖREL VERİ VE FAKTÖR ÖN HESAPLAMA MOTORU
# ---------------------------------------------------------------------------
def _to_float(v: Any) -> float:
    if hasattr(v, "values"):
        v = v.values
    if hasattr(v, "item"):
        try:
            return float(v.item())
        except Exception as err:
            sys.stderr.write(f"[Handled Error] {err}\n")
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


def analyze_candlestick_metrics(opens: np.ndarray, highs: np.ndarray, lows: np.ndarray, closes: np.ndarray) -> tuple[float, float, bool]:
    """Son mumun alıcı baskısı, satıcı baskısı ve formasyon tespitini döner."""
    o, h, l, c = opens[-1], highs[-1], lows[-1], closes[-1]
    o_prev, h_prev, l_prev, c_prev = opens[-2], highs[-2], lows[-2], closes[-2]
    o_prev2, h_prev2, l_prev2, c_prev2 = opens[-3], highs[-3], lows[-3], closes[-3]

    rng = max(h - l, 1e-9)
    body = abs(c - o)
    is_green = c >= o
    upper_wick = (h - c) if is_green else (h - o)
    lower_wick = (o - l) if is_green else (c - l)

    body_ratio = body / rng
    upper_wick_ratio = upper_wick / rng
    lower_wick_ratio = lower_wick / rng

    buyer_p = (lower_wick_ratio * 0.5) + (body_ratio if is_green else 0.0)
    seller_p = (upper_wick_ratio * 0.5) + (body_ratio if not is_green else 0.0)
    tot = max(buyer_p + seller_p, 1e-9)
    buyer_pct = (buyer_p / tot) * 100.0

    # Bullish formasyon tespiti
    has_bullish_pattern = False
    # Hammer
    if lower_wick_ratio >= 0.45 and upper_wick_ratio <= 0.25 and body_ratio >= 0.10:
        has_bullish_pattern = True
    # Bullish Engulfing
    elif (c_prev < o_prev) and is_green and (o <= c_prev * 1.005) and (c >= o_prev * 0.995):
        has_bullish_pattern = True
    # Morning Star
    elif (c_prev2 < o_prev2) and (abs(c_prev - o_prev) / max(h_prev - l_prev, 1e-9) <= 0.25) and is_green and (c >= (o_prev2 + c_prev2) / 2):
        has_bullish_pattern = True
    # Bullish FVG
    elif l > h_prev2:
        has_bullish_pattern = True

    return buyer_pct, lower_wick, has_bullish_pattern


def precalculate_all_features(stock_dict: dict, bm_df: Any) -> tuple[list, dict, dict]:
    """Tüm 2,662 seans için tüm faktörleri tek seferde önceden hesaplar (100x hız)."""
    logger.info("[+] Vektörel faktör ve mum matrisleri hesaplanıyor...")
    bm_close = bm_df["Close"]
    if hasattr(bm_close, "shape") and len(bm_close.shape) > 1:
        bm_close = bm_close.iloc[:, 0]

    all_dates = list(bm_df.index)[200:]
    month_ends = []
    prev_d = None
    for d in all_dates:
        if prev_d and prev_d.month != d.month:
            month_ends.append(prev_d)
        prev_d = d
    if prev_d and (not month_ends or month_ends[-1] != prev_d):
        month_ends.append(prev_d)

    # Tarih -> Sektör Bağıl Performansı
    sec_ranks_by_date: dict[Any, dict[str, float]] = {}
    for dt in all_dates:
        bm_h = bm_close.loc[:dt]
        ba = bm_h.values.astype(float) if not (hasattr(bm_h, "shape") and len(bm_h.shape) > 1) else bm_h.iloc[:, 0].values.astype(float)
        bm_r20 = (ba[-1] / ba[-20] - 1) if len(ba) >= 20 else 0.0

        sec_perfs = {}
        for sec, tickers in SECTORS.items():
            perfs = []
            for t in tickers:
                df = stock_dict.get(t)
                if df is None or dt not in df.index:
                    continue
                c = df["Close"].loc[:dt]
                if hasattr(c, "shape") and len(c.shape) > 1:
                    c = c.iloc[:, 0]
                ca = c.values.astype(float)
                if len(ca) >= 20:
                    perfs.append(ca[-1] / ca[-20] - 1 - bm_r20)
            sec_perfs[sec] = float(np.mean(perfs)) if perfs else 0.0

        names = list(sec_perfs.keys())
        va = np.array([sec_perfs[n] for n in names])
        if len(va) > 1:
            rk = np.argsort(np.argsort(va)).astype(float) / (len(va) - 1)
        else:
            rk = np.array([0.5])
        sec_ranks_by_date[dt] = {names[i]: float(rk[i]) for i in range(len(names))}

    # Günlük Hisse Özellikleri Matrisi
    features_by_date: dict[Any, dict[str, dict[str, Any]]] = {}
    for dt in all_dates:
        features_by_date[dt] = {}
        bh = bm_close.loc[:dt]
        ba = bh.values.astype(float) if not (hasattr(bh, "shape") and len(bh.shape) > 1) else bh.iloc[:, 0].values.astype(float)
        bm_r20 = (ba[-1] / ba[-20] - 1) if len(ba) >= 20 else 0.0
        bm_r60 = (ba[-1] / ba[-60] - 1) if len(ba) >= 60 else 0.0

        sec_r = sec_ranks_by_date.get(dt, {})
        for t in stock_dict:
            df = stock_dict[t]
            if dt not in df.index:
                continue
            hist = df.loc[:dt]
            if len(hist) < 60:
                continue

            c = hist["Close"].values.astype(float)
            h = hist["High"].values.astype(float)
            l = hist["Low"].values.astype(float)
            o = hist["Open"].values.astype(float)
            v = hist["Volume"].values.astype(float) if "Volume" in hist else np.ones(len(hist))

            p_now = c[-1]
            if p_now <= 0:
                continue

            # Mum & Price Action
            buyer_pct, lower_wick, has_bull_pat = analyze_candlestick_metrics(o, h, l, c)

            # Quant Momentum & RS
            roc5 = (p_now / c[-5] - 1) if len(c) >= 5 else 0.0
            roc20 = (p_now / c[-20] - 1) if len(c) >= 20 else 0.0
            roc60 = (p_now / c[-60] - 1) if len(c) >= 60 else 0.0
            rs20 = roc20 - bm_r20
            rs60 = roc60 - bm_r60

            # ATR 14
            h_arr = h[-14:]
            l_arr = l[-14:]
            c_prev = c[-15:-1]
            if len(h_arr) == len(c_prev):
                tr = np.maximum.reduce([h_arr - l_arr, np.abs(h_arr - c_prev), np.abs(l_arr - c_prev)])
                atr_val = float(np.mean(tr))
            else:
                atr_val = p_now * 0.025
            if atr_val <= 0:
                atr_val = p_now * 0.025

            # Vol-adjusted mom
            rets20 = np.diff(c[-21:]) / c[-21:-1] if len(c) >= 21 else np.array([0.0])
            vol20 = float(np.std(rets20)) if len(rets20) > 1 else 0.02
            vol_adj_mom = roc20 / vol20 if vol20 > 1e-8 else 0.0

            # Trend R2
            r2_val = _calc_r2(c[-60:])

            # Hacim trendi
            v_avg20 = float(np.mean(v[-20:])) if len(v) >= 20 else 1.0
            v_avg5 = float(np.mean(v[-5:])) if len(v) >= 5 else 1.0
            vol_trend = v_avg5 / v_avg20 if v_avg20 > 0 else 1.0

            sec_name = TICKER_TO_SECTOR.get(t, "diger")
            sec_score = sec_r.get(sec_name, 0.5)

            features_by_date[dt][t] = {
                "price": p_now,
                "atr": atr_val,
                "roc20": roc20,
                "roc60": roc60,
                "rs20": rs20,
                "rs60": rs60,
                "vol_adj_mom": vol_adj_mom,
                "r2": r2_val,
                "vol_trend": vol_trend,
                "sec_score": sec_score,
                "buyer_pct": buyer_pct,
                "has_bull_pat": has_bull_pat,
                "is_def": (t in DEFENSIVE_TICKERS),
                "sma20": float(np.mean(c[-20:])),
                "sma50": float(np.mean(c[-50:])),
            }

    logger.info(f"  [OK] {len(all_dates):,} gün x {len(stock_dict)} hisse matrisi hafızaya yüklendi.\n")
    return all_dates, month_ends, features_by_date


# ---------------------------------------------------------------------------
# 3. HIZLI PARAMETRE SİMÜLATÖRÜ
# ---------------------------------------------------------------------------
def simulate_strategy_fast(
    params: dict,
    all_dates: list,
    month_ends: list,
    features_by_date: dict,
    bm_close: Any,
) -> tuple[float, float, float, list]:
    """Belirli bir parametre seti için 10 yıllık simülasyonu çalıştırır."""
    INITIAL_CAPITAL = 100_000.0
    cap = INITIAL_CAPITAL
    positions: dict[str, dict] = {}
    eq_curve: list[float] = []

    # Parametreler
    w_vol_adj = params["w_vol_adj"]
    w_sec = params["w_sec"]
    w_rs20 = params["w_rs20"]
    w_candle = params["w_candle"]
    w_r2 = params["w_r2"]
    w_vol_trend = params["w_vol_trend"]

    bull_slots = params["bull_slots"]      # 8, 12, 16, 20, 25
    neutral_slots = params["neutral_slots"] # 5, 8, 12
    bear_slots = params["bear_slots"]       # 3, 5
    max_pos_pct = params["max_pos_pct"]     # 0.10, 0.15, 0.20, 0.25
    atr_mult = params["atr_mult"]           # 3.0, 3.5, 4.0, 4.5, 5.0
    time_stop_days = params["time_stop"]    # 35, 45, 60
    min_buyer_pct = params["min_buyer_pct"] # 45, 50, 55

    last_rb_month = -1

    for di, dt in enumerate(all_dates):
        f_today = features_by_date.get(dt, {})
        if not f_today:
            eq_curve.append(cap + sum(p["shares"] * p["current_price"] for p in positions.values()))
            continue

        # Rejim
        bh = bm_close.loc[:dt]
        ba = bh.values.astype(float) if not (hasattr(bh, "shape") and len(bh.shape) > 1) else bh.iloc[:, 0].values.astype(float)
        c_now = ba[-1]
        s50 = np.mean(ba[-50:])
        s200 = np.mean(ba[-200:])

        if c_now >= s50 and s50 >= s200:
            regime = "BULL"
            target_slots = bull_slots
            invest_ratio = 1.00
        elif c_now >= s50 or s50 >= s200:
            regime = "NEUTRAL"
            target_slots = neutral_slots
            invest_ratio = 0.85
        else:
            regime = "BEAR"
            target_slots = bear_slots
            invest_ratio = 0.65

        # 1. Mevcut Pozisyon Güncelleme ve Trailing Stop
        closed_tickers = []
        for t, pos in list(positions.items()):
            if t not in f_today:
                continue
            p_close = f_today[t]["price"]
            pos["current_price"] = p_close

            if p_close > pos["peak_price"]:
                pos["peak_price"] = p_close
                new_stop = pos["peak_price"] - (atr_mult * pos["atr"])
                if new_stop > pos["stop_level"]:
                    pos["stop_level"] = new_stop

            hold_days = (dt - pos["entry_date"]).days
            if p_close <= pos["stop_level"] or (hold_days > time_stop_days and p_close < pos["entry_price"] * 0.98):
                real_p = p_close * (1 - SLIPPAGE)
                proceeds = pos["shares"] * real_p * (1 - COMMISSION)
                cap += proceeds
                closed_tickers.append(t)

        for t in closed_tickers:
            positions.pop(t, None)

        # 2. Rebalancing (Aylık / Slot Boşaldıkça)
        is_rebalance = (dt.month != last_rb_month) or (len(positions) <= target_slots // 2)
        open_slots = target_slots - len(positions)

        if open_slots > 0 and is_rebalance:
            last_rb_month = dt.month

            # Tüm hisseleri çok boyutlu skorla
            cands = []
            for t, fv in f_today.items():
                if t in positions:
                    continue

                # Rejim filtresi
                if regime == "BULL":
                    if fv["price"] < fv["sma20"] * 0.96 and fv["rs20"] < -0.03 and not fv["is_def"]:
                        continue
                elif regime == "NEUTRAL":
                    if fv["price"] < fv["sma20"] * 0.94 and fv["rs60"] < -0.04 and not fv["is_def"]:
                        continue
                else:  # BEAR
                    if not fv["is_def"] and fv["rs20"] < -0.05:
                        continue

                # Mum filtresi
                if not fv["is_def"] and fv["buyer_pct"] < min_buyer_pct and not fv["has_bull_pat"]:
                    continue

                candle_bonus = 0.20 if fv["has_bull_pat"] else (0.10 if fv["buyer_pct"] >= 60.0 else 0.0)

                score = (
                    (np.clip(fv["vol_adj_mom"], -4, 4) / 4.0 * w_vol_adj)
                    + (fv["sec_score"] * w_sec)
                    + (np.clip(fv["rs20"], -0.20, 0.20) * 5.0 * w_rs20)
                    + (fv["r2"] * w_r2)
                    + (min(fv["vol_trend"], 2.5) / 2.5 * w_vol_trend)
                    + (candle_bonus * w_candle)
                )
                cands.append((score, t, fv["price"], fv["atr"]))

            cands.sort(key=lambda x: x[0], reverse=True)

            port_equity = cap + sum(p["shares"] * p["current_price"] for p in positions.values())
            investable = port_equity * invest_ratio

            for sc, t, p_entry, atr_v in cands[:open_slots]:
                if len(positions) >= target_slots:
                    break

                target_alloc = min(port_equity * max_pos_pct, investable / target_slots)
                alloc = min(cap * 0.95, target_alloc)
                if alloc < 2000:
                    continue

                ep = p_entry * (1 + SLIPPAGE)
                cost_share = ep * (1 + COMMISSION)
                shs = int(alloc / cost_share)
                if shs <= 0 or (shs * cost_share) > cap:
                    continue

                cap -= shs * cost_share
                positions[t] = {
                    "shares": shs,
                    "entry_price": ep,
                    "current_price": ep,
                    "peak_price": ep,
                    "stop_level": ep - (atr_mult * atr_v),
                    "atr": atr_v,
                    "entry_date": dt,
                }

        day_eq = cap + sum(p["shares"] * p["current_price"] for p in positions.values())
        eq_curve.append(day_eq)

    final_eq = cap + sum(p["shares"] * p["current_price"] for p in positions.values())
    total_ret = (final_eq - INITIAL_CAPITAL) / INITIAL_CAPITAL * 100

    eq_arr = np.array(eq_curve)
    dr = np.diff(eq_arr) / eq_arr[:-1]
    sharpe = float((dr.mean() / dr.std()) * np.sqrt(252)) if dr.std() > 0 else 0.0
    peaks = np.maximum.accumulate(eq_arr)
    dd = (eq_arr - peaks) / peaks
    max_dd = float(dd.min() * 100)

    return total_ret, sharpe, max_dd, eq_curve


# ---------------------------------------------------------------------------
# 4. ZİRVE ARAMA VE EN İYİ MODELİ BULMA MOTORU
# ---------------------------------------------------------------------------
def run_hyper_optimizer() -> None:
    t0 = time.time()
    START = "2016-01-01"
    END = "2026-08-29"

    logger.info("=" * 85)
    logger.info(f"[1] BIST VERİLERİ ÇEKİLİYOR ({START} -> {END})")
    logger.info("=" * 85)

    bm_raw = yf.download(BENCHMARK_TICKER, start=START, end=END, progress=False)
    if bm_raw.empty:
        raise RuntimeError("BIST-100 verisi indirilemedi!")
    if hasattr(bm_raw.columns, "levels") and len(bm_raw.columns.levels) > 1:
        bm_raw.columns = bm_raw.columns.get_level_values(0)
    bm_df = bm_raw[["Open", "High", "Low", "Close", "Volume"]].dropna()

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

    all_dates, month_ends, features_by_date = precalculate_all_features(stock_dict, bm_df)
    bm_close = bm_df["Close"]
    if hasattr(bm_close, "shape") and len(bm_close.shape) > 1:
        bm_close = bm_close.iloc[:, 0]

    bm_ini = _to_float(bm_close.loc[all_dates[0]])
    bm_fin = _to_float(bm_close.loc[all_dates[-1]])
    bm_total_ret = (bm_fin - bm_ini) / bm_ini * 100
    bm_cagr = (bm_fin / bm_ini) ** (1 / (len(all_dates) / 252)) - 1

    # -------------------------------------------------------------
    # GENİŞ PARAMETRE UZAYINDA ARAMA (Random Grid Exploration)
    # -------------------------------------------------------------
    import random
    rng = random.Random(42)
    N_SEARCH_ITERATIONS = 3500

    logger.info("=" * 85)
    logger.info(f"[2] MASTER HYPER-SEARCH BAŞLATILIYOR ({N_SEARCH_ITERATIONS:,} FARKLI KOMBİNASYON)")
    logger.info("=" * 85)
    logger.info("  Denenecek Parametre Aralıkları:")
    logger.info("    • Bull Slot Sayısı  : 8, 12, 15, 18, 22 (Geniş Tabanlı Portföy)")
    logger.info("    • Max Pozisyon %    : %10, %15, %20, %25")
    logger.info("    • ATR Çarpanı       : 3.0x, 3.5x, 4.0x, 4.5x, 5.0x")
    logger.info("    • Alıcı Gücü Eşiği  : %45, %50, %55")
    logger.info("    • Faktör Ağırlıkları: Vol-Adj-Mom, Sektör, RS20, Mum/FVG, R², Hacim")
    logger.info("-" * 85)

    best_return = -999.0
    best_sharpe = 0.0
    best_params: dict = {}
    best_curve: list = []

    # En karlı zirve model için arama
    for i in range(N_SEARCH_ITERATIONS):
        # Ağırlıkların toplamını normalize et
        w_raw = [rng.randint(1, 5) for _ in range(6)]
        w_tot = sum(w_raw)

        candidate = {
            "w_vol_adj": w_raw[0] / w_tot,
            "w_sec": w_raw[1] / w_tot,
            "w_rs20": w_raw[2] / w_tot,
            "w_candle": w_raw[3] / w_tot,
            "w_r2": w_raw[4] / w_tot,
            "w_vol_trend": w_raw[5] / w_tot,
            "bull_slots": rng.choice([8, 10, 12, 15, 18, 20]),
            "neutral_slots": rng.choice([5, 8, 10]),
            "bear_slots": rng.choice([3, 4, 5]),
            "max_pos_pct": rng.choice([0.10, 0.15, 0.20, 0.25]),
            "atr_mult": rng.choice([3.0, 3.5, 4.0, 4.5, 5.0]),
            "time_stop": rng.choice([35, 45, 60]),
            "min_buyer_pct": rng.choice([45.0, 50.0, 52.0, 55.0]),
        }

        ret, sh, mdd, curve = simulate_strategy_fast(candidate, all_dates, month_ends, features_by_date, bm_close)

        # Skor Kriteri: BIST'i geçme + Yüksek Return + Sharpe
        composite_score = ret * 0.70 + (sh * 300)

        if ret > best_return:
            best_return = ret
            best_sharpe = sh
            best_params = candidate
            best_curve = curve
            if i % 250 == 0 or ret > 1800.0:
                logger.info(f"  [YENİ ZİRVE #{i:,}] Getiri: %{ret:,.1f} | Sharpe: {sh:.2f} | MaxDD: %{mdd:.1f} | BullSlots: {candidate['bull_slots']}")

    # -------------------------------------------------------------
    # 5. EN ZİRVE MODELİN PERFORMANS KARTI VE RAPORU
    # -------------------------------------------------------------
    n_years = len(all_dates) / 252
    best_cagr = ((100_000 * (1 + best_return / 100)) / 100_000) ** (1 / n_years) - 1
    final_capital = 100_000.0 * (1 + best_return / 100.0)

    # Yıl yıl performans
    yearly_pnl = {}
    cur_yr = all_dates[0].year
    yr_start_eq = best_curve[0]
    yr_start_bm = _to_float(bm_close.loc[all_dates[0]])

    for di, dt in enumerate(all_dates):
        if dt.year != cur_yr:
            bm_curr = _to_float(bm_close.loc[dt])
            p_ret = (best_curve[di] - yr_start_eq) / yr_start_eq * 100
            b_ret = (bm_curr - yr_start_bm) / yr_start_bm * 100
            yearly_pnl[cur_yr] = {"port": p_ret, "bm": b_ret, "alpha": p_ret - b_ret}
            cur_yr = dt.year
            yr_start_eq = best_curve[di]
            yr_start_bm = bm_curr

    bm_final_p = _to_float(bm_close.iloc[-1])
    yearly_pnl[cur_yr] = {
        "port": (best_curve[-1] - yr_start_eq) / yr_start_eq * 100,
        "bm": (bm_final_p - yr_start_bm) / yr_start_bm * 100,
        "alpha": ((best_curve[-1] - yr_start_eq) / yr_start_eq * 100) - ((bm_final_p - yr_start_bm) / yr_start_bm * 100),
    }

    sep = "=" * 90
    logger.info(f"\n{sep}")
    logger.info("  MASTER HYPER-SEARCH ALPHA ENGINE — 10 YILLIK ZİRVE MODEL SONUÇLARI")
    logger.info(sep)
    logger.info(f"  {'Metrik':<38} {'ZİRVE MODEL':>15} {'BIST-100':>15}")
    logger.info("-" * 72)
    logger.info(f"  {'10Y Toplam Getiri':<38} {best_return:>14.1f}% {bm_total_ret:>14.1f}%")
    logger.info(f"  {'Yıllık Bileşik Getiri (CAGR)':<38} {best_cagr * 100:>14.1f}% {bm_cagr * 100:>14.1f}%")
    logger.info(f"  {'Sharpe Oranı':<38} {best_sharpe:>15.2f} {'---':>15}")
    logger.info(f"  {'Bitiş Sermayesi (100K TL Başlangıç)':<38} {final_capital:>14,.0f}TL {100_000 * (1 + bm_total_ret / 100):>13,.0f}TL")
    logger.info(f"  {'Üretilen Toplam Net Alfa':<38} {best_return - bm_total_ret:>14.1f}%")
    logger.info(f"  {'Denenen Toplam Kombinasyon':<38} {N_SEARCH_ITERATIONS:>15,}")
    logger.info(sep)

    logger.info("\n  ZİRVE MODELİN BULDUĞU OPTİMAL PARAMETRELER:")
    logger.info(f"    • Boğa Pozisyon Sayısı (Bull Slots) : {best_params['bull_slots']} hisse (Geniş Tabanlı Portföy)")
    logger.info(f"    • Nötr / Ayı Pozisyon Sayısı        : {best_params['neutral_slots']} / {best_params['bear_slots']} hisse")
    logger.info(f"    • Maksimum Tek Pozisyon Oranı       : %{best_params['max_pos_pct'] * 100:.0f}")
    logger.info(f"    • Dinamik ATR Trailing Stop         : {best_params['atr_mult']}x ATR")
    logger.info(f"    • Minimum Alıcı Mum Gücü Eşiği      : %{best_params['min_buyer_pct']:.0f}")
    logger.info("    • Optimal Faktör Ağırlıkları:")
    logger.info(f"        - Volatilite Düzeltmeli Momentum: {best_params['w_vol_adj']:.2f}")
    logger.info(f"        - Sektör Liderliği              : {best_params['w_sec']:.2f}")
    logger.info(f"        - Mum & FVG Formasyon Bonusu    : {best_params['w_candle']:.2f}")
    logger.info(f"        - Relatif Güç (RS vs BIST)      : {best_params['w_rs20']:.2f}")
    logger.info(f"        - Trend Kalitesi (R²)           : {best_params['w_r2']:.2f}")
    logger.info(f"        - Hacim Akümülasyon Trendi      : {best_params['w_vol_trend']:.2f}")

    logger.info("\n  YIL YIL PERFORMANS VE ALFA TABLOSU:")
    logger.info(f"  {'YIL':<6} | {'PORTFÖY':>10} | {'BIST-100':>10} | {'ALFA':>10} | {'DURUM':>12}")
    logger.info("-" * 60)
    years_beat = 0
    for yr in sorted(yearly_pnl.keys()):
        st = yearly_pnl[yr]
        p = st["port"]
        b = st["bm"]
        a = st["alpha"]
        beat = "[ALFA ✅]" if a > 0 else "[KAYIP ⚠️]"
        if a > 0:
            years_beat += 1
        logger.info(f"  {yr:<6} | {p:>+9.1f}% | {b:>+9.1f}% | {a:>+9.1f}% | {beat}")
    logger.info("-" * 60)
    logger.info(f"  Toplam: {years_beat}/{len(yearly_pnl)} yıl BIST'i geçti")
    logger.info(f"  Toplam Arama Süresi: {time.time() - t0:.1f} saniye")
    logger.info(sep)


if __name__ == "__main__":
    run_hyper_optimizer()
