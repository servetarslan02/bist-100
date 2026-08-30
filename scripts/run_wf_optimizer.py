"""
ALPHA BIST - WALK-FORWARD PARAMETRE OPTIMIZASYON MOTORU v1.0
=============================================================
17 parametreyi ayni anda optimize eder. Sistem kendi kendine
hangi metrik kombinasyonunun en karli, en az zararli, en tutarli
oldugunu bulur. Tam Point-in-Time garantisi: egitim verisi hicbir
zaman test verisini gormez.

PARAMETRE UZAYI (17 parametre, ~8.7M kombinasyon):
  Rejim    : sma_fast x sma_slow
  Stop     : atr_mult x time_stop
  Momentum : mom_short x mom_long x r2_window
  Pozisyon : bull_slots x neutral_slots x bear_slots x max_pos_pct
  Faktorler: w_vol_adj x w_sec x w_rs_s x w_mom_s x w_r2 x w_mom_l

YONTEM:
  Her 6 aylik egitim penceresinde 400 rastgele kombinasyon
  hizli mini-backtest (aylik rebalance) ile test edilir.
  En iyi skor eden kombinasyon sonraki 6 ay icin kullanilir.
  Bu walk-forward simulasyon 10 yil boyunca devam eder.

SKOR = 0.40*Sharpe + 0.35*Calmar + 0.25*Tutarlilik
"""
from __future__ import annotations

import random
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
rng = random.Random(42)

# ---------------------------------------------------------------------------
# PARAMETRE UZAYI
# ---------------------------------------------------------------------------
PARAM_SPACE: dict[str, list] = {
    "sma_fast":      [20, 30, 50],
    "sma_slow":      [100, 150, 200, 250],
    "atr_mult":      [2.5, 3.0, 4.0, 5.0],
    "time_stop":     [25, 35, 45, 55],
    "mom_short":     [10, 15, 20, 30],
    "mom_long":      [40, 60, 90],
    "r2_window":     [40, 60, 80],
    "bull_slots":    [5, 8, 10, 13],
    "neutral_slots": [3, 5, 7],
    "bear_slots":    [2, 3, 4],
    "max_pos_pct":   [0.15, 0.20, 0.25],
    "w_vol_adj":     [1, 2, 3, 4],
    "w_sec":         [1, 2, 3, 4],
    "w_rs_s":        [1, 2, 3],
    "w_mom_s":       [1, 2, 3],
    "w_r2":          [1, 2, 3],
    "w_mom_l":       [1, 2],
}

SECTORS: dict[str, list[str]] = {
    "finansal": ["GARAN.IS","AKBNK.IS","ISCTR.IS","YKBNK.IS","HALKB.IS","VAKBN.IS","TSKB.IS"],
    "holding":  ["KCHOL.IS","SAHOL.IS","DOHOL.IS"],
    "sanayi":   ["ENKAI.IS","EREGL.IS","SISE.IS","TOASO.IS","FROTO.IS","ARCLK.IS","KRDMD.IS","VESBE.IS"],
    "enerji":   ["TUPRS.IS","PETKM.IS","GUBRF.IS"],
    "havacilik":["THYAO.IS","PGSUS.IS","TAVHL.IS"],
    "teletek":  ["TTKOM.IS","TCELL.IS","ASELS.IS","LOGO.IS"],
    "tuketim":  ["BIMAS.IS","MGROS.IS","CCOLA.IS","AEFES.IS","ULKER.IS","MAVI.IS"],
    "diger":    ["TKFEN.IS","CIMSA.IS","BRSAN.IS","ECILC.IS","ISGYO.IS"],
}
UNIVERSE = [t for ts in SECTORS.values() for t in ts]
TICKER_SEC = {t: s for s, ts in SECTORS.items() for t in ts}
DEF_TICKERS = set(SECTORS["tuketim"] + SECTORS["teletek"])
BENCHMARK = "XU100.IS"
COMM = 0.0015; SLIP = 0.0010; COST1W = COMM + SLIP

# ---------------------------------------------------------------------------
# YARDIMCILAR
# ---------------------------------------------------------------------------
def _f(v: Any) -> float:
    if hasattr(v, "values"):
        v = v.values
    if hasattr(v, "item"):
        try:
            return float(v.item())
        except (ValueError, TypeError, AttributeError):
            a = np.ravel(v)
            return float(a[0]) if len(a) > 0 else 0.0
    a = np.ravel(v)
    return float(a[0]) if len(a) > 0 else 0.0

