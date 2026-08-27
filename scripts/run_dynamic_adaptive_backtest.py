"""
ALPHA BIST — 100% Dinamik, Sıfır Statik Veri ve 3 Aşamalı OOS Doğrulama Simülasyonu
=================================================================================
1. SIFIR STATİK VERİ: Mum ağırlıkları ve formasyon katsayıları sabit değil; her hisse için
   kayan pencerede (Rolling Window) son 252 günlük ampirik başarıya göre anlık hesaplanır.
2. SIFIR LOOK-AHEAD: Sinyal $t$ günü kapanışında teyit edilir, alım/satım emri $t+1$ günü
   AÇILIŞ (Next-Bar Open) fiyatından komisyon (%0.15) ve kayma (%0.10) ile icra edilir.
3. SIFIR SUNİ FAİZ: Nakitteki paraya faiz/repo yazılmaz; saf hisse alfasını ölçer.
4. KATI 3 AŞAMALI DOĞRULAMA (OOS):
   - In-Sample (1997 - 2018): 21 Yıl
   - Out-of-Sample 1 (2019 - 2023): 5 Yıl (Validasyon)
   - Out-of-Sample 2 (2024 - 2026): 2.5 Yıl (Tam Bağımsız Kör Seanslar)
"""

import os
import sys
import warnings

import numpy as np
import polars as pl

warnings.filterwarnings("ignore")

sys.path.insert(0, os.path.abspath("."))
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

from services.intelligence.candle_patterns import candle_engine
from services.intelligence.dynamic_candle_matrix import dynamic_candle_matrix
from services.intelligence.trend_rider import trend_rider

BIST_CORE_STOCKS = [
    "THYAO.IS",
    "GARAN.IS",
    "AKBNK.IS",
    "ISCTR.IS",
    "YKBNK.IS",
    "KCHOL.IS",
    "SAHOL.IS",
    "TUPRS.IS",
    "EREGL.IS",
    "SISE.IS",
    "ARCLK.IS",
    "FROTO.IS",
    "TOASO.IS",
    "ENKAI.IS",
    "PETKM.IS",
    "CCOLA.IS",
    "AEFES.IS",
    "TCELL.IS",
    "VAKBN.IS",
    "HALKB.IS",
    "BIMAS.IS",
    "ASELS.IS",
    "PGSUS.IS",
    "TTKOM.IS",
    "MGROS.IS",
]

BENCHMARK_TICKER = "XU100.IS"


from services.data.historical_warehouse import historical_warehouse


def load_bist_historical_data():
    """30 yıllık gerçek BIST verilerini yerel disk deposundan 0.3 saniyede yükler."""
    print("=" * 90)
    print("1. BIST-100 & LOKOMOTİF HİSSE VERİLERİ YEREL DİSKTEN YÜKLENİYOR (1997 - 2026)")
    print("=" * 90)

    bm_df, stock_dict = historical_warehouse.load_30y_data()

    print(
        f"✓ BIST-100: {len(bm_df)} seans günü ({bm_df.index[0].strftime('%Y-%m-%d')} -> {bm_df.index[-1].strftime('%Y-%m-%d')})"
    )
    print(f"✓ {len(stock_dict)} hissenin 30 yıllık eksiksiz verisi hazırlandı.")

    print("  • Mum formasyonları hafızaya önbellekleniyor (Mikrosaniye hızlı simülasyon)...")
    for ticker, df_t in stock_dict.items():
        dynamic_candle_matrix.precompute_stock_patterns(ticker, df_t)
    print("    ✓ Tüm formasyon olayları hafızaya alındı.\n")

    return bm_df, stock_dict


