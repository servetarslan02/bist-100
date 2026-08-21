"""FAZ 14: ABSOLUTE + RELATIVE ALPHA ARCHITECTURE
"""

import numpy as np
import pandas as pd
from datetime import timedelta
import lightgbm as lgb
from catboost import CatBoostClassifier
import xgboost as xgb
import warnings
import random
warnings.filterwarnings('ignore')

from services.learning.institutional_walkforward_engine import (
import structlog
logger = structlog.get_logger()

    load_all_market_data, extract_point_in_time_features, detect_market_regime
)

# =====================================================================
# M0: OLD TRAINER (REGRESSOR)
# =====================================================================
class ModelTrainerM0:
    def __init__(self, feature_cols):
        self.feature_cols = feature_cols
        self.lgb_model = None

    def retrain_fold(self, train_df):
        if len(train_df) < 100: return
        X = train_df[self.feature_cols].values
        y_reg = train_df["target_5d_ret"].values
        train_data = lgb.Dataset(X, label=y_reg)
        params_lgb = {"objective": "regression", "metric": "rmse", "learning_rate": 0.05, "num_leaves": 15, "min_data_in_leaf": 10, "verbose": -1, "seed": 42, "num_threads": 2}
        self.lgb_model = lgb.train(params_lgb, train_data, num_boost_round=40)

    def predict_batch_day(self, tickers, features_list):
        X_mat = np.array([f[self.feature_cols].values for f in features_list])
        lgb_preds = np.zeros(len(tickers))
        if self.lgb_model:
            raw_lgb = self.lgb_model.predict(X_mat)
            lgb_preds = np.tanh(raw_lgb / 3.0)
        return {tk: {"LightGBM_LambdaRank": float(lgb_preds[i])} for i, tk in enumerate(tickers)}

# =====================================================================
# M1/M2: RANKER TRAINER
# =====================================================================
class ModelTrainerRanker:
    def __init__(self, feature_cols):
        self.feature_cols = feature_cols
        self.rank_model = None

    def retrain_fold(self, train_df):
        if len(train_df) < 100: return
        df_sorted = train_df.sort_values('date').copy()
        df_sorted['target_rank_pct'] = df_sorted.groupby('date')['target_5d_ret'].rank(pct=True, method='average')
        df_sorted['relevance'] = (df_sorted['target_rank_pct'] * 4.999).fillna(0).astype(int)
        groups = df_sorted.groupby('date').size().values
        X_df = df_sorted[self.feature_cols]
        y_rel = df_sorted['relevance']
        self.rank_model = lgb.LGBMRanker(
            n_estimators=40, learning_rate=0.05, num_leaves=15, 
            min_data_in_leaf=10, objective='lambdarank', metric='ndcg',
            random_state=42, n_jobs=2, verbose=-1
        )
        self.rank_model.fit(X_df, y_rel, group=groups)

    def predict_batch_day(self, tickers, features_list):
        X_mat = np.array([f[self.feature_cols].values for f in features_list])
        lgb_preds = np.zeros(len(tickers))
        if self.rank_model:
            raw_lgb = self.rank_model.predict(X_mat)
            s = pd.Series(raw_lgb)
            if len(s) > 1: lgb_preds = ((s.rank(pct=True) - 0.5) * 2.0).values
        return {tk: {"LightGBM_LambdaRank": float(lgb_preds[i])} for i, tk in enumerate(tickers)}

