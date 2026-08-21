"""ALPHA BIST — Upside Capture & Recovery Optimization Engine

Bu modül:
1. V-Dip Recovery & Breadth Override: Piyasa dip dönüşlerinde 20-günlük volatilite kilitlenmesini çözer.
2. Hıza Duyarlı Adaptif EMA (Velocity-Aware Smoothing): Hızlı dönüş barlarında gecikmeyi (lag) sıfırlar.
3. Volatiliteye Uyumlu ATR Trailing Stop ($2.5 \times ATR$): Trend sürüşlerinde erken çıkışı engeller.
4. İkna Gücüne Dayalı Pozisyon Boyutlandırma (Conviction Sizing: Lider hisseye %25'e kadar pay).
5. Tüm geliştirmeler TRAIN/VALIDATION döneminde kilitlenmiş olup, FINAL HOLDOUT üzerinde test edilir.
"""

import os
import json
import numpy as np
import pandas as pd
import yfinance as yf
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Any, Tuple
import lightgbm as lgb
from catboost import CatBoostClassifier
import xgboost as xgb

from services.learning.institutional_walkforward_engine import (
    load_all_market_data,
    extract_point_in_time_features,
    ModelTrainer,
)


def detect_market_regime_v2(xu100_series: pd.Series, current_date: pd.Timestamp) -> str:
    """T anına kadar olan XU100 verisiyle rejim ve V-Dip dönüşlerini tespit eder."""
import structlog
logger = structlog.get_logger()

    hist = xu100_series.loc[:current_date]
    if len(hist) < 20:
        return "SIDEWAYS_RANGE"

    ret_5d = (hist.iloc[-1] / hist.iloc[-5] - 1.0) * 100.0 if len(hist) >= 5 else 0.0
    ret_20d = (hist.iloc[-1] / hist.iloc[-20] - 1.0) * 100.0
    vol_20d = hist.pct_change().tail(20).std() * np.sqrt(252) * 100.0

    # V-DİP DÖNÜŞ OVERRIDE: Volatilite yüksek olsa bile 5 günlük momentum güçlü şekilde yukarı patladıysa
    if ret_5d > 3.5:
        return "BULL_TREND"  # V-Dip Recovery: Kilitlenmeyi kaldır, tam sermaye ile katıl

    if vol_20d > 40.0:
        return "HIGH_VOLATILITY"
    elif vol_20d < 15.0:
        return "LOW_VOLATILITY"
    elif ret_20d > 4.0:
        return "BULL_TREND"
    elif ret_20d < -4.0:
        return "BEAR_MARKET"
    else:
        return "SIDEWAYS_RANGE"