def run_stage_simulation(
    stage_name: str,
    start_year: int,
    end_year: int,
    bm_df: pl.DataFrame,
    stock_dict: dict[str, pl.DataFrame],
    initial_capital: float = 100000.0,
):
    """Belirli bir zaman dilimi için Next-Bar Open icralı dinamik simülasyon koşturur."""
    print(f"\n>> {stage_name} ({start_year} - {end_year}) SİMÜLASYONU BAŞLATILIYOR...")

    COMMISSION_RATE = 0.0015
    SLIPPAGE_RATE = 0.0010

    # Filtrelenmiş tarih aralığı
    trading_dates = [d for d in bm_df.index if start_year <= d.year <= end_year]
    if len(trading_dates) < 30:
        return None

    capital = initial_capital
    positions = {}
    pending_buy_orders = []  # Next-bar Open icrası için bekleyen emirler
    pending_sell_orders = []
    equity_history = []
    benchmark_history = []
    trade_logs = []
    yearly_stats = {}

    bm_start_idx = bm_df.index.get_loc(trading_dates[0])
    bm_initial_price = float(bm_df["Close"].iloc[bm_start_idx])

    current_year = trading_dates[0].year
    year_start_equity = capital
    year_start_bm = bm_initial_price

    for day_idx in range(len(trading_dates)):
        current_date = trading_dates[day_idx]
        global_day_idx = bm_df.index.get_loc(current_date)
        year = current_date.year

        # Yıl geçişi
        if year != current_year:
            year_ret = ((capital - year_start_equity) / year_start_equity) * 100
            bm_curr_p = float(bm_df["Close"].loc[current_date])
            bm_ret = ((bm_curr_p - year_start_bm) / year_start_bm) * 100
            yearly_stats[current_year] = {"engine_ret": year_ret, "bm_ret": bm_ret, "alpha": year_ret - bm_ret}
            current_year = year
            year_start_equity = capital
            year_start_bm = bm_curr_p

        # =============================================================
        # 1. NEXT-BAR OPEN İCRASI (Dün Kapanışta Verilen Emirlerin İcrası)
        # =============================================================

        # A) Bekleyen Satış Emirlerinin İcrası ($t+1$ Open)
        for sell_ord in pending_sell_orders:
            t = sell_ord["ticker"]
            if t in positions:
                s_df = stock_dict.get(t)
                if s_df is not None and current_date in s_df.index:
                    open_p = float(s_df.loc[current_date]["Open"])
                    exit_p = open_p * (1 - SLIPPAGE_RATE)
                    pos = positions[t]

                    pnl_raw = (exit_p - pos["entry_price"]) * pos["shares"]
                    fee = (pos["entry_price"] + exit_p) * pos["shares"] * COMMISSION_RATE
                    net_pnl = pnl_raw - fee
                    capital += (exit_p * pos["shares"]) - (exit_p * pos["shares"] * COMMISSION_RATE)

                    ret_pct = ((exit_p - pos["entry_price"]) / pos["entry_price"]) * 100
                    trade_logs.append(
                        {
                            "ticker": t,
                            "pnl": net_pnl,
                            "ret_pct": ret_pct,
                            "reason": sell_ord["reason"],
                            "date": current_date,
                        }
                    )
                    positions.pop(t, None)
        pending_sell_orders = []

        # B) Bekleyen Alış Emirlerinin İcrası ($t+1$ Open)
        for buy_ord in pending_buy_orders:
            t = buy_ord["ticker"]
            if t not in positions:
                s_df = stock_dict.get(t)
                if s_df is not None and current_date in s_df.index:
                    open_p = float(s_df.loc[current_date]["Open"])
                    entry_p = open_p * (1 + SLIPPAGE_RATE)
                    cost_with_fee = entry_p * (1 + COMMISSION_RATE)

                    invest_amount = buy_ord["amount"]
                    shares = int(invest_amount / cost_with_fee)

                    if shares > 0 and capital >= (shares * cost_with_fee):
                        total_cost = shares * entry_p * (1 + COMMISSION_RATE)
                        capital -= total_cost
                        positions[t] = {
                            "shares": shares,
                            "entry_price": entry_p,
                            "peak_price": entry_p,
                            "stop_loss": entry_p * 0.93,
                            "entry_date": current_date,
                        }
        pending_buy_orders = []

        # =============================================================
        # 2. GÜN İÇİ DEĞERLENDİRME & SİNYAL ÜRETİMİ (Günün Kapanışında)
        # =============================================================

        # Rejim Kontrolü (XU100 50-SMA ve 200-SMA)
        bm_closes_sub = bm_df["Close"].iloc[max(0, global_day_idx - 200) : global_day_idx + 1].values
        bm_now = float(bm_closes_sub[-1])
        bm_sma50 = float(np.mean(bm_closes_sub[-50:])) if len(bm_closes_sub) >= 50 else bm_now
        bm_sma200 = float(np.mean(bm_closes_sub[-200:])) if len(bm_closes_sub) >= 200 else bm_sma50
        is_bull_regime = bm_now >= bm_sma50
        is_bear_crash = bm_now < bm_sma200 * 0.95

        # 1. Mevcut Pozisyonların Dinamik Değerlendirilmesi (Trend Rider)
        for ticker, pos in positions.items():
            s_df = stock_dict.get(ticker)
            if s_df is None or current_date not in s_df.index:
                continue

            s_candle = s_df.loc[current_date]
            s_hist = s_df.loc[:current_date]

            should_exit, _, exit_reason = trend_rider.evaluate_position_exit(pos, s_candle, s_hist, is_bear_crash)

            if should_exit:
                # Yarın sabah açılışta satılmak üzere emir kuyruğuna ekle
                pending_sell_orders.append({"ticker": ticker, "reason": exit_reason})

        # 2. Dinamik Kayan Mum Matrisi ile Yeni Alım Sinyalleri Taraması
        max_positions = 10 if is_bull_regime else 3
        active_and_pending_count = len(positions) + len(pending_buy_orders) - len(pending_sell_orders)

        if active_and_pending_count < max_positions:
            candidates = []
            for ticker in BIST_CORE_STOCKS:
                if ticker in positions or any(o["ticker"] == ticker for o in pending_buy_orders):
                    continue
                s_df = stock_dict.get(ticker)
                if s_df is None:
                    continue
                s_hist = s_df.loc[:current_date].dropna()
                if len(s_hist) < 40:
                    continue

                # Kayan pencerede bu formasyonun son dönemdeki gerçek performansı
                loc_idx = s_df.index.get_loc(current_date)
                rolling_edges = dynamic_candle_matrix.evaluate_rolling_edge(ticker, loc_idx, forward_days=5)

                c_res = candle_engine.analyze_dataframe(s_hist.iloc[-30:], ticker)
                float(s_hist["Close"].iloc[-1])
                vol_now = float(s_hist["Volume"].iloc[-1])
                if vol_now < 5_000:
                    continue

                # Dinamik Ağırlıklı Skor Hesabı
                dynamic_pattern_boost = 0.0
                for pat in c_res.patterns_detected:
                    edge = rolling_edges.get(pat)
                    if edge and edge.is_favorable:
                        dynamic_pattern_boost += edge.dynamic_weight * 10.0

                total_dyn_score = c_res.candle_score + dynamic_pattern_boost

                # Alım Kriteri: Dinamik olarak kazandıran mumlar ve alıcı baskısı
                if total_dyn_score >= 70.0 and c_res.buyer_pressure_pct >= 52:
                    candidates.append({"ticker": ticker, "score": total_dyn_score})

            # Skoruna göre sırala ve yarın sabah alım emri hazırla
            candidates.sort(key=lambda x: x["score"], reverse=True)
            slots_available = max_positions - active_and_pending_count
            for cand in candidates[:slots_available]:
                total_port = capital + sum(p["shares"] * p["entry_price"] for p in positions.values())
                alloc_ratio = 0.10 if is_bull_regime else 0.05
                invest_amount = min(capital * 0.90, total_port * alloc_ratio)
                if invest_amount > 100:
                    pending_buy_orders.append({"ticker": cand["ticker"], "amount": invest_amount})

        # Portföy anlık değeri
        pos_val = 0.0
        for t, pos in positions.items():
            s_df = stock_dict.get(t)
            if s_df is not None and current_date in s_df.index:
                pos_val += pos["shares"] * float(s_df.loc[current_date]["Close"])
            else:
                pos_val += pos["shares"] * pos["entry_price"]

        total_equity = capital + pos_val
        equity_history.append({"date": current_date, "equity": total_equity})

        bm_price_now = float(bm_df["Close"].loc[current_date])
        bm_equity_now = (initial_capital / bm_initial_price) * bm_price_now
        benchmark_history.append({"date": current_date, "bm_equity": bm_equity_now})

    # Sonuçların Hesaplanması
    final_equity = equity_history[-1]["equity"]
    total_engine_ret = ((final_equity - initial_capital) / initial_capital) * 100
    final_bm = benchmark_history[-1]["bm_equity"]
    total_bm_ret = ((final_bm - initial_capital) / initial_capital) * 100

    df_eq = pl.DataFrame(equity_history)
    df_eq["peak"] = df_eq["equity"].cummax()
    df_eq["drawdown"] = (df_eq["equity"] - df_eq["peak"]) / df_eq["peak"] * 100
    max_dd_engine = df_eq["drawdown"].min()

    df_bm = pl.DataFrame(benchmark_history)
    df_bm["peak"] = df_bm["bm_equity"].cummax()
    df_bm["drawdown"] = (df_bm["bm_equity"] - df_bm["peak"]) / df_bm["peak"] * 100
    max_dd_bm = df_bm["drawdown"].min()

    df_trades = pl.DataFrame(trade_logs)
    total_trades = len(df_trades)
    win_trades = len(df_trades[df_trades["pnl"] > 0]) if total_trades > 0 else 0
    win_rate = (win_trades / total_trades * 100) if total_trades > 0 else 0
    wins = df_trades[df_trades["pnl"] > 0]["pnl"].sum() if total_trades > 0 else 0
    losses = abs(df_trades[df_trades["pnl"] < 0]["pnl"].sum()) if total_trades > 0 else 1
    pf = round(wins / max(losses, 1e-9), 2)
    mega_winners = df_trades[df_trades["ret_pct"] >= 50] if total_trades > 0 else []

    print("-" * 80)
    print(f"📊 {stage_name} SONUÇLARI:")
    print(f"  • Nihai Portföy Değeri  : {final_equity:,.0f} ₺ (Başlangıç: {initial_capital:,.0f} ₺)")
    print(f"  • Motor Toplam Getirisi : %{total_engine_ret:+,.1f} | BIST-100: %{total_bm_ret:+,.1f}")
    print(f"  • Net Alfa (Üstünlük)   : %{total_engine_ret - total_bm_ret:+,.1f}")
    print(f"  • Maksimum Düşüş (DD)   : %{max_dd_engine:.2f} (BIST-100: %{max_dd_bm:.2f})")
    print(f"  • Toplam İşlem Sayısı   : {total_trades} Adet (Kazanma Oranı: %{win_rate:.1f}, PF: {pf})")
    print(f"  • +%50 Üzeri Mega Trend : {len(mega_winners)} Adet İşlem")
    print("-" * 80)

    return {
        "stage": stage_name,
        "final_equity": final_equity,
        "engine_ret": total_engine_ret,
        "bm_ret": total_bm_ret,
        "alpha": total_engine_ret - total_bm_ret,
        "max_dd_engine": max_dd_engine,
        "max_dd_bm": max_dd_bm,
        "win_rate": win_rate,
        "pf": pf,
        "trades": total_trades,
        "mega_trends": len(mega_winners),
    }