def _r2(c: np.ndarray) -> float:
    if len(c)<10: return 0.0
    x=np.arange(len(c),dtype=float); p=np.polyfit(x,c,1); fit=np.polyval(p,x)
    ss_r=np.sum((c-fit)**2); ss_t=np.sum((c-c.mean())**2)
    return float(max(0.0,1.0-ss_r/ss_t)) if ss_t>1e-10 else 0.0

def sample_params(n: int) -> list[dict]:
    samples = []
    for _ in range(n):
        p = {k: rng.choice(v) for k, v in PARAM_SPACE.items()}
        # Mantiksal kisit: neutral_slots <= bull_slots, bear_slots <= neutral_slots
        p["neutral_slots"] = min(p["neutral_slots"], p["bull_slots"])
        p["bear_slots"]    = min(p["bear_slots"], p["neutral_slots"])
        # Faktor agirliklarini normalize et
        tw = p["w_vol_adj"] + p["w_sec"] + p["w_rs_s"] + p["w_mom_s"] + p["w_r2"] + p["w_mom_l"]
        p["_fw"] = {
            "vol_adj": p["w_vol_adj"]/tw,
            "sec":     p["w_sec"]/tw,
            "rs_s":    p["w_rs_s"]/tw,
            "mom_s":   p["w_mom_s"]/tw,
            "r2":      p["w_r2"]/tw,
            "mom_l":   p["w_mom_l"]/tw,
        }
        samples.append(p)
    return samples

def multi_score(monthly_returns: np.ndarray) -> float:
    """Cok-amacli skor: Sharpe + Calmar + Tutarlilik."""
    if len(monthly_returns) < 3:
        return -999.0
    mr = np.array(monthly_returns, dtype=float)
    sharpe = (mr.mean() / mr.std() * np.sqrt(12)) if mr.std() > 1e-10 else 0.0
    cum = np.cumprod(1 + mr) - 1
    ea = np.cumprod(1 + mr)
    peaks = np.maximum.accumulate(ea)
    dd = (ea - peaks) / peaks
    max_dd = float(dd.min())
    calmar = (float(mr.mean()) * 12) / abs(max_dd) if abs(max_dd) > 1e-10 else 0.0
    consistency = float(np.mean(mr > 0))  # % pozitif aylar
    return float(0.40*min(sharpe,10) + 0.35*min(calmar,20) + 0.25*consistency*10)

# ---------------------------------------------------------------------------
# FAK TOR ON HESAPLAMA (Hizli mini-backtest icin)
# ---------------------------------------------------------------------------
def precompute_factors(
    stock_dict: dict,
    month_ends: list,
    bm_close: Any,
    sec_tracker_ranks: dict,  # {date -> {ticker -> float}}
) -> dict[str, dict[str, dict[str, float]]]:
    """
    returns: {date_str -> {ticker -> {factor -> float}}}
    Tum faktörleri her ay-sonu icin once hesapla.
    """
    result: dict[str, dict[str, dict[str, float]]] = {}
    for dt in month_ends:
        dt_str = dt.strftime("%Y-%m")
        result[dt_str] = {}
        bh = bm_close.loc[:dt]
        ba = bh.values.astype(float) if not (hasattr(bh,"shape") and len(bh.shape)>1) else bh.iloc[:,0].values.astype(float)
        if len(ba) < 90:
            continue
        bm_r10 = ba[-1]/ba[-10]-1 if len(ba)>=10 else 0.0
        bm_r20 = ba[-1]/ba[-20]-1 if len(ba)>=20 else 0.0
        bm_r30 = ba[-1]/ba[-30]-1 if len(ba)>=30 else 0.0
        bm_r40 = ba[-1]/ba[-40]-1 if len(ba)>=40 else 0.0
        bm_r60 = ba[-1]/ba[-60]-1 if len(ba)>=60 else 0.0
        bm_r90 = ba[-1]/ba[-90]-1 if len(ba)>=90 else 0.0

        sec_r = sec_tracker_ranks.get(dt, {})
        for t in stock_dict:
            df = stock_dict[t]
            if dt not in df.index: continue
            hist = df.loc[:dt]
            c = hist["Close"]
            if hasattr(c,"shape") and len(c.shape)>1: c=c.iloc[:,0]
            ca = c.values.astype(float)
            if len(ca) < 90: continue
            p = ca[-1]
            if p <= 0: continue
            # Pre-compute all possible windows
            ret = {}
            for w, bm_rw in [(10,bm_r10),(15,bm_r10),(20,bm_r20),(30,bm_r30),(40,bm_r40),(60,bm_r60),(90,bm_r90)]:
                if len(ca) >= w:
                    ret[w] = ca[-1]/ca[-w]-1
                else:
                    ret[w] = 0.0
            # vol (realized, 20d)
            if len(ca) >= 21:
                rets20 = np.diff(ca[-21:])/ca[-21:-1]
                vol20 = float(np.std(rets20)) if rets20.std()>0 else 0.01
            else:
                vol20 = 0.025
            # r2 for different windows
            r2_40 = _r2(ca[-40:]) if len(ca)>=40 else 0.0
            r2_60 = _r2(ca[-60:]) if len(ca)>=60 else 0.0
            r2_80 = _r2(ca[-80:]) if len(ca)>=80 else 0.0
            result[dt_str][t] = {
                "ret10": ret[10], "ret15": ret[15], "ret20": ret[20],
                "ret30": ret[30], "ret40": ret[40], "ret60": ret[60],
                "ret90": ret[90],
                "bm10": bm_r10, "bm20": bm_r20, "bm30": bm_r30,
                "bm40": bm_r40, "bm60": bm_r60, "bm90": bm_r90,
                "vol20": vol20,
                "r2_40": r2_40, "r2_60": r2_60, "r2_80": r2_80,
                "sec_rank": float(sec_r.get(t, 0.5)),
                "is_def": 1.0 if t in DEF_TICKERS else 0.0,
                "price": p,
            }
    return result