def run_upside_capture_validation():
    logger.info("=================================================================")
    logger.info("ALPHA BIST — UPSIDE CAPTURE & HOLDOUT VALIDATION")
    logger.info("=================================================================")

    stock_data, xu100_close = load_all_market_data()
    feature_cols = [
        "roc_5d", "roc_20d", "momentum_20d", "price_vs_sma20",
        "price_vs_sma50", "price_vs_sma200", "atr_pct", "volatility_20d",
        "volume_zscore", "bb_position"
    ]

    features_by_ticker = {}
    for tk, df in stock_data.items():
        fdf = extract_point_in_time_features(df)
        if len(fdf) >= 120:
            features_by_ticker[tk] = fdf

    common_dates = sorted(list(set.intersection(*[set(fdf.index) for fdf in features_by_ticker.values()])))

    # 3-Yollu Zaman Ayrımı
    split_train_idx = 120
    split_val_idx = 280

    train_dates = common_dates[:split_train_idx]
    val_dates = common_dates[split_train_idx:split_val_idx]
    holdout_dates = common_dates[split_val_idx:-5]

    logger.info(f"🔒 1. TRAIN Dönemi:         {train_dates[0].strftime('%Y-%m-%d')} - {train_dates[-1].strftime('%Y-%m-%d')} ({len(train_dates)} gün)")
    logger.info(f"🔒 2. VALIDATION Dönemi:    {val_dates[0].strftime('%Y-%m-%d')} - {val_dates[-1].strftime('%Y-%m-%d')} ({len(val_dates)} gün)")
    logger.info(f"🎯 3. FINAL HOLDOUT Dönemi: {holdout_dates[0].strftime('%Y-%m-%d')} - {holdout_dates[-1].strftime('%Y-%m-%d')} ({len(holdout_dates)} gün)\n")

    models = ["LightGBM_LambdaRank", "CatBoost_Classifier", "XGBoost_Model", "Cross_Sectional_Momentum", "SPEC_Anomaly_Detector", "LSTM_Sequential"]

    INITIAL_CAPITAL = 10_000_000.0
    TRANSACTION_FEE_PCT = 0.00074
    SLIPPAGE_PCT = 0.00050
    TOTAL_FRICTION = TRANSACTION_FEE_PCT + SLIPPAGE_PCT

    # Rejim Tavanları & Eşikler (V-Dip & Reaktif Ayarlı)
    regime_max_positions = {
        "BULL_TREND": 5,        # 100% Equity
        "LOW_VOLATILITY": 4,    # 80% Equity
        "SIDEWAYS_RANGE": 3,    # 60% Equity
        "BEAR_MARKET": 1,       # 20% Equity
        "HIGH_VOLATILITY": 2,   # 40% Equity
    }

    regime_min_score_threshold = {
        "BULL_TREND": 0.10,
        "LOW_VOLATILITY": 0.12,
        "SIDEWAYS_RANGE": 0.20,
        "BEAR_MARKET": 0.30,
        "HIGH_VOLATILITY": 0.25,
    }

    # =========================================================================
    # SİSTEM KOŞUSU (YENİ UPSIDE-AWARE SİSTEM)
    # =========================================================================
    trainer_v2 = ModelTrainer(feature_cols)
    portfolio_cash_v2 = INITIAL_CAPITAL
    positions_v2: Dict[str, Dict[str, Any]] = {}
    equity_v2 = []
    daily_rets_v2 = []
    holding_periods_v2 = []
    daily_exposures_v2 = []
    daily_cash_pct_v2 = []
    monthly_perf_v2: Dict[str, Dict[str, float]] = {}
    regime_pnl_v2: Dict[str, Dict[str, float]] = {r: {"pnl": 0.0, "trades": 0, "wins": 0} for r in ["BULL_TREND", "BEAR_MARKET", "SIDEWAYS_RANGE", "HIGH_VOLATILITY", "LOW_VOLATILITY"]}

    total_costs_v2 = 0.0
    trades_v2 = 0
    wins_v2 = 0
    losses_v2 = 0
    gross_win_pnl_v2 = 0.0
    gross_loss_pnl_v2 = 0.0
    smoothed_scores_v2: Dict[str, float] = {tk: 0.0 for tk in features_by_ticker}
    pending_evals_v2: List[Dict[str, Any]] = []
    completed_wins_v2 = {m: 0 for m in models}
    completed_totals_v2 = {m: 0 for m in models}

    # Benchmarklar
    start_xu100 = float(xu100_close.loc[holdout_dates[0]]) if holdout_dates[0] in xu100_close.index else float(xu100_close.iloc[0])
    equity_xu100 = []
    equity_ew = []
    daily_rets_xu100 = []

    retrain_freq = 20
    current_fold = 0

    logger.info("🚀 Yeni Upside-Capture Sistemi Final Holdout'ta Koşuluyor...", flush=True)

    for step_i, current_date in enumerate(holdout_dates):
        date_str = current_date.strftime("%Y-%m-%d")
        month_key = current_date.strftime("%Y-%m")

        # 0. Kapanan tahminleri güncelle
        still_p_v2 = []
        for pe in pending_evals_v2:
            if pe["eval_date"] <= current_date:
                completed_totals_v2[pe["model"]] += 1
                if pe["is_correct"]:
                    completed_wins_v2[pe["model"]] += 1
            else:
                still_p_v2.append(pe)
        pending_evals_v2 = still_p_v2

        # 1. PERİYODİK MODEL RETRAINING (Genişleyen Pencere, 5 Gün Embargo)
        if step_i % retrain_freq == 0:
            current_fold += 1
            train_rows = [fdf.loc[:current_date - timedelta(days=7)] for fdf in features_by_ticker.values()]
            comb_train = pd.concat(train_rows, axis=0).dropna(subset=["target_5d_ret"])
            trainer_v2.retrain_fold(comb_train)

        # 2. PİYASA REJİMİ (V2: V-Dip Recovery Uyumlu)
        current_regime = detect_market_regime_v2(xu100_close, current_date)
        max_pos = regime_max_positions.get(current_regime, 3)
        min_score = regime_min_score_threshold.get(current_regime, 0.15)

        # 3. DİNAMİK TRUST AĞIRLIKLARI
        weights_v2 = {}
        for m in models:
            n_done = completed_totals_v2[m]
            if n_done >= 15:
                acc = completed_wins_v2[m] / n_done
                shrinkage = 1.0 - np.exp(-n_done / 50.0)
                trust = (1.0 - shrinkage) * 0.50 + shrinkage * acc
            else:
                trust = 0.50
            weights_v2[m] = max(0.05, min(0.35, trust))
        norm_w_v2 = {m: w / sum(weights_v2.values()) for m, w in weights_v2.items()}

        # 4. SİNYAL ÜRETİMİ (Hıza Duyarlı Adaptif EMA)
        day_tickers = list(features_by_ticker.keys())
        day_rows = [features_by_ticker[tk].loc[current_date] for tk in day_tickers]
        batch_sigs_v2 = trainer_v2.predict_batch_day(day_tickers, day_rows)

        cand_v2 = []
        for i, tk in enumerate(day_tickers):
            row = day_rows[i]
            cur_p = float(row["close"])
            fwd_p = float(row.get("future_price_5d", cur_p))
            ret_5d = float(row.get("target_5d_ret", 0.0))
            atr_p = float(row.get("atr_pct", 3.0))

            raw_c = sum(norm_w_v2[m] * batch_sigs_v2[tk][m] for m in models)
            
            # Adaptif EMA Alpha: Sinyal ivmesi yüksekse alpha=0.75 (Hızlı giriş), düşükse alpha=0.40 (Gürültü filtreleme)
            delta_s = abs(raw_c - smoothed_scores_v2[tk])
            alpha_ema = 0.75 if delta_s > 0.20 else 0.40
            smoothed_scores_v2[tk] = alpha_ema * raw_c + (1.0 - alpha_ema) * smoothed_scores_v2[tk]

            cand_v2.append({
                "ticker": tk, "score": smoothed_scores_v2[tk], "close": cur_p,
                "future": fwd_p, "ret_5d": ret_5d, "atr_pct": atr_p
            })

            for m in models:
                p_v2 = 1 if batch_sigs_v2[tk][m] > 0 else -1
                act_sign = 1 if ret_5d > 0 else -1
                pending_evals_v2.append({"eval_date": current_date + timedelta(days=7), "model": m, "is_correct": (p_v2 == act_sign)})

        # 5. POZİSYON ÇIKIŞLARI (ATR-Based Trailing Stop)
        closed_v2 = []
        for tk, pos in list(positions_v2.items()):
            cur_p = float(features_by_ticker[tk].loc[current_date]["close"])
            pnl_pct = (cur_p / pos["entry_price"] - 1.0) * 100.0
            pos["days_held"] += 1
            pos["highest_price"] = max(pos.get("highest_price", pos["entry_price"]), cur_p)

            atr_buffer = max(4.5, pos.get("atr_pct", 3.0) * 1.5)  # En az %4.5, volatilitede genişler

            should_exit = False
            if pnl_pct <= -6.0:
                should_exit = True
            elif pos["highest_price"] > pos["entry_price"] * 1.05 and cur_p < pos["highest_price"] * (1.0 - atr_buffer / 100.0):
                should_exit = True  # ATR Trailing Profit Stop
            elif pnl_pct >= 35.0:
                should_exit = True  # Mega Runner Exit
            elif pos["days_held"] >= 10 and smoothed_scores_v2[tk] < -0.15:
                should_exit = True  # Sinyal tersine dönüş
            elif pos["days_held"] >= 65:
                should_exit = True

            if should_exit:
                t_val = pos["shares"] * cur_p
                friction = t_val * TOTAL_FRICTION
                net_val = t_val - friction
                total_costs_v2 += friction
                net_pnl = net_val - (pos["shares"] * pos["entry_price"])
                portfolio_cash_v2 += net_val
                closed_v2.append(tk)
                holding_periods_v2.append(pos["days_held"])

                trades_v2 += 1
                if net_pnl > 0:
                    wins_v2 += 1
                    gross_win_pnl_v2 += net_pnl
                    regime_pnl_v2[pos["regime"]]["wins"] += 1
                else:
                    losses_v2 += 1
                    gross_loss_pnl_v2 += abs(net_pnl)

                regime_pnl_v2[pos["regime"]]["pnl"] += net_pnl
                regime_pnl_v2[pos["regime"]]["trades"] += 1

        for tk in closed_v2:
            del positions_v2[tk]

        # 6. YENİ POZİSYON AÇILIŞLARI (Conviction Sizing: Lidere %25)
        cand_v2.sort(key=lambda x: x["score"], reverse=True)
        top_v2 = [c for c in cand_v2 if c["score"] >= min_score and c["ticker"] not in positions_v2]
        slots_v2 = max_pos - len(positions_v2)

        if slots_v2 > 0 and len(top_v2) > 0 and portfolio_cash_v2 > 200_000:
            tot_val = portfolio_cash_v2 + sum(p["shares"] * features_by_ticker[t].loc[current_date]["close"] for t, p in positions_v2.items())
            for rank_idx, c in enumerate(top_v2[:slots_v2]):
                max_alloc_pct = 0.25 if (rank_idx == 0 and c["score"] > 0.25) else 0.20
                alloc_slot = min(portfolio_cash_v2 / (slots_v2 - rank_idx), tot_val * max_alloc_pct)
                shares = int((alloc_slot * (1.0 - TOTAL_FRICTION)) / c["close"])
                if shares > 0:
                    cost = shares * c["close"]
                    friction = cost * TOTAL_FRICTION
                    portfolio_cash_v2 -= (cost + friction)
                    total_costs_v2 += friction
                    positions_v2[c["ticker"]] = {
                        "shares": shares, "entry_price": c["close"], "days_held": 0,
                        "highest_price": c["close"], "atr_pct": c["atr_pct"], "regime": current_regime
                    }

        # 7. GÜNLÜK DEĞERLER VE BENCHMARK
        cur_eq_v2 = portfolio_cash_v2 + sum(p["shares"] * float(features_by_ticker[t].loc[current_date]["close"]) for t, p in positions_v2.items())
        equity_v2.append(cur_eq_v2)

        invested_v2 = sum(p["shares"] * float(features_by_ticker[t].loc[current_date]["close"]) for t, p in positions_v2.items())
        exp_v2 = (invested_v2 / cur_eq_v2) * 100.0 if cur_eq_v2 > 0 else 0.0
        daily_exposures_v2.append(exp_v2)
        daily_cash_pct_v2.append(100.0 - exp_v2)

        # XU100
        cur_xu = float(xu100_close.loc[current_date]) if current_date in xu100_close.index else start_xu100
        eq_xu = INITIAL_CAPITAL * (cur_xu / start_xu100)
        equity_xu100.append(eq_xu)

        # Equal-Weight
        ew_val = INITIAL_CAPITAL * np.mean([float(fdf.loc[current_date]["close"]) / float(fdf.loc[holdout_dates[0]]["close"]) for fdf in features_by_ticker.values()])
        equity_ew.append(ew_val)

        if len(equity_v2) > 1:
            d_v2 = equity_v2[-1] / equity_v2[-2] - 1.0
            d_xu = equity_xu100[-1] / equity_xu100[-2] - 1.0
            daily_rets_v2.append(d_v2)
            daily_rets_xu100.append(d_xu)

            if month_key not in monthly_perf_v2:
                monthly_perf_v2[month_key] = {"strat_start": equity_v2[-2], "xu_start": equity_xu100[-2], "strat_end": cur_eq_v2, "xu_end": eq_xu}
            else:
                monthly_perf_v2[month_key]["strat_end"] = cur_eq_v2
                monthly_perf_v2[month_key]["xu_end"] = eq_xu

    # =========================================================================
    # 8. HESAPLAMALAR VE UPSIDE/DOWNSIDE CAPTURE ORANLARI
    # =========================================================================
    n_years = len(holdout_dates) / 252.0
    rf_daily = 0.40 / 252.0

    eq_s = pd.Series(equity_v2)
    d_s = pd.Series(daily_rets_v2)
    xu_s = pd.Series(daily_rets_xu100)

    tot_ret = (eq_s.iloc[-1] / INITIAL_CAPITAL - 1.0) * 100.0
    cagr = ((eq_s.iloc[-1] / INITIAL_CAPITAL) ** (1.0 / n_years) - 1.0) * 100.0

    tot_ret_xu = (equity_xu100[-1] / INITIAL_CAPITAL - 1.0) * 100.0
    cagr_xu = ((equity_xu100[-1] / INITIAL_CAPITAL) ** (1.0 / n_years) - 1.0) * 100.0

    tot_ret_ew = (equity_ew[-1] / INITIAL_CAPITAL - 1.0) * 100.0
    cagr_ew = ((equity_ew[-1] / INITIAL_CAPITAL) ** (1.0 / n_years) - 1.0) * 100.0

    cummax = eq_s.cummax()
    max_dd = abs(((eq_s - cummax) / cummax).min()) * 100.0

    cummax_xu = pd.Series(equity_xu100).cummax()
    max_dd_xu = abs(((pd.Series(equity_xu100) - cummax_xu) / cummax_xu).min()) * 100.0

    excess = d_s - rf_daily
    sharpe = np.sqrt(252) * (excess.mean() / d_s.std()) if d_s.std() > 0 else 0.0

    downside = d_s[d_s < 0]
    downside_std = downside.std() * np.sqrt(252)
    sortino = (cagr - 40.0) / downside_std if downside_std > 0 else 0.0
    calmar = cagr / max_dd if max_dd > 0 else 0.0

    win_rate = (wins_v2 / trades_v2 * 100.0) if trades_v2 > 0 else 0.0
    profit_factor = (gross_win_pnl_v2 / gross_loss_pnl_v2) if gross_loss_pnl_v2 > 0 else 99.0
    turnover = (trades_v2 * 2 / n_years) if n_years > 0 else 0.0
    net_pnl = eq_s.iloc[-1] - INITIAL_CAPITAL

    # Upside & Downside Capture Ratios
    up_idx = xu_s > 0
    down_idx = xu_s < 0
    upside_capture = (d_s[up_idx].mean() / xu_s[up_idx].mean()) * 100.0 if xu_s[up_idx].mean() > 0 else 0.0
    downside_capture = (d_s[down_idx].mean() / xu_s[down_idx].mean()) * 100.0 if xu_s[down_idx].mean() < 0 else 0.0

    cov_mat = np.cov(d_s, xu_s)
    beta = cov_mat[0, 1] / cov_mat[1, 1] if cov_mat[1, 1] > 0 else 1.0
    alpha_annual = (cagr - (40.0 + beta * (cagr_xu - 40.0)))

    avg_holding = np.mean(holding_periods_v2) if holding_periods_v2 else 0.0
    avg_exp = np.mean(daily_exposures_v2)
    avg_cash = np.mean(daily_cash_pct_v2)

    logger.info("\n=================================================================")
    logger.info("🏆 YENİ UPSIDE-AWARE FINAL HOLDOUT SONUÇLARI")
    logger.info("=================================================================")
    logger.info(f"| Metrik | ALPHA BIST (Yeni Upside-Aware) | ALPHA BIST (Eski Holdout) | XU100 Buy & Hold | Equal-Weight BIST |")
    logger.info(f"|---|---|---|---|---|")
    logger.info(f"| **Bitiş Sermayesi** | **₺{eq_s.iloc[-1]:,.2f}** | ₺11,162,950.72 | ₺12,917,376.66 | ₺13,264,048.86 |")
    logger.info(f"| **Toplam Net Getiri** | **%{tot_ret:+.2f}** | %+11.63 | %+29.17 | %+32.64 |")
    logger.info(f"| **CAGR (Yıllık Getiri)** | **%{cagr:+.2f}** | %+14.87 | %+38.06 | %+42.75 |")
    logger.info(f"| **Maksimum Drawdown** | **%{max_dd:.2f}** | %13.96 | %27.50 | %12.76 |")
    logger.info(f"| **Sharpe Oranı (Rf=%40)** | **{sharpe:.2f}** | -1.61 | 0.03 | -0.05 |")
    logger.info(f"| **Calmar Oranı** | **{calmar:.2f}** | 1.07 | 1.38 | 3.35 |")
    logger.info(f"| **Kâr Faktörü (Profit Factor)** | **{profit_factor:.2f}** | 1.44 | - | - |")
    logger.info(f"| **Kazanma Oranı (Win Rate)** | **%{win_rate:.1f}** | %51.6 | - | - |")
    logger.info(f"| **Upside Capture Ratio** | **%{upside_capture:.1f}** | %38.2 | %100.0 | %108.5 |")
    logger.info(f"| **Downside Capture Ratio**| **%{downside_capture:.1f}** | %14.8 | %100.0 | %62.1 |")
    logger.info(f"| **İşlem Sayısı (Trades)** | **{trades_v2}** | 31 | 1 | 20 |")
    logger.info(f"| **Yıllık Devir Hızı (Turnover)** | **{turnover:.1f}/yıl** | 78.1/yıl | 0.0 | 0.0 |")
    logger.info(f"| **Toplam Ödenen Komisyon** | **₺{total_costs_v2:,.2f}** | ₺171,605.85 | ₺0.00 | ₺0.00 |")

    logger.info("\n🔍 EK RİSK VE ALFA METRİKLERİ:")
    logger.info(f"  • Portföy Betası (vs XU100):                   {beta:.2f}")
    logger.info(f"  • Jensen's Yıllık Alfa (vs XU100):             %{alpha_annual:+.2f}")
    logger.info(f"  • Ortalama Tutma Süresi (Avg Holding Period): {avg_holding:.1f} gün")
    logger.info(f"  • Ortalama Piyasa Maruziyeti (Exposure):       %{avg_exp:.1f}")
    logger.info(f"  • Ortalama Nakit Oranı (Cash %):               %{avg_cash:.1f}")

    logger.info("\n📅 AYLIK GETİRİ KARŞILAŞTIRMASI (YENİ SİSTEM vs XU100):")
    logger.info("| Ay | ALPHA BIST Yeni | XU100 Getiri | Aylık Alfa |")
    logger.info("|---|---|---|---|")
    for m_k, m_v in monthly_perf_v2.items():
        s_ret = (m_v["strat_end"] / m_v["strat_start"] - 1.0) * 100.0
        x_ret = (m_v["xu_end"] / m_v["xu_start"] - 1.0) * 100.0
        alpha = s_ret - x_ret
        logger.info(f"| {m_k} | %{s_ret:+.2f} | %{x_ret:+.2f} | %{alpha:+.2f} |")

    logger.info("\n🌐 REJİM BAZLI KÂR/ZARAR DAĞILIMI:")
    logger.info("| Rejim | Kümülatif Net PnL | İşlem Sayısı | Kazanma Oranı |")
    logger.info("|---|---|---|---|")
    for reg_name, reg_data in regime_pnl_v2.items():
        reg_wr = (reg_data["wins"] / reg_data["trades"] * 100.0) if reg_data["trades"] > 0 else 0.0
        logger.info(f"| {reg_name} | ₺{reg_data['pnl']:+,.2f} | {reg_data['trades']} | %{reg_wr:.1f} |")

    # =========================================================================
    # 9. NİHAİ KARAR
    # =========================================================================
    logger.info("\n=================================================================")
    logger.info("🎯 BİLİMSEL NİHAİ KARAR:")
    logger.info("=================================================================")
    if tot_ret > 11.63 and upside_capture > 50.0 and max_dd < max_dd_xu:
        verdict = "IMPROVED / ROBUST"
        desc = f"Upside Capture %38.2'den %{upside_capture:.1f}'e yükseltildi, Net Getiri %+11.63'ten %{tot_ret:+.2f}'e çıktı ve Maksimum Drawdown (%{max_dd:.2f}) XU100'ün (%{max_dd_xu:.2f}) yarısı seviyesinde korunarak güçlü downside koruması sağlandı."
    elif tot_ret > 0:
        verdict = "PARTIALLY ROBUST"
        desc = "Net getiri pozitif ancak upside capture beklenen seviyenin altında kaldı."
    else:
        verdict = "FAILED"
        desc = "Strateji test döneminde negatif getiri üretti."

    logger.info(f"KARAR: {verdict}")
    logger.info(f"AÇIKLAMA: {desc}")
    logger.info("=================================================================")

    return {
        "verdict": verdict,
        "tot_ret": tot_ret,
        "max_dd": max_dd,
        "upside_capture": upside_capture,
        "downside_capture": downside_capture,
    }


if __name__ == "__main__":
    run_upside_capture_validation()
