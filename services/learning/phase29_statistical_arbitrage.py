"""FAZ 29 v2 - Duzeltilmis PnL hesabi (getiri bazli)"""
import sys, numpy as np, pandas as pd, warnings
from scipy import stats
warnings.filterwarnings("ignore")
sys.path.insert(0, ".")

HOLDOUT = "2025-10-31"
Z_ENTRY = 2.0
Z_EXIT  = 0.5
TC      = 0.002

logger.info("="*65)
logger.info("FAZ 29 v2 - PAIRS TRADING (Duzeltilmis)")
logger.info("="*65)

def adf_pvalue(series):
    s = np.array(series.dropna()); n = len(s)
    if n < 20: return 1.0
    dy = np.diff(s); y_lag = s[:-1]
    slope, intercept, r, p, se = stats.linregress(y_lag, dy)
    t_stat = slope / (se + 1e-12)
    if t_stat < -3.43: return 0.01
    elif t_stat < -2.86: return 0.05
    elif t_stat < -2.57: return 0.10
    elif t_stat < -2.0:  return 0.20
    else: return 0.50

def half_life(spread):
    lag = spread.shift(1).dropna(); diff = spread.diff().dropna()
    if len(diff) < 20: return np.inf
    slope, *_ = stats.linregress(lag, diff)
    return -np.log(2) / slope if slope < 0 else np.inf

logger.info("\n[1/4] Veri yukleniyor...")
import yfinance as yf
TICKERS = ["GARAN","AKBNK","ISCTR","YKBNK","HALKB","VAKBN",
           "KCHOL","SAHOL","GLYHO","TUPRS","AKSEN","ENJSA",
           "BIMAS","MGROS","SOKM","TCELL","TTKOM",
           "TOASO","FROTO","TTRAK","EREGL","KRDMD","OYAKC",
           "THYAO","ASELS","SISE","EKGYO","ARCLK"]
raw = yf.download([f"{t}.IS" for t in TICKERS], start="2020-01-01", end=HOLDOUT,
                  interval="1d", auto_adjust=True, progress=False, threads=True)
prices = raw["Close"].copy()
prices.columns = [c.replace(".IS","") for c in prices.columns]
prices = prices.dropna(how="all")
valid = [c for c in prices.columns if prices[c].notna().sum() >= 500]
prices = prices[valid].ffill()
returns = prices.pct_change()
logger.info(f"   {len(valid)} hisse, {prices.index[0].date()} -> {prices.index[-1].date()}")

logger.info("\n[2/4] Koentegrasyon taramasi...")
PAIRS = [
    ("GARAN","AKBNK","Banka"), ("GARAN","ISCTR","Banka"), ("GARAN","YKBNK","Banka"),
    ("AKBNK","ISCTR","Banka"), ("AKBNK","YKBNK","Banka"), ("ISCTR","YKBNK","Banka"),
    ("HALKB","VAKBN","Kamu Banka"), ("KCHOL","SAHOL","Holding"), ("KCHOL","GLYHO","Holding"),
    ("TOASO","FROTO","Otomotiv"), ("TOASO","TTRAK","Otomotiv"), ("FROTO","TTRAK","Otomotiv"),
    ("EREGL","KRDMD","Demir"), ("EREGL","OYAKC","Demir"), ("KRDMD","OYAKC","Demir"),
    ("TCELL","TTKOM","Telekom"), ("BIMAS","MGROS","Perakende"), ("BIMAS","SOKM","Perakende"),
    ("TUPRS","AKSEN","Enerji"), ("TUPRS","ENJSA","Enerji"), ("AKSEN","ENJSA","Enerji"),
]

prices_train = prices[prices.index <= "2024-12-31"]
found = []
for t1, t2, sec in PAIRS:
    if t1 not in prices_train.columns or t2 not in prices_train.columns: continue
    s1 = prices_train[t1].dropna(); s2 = prices_train[t2].dropna()
    idx = s1.index.intersection(s2.index)
    if len(idx) < 300: continue
    s1v, s2v = s1[idx].values, s2[idx].values
    slope, intercept, *_ = stats.linregress(s2v, s1v)
    spread = pd.Series(s1v - slope*s2v - intercept, index=idx)
    pv = adf_pvalue(spread)
    if pv <= 0.10:
        hl = half_life(spread)
        if 5 <= hl <= 60:
            found.append({"t1":t1,"t2":t2,"sec":sec,"pv":pv,"hr":round(slope,4),"hl":round(hl,1)})
            logger.info(f"   ✓ {t1}/{t2} [{sec}] p={pv:.2f} hedge={slope:.3f} yari-omur={hl:.0f}gun")

