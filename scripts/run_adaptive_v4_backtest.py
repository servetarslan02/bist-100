"""
ALPHA BIST - HIBRIT UYARLAMALI STRATEJI v4.0 (2016-2026)
=========================================================
v2'nin kazanan ozellikleri + adaptif sektor rotasyonu + haftalik rebalance

v2'nin guclu yonleri (korunuyor):
  - Hicbir zaman %100 nakit YOK
  - SMA50/SMA200 3-kademeli rejim
  - 4xATR genis stop
  - Sektor filtreli geniş evren

Yeni eklemeler (v4):
  - HAFTALIK rebalance: Sektor rotasyonuna hizli uyum (ayliktan daha iyi)
  - Sektor konsantrasyon limiti: Max %40 tek sektor
  - "Erken Giris" modu: rs_20d negatif ama rs_60d pozitif olan "toparlanma" hisseleri
  - Vol ölçekleme: Dusuk vol = 7 pozisyon, kriz = 3 pozisyon
  - Ceyreklik adaptasyon: Hangi faktor bu ceyrek calisıyor?
"""
from __future__ import annotations
import sys, warnings
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
DEF_TICKERS = set(SECTORS["tuketim"] + SECTORS["teletek"])

def _f(v: Any) -> float:
    if hasattr(v,"values"): v = v.values
    if hasattr(v,"item"):
        try: return float(v.item())
        except: pass
    a = np.ravel(v)
    return float(a[0]) if len(a)>0 else 0.0

def _rank_corr(x: np.ndarray, y: np.ndarray) -> float:
    n = len(x)
    if n < 4: return 0.0
    rx = np.argsort(np.argsort(x)).astype(float)
    ry = np.argsort(np.argsort(y)).astype(float)
    d2 = float(np.sum((rx-ry)**2))
    den = float(n*(n**2-1))
    return 1.0 - 6.0*d2/den if den>0 else 0.0

def _r2(c: np.ndarray) -> float:
    if len(c)<10: return 0.0
    x=np.arange(len(c),dtype=float)
    p=np.polyfit(x,c,1); fit=np.polyval(p,x)
    ss_r=np.sum((c-fit)**2); ss_t=np.sum((c-c.mean())**2)
    return float(max(0.0,1.0-ss_r/ss_t)) if ss_t>1e-10 else 0.0

class SectorTracker:
    def __init__(self):
        self.sec_perf: dict[str,float] = {s:0.0 for s in SECTORS}
        self.sec_rank: dict[str,float] = {s:0.5 for s in SECTORS}
        self.ticker_rank: dict[str,float] = {}
    def update(self, sd:dict, bmc:Any, dt:Any):
        bh = bmc.loc[:dt]
        bh_arr = bh.values.astype(float) if not (hasattr(bh,"shape") and len(bh.shape)>1) else bh.iloc[:,0].values.astype(float)
        bm_r20 = (bh_arr[-1]/bh_arr[-20]-1) if len(bh_arr)>=20 else 0.0
        perfs: dict[str,float] = {}
        for sec,tks in SECTORS.items():
            vs=[]
            for t in tks:
                df=sd.get(t)
                if df is None or dt not in df.index: continue
                c=df["Close"].loc[:dt]
                if hasattr(c,"shape") and len(c.shape)>1: c=c.iloc[:,0]
                ca=c.values.astype(float)
                if len(ca)<20: continue
                vs.append(ca[-1]/ca[-20]-1-bm_r20)
            perfs[sec]=float(np.mean(vs)) if vs else 0.0
        ns=list(perfs.keys()); va=np.array([perfs[n] for n in ns])
        if len(va)>1:
            rk=np.argsort(np.argsort(va)).astype(float)/(len(va)-1)
        else:
            rk=np.array([0.5])
        self.sec_perf=perfs
        self.sec_rank={ns[i]:float(rk[i]) for i in range(len(ns))}
        self.ticker_rank={t:self.sec_rank.get(TICKER_SEC.get(t,"diger"),0.5) for t in UNIVERSE}
    def get(self,t:str)->float: return self.ticker_rank.get(t,0.5)
    def top_sectors(self,n:int=3)->list[str]:
        return sorted(self.sec_rank,key=self.sec_rank.get,reverse=True)[:n]

