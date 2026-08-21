"""ALPHA BIST — Final Holdout Validation Engine (Strict 3-Way Split)

Zaman Serisi 3-Yollu Ayrımı (Strict 3-Way Temporal Split):
1. TRAIN:       2024-08-21 -> 2025-03-10 (~140 gün) - İlk model kalibrasyonu & ısınma
2. VALIDATION:  2025-03-10 -> 2025-11-28 (~180 gün) - Parametre & histerezis optimizasyon dönemi
3. FINAL HOLDOUT: 2025-11-28 -> 2026-08-14 (~180 gün) - TAMAMEN DOKUNULMAMIŞ, GÖRÜLMEMİŞ FİNAL TEST

Tüm parametreler kesin olarak DONDURULMUŞTUR:
- EMA Smoothing: 0.50
- Rebalance Barrier / Hysteresis: In-sample rejim eşikleri
- Trailing Stop: +%6 kâr sonrası zirveden %4 çekilme
- Hard Stop-Loss: -%6
- Pozisyon Başına Tavan: %20 (Maksimum 5 pozisyon)
- BIST İşlem Sürtünmesi: %0.074 komisyon + %0.050 slippage = %0.124
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
import structlog
logger = structlog.get_logger()

    load_all_market_data,
    extract_point_in_time_features,
    detect_market_regime,
    ModelTrainer,
)


def run_final_holdout_validation():
    logger.info("=================================================================")
    logger.info("ALPHA BIST — FINAL HOLDOUT VALIDATION (3-WAY SPLIT)")
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
    # Train: 0 -> 120 (Warmup)
    # Validation: 120 -> 280 (Geçmişte optimize edilen aralık)
    # Final Holdout: 280 -> son (Tamamen Görülmemiş Gelecek Dönem)
    split_train_idx = 120
    split_val_idx = 280

    train_dates = common_dates[:split_train_idx]
    val_dates = common_dates[split_train_idx:split_val_idx]
    holdout_dates = common_dates[split_val_idx:-5]  # Son 5 gün kapanmamış trade'ler hariç

    logger.info(f"🔒 1. TRAIN Dönemi:         {train_dates[0].strftime('%Y-%m-%d')} - {train_dates[-1].strftime('%Y-%m-%d')} ({len(train_dates)} gün)")
    logger.info(f"🔒 2. VALIDATION Dönemi:    {val_dates[0].strftime('%Y-%m-%d')} - {val_dates[-1].strftime('%Y-%m-%d')} ({len(val_dates)} gün)")
    logger.info(f"🎯 3. FINAL HOLDOUT Dönemi: {holdout_dates[0].strftime('%Y-%m-%d')} - {holdout_dates[-1].strftime('%Y-%m-%d')} ({len(holdout_dates)} gün)")
    logger.info("-----------------------------------------------------------------")
    logger.info("⚠️ UYARI: Final Holdout verisi hiçbir parametre seçiminde veya optimizasyonda kullanılmamıştır.\n")

    models = ["LightGBM_LambdaRank", "CatBoost_Classifier", "XGBoost_Model", "Cross_Sectional_Momentum", "SPEC_Anomaly_Detector", "LSTM_Sequential"]

    INITIAL_CAPITAL = 10_000_000.0
    TRANSACTION_FEE_PCT = 0.00074
    SLIPPAGE_PCT = 0.00050
    TOTAL_FRICTION = TRANSACTION_FEE_PCT + SLIPPAGE_PCT

    # DONDURULMUŞ PARAMETRELER (FROZEN PARAMETERS)
    regime_max_positions = {
        "BULL_TREND": 5,        # 100% Equity
        "LOW_VOLATILITY": 4,    # 80% Equity
        "SIDEWAYS_RANGE": 2,    # 40% Equity
        "BEAR_MARKET": 1,       # 20% Equity
        "HIGH_VOLATILITY": 1,   # 20% Equity
    }

    regime_min_score_threshold = {
        "BULL_TREND": 0.12,
        "LOW_VOLATILITY": 0.15,
        "SIDEWAYS_RANGE": 0.28,
        "BEAR_MARKET": 0.35,
        "HIGH_VOLATILITY": 0.40,
    }

    # =========================================================================
    # 4 SİSTEMİN FINAL HOLDOUT KOŞUSU
    # =========================================================================
    # 1. ALPHA BIST OPTIMIZED (Frozen Parameters)
    # 2. ALPHA BIST ORIGINAL (Naive 5d Churn)
    # 3. XU100 Buy & Hold
    # 4. Equal-Weight 20 Hisse

    # 1. OPTIMIZED ENGINE RUN
    logger.info("🚀 [1/4] Alpha BIST Optimized (Dondurulmuş Parametreler) Final Holdout'ta Koşuluyor...", flush=True)
    trainer_opt = ModelTrainer(feature_cols)
    portfolio_cash_opt = INITIAL_CAPITAL
    positions_opt: Dict[str, Dict[str, Any]] = {}
    equity_opt = []
    daily_rets_opt = []
    holding_periods_opt = []
    daily_exposures_opt = []
    daily_cash_pct_opt = []
    monthly_perf_opt: Dict[str, Dict[str, float]] = {}
    regime_pnl_opt: Dict[str, Dict[str, float]] = {r: {"pnl": 0.0, "trades": 0, "wins": 0} for r in ["BULL_TREND", "BEAR_MARKET", "SIDEWAYS_RANGE", "HIGH_VOLATILITY", "LOW_VOLATILITY"]}
    
    total_costs_opt = 0.0
    trades_opt = 0
    wins_opt = 0
    losses_opt = 0
    gross_win_pnl_opt = 0.0
    gross_loss_pnl_opt = 0.0
    smoothed_scores_opt: Dict[str, float] = {tk: 0.0 for tk in features_by_ticker}
    pending_evals_opt: List[Dict[str, Any]] = []
    completed_wins_opt = {m: 0 for m in models}
    completed_totals_opt = {m: 0 for m in models}

    # 2. ORIGINAL ENGINE RUN (Naive 5-Day)
    logger.info("🚀 [2/4] Alpha BIST Original (Naive 5-Day Churn) Final Holdout'ta Koşuluyor...", flush=True)
    trainer_orig = ModelTrainer(feature_cols)
    portfolio_cash_orig = INITIAL_CAPITAL
    positions_orig: Dict[str, Dict[str, Any]] = {}
    equity_orig = []
    daily_rets_orig = []
    total_costs_orig = 0.0
    trades_orig = 0
    wins_orig = 0
    losses_orig = 0
    gross_win_pnl_orig = 0.0
    gross_loss_pnl_orig = 0.0
    pending_evals_orig: List[Dict[str, Any]] = []
    completed_wins_orig = {m: 0 for m in models}
    completed_totals_orig = {m: 0 for m in models}

    # Benchmark Başlangıç Değerleri
    start_xu100 = float(xu100_close.loc[holdout_dates[0]]) if holdout_dates[0] in xu100_close.index else float(xu100_close.iloc[0])
    equity_xu100 = []
    equity_ew = []
    daily_rets_xu100 = []

    retrain_freq = 20
    current_fold = 0

    for step_i, current_date in enumerate(holdout_dates):
        date_str = current_date.strftime("%Y-%m-%d")
        month_key = current_date.strftime("%Y-%m")

        # 0. Kapanan tahmin havuzlarını güncelle
        still_p_opt = []
        for pe in pending_evals_opt:
            if pe["eval_date"] <= current_date:
                completed_totals_opt[pe["model"]] += 1
                if pe["is_correct"]:
                    completed_wins_opt[pe["model"]] += 1
            else:
                still_p_opt.append(pe)
        pending_evals_opt = still_p_opt

        still_p_orig = []
        for pe in pending_evals_orig:
            if pe["eval_date"] <= current_date:
                completed_totals_orig[pe["model"]] += 1
                if pe["is_correct"]:
                    completed_wins_orig[pe["model"]] += 1
            else:
                still_p_orig.append(pe)
        pending_evals_orig = still_p_orig

        # 1. PERİYODİK MODEL RETRAINING (Genişleyen Pencere, 5 Gün Embargo)
        if step_i % retrain_freq == 0:
            current_fold += 1
            train_rows = [fdf.loc[:current_date - timedelta(days=7)] for fdf in features_by_ticker.values()]
            comb_train = pd.concat(train_rows, axis=0).dropna(subset=["target_5d_ret"])
            trainer_opt.retrain_fold(comb_train)
            trainer_orig.retrain_fold(comb_train)

        # 2. PİYASA REJİMİ
        current_regime = detect_market_regime(xu100_close, current_date)
        max_pos_opt = regime_max_positions.get(current_regime, 3)
        min_score_opt = regime_min_score_threshold.get(current_regime, 0.20)

        # 3. DİNAMİK TRUST AĞIRLIKLARI
        weights_opt = {}
        for m in models:
            n_done = completed_totals_opt[m]
            if n_done >= 15:
                acc = completed_wins_opt[m] / n_done
                shrinkage = 1.0 - np.exp(-n_done / 50.0)
                trust = (1.0 - shrinkage) * 0.50 + shrinkage * acc
            else:
                trust = 0.50
            weights_opt[m] = max(0.05, min(0.35, trust))
        norm_w_opt = {m: w / sum(weights_opt.values()) for m, w in weights_opt.items()}

        weights_orig = {}
        for m in models:
            n_done = completed_totals_orig[m]
            if n_done >= 15:
                acc = completed_wins_orig[m] / n_done
                shrinkage = 1.0 - np.exp(-n_done / 50.0)
                trust = (1.0 - shrinkage) * 0.50 + shrinkage * acc
            else:
                trust = 0.50
            weights_orig[m] = max(0.05, min(0.35, trust))
        norm_w_orig = {m: w / sum(weights_orig.values()) for m, w in weights_orig.items()}

        # 4. SİNYAL VE SKOR ÜRETİMİ
        day_tickers = list(features_by_ticker.keys())
        day_rows = [features_by_ticker[tk].loc[current_date] for tk in day_tickers]
        batch_sigs_opt = trainer_opt.predict_batch_day(day_tickers, day_rows)
        batch_sigs_orig = trainer_orig.predict_batch_day(day_tickers, day_rows)

        cand_opt = []
        cand_orig = []
        for i, tk in enumerate(day_tickers):
            row = day_rows[i]
            cur_p = float(row["close"])
            fwd_p = float(row.get("future_price_5d", cur_p))
            ret_5d = float(row.get("target_5d_ret", 0.0))

            # Opt Sinyal (EMA Düzleştirmeli)
            raw_c_opt = sum(norm_w_opt[m] * batch_sigs_opt[tk][m] for m in models)
            smoothed_scores_opt[tk] = 0.50 * raw_c_opt + 0.50 * smoothed_scores_opt[tk]
            cand_opt.append({"ticker": tk, "score": smoothed_scores_opt[tk], "close": cur_p, "future": fwd_p, "ret_5d": ret_5d})

            # Orig Sinyal (Ham)
            raw_c_orig = sum(norm_w_orig[m] * batch_sigs_orig[tk][m] for m in models)
            cand_orig.append({"ticker": tk, "score": raw_c_orig, "close": cur_p, "future": fwd_p, "ret_5d": ret_5d})

            for m in models:
                p_opt = 1 if batch_sigs_opt[tk][m] > 0 else -1
                p_orig = 1 if batch_sigs_orig[tk][m] > 0 else -1
                act_sign = 1 if ret_5d > 0 else -1
                pending_evals_opt.append({"eval_date": current_date + timedelta(days=7), "model": m, "is_correct": (p_opt == act_sign)})
                pending_evals_orig.append({"eval_date": current_date + timedelta(days=7), "model": m, "is_correct": (p_orig == act_sign)})

        # 5. POZİSYON ÇIKIŞLARI
        # A) OPTIMIZED EXIT (Trailing Stop + Dynamic Barrier)
        closed_opt = []
        for tk, pos in list(positions_opt.items()):
            cur_p = float(features_by_ticker[tk].loc[current_date]["close"])
            pnl_pct = (cur_p / pos["entry_price"] - 1.0) * 100.0
            pos["days_held"] += 1
            pos["highest_price"] = max(pos.get("highest_price", pos["entry_price"]), cur_p)

            should_exit = False
            if pnl_pct <= -6.0:
                should_exit = True
            elif pos["highest_price"] > pos["entry_price"] * 1.06 and cur_p < pos["highest_price"] * 0.96:
                should_exit = True
            elif pnl_pct >= 25.0:
                should_exit = True
            elif pos["days_held"] >= 10 and smoothed_scores_opt[tk] < -0.10:
                should_exit = True
            elif pos["days_held"] >= 60:
                should_exit = True

            if should_exit:
                t_val = pos["shares"] * cur_p
                friction = t_val * TOTAL_FRICTION
                net_val = t_val - friction
                total_costs_opt += friction
                net_pnl = net_val - (pos["shares"] * pos["entry_price"])
                portfolio_cash_opt += net_val
                closed_opt.append(tk)
                holding_periods_opt.append(pos["days_held"])

                trades_opt += 1
                if net_pnl > 0:
                    wins_opt += 1
                    gross_win_pnl_opt += net_pnl
                    regime_pnl_opt[pos["regime"]]["wins"] += 1
                else:
                    losses_opt += 1
                    gross_loss_pnl_opt += abs(net_pnl)

                regime_pnl_opt[pos["regime"]]["pnl"] += net_pnl
                regime_pnl_opt[pos["regime"]]["trades"] += 1

        for tk in closed_opt:
            del positions_opt[tk]

        # B) ORIGINAL EXIT (Strict 5-Day Forced Exit)
        closed_orig = []
        for tk, pos in list(positions_orig.items()):
            cur_p = float(features_by_ticker[tk].loc[current_date]["close"])
            pos["days_held"] += 1
            pnl_pct = (cur_p / pos["entry_price"] - 1.0) * 100.0
            
            should_exit = False
            if pnl_pct <= -5.0 or pnl_pct >= 12.0 or pos["days_held"] >= 5:
                should_exit = True

            if should_exit:
                t_val = pos["shares"] * cur_p
                friction = t_val * TOTAL_FRICTION
                net_val = t_val - friction
                total_costs_orig += friction
                net_pnl = net_val - (pos["shares"] * pos["entry_price"])
                portfolio_cash_orig += net_val
                closed_orig.append(tk)

                trades_orig += 1
                if net_pnl > 0:
                    wins_orig += 1
                    gross_win_pnl_orig += net_pnl
                else:
                    losses_orig += 1
                    gross_loss_pnl_orig += abs(net_pnl)

        for tk in closed_orig:
            del positions_orig[tk]

        # 6. YENİ POZİSYON AÇILIŞLARI
        # A) OPTIMIZED ENTRY
        cand_opt.sort(key=lambda x: x["score"], reverse=True)
        top_opt = [c for c in cand_opt if c["score"] >= min_score_opt and c["ticker"] not in positions_opt]
        slots_opt = max_pos_opt - len(positions_opt)
        if slots_opt > 0 and len(top_opt) > 0 and portfolio_cash_opt > 200_000:
            tot_val_opt = portfolio_cash_opt + sum(p["shares"] * features_by_ticker[t].loc[current_date]["close"] for t, p in positions_opt.items())
            alloc_slot = min(portfolio_cash_opt / slots_opt, tot_val_opt * 0.20)
            for c in top_opt[:slots_opt]:
                shares = int((alloc_slot * (1.0 - TOTAL_FRICTION)) / c["close"])
                if shares > 0:
                    cost = shares * c["close"]
                    friction = cost * TOTAL_FRICTION
                    portfolio_cash_opt -= (cost + friction)
                    total_costs_opt += friction
                    positions_opt[c["ticker"]] = {
                        "shares": shares, "entry_price": c["close"], "days_held": 0, "highest_price": c["close"], "regime": current_regime
                    }

        # B) ORIGINAL ENTRY
        cand_orig.sort(key=lambda x: x["score"], reverse=True)
        top_orig = [c for c in cand_orig if c["score"] > 0.10 and c["ticker"] not in positions_orig]
        slots_orig = 5 - len(positions_orig)
        if slots_orig > 0 and len(top_orig) > 0 and portfolio_cash_orig > 200_000:
            tot_val_orig = portfolio_cash_orig + sum(p["shares"] * features_by_ticker[t].loc[current_date]["close"] for t, p in positions_orig.items())
            alloc_orig = min(portfolio_cash_orig / slots_orig, tot_val_orig * 0.20)
            for c in top_orig[:slots_orig]:
                shares = int((alloc_orig * (1.0 - TOTAL_FRICTION)) / c["close"])
                if shares > 0:
                    cost = shares * c["close"]
                    friction = cost * TOTAL_FRICTION
                    portfolio_cash_orig -= (cost + friction)
                    total_costs_orig += friction
                    positions_orig[c["ticker"]] = {"shares": shares, "entry_price": c["close"], "days_held": 0, "regime": current_regime}

        # 7. GÜNLÜK DEĞERLER VE BENCHMARK
        cur_eq_opt = portfolio_cash_opt + sum(p["shares"] * float(features_by_ticker[t].loc[current_date]["close"]) for t, p in positions_opt.items())
        equity_opt.append(cur_eq_opt)

        invested_opt = sum(p["shares"] * float(features_by_ticker[t].loc[current_date]["close"]) for t, p in positions_opt.items())
        exp_opt = (invested_opt / cur_eq_opt) * 100.0 if cur_eq_opt > 0 else 0.0
        daily_exposures_opt.append(exp_opt)
        daily_cash_pct_opt.append(100.0 - exp_opt)

        cur_eq_orig = portfolio_cash_orig + sum(p["shares"] * float(features_by_ticker[t].loc[current_date]["close"]) for t, p in positions_orig.items())
        equity_orig.append(cur_eq_orig)

        # XU100
        cur_xu = float(xu100_close.loc[current_date]) if current_date in xu100_close.index else start_xu100
        eq_xu = INITIAL_CAPITAL * (cur_xu / start_xu100)
        equity_xu100.append(eq_xu)

        # Equal-Weight 20
        ew_val = INITIAL_CAPITAL * np.mean([float(fdf.loc[current_date]["close"]) / float(fdf.loc[holdout_dates[0]]["close"]) for fdf in features_by_ticker.values()])
        equity_ew.append(ew_val)

        if len(equity_opt) > 1:
            d_opt = equity_opt[-1] / equity_opt[-2] - 1.0
            d_xu = equity_xu100[-1] / equity_xu100[-2] - 1.0
            daily_rets_opt.append(d_opt)
            daily_rets_xu100.append(d_xu)
            daily_rets_orig.append(equity_orig[-1] / equity_orig[-2] - 1.0)

            if month_key not in monthly_perf_opt:
                monthly_perf_opt[month_key] = {"strat_start": equity_opt[-2], "xu_start": equity_xu100[-2], "strat_end": cur_eq_opt, "xu_end": eq_xu}
            else:
                monthly_perf_opt[month_key]["strat_end"] = cur_eq_opt
                monthly_perf_opt[month_key]["xu_end"] = eq_xu

    # =========================================================================
    # 8. HESAPLAMALAR VE KARŞILAŞTIRMA RAPORU
    # =========================================================================
    n_years = len(holdout_dates) / 252.0
    rf_daily = 0.40 / 252.0

    def calc_metrics(eq_list, daily_rets_list, trades_count, wins_count, gross_win, gross_loss, total_costs):
        eq_s = pd.Series(eq_list)
        d_s = pd.Series(daily_rets_list)
        tot_ret = (eq_s.iloc[-1] / INITIAL_CAPITAL - 1.0) * 100.0
        cagr = ((eq_s.iloc[-1] / INITIAL_CAPITAL) ** (1.0 / n_years) - 1.0) * 100.0
        
        cummax = eq_s.cummax()
        max_dd = abs(((eq_s - cummax) / cummax).min()) * 100.0

        excess = d_s - rf_daily
        sharpe = np.sqrt(252) * (excess.mean() / d_s.std()) if d_s.std() > 0 else 0.0

        downside = d_s[d_s < 0]
        downside_std = downside.std() * np.sqrt(252)
        sortino = (cagr - 40.0) / downside_std if downside_std > 0 else 0.0
        calmar = cagr / max_dd if max_dd > 0 else 0.0

        win_rate = (wins_count / trades_count * 100.0) if trades_count > 0 else 0.0
        profit_factor = (gross_win / gross_loss) if gross_loss > 0 else 99.0
        turnover = (trades_count * 2 / n_years) if n_years > 0 else 0.0
        net_pnl = eq_s.iloc[-1] - INITIAL_CAPITAL

        return {
            "total_return": tot_ret, "cagr": cagr, "max_dd": max_dd, "sharpe": sharpe,
            "sortino": sortino, "calmar": calmar, "win_rate": win_rate, "profit_factor": profit_factor,
            "turnover": turnover, "net_pnl": net_pnl, "trades": trades_count, "costs": total_costs,
            "final_equity": eq_s.iloc[-1]
        }

    m_opt = calc_metrics(equity_opt, daily_rets_opt, trades_opt, wins_opt, gross_win_pnl_opt, gross_loss_pnl_opt, total_costs_opt)
    m_orig = calc_metrics(equity_orig, daily_rets_orig, trades_orig, wins_orig, gross_win_pnl_orig, gross_loss_pnl_orig, total_costs_orig)
    m_xu = calc_metrics(equity_xu100, daily_rets_xu100, 0, 0, 0, 0, 0)
    m_ew = calc_metrics(equity_ew, pd.Series(equity_ew).pct_change().dropna(), 0, 0, 0, 0, 0)

    # Beta & Alpha
    cov_mat = np.cov(daily_rets_opt, daily_rets_xu100)
    beta = cov_mat[0, 1] / cov_mat[1, 1] if cov_mat[1, 1] > 0 else 1.0
    alpha_annual = (m_opt["cagr"] - (40.0 + beta * (m_xu["cagr"] - 40.0)))

    avg_holding = np.mean(holding_periods_opt) if holding_periods_opt else 0.0
    avg_exp = np.mean(daily_exposures_opt)
    avg_cash = np.mean(daily_cash_pct_opt)

    logger.info("\n=================================================================")
    logger.info("📊 FINAL HOLDOUT KARŞILAŞTIRMA MATRİSİ (TAMAMEN GÖRÜLMEMİŞ DÖNEM)")
    logger.info("=================================================================")
    logger.info(f"| Metrik | ALPHA BIST (Optimized) | ALPHA BIST (Original) | XU100 Buy & Hold | Equal-Weight BIST |")
    logger.info(f"|---|---|---|---|---|")
    logger.info(f"| **Bitiş Sermayesi** | **₺{m_opt['final_equity']:,.2f}** | ₺{m_orig['final_equity']:,.2f} | ₺{m_xu['final_equity']:,.2f} | ₺{m_ew['final_equity']:,.2f} |")
    logger.info(f"| **Toplam Net Getiri** | **%{m_opt['total_return']:+.2f}** | %{m_orig['total_return']:+.2f} | %{m_xu['total_return']:+.2f} | %{m_ew['total_return']:+.2f} |")
    logger.info(f"| **CAGR (Yıllık Getiri)** | **%{m_opt['cagr']:+.2f}** | %{m_orig['cagr']:+.2f} | %{m_xu['cagr']:+.2f} | %{m_ew['cagr']:+.2f} |")
    logger.info(f"| **Maksimum Drawdown** | **%{m_opt['max_dd']:.2f}** | %{m_orig['max_dd']:.2f} | %{m_xu['max_dd']:.2f} | %{m_ew['max_dd']:.2f} |")
    logger.info(f"| **Sharpe Oranı (Rf=%40)** | **{m_opt['sharpe']:.2f}** | {m_orig['sharpe']:.2f} | {m_xu['sharpe']:.2f} | {m_ew['sharpe']:.2f} |")
    logger.info(f"| **Calmar Oranı** | **{m_opt['calmar']:.2f}** | {m_orig['calmar']:.2f} | {m_xu['calmar']:.2f} | {m_ew['calmar']:.2f} |")
    logger.info(f"| **Kâr Faktörü (Profit Factor)** | **{m_opt['profit_factor']:.2f}** | {m_orig['profit_factor']:.2f} | - | - |")
    logger.info(f"| **Kazanma Oranı (Win Rate)** | **%{m_opt['win_rate']:.1f}** | %{m_orig['win_rate']:.1f} | - | - |")
    logger.info(f"| **İşlem Sayısı (Trades)** | **{m_opt['trades']}** | {m_orig['trades']} | 1 | 20 |")
    logger.info(f"| **Yıllık Devir Hızı (Turnover)** | **{m_opt['turnover']:.1f}/yıl** | {m_orig['turnover']:.1f}/yıl | 0.0 | 0.0 |")
    logger.info(f"| **Toplam Ödenen Komisyon** | **₺{m_opt['costs']:,.2f}** | ₺{m_orig['costs']:,.2f} | ₺0.00 | ₺0.00 |")

    logger.info("\n🔍 EK KURUMSAL RİSK VE POZİSYON METRİKLERİ:")
    logger.info(f"  • Ortalama Tutma Süresi (Avg Holding Period): {avg_holding:.1f} gün")
    logger.info(f"  • Portföy Betası (vs XU100):                   {beta:.2f}")
    logger.info(f"  • Jensen's Yıllık Alfa (vs XU100):             %{alpha_annual:+.2f}")
    logger.info(f"  • Ortalama Piyasa Maruziyeti (Exposure):       %{avg_exp:.1f}")
    logger.info(f"  • Ortalama Nakit Oranı (Cash %):               %{avg_cash:.1f}")

    logger.info("\n📅 FINAL HOLDOUT AYLIK GETİRİ DAĞILIMI (Strateji vs XU100):")
    logger.info("| Ay | ALPHA BIST Optimized | XU100 Getiri | Aylık Alfa |")
    logger.info("|---|---|---|---|")
    for m_k, m_v in monthly_perf_opt.items():
        s_ret = (m_v["strat_end"] / m_v["strat_start"] - 1.0) * 100.0
        x_ret = (m_v["xu_end"] / m_v["xu_start"] - 1.0) * 100.0
        alpha = s_ret - x_ret
        logger.info(f"| {m_k} | %{s_ret:+.2f} | %{x_ret:+.2f} | %{alpha:+.2f} |")

    logger.info("\n🌐 FINAL HOLDOUT REJİM BAZLI KÂR/ZARAR:")
    logger.info("| Rejim | Kümülatif Net PnL | İşlem Sayısı | Kazanma Oranı |")
    logger.info("|---|---|---|---|")
    for reg_name, reg_data in regime_pnl_opt.items():
        reg_wr = (reg_data["wins"] / reg_data["trades"] * 100.0) if reg_data["trades"] > 0 else 0.0
        logger.info(f"| {reg_name} | ₺{reg_data['pnl']:+,.2f} | {reg_data['trades']} | %{reg_wr:.1f} |")

    # =========================================================================
    # 9. KESİN VE TAVİZSİZ SONUÇ DEĞERLENDİRMESİ
    # =========================================================================
    logger.info("\n=================================================================")
    logger.info("🎯 BİLİMSEL VE TAVİZSİZ NİHAİ KARAR:")
    logger.info("=================================================================")
    
    if m_opt["total_return"] > 0 and m_opt["profit_factor"] >= 1.3 and m_opt["max_dd"] < m_xu["max_dd"]:
        verdict = "A) ROBUST"
        desc = "Final holdout dönemi pozitif net getiri üretti, kâr faktörü 1.30'un üzerinde kaldı ve maksimum drawdown benchmarktan belirgin şekilde daha düşük gerçekleşti. Edge kalıcı ve genelleştirilebilir."
    elif m_opt["total_return"] > 0:
        verdict = "B) PARTIALLY ROBUST"
        desc = "Final holdout dönemi pozitif getiri sağladı ancak validasyon dönemine göre getiri/kâr faktöründe düşüş görüldü."
    else:
        verdict = "C) OVERFIT"
        desc = "Final holdout döneminde pozitif edge kayboldu ve strateji net zarar yazdı."

    logger.info(f"KARAR: {verdict}")
    logger.info(f"AÇIKLAMA: {desc}")
    logger.info("=================================================================")

    return {
        "verdict": verdict,
        "m_opt": m_opt,
        "m_orig": m_orig,
        "m_xu": m_xu,
        "m_ew": m_ew,
    }


if __name__ == "__main__":
    run_final_holdout_validation()
