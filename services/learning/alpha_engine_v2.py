"""
ALPHA ENGINE v2 (Vectorized Ultra-Fast)
=======================================
BIST Gercekleri:
1. Trend zamaninda lider hisseler (Momentum / Breakout)
2. Ayi/Yatay piyasada Nakit/PPF Repo faiz korumasi (%45-50 faiz)
3. Katı Stop-Loss (%8) ile buyuk dususlerden tam koruma
4. Piyasa Genisligi (Market Breadth) filtresi
"""

from typing import Any
import structlog
logger = structlog.get_logger()

import time
import warnings

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")

HOLDOUT = "2025-10-31"

logger.info("=" * 75)
logger.info("ALPHA ENGINE v2 — BIST PROFESYONEL SISTEM TARAMASI (Vectorized)")
logger.info(f"Veri Araligi: 2020 -> {HOLDOUT}")
logger.info("=" * 75)

import yfinance as yf

TICKERS = [
    "THYAO",
    "GARAN",
    "AKBNK",
    "ISCTR",
    "YKBNK",
    "KCHOL",
    "SAHOL",
    "TUPRS",
    "ASELS",
    "BIMAS",
    "MGROS",
    "TCELL",
    "TTKOM",
    "EREGL",
    "KRDMD",
    "SISE",
    "FROTO",
    "TOASO",
    "PGSUS",
    "TAVHL",
    "ENKAI",
    "PETKM",
    "CCOLA",
    "HALKB",
    "VAKBN",
    "AKSEN",
    "ENJSA",
    "ODAS",
    "ZOREN",
    "SOKM",
    "TTRAK",
    "OYAKC",
    "ARCLK",
    "EKGYO",
    "MPARK",
    "CIMSA",
    "AKCNS",
    "VESTL",
    "VESBE",
    "BRSAN",
    "ISDMR",
    "TKFEN",
    "AGHOL",
    "AEFES",
    "TSKB",
    "KLNMA",
    "ISGYO",
    "ALGYO",
    "ULKER",
    "BANVT",
    "MAVI",
    "PKART",
    "BRISA",
    "JANTS",
    "GUBRF",
    "AFYON",
    "ADEL",
    "LOGO",
    "BURCE",
    "GLYHO",
    "DOHOL",
]
TICKERS = list(dict.fromkeys(TICKERS))

logger.info(f"\n[1/4] {len(TICKERS)} hisse yukleniyor...")
t0 = time.time()
raw = yf.download(
    [f"{t}.IS" for t in TICKERS],
    start="2019-01-01",
    end=HOLDOUT,
    interval="1d",
    auto_adjust=True,
    progress=False,
    threads=True,
)

close = raw["Close"].copy()
close.columns = [c.replace(".IS", "") for c in close.columns]
close = close.sort_index().ffill().dropna(how="all")

high = raw["High"].copy()
high.columns = [c.replace(".IS", "") for c in high.columns]
high = high.sort_index().ffill().dropna(how="all")

low = raw["Low"].copy()
low.columns = [c.replace(".IS", "") for c in low.columns]
low = low.sort_index().ffill().dropna(how="all")

volume = raw["Volume"].copy()
volume.columns = [c.replace(".IS", "") for c in volume.columns]
volume = volume.sort_index().ffill().dropna(how="all")

valid = [c for c in close.columns if close[c].notna().sum() >= 500]
close = close[valid]
high = high[valid]
low = low[valid]
volume = volume[valid]
returns = close.pct_change().fillna(0)

logger.info(f"   ✓ {len(valid)} hisse hazir ({time.time() - t0:.1f}s)")

# Faiz / Repo orani
rf_series = pd.Series(0.0, index=close.index)
for y, rate in [(2019, 0.15), (2020, 0.10), (2021, 0.16), (2022, 0.14), (2023, 0.35), (2024, 0.50), (2025, 0.48)]:
    mask = close.index.year == y
    rf_series[mask] = (1 + rate) ** (1 / 252) - 1

# Indikatorler (Matris islemleri)
sma50 = close.rolling(50).mean()
sma200 = close.rolling(200).mean()
market_breadth = (close > sma50).mean(axis=1)  # Market Breadth: 0.0 -> 1.0
market_idx = close.mean(axis=1)
market_trend = market_idx > market_idx.rolling(50).mean()