# =====================================================================
# WALK-FORWARD ENGINE WITH FILTER SUPPORT
# =====================================================================
def run_simulation(trainer, eval_dates, features_by_ticker, xu100_close, filter_mode="NONE"):
    INITIAL_CAPITAL = 10_000_000.0
    portfolio_cash = INITIAL_CAPITAL
    positions = {}
    portfolio_equity_curve = []
    
    total_transaction_costs = 0.0
    total_trades_count = 0
    gross_profits = 0.0
    gross_losses = 0.0
    exposure_history = []
    
    TRANSACTION_FEE_PCT = 0.00074
    SLIPPAGE_PCT = 0.00050
    TOTAL_FRICTION = TRANSACTION_FEE_PCT + SLIPPAGE_PCT

    # Track historical regimes for lagged filter
    regime_history = []

    for step_i, current_date in enumerate(eval_dates):
        # 1. PURGED RETRAINING
        if step_i % 20 == 0:
            train_rows = []
            for tk, fdf in features_by_ticker.items():
                hist_df = fdf.loc[:current_date - timedelta(days=7)]
                if not hist_df.empty:
                    hist_df = hist_df.copy()
                    hist_df['date'] = hist_df.index
                    train_rows.append(hist_df)
            if train_rows:
                combined_train = pd.concat(train_rows, axis=0).dropna(subset=["target_5d_ret"])
                trainer.retrain_fold(combined_train)

        # 2. REGIME & FILTER LOGIC
        current_regime = detect_market_regime(xu100_close, current_date)
        regime_history.append(current_regime)
        
        permit_long = True
        
        # Absolute Filter Implementation
        if filter_mode == "ACTUAL":
            permit_long = current_regime not in ["BEAR_MARKET", "HIGH_VOLATILITY"]
        elif filter_mode == "LAGGED":
            lagged_idx = max(0, len(regime_history) - 21)
            lagged_regime = regime_history[lagged_idx]
            permit_long = lagged_regime not in ["BEAR_MARKET", "HIGH_VOLATILITY"]
        elif filter_mode == "RANDOM":
            permit_long = random.choice([True, False])
        elif filter_mode == "ALWAYS_OFF":
            permit_long = False
            
        # 3. INFERENCE
        day_tickers = list(features_by_ticker.keys())
        day_rows = [features_by_ticker[tk].loc[current_date] for tk in day_tickers]
        batch_signals = trainer.predict_batch_day(day_tickers, day_rows)

        candidate_scores = []
        for i, tk in enumerate(day_tickers):
            row = day_rows[i]
            # Since we isolated to just LightGBM for this specific core logic test:
            composite_score = batch_signals[tk]["LightGBM_LambdaRank"]
            # Apply Absolute Filter (if not permitted, squash score to 0)
            if not permit_long:
                composite_score = -1.0
                
            candidate_scores.append({
                "ticker": tk, "composite_score": composite_score, "close_price": float(row["close"])
            })

        # 4. EXITS
        closed_tickers = []
        for tk, pos in list(positions.items()):
            cur_price = float(features_by_ticker[tk].loc[current_date]["close"])
            pnl_pct = (cur_price / pos["entry_price"] - 1.0) * 100.0
            pos["days_held"] += 1
            if pnl_pct <= -5.0 or pnl_pct >= 12.0 or pos["days_held"] >= 5:
                trade_val = pos["shares"] * cur_price
                friction = trade_val * TOTAL_FRICTION
                net_val = trade_val - friction
                total_transaction_costs += friction
                net_trade_pnl = net_val - (pos["shares"] * pos["entry_price"])
                portfolio_cash += net_val
                closed_tickers.append(tk)
                total_trades_count += 1
                if net_trade_pnl > 0: gross_profits += net_trade_pnl
                else: gross_losses += abs(net_trade_pnl)
        for tk in closed_tickers: del positions[tk]

        # 5. ENTRIES
        candidate_scores.sort(key=lambda x: x["composite_score"], reverse=True)
        top_candidates = [c for c in candidate_scores if c["composite_score"] > 0.15 and c["ticker"] not in positions]
        
        open_slots = 5 - len(positions)
        if open_slots > 0 and portfolio_cash > 200_000:
            target_alloc_per_slot = min(portfolio_cash / open_slots, (portfolio_cash + sum(p["shares"] * features_by_ticker[t].loc[current_date]["close"] for t, p in positions.items())) * 0.20)
            for cand in top_candidates[:open_slots]:
                alloc = target_alloc_per_slot * (1.0 - TOTAL_FRICTION)
                shares = int(alloc / cand["close_price"])
                if shares > 0:
                    cost = shares * cand["close_price"]
                    friction = cost * TOTAL_FRICTION
                    portfolio_cash -= (cost + friction)
                    total_transaction_costs += friction
                    positions[cand["ticker"]] = {"shares": shares, "entry_price": cand["close_price"], "days_held": 0}

        # 6. EQUITY LOG
        current_equity = portfolio_cash + sum(p["shares"] * float(features_by_ticker[t].loc[current_date]["close"]) for t, p in positions.items())
        portfolio_equity_curve.append(current_equity)
        exposure_history.append(len(positions) / 5.0)

    return portfolio_equity_curve, total_trades_count, gross_profits, gross_losses, np.mean(exposure_history)

