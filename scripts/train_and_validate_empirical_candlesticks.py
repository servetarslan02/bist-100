import structlog

logger = structlog.get_logger(__name__)
from typing import Any

"""
ALPHA BIST — Mum Formasyonları Ampirik Eğitim & Trend Rider 30 Yıllık Testi
==========================================================================
1. 12 Japon Mumunun BIST Tarihsel Başarı / Zarar Karnesini Çıkarır (Empirical Edge).
2. Yapay Zeka Modelini (LightGBM) bu özelliklerle eğitir ve ağırlıklarını çıkarır.
3. 30 Yıllık Gerçek BIST Verisi üzerinde Sıfır Suni Faiz ile Trend Rider motorunu test eder.
"""

import os
import sys
import warnings

import lightgbm as lgb
import numpy as np
import polars as pl
import yfinance as yf

warnings.filterwarnings("ignore")

sys.path.insert(0, os.path.abspath("."))
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

from services.intelligence.candle_patterns import candle_engine
from services.intelligence.trend_rider import trend_rider
from services.ml.candle_feature_engineer import candle_feature_engineer

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


def main() -> Any:
    """Otomatik eklendi."""
    logger.info("=" * 85)
    logger.info("1. BIST-100 GEÇMİŞ VERİLERİ İNDİRİLİYOR (1997 - 2026)")
    logger.info("=" * 85)

    bm_df = yf.download(BENCHMARK_TICKER, start="1997-01-01", end="2026-08-23", progress=False)
    if isinstance(bm_df.columns, list):
        bm_df.columns = [c[0] for c in bm_df.columns]

    stocks_raw = yf.download(BIST_CORE_STOCKS, start="1997-01-01", end="2026-08-23", progress=False, group_by="ticker")
    stock_dict = {}
    for ticker in BIST_CORE_STOCKS:
        if ticker in stocks_raw.columns.get_level_values(0):
            df_t = stocks_raw[ticker].dropna()
            if isinstance(df_t.columns, list):
                df_t.columns = [c[0] for c in df_t.columns]
            if len(df_t) > 50:
                stock_dict[ticker] = df_t

    logger.info(f"✓ {len(stock_dict)} hissenin 30 yıllık günlük mumları başarıyla yüklendi.\n")

    # -------------------------------------------------------------
    # 2. Mum Formasyonları BIST Ampirik Başarı Karnesi
    # -------------------------------------------------------------
    logger.info("=" * 85)
    logger.info("2. JAPON MUM FORMASYONLARI BIST GERÇEK KAZANÇ / KAYIP KARNESİ")
    logger.info("=" * 85)
    logger.info("BIST-100 hisselerinin tüm tarihsel seansları taranarak 10 günlük ileri getiri hesaplandı:\n")

    edge_table = candle_feature_engineer.compute_empirical_edge_table(stock_dict, forward_days=10)

    if not edge_table.empty:
        cols_to_print = [
            "Formasyon",
            "BIST Örneklem Sayısı",
            "Kazanma Oranı (Win Rate)",
            "Ort. 10G Getiri %",
            "Kâr / Zarar Çarpanı (PF)",
            "Beklenen Değer (Expectancy %)",
            "Model Öneri Derecesi",
        ]
        logger.info(edge_table[cols_to_print].to_string(index=False))
    logger.info("-" * 85)

    # -------------------------------------------------------------
    # 3. Yapay Zeka (LightGBM) Modelinin Mum Özellikleriyle Eğitimi
    # -------------------------------------------------------------
    logger.info("\n" + "=" * 85)
    logger.info("3. YAPAY ZEKA (LIGHTGBM) MODELİNİN MUM VE PRICE ACTION ZEKASIYLA EĞİTİLMESİ")
    logger.info("=" * 85)

    X_list, y_list = [], []
    feature_names = [
        "feat_buyer_pressure",
        "feat_candle_score",
        "feat_has_bull_engulfing",
        "feat_has_hammer",
        "feat_has_morning_star",
        "feat_has_soldiers",
        "feat_has_fvg",
        "feat_has_shooting_star",
        "feat_has_crows",
    ]

    for ticker, df in stock_dict.items():
        df_f = candle_feature_engineer.extract_features_for_dataframe(df, ticker)
        closes = df_f["Close"].values
        for i in range(50, len(df_f) - 10):
            row_feat = [df_f[col].iloc[i] for col in feature_names]
            # Hedef: 10 gün sonraki getiri %5'in üzerindeyse pozitif (1), değilse (0)
            p_now = float(closes[i])
            p_fwd = float(closes[i + 10])
            label = 1 if (p_fwd - p_now) / p_now >= 0.04 else 0

            X_list.append(row_feat)
            y_list.append(label)

    X_mat = np.array(X_list)
    y_vec = np.array(y_list)

    train_ds = lgb.Dataset(X_mat, label=y_vec, feature_name=feature_names)
    params = {
        "objective": "binary",
        "metric": "auc",
        "boosting_type": "gbdt",
        "learning_rate": 0.05,
        "num_leaves": 31,
        "verbose": -1,
    }
    model = lgb.train(params, train_ds, num_boost_round=100)

    # Özellik Ağırlıkları (Feature Importance)
    imp = model.feature_importance(importance_type="gain")
    df_imp = pl.DataFrame({"Özellik (Mum/Price Action)": feature_names, "Öğrenilen Model Ağırlığı (Gain)": imp})
    df_imp = df_imp.sort(by="Öğrenilen Model Ağırlığı (Gain)", reverse=True)

    logger.info("🧠 Model Tarafından Öğrenilen Mum Özellik Ağırlıkları (Feature Importance):")
    logger.info(df_imp.to_string(index=False))
    logger.info("✓ Model eğitimi başarıyla tamamlandı!\n")

    # -------------------------------------------------------------
    # 4. 30 Yıllık Saf Hisse Trend Rider Simülasyonu (Sıfır Faiz)
    # -------------------------------------------------------------
    logger.info("=" * 85)
    logger.info("4. TREND RIDER & SAF HİSSE 30 YILLIK KURUMSAL BACKTEST (SIFIR YAPAY FAİZ)")
    logger.info("=" * 85)
    logger.info("  • Başlangıç Sermayesi       : 100.000 ₺")
    logger.info("  • İşlem Maliyeti (Komisyon) : %0.15 Alış + %0.15 Satış")
    logger.info("  • Fiyat Kayması (Slippage)  : %0.10 Alış + %0.10 Satış (Toplam %0.50 Round-Trip)")
    logger.info("  • Tavan & Mega Trend Kuralı : Erken kâr kesilmez, 9-EMA ve tepe dönüş mumuna kadar sürülür.")
    logger.info("  • Nakit Geliri              : %0.0 (Sıfır Faiz/Repo — Saf Hisse Alfasını Ölçmek İçin)")
    logger.info("-" * 85)

    COMMISSION_RATE = 0.0015
    SLIPPAGE_RATE = 0.0010

    trading_dates = list(bm_df.index)
    capital = 100000.0
    initial_capital = capital
    positions = {}
    equity_history = []
    benchmark_history = []
    trade_logs = []
    yearly_stats = {}

    bm_initial_price = float(bm_df["Close"].iloc[0])
    current_year = trading_dates[50].year
    year_start_equity = capital
    year_start_bm = float(bm_df["Close"].iloc[50])

    for day_idx in range(50, len(trading_dates)):
        current_date = trading_dates[day_idx]
        year = current_date.year

        if year != current_year:
            year_ret_pct = ((capital - year_start_equity) / year_start_equity) * 100
            bm_year_price = float(bm_df["Close"].iloc[day_idx - 1])
            bm_ret_pct = ((bm_year_price - year_start_bm) / year_start_bm) * 100

            yearly_stats[current_year] = {
                "engine_ret": year_ret_pct,
                "bm_ret": bm_ret_pct,
                "alpha": year_ret_pct - bm_ret_pct,
            }
            current_year = year
            year_start_equity = capital
            year_start_bm = float(bm_df["Close"].iloc[day_idx])

        # Rejim
        bm_closes = bm_df["Close"].iloc[max(0, day_idx - 200) : day_idx + 1].values
        bm_now = float(bm_closes[-1])
        bm_sma50 = float(np.mean(bm_closes[-50:])) if len(bm_closes) >= 50 else bm_now
        bm_sma200 = float(np.mean(bm_closes[-200:])) if len(bm_closes) >= 200 else bm_sma50
        is_bull_regime = bm_now >= bm_sma50
        is_bear_crash = bm_now < bm_sma200 * 0.95

        # 1. Trend Rider ile Pozisyon Yönetimi
        closed_tickers = []
        for ticker, pos in positions.items():
            s_df = stock_dict.get(ticker)
            if s_df is None or current_date not in s_df.index:
                continue

            s_candle = s_df.loc[current_date]
            s_hist = s_df.loc[:current_date]

            should_exit, exit_price, exit_reason = trend_rider.evaluate_position_exit(
                pos, s_candle, s_hist, is_bear_crash
            )

            if should_exit:
                p_real_exit = exit_price * (1 - SLIPPAGE_RATE)
                pnl_raw = (p_real_exit - pos["entry_price"]) * pos["shares"]
                fee = (pos["entry_price"] + p_real_exit) * pos["shares"] * COMMISSION_RATE
                net_pnl = pnl_raw - fee
                capital += (p_real_exit * pos["shares"]) - (p_real_exit * pos["shares"] * COMMISSION_RATE)

                ret_pct = ((p_real_exit - pos["entry_price"]) / pos["entry_price"]) * 100
                trade_logs.append(
                    {"ticker": ticker, "pnl": net_pnl, "ret_pct": ret_pct, "reason": exit_reason, "date": current_date}
                )
                closed_tickers.append(ticker)

        for t in closed_tickers:
            positions.pop(t, None)

        # 2. Yeni Sinyaller (Model Skoru & Trend Başlangıcı)
        max_positions = 10 if is_bull_regime else 3
        if len(positions) < max_positions:
            candidates = []
            for ticker in BIST_CORE_STOCKS:
                if ticker in positions:
                    continue
                s_df = stock_dict.get(ticker)
                if s_df is None:
                    continue
                s_hist = s_df.loc[:current_date].dropna()
                if len(s_hist) < 30:
                    continue

                c_res = candle_engine.analyze_dataframe(s_hist.iloc[-30:], ticker)
                p_now = float(s_hist["Close"].iloc[-1])
                vol_now = float(s_hist["Volume"].iloc[-1])
                if vol_now < 5_000:
                    continue

                # Model skoru & formasyon
                has_bull = any(
                    p in {"BULLISH_ENGULFING", "HAMMER_PINBAR", "MORNING_STAR", "THREE_WHITE_SOLDIERS", "BULLISH_FVG"}
                    for p in c_res.patterns_detected
                )
                if (has_bull or c_res.candle_score >= 65) and c_res.buyer_pressure_pct >= 52:
                    candidates.append(
                        {
                            "ticker": ticker,
                            "price": p_now,
                            "score": c_res.candle_score,
                        }
                    )

            candidates.sort(key=lambda x: x["score"], reverse=True)
            for cand in candidates[: max_positions - len(positions)]:
                total_port = capital + sum(p["shares"] * p["entry_price"] for p in positions.values())
                invest_amount = min(capital * 0.90, total_port * (0.10 if is_bull_regime else 0.05))
                if invest_amount > 100:
                    entry_p = cand["price"] * (1 + SLIPPAGE_RATE)
                    cost_with_fee = entry_p * (1 + COMMISSION_RATE)
                    shares = int(invest_amount / cost_with_fee)

                    if shares > 0:
                        total_cost = shares * entry_p * (1 + COMMISSION_RATE)
                        capital -= total_cost
                        positions[cand["ticker"]] = {
                            "shares": shares,
                            "entry_price": entry_p,
                            "peak_price": entry_p,
                            "stop_loss": entry_p * 0.93,
                            "entry_date": current_date,
                        }

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
        bm_equity_now = (100000.0 / bm_initial_price) * bm_price_now
        benchmark_history.append({"date": current_date, "bm_equity": bm_equity_now})

    # Sonuçlar
    final_equity = equity_history[-1]["equity"]
    total_engine_ret = ((final_equity - initial_capital) / initial_capital) * 100
    final_bm = benchmark_history[-1]["bm_equity"]
    total_bm_ret = ((final_bm - 100000.0) / 100000.0) * 100

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

    # Mega Trend İşlemleri (+%50 ve üzeri kârla kapatılanlar)
    mega_winners = df_trades[df_trades["ret_pct"] >= 50]
    best_trade = df_trades.sort(by="ret_pct", reverse=True).iloc[0] if total_trades > 0 else None

    logger.info("\n" + "=" * 85)
    logger.info("🏆 30 YILLIK SAF HİSSE & TREND RIDER KURUMSAL PERFORMANSI")
    logger.info("=" * 85)
    logger.info(f"{'METRİK':<38} | {'BIST-100 (Al ve Unut)':<20} | {'TREND RIDER MOTORU':<20}")
    logger.info("-" * 85)
    logger.info(f"{'Başlangıç Sermayesi':<38} | {'100.000 ₺':<20} | {'100.000 ₺':<20}")
    logger.info(f"{'Nihai Portföy Değeri (Net)':<38} | {f'{final_bm:,.0f} ₺':<20} | {f'{final_equity:,.0f} ₺':<20}")
    logger.info(f"{'Kümülatif Toplam Getiri':<38} | %{total_bm_ret:<19,.1f} | %{total_engine_ret:<19,.1f}")
    logger.info(f"{'Maksimum Çöküş / Düşüş (Max DD)':<38} | %{max_dd_bm:<19.2f} | %{max_dd_engine:<19.2f} (Kriz Zırhı)")
    logger.info(f"{'Toplam İşlem Sayısı':<38} | {'1 İşlem':<20} | {f'{total_trades} İşlem':<20}")
    logger.info(f"{'Kazanma Oranı (Win Rate)':<38} | {'—':<20} | %{win_rate:<19.1f}")
    logger.info(f"{'Kar / Zarar Çarpanı (Profit Factor)':<38} | {'—':<20} | {pf:<20}")
    logger.info(f"{'+%50 Üzeri Mega Trend İşlemleri':<38} | {'—':<20} | {len(mega_winners)} Adet Mega Trend")
    if best_trade is not None:
        logger.info(
            f"{'En Yüksek Tekil İşlem Kârı':<38} | {'—':<20} | {best_trade['ticker']} (+%{best_trade['ret_pct']:.1f})"
        )
    logger.info("=" * 85)


if __name__ == "__main__":
    main()