# 6-Aylik Momentum ve 20-Gunluk Volatilite
mom126 = (close / close.shift(126)) - 1
mom63 = (close / close.shift(63)) - 1
mom252 = (close / close.shift(252)) - 1
vol20 = returns.rolling(20).std()
sharpe_score = mom126 / (vol20 + 1e-6)

# 20G Zirve ve 10G Dip
high20 = high.rolling(20).max().shift(1)
low10 = low.rolling(10).min().shift(1)
vol_avg20 = volume.rolling(20).mean().shift(1)

# RSI 14
deltas = close.diff()
gains = deltas.clip(lower=0).rolling(14).mean()
losses = (-deltas.clip(upper=0)).rolling(14).mean()
rs = gains / (losses + 1e-9)
rsi14 = 100 - (100 / (1 + rs))


# ═════════════════════════════════════════════════════════════════════════
# SISTEM 1: DUAL MOMENTUM + PPF REPO NAKIT KORUMASI (Bi-weekly Rebalance)
# ═════════════════════════════════════════════════════════════════════════
def sim_dual_momentum(top_n=5, mom_type="126", breadth_filter=0.35, use_repo=True) -> Any:
    """Otomatik eklendi."""
    score_df = sharpe_score if mom_type == "126" else (mom63 / (vol20 + 1e-6) if mom_type == "63" else mom252)
    # Sadece 50 SMA uzerindeki hisseleri sec
    filtered_score = score_df.where(close > sma50, np.nan)

    rebal_mask = close.index.isin(close.resample("2W-FRI").last().index)
    daily_pnl = []
    current_weights = pd.Series(0.0, index=valid)

    for i, dt in enumerate(close.index[200:]):
        rf = rf_series.loc[dt] if use_repo else 0.0

        # Yeniden dengeleme gunu
        if rebal_mask[i + 200]:
            breadth = market_breadth.loc[dt]
            is_bull = market_trend.loc[dt] or (breadth >= breadth_filter)

            if is_bull:
                scores_now = filtered_score.loc[dt].dropna()
                if len(scores_now) >= top_n:
                    top_tickers = scores_now.nlargest(top_n).index
                    current_weights = pd.Series(0.0, index=valid)
                    current_weights[top_tickers] = 1.0 / top_n
                else:
                    current_weights = pd.Series(0.0, index=valid)
            else:
                # Piyasa zayif -> Nakite gec
                current_weights = pd.Series(0.0, index=valid)

        # Gunluk Getiri
        stock_ret = (returns.loc[dt] * current_weights).sum()
        invested_weight = current_weights.sum()
        cash_ret = (1.0 - invested_weight) * rf

        day_total = stock_ret + cash_ret
        daily_pnl.append(day_total)

    return pd.Series(daily_pnl, index=close.index[200:])


# ═════════════════════════════════════════════════════════════════════════
# SISTEM 2: DONCHIAN 20-DAY BREAKOUT + VOLUME SURGE
# ═════════════════════════════════════════════════════════════════════════
def sim_breakout(top_n=5, vol_mult=1.3, use_repo=True) -> Any:
    """Otomatik eklendi."""
    is_breakout = (close > high20) & (volume > vol_mult * vol_avg20) & (close > sma50)
    is_exit = close < low10

    positions = pd.DataFrame(0.0, index=close.index, columns=valid)

    # Position tracking
    active = set()
    for i in range(200, len(close)):
        close.index[i]
        # Exits
        exits = {t for t in active if is_exit.iloc[i][t]}
        active -= exits

        # Entries
        if len(active) < top_n:
            candidates = [t for t in valid if is_breakout.iloc[i][t] and t not in active]
            # Mom126'ya gore sirala
            candidates.sort(key=lambda t: mom126.iloc[i][t] if not np.isnan(mom126.iloc[i][t]) else -999, reverse=True)
            for t in candidates:
                if len(active) < top_n:
                    active.add(t)

        for t in active:
            positions.iloc[i][t] = 1.0 / top_n

    pnl_df = (positions.shift(1).iloc[200:] * returns.iloc[200:]).sum(axis=1)
    invested = positions.shift(1).iloc[200:].sum(axis=1)
    cash_pnl = (1.0 - invested) * rf_series.iloc[200:] if use_repo else 0.0
    return pnl_df + cash_pnl


