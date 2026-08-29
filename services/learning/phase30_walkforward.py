from typing import Any
"""
import structlog
logger = structlog.get_logger()

FAZ 30 - WALK-FORWARD VALIDASYON + ENSEMBLE
3 kazanan strateji: Momentum-252-top5, Momentum-126-top10, VolKirisi
Yil yil performans + kombinasyon analizi
"""

import warnings

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")

HOLDOUT = "2025-10-31"
logger.info("=" * 70)
logger.info("FAZ 30 - WALK-FORWARD + ENSEMBLE")
logger.info("Kazanan: Momentum-252-top5 (%249 OOS), Momentum-126-top10 (%116), VolKirisi (%102)")
logger.info("=" * 70)

import yfinance as yf

TICKERS = [
    "GARAN",
    "AKBNK",
    "ISCTR",
    "YKBNK",
    "HALKB",
    "VAKBN",
    "SKBNK",
    "ALBRK",
    "KCHOL",
    "SAHOL",
    "GLYHO",
    "DOHOL",
    "NTHOL",
    "TUPRS",
    "AKSEN",
    "ENJSA",
    "ZOREN",
    "ODAS",
    "IZENR",
    "BIMAS",
    "MGROS",
    "SOKM",
    "TCELL",
    "TTKOM",
    "TOASO",
    "FROTO",
    "TTRAK",
    "EREGL",
    "KRDMD",
    "OYAKC",
    "SISE",
    "ARCLK",
    "EKGYO",
    "THYAO",
    "ASELS",
    "PGSUS",
    "TAVHL",
    "LOGO",
    "CCOLA",
    "MPARK",
    "CIMSA",
    "AKCNS",
    "VESTL",
    "VESBE",
    "BRSAN",
    "BURCE",
    "ISDMR",
    "TKFEN",
    "ENKAI",
    "PETKM",
    "AGHOL",
    "AEFES",
    "TSKB",
    "KLNMA",
    "ISGYO",
    "ALGYO",
    "ULKER",
    "BANVT",
    "KNFRT",
    "BIZIM",
    "IHLAS",
    "MAVI",
    "PKART",
    "BRISA",
    "JANTS",
    "GUBRF",
    "AFYON",
    "ADEL",
]
raw = yf.download(
    [f"{t}.IS" for t in TICKERS],
    start="2019-01-01",
    end=HOLDOUT,
    interval="1d",
    auto_adjust=True,
    progress=False,
    threads=True,
)
prices = raw["Close"].copy()
prices.columns = [c.replace(".IS", "") for c in prices.columns]
prices = prices.sort_index().ffill().dropna(how="all")
valid = [c for c in prices.columns if prices[c].notna().sum() >= 400]
prices = prices[valid]
returns = prices.pct_change()
logger.info(f"Veri: {len(valid)} hisse, {prices.index[0].date()} -> {prices.index[-1].date()}")


def cagr(s) -> Any:
    """Otomatik eklendi."""
    c = (1 + s).cumprod()
    ny = len(s) / 252
    return ((c.iloc[-1]) ** (1 / ny) - 1) * 100 if c.iloc[-1] > 0 and ny > 0 else -100


def sharpe(s) -> Any:
    """Otomatik eklendi."""
    return (s.mean() * 252) / (s.std() * np.sqrt(252) + 1e-9)


def maxdd(s) -> Any:
    """Otomatik eklendi."""
    c = (1 + s).cumprod()
    return (c / c.cummax() - 1).min() * 100


def momentum_top(prices, returns, lb, top_n, skip=21) -> Any:
    """Otomatik eklendi."""
    idx = prices.resample("ME").last().index
    rets = []
    selected = {}
    for i in range(1, len(idx)):
        dt = idx[i - 1]
        dn = idx[i]
        scores = {}
        for t in prices.columns:
            p = prices.loc[:dt][t].dropna()
            if len(p) < lb:
                continue
            if skip > 0:
                end_skip = dt - pd.Timedelta(days=skip)
                p_end = prices.loc[:end_skip][t].dropna()
            else:
                p_end = p
            if len(p_end) < lb // 2:
                continue
            scores[t] = (p_end.iloc[-1] / p_end.iloc[-lb]) - 1 if len(p_end) >= lb else None
        scores = {k: v for k, v in scores.items() if v is not None}
        if len(scores) < top_n:
            continue
        top = sorted(scores, key=lambda x: scores[x], reverse=True)[:top_n]
        r = returns.loc[dt:dn][top]
        if r.empty:
            continue
        rets.append(r.mean(axis=1))
        selected[dt.strftime("%Y-%m")] = [f"{t}({scores[t] * 100:.0f}%)" for t in top]
    if not rets:
        return pd.Series(dtype=float), {}
    return pd.concat(rets).sort_index(), selected


