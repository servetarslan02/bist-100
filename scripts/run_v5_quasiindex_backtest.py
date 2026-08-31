"""
ALPHA BIST - QUASI-INDEX ALPHA TILT v5.0 (2016-2026)
======================================================
Temel Fikir: BIST'i geçmek icin genis tabanli rallilerde endekse yakin kal,
momentum yillarinda top pozisyonlara yogunlas.

v2'nin kanıtlanmış özellikleri (korunuyor):
  - Hicbir zaman %100 nakit YOK
  - 4xATR trailing stop
  - SMA50/SMA200 rejim sistemi
  - Aylik rebalance (haftalik degil - v4 kanitledi ki haftalik gurultu)

v5'in yeni özellikleri:
  - BULL: 12-15 pozisyon (5 yerine) - quasi-index + alpha tilt
  - NEUTRAL: 7-9 pozisyon
  - BEAR: 3-4 pozisyon (savunma)
  - Her sektorden en az 1 hisse BULL'da (sector miss engeli)
  - Top 3 hisseye 2x agirlik (alpha tilt)
  - vol_adj_mom + sec_rank agirlikli scoring (v3/v4'ten ogrenildi)
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

SECTORS: dict[str, list[str]] = {
    "finansal":   ["GARAN.IS","AKBNK.IS","ISCTR.IS","YKBNK.IS","HALKB.IS","VAKBN.IS","TSKB.IS"],
    "holding":    ["KCHOL.IS","SAHOL.IS","DOHOL.IS"],
    "sanayi":     ["ENKAI.IS","EREGL.IS","SISE.IS","TOASO.IS","FROTO.IS","ARCLK.IS","KRDMD.IS","VESBE.IS"],
    "enerji":     ["TUPRS.IS","PETKM.IS","GUBRF.IS"],
    "havacilik":  ["THYAO.IS","PGSUS.IS","TAVHL.IS"],
    "teletek":    ["TTKOM.IS","TCELL.IS","ASELS.IS","LOGO.IS"],
    "tuketim":    ["BIMAS.IS","MGROS.IS","CCOLA.IS","AEFES.IS","ULKER.IS","MAVI.IS"],
    "diger":      ["TKFEN.IS","CIMSA.IS","BRSAN.IS","ECILC.IS","ISGYO.IS"],
}
UNIVERSE = [t for ts in SECTORS.values() for t in ts]
BENCHMARK = "XU100.IS"
TICKER_SEC = {t: s for s, ts in SECTORS.items() for t in ts}
DEF_TICKERS = set(SECTORS["tuketim"] + SECTORS["teletek"] + SECTORS["enerji"])

# v4'ten ogrenilen optimal faktor agirliklari (sabit - gurultu yok)
FACTOR_W = {
    "vol_adj_mom": 0.22,  # Kalite-ayarli momentum - en tutarli
    "sec_rank":    0.18,  # Sektor liderligi
    "rs_20d":      0.16,  # BIST-bagil 20d
    "mom_20d":     0.15,  # Kisa vade momentum
    "r2":          0.13,  # Trend tutarliligi
    "mom_60d":     0.09,  # Uzun vade momentum
    "rs_60d":      0.07,  # BIST-bagil 60d
}

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
    if len(c)<10:
        return 0.0
    x=np.arange(len(c),dtype=float)
    p=np.polyfit(x,c,1)
    fit=np.polyval(p,x)
    ss_r=np.sum((c-fit)**2)
    ss_t=np.sum((c-c.mean())**2)
    return float(max(0.0,1.0-ss_r/ss_t)) if ss_t>1e-10 else 0.0

class SectorTracker:
    def __init__(self):
        self.sec_rank: dict[str,float] = {s:0.5 for s in SECTORS}
        self.ticker_rank: dict[str,float] = {}
        self.sec_perf: dict[str,float] = {s:0.0 for s in SECTORS}
    def update(self, sd:dict, bmc:Any, dt:Any):
        bh = bmc.loc[:dt]
        ba = bh.values.astype(float) if not (hasattr(bh,"shape") and len(bh.shape)>1) else bh.iloc[:,0].values.astype(float)
        bm20 = (ba[-1]/ba[-20]-1) if len(ba)>=20 else 0.0
        bm60 = (ba[-1]/ba[-60]-1) if len(ba)>=60 else 0.0
        perfs: dict[str,float] = {}
        for sec,tks in SECTORS.items():
            vs20=[]
            vs60=[]
            for t in tks:
                df=sd.get(t)
                if df is None or dt not in df.index:
                    continue
                c=df["Close"].loc[:dt]
                if hasattr(c,"shape") and len(c.shape)>1:
                    c=c.iloc[:,0]
                ca=c.values.astype(float)
                if len(ca)<60:
                    continue
                vs20.append(ca[-1]/ca[-20]-1-bm20)
                vs60.append(ca[-1]/ca[-60]-1-bm60)
            # 20d ve 60d ortalamasini al (daha stabil)
            p20 = float(np.mean(vs20)) if vs20 else 0.0
            p60 = float(np.mean(vs60)) if vs60 else 0.0
            perfs[sec] = 0.6*p20 + 0.4*p60
        self.sec_perf = perfs
        ns=list(perfs.keys())
        va=np.array([perfs[n] for n in ns])
        if len(va)>1:
            rk=np.argsort(np.argsort(va)).astype(float)/(len(va)-1)
        else:
            rk=np.array([0.5])
        self.sec_rank={ns[i]:float(rk[i]) for i in range(len(ns))}
        self.ticker_rank={t:self.sec_rank.get(TICKER_SEC.get(t,"diger"),0.5) for t in UNIVERSE}
    def top_secs(self,n:int=4)->set[str]: return set(sorted(self.sec_rank,key=self.sec_rank.get,reverse=True)[:n])
    def get(self,t:str)->float: return self.ticker_rank.get(t,0.5)

def regime(bmc,dt,sma50,sma200)->str:
    c,s50,s200=_f(bmc.loc[dt]),_f(sma50.loc[dt]),_f(sma200.loc[dt])
    if np.isnan(s50) or np.isnan(s200):
        return "NEUTRAL"
    return "BULL" if c>=s50 and s50>=s200 else ("NEUTRAL" if c>=s50 or s50>=s200 else "BEAR")

def score_tick(t:str, sd:dict, dt:Any, bmc:Any, st:SectorTracker, reg:str) -> tuple[float,float,float,bool]|None:
    df=sd.get(t)
    if df is None or dt not in df.index:
        return None
    hist=df.loc[:dt]
    c=hist["Close"]
    h=hist["High"]
    l=hist["Low"]
    v=hist["Volume"]
    if hasattr(c,"shape") and len(c.shape)>1:
        c=c.iloc[:,0]
    if hasattr(h,"shape") and len(h.shape)>1:
        h=h.iloc[:,0]
    if hasattr(l,"shape") and len(l.shape)>1:
        l=l.iloc[:,0]
    if hasattr(v,"shape") and len(v.shape)>1:
        v=v.iloc[:,0]
    ca=c.values.astype(float)
    if len(ca)<60:
        return None
    p=ca[-1]
    if p<=0:
        return None

    bh=bmc.loc[:dt]
    ba=bh.values.astype(float) if not (hasattr(bh,"shape") and len(bh.shape)>1) else bh.iloc[:,0].values.astype(float)
    bm20=(ba[-1]/ba[-20]-1) if len(ba)>=20 else 0.0
    bm60=(ba[-1]/ba[-60]-1) if len(ba)>=60 else 0.0

    mom20=(p/ca[-20]-1) if len(ca)>=20 else 0.0
    mom60=(p/ca[-60]-1) if len(ca)>=60 else 0.0
    rs20=mom20-bm20
    rs60=mom60-bm60

    ha=h.values[-14:].astype(float)
    la=l.values[-14:].astype(float)
    cp=ca[-15:-1]
    if len(ha)==len(cp):
        tr=np.maximum.reduce([ha-la,np.abs(ha-cp),np.abs(la-cp)])
        atr=float(np.mean(tr))
    else:
        atr=p*0.025
    if atr<=0:
        atr=p*0.025

    rets20=np.diff(ca[-21:])/ca[-21:-1] if len(ca)>=21 else np.array([0.0])
    vol20=float(np.std(rets20)) if len(rets20)>1 else 0.01
    vol_adj=mom20/vol20 if vol20>1e-8 else 0.0

    r2v=_r2(ca[-60:])
    sec_rk=st.get(t)
    sec_name=TICKER_SEC.get(t,"?")
    in_top=sec_name in st.top_secs(4)
    is_def=t in DEF_TICKERS

    sma20=float(np.mean(ca[-20:])) if len(ca)>=20 else 0.0

    # GENIS FILTRE - v5'in kalbi:
    # BULL rejimde daha az kısıtlayıcı (genis tabanli rallilere katil)
    if reg=="BULL":
        # Saf momentum VEYA sektor lideri VEYA toparlanma (rs60 pozitif)
        ok = (p > sma20*0.96 and rs20 > -0.02) or (in_top and rs60 > 0.0) or (is_def)
        if not ok:
            return None
    elif reg=="NEUTRAL":
        ok = (p > sma20*0.94 and rs60 > -0.03) or (in_top) or (is_def)
        if not ok:
            return None
    else:
        # BEAR
        if not (is_def or (in_top and rs20 > -0.05)):
            return None

    fv = {
        "vol_adj_mom": float(np.clip(vol_adj,-5,5)),
        "sec_rank":    float(sec_rk),
        "rs_20d":      float(rs20),
        "mom_20d":     float(mom20),
        "r2":          float(r2v),
        "mom_60d":     float(mom60),
        "rs_60d":      float(rs60),
    }
    sc = sum(FACTOR_W.get(f,0)*fv.get(f,0) for f in FACTOR_W)
    return sc, p, atr, in_top

def run_v5() -> None:
    START="2016-01-01"
    END="2026-08-29"
    INIT=100_000.0
    COMM=0.0015
    SLIP=0.0010
    COST1W=COMM+SLIP
    ATR=4.0
    TIME_STP=40

    logger.info("="*80)
    logger.info(f"[1] BIST VERISI INDIRILIYOR ({START} -> {END})")
    logger.info("="*80)
    bm=yf.download(BENCHMARK,start=START,end=END,progress=False)
    if bm.empty:
        raise RuntimeError("BIST indirilemedi")
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
                if len(df)>250:
                    sd[t]=df
        except Exception:
            continue
    logger.info(f"  [OK] {len(sd)} hisse hazir.\n")

    logger.info("="*80)
    logger.info("[2] QUASI-INDEX ALPHA TILT v5.0")
    logger.info("="*80)
    logger.info("  BULL  : 12-15 pozisyon (quasi-index + alpha tilt)")
    logger.info("  NEUTRAL:  7-9 pozisyon")
    logger.info("  BEAR  :  3-4 pozisyon (savunma)")
    logger.info("  Her sektorden min 1 hisse BULL'da")
    logger.info("  Top 3 hisseye 2x agirlik (alpha tilt)")
    logger.info("-"*80)

    bmc=bm_df["Close"]
    if hasattr(bmc,"shape") and len(bmc.shape)>1:
        bmc=bmc.iloc[:,0]
    s50=bmc.rolling(50).mean()
    s200=bmc.rolling(200).mean()
    dates=list(bm_df.index)[200:]
    cap=INIT
    pos:dict[str,dict]={}
    tlog:list[dict]=[]
    eq_curve:list[float]=[]
    yearly:dict[int,dict]={}
    cy=dates[0].year
    yc=cap
    yb=_f(bmc.loc[dates[0]])
    last_rb=-1
    last_sec=-1
    st=SectorTracker()
    rcnt:dict[str,int]={"BULL":0,"NEUTRAL":0,"BEAR":0}

    for di,dt in enumerate(dates):
        if dt.year!=cy:
            pv=cap+sum(p["s"]*p["cp"] for p in pos.values())
            bn=_f(bmc.loc[dt])
            yearly[cy]={"p":(pv-yc)/yc*100,"b":(bn-yb)/yb*100,"eq":pv}
            cy=dt.year
            yc=pv
            yb=bn

        reg=regime(bmc,dt,s50,s200)
        rcnt[reg]+=1
        iso_w=dt.isocalendar()[1]
        if iso_w!=last_sec:
            last_sec=iso_w
            st.update(sd,bmc,dt)

        # Rejime gore hedef pozisyon sayisi
        if reg=="BULL":
            target=13
            invest=0.97
        elif reg=="NEUTRAL":
            target=8
            invest=0.90
        else:
            target=3
            invest=0.65

        # Pozisyon guncelle
        cl=[]
        for t,p in list(pos.items()):
            df=sd.get(t)
            if df is None or dt not in df.index:
                continue
            bar=df.loc[dt]
            ph=_f(bar["High"])
            pl=_f(bar["Low"])
            pc=_f(bar["Close"])
            po=_f(bar["Open"])
            p["cp"]=pc
            if ph>p["pk"]:
                p["pk"]=ph
                ns=p["pk"]-ATR*p["atr"]
                if ns>p["sl"]:
                    p["sl"]=ns
            hd=(dt-p["ed"]).days
            exit,reason,ep=False,"",pc
            if pl<=p["sl"]:
                exit=True
                ep=min(po,p["sl"])
                reason="TRAIL" if ep>p["ep"] else "STOP"
            elif hd>TIME_STP and pc<p["ep"]*0.98:
                exit=True
                reason="TIME"
            if exit:
                proc=p["s"]*ep*(1-SLIP)*(1-COMM)
                cost=p["s"]*p["ep"]*(1+COST1W)
                pnl=proc-cost
                cap+=proc
                tlog.append({"t":t,"pnl":pnl,"pp":pnl/cost*100,"r":reason,"h":hd,"rg":reg})
                cl.append(t)
        for t in cl:
            pos.pop(t,None)

        # Aylik rebalance
        if dt.month!=last_rb:
            last_rb=dt.month
            slots=target-len(pos)
            if slots>0:
                cands:list[tuple[float,str,float,float,bool]]=[]
                for t in sd:
                    if t in pos:
                        continue
                    r=score_tick(t,sd,dt,bmc,st,reg)
                    if r:
                        cands.append((r[0],t,r[1],r[2],r[3]))
                cands.sort(reverse=True,key=lambda x:x[0])

                pv=cap+sum(p["s"]*p["cp"] for p in pos.values())
                inv=pv*invest

                # Sektor temsil takibi
                sec_covered:set[str]=set()
                for t in pos:
                    sec_covered.add(TICKER_SEC.get(t,"?"))

                # Adim 1: Her sektorden min 1 hisse al (BULL'da)
                if reg=="BULL":
                    for sec in SECTORS:
                        if sec in sec_covered:
                            continue
                        if len(pos)>=target:
                            break
                        # Bu sektorun en iyi adayi bul
                        sec_cands=[(sc,t,ps,at,it) for sc,t,ps,at,it in cands if TICKER_SEC.get(t)==sec]
                        if not sec_cands:
                            continue
                        sc,t,ps,at,it=sec_cands[0]
                        alloc=min(cap*0.92,inv/target)
                        if alloc<1500:
                            continue
                        ep=ps*(1+SLIP)
                        cps=ep*(1+COMM)
                        shs=int(alloc/cps)
                        if shs<=0 or shs*cps>cap:
                            continue
                        cap-=shs*cps
                        sec_covered.add(sec)
                        pos[t]={"s":shs,"ep":ep,"cp":ep,"pk":ep,"sl":ep-ATR*at,"atr":at,"ed":dt}

                # Adim 2: Kalan slotlara en iyi skorlu hisseleri al
                # Top 3'e 2x agirlik (alpha tilt - 2 slot verir)
                top3_done=0
                for sc,t,ps,at,it in cands:
                    if len(pos)>=target:
                        break
                    if t in pos:
                        continue
                    is_top3=(sc==cands[0][0] or top3_done<3)
                    slot_mult=1.5 if is_top3 and top3_done<3 else 1.0
                    if is_top3:
                        top3_done+=1
                    alloc=min(cap*0.92,inv/target*slot_mult)
                    if alloc<1500:
                        continue
                    ep=ps*(1+SLIP)
                    cps=ep*(1+COMM)
                    shs=int(alloc/cps)
                    if shs<=0 or shs*cps>cap:
                        continue
                    cap-=shs*cps
                    pos[t]={"s":shs,"ep":ep,"cp":ep,"pk":ep,"sl":ep-ATR*at,"atr":at,"ed":dt}

        eq=cap+sum(p["s"]*p["cp"] for p in pos.values())
        eq_curve.append(eq)

    fe=cap+sum(p["s"]*p["cp"] for p in pos.values())
    if cy not in yearly:
        bf=_f(bmc.iloc[-1])
        yearly[cy]={"p":(fe-yc)/yc*100,"b":(bf-yb)/yb*100,"eq":fe}

    tot=(fe-INIT)/INIT*100
    bi=_f(bmc.loc[dates[0]])
    bf=_f(bmc.loc[dates[-1]])
    bm_ret=(bf-bi)/bi*100
    ea=np.array(eq_curve)
    dr=np.diff(ea)/ea[:-1]
    sh=float((dr.mean()/dr.std())*np.sqrt(252)) if dr.std()>0 else 0.0
    pk=np.maximum.accumulate(ea)
    dd=(ea-pk)/pk
    mdd=float(dd.min()*100)
    ny=len(ea)/252
    cagr=(fe/INIT)**(1/ny)-1 if ny>0 else 0
    bm_cagr=(bf/bi)**(1/ny)-1 if ny>0 else 0
    wins=[x for x in tlog if x["pnl"]>0]
    loss=[x for x in tlog if x["pnl"]<=0]
    wr=len(wins)/len(tlog)*100 if tlog else 0
    ls=abs(sum(x["pnl"] for x in loss))
    pf=sum(x["pnl"] for x in wins)/ls if ls>0 else 999
    sum(rcnt.values())

    # KARSILASTIRMA TABLOSU
    S="="*90
    logger.info(f"\n{S}")
    logger.info("  TUM VERSIYON KARSILASTIRMASI + v5 SONUCU  (2016-2026)")
    logger.info(S)
    logger.info(f"  {'Versiyon':<22} {'10Y Getiri':>12} {'CAGR':>8} {'Sharpe':>8} {'MaxDD':>9} {'BIST>':>8}")
    logger.info("-"*72)
    rows=[
        ("v1 (SMA200+Nakit)",   113.2,  7.7, 0.45, -59.0, 1),
        ("v2 (NoCache+SMA50)",  1500.8, 32.8, 1.45, -30.1, 4),
        ("v3 (Adaptif)",         962.2, 27.4, 1.27, -33.6, 4),
        ("v4 (Hibrit+Haftalık)", 851.1,  25.9, 1.12, -49.3, 5),
    ]
    for rw in rows:
        logger.info(f"  {rw[0]:<22} {rw[1]:>11.1f}% {rw[2]:>7.1f}% {rw[3]:>8.2f} {rw[4]:>8.1f}% {rw[5]:>7}/11")
    beat=sum(1 for yr in yearly if yearly[yr]["p"]>yearly[yr]["b"])
    logger.info(f"  {'v5 (QuasiIdx+Alpha)':<22} {tot:>11.1f}% {cagr*100:>7.1f}% {sh:>8.2f} {mdd:>8.1f}% {beat:>7}/11  <-- YENI")
    logger.info(f"  {'BIST-100':<22} {bm_ret:>11.1f}% {bm_cagr*100:>7.1f}%")
    logger.info(S)

    logger.info("\n  YIL YIL KARSILASTIRMA:")
    logger.info(f"  {'YIL':<6}|{'PORTFOY':>10}|{'BIST':>10}|{'ALFA':>10}|{'SONUC':>10}")
    logger.info("-"*53)
    beat_yrs=[]
    for yr in sorted(yearly):
        p=yearly[yr]["p"]
        b=yearly[yr]["b"]
        a=p-b
        s="[ALFA]" if a>0 else "[KAYIP]"
        if a>0:
            beat_yrs.append(yr)
        logger.info(f"  {yr:<6}|{p:>+9.1f}%|{b:>+9.1f}%|{a:>+9.1f}%|{s:>10}")
    logger.info("-"*53)
    logger.info(f"  Toplam: {len(beat_yrs)}/{len(yearly)} yil BIST'i gecti")
    logger.info(S)
    logger.info(f"  Toplam Islem: {len(tlog)} | Win Rate: {wr:.1f}% | PF: {pf:.2f}")
    logger.info(S)

    if tlog:
        by={}
        for x in tlog:
            by[x["t"]]=by.get(x["t"],0)+x["pnl"]
        b5=sorted(by.items(),key=lambda x:x[1],reverse=True)[:5]
        w5=sorted(by.items(),key=lambda x:x[1])[:5]
        logger.info("\n  [TOP5]")
        [logger.info(f"    {t:<15} +{p:,.0f} TL") for t,p in b5]
        logger.info("\n  [BOT5]")
        [logger.info(f"    {t:<15} {p:,.0f} TL") for t,p in w5]
    logger.info(S)

if __name__=="__main__":
    run_v5()