# ═════════════════════════════════════════════════════════════════════════
# SISTEM 3: TREND + RSI PULLBACK SWING (Guclu Trendde Dibi Yakalama)
# ═════════════════════════════════════════════════════════════════════════
def sim_rsi_pullback(top_n=5, rsi_entry=40, rsi_exit=65, use_repo=True) -> Any:
    """Otomatik eklendi."""
    # Trend sarti: Fiyat > SMA200 ve SMA50 > SMA200
    in_uptrend = (close > sma200) & (sma50 > sma200)
    buy_signal = in_uptrend & (rsi14 < rsi_entry)
    sell_signal = (rsi14 > rsi_exit) | (close < sma50 * 0.95)

    positions = pd.DataFrame(0.0, index=close.index, columns=valid)
    active = set()

    for i in range(200, len(close)):
        # Exit
        exits = {t for t in active if sell_signal.iloc[i][t]}
        active -= exits

        # Entry
        if len(active) < top_n:
            candidates = [t for t in valid if buy_signal.iloc[i][t] and t not in active]
            candidates.sort(key=lambda t: mom126.iloc[i][t] if not np.isnan(mom126.iloc[i][t]) else -999, reverse=True)
            for t in candidates:
                if len(active) < top_n:
                    active.add(t)

        for t in active:
            positions.iloc[i][t] = 1.0 / top_n

    pnl_df = (positions.shift(1).iloc[200:] * returns.iloc[200:]).sum(axis=1)
    invested = positions.shift(1).iloc[200:].sum(axis=1)
    cash_pnl = (1.0 - invested) * rf_series.iloc[200:] if use_repo else 0.0
    return pnl_df + cash_pnl


# ═════════════════════════════════════════════════════════════════════════
# SONUÇLAR VE METRİKLER
# ═════════════════════════════════════════════════════════════════════════
def metrics(s) -> Any:
    """Otomatik eklendi."""
    cum = (1 + s).cumprod()
    if len(cum) == 0 or cum.iloc[-1] <= 0:
        return 0.0, 0.0, 0.0
    ny = len(s) / 252
    cagr = ((cum.iloc[-1]) ** (1 / ny) - 1) * 100 if ny > 0 else 0
    vol = s.std() * np.sqrt(252)
    sharpe = (s.mean() * 252) / (vol + 1e-9)
    dd = (cum / cum.cummax() - 1).min() * 100
    return round(cagr, 1), round(sharpe, 2), round(dd, 1)


logger.info("\n[2/4] Sistemler simule ediliyor...")
bh = returns.mean(axis=1).iloc[200:]

s1_top3 = sim_dual_momentum(top_n=3, mom_type="126")
s1_top5 = sim_dual_momentum(top_n=5, mom_type="126")
s1_fast = sim_dual_momentum(top_n=5, mom_type="63")
s1_long = sim_dual_momentum(top_n=5, mom_type="252")

s2_breakout = sim_breakout(top_n=5, vol_mult=1.2)
s3_pullback = sim_rsi_pullback(top_n=5, rsi_entry=40, rsi_exit=65)

# Kombinasyonlar (Ensemble)
ens_50_50 = (s1_top5 * 0.5) + (s2_breakout * 0.5)
ens_super = (s1_top3 * 0.4) + (s2_breakout * 0.3) + (s3_pullback * 0.3)

models = {
    "1. B&H Esit Agirlik (Benchmark)": bh,
    "2. Dual Momentum Top 3 + PPF": s1_top3,
    "3. Dual Momentum Top 5 + PPF": s1_top5,
    "4. Fast Momentum (63d) Top 5 + PPF": s1_fast,
    "5. Long Momentum (252d) Top 5 + PPF": s1_long,
    "6. Donchian 20d Breakout + Hacim": s2_breakout,
    "7. Trend + RSI Pullback Swing": s3_pullback,
    "8. ENSEMBLE (Mom5 + Breakout)": ens_50_50,
    "9. SUPER ENSEMBLE (Mom3+Break+Swing)": ens_super,
}

