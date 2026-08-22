import os
import pandas as pd
import numpy as np
import lightgbm as lgb
import yfinance as yf
from datetime import datetime, timedelta
from typing import Dict, List, Any
import structlog
import traceback

from services.ingestion.bist_universe import bist_universe
from services.ml.feature_engine import compute_universe_features

logger = structlog.get_logger()

def _tz_naive(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty: return df
    df = df.copy()
    idx = pd.to_datetime(df.index)
    df.index = idx.tz_convert(None) if getattr(idx, 'tz', None) is not None else idx
    return df

class AlphaEngine:
    def __init__(self):
        self.params = {
            "objective": "regression",
            "metric": "rmse",
            "n_estimators": 100,
            "learning_rate": 0.05,
            "max_depth": 3,
            "num_leaves": 7,
            "verbose": -1,
            "n_jobs": -1
        }
        self.model = None
        self.features = []

    def fetch_data(self, start_date: str, end_date: str) -> tuple[Dict[str, pd.DataFrame], pd.DataFrame, Dict[str, str]]:
        tickers = bist_universe.BIST_100_TICKERS
        sector_map = {t: bist_universe.get_ticker_sector(t) for t in tickers}
        
        # Load stocks
        market_data = {}
        for ticker in tickers:
            try:
                df = yf.Ticker(f"{ticker}.IS").history(start=start_date, end=end_date)
                if not df.empty:
                    market_data[ticker] = _tz_naive(df)
            except Exception as e:
                logger.warning(f"Failed to fetch {ticker}", error=str(e))
                
        # Load benchmark
        bm_df = yf.Ticker("XU100.IS").history(start=start_date, end=end_date)
        bm_df = _tz_naive(bm_df)
        
        return market_data, bm_df, sector_map

    def generate_training_samples(
        self,
        market_data: Dict[str, pd.DataFrame],
        bm_df: pd.DataFrame,
        sector_map: Dict[str, str],
        train_start: pd.Timestamp,
        train_end: pd.Timestamp,
        snapshot_offsets: List[int] = [20, 40, 60, 80],
        forward_days: int = 20
    ):
        rows = []
        labels = []
        all_keys = []
        
        for offset in snapshot_offsets:
            t_snap = train_end - pd.Timedelta(days=int(offset))
            t_fwd  = t_snap + pd.Timedelta(days=int(forward_days))
            
            if t_snap < train_start:
                continue
                
            snap_md = {}
            for t, df in market_data.items():
                sub_df = df[(df.index >= train_start) & (df.index <= t_snap)]
                if len(sub_df) >= 120:
                    snap_md[t] = sub_df
                    
            snap_bm = bm_df[(bm_df.index >= train_start) & (bm_df.index <= t_snap)]
            if len(snap_bm) < 120:
                continue
                
            features = compute_universe_features(snap_md, snap_bm, sector_map)
            
            for ticker, feats in features.items():
                if not feats: continue
                if ticker not in market_data: continue
                
                df_fwd = market_data[ticker][(market_data[ticker].index >= t_snap) & (market_data[ticker].index <= t_fwd)]
                bm_fwd = bm_df[(bm_df.index >= t_snap) & (bm_df.index <= t_fwd)]
                
                if len(df_fwd) < 2 or len(bm_fwd) < 2: continue
                    
                p_0, p_1 = df_fwd["Close"].iloc[0], df_fwd["Close"].iloc[-1]
                b_0, b_1 = bm_fwd["Close"].iloc[0], bm_fwd["Close"].iloc[-1]
                
                if p_0 <= 0 or b_0 <= 0: continue
                    
                excess_ret = ((p_1 / p_0) - 1.0) - ((b_1 / b_0) - 1.0)
                
                rows.append(feats)
                labels.append(excess_ret)
                if not all_keys: all_keys = sorted(list(feats.keys()))
                    
        if not rows:
            return np.array([]), np.array([]), []
            
        X = np.array([[r.get(k, 0.0) or 0.0 for k in all_keys] for r in rows])
        y = np.array(labels)
        X = np.nan_to_num(X, nan=0.0, posinf=0.0, neginf=0.0)
        return X, y, all_keys

    def train(self, market_data, bm_df, sector_map, train_start_str: str, train_end_str: str):
        t_start = pd.Timestamp(train_start_str)
        t_end = pd.Timestamp(train_end_str)
        X, y, feature_names = self.generate_training_samples(market_data, bm_df, sector_map, t_start, t_end)
        
        if len(X) == 0:
            logger.error("No training samples generated")
            return False
            
        self.features = feature_names
        train_data = lgb.Dataset(X, label=y, feature_name=feature_names)
        self.model = lgb.train(self.params, train_data, num_boost_round=100)
        logger.info(f"Model trained successfully on {len(X)} samples.")
        return True

    def predict(self, market_data, bm_df, sector_map, target_date_str: str):
        if not self.model:
            raise ValueError("Model not trained")
            
        target_date = pd.Timestamp(target_date_str)
        start_date_dt = target_date - pd.Timedelta(days=252)
        
        snap_md = {}
        for t, df in market_data.items():
            sub_df = df[(df.index >= start_date_dt) & (df.index <= target_date)]
            if len(sub_df) >= 120:
                snap_md[t] = sub_df
                
        snap_bm = bm_df[(bm_df.index >= start_date_dt) & (bm_df.index <= target_date)]
        if len(snap_bm) < 120:
            raise ValueError("Insufficient benchmark data for prediction")
            
        features = compute_universe_features(snap_md, snap_bm, sector_map)
        
        predictions = []
        for ticker, feats in features.items():
            if not feats: continue
            x_vec = np.array([[feats.get(k, 0.0) or 0.0 for k in self.features]])
            x_vec = np.nan_to_num(x_vec, nan=0.0, posinf=0.0, neginf=0.0)
            score = float(self.model.predict(x_vec)[0])
            predictions.append({
                "ticker": ticker,
                "score": score,
                "features": feats
            })
            
        predictions.sort(key=lambda x: x["score"], reverse=True)
        return predictions

    def run_daily_pipeline(self, date: str):
        """Run daily production logic"""
        end_date_dt = pd.Timestamp(date)
        start_date_dt = end_date_dt - pd.Timedelta(days=252)  # Match exactly TRAIN_DAYS=252 from validation
        
        market_data, bm_df, sector_map = self.fetch_data(
            start_date_dt.strftime('%Y-%m-%d'), 
            end_date_dt.strftime('%Y-%m-%d')
        )
        
        success = self.train(
            market_data, bm_df, sector_map, 
            start_date_dt.strftime('%Y-%m-%d'), 
            date
        )
        if not success:
            return None
            
        top_picks = self.predict(market_data, bm_df, sector_map, date)
        return top_picks