class Adaptor:
    FACS=["mom_20d","mom_60d","rs_20d","rs_60d","vol_adj","r2","sec_rank"]
    def __init__(self):
        n=len(self.FACS); self.w={f:1/n for f in self.FACS}; self.log=[]; self.cnt=0
    def rec(self,fv:dict,ret:float): self.log.append({"f":fv,"r":ret})
    def upd(self):
        if len(self.log)<20: return
        rec=self.log[-80:]; ra=np.array([x["r"] for x in rec]); nw={}
        for f in self.FACS:
            fa=np.array([x["f"].get(f,0.0) for x in rec])
            if np.std(fa)<1e-8: nw[f]=0.02; continue
            c=_rank_corr(fa,ra); nw[f]=max(0.01,(c+1)/2)
        t=sum(nw.values()); self.w={f:v/t for f,v in nw.items()}; self.cnt+=1
        top=sorted(self.w.items(),key=lambda x:x[1],reverse=True)[:3]
        logger.info(f"[ADAPT #{self.cnt}] Top3: "+", ".join(f"{f}={v:.3f}" for f,v in top))
    def score(self,fv:dict)->float:
        return sum(self.w.get(f,0)*fv.get(f,0) for f in self.FACS)

def vol_slots(bmc:Any, dt:Any) -> tuple[int,float]:
    h=bmc.loc[:dt]
    if len(h)<22: return 5,0.90
    ha=h.values.astype(float) if not (hasattr(h,"shape") and len(h.shape)>1) else h.iloc[:,0].values.astype(float)
    rets=np.diff(ha[-21:])/ha[-21:-1]
    v=float(np.std(rets[~np.isnan(rets)])*np.sqrt(252)) if len(rets)>2 else 0.25
    if v<0.15: return 7,1.00
    elif v<0.25: return 5,0.95
    elif v<0.35: return 4,0.80
    else: return 3,0.60

def reg(bmc,dt,sma50,sma200)->str:
    c,s50,s200=_f(bmc.loc[dt]),_f(sma50.loc[dt]),_f(sma200.loc[dt])
    if np.isnan(s50) or np.isnan(s200): return "NEUTRAL"
    return "BULL" if c>=s50 and s50>=s200 else ("NEUTRAL" if c>=s50 or s50>=s200 else "BEAR")

def score_tick(t:str, sd:dict, dt:Any, bmc:Any, sec:SectorTracker, regime:str, adaptor:Adaptor) -> tuple[float,float,float,dict]|None:
    df=sd.get(t)
    if df is None or dt not in df.index: return None
    hist=df.loc[:dt]
    c=hist["Close"]
    if hasattr(c,"shape") and len(c.shape)>1: c=c.iloc[:,0]
    h=hist["High"]
    if hasattr(h,"shape") and len(h.shape)>1: h=h.iloc[:,0]
    l=hist["Low"]
    if hasattr(l,"shape") and len(l.shape)>1: l=l.iloc[:,0]
    v=hist["Volume"]
    if hasattr(v,"shape") and len(v.shape)>1: v=v.iloc[:,0]
    ca=c.values.astype(float)
    if len(ca)<60: return None
    p=ca[-1]
    if p<=0: return None

    bh=bmc.loc[:dt]
    ba=bh.values.astype(float) if not (hasattr(bh,"shape") and len(bh.shape)>1) else bh.iloc[:,0].values.astype(float)
    bm20=(ba[-1]/ba[-20]-1) if len(ba)>=20 else 0.0
    bm60=(ba[-1]/ba[-60]-1) if len(ba)>=60 else 0.0
    mom20=(p/ca[-20]-1) if len(ca)>=20 else 0.0
    mom60=(p/ca[-60]-1) if len(ca)>=60 else 0.0
    rs20=mom20-bm20; rs60=mom60-bm60

    ha=h.values[-14:].astype(float); la=l.values[-14:].astype(float); cp=ca[-15:-1]
    if len(ha)==len(cp):
        tr=np.maximum.reduce([ha-la,np.abs(ha-cp),np.abs(la-cp)]); atr=float(np.mean(tr))
    else:
        atr=p*0.025
    if atr<=0: atr=p*0.025

    rets20=np.diff(ca[-21:])/ca[-21:-1] if len(ca)>=21 else np.array([0.0])
    vol20=float(np.std(rets20)) if len(rets20)>1 else 0.01
    vol_adj=mom20/vol20 if vol20>1e-8 else 0.0

    r2v=_r2(ca[-60:])

    sma20=float(np.mean(ca[-20:])) if len(ca)>=20 else 0.0
    sma50=float(np.mean(ca[-50:])) if len(ca)>=50 else 0.0
    sec_rk=sec.get(t)

    # Hibrit Filtre: Momentum VEYA Toparlanma modeli
    in_top_sector = TICKER_SEC.get(t,"?") in sec.top_sectors(3)
    is_def = t in DEF_TICKERS

    if regime=="BULL":
        # Saf momentum: SMA altinda ama sektor lideri ise al (erken giris)
        # Normal: p>sma20 ve rs20>0
        ok_momentum = (p > sma20 * 0.98 and rs20 > 0.0)
        ok_early    = (in_top_sector and rs60 > 0.02 and mom20 > -0.05)  # toparlanma
        if not (ok_momentum or ok_early): return None
    elif regime=="NEUTRAL":
        ok = (p > sma20 * 0.95 and rs60 > -0.02) or (in_top_sector and rs20 > -0.03)
        if not ok: return None
    else:  # BEAR
        if not (is_def or (in_top_sector and rs20 > -0.04)): return None

    fv = {"mom_20d":float(mom20),"mom_60d":float(mom60),"rs_20d":float(rs20),"rs_60d":float(rs60),
          "vol_adj":float(np.clip(vol_adj,-5,5)),"r2":float(r2v),"sec_rank":float(sec_rk)}
    sc = adaptor.score(fv)
    return sc, p, atr, fv