if __name__ == "__main__":
    logger.info("🚀 FAZ 14: ABSOLUTE + RELATIVE ALPHA ARCHITECTURE")
    
    stock_data, xu100_close = load_all_market_data()
    feature_cols = ["roc_5d", "roc_20d", "momentum_20d", "price_vs_sma20", 
                    "price_vs_sma50", "price_vs_sma200", "atr_pct", 
                    "volatility_20d", "volume_zscore", "bb_position"]
                    
    features_by_ticker = {tk: extract_point_in_time_features(df) for tk, df in stock_data.items() if len(df) >= 120}
    common_dates = sorted(list(set.intersection(*[set(fdf.index) for fdf in features_by_ticker.values()])))
    val_dates = [d for d in common_dates[120:] if d <= pd.Timestamp("2025-10-31")]
    
    logger.info("\n==================================================")
    logger.info("M0 (REGRESSION) vs M1 (RANKER) vs M2 (RANKER + FILTER)")
    logger.info("==================================================")
    
    # 1. M0
    trainer_m0 = ModelTrainerM0(feature_cols)
    eq_m0, tr_m0, gp_m0, gl_m0, exp_m0 = run_simulation(trainer_m0, val_dates, features_by_ticker, xu100_close, filter_mode="NONE")
    
    # 2. M1
    trainer_ranker = ModelTrainerRanker(feature_cols)
    eq_m1, tr_m1, gp_m1, gl_m1, exp_m1 = run_simulation(trainer_ranker, val_dates, features_by_ticker, xu100_close, filter_mode="NONE")
    
    # 3. M2
    eq_m2, tr_m2, gp_m2, gl_m2, exp_m2 = run_simulation(trainer_ranker, val_dates, features_by_ticker, xu100_close, filter_mode="ACTUAL")
    
    def print_metrics(name, eq_curve, trades, gp, gl, exp):
        init = 10_000_000.0
        final = eq_curve[-1]
        cagr = ((final / init) ** (252.0 / len(eq_curve)) - 1.0) * 100.0
        s = pd.Series(eq_curve)
        cummax = s.cummax()
        mdd = abs(((s - cummax) / cummax).min()) * 100.0
        pf = (gp / gl) if gl > 0 else 99.0
        logger.info(f"{name:30} | CAGR: %{cagr:>6.2f} | MaxDD: %{mdd:>5.2f} | PF: {pf:>4.2f} | Trades: {trades:>4} | Avg Exposure: %{exp*100:>4.1f}")
        return cagr

    print_metrics("M0: Regression (V3 Baseline)", eq_m0, tr_m0, gp_m0, gl_m0, exp_m0)
    print_metrics("M1: Ranker Only (Always ON)", eq_m1, tr_m1, gp_m1, gl_m1, exp_m1)
    cagr_m2 = print_metrics("M2: Ranker + Absolute Filter", eq_m2, tr_m2, gp_m2, gl_m2, exp_m2)

    logger.info("\n==================================================")
    logger.info("FAZ 14.5 — PLACEBO FILTER TESTS (ON RANKER)")
    logger.info("==================================================")
    eq_lag, tr_lag, gp_lag, gl_lag, exp_lag = run_simulation(trainer_ranker, val_dates, features_by_ticker, xu100_close, filter_mode="LAGGED")
    eq_rnd, tr_rnd, gp_rnd, gl_rnd, exp_rnd = run_simulation(trainer_ranker, val_dates, features_by_ticker, xu100_close, filter_mode="RANDOM")
    
    print_metrics("Placebo 1: Lagged Filter", eq_lag, tr_lag, gp_lag, gl_lag, exp_lag)
    print_metrics("Placebo 2: Random Filter", eq_rnd, tr_rnd, gp_rnd, gl_rnd, exp_rnd)

    logger.info("\n==================================================")
    logger.info("FAZ 14.8 — KARAR KURALI")
    logger.info("==================================================")
    if cagr_m2 > 10.0 and (gp_m2/gl_m2) > 1.10:
        logger.info("Karar: A) PRODUCTION CANDIDATE")
    else:
        logger.info("Karar: C) REJECT (M2 yetersiz kaldı)")
