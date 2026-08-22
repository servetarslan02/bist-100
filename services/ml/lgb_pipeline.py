import pandas as pd
import numpy as np
import lightgbm as lgb
from typing import Dict, List, Any
import structlog

from services.ml.feature_engine import compute_universe_features

logger = structlog.get_logger()

class LightGBMPipeline:
    def __init__(self):
        self.model = None
        self.features = []
        self.params = {
            "objective": "regression",
            "metric": "rmse",
            "boosting_type": "gbdt",
            "learning_rate": 0.05,
            "num_leaves": 31,
            "max_depth": 5,
            "feature_fraction": 0.8,
            "min_data_in_leaf": 20,
            "verbose": -1,
            "random_state": 42
        }

    def generate_samples(
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
                sub_df = df[df.index <= t_snap]
                if len(sub_df) >= 120:
                    snap_md[t] = sub_df
                    
            snap_bm = bm_df[bm_df.index <= t_snap]
            if len(snap_bm) < 120:
                continue
                
            features = compute_universe_features(snap_md, snap_bm, sector_map)
            
            for ticker, feats in features.items():
                if not feats:
                    continue
                    
                df_fwd = market_data[ticker][(market_data[ticker].index >= t_snap) & (market_data[ticker].index <= t_fwd)]
                bm_fwd = bm_df[(bm_df.index >= t_snap) & (bm_df.index <= t_fwd)]
                
                if len(df_fwd) < 2 or len(bm_fwd) < 2:
                    continue
                    
                p_0 = df_fwd["Close"].iloc[0]
                p_1 = df_fwd["Close"].iloc[-1]
                b_0 = bm_fwd["Close"].iloc[0]
                b_1 = bm_fwd["Close"].iloc[-1]
                
                if p_0 <= 0 or b_0 <= 0:
                    continue
                    
                ret = (p_1 / p_0) - 1.0
                bm_ret = (b_1 / b_0) - 1.0
                excess_ret = ret - bm_ret
                
                rows.append(feats)
                labels.append(excess_ret)
                
                if not all_keys:
                    all_keys = sorted(list(feats.keys()))
                    
        if not rows:
            return np.array([]), np.array([]), []
            
        X = np.array([[r.get(k, 0.0) or 0.0 for k in all_keys] for r in rows])
        y = np.array(labels)
        
        return X, y, all_keys

    def train(
        self,
        market_data: Dict[str, pd.DataFrame],
        bm_df: pd.DataFrame,
        sector_map: Dict[str, str],
        train_start: pd.Timestamp,
        train_end: pd.Timestamp
    ):
        X, y, feature_names = self.generate_samples(
            market_data, bm_df, sector_map, train_start, train_end
        )
        
        if len(X) == 0:
            logger.warning("No training samples generated")
            return False
            
        self.features = feature_names
        train_data = lgb.Dataset(X, label=y, feature_name=feature_names)
        self.model = lgb.train(self.params, train_data, num_boost_round=100)
        return True

    def predict(
        self,
        market_data: Dict[str, pd.DataFrame],
        bm_df: pd.DataFrame,
        sector_map: Dict[str, str],
        target_date: pd.Timestamp
    ) -> List[Dict[str, Any]]:
        if not self.model:
            return []
            
        snap_md = {}
        for t, df in market_data.items():
            sub_df = df[df.index <= target_date]
            if len(sub_df) >= 120:
                snap_md[t] = sub_df
                
        snap_bm = bm_df[bm_df.index <= target_date]
        if len(snap_bm) < 120:
            return []
            
        features = compute_universe_features(snap_md, snap_bm, sector_map)
        
        predictions = []
        for ticker, feats in features.items():
            if not feats:
                continue
            x_vec = np.array([[feats.get(k, 0.0) or 0.0 for k in self.features]])
            score = self.model.predict(x_vec)[0]
            
            # Additional logic to extract important variables for confidence/ranking if needed
            predictions.append({
                "ticker": ticker,
                "score": float(score),
                "features": feats
            })
            
        # Sort by score descending
        predictions.sort(key=lambda x: x["score"], reverse=True)
        return predictions

