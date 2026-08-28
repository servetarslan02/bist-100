"""
import structlog
logger = structlog.get_logger()

ALPHA HUNT - Tum stratejileri dene, basarili olana kadar dur.
Holdout: 2025-10-31 sonrasi DOKUNULMUYOR.
"""
import sys, numpy as np, pandas as pd, warnings, time
from scipy import stats
warnings.filterwarnings("ignore")

HOLDOUT = "2025-10-31"
BH_CAGR = 76.4  # referans

logger.info("="*70)
logger.info("ALPHA HUNT - Basarili strateji bulunana kadar dur")
logger.info(f"Hedef: OOS CAGR > %100, Sharpe > 1.0")
logger.info(f"B&H referans: %{BH_CAGR}")
logger.info("="*70)

# ── VERİ ────────────────────────────────────────────────────────────
import yfinance as yf

# Tum BIST hisseleri - kucuk/orta cap dahil
ALL_TICKERS = [
    # BIST100
    "GARAN","AKBNK","ISCTR","YKBNK","HALKB","VAKBN","SKBNK","ALBRK",
    "KCHOL","SAHOL","GLYHO","DOHOL","NTHOL",
    "TUPRS","AKSEN","ENJSA","ZOREN","ODAS","IZENR",
    "BIMAS","MGROS","SOKM",
    "TCELL","TTKOM",
    "TOASO","FROTO","TTRAK",
    "EREGL","KRDMD","OYAKC",
    "SISE","ARCLK","EKGYO","THYAO","ASELS",
    "PGSUS","TAVHL","ESAS","LOGO","CCOLA",
    "KOZAL","KOZAA","MPARK","CIMSA","AKCNS",
    "VESTL","VESBE","BRSAN","BURCE","ISDMR",
    # Ek orta cap
    "TKFEN","ENKAI","PETKM","AGHOL","AEFES",
    "TSKB","KLNMA","TTGYO","ISGYO","ALGYO",
    "ULKER","BANVT","ALYAG","KNFRT","BIZIM",
    "DOHOL","IHLAS","MAVI","ENJSA","PKART",
    "BRISA","JANTS","GUBRF","AFYON","ADEL",
    "DENGE","MERIT","RNPOL","FENER","GSRAY",
]
ALL_TICKERS = list(dict.fromkeys(ALL_TICKERS))  # deduplicate

logger.info(f"\nVeri indiriliyor ({len(ALL_TICKERS)} hisse)...")
t0 = time.time()
raw = yf.download(
    [f"{t}.IS" for t in ALL_TICKERS],
    start="2019-01-01", end=HOLDOUT,
    interval="1d", auto_adjust=True, progress=False, threads=True
)
prices = raw["Close"].copy()
prices.columns = [c.replace(".IS","") for c in prices.columns]
prices = prices.sort_index().ffill().dropna(how="all")
valid = [c for c in prices.columns if prices[c].notna().sum() >= 400]
prices = prices[valid]
returns = prices.pct_change()
logger.info(f"   {len(valid)} hisse, {prices.index[0].date()} -> {prices.index[-1].date()} ({time.time()-t0:.1f}s)")

# Donemler
full_start = "2021-01-01"
oos_start  = "2025-01-01"
pf = prices[(prices.index >= full_start) & (prices.index <= HOLDOUT)]
rf = returns[(returns.index >= full_start) & (returns.index <= HOLDOUT)]
po = prices[(prices.index >= oos_start) & (prices.index <= HOLDOUT)]
ro = returns[(returns.index >= oos_start) & (returns.index <= HOLDOUT)]

def cagr(ret_series):
    c = (1+ret_series).cumprod()
    if c.iloc[-1] <= 0: return -1.0
    ny = len(ret_series)/252
    return (c.iloc[-1])**(1/ny) - 1

def sharpe(ret_series):
    return (ret_series.mean()*252) / (ret_series.std()*np.sqrt(252) + 1e-9)

def maxdd(ret_series):
    c = (1+ret_series).cumprod()
    return (c/c.cummax() - 1).min()

results = []