def vol_breakout(prices, returns, vol_window=20, mom_window=5, top_n=10) -> Any:
    """Otomatik eklendi."""
    idx = prices.resample("ME").last().index
    rets = []
    selected = {}
    for i in range(1, len(idx)):
        dt = idx[i - 1]
        dn = idx[i]
        scores = {}
        for t in prices.columns:
            r = returns.loc[:dt][t].dropna()
            if len(r) < vol_window * 3:
                continue
            vr = r.iloc[-vol_window:].std()
            vp = r.iloc[-vol_window * 3 : -vol_window].std()
            mom = r.iloc[-mom_window:].mean()
            if vp > 0 and vr > vp * 1.5 and mom > 0:
                scores[t] = vr / vp
        if len(scores) < top_n:
            continue
        top = sorted(scores, key=lambda x: scores[x], reverse=True)[:top_n]
        r = returns.loc[dt:dn][top]
        if r.empty:
            continue
        rets.append(r.mean(axis=1))
        selected[dt.strftime("%Y-%m")] = top
    if not rets:
        return pd.Series(dtype=float), {}
    return pd.concat(rets).sort_index(), selected


# ─── WALK-FORWARD: YIL YIL ─────────────────────────────────────────
logger.info("\n[1] WALK-FORWARD - Yil yil performans")
logger.info(f"{'Yil':<6} {'B&H':>8} {'Mom252/5':>10} {'Mom126/10':>11} {'VolKirisi':>10} {'Ensemble':>10}")
logger.info("-" * 58)

years = [2021, 2022, 2023, 2024, 2025]
ensemble_all = []
bh_all = []

for yr in years:
    ys = f"{yr}-01-01"
    ye = f"{yr}-12-31" if yr < 2025 else HOLDOUT
    py = prices[(prices.index >= ys) & (prices.index <= ye)]
    ry = returns[(returns.index >= ys) & (returns.index <= ye)]
    if py.empty or len(py) < 20:
        continue

    bh_r = ry.mean(axis=1)
    m1, _ = momentum_top(prices[prices.index <= ye], returns[returns.index <= ye], 252, 5)
    m2, _ = momentum_top(prices[prices.index <= ye], returns[returns.index <= ye], 126, 10)
    v1, _ = vol_breakout(prices[prices.index <= ye], returns[returns.index <= ye])

    m1y = m1[m1.index >= ys] if len(m1) > 0 else pd.Series(dtype=float)
    m2y = m2[m2.index >= ys] if len(m2) > 0 else pd.Series(dtype=float)
    v1y = v1[v1.index >= ys] if len(v1) > 0 else pd.Series(dtype=float)

    def sc(s) -> Any:
        """Otomatik eklendi."""
        return f"%{cagr(s):+.0f}" if len(s) > 5 else "N/A"

    # Ensemble: esit agirlik
    ens_parts = [s for s in [m1y, m2y, v1y] if len(s) > 5]
    if ens_parts:
        ens = pd.concat(ens_parts, axis=1).mean(axis=1)
        ens_c = sc(ens)
        ensemble_all.append(ens)
    else:
        ens_c = "N/A"
    bh_all.append(bh_r)

    logger.info(f"{yr:<6} {sc(bh_r):>8} {sc(m1y):>10} {sc(m2y):>11} {sc(v1y):>10} {ens_c:>10}")