def run_v4() -> None:
    START="2016-01-01"; END="2026-08-29"; INIT=100_000.0
    COMM=0.0015; SLIP=0.0010; COST1W=COMM+SLIP; ATR=4.0; TIME_STP=40
    MAX_SEC_WEIGHT=0.40  # Tek sektorde max %40

    logger.info("="*80)
    logger.info(f"[1] BIST VERISI INDIRILIYOR ({START} -> {END})")
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
        except: continue
    logger.info(f"  [OK] {len(sd)} hisse hazir ({len(UNIVERSE)} istendi).\n")

    logger.info("="*80)
    logger.info("[2] HIBRIT v4.0 - ADAPTIF SEKTOR ROTASYON + VOL OLCEKLEME")
    logger.info("="*80)
    logger.info(f"  Baslangic: {INIT:,.0f} TL  |  ATR:{ATR}x  |  Maliyet:%{COST1W*100:.2f}")
    logger.info(f"  Sektor limit: max %{MAX_SEC_WEIGHT*100:.0f} tek sektor")
    logger.info(f"  Rebalance: HAFTALIK  |  Adaptasyon: Her ceyrek")
    logger.info("-"*80)

    bmc=bm_df["Close"]
    if hasattr(bmc,"shape") and len(bmc.shape)>1: bmc=bmc.iloc[:,0]
    s50=bmc.rolling(50).mean(); s200=bmc.rolling(200).mean()
    dates=list(bm_df.index)[200:]
    cap=INIT; pos:dict[str,dict]={}; tlog:list[dict]=[]
    eq_curve:list[float]=[]
    yearly:dict[int,dict]={}
    cy=dates[0].year; yc=cap; yb=_f(bmc.loc[dates[0]])
    last_rb_week=-1; last_adapt=0
    last_sec_week=-1; sec_t=SectorTracker(); adapt=Adaptor()
    rcnt:dict[str,int]={"BULL":0,"NEUTRAL":0,"BEAR":0}

    for di,dt in enumerate(dates):
        if dt.year!=cy:
            pv=cap+sum(p["s"]*p["cp"] for p in pos.values())
            bn=_f(bmc.loc[dt])
            yearly[cy]={"p":(pv-yc)/yc*100,"b":(bn-yb)/yb*100,"eq":pv}
            cy=dt.year; yc=pv; yb=bn

        regime=reg(bmc,dt,s50,s200); rcnt[regime]+=1
        iso_w=dt.isocalendar()[1]
        if iso_w!=last_sec_week:
            last_sec_week=iso_w; sec_t.update(sd,bmc,dt)

        ts,ir=vol_slots(bmc,dt)
        if regime=="BEAR": ts=min(ts,3); ir=min(ir,0.60)

        # Pozisyon guncelle
        cl=[]
        for t,p in list(pos.items()):
            df=sd.get(t)
            if df is None or dt not in df.index: continue
            bar=df.loc[dt]
            ph=_f(bar["High"]); pl=_f(bar["Low"]); pc=_f(bar["Close"]); po=_f(bar["Open"])
            p["cp"]=pc
            if ph>p["pk"]:
                p["pk"]=ph; ns=p["pk"]-ATR*p["atr"]
                if ns>p["sl"]: p["sl"]=ns
            hd=(dt-p["ed"]).days
            exit,reason,ep=False,"",pc
            if pl<=p["sl"]: exit=True; ep=min(po,p["sl"]); reason="TRAIL" if ep>p["ep"] else "STOP"
            elif hd>TIME_STP and pc<p["ep"]*0.98: exit=True; reason="TIME"
            if exit:
                proc=p["s"]*ep*(1-SLIP)*(1-COMM); cost=p["s"]*p["ep"]*(1+COST1W)
                pnl=proc-cost; pnl_p=pnl/cost*100; cap+=proc
                adapt.rec(p["fv"],pnl_p)
                tlog.append({"t":t,"pnl":pnl,"pp":pnl_p,"r":reason,"h":hd,"rg":regime}); cl.append(t)
        for t in cl: pos.pop(t,None)

        if di-last_adapt>=63: adapt.upd(); last_adapt=di

        # HAFTALIK dengeleme
        if iso_w!=last_rb_week:
            last_rb_week=iso_w
            slots=ts-len(pos)
            if slots>0:
                cands:list[tuple[float,str,float,float,dict]]=[]
                for t in sd:
                    if t in pos: continue
                    r=score_tick(t,sd,dt,bmc,sec_t,regime,adapt)
                    if r: cands.append((r[0],t,r[1],r[2],r[3]))
                cands.sort(reverse=True,key=lambda x:x[0])

                pv=cap+sum(p["s"]*p["cp"] for p in pos.values())
                inv=pv*ir

                # Sektor konsantrasyon kontrolu
                sec_alloc:dict[str,float]={s:0.0 for s in SECTORS}
                for t,p in pos.items():
                    sec_alloc[TICKER_SEC.get(t,"diger")]+=p["s"]*p["cp"]/pv

                for sc,t,ps,atr_v,fv in cands[:slots*2]:  # 2x fazla incelensin, sektör limiti uygulansin
                    if len(pos)>=ts: break
                    sec=TICKER_SEC.get(t,"diger")
                    if sec_alloc.get(sec,0)+1/ts>MAX_SEC_WEIGHT: continue  # Sektör limit
                    alloc=min(cap*0.93,inv/ts)
                    if alloc<2000: continue
                    ep=ps*(1+SLIP); cps=ep*(1+COMM); shs=int(alloc/cps)
                    if shs<=0: continue
                    out=shs*cps
                    if out>cap: continue
                    cap-=out; sec_alloc[sec]=sec_alloc.get(sec,0)+out/pv
                    pos[t]={"s":shs,"ep":ep,"cp":ep,"pk":ep,"sl":ep-ATR*atr_v,"atr":atr_v,"ed":dt,"fv":fv}

        eq=cap+sum(p["s"]*p["cp"] for p in pos.values()); eq_curve.append(eq)

    fe=cap+sum(p["s"]*p["cp"] for p in pos.values())
    if cy not in yearly:
        bf=_f(bmc.iloc[-1]); yearly[cy]={"p":(fe-yc)/yc*100,"b":(bf-yb)/yb*100,"eq":fe}

    tot_ret=(fe-INIT)/INIT*100
    bi=_f(bmc.loc[dates[0]]); bf=_f(bmc.loc[dates[-1]]); bm_ret=(bf-bi)/bi*100
    ea=np.array(eq_curve); dr=np.diff(ea)/ea[:-1]
    sh=float((dr.mean()/dr.std())*np.sqrt(252)) if dr.std()>0 else 0.0
    pk=np.maximum.accumulate(ea); dd=(ea-pk)/pk; mdd=float(dd.min()*100)
    ny=len(ea)/252; cagr=(fe/INIT)**(1/ny)-1 if ny>0 else 0; bm_cagr=(bf/bi)**(1/ny)-1 if ny>0 else 0
    wins=[x for x in tlog if x["pnl"]>0]; loss=[x for x in tlog if x["pnl"]<=0]
    wr=len(wins)/len(tlog)*100 if tlog else 0
    ls=abs(sum(x["pnl"] for x in loss)); pf=sum(x["pnl"] for x in wins)/ls if ls>0 else 999
    td=sum(rcnt.values())

    S="="*88
    logger.info(f"\n{S}")
    logger.info("  HIBRIT ADAPTIF v4.0 SONUC KARTI  (2016-2026)")
    logger.info(S)
    logger.info(f"  {'Metrik':<35} {'v4 Strateji':>14} {'BIST-100':>14}")
    logger.info("-"*65)
    logger.info(f"  {'10Y Toplam Getiri':<35} {tot_ret:>13.1f}% {bm_ret:>13.1f}%")
    logger.info(f"  {'Yillik CAGR':<35} {cagr*100:>13.1f}% {bm_cagr*100:>13.1f}%")
    logger.info(f"  {'Sharpe Orani':<35} {sh:>14.2f} {'---':>14}")
    logger.info(f"  {'Max Drawdown':<35} {mdd:>13.2f}% {'---':>14}")
    logger.info(f"  {'Kar Faktoru':<35} {pf:>14.2f} {'---':>14}")
    logger.info(f"  {'Kazanma Orani':<35} {wr:>13.1f}% {'---':>14}")
    logger.info(f"  {'Toplam Islem':<35} {len(tlog):>14,}")
    logger.info(f"  {'Adaptasyon Sayisi':<35} {adapt.cnt:>14}")
    logger.info(f"  {'Bitis Sermayesi':<35} {fe:>13,.0f}TL")
    logger.info(f"  {'Alfa (Excess)':<35} {tot_ret-bm_ret:>13.1f}%")
    logger.info(S)
    logger.info("\n  REJIM DAGILIMI:")
    for rg,cnt in rcnt.items():
        logger.info(f"    {rg:<8}: {cnt:,} gun ({cnt/td*100:.0f}%)")
    logger.info("\n  SON FAKTOR AGIRLIKLARI:")
    for f,w in sorted(adapt.w.items(),key=lambda x:x[1],reverse=True):
        bar="#"*int(w*50)
        logger.info(f"    {f:<18}: {w:.3f}  {bar}")
    logger.info(f"\n  YIL YIL KARSILASTIRMA:")
    logger.info(f"  {'YIL':<6}|{'PORTFOY':>10}|{'BIST':>10}|{'ALFA':>10}|{'SONUC':>10}")
    logger.info("-"*52); bt=0
    for yr in sorted(yearly):
        p=yearly[yr]["p"]; b=yearly[yr]["b"]; a=p-b
        if a>0: bt+=1
        s="[ALFA]" if a>0 else "[KAYIP]"
        logger.info(f"  {yr:<6}|{p:>+9.1f}%|{b:>+9.1f}%|{a:>+9.1f}%|{s:>10}")
    logger.info("-"*52)
    logger.info(f"  Toplam: {bt}/{len(yearly)} yil BIST'i gecti")
    logger.info(S)
    logger.info("  [OK] POINT-IN-TIME: Gelecek sizintisi YOK")
    logger.info(f"  [OK] Walk-Forward Adaptasyon: {adapt.cnt} kez")
    logger.info(f"  [OK] Sektor limit: max %{MAX_SEC_WEIGHT*100:.0f} tek sektor")
    logger.info(S)
    if tlog:
        by={};
        for x in tlog: by[x["t"]]=by.get(x["t"],0)+x["pnl"]
        b5=sorted(by.items(),key=lambda x:x[1],reverse=True)[:5]
        w5=sorted(by.items(),key=lambda x:x[1])[:5]
        logger.info("\n  [TOP5] En Karli:"); [logger.info(f"    {t:<15} +{p:,.0f} TL") for t,p in b5]
        logger.info("\n  [BOT5] En Zararli:"); [logger.info(f"    {t:<15} {p:,.0f} TL") for t,p in w5]
    logger.info("\n  SEKTOR PERFORMANSI (Son):")
    for sc,rk in sorted(sec_t.sec_rank.items(),key=lambda x:x[1],reverse=True):
        bar="#"*int(rk*25)
        logger.info(f"    {sc:<15}: {rk:.2f}  {bar}")
    logger.info(S)

if __name__=="__main__":
    run_v4()