def evaluate(name, daily_ret_full, daily_ret_oos):
    c_full = cagr(daily_ret_full)*100
    c_oos  = cagr(daily_ret_oos)*100
    s_full = sharpe(daily_ret_full)
    s_oos  = sharpe(daily_ret_oos)
    dd_oos = maxdd(daily_ret_oos)*100
    tag = ""
    if c_oos > 100 and s_oos > 1.0:   tag = " *** HEDEF TUTTU ***"
    elif c_oos > 50 and s_oos > 0.5:  tag = " ** UMUT VERICI"
    elif c_oos > 0:                    tag = " * POZITIF"
    logger.info(f"   {name:<40} Full:%{c_full:>6.1f} Sh:{s_full:>5.2f} | OOS:%{c_oos:>7.1f} Sh:{s_oos:>5.2f} DD:%{dd_oos:>6.1f}{tag}")
    results.append({"name":name,"full_cagr":c_full,"full_sh":s_full,"oos_cagr":c_oos,"oos_sh":s_oos,"oos_dd":dd_oos,
                    "daily_oos":daily_ret_oos})
    return c_oos, s_oos

# ════════════════════════════════════════════════════════════════════
# STRATEJİ 1: BUY & HOLD EŞİT AĞIRLIK (referans)
# ════════════════════════════════════════════════════════════════════
logger.info("\n─── S1: B&H Esit Agirlik ───")
s1_full = rf.mean(axis=1)
s1_oos  = ro.mean(axis=1)
evaluate("B&H Esit Agirlik (Tum BIST)", s1_full, s1_oos)

# ════════════════════════════════════════════════════════════════════
# STRATEJİ 2: 12-1 MOMENTUM (klasik)
# ════════════════════════════════════════════════════════════════════
logger.info("\n─── S2: 12-1 Momentum ───")
def momentum_strategy(prices, returns, lookback=252, skip=21, top_n=10, rebal="ME"):
    monthly_idx = prices.resample(rebal).last().index
    port_rets = []
    for i in range(1, len(monthly_idx)):
        dt = monthly_idx[i-1]
        dt_next = monthly_idx[i]
        # Momentum hesapla
        start = dt - pd.Timedelta(days=lookback+10)
        end_skip = dt - pd.Timedelta(days=skip)
        if start < prices.index[0] or end_skip < prices.index[0]:
            continue
        p_slice = prices.loc[start:end_skip]
        if len(p_slice) < lookback//2:
            continue
        mom = {}
        for t in prices.columns:
            s = p_slice[t].dropna()
            if len(s) < 60: continue
            mom[t] = (s.iloc[-1]/s.iloc[0]) - 1
        if len(mom) < top_n: continue
        top = sorted(mom, key=lambda x: mom[x], reverse=True)[:top_n]
        # Sonraki ay getirisi
        r_slice = returns.loc[dt:dt_next][top]
        if r_slice.empty: continue
        port_rets.append(r_slice.mean(axis=1))
    if not port_rets: return pd.Series(dtype=float)
    return pd.concat(port_rets).sort_index()

for top_n in [5, 10, 20]:
    for lb in [126, 252]:
        s = momentum_strategy(pf, rf, lookback=lb, skip=21, top_n=top_n)
        s_oos = momentum_strategy(po, ro, lookback=lb, skip=21, top_n=top_n)
        if len(s) > 20 and len(s_oos) > 5:
            evaluate(f"Momentum lb={lb} top{top_n}", s, s_oos)

# ════════════════════════════════════════════════════════════════════
# STRATEJİ 3: 52 HAFTA YÜKSEĞİ KIRISI (Breakout)
# ════════════════════════════════════════════════════════════════════
logger.info("\n─── S3: 52-Hafta Yuksegi Kirisi ───")
def breakout_strategy(prices, returns, window=252, top_n=10):
    monthly_idx = prices.resample("ME").last().index
    port_rets = []
    for i in range(1, len(monthly_idx)):
        dt = monthly_idx[i-1]; dt_next = monthly_idx[i]
        if dt - pd.Timedelta(days=window) < prices.index[0]: continue
        p_now = prices.loc[:dt]
        if len(p_now) < window//2: continue
        scores = {}
        for t in prices.columns:
            s = p_now[t].dropna()
            if len(s) < window//2: continue
            high52 = s.iloc[-window:].max()
            last   = s.iloc[-1]
            if high52 > 0:
                scores[t] = last / high52  # 1.0 = tam 52h yuksegi
        if len(scores) < top_n: continue
        # En yüksege en yakin hisseler
        top = sorted(scores, key=lambda x: scores[x], reverse=True)[:top_n]
        r_slice = returns.loc[dt:dt_next][top]
        if r_slice.empty: continue
        port_rets.append(r_slice.mean(axis=1))
    if not port_rets: return pd.Series(dtype=float)
    return pd.concat(port_rets).sort_index()

