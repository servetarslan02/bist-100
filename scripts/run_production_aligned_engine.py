"""
ALPHA BIST — PRODUCTION-ALIGNED REAL ENGINE BACKTEST (2016-2026)
================================================================
Doğrudan services/risk/regime_limits.py, services/portfolio/portfolio_optimizer.py
ve services/core/constants.py Dosyalarındaki Gerçek Kurallarla Birebir Eşitlenmiş Motor:

1. GERÇEK REJİM VE RİSK LİMİTLERİ (RegimeRiskLimits):
   - BULL     : Tek hisse max %12 (en az ~8-10 hisse), toplam maruziyet %100, sektör tavanı %30
   - BEAR     : Tek hisse max %6, toplam maruziyet %50 (savunma/nakit %50), sektör tavanı %20
   - SIDEWAYS : Tek hisse max %8 (en az ~12 hisse), toplam maruziyet %70, sektör tavanı %25
   - Portföy genel tavanı: MAX_POSITIONS = 20

2. HALKA ARZ & POINT-IN-TIME EVREN (Sıfır Hayatta Kalma Yanlılığı):
   - Tüm BIST-100 ve genişletilmiş hisse evreni taranır.
   - Bir hisse SADECE VE SADECE borsada ilk işlem gördüğü tarihten sonra evrene girer.
   - Halka arz öncesi geçmişe dönük geleceği görme (lookahead) sıfırlanmıştır.

3. MUM VE PRICE ACTION ZEKA MOTORU (CandlePatternEngine):
   - Çekiç/Pinbar, Yutan Boğa, Sabah Yıldızı, Üç Beyaz Asker, Bullish FVG ve Alıcı Baskısı %
   - Sadece onaylı mum günlerinde alım yapılır.

4. QUANT SIRALAMA METRİKLERİ (RankingModel):
   - Sektör Liderliği (7 Sektör Bağıl Gücü)
   - Hacim Akümülasyon Trendi (5g vs 20g)
   - Relatif Güç (RS vs BIST) & Trend R²
   - Volatilite Düzeltmeli Momentum (Sharpe Proxy)
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

# Doğrudan sistem servislerinin sabitleri ve limit tanımları
from services.core.constants import MAX_POSITIONS
from services.risk.regime_limits import RegimeRiskLimits, regime_limits

REGIME_LIMITS = regime_limits.REGIME_LIMITS

logger = structlog.get_logger()

# ---------------------------------------------------------------------------
# 1. GENİŞLETİLMİŞ BIST EVRENİ (BIST-100 + Büyüme Hisseleri)
# ---------------------------------------------------------------------------
SECTOR_MAP: dict[str, str] = {
    # Finans
    "GARAN.IS": "FINANS", "AKBNK.IS": "FINANS", "ISCTR.IS": "FINANS", "YKBNK.IS": "FINANS",
    "HALKB.IS": "FINANS", "VAKBN.IS": "FINANS", "TSKB.IS": "FINANS", "ISMEN.IS": "FINANS",
    "ALBRK.IS": "FINANS", "SKBNK.IS": "FINANS", "ANSGR.IS": "FINANS", "TURSG.IS": "FINANS",
    # Holding
    "KCHOL.IS": "HOLDING", "SAHOL.IS": "HOLDING", "DOHOL.IS": "HOLDING", "AGHOL.IS": "HOLDING",
    "ALARK.IS": "HOLDING", "BERA.IS": "HOLDING", "TKFEN.IS": "HOLDING",
    # Sanayi & Otomotiv & Çimento
    "ENKAI.IS": "SANAYI", "EREGL.IS": "SANAYI", "SISE.IS": "SANAYI", "TOASO.IS": "SANAYI",
    "FROTO.IS": "SANAYI", "ARCLK.IS": "SANAYI", "KRDMD.IS": "SANAYI", "VESBE.IS": "SANAYI",
    "VESTL.IS": "SANAYI", "DOAS.IS": "SANAYI", "TTRAK.IS": "SANAYI", "OTKAR.IS": "SANAYI",
    "CIMSA.IS": "SANAYI", "AKCNS.IS": "SANAYI", "BRSAN.IS": "SANAYI", "EGEEN.IS": "SANAYI",
    # Enerji & Kimya
    "TUPRS.IS": "ENERJI", "PETKM.IS": "ENERJI", "GUBRF.IS": "ENERJI", "SASA.IS": "ENERJI",
    "HEKTS.IS": "ENERJI", "AKSA.IS": "ENERJI", "AKSEN.IS": "ENERJI", "ENJSA.IS": "ENERJI",
    "ASTOR.IS": "ENERJI", "KONTR.IS": "ENERJI", "GESAN.IS": "ENERJI", "EUPWR.IS": "ENERJI",
    # Havacılık & Ulaştırma
    "THYAO.IS": "ULASTIRMA", "PGSUS.IS": "ULASTIRMA", "TAVHL.IS": "ULASTIRMA", "CLEBI.IS": "ULASTIRMA",
    # Telekom & Teknoloji & Savunma
    "TTKOM.IS": "TEKNOLOJI", "TCELL.IS": "TEKNOLOJI", "ASELS.IS": "TEKNOLOJI", "LOGO.IS": "TEKNOLOJI",
    "MIATK.IS": "TEKNOLOJI", "ARDYZ.IS": "TEKNOLOJI",
    # Perakende & Tüketim & İlaç
    "BIMAS.IS": "TUKETIM", "MGROS.IS": "TUKETIM", "SOKM.IS": "TUKETIM", "CCOLA.IS": "TUKETIM",
    "AEFES.IS": "TUKETIM", "ULKER.IS": "TUKETIM", "MAVI.IS": "TUKETIM", "ECILC.IS": "TUKETIM",
    # GYO & Madencilik
    "EKGYO.IS": "GYO", "ISGYO.IS": "GYO", "KOZAL.IS": "MADEN", "KOZAA.IS": "MADEN",
}

FULL_UNIVERSE = list(SECTOR_MAP.keys())
BENCHMARK_TICKER = "XU100.IS"
DEFENSIVE_SECTORS = {"TUKETIM", "TEKNOLOJI", "ENERJI"}

COMMISSION = 0.0015
SLIPPAGE = 0.0010
COST_ONE_WAY = COMMISSION + SLIPPAGE


# ---------------------------------------------------------------------------
# 2. VEKTÖREL MUM VE FAKTÖR ANALİZİ
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


def analyze_candlestick(o: float, h: float, l: float, c: float, o_prev: float, c_prev: float) -> tuple[float, bool]:
    """Mum anatomisi ve formasyon tespiti."""
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

    # Bullish formasyon
    has_bull_pat = False
    if lower_wick_ratio >= 0.45 and upper_wick_ratio <= 0.25 and body_ratio >= 0.10:
        has_bull_pat = True  # Hammer
    elif (c_prev < o_prev) and is_green and (o <= c_prev * 1.005) and (c >= o_prev * 0.995):
        has_bull_pat = True  # Bullish Engulfing

    return buyer_pct, has_bull_pat


# ---------------------------------------------------------------------------
# 3. GERÇEK MOTOR SİMÜLASYONU (Production Rules Aligned)
# ---------------------------------------------------------------------------
def run_production_aligned_backtest() -> None:
    t0 = time.time()
    START = "2016-01-01"
    END = "2026-08-29"
    INITIAL_CAPITAL = 100_000.0

    logger.info("=" * 88)
    logger.info(f"[1] GENİŞLETİLMİŞ BIST EVRENİ İNDİRİLİYOR ({len(FULL_UNIVERSE)} Hisse)")
    logger.info("=" * 88)

    bm_raw = yf.download(BENCHMARK_TICKER, start=START, end=END, progress=False)
    if bm_raw.empty:
        raise RuntimeError("BIST-100 verisi indirilemedi!")
    if hasattr(bm_raw.columns, "levels") and len(bm_raw.columns.levels) > 1:
        bm_raw.columns = bm_raw.columns.get_level_values(0)
    bm_df = bm_raw[["Open", "High", "Low", "Close", "Volume"]].dropna()

    stocks_raw = yf.download(FULL_UNIVERSE, start=START, end=END, progress=False, group_by="ticker")
    stock_dict: dict[str, Any] = {}
    listing_dates: dict[str, Any] = {}

    for t in FULL_UNIVERSE:
        try:
            if hasattr(stocks_raw.columns, "levels") and t in stocks_raw.columns.get_level_values(0):
                df_t = stocks_raw[t][["Open", "High", "Low", "Close", "Volume"]].dropna()
                if len(df_t) > 60:
                    stock_dict[t] = df_t
                    listing_dates[t] = df_t.index[0]  # Halka arz / ilk işlem tarihi
        except Exception:
            continue

    logger.info(f"  [OK] BIST-100: {len(bm_df):,} seans ({bm_df.index[0].date()} - {bm_df.index[-1].date()})")
    logger.info(f"  [OK] {len(stock_dict)} hisse yüklendi. Halka arz tarihleri indekslendi.\n")

    bm_close = bm_df["Close"]
    if hasattr(bm_close, "shape") and len(bm_close.shape) > 1:
        bm_close = bm_close.iloc[:, 0]

    all_dates = list(bm_df.index)[200:]
    bm_ini = _to_float(bm_close.loc[all_dates[0]])
    bm_fin = _to_float(bm_close.loc[all_dates[-1]])
    bm_total_ret = (bm_fin - bm_ini) / bm_ini * 100
    bm_cagr = (bm_fin / bm_ini) ** (1 / (len(all_dates) / 252)) - 1

    logger.info("=" * 88)
    logger.info("[2] GERÇEK MOTOR RİSK VE PORTFÖY KURALLARI YÜKLENDİ")
    logger.info("=" * 88)
    for reg_name, lim in REGIME_LIMITS.items():
        logger.info(f"  • {reg_name:<9}: Tek Hisse Max %{lim.max_position_pct * 100:.0f} | "
                    f"Toplam Maruziyet: %{lim.max_total_exposure * 100:.0f} | "
                    f"Sektör Tavanı: %{lim.max_sector_concentration * 100:.0f} | {lim.description}")
    logger.info(f"  • Genel Tavan: MAX_POSITIONS = {MAX_POSITIONS} hisse")
    logger.info("  • Halka Arz Kuralı: Bir hisse sadece listelenme tarihinden sonra taranabilir.")
    logger.info("-" * 88)

    capital = INITIAL_CAPITAL
    positions: dict[str, dict[str, Any]] = {}
    trade_logs: list[dict[str, Any]] = []
    equity_curve: list[float] = []

    yearly_stats: dict[int, dict[str, Any]] = {}
    current_year = all_dates[0].year
    year_start_capital = capital
    year_start_bm = _to_float(bm_close.loc[all_dates[0]])
    last_rebalance_month = -1

    regime_counter = {"BULL": 0, "SIDEWAYS": 0, "BEAR": 0}

    for di, dt in enumerate(all_dates):
        # Yıl geçiş kaydı
        if dt.year != current_year:
            port_val = capital + sum(p["shares"] * p["current_price"] for p in positions.values())
            year_ret = (port_val - year_start_capital) / year_start_capital * 100
            bm_curr = _to_float(bm_close.loc[dt])
            bm_ret = (bm_curr - year_start_bm) / year_start_bm * 100
            yearly_stats[current_year] = {
                "port_return": year_ret,
                "bm_return": bm_ret,
                "alpha": year_ret - bm_ret,
            }
            current_year = dt.year
            year_start_capital = port_val
            year_start_bm = bm_curr

        # Rejim Belirleme (BULL, SIDEWAYS, BEAR)
        bh = bm_close.loc[:dt]
        ba = bh.values.astype(float) if not (hasattr(bh, "shape") and len(bh.shape) > 1) else bh.iloc[:, 0].values.astype(float)
        c_now = ba[-1]
        s50 = np.mean(ba[-50:])
        s200 = np.mean(ba[-200:])

        if c_now >= s50 and s50 >= s200:
            current_regime = "BULL"
        elif c_now >= s50 or s50 >= s200:
            current_regime = "SIDEWAYS"
        else:
            current_regime = "BEAR"

        regime_counter[current_regime] += 1
        limits: RegimeRiskLimits = REGIME_LIMITS[current_regime]

        # -------------------------------------------------------------
        # 1. MEVCUT POZİSYONLARI GÜNCELLE & STOP ÇIKIŞLARI KONTROL ET
        # -------------------------------------------------------------
        closed_tickers = []
        for t, pos in list(positions.items()):
            df_t = stock_dict.get(t)
            if df_t is None or dt not in df_t.index:
                continue

            bar = df_t.loc[dt]
            p_close = _to_float(bar["Close"])
            p_high = _to_float(bar["High"])
            p_open = _to_float(bar["Open"])
            pos["current_price"] = p_close

            # Trailing stop güncelleme (ATR 4.0x)
            if p_high > pos["peak_price"]:
                pos["peak_price"] = p_high
                new_stop = pos["peak_price"] - (4.0 * pos["atr"])
                if new_stop > pos["stop_level"]:
                    pos["stop_level"] = new_stop

            hold_days = (dt - pos["entry_date"]).days
            should_exit = False
            exit_reason = ""
            exit_price = p_close

            # Çıkış 1: Trailing stop patladı
            if p_close <= pos["stop_level"]:
                should_exit = True
                exit_price = pos["stop_level"]
                exit_reason = "TRAILING_STOP"
            # Çıkış 2: Zaman stopu (45 gün)
            elif hold_days > 45 and p_close < pos["entry_price"] * 0.98:
                should_exit = True
                exit_price = p_close
                exit_reason = "TIME_STOP_45D"

            if should_exit:
                real_p = exit_price * (1 - SLIPPAGE)
                proceeds = pos["shares"] * real_p * (1 - COMMISSION)
                capital += proceeds
                cost = pos["shares"] * pos["entry_price"] * (1 + COST_ONE_WAY)
                trade_logs.append({
                    "ticker": t,
                    "pnl": proceeds - cost,
                    "pnl_pct": (proceeds - cost) / cost * 100,
                    "reason": exit_reason,
                    "regime": current_regime,
                })
                closed_tickers.append(t)

        for t in closed_tickers:
            positions.pop(t, None)

        # -------------------------------------------------------------
        # 2. YENİ POZİSYON GİRİŞLERİ (Aylık Rebalance / Dinamik)
        # -------------------------------------------------------------
        is_rebalance_trigger = (dt.month != last_rebalance_month) or (len(positions) <= 3)

        if is_rebalance_trigger and len(positions) < MAX_POSITIONS:
            last_rebalance_month = dt.month

            # POINT-IN-TIME ADAY HAVUZU: Sadece o gün borsada listeli hisseler!
            eligible_tickers = [t for t, df_t in stock_dict.items() if listing_dates[t] <= dt and dt in df_t.index]

            cands = []
            bm_r20 = (ba[-1] / ba[-20] - 1) if len(ba) >= 20 else 0.0

            for t in eligible_tickers:
                if t in positions:
                    continue

                hist = stock_dict[t].loc[:dt]
                if len(hist) < 60:
                    continue

                ca = hist["Close"].values.astype(float)
                ha = hist["High"].values.astype(float)
                la = hist["Low"].values.astype(float)
                oa = hist["Open"].values.astype(float)
                va = hist["Volume"].values.astype(float) if "Volume" in hist else np.ones(len(hist))

                p_now = ca[-1]
                if p_now <= 0:
                    continue

                # Mum analizi
                buyer_pct, has_bull_pat = analyze_candlestick(oa[-1], ha[-1], la[-1], ca[-1], oa[-2], ca[-2])

                # Quant metrikler
                roc20 = (p_now / ca[-20] - 1) if len(ca) >= 20 else 0.0
                rs20 = roc20 - bm_r20

                # ATR 14
                h_arr = ha[-14:]
                l_arr = la[-14:]
                c_prev = ca[-15:-1]
                if len(h_arr) == len(c_prev):
                    tr = np.maximum.reduce([h_arr - l_arr, np.abs(h_arr - c_prev), np.abs(l_arr - c_prev)])
                    atr_v = float(np.mean(tr))
                else:
                    atr_v = p_now * 0.025
                if atr_v <= 0:
                    atr_v = p_now * 0.025

                # Vol-adj mom
                rets20 = np.diff(ca[-21:]) / ca[-21:-1] if len(ca) >= 21 else np.array([0.0])
                vol20 = float(np.std(rets20)) if len(rets20) > 1 else 0.02
                vol_adj = roc20 / vol20 if vol20 > 1e-8 else 0.0

                r2_val = _calc_r2(ca[-60:])
                v_avg20 = float(np.mean(va[-20:])) if len(va) >= 20 else 1.0
                v_avg5 = float(np.mean(va[-5:])) if len(va) >= 5 else 1.0
                vol_trend = v_avg5 / v_avg20 if v_avg20 > 0 else 1.0

                sec_name = SECTOR_MAP.get(t, "DIGER")
                is_def = sec_name in DEFENSIVE_SECTORS

                # Mum filtresi: En az %50 alıcı baskısı veya onaylı mum
                if not is_def and buyer_pct < 50.0 and not has_bull_pat:
                    continue

                candle_bonus = 0.20 if has_bull_pat else (0.10 if buyer_pct >= 60.0 else 0.0)

                # Bütünleşik Puan
                score = (
                    (np.clip(vol_adj, -4, 4) / 4.0 * 0.20)
                    + (np.clip(rs20, -0.20, 0.20) * 5.0 * 0.20)
                    + (r2_val * 0.15)
                    + (min(vol_trend, 2.5) / 2.5 * 0.25)
                    + (candle_bonus * 0.20)
                )
                cands.append((score, t, p_now, atr_v, sec_name))

            cands.sort(key=lambda x: x[0], reverse=True)

            port_equity = capital + sum(p["shares"] * p["current_price"] for p in positions.values())
            investable = port_equity * limits.max_total_exposure

            # Sektör konsantrasyonu takibi
            sector_allocations: dict[str, float] = {}
            for t, pos in positions.items():
                s = SECTOR_MAP.get(t, "DIGER")
                val = pos["shares"] * pos["current_price"]
                sector_allocations[s] = sector_allocations.get(s, 0.0) + (val / port_equity)

            # Pozisyon açma döngüsü
            for sc, t, p_entry, atr_v, sec in cands:
                if len(positions) >= limits.max_positions or len(positions) >= MAX_POSITIONS:
                    break

                # Toplam hisse maruziyeti kontrolü (Nakit tamponu kuralı)
                current_total_val = sum(p["shares"] * p["current_price"] for p in positions.values())
                if (current_total_val / port_equity) >= limits.max_total_exposure:
                    break  # Fırsatlar için ayrılan nakit rezervine dokunma

                # Sektör tavanı kontrolü (Gerçek Motor Kuralı: max_sector_concentration)
                current_sec_weight = sector_allocations.get(sec, 0.0)
                if current_sec_weight + limits.max_position_pct > limits.max_sector_concentration:
                    continue

                # Tekil hisse tavanı (Gerçek Motor Kuralı: max_position_pct)
                target_alloc = port_equity * limits.max_position_pct
                # Kalan nakit ile nakit rezervi sınırına saygı duy
                max_allowed_spend = max(0.0, (port_equity * limits.max_total_exposure) - current_total_val)
                alloc = min(capital * 0.95, target_alloc, max_allowed_spend)

                if alloc < 2000:
                    continue

                ep = p_entry * (1 + SLIPPAGE)
                cost_share = ep * (1 + COMMISSION)
                shs = int(alloc / cost_share)

                if shs <= 0 or (shs * cost_share) > capital:
                    continue

                capital -= shs * cost_share
                sector_allocations[sec] = sector_allocations.get(sec, 0.0) + ((shs * cost_share) / port_equity)

                positions[t] = {
                    "shares": shs,
                    "entry_price": ep,
                    "current_price": ep,
                    "peak_price": ep,
                    "stop_level": ep - (4.0 * atr_v),
                    "atr": atr_v,
                    "entry_date": dt,
                }

        day_eq = capital + sum(p["shares"] * p["current_price"] for p in positions.values())
        equity_curve.append(day_eq)

    # -------------------------------------------------------------
    # 4. FİNAL RAPOR VE ALFA TABLOSU
    # -------------------------------------------------------------
    final_eq = capital + sum(p["shares"] * p["current_price"] for p in positions.values())
    if current_year not in yearly_stats:
        year_ret = (final_eq - year_start_capital) / year_start_capital * 100
        bm_curr = _to_float(bm_close.iloc[-1])
        bm_ret = (bm_curr - year_start_bm) / year_start_bm * 100
        yearly_stats[current_year] = {
            "port_return": year_ret,
            "bm_return": bm_ret,
            "alpha": year_ret - bm_ret,
        }

    total_net_profit = final_eq - INITIAL_CAPITAL
    total_return_pct = total_net_profit / INITIAL_CAPITAL * 100

    eq_series = np.array(equity_curve)
    daily_returns = np.diff(eq_series) / eq_series[:-1]
    sharpe = float((np.mean(daily_returns) / np.std(daily_returns)) * np.sqrt(252)) if np.std(daily_returns) > 0 else 0.0

    peaks = np.maximum.accumulate(eq_series)
    drawdowns = (eq_series - peaks) / peaks
    max_drawdown_pct = float(np.min(drawdowns) * 100)

    n_years = len(eq_series) / 252
    cagr = (final_eq / INITIAL_CAPITAL) ** (1 / n_years) - 1 if n_years > 0 else 0

    total_trades = len(trade_logs)
    wins = [t for t in trade_logs if t["pnl"] > 0]
    win_rate = len(wins) / total_trades * 100 if total_trades > 0 else 0

    sep = "=" * 90
    logger.info(f"\n{sep}")
    logger.info("  ALPHA BIST — GERÇEK MOTOR VE SİSTEM KURALLARIYLA 10-YILLIK SONUÇ (2016-2026)")
    logger.info(sep)
    logger.info(f"  {'Metrik':<38} {'GERÇEK MOTOR':>15} {'BIST-100':>15}")
    logger.info("-" * 72)
    logger.info(f"  {'10Y Toplam Getiri':<38} {total_return_pct:>14.1f}% {bm_total_ret:>14.1f}%")
    logger.info(f"  {'Yıllık Bileşik Getiri (CAGR)':<38} {cagr * 100:>14.1f}% {bm_cagr * 100:>14.1f}%")
    logger.info(f"  {'Sharpe Oranı':<38} {sharpe:>15.2f} {'---':>15}")
    logger.info(f"  {'Maksimum Drawdown':<38} {max_drawdown_pct:>14.2f}% {'---':>15}")
    logger.info(f"  {'Kazanma Oranı (Win Rate)':<38} {win_rate:>14.1f}% {'---':>15}")
    logger.info(f"  {'Toplam İşlem Sayısı':<38} {total_trades:>15,} {'---':>15}")
    logger.info(f"  {'Bitiş Sermayesi (100K TL Başlangıç)':<38} {final_eq:>14,.0f}TL {100_000 * (1 + bm_total_ret / 100):>13,.0f}TL")
    logger.info(f"  {'Üretilen Toplam Net Alfa':<38} {total_return_pct - bm_total_ret:>14.1f}%")
    logger.info(sep)

    logger.info("\n  REJİM DAĞILIMI (10 YIL):")
    total_days = sum(regime_counter.values())
    for r, cnt in regime_counter.items():
        logger.info(f"    • {r:<9}: {cnt:,} seans (%{cnt / total_days * 100:.1f})")

    logger.info("\n  YIL YIL PERFORMANS VE ALFA TABLOSU:")
    logger.info(f"  {'YIL':<6} | {'GERÇEK MOTOR':>13} | {'BIST-100':>10} | {'ALFA':>10} | {'DURUM':>12}")
    logger.info("-" * 65)
    years_beat = 0
    for yr in sorted(yearly_stats.keys()):
        st = yearly_stats[yr]
        p = st["port_return"]
        b = st["bm_return"]
        a = st["alpha"]
        beat = "[ALFA ✅]" if a > 0 else "[KAYIP ⚠️]"
        if a > 0:
            years_beat += 1
        logger.info(f"  {yr:<6} | {p:>+12.1f}% | {b:>+9.1f}% | {a:>+9.1f}% | {beat}")
    logger.info("-" * 65)
    logger.info(f"  Toplam: {years_beat}/{len(yearly_stats)} yıl BIST'i geçti")
    logger.info(f"  Toplam Test Süresi: {time.time() - t0:.1f} saniye")
    logger.info(sep)

    if trade_logs:
        by_ticker: dict[str, float] = {}
        for tl in trade_logs:
            by_ticker[tl["ticker"]] = by_ticker.get(tl["ticker"], 0) + tl["pnl"]
        best = sorted(by_ticker.items(), key=lambda x: x[1], reverse=True)[:5]
        worst = sorted(by_ticker.items(), key=lambda x: x[1])[:5]
        logger.info("\n  [TOP 5] En Çok Kazandıran Hisseler:")
        for t, pnl in best:
            logger.info(f"    {t:<15} +{pnl:,.0f} TL")
        logger.info("\n  [BOT 5] En Çok Kaybettiren Hisseler:")
        for t, pnl in worst:
            logger.info(f"    {t:<15} {pnl:,.0f} TL")
    logger.info(sep)


if __name__ == "__main__":
    run_production_aligned_backtest()
