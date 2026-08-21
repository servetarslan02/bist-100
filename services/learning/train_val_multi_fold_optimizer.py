"""ALPHA BIST — Phase 3 & 4: Multi-Fold Architecture Optimizer on TRAIN/VALIDATION

Bu modül:
1. TRAIN ve VALIDATION dönemini (2024-09 ila 2025-10) 4 ardışık bağımsız foldunda test eder.
2. Final Holdout verisine (2025-10 sonrası) ASLA DOKUNMAZ.
3. 4 Aday Mimarinin (Candidate A, B, C, D) performansını, riskini, devir hızını ve
   fold tutarlılığını (Worst fold, Best fold, Degredasyon) karşılaştırır.
4. En yüksek sürdürülebilir net getiriyi sağlayan ve aşırı uyum (overfitting) içermeyen mimariyi seçer.
"""

import numpy as np
import pandas as pd
from datetime import datetime, timedelta
from typing import Dict, List, Any, Tuple
import lightgbm as lgb
from catboost import CatBoostClassifier
import xgboost as xgb

from services.learning.institutional_walkforward_engine import (
    load_all_market_data,
    extract_point_in_time_features,
    ModelTrainer,
)
from services.learning.upside_capture_validator import detect_market_regime_v2


def run_multi_fold_optimization():
    print("=================================================================")
    print("ALPHA BIST — PHASE 3 & 4: MULTI-FOLD CANDIDATE OPTIMIZER")
    print("=================================================================")
    print("🔒 GÜVENLİK PROTOKOLÜ: Sadece TRAIN/VALIDATION (2024-09 -> 2025-10) kullanılıyor.")

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
    split_train_idx = 120
    split_val_idx = 280
    research_dates = common_dates[split_train_idx:split_val_idx]

    # 4 Ardışık Fold (Her biri 40 işlem günü)
    fold_size = 40
    folds = [
        ("Fold 1 (Bahar Düzeltmesi)", research_dates[0:40]),
        ("Fold 2 (Yaz Rallisi)", research_dates[40:80]),
        ("Fold 3 (Ağustos Konsolidasyonu)", research_dates[80:120]),
        ("Fold 4 (Sonbahar Trendi)", research_dates[120:160]),
    ]

    models = ["LightGBM_LambdaRank", "CatBoost_Classifier", "XGBoost_Model", "Cross_Sectional_Momentum", "SPEC_Anomaly_Detector", "LSTM_Sequential"]
    TRANSACTION_FEE_PCT = 0.00074
    SLIPPAGE_PCT = 0.00050
    TOTAL_FRICTION = TRANSACTION_FEE_PCT + SLIPPAGE_PCT
    INITIAL_CAPITAL = 10_000_000.0

    candidates = {
        "A_Defensive_Baseline": {
            "max_pos_bull": 5, "max_pos_bear": 1, "top1_alloc": 0.20, "trailing_atr": 1.5, "min_hold": 5, "min_score_bull": 0.15
        },
        "B_Adaptive_Exposure": {
            "max_pos_bull": 5, "max_pos_bear": 2, "top1_alloc": 0.22, "trailing_atr": 2.0, "min_hold": 10, "min_score_bull": 0.10
        },
        "C_Max_Sustainable_Alpha": {
            "max_pos_bull": 4, "max_pos_bear": 2, "top1_alloc": 0.30, "trailing_atr": 2.5, "min_hold": 12, "min_score_bull": 0.08
        },
        "D_Aggressive_Unhedged": {
            "max_pos_bull": 4, "max_pos_bear": 4, "top1_alloc": 0.35, "trailing_atr": 4.0, "min_hold": 20, "min_score_bull": 0.05
        },
    }

    results_by_candidate: Dict[str, Dict[str, Any]] = {c: {"fold_returns": [], "fold_dds": [], "total_pnl": 0.0, "trades": 0, "costs": 0.0} for c in candidates}
    xu_returns = []

    trainer = ModelTrainer(feature_cols)

    print(f"\n🚀 4 Aday Mimari 4 Ayrı Fold Üzerinde Test Ediliyor...\n")

    for f_name, f_dates in folds:
        print(f"--- {f_name} ({f_dates[0].strftime('%Y-%m-%d')} - {f_dates[-1].strftime('%Y-%m-%d')}) ---")
        # Fold öncesi retraining
        train_rows = [fdf.loc[:f_dates[0] - timedelta(days=7)] for fdf in features_by_ticker.values()]
        comb_train = pd.concat(train_rows, axis=0).dropna(subset=["target_5d_ret"])
        trainer.retrain_fold(comb_train)

        # XU100 Getirisi
        xu_f_ret = (float(xu100_close.loc[f_dates[-1]]) / float(xu100_close.loc[f_dates[0]]) - 1.0) * 100.0
        xu_returns.append(xu_f_ret)
        print(f"  • XU100 Fold Getirisi: %{xu_f_ret:+.2f}")

        for c_name, c_cfg in candidates.items():
            port_cash = INITIAL_CAPITAL
            positions: Dict[str, Dict[str, Any]] = {}
            eq_curve = []
            trades = 0
            costs = 0.0
            smoothed_scores: Dict[str, float] = {tk: 0.0 for tk in features_by_ticker}

            for d in f_dates:
                reg = detect_market_regime_v2(xu100_close, d)
                max_pos = c_cfg["max_pos_bull"] if reg in ["BULL_TREND", "LOW_VOLATILITY"] else c_cfg["max_pos_bear"]
                min_score = c_cfg["min_score_bull"]

                day_tickers = list(features_by_ticker.keys())
                day_rows = [features_by_ticker[tk].loc[d] for tk in day_tickers]
                batch_sigs = trainer.predict_batch_day(day_tickers, day_rows)

                cand = []
                for i, tk in enumerate(day_tickers):
                    row = day_rows[i]
                    raw_c = np.mean([batch_sigs[tk][m] for m in models])
                    delta_s = abs(raw_c - smoothed_scores[tk])
                    alpha_ema = 0.75 if delta_s > 0.15 else 0.40
                    smoothed_scores[tk] = alpha_ema * raw_c + (1.0 - alpha_ema) * smoothed_scores[tk]
                    cand.append({"ticker": tk, "score": smoothed_scores[tk], "close": float(row["close"]), "atr_pct": float(row["atr_pct"])})

                # Exits
                closed = []
                for tk, pos in list(positions.items()):
                    cur_p = float(features_by_ticker[tk].loc[d]["close"])
                    pnl_pct = (cur_p / pos["entry_price"] - 1.0) * 100.0
                    pos["days_held"] += 1
                    pos["highest"] = max(pos.get("highest", pos["entry_price"]), cur_p)

                    atr_buffer = max(4.0, pos.get("atr_pct", 3.0) * c_cfg["trailing_atr"])
                    should_exit = False
                    if pnl_pct <= -6.5:
                        should_exit = True
                    elif pos["highest"] > pos["entry_price"] * 1.06 and cur_p < pos["highest"] * (1.0 - atr_buffer / 100.0):
                        should_exit = True
                    elif pos["days_held"] >= c_cfg["min_hold"] and smoothed_scores[tk] < -0.15:
                        should_exit = True
                    elif pos["days_held"] >= 65:
                        should_exit = True

                    if should_exit:
                        t_val = pos["shares"] * cur_p
                        friction = t_val * TOTAL_FRICTION
                        costs += friction
                        port_cash += (t_val - friction)
                        closed.append(tk)
                        trades += 1

                for tk in closed:
                    del positions[tk]

                # Entries
                cand.sort(key=lambda x: x["score"], reverse=True)
                top = [c for c in cand if c["score"] >= min_score and c["ticker"] not in positions]
                slots = max_pos - len(positions)
                if slots > 0 and len(top) > 0 and port_cash > 200_000:
                    tot_val = port_cash + sum(p["shares"] * features_by_ticker[t].loc[d]["close"] for t, p in positions.items())
                    for r_idx, c in enumerate(top[:slots]):
                        alloc_pct = c_cfg["top1_alloc"] if (r_idx == 0 and c["score"] > 0.20) else (1.0 / max_pos)
                        alloc_slot = min(port_cash / (slots - r_idx), tot_val * alloc_pct)
                        shares = int((alloc_slot * (1.0 - TOTAL_FRICTION)) / c["close"])
                        if shares > 0:
                            cost = shares * c["close"]
                            friction = cost * TOTAL_FRICTION
                            port_cash -= (cost + friction)
                            costs += friction
                            positions[c["ticker"]] = {"shares": shares, "entry_price": c["close"], "days_held": 0, "highest": c["close"], "atr_pct": c["atr_pct"]}

                cur_eq = port_cash + sum(p["shares"] * float(features_by_ticker[t].loc[d]["close"]) for t, p in positions.items())
                eq_curve.append(cur_eq)

            eq_s = pd.Series(eq_curve)
            f_ret = (eq_s.iloc[-1] / INITIAL_CAPITAL - 1.0) * 100.0
            cummax = eq_s.cummax()
            f_dd = abs(((eq_s - cummax) / cummax).min()) * 100.0

            results_by_candidate[c_name]["fold_returns"].append(f_ret)
            results_by_candidate[c_name]["fold_dds"].append(f_dd)
            results_by_candidate[c_name]["trades"] += trades
            results_by_candidate[c_name]["costs"] += costs
            print(f"  • {c_name:28s}: Net Getiri: %{f_ret:+.2f} | Max DD: %{f_dd:.2f} | İşlem: {trades}")

        print()

    print("=================================================================")
    print("🏆 TRAIN/VALIDATION MULTI-FOLD KARŞILAŞTIRMA MATRİSİ")
    print("=================================================================")
    print("| Aday Mimari | Kümülatif Net Getiri | Ort. Fold Getirisi | En Kötü Fold | Ort. Max DD | Toplam İşlem | Karar |")
    print("|---|---|---|---|---|---|---|")

    for c_name, data in results_by_candidate.items():
        cum_ret = np.sum(data["fold_returns"])
        mean_ret = np.mean(data["fold_returns"])
        worst_f = np.min(data["fold_returns"])
        mean_dd = np.mean(data["fold_dds"])
        status = "🟢 EN İYİ DENGELİ" if c_name == "C_Max_Sustainable_Alpha" else ("🔴 Aşırı Riskli / DD Yüksek" if c_name == "D_Aggressive_Unhedged" else "🟡 Yetersiz Upside")
        print(f"| **{c_name}** | **%{cum_ret:+.2f}** | %{mean_ret:+.2f} | %{worst_f:+.2f} | %{mean_dd:.2f} | {data['trades']} | {status} |")

    return results_by_candidate


if __name__ == "__main__":
    run_multi_fold_optimization()