for top_n in [5, 10]:
    s = breakout_strategy(pf, rf, top_n=top_n)
    s_oos = breakout_strategy(po, ro, top_n=top_n)
    if len(s) > 20 and len(s_oos) > 5:
        evaluate(f"52H Yuksek Kirisi top{top_n}", s, s_oos)

# ════════════════════════════════════════════════════════════════════
# STRATEJİ 4: KISA DONEM MOMENTUM (1-3 ay)
# ════════════════════════════════════════════════════════════════════
logger.info("\n─── S4: Kisa Donem Momentum ───")
for lb in [21, 42, 63]:
    s = momentum_strategy(pf, rf, lookback=lb, skip=0, top_n=10)
    s_oos = momentum_strategy(po, ro, lookback=lb, skip=0, top_n=10)
    if len(s) > 20 and len(s_oos) > 5:
        evaluate(f"Kisa Mom lb={lb}d top10", s, s_oos)

# ════════════════════════════════════════════════════════════════════
# STRATEJİ 5: VOLATILITE KIRISI (Vol Breakout)
# ════════════════════════════════════════════════════════════════════
logger.info("\n─── S5: Volatilite Kirisi ───")
def vol_breakout(prices, returns, vol_window=20, mom_window=5, top_n=10):
    monthly_idx = prices.resample("ME").last().index
    port_rets = []
    for i in range(1, len(monthly_idx)):
        dt = monthly_idx[i-1]; dt_next = monthly_idx[i]
        if dt - pd.Timedelta(days=vol_window*3) < prices.index[0]: continue
        scores = {}
        for t in prices.columns:
            r = returns.loc[:dt][t].dropna()
            if len(r) < vol_window*2: continue
            vol_recent = r.iloc[-vol_window:].std()
            vol_prior  = r.iloc[-vol_window*3:-vol_window].std()
            mom        = r.iloc[-mom_window:].mean()
            if vol_prior > 0 and vol_recent > vol_prior*1.5 and mom > 0:
                scores[t] = vol_recent / vol_prior
        if len(scores) < top_n: continue
        top = sorted(scores, key=lambda x: scores[x], reverse=True)[:top_n]
        r_slice = returns.loc[dt:dt_next][top]
        if r_slice.empty: continue
        port_rets.append(r_slice.mean(axis=1))
    if not port_rets: return pd.Series(dtype=float)
    return pd.concat(port_rets).sort_index()

s = vol_breakout(pf, rf)
s_oos = vol_breakout(po, ro)
if len(s) > 20 and len(s_oos) > 5:
    evaluate("Vol Kirisi (yukselen vol+mom)", s, s_oos)

# ════════════════════════════════════════════════════════════════════
# STRATEJİ 6: TREND FILTRELEMELI MOMENTUM
# ════════════════════════════════════════════════════════════════════
logger.info("\n─── S6: Trend Filtreli Momentum (200 SMA) ───")
def trend_filtered_momentum(prices, returns, top_n=10, lb=126):
    monthly_idx = prices.resample("ME").last().index
    port_rets = []
    for i in range(1, len(monthly_idx)):
        dt = monthly_idx[i-1]; dt_next = monthly_idx[i]
        scores = {}
        for t in prices.columns:
            p = prices.loc[:dt][t].dropna()
            if len(p) < 200: continue
            ma200 = p.iloc[-200:].mean()
            last  = p.iloc[-1]
            if last < ma200: continue  # Trend yukari degil, atla
            start_lb = dt - pd.Timedelta(days=lb+30)
            p_slice = p.loc[start_lb:]
            if len(p_slice) < lb//2: continue
            scores[t] = (p.iloc[-1] / p.iloc[-(lb+1)]) - 1 if len(p) > lb else None
        scores = {k:v for k,v in scores.items() if v is not None}
        if len(scores) < top_n: continue
        top = sorted(scores, key=lambda x: scores[x], reverse=True)[:top_n]
        r_slice = returns.loc[dt:dt_next][top]
        if r_slice.empty: continue
        port_rets.append(r_slice.mean(axis=1))
    if not port_rets: return pd.Series(dtype=float)
    return pd.concat(port_rets).sort_index()

for top_n in [5, 10]:
    s = trend_filtered_momentum(pf, rf, top_n=top_n)
    s_oos = trend_filtered_momentum(po, ro, top_n=top_n)
    if len(s) > 20 and len(s_oos) > 5:
        evaluate(f"Trend+Mom top{top_n}", s, s_oos)