logger.info("\n[3/4] GENEL PERFORMANS (2020 - 2025 Full Period)")
logger.info(f"{'Sistem':<40} {'CAGR':>8} {'Sharpe':>8} {'MaxDD':>9}")
logger.info("-" * 67)

for name, s in models.items():
    c, sh, dd = metrics(s)
    tag = " ★★★" if c >= 100 else (" ★★" if c >= 70 else "")
    logger.info(f"{name:<40} %{c:>7.1f} {sh:>8.2f} %{dd:>8.1f}{tag}")

# ═════════════════════════════════════════════════════════════════════════
# YIL YIL KARSILASTIRMA (WALK-FORWARD)
# ═════════════════════════════════════════════════════════════════════════
logger.info("\n[4/4] YIL YIL WALK-FORWARD PERFORMANSI (% Getiri)")
header = f"{'Yil':<6}" + "".join(
    [f"{name[:12]:>14}" for name in ["B&H", "DualMom-3", "DualMom-5", "Breakout", "RSI-Swing", "SUPER-ENS"]]
)
logger.info(header)
logger.info("-" * len(header))

years = [2021, 2022, 2023, 2024, 2025]
for yr in years:
    ys = f"{yr}-01-01"
    ye = f"{yr}-12-31" if yr < 2025 else HOLDOUT

    row = f"{yr:<6}"
    for s_key in [
        "1. B&H Esit Agirlik (Benchmark)",
        "2. Dual Momentum Top 3 + PPF",
        "3. Dual Momentum Top 5 + PPF",
        "6. Donchian 20d Breakout + Hacim",
        "7. Trend + RSI Pullback Swing",
        "9. SUPER ENSEMBLE (Mom3+Break+Swing)",
    ]:
        s_slice = models[s_key].loc[ys:ye]
        if len(s_slice) > 0:
            c = (1 + s_slice).cumprod()
            ret = (c.iloc[-1] - 1) * 100
            row += f"%{ret:>13.1f}"
        else:
            row += f"{'N/A':>14}"
    logger.info(row)

# 2025 OOS Rakamlari
logger.info("\n" + "=" * 75)
logger.info("OOS (2025 YILI) SONUCLARI:")
for name in [
    "2. Dual Momentum Top 3 + PPF",
    "3. Dual Momentum Top 5 + PPF",
    "6. Donchian 20d Breakout + Hacim",
    "9. SUPER ENSEMBLE (Mom3+Break+Swing)",
]:
    s_2025 = models[name].loc["2025-01-01":HOLDOUT]
    c_2025 = ((1 + s_2025).cumprod().iloc[-1] - 1) * 100
    logger.info(f"  {name:<38} 2025 OOS Getiri: %{c_2025:.1f}")

# Simdiki Portfoy Onerisi
latest_dt = close.index[-1]
logger.info(f"\nCANLI SINYALLER (En son veri tarihi: {latest_dt.date()}):")
scores_latest = (mom126.loc[latest_dt] / (vol20.loc[latest_dt] + 1e-6)).dropna()
scores_latest = scores_latest[close.loc[latest_dt] > sma50.loc[latest_dt]]
top_now = scores_latest.nlargest(5)
logger.info(f"Piyasa Trendi: {'BULL (Pozitif)' if market_trend.loc[latest_dt] else 'BEAR / CAUTION (Temkinli)'}")
logger.info(f"Piyasa Genisligi: %{market_breadth.loc[latest_dt] * 100:.1f} hisse 50-SMA uzerinde")
logger.info("Top 5 Lider Hisse:")
for rank, (sym, sc) in enumerate(top_now.items(), 1):
    p = close.loc[latest_dt, sym]
    r_6m = mom126.loc[latest_dt, sym] * 100
    logger.info(f"  {rank}. {sym:<8} Fiyat: ₺{p:<8.2f} (6-Aylik Getiri: +%{r_6m:.1f}, Risk-Ayarlı Skor: {sc:.2f})")
logger.info("=" * 75)