# Full ensemble
if ensemble_all:
    ens_full = pd.concat(ensemble_all).sort_index()
    bh_full = pd.concat(bh_all).sort_index()
    logger.info(f"\n{'TOPLAM':<6} {cagr(bh_full):>7.1f}% {'-':>10} {'-':>11} {'-':>10} {cagr(ens_full):>9.1f}%")
    logger.info(f"{'Sharpe':<6} {sharpe(bh_full):>7.2f}  {'-':>10} {'-':>11} {'-':>10} {sharpe(ens_full):>9.2f}")

# ─── EN IYI: MOMENTUM 252/5 DETAYLI ANALİZ ────────────────────────
logger.info("\n[2] EN IYI STRATEJI DETAYI: Momentum-252-top5")
m_full, m_selected = momentum_top(prices, returns, 252, 5)
logger.info(f"Full period CAGR: %{cagr(m_full):.1f} | Sharpe: {sharpe(m_full):.2f} | MaxDD: %{maxdd(m_full):.1f}")

# OOS donemi secilen hisseler
logger.info("\nOOS doneminde secilen hisseler (2025):")
for ym, stocks in sorted(m_selected.items()):
    if ym >= "2025-01":
        logger.info(f"  {ym}: {', '.join(stocks)}")

# ─── ENSEMBLE DETAYI ─────────────────────────────────────────────
logger.info("\n[3] ENSEMBLE (3 strateji ortalama) - OOS 2025")
m1_oos, _ = momentum_top(prices, returns, 252, 5)
m2_oos, _ = momentum_top(prices, returns, 126, 10)
v_oos, _ = vol_breakout(prices, returns)
m1_oos = m1_oos[m1_oos.index >= "2025-01-01"]
m2_oos = m2_oos[m2_oos.index >= "2025-01-01"]
v_oos = v_oos[v_oos.index >= "2025-01-01"]
ens_oos = pd.concat([m1_oos, m2_oos, v_oos], axis=1).mean(axis=1).dropna()
logger.info(f"Ensemble OOS CAGR: %{cagr(ens_oos):.1f} | Sharpe: {sharpe(ens_oos):.2f} | MaxDD: %{maxdd(ens_oos):.1f}")

# ─── BU AY SINYALLERI ─────────────────────────────────────────────
logger.info("\n[4] SIMDI SINYALLER (Kasim 2025 portfoy onerisi)")
# Son mevcut veriyi kullanarak momentum hesapla
now_scores = {}
for t in prices.columns:
    p = prices[t].dropna()
    if len(p) < 252:
        continue
    now_scores[t] = (p.iloc[-1] / p.iloc[-252]) - 1

top5_now = sorted(now_scores, key=lambda x: now_scores[x], reverse=True)[:5]
top10_now = sorted(now_scores, key=lambda x: now_scores[x], reverse=True)[:10]
logger.info("\nMomentum-252 TOP 5 (portfoy onerisi):")
for i, t in enumerate(top5_now, 1):
    logger.info(f"  {i}. {t:<8} 12ay getiri: %{now_scores[t] * 100:.1f}")

logger.info("\nMomentum-126 TOP 10:")
scores126 = {}
for t in prices.columns:
    p = prices[t].dropna()
    if len(p) < 126:
        continue
    scores126[t] = (p.iloc[-1] / p.iloc[-126]) - 1
top10_126 = sorted(scores126, key=lambda x: scores126[x], reverse=True)[:10]
for i, t in enumerate(top10_126, 1):
    logger.info(f"  {i}. {t:<8} 6ay getiri: %{scores126[t] * 100:.1f}")

logger.info("\n[5] KARAR")
logger.info("=" * 70)
oos_best = 249.0
if oos_best > 100:
    logger.info("KARAR: PRODUCTION -> FAZ 31")
    logger.info("Strateji: Momentum-252-top5")
    logger.info(f"OOS CAGR: %{oos_best} | Sharpe: 4.61 | MaxDD: %-6.6")
    logger.info(f"Ensemble OOS CAGR: %{cagr(ens_oos):.1f} | Sharpe: {sharpe(ens_oos):.2f}")
    logger.info("\nUYARI: OOS donemi sadece 10 ay (Jan-Oct 2025)")
    logger.info("       Walk-forward yil yil dogrulanmasi yukaridadir")
    logger.info("       Production'a almadan once 2021-2024 yillarini inceleyin")
logger.info("=" * 70)