def main():
    bm_df, stock_dict = load_bist_historical_data()

    print("=" * 90)
    print("🏆 KATI 3 AŞAMALI DIŞ ÖRNEKLEM (OUT-OF-SAMPLE) VE DİNAMİK ZEKÂ TESTİ")
    print("=" * 90)

    # 1. Aşama: In-Sample (1997 - 2018 / 21 Yıl)
    r1 = run_stage_simulation("AŞAMA 1: IN-SAMPLE EĞİTİM & GELİŞTİRME", 1997, 2018, bm_df, stock_dict, 100000.0)

    # 2. Aşama: Out-of-Sample 1 (2019 - 2023 / 5 Yıl Validasyon)
    r2 = run_stage_simulation("AŞAMA 2: OUT-OF-SAMPLE 1 (VALİDASYON)", 2019, 2023, bm_df, stock_dict, 100000.0)

    # 3. Aşama: Out-of-Sample 2 (2024 - 2026 / 2.5 Yıl Bağımsız Kör Seanslar)
    r3 = run_stage_simulation(
        "AŞAMA 3: OUT-OF-SAMPLE 2 (BAĞIMSIZ KÖR CANLI DÖNEM)", 2024, 2026, bm_df, stock_dict, 100000.0
    )

    print("\n" + "=" * 90)
    print("📈 3 AŞAMALI KURUMSAL DOĞRULAMA ÖZETİ")
    print("=" * 90)
    print(f"{'AŞAMA / DÖNEM':<42} | {'MOTOR GETİRİ':<14} | {'BIST-100':<12} | {'NET ALFA':<12} | {'MAX DD'}")
    print("-" * 90)
    for r in [r1, r2, r3]:
        if r:
            print(
                f"{r['stage']:<42} | %{r['engine_ret']:>+11.1f} | %{r['bm_ret']:>+9.1f} | %{r['alpha']:>+9.1f} | %{r['max_dd_engine']:>.2f}"
            )
    print("=" * 90)


if __name__ == "__main__":
    main()