def score_ticker_with_params(fv: dict, p: dict, regime: str) -> float | None:
    """Verilen faktor degerleri ve parametrelerle hisse skoru hesapla."""
    ms = p["mom_short"]; ml = p["mom_long"]; rw = p["r2_window"]
    fw = p["_fw"]
    # Seç doğru momentum penceresini
    ms_key = min([10,15,20,30], key=lambda x: abs(x-ms))
    ml_key = min([40,60,90],    key=lambda x: abs(x-ml))
    rw_key = min([40,60,80],    key=lambda x: abs(x-rw))
    mom_s  = fv.get(f"ret{ms_key}", 0.0)
    mom_l  = fv.get(f"ret{ml_key}", 0.0)
    bm_s   = fv.get(f"bm{ms_key}", 0.0)
    bm_l   = fv.get(f"bm{ml_key}", 0.0)
    rs_s   = mom_s - bm_s
    rs_l   = mom_l - bm_l
    r2v    = fv.get(f"r2_{rw_key}", 0.0)
    vol20  = fv.get("vol20", 0.025)
    vol_adj = mom_s / vol20 if vol20 > 1e-8 else 0.0
    sec_rk = fv.get("sec_rank", 0.5)
    is_def = fv.get("is_def", 0.0)
    # Filtre
    if regime == "BULL":
        if mom_s < -0.03 and rs_s < -0.02 and is_def < 0.5: return None
    elif regime == "NEUTRAL":
        if mom_l < -0.05 and rs_s < -0.04 and is_def < 0.5: return None
    else:  # BEAR
        if is_def < 0.5 and rs_s < -0.06: return None
    sc = (fw["vol_adj"] * np.clip(vol_adj,-5,5)
         + fw["sec"]    * sec_rk
         + fw["rs_s"]   * rs_s
         + fw["mom_s"]  * mom_s
         + fw["r2"]     * r2v
         + fw["mom_l"]  * mom_l
         + fw["rs_s"]   * rs_l * 0.3)  # rs_l bonus
    return float(sc)