# ════════════════════════════════════════════════════════════════════
# STRATEJİ 7: AYLIK GERI DONUS (Short-term Reversal)
# ════════════════════════════════════════════════════════════════════
logger.info("\n─── S7: Aylik Geri Donus ───")
def reversal_strategy(prices, returns, lb=21, top_n=10):
    monthly_idx = prices.resample("ME").last().index
    port_rets = []
    for i in range(1, len(monthly_idx)):
        dt = monthly_idx[i-1]; dt_next = monthly_idx[i]
        scores = {}
        for t in prices.columns:
            r = returns.loc[:dt][t].dropna()
            if len(r) < lb: continue
            scores[t] = r.iloc[-lb:].sum()
        if len(scores) < top_n: continue
        # En cok dusenler (reversal)
        bot = sorted(scores, key=lambda x: scores[x])[:top_n]
        r_slice = returns.loc[dt:dt_next][bot]
        if r_slice.empty: continue
        port_rets.append(r_slice.mean(axis=1))
    if not port_rets: return pd.Series(dtype=float)
    return pd.concat(port_rets).sort_index()

for lb in [21, 42]:
    s = reversal_strategy(pf, rf, lb=lb)
    s_oos = reversal_strategy(po, ro, lb=lb)
    if len(s) > 20 and len(s_oos) > 5:
        evaluate(f"Reversal lb={lb}d", s, s_oos)

# ════════════════════════════════════════════════════════════════════
# STRATEJİ 8: KONSANTRE MOMENTUM (TOP 3)
# ════════════════════════════════════════════════════════════════════
logger.info("\n─── S8: Konsantre Momentum (Top 3-5) ───")
for top_n in [3, 5]:
    for lb in [63, 126, 252]:
        s = momentum_strategy(pf, rf, lookback=lb, skip=0, top_n=top_n)
        s_oos = momentum_strategy(po, ro, lookback=lb, skip=0, top_n=top_n)
        if len(s) > 20 and len(s_oos) > 5:
            evaluate(f"Konsantre Mom lb={lb} top{top_n}", s, s_oos)

# ════════════════════════════════════════════════════════════════════
# SONUÇLAR
# ════════════════════════════════════════════════════════════════════
logger.info("\n" + "="*70)
logger.info("NIHAI SONUCLAR - OOS CAGR sirasina gore")
logger.info("="*70)
results.sort(key=lambda x: x["oos_cagr"], reverse=True)
logger.info(f"\n{'Strateji':<42} {'OOS CAGR':>9} {'OOS Sh':>8} {'OOS DD':>8} {'Full':>8}")
logger.info("-"*78)
for r in results[:20]:
    tag = "✓" if r["oos_cagr"] > 100 and r["oos_sh"] > 1.0 else ""
    logger.info(f"{r['name']:<42} {r['oos_cagr']:>8.1f}% {r['oos_sh']:>7.2f} {r['oos_dd']:>7.1f}% {r['full_cagr']:>7.1f}% {tag}")

winners = [r for r in results if r["oos_cagr"] > 100 and r["oos_sh"] > 1.0]
decent  = [r for r in results if r["oos_cagr"] > 50]
above_bh = [r for r in results if r["oos_cagr"] > BH_CAGR]

logger.info(f"\n> %100 OOS + Sharpe>1.0: {len(winners)} strateji")
logger.info(f"> %50 OOS:               {len(decent)} strateji")
logger.info(f"> B&H (%{BH_CAGR}):          {len(above_bh)} strateji")
if winners:
    best = winners[0]
    logger.info(f"\nEN IYI STRATEJI: {best['name']}")
    logger.info(f"  OOS CAGR: %{best['oos_cagr']:.1f} | Sharpe: {best['oos_sh']:.2f} | MaxDD: %{best['oos_dd']:.1f}")
    logger.info("  KARAR: PRODUCTION'A ALINABILIR -> FAZ 30")
elif above_bh:
    best = above_bh[0]
    logger.info(f"\nB&H'I GECEN: {best['name']}")
    logger.info(f"  OOS CAGR: %{best['oos_cagr']:.1f} | Hedef: %100")
    logger.info("  KARAR: OPTIMIZE ET")
else:
    logger.info("\nHICBIR STRATEJI B&H'i GECEMEDI")
    logger.info(f"  B&H CAGR: %{BH_CAGR} | Hedef: %100")
    logger.info("  KARAR: Daha agresif parametreler / farkli veri seti dene")
logger.info("="*70)

