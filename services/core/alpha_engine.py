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
    def __init__(self, exclude_features: List[str] = None):
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
        
        # Phase 18: Kalici olarak cope atilan gurultu gostergeler (Ablation Test sonuclari)
        default_bad_features = [
            'momentum_accel', 'roc_120d', 'dist_sma200', 
            'cs_zscore_ret_1d', 'roc_5d'
        ]
        self.exclude_features = exclude_features if exclude_features is not None else default_bad_features

    def fetch_data(self, start_date: str, end_date: str, tickers: List[str] = None) -> tuple[Dict[str, pd.DataFrame], pd.DataFrame, Dict[str, str]]:
        if tickers is None:
            tickers = bist_universe.BIST_100_TICKERS if hasattr(bist_universe, 'BIST_100_TICKERS') and bist_universe.BIST_100_TICKERS else bist_universe.BIST_ALL_TICKERS[:100]
        sector_map = {t: bist_universe.get_ticker_sector(t) for t in tickers}
        
        market_data = {}
        download_tickers = [f"{t}.IS" for t in tickers]
        try:
            raw = yf.download(
                tickers=" ".join(download_tickers),
                start=start_date,
                end=end_date,
                group_by="ticker",
                auto_adjust=True,
                progress=False,
                threads=True,
            )
            if not raw.empty:
                for t in tickers:
                    tick_sym = f"{t}.IS"
                    try:
                        if isinstance(raw.columns, pd.MultiIndex):
                            if tick_sym in raw.columns.levels[0]:
                                df_t = raw[tick_sym].dropna(how="all")
                                if not df_t.empty and len(df_t) >= 10:
                                    market_data[t] = _tz_naive(df_t)
                        else:
                            df_t = raw.dropna(how="all")
                            if not df_t.empty and len(df_t) >= 10:
                                market_data[t] = _tz_naive(df_t)
                    except Exception:
                        continue
        except Exception as e:
            logger.warning(f"AlphaEngine batch download warning: {e}")

        # Load benchmark
        try:
            bm_df = yf.download("XU100.IS", start=start_date, end=end_date, auto_adjust=True, progress=False)
            if isinstance(bm_df.columns, pd.MultiIndex):
                bm_df = bm_df.xs("XU100.IS", level=0, axis=1) if "XU100.IS" in bm_df.columns.levels[0] else bm_df
            bm_df = _tz_naive(bm_df.dropna(how="all"))
        except Exception as e:
            logger.warning(f"Benchmark download warning: {e}")
            bm_df = pd.DataFrame()
        
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
                
                # Exclude features for ablation
                if self.exclude_features:
                    for exf in self.exclude_features:
                        feats.pop(exf, None)
                
                df_fwd = market_data[ticker][(market_data[ticker].index >= t_snap) & (market_data[ticker].index <= t_fwd)]
                bm_fwd = bm_df[(bm_df.index >= t_snap) & (bm_df.index <= t_fwd)]
                
                if len(df_fwd) < 2 or len(bm_fwd) < 2: continue
                    
                p_close = df_fwd["Close"].squeeze() if hasattr(df_fwd["Close"], 'squeeze') else df_fwd["Close"]
                bm_close = bm_fwd["Close"].squeeze() if hasattr(bm_fwd["Close"], 'squeeze') else bm_fwd["Close"]
                
                try:
                    p_0 = float(p_close.iloc[0])
                    p_1 = float(p_close.iloc[-1])
                    b_0 = float(bm_close.iloc[0])
                    b_1 = float(bm_close.iloc[-1])
                except Exception:
                    continue
                
                if p_0 <= 0 or b_0 <= 0:
                    continue
                    
                excess_ret = float(((p_1 / p_0) - 1.0) - ((b_1 / b_0) - 1.0))
                
                rows.append(feats)
                labels.append(excess_ret)
                if not all_keys: all_keys = sorted(list(feats.keys()))
                    
        if not rows:
            return np.array([]), np.array([]), []
            
        X = np.array([[r.get(k, 0.0) or 0.0 for k in all_keys] for r in rows])
        y = np.array(labels)
        X = np.nan_to_num(X, nan=0.0, posinf=0.0, neginf=0.0)
        return X, y, all_keys

    def train(self, market_data, bm_df, sector_map, train_start_str: str, train_end_str: str, optimize: bool = True):
        t_start = pd.Timestamp(train_start_str)
        t_end = pd.Timestamp(train_end_str)
        X, y, feature_names = self.generate_training_samples(market_data, bm_df, sector_map, t_start, t_end)
        
        if len(X) == 0:
            logger.error("No training samples generated")
            return False
            
        self.features = feature_names
        
        if optimize:
            # Optuna ile dinamik hyperparameter tuning (TimeSeriesSplit korumali)
            from services.ml.hyper_optimizer import HyperOptimizer
            optimizer = HyperOptimizer(n_trials=20)
            best_params = optimizer.optimize(X, y, feature_names)
            
            # Bulunan en iyi parametreleri guncelle
            self.params.update(best_params)
            logger.info(f"Optuna params found: lr={self.params.get('learning_rate', 0):.3f}, leaves={self.params.get('num_leaves', 0)}, max_depth={self.params.get('max_depth', 0)}")
            
        train_data = lgb.Dataset(X, label=y, feature_name=feature_names)
        self.model = lgb.train(self.params, train_data, num_boost_round=100)
        logger.info(f"Model trained successfully on {len(X)} samples.")
        return True

    def predict(self, market_data, bm_df, sector_map, target_date_str: str):
        if not self.model:
            raise ValueError("Model not trained")
            
        target_date = pd.Timestamp(target_date_str)
        start_date_dt = target_date - pd.Timedelta(days=400)
        
        snap_md = {}
        for t, df in market_data.items():
            sub_df = df[(df.index >= start_date_dt) & (df.index <= target_date)]
            if len(sub_df) >= 120:
                snap_md[t] = sub_df
                
        snap_bm = bm_df[(bm_df.index >= start_date_dt) & (bm_df.index <= target_date)]
        if len(snap_bm) < 120:
            raise ValueError("Insufficient benchmark data for prediction")
            
        features = compute_universe_features(snap_md, snap_bm, sector_map)
        
        # Exclude features for ablation
        if self.exclude_features:
            for ticker, feats in features.items():
                for exf in self.exclude_features:
                    feats.pop(exf, None)
        
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
        start_date_dt = end_date_dt - pd.Timedelta(days=400)  # Match exactly TRAIN_DAYS=252 from validation
        
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