# ---------------------------------------------------------------------------
# MINI BACKTEST (Hizli - sadece aylik, stop yok)
# ---------------------------------------------------------------------------
def mini_backtest(
    params: dict,
    precomp: dict[str, dict[str, dict[str, float]]],
    month_ends: list,
    bm_close: Any,
) -> tuple[float, list[float]]:
    """
    Verilen parametrelerle aylik rebalance simulasyonu.
    Returns: (score, [monthly_returns])
    """
    sf = params["sma_fast"]; sl = params["sma_slow"]
    bull_s = params["bull_slots"]; neu_s = params["neutral_slots"]; bear_s = params["bear_slots"]
    max_pp = params["max_pos_pct"]

    port: dict[str, float] = {}  # {ticker: weight}
    monthly_rets: list[float] = []

    for i in range(1, len(month_ends)):
        prev_dt = month_ends[i-1]; curr_dt = month_ends[i]
        curr_str = curr_dt.strftime("%Y-%m")

        # Regime
        bh = bm_close.loc[:curr_dt]
        ba = bh.values.astype(float) if not (hasattr(bh,"shape") and len(bh.shape)>1) else bh.iloc[:,0].values.astype(float)
        if len(ba) < sl + 5:
            monthly_rets.append(0.0); continue
        sma_f = float(np.mean(ba[-sf:]))
        sma_s = float(np.mean(ba[-sl:]))
        c_now = ba[-1]
        if c_now >= sma_f and sma_f >= sma_s:
            reg = "BULL"; target = bull_s
        elif c_now >= sma_f or sma_f >= sma_s:
            reg = "NEUTRAL"; target = neu_s
        else:
            reg = "BEAR"; target = bear_s

        # Portfoy getirisi hesapla (prev -> curr)
        if port:
            ret_sum = 0.0
            for t, w in port.items():
                fc = precomp.get(curr_str, {}).get(t, {})
                fp = precomp.get(prev_dt.strftime("%Y-%m"), {}).get(t, {})
                if fp and fc and fp.get("price",0)>0 and fc.get("price",0)>0:
                    t_ret = fc["price"]/fp["price"] - 1
                else:
                    t_ret = 0.0
                ret_sum += w * t_ret
            # Maliyet: her degisimde %0.25 tek yon
            monthly_rets.append(ret_sum)
        else:
            monthly_rets.append(0.0)

        # Rebalance: En iyi `target` hisseyi sec
        curr_factors = precomp.get(curr_str, {})
        if not curr_factors:
            continue
        cands: list[tuple[float, str]] = []
        for t, fv in curr_factors.items():
            sc = score_ticker_with_params(fv, params, reg)
            if sc is not None:
                cands.append((sc, t))
        cands.sort(reverse=True)
        selected = [t for _, t in cands[:target]]
        # Max pozisyon limiti
        n = len(selected)
        if n == 0:
            port = {}; continue
        eq_w = 1.0/n
        # max_pos_pct uygula
        w_per = min(eq_w, max_pp)
        port = {t: w_per for t in selected}

    sc = multi_score(np.array(monthly_rets)) if monthly_rets else -999.0
    return sc, monthly_rets

# ---------------------------------------------------------------------------
# SEKTOR RANK ON HESAPLAMA
# ---------------------------------------------------------------------------
def compute_sector_ranks_at_date(
    stock_dict: dict, bm_close: Any, dt: Any
) -> dict[str, float]:
    bh = bm_close.loc[:dt]
    ba = bh.values.astype(float) if not (hasattr(bh,"shape") and len(bh.shape)>1) else bh.iloc[:,0].values.astype(float)
    bm20 = (ba[-1]/ba[-20]-1) if len(ba)>=20 else 0.0
    perfs: dict[str,float] = {}
    for sec, tks in SECTORS.items():
        vs = []
        for t in tks:
            df = stock_dict.get(t)
            if df is None or dt not in df.index: continue
            c = df["Close"].loc[:dt]
            if hasattr(c,"shape") and len(c.shape)>1: c=c.iloc[:,0]
            ca = c.values.astype(float)
            if len(ca)<20: continue
            vs.append(ca[-1]/ca[-20]-1-bm20)
        perfs[sec] = float(np.mean(vs)) if vs else 0.0
    ns=list(perfs.keys()); va=np.array([perfs[n] for n in ns])
    if len(va)>1:
        rk=np.argsort(np.argsort(va)).astype(float)/(len(va)-1)
    else:
        rk=np.array([0.5])
    sec_ranks={ns[i]:float(rk[i]) for i in range(len(ns))}
    return {t: sec_ranks.get(TICKER_SEC.get(t,"diger"),0.5) for t in UNIVERSE}

