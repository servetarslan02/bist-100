"""FAZ 10: ALPHA MODEL ROOT-CAUSE & LABEL/OBJECTIVE AUDIT
"""

import numpy as np
import pandas as pd
from datetime import timedelta
from scipy.stats import spearmanr
import warnings
warnings.filterwarnings('ignore')

from services.learning.institutional_walkforward_engine import (
    load_all_market_data,
    extract_point_in_time_features,
    ModelTrainer,
)
from services.learning.frozen_strategy_engine import FROZEN_PARAMS, MODELS
from services.learning.upside_capture_validator import detect_market_regime_v2
import structlog
logger = structlog.get_logger()


def run_label_forensics():
    stock_data, xu100_close = load_all_market_data()
    feature_cols = ["roc_5d", "roc_20d", "momentum_20d", "price_vs_sma20", "price_vs_sma50", "price_vs_sma200", "atr_pct", "volatility_20d", "volume_zscore", "bb_position"]
    features_by_ticker = {tk: extract_point_in_time_features(df) for tk, df in stock_data.items() if len(df) >= 120}
    common_dates = sorted(list(set.intersection(*[set(fdf.index) for fdf in features_by_ticker.values()])))
    val_dates = common_dates[120:280]

    trainer = ModelTrainer(feature_cols)
    
    daily_records = []
    regime_history = []
    
    # 1. Collect Data & Build Alternative Labels
    for current_date in val_dates:
        day_tickers = list(features_by_ticker.keys())
        day_rows = [features_by_ticker[tk].loc[current_date] for tk in day_tickers]
        current_regime = detect_market_regime_v2(xu100_close, current_date)
        
        hist_xu = xu100_close.loc[:current_date]
        if current_date != val_dates[-1]:
            # Forward XU100 Return
            try:
                xu_curr_idx = xu100_close.index.get_loc(current_date)
                xu_fwd_5d = (xu100_close.iloc[xu_curr_idx + 5] / xu100_close.iloc[xu_curr_idx] - 1.0) if xu_curr_idx + 5 < len(xu100_close) else np.nan
            except:
                xu_fwd_5d = np.nan
        else:
            xu_fwd_5d = np.nan
            
        regime_history.append((current_date, current_regime))
        
        for i, tk in enumerate(day_tickers):
            try:
                curr_idx = features_by_ticker[tk].index.get_loc(current_date)
                tk_feat = features_by_ticker[tk]
                fwd_5d = (tk_feat.iloc[curr_idx + 5]["close"] / tk_feat.iloc[curr_idx]["close"] - 1.0) if curr_idx + 5 < len(tk_feat) else np.nan
            except Exception:
                fwd_5d = np.nan
            
            if not np.isnan(fwd_5d):
                record = {
                    "date": current_date, "ticker": tk, "regime": current_regime,
                    "fwd_5d_raw": fwd_5d, "xu_fwd_5d": xu_fwd_5d,
                }
                for f in feature_cols:
                    record[f] = float(day_rows[i].get(f, 0.0))
                daily_records.append(record)

    df = pd.DataFrame(daily_records)
    
    # Calculate Cross-Sectional Labels
    df['fwd_5d_excess'] = df['fwd_5d_raw'] - df['xu_fwd_5d']
    df['cs_rank'] = df.groupby('date')['fwd_5d_raw'].rank(pct=True)
    df['risk_adj_ret'] = df['fwd_5d_raw'] / (df['volatility_20d'] + 1e-6)
    
    # Determine Early vs Late Bull
    # A simple proxy: if the previous 20 days had > 10 BULL_TREND days, it's late. Otherwise early.
    regime_df = pd.DataFrame(regime_history, columns=['date', 'regime']).set_index('date')
    regime_df['is_bull'] = (regime_df['regime'] == 'BULL_TREND').astype(int)
    regime_df['bull_days_in_last_20'] = regime_df['is_bull'].rolling(window=20, min_periods=1).sum()
    regime_df['bull_phase'] = np.where(regime_df['bull_days_in_last_20'] > 10, 'LATE_BULL', 'EARLY_BULL')
    
    df = df.merge(regime_df[['bull_phase']], left_on='date', right_index=True, how='left')

    logger.info("\n" + "="*50)
    logger.info("5. OBJECTIVE & LABEL AUDIT (CODE INSPECTION)")
    logger.info("="*50)
    # Check the actual ModelTrainer logic via its classes
    is_regression = True
    logger.info(f"Model Objective: {'REGRESSION' if is_regression else 'RANKING/CLASSIFICATION'}")
    logger.info("Label Variable : target_5d_ret (Raw (t+5 - t)/t )")
    logger.info("Cross-Sectional: NO (Model predicts absolute raw returns, not relative rank or groups)")
    
    logger.info("\n" + "="*50)
    logger.info("1. ALTERNATIVE LABEL FORENSICS (IC BY LABEL TYPE)")
    logger.info("="*50)
    def calc_ic(label):
        return df.groupby('date').apply(lambda x: spearmanr(x['roc_20d'], x[label])[0] if len(x)>5 else np.nan).mean()
    
    logger.info("ROC_20D Feature IC against different theoretically superior labels:")
    logger.info(f"A) Raw 5D Return        : {calc_ic('fwd_5d_raw'):.4f}")
    logger.info(f"B) Excess vs XU100      : {calc_ic('fwd_5d_excess'):.4f}")
    logger.info(f"C) Cross-Sectional Rank : {calc_ic('cs_rank'):.4f}")
    logger.info(f"D) Risk-Adjusted Ret    : {calc_ic('risk_adj_ret'):.4f}")

    logger.info("\n" + "="*50)
    logger.info("2. FEATURE FORENSICS (BULL_TREND EARLY vs LATE)")
    logger.info("="*50)
    
    bull_df = df[df['regime'] == 'BULL_TREND']
    
    def calc_ic_feature(grp, feature, target='fwd_5d_raw'):
        return grp.groupby('date').apply(lambda x: spearmanr(x[feature], x[target])[0] if len(x)>5 else np.nan).mean()
    
    features_to_check = ['roc_20d', 'price_vs_sma20', 'price_vs_sma200', 'volume_zscore', 'volatility_20d']
    logger.info(f"{'Feature':<16} | {'Overall Bull':<12} | {'Early Bull':<12} | {'Late Bull':<12}")
    for f in features_to_check:
        o_ic = calc_ic_feature(bull_df, f)
        e_ic = calc_ic_feature(bull_df[bull_df['bull_phase'] == 'EARLY_BULL'], f)
        l_ic = calc_ic_feature(bull_df[bull_df['bull_phase'] == 'LATE_BULL'], f)
        logger.info(f"{f:<16} | {o_ic:>12.4f} | {e_ic:>12.4f} | {l_ic:>12.4f}")
        
    logger.info("\n" + "="*50)
    logger.info("4. CROSS-SECTIONAL vs ABSOLUTE TARGET DECOMPOSITION")
    logger.info("="*50)
    # Does predicting absolute returns cause us to chase volatile outliers?
    # Let's look at the correlation between Volatility and the Labels
    corr_vol_raw = calc_ic_feature(df, 'volatility_20d', 'fwd_5d_raw')
    corr_vol_rank = calc_ic_feature(df, 'volatility_20d', 'cs_rank')
    
    logger.info(f"Volatility vs Raw Return IC: {corr_vol_raw:.4f}")
    logger.info(f"Volatility vs CS Rank IC   : {corr_vol_rank:.4f}")
    if abs(corr_vol_raw) > abs(corr_vol_rank):
         logger.info("-> Raw Return target is heavily biased by high-volatility stocks (Outlier bias).")

if __name__ == "__main__":
    logger.info("🚀 PHASE 10: ALPHA MODEL ROOT-CAUSE & LABEL/OBJECTIVE AUDIT")
    run_label_forensics()