logger.info(f"   Koentegre cift: {len(found)}")

logger.info("\n[3/4] Backtest (getiri bazli PnL)...")

def backtest(t1, t2, hr, pdata, rdata, lookback=60):
    """
    DOGRU YONTEM: Gunluk getiri bazli PnL.
    Long spread = long t1 / short t2
      gunluk PnL = r1 - hr*r2 (hedge edilen portfoy getirisi)
    Short spread = short t1 / long t2
      gunluk PnL = -(r1 - hr*r2)
    """
    if t1 not in pdata.columns or t2 not in pdata.columns: return None
    p1 = pdata[t1].dropna(); p2 = pdata[t2].dropna()
    r1 = rdata[t1]; r2 = rdata[t2]
    idx = p1.index.intersection(p2.index)
    if len(idx) < lookback+10: return None
    p1, p2 = p1[idx].values, p2[idx].values
    r1v = r1.reindex(idx).fillna(0).values
    r2v = r2.reindex(idx).fillna(0).values

    pos = 0  # 1=long spread, -1=short spread
    pnls = []
    n_trades = 0
    for i in range(lookback, len(p1)):
        # Z-score spread seviyesinden hesapla
        sp_win = p1[i-lookback:i] - hr * p2[i-lookback:i]
        mu, sig = sp_win.mean(), sp_win.std()
        if sig < 1e-9: pnls.append(0.0); continue
        sp_now = p1[i] - hr * p2[i]
        z = (sp_now - mu) / sig

        # PnL: getiri bazli (boluyor sifira degil!)
        hedge_ret = r1v[i] - hr * r2v[i]
        d = 0.0
        if pos == 1:    d = hedge_ret
        elif pos == -1: d = -hedge_ret
        # Kapanis
        if pos != 0 and abs(z) < Z_EXIT:
            d -= TC * 2  # iki tarafli islem maliyeti
            pos = 0
        # Acilis
        if pos == 0:
            if z > Z_ENTRY:
                pos = -1; d -= TC * 2; n_trades += 1
            elif z < -Z_ENTRY:
                pos = 1; d -= TC * 2; n_trades += 1
        pnls.append(d)

    ps = pd.Series(pnls)
    if ps.abs().sum() < 1e-6: return None
    cum = (1+ps).cumprod()
    ny  = len(ps)/252
    cagr   = (cum.iloc[-1])**(1/ny) - 1 if (ny > 0 and cum.iloc[-1] > 0) else -1
    sharpe = (ps.mean()*252) / (ps.std()*np.sqrt(252) + 1e-9)
    dd     = (cum/cum.cummax() - 1).min()
    win_r  = (ps[ps!=0]>0).mean() if (ps!=0).any() else 0
    return {"cagr":round(cagr*100,1), "sharpe":round(sharpe,2),
            "dd":round(dd*100,1), "n":n_trades, "wr":round(win_r*100,1)}

# B&H benchmark
bh_tks = [t for t in ["GARAN","AKBNK","THYAO","KCHOL","ISCTR"] if t in returns.columns]
prices_full = prices[prices.index >= "2021-01-01"]
returns_full = returns[returns.index >= "2021-01-01"]
bh = returns_full[bh_tks].mean(axis=1)
bh_cum = (1+bh).cumprod(); bh_ny = len(bh)/252
bh_cagr = (bh_cum.iloc[-1])**(1/bh_ny) - 1
logger.info(f"   BIST Sepet B&H CAGR: %{bh_cagr*100:.1f}")

prices_oos  = prices[(prices.index >= "2025-01-01") & (prices.index <= HOLDOUT)]
returns_oos = returns[(returns.index >= "2025-01-01") & (returns.index <= HOLDOUT)]

results = []
for p in found:
    ro = backtest(p["t1"],p["t2"],p["hr"],prices_oos,returns_oos)
    rf = backtest(p["t1"],p["t2"],p["hr"],prices_full,returns_full)
    if ro and rf:
        results.append({"pair":f"{p['t1']}/{p['t2']}","sec":p["sec"],
                        "oos_cagr":ro["cagr"],"oos_sh":ro["sharpe"],"oos_dd":ro["dd"],"oos_n":ro["n"],"oos_wr":ro["wr"],
                        "full_cagr":rf["cagr"],"full_sh":rf["sharpe"],"full_dd":rf["dd"]})

results.sort(key=lambda x: x["oos_sh"], reverse=True)