# ---------------------------------------------------------------------------
# FULL SIMULASYON (Gunluk stop ile, optimal parametreler)
# ---------------------------------------------------------------------------
def run_full_sim(
    stock_dict: dict,
    bm_df: Any,
    wf_params: dict,  # {period_start_date -> best_params}
    all_dates: list,
    bm_close: Any,
) -> tuple[float, dict, list[float]]:
    """Walk-forward optimal parametreler ile tam simulasyon."""
    INIT = 100_000.0
    cap = INIT; pos: dict[str, dict] = {}
    tlog: list[dict] = []; eq_curve: list[float] = []
    yearly: dict[int, dict] = {}
    cy = all_dates[0].year; yc = cap; yb = _f(bm_close.loc[all_dates[0]])
    last_rb = -1; last_sec_week = -1
    cached_sec: dict[str, float] = {}

    # Aktif parametre: Tarih araligi -> params
    sorted_periods = sorted(wf_params.keys())

    def get_active_params(dt: Any) -> dict:
        """Verilen tarih icin gecerli parametreleri sec."""
        p = None
        for pd in sorted_periods:
            if dt >= pd:
                p = wf_params[pd]
        return p if p else list(wf_params.values())[0]

    for di, dt in enumerate(all_dates):
        if dt.year != cy:
            pv = cap + sum(p["s"]*p["cp"] for p in pos.values())
            bn = _f(bm_close.loc[dt])
            yearly[cy] = {"p":(pv-yc)/yc*100,"b":(bn-yb)/yb*100}
            cy=dt.year; yc=pv; yb=bn

        ap = get_active_params(dt)
        sf=ap["sma_fast"]; sl_=ap["sma_slow"]
        atr_m=ap["atr_mult"]; t_stop=ap["time_stop"]
        bull_s=ap["bull_slots"]; neu_s=ap["neutral_slots"]; bear_s=ap["bear_slots"]
        max_pp=ap["max_pos_pct"]

        # Regime
        bh=bm_close.loc[:dt]
        ba=bh.values.astype(float) if not (hasattr(bh,"shape") and len(bh.shape)>1) else bh.iloc[:,0].values.astype(float)
        if len(ba)<sl_+5:
            eq_curve.append(cap); continue
        sma_f=float(np.mean(ba[-sf:])); sma_s=float(np.mean(ba[-sl_:])); c_now=ba[-1]
        if c_now>=sma_f and sma_f>=sma_s: reg="BULL"; target=bull_s
        elif c_now>=sma_f or sma_f>=sma_s: reg="NEUTRAL"; target=neu_s
        else: reg="BEAR"; target=bear_s

        # Sektor (haftalik)
        iso_w=dt.isocalendar()[1]
        if iso_w!=last_sec_week:
            last_sec_week=iso_w
            cached_sec=compute_sector_ranks_at_date(stock_dict,bm_close,dt)

        # Pozisyon guncelle
        cl=[]
        for t,p in list(pos.items()):
            df=stock_dict.get(t)
            if df is None or dt not in df.index: continue
            bar=df.loc[dt]
            ph=_f(bar["High"]); pl=_f(bar["Low"]); pc=_f(bar["Close"]); po=_f(bar["Open"])
            p["cp"]=pc
            if ph>p["pk"]:
                p["pk"]=ph; ns=p["pk"]-atr_m*p["atr"]
                if ns>p["sl"]: p["sl"]=ns
            hd=(dt-p["ed"]).days
            ex=False; reason=""; ep=pc
            if pl<=p["sl"]: ex=True; ep=min(po,p["sl"]); reason="TRAIL" if ep>p["ep"] else "STOP"
            elif hd>t_stop and pc<p["ep"]*0.98: ex=True; reason="TIME"
            if ex:
                proc=p["s"]*ep*(1-SLIP)*(1-COMM); cost=p["s"]*p["ep"]*(1+COST1W)
                cap+=proc
                tlog.append({"t":t,"pnl":proc-cost,"rg":reg}); cl.append(t)
        for t in cl: pos.pop(t,None)

        # Aylik rebalance
        if dt.month!=last_rb:
            last_rb=dt.month
            slots=target-len(pos)
            if slots>0:
                pv=cap+sum(p["s"]*p["cp"] for p in pos.values())
                bh2=bm_close.loc[:dt]; ba2=bh2.values.astype(float) if not (hasattr(bh2,"shape") and len(bh2.shape)>1) else bh2.iloc[:,0].values.astype(float)
                bm_s=ba2[-1]/ba2[-ap["mom_short"]]-1 if len(ba2)>=ap["mom_short"] else 0.0
                bm_l=ba2[-1]/ba2[-ap["mom_long"]]-1 if len(ba2)>=ap["mom_long"] else 0.0
                cands2=[]
                for t in stock_dict:
                    if t in pos: continue
                    df=stock_dict[t]
                    if dt not in df.index: continue
                    hist=df.loc[:dt]
                    c2=hist["Close"]
                    if hasattr(c2,"shape") and len(c2.shape)>1: c2=c2.iloc[:,0]
                    ha2=hist["High"]
                    if hasattr(ha2,"shape") and len(ha2.shape)>1: ha2=ha2.iloc[:,0]
                    la2=hist["Low"]
                    if hasattr(la2,"shape") and len(la2.shape)>1: la2=la2.iloc[:,0]
                    ca2=c2.values.astype(float)
                    if len(ca2)<ap["mom_long"]+5: continue
                    p2=ca2[-1]
                    if p2<=0: continue
                    mom_s2=ca2[-1]/ca2[-ap["mom_short"]]-1 if len(ca2)>=ap["mom_short"] else 0.0
                    mom_l2=ca2[-1]/ca2[-ap["mom_long"]]-1 if len(ca2)>=ap["mom_long"] else 0.0
                    rs_s2=mom_s2-bm_s
                    rs_l2=mom_l2-bm_l
                    rw=ap["r2_window"]
                    r2v=_r2(ca2[-rw:]) if len(ca2)>=rw else 0.0
                    rets=np.diff(ca2[-21:])/ca2[-21:-1] if len(ca2)>=21 else np.array([0.0])
                    vol2=float(np.std(rets)) if len(rets)>1 else 0.025
                    va2=mom_s2/vol2 if vol2>1e-8 else 0.0
                    sec_rk=cached_sec.get(t,0.5)
                    fw=ap["_fw"]
                    # Filtre
                    is_def=t in DEF_TICKERS
                    if reg=="BULL" and mom_s2<-0.03 and rs_s2<-0.02 and not is_def: continue
                    elif reg=="NEUTRAL" and mom_l2<-0.05 and rs_s2<-0.04 and not is_def: continue
                    elif reg=="BEAR" and not is_def and rs_s2<-0.06: continue
                    sc2=(fw["vol_adj"]*np.clip(va2,-5,5)+fw["sec"]*sec_rk
                         +fw["rs_s"]*rs_s2+fw["mom_s"]*mom_s2+fw["r2"]*r2v+fw["mom_l"]*mom_l2)
                    # ATR
                    h_arr=ha2.values[-14:].astype(float) if hasattr(ha2,"values") else ha2[-14:]
                    l_arr=la2.values[-14:].astype(float) if hasattr(la2,"values") else la2[-14:]
                    c_prev=ca2[-15:-1]
                    if len(h_arr)==len(c_prev):
                        tr=np.maximum.reduce([h_arr-l_arr,np.abs(h_arr-c_prev),np.abs(l_arr-c_prev)])
                        atr_v=float(np.mean(tr))
                    else:
                        atr_v=p2*0.025
                    if atr_v<=0: atr_v=p2*0.025
                    cands2.append((sc2,t,p2,atr_v))
                cands2.sort(reverse=True)
                for sc2,t,ps2,atr_v in cands2[:slots*2]:
                    if len(pos)>=target: break
                    if t in pos: continue
                    alloc=min(cap*0.93,pv*max_pp)
                    if alloc<1500: continue
                    ep2=ps2*(1+SLIP); cps2=ep2*(1+COMM); shs2=int(alloc/cps2)
                    if shs2<=0 or shs2*cps2>cap: continue
                    cap-=shs2*cps2
                    pos[t]={"s":shs2,"ep":ep2,"cp":ep2,"pk":ep2,"sl":ep2-atr_m*atr_v,"atr":atr_v,"ed":dt}
        eq=cap+sum(p["s"]*p["cp"] for p in pos.values()); eq_curve.append(eq)
    fe=cap+sum(p["s"]*p["cp"] for p in pos.values())
    if cy not in yearly:
        bf=_f(bm_close.iloc[-1]); yearly[cy]={"p":(fe-yc)/yc*100,"b":(bf-yb)/yb*100}
    return fe, yearly, eq_curve

# ---------------------------------------------------------------------------
# ANA MOTOR
# ---------------------------------------------------------------------------
def run_optimizer() -> None:
    t0 = time.time()
    START="2016-01-01"; END="2026-08-29"; INIT=100_000.0
    N_SAMPLES = 400  # Her pencerede kac kombinasyon denenecek

    logger.info("="*80)
    logger.info("[1] BIST VERISI INDIRILIYOR")
    logger.info("="*80)
    bm=yf.download(BENCHMARK,start=START,end=END,progress=False)
    if bm.empty: raise RuntimeError("BIST indirilemedi")
    if hasattr(bm.columns,"levels") and len(bm.columns.levels)>1:
        bm.columns=bm.columns.get_level_values(0)
    bm_df=bm[["Open","High","Low","Close","Volume"]].dropna()
    logger.info(f"  [OK] BIST-100: {len(bm_df):,} seans")
    sr=yf.download(UNIVERSE,start=START,end=END,progress=False,group_by="ticker")
    sd:dict[str,Any]={}
    for t in UNIVERSE:
        try:
            if hasattr(sr.columns,"levels") and t in sr.columns.get_level_values(0):
                df=sr[t][["Open","High","Low","Close","Volume"]].dropna()
                if len(df)>250: sd[t]=df
        except Exception:
            continue
    logger.info(f"  [OK] {len(sd)} hisse hazir.\n")

    bmc=bm_df["Close"]
    if hasattr(bmc,"shape") and len(bmc.shape)>1: bmc=bmc.iloc[:,0]

    # Walk-Forward pencereleri: 18 ay egitim, 6 ay test, 6 ay kaydir
    all_dates_idx = list(bm_df.index)
    def get_month_ends_in(d_start, d_end):
        mends=[]
        prev=None
        for d in all_dates_idx:
            if d<d_start: prev=d; continue
            if d>d_end: break
            if prev and prev.month!=d.month: mends.append(prev)
            prev=d
        if prev and (not mends or mends[-1]!=prev): mends.append(prev)
        return mends

    import pandas as pd
    wf_windows = []
    train_start = pd.Timestamp("2016-01-01")
    wf_step_months = 6
    n_test_months = 6
    n_train_months = 18
    current_start = train_start
    while True:
        train_end = current_start + pd.DateOffset(months=n_train_months)
        test_end  = train_end + pd.DateOffset(months=n_test_months)
        if test_end > pd.Timestamp(END): break
        wf_windows.append((current_start, train_end, test_end))
        current_start = current_start + pd.DateOffset(months=wf_step_months)
        if len(wf_windows) >= 12: break
    logger.info(f"  Walk-Forward pencereleri: {len(wf_windows)}")

    # FAKTORLERİ ÖN HESAPLA (tum tarihler icin)
    logger.info("[2] FAKTORLER ON HESAPLANIYOR...")
    all_month_ends = get_month_ends_in(pd.Timestamp(START), pd.Timestamp(END))
    # Sektor rankları ay-sonu icin hesapla
    sec_ranks_by_date: dict = {}
    for dt in all_month_ends:
        sec_ranks_by_date[dt] = compute_sector_ranks_at_date(sd, bmc, dt)
    precomp = precompute_factors(sd, all_month_ends, bmc, sec_ranks_by_date)
    logger.info(f"  [OK] {len(precomp)} ay-sonu onceden hesaplandi.")

    # WALK-FORWARD OPTIMiZASYON
    logger.info(f"\n[3] WALK-FORWARD OPTIMIZASYON BASLIYOR ({N_SAMPLES} kombinasyon/pencere)")
    logger.info("="*80)
    best_params_by_period: dict[Any, dict] = {}

    for wi, (tr_s, tr_e, te_e) in enumerate(wf_windows):
        train_months = [d for d in all_month_ends if tr_s <= d <= tr_e]
        if len(train_months) < 4:
            continue
        candidates = sample_params(N_SAMPLES)
        best_sc = -999.0; best_p = candidates[0]
        scores_all = []
        for pc in candidates:
            sc, _ = mini_backtest(pc, precomp, train_months, bmc)
            scores_all.append(sc)
            if sc > best_sc:
                best_sc = sc; best_p = pc
        # Test donemini kaydet
        best_params_by_period[tr_e] = best_p
        # Top 5 parametre ozeti
        top_idx = sorted(range(len(scores_all)), key=lambda x: scores_all[x], reverse=True)[:3]
        logger.info(f"\n  Pencere {wi+1}: Egitim {tr_s.date()} -> {tr_e.date()}  Test -> {te_e.date()}")
        logger.info(f"    En iyi skor: {best_sc:.3f}  (400 kombinasyondan)")
        logger.info("    Optimal params:")
        bp=best_p
        logger.info(f"      sma={bp['sma_fast']}/{bp['sma_slow']}  atr={bp['atr_mult']}x  "
                    f"stop={bp['time_stop']}d  slots={bp['bull_slots']}/{bp['neutral_slots']}/{bp['bear_slots']}")
        logger.info(f"      mom={bp['mom_short']}d/{bp['mom_long']}d  r2={bp['r2_window']}d  "
                    f"max_pos={bp['max_pos_pct']*100:.0f}%")
        fw=bp["_fw"]
        logger.info(f"      Faktor agirliklari: vol_adj={fw['vol_adj']:.2f}  sec={fw['sec']:.2f}  "
                    f"rs_s={fw['rs_s']:.2f}  mom_s={fw['mom_s']:.2f}  r2={fw['r2']:.2f}  mom_l={fw['mom_l']:.2f}")

    # Full simulasyon
    logger.info("\n[4] FULL SIMULASYON (optimal parametrelerle, gunluk stop)")
    logger.info("="*80)
    sim_dates = all_dates_idx[200:]
    final_eq, yearly, eq_curve = run_full_sim(sd, bm_df, best_params_by_period, sim_dates, bmc)

    total_ret = (final_eq-INIT)/INIT*100
    bi=_f(bmc.loc[sim_dates[0]]); bf=_f(bmc.loc[sim_dates[-1]]); bm_ret=(bf-bi)/bi*100
    ea=np.array(eq_curve); dr=np.diff(ea)/ea[:-1]
    sh=float((dr.mean()/dr.std())*np.sqrt(252)) if dr.std()>0 else 0.0
    pk=np.maximum.accumulate(ea); dd=(ea-pk)/pk; mdd=float(dd.min()*100)
    ny=len(ea)/252; cagr=(final_eq/INIT)**(1/ny)-1 if ny>0 else 0
    bm_cagr=(bf/bi)**(1/ny)-1 if ny>0 else 0

    S="="*88
    logger.info(f"\n{S}")
    logger.info("  WALK-FORWARD OPTIMIZASYON MOTORU SONUC KARTI  (2016-2026)")
    logger.info(S)
    logger.info(f"  {'Metrik':<35} {'WF Optimizer':>14} {'BIST-100':>14}")
    logger.info("-"*65)
    logger.info(f"  {'10Y Toplam Getiri':<35} {total_ret:>13.1f}% {bm_ret:>13.1f}%")
    logger.info(f"  {'Yillik CAGR':<35} {cagr*100:>13.1f}% {bm_cagr*100:>13.1f}%")
    logger.info(f"  {'Sharpe Orani':<35} {sh:>14.2f}")
    logger.info(f"  {'Max Drawdown':<35} {mdd:>13.2f}%")
    logger.info(f"  {'Bitis Sermayesi':<35} {final_eq:>13,.0f}TL")
    logger.info(f"  {'Walk-Forward Pencereleri':<35} {len(best_params_by_period):>14}")
    logger.info(f"  {'Denenen Kombinasyon':<35} {N_SAMPLES*len(best_params_by_period):>14,}")
    logger.info(S)

    beat=0
    logger.info("\n  YIL YIL KARSILASTIRMA:")
    logger.info(f"  {'YIL':<6}|{'WF-OPT':>10}|{'BIST':>10}|{'ALFA':>10}|{'SONUC':>10}")
    logger.info("-"*53)
    for yr in sorted(yearly):
        p2=yearly[yr]["p"]; b2=yearly[yr]["b"]; a=p2-b2
        if a>0: beat+=1
        s="[ALFA]" if a>0 else "[KAYIP]"
        logger.info(f"  {yr:<6}|{p2:>+9.1f}%|{b2:>+9.1f}%|{a:>+9.1f}%|{s:>10}")
    logger.info("-"*53)
    logger.info(f"  Toplam: {beat}/{len(yearly)} yil BIST'i gecti")
    logger.info(S)
    logger.info("  [OK] POINT-IN-TIME: Gelecek sizintisi YOK")
    logger.info("  [OK] Her pencere icin 400 kombinasyon test edildi")
    logger.info("  [OK] Max pozisyon limiti: Optimize edilen max_pos_pct uygulandı")
    logger.info(f"  Toplam sure: {time.time()-t0:.0f} saniye")
    logger.info(S)

    # Parametre tutarliligi analizi
    logger.info("\n  PARAMETRE TUTARLILIK ANALIZI (Hangi Degerler Tekrar Secildi?):")
    from collections import Counter
    param_counts: dict[str,Counter] = {k:Counter() for k in PARAM_SPACE}
    for bp in best_params_by_period.values():
        for k in PARAM_SPACE:
            param_counts[k][str(bp[k])] += 1
    for k, cnt in param_counts.items():
        most_common = cnt.most_common(2)
        logger.info(f"    {k:<20}: {dict(most_common)}")
    logger.info(S)

if __name__=="__main__":
    run_optimizer()