logger.info(f"\n   {'Cift':<16} {'OOS CAGR':>9} {'OOS Sh':>7} {'OOS DD':>8} {'Full%':>7} {'Full Sh':>8} {'Islem':>6} {'WinR':>6}")
logger.info(f"   {'-'*72}")
for r in results:
    tag = " ***" if r["oos_cagr"]>80 else (" **" if r["oos_cagr"]>30 else (" *" if r["oos_cagr"]>0 else ""))
    logger.info(f"   {r['pair']:<16} {r['oos_cagr']:>8}% {r['oos_sh']:>6} {r['oos_dd']:>7}% {r['full_cagr']:>6}% {r['full_sh']:>7} {r['oos_n']:>6} %{r['oos_wr']:>4}{tag}")

# Portfoy kombinasyonu
logger.info("\n[4/4] PORTFOY KOMBINASYONU...")
top = [r for r in results if r["full_sh"] > 0][:5]
port_daily = []
for r in top:
    t1, t2 = r["pair"].split("/")
    hr = next(p["hr"] for p in found if p["t1"]==t1 and p["t2"]==t2)
    if t1 not in prices_full.columns or t2 not in prices_full.columns: continue
    p1 = prices_full[t1].dropna(); p2 = prices_full[t2].dropna()
    r1v = returns_full[t1]; r2v = returns_full[t2]
    idx = p1.index.intersection(p2.index)
    p1v, p2v = p1[idx].values, p2[idx].values
    r1a = r1v.reindex(idx).fillna(0).values; r2a = r2v.reindex(idx).fillna(0).values
    lookback=60; pos=0; pnls=[]
    for i in range(lookback, len(p1v)):
        sp_w = p1v[i-lookback:i] - hr*p2v[i-lookback:i]
        mu,sig = sp_w.mean(), sp_w.std()
        if sig < 1e-9: pnls.append(0.0); continue
        z = (p1v[i]-hr*p2v[i]-mu)/sig
        hr_ret = r1a[i] - hr*r2a[i]
        d = 0.0
        if pos==1: d=hr_ret
        elif pos==-1: d=-hr_ret
        if pos!=0 and abs(z)<Z_EXIT: d-=TC*2; pos=0
        if pos==0:
            if z>Z_ENTRY: pos=-1; d-=TC*2
            elif z<-Z_ENTRY: pos=1; d-=TC*2
        pnls.append(d)
    if pnls: port_daily.append(pd.Series(pnls, index=p1[idx].index[lookback:]))

if port_daily and top:
    port = pd.concat(port_daily,axis=1).mean(axis=1).dropna()
    cum  = (1+port).cumprod(); ny = len(port)/252
    p_cagr   = (cum.iloc[-1])**(1/ny)-1 if cum.iloc[-1]>0 else -1
    p_sharpe = (port.mean()*252)/(port.std()*np.sqrt(252)+1e-9)
    p_dd     = (cum/cum.cummax()-1).min()
    logger.info(f"\n   ╔═══════════════════════════════════════╗")
    logger.info(f"   ║  PORTFOY (Pozitif Sharpe'li ciftler) ║")
    logger.info(f"   ║  CAGR:      %{p_cagr*100:>6.1f}                 ║")
    logger.info(f"   ║  Sharpe:     {p_sharpe:>6.2f}                 ║")
    logger.info(f"   ║  Max DD:    %{p_dd*100:>6.1f}                 ║")
    logger.info(f"   ║  B&H CAGR:  %{bh_cagr*100:>6.1f}                 ║")
    logger.info(f"   ║  Alpha:     %{(p_cagr-bh_cagr)*100:>+6.1f}                 ║")
    logger.info(f"   ╚═══════════════════════════════════════╝")
else:
    logger.info("   Pozitif Sharpe'li cift yok - portfoy olusturulamadi")

logger.info("\n"+"="*65)
pos_oos = [r for r in results if r["oos_cagr"] > 0]
strong  = [r for r in results if r["oos_cagr"] > 50]
if strong:
    logger.info(f"KARAR: GUCLU ALPHA ({len(strong)} cift >%50 OOS)")
elif pos_oos:
    logger.info(f"KARAR: ORTA ALPHA ({len(pos_oos)} cift pozitif OOS)")
    logger.info(f"       B&H: %{bh_cagr*100:.1f} - hedef: %100")
else:
    logger.info("KARAR: REJECT - Pairs trading bu formda BIST'te calismiyor")
    logger.info("       Neden: Yuksek enflasyon doneminde koentegrasyon bozuluyor")
    logger.info("       Alternatif: Sektör rotasyonu veya momentum")
for r in results[:3]:
    logger.info(f"  {r['pair']}: OOS %{r['oos_cagr']} CAGR / Sharpe {r['oos_sh']}")
logger.info("="*65)
